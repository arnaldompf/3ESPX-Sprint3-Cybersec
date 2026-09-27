"""WP-10 — extração estruturada: fast-path, provedor de LLM e orquestração.

Os três critérios de aceite da spec, mais as regressões dos defeitos que a sonda achou
nos regexes de `docs/12` §6.8. Tudo com `LLM_FAKE=1`: nenhuma chamada de rede.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import llm
from pipeline.eval.compare import comparar_qualquer, grounding
from pipeline.eval.gabarito import carregar_gabarito
from pipeline.extract import fastpath, prompt
from pipeline.extract.run import (
    Documento,
    extrair_documento,
    extrair_fontes,
    montar_prompt,
    planejar_chamadas,
)
from pipeline.parse.pdf import DocumentoPdf, Tabela
from pipeline.parse.version_slicer import recortar
from pipeline.store import FIXTURES, snapshots_de

ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "gabarito" / "raw"
FIXTURES_PDF = ROOT / "tests" / "fixtures" / "pdf" / "toyota_hilux_my26"


@pytest.fixture(scope="module")
def texto_raptor() -> str:
    """Página da versão + ficha técnica + registro de evidências, como o pipeline vê."""
    partes = [
        (RAW / "ford_raptor_site_versao.md").read_text(encoding="utf-8"),
        (RAW / "ford_raptor_ficha_tecnica_oficial.txt").read_text(encoding="utf-8"),
        (RAW / "manus_raptor.json").read_text(encoding="utf-8"),
    ]
    return "\n\n".join(partes)


@pytest.fixture(scope="module")
def pdf_hilux() -> DocumentoPdf:
    dados = json.loads((FIXTURES_PDF / "tables.json").read_text(encoding="utf-8"))
    md = (FIXTURES_PDF / "doc.md").read_text(encoding="utf-8")
    return DocumentoPdf(
        md, md.split("\n\n"), [Tabela.from_dict(t) for t in dados["tabelas"]], dados["motor"]
    )


# ------------------------------------------------------------ critérios de aceite
def test_raptor_retorna_397_transmissao_e_quatro_modos(texto_raptor):
    """Critério 1: potencia_cv, transmissão e modos_direcao, cada um com quote."""
    campos = {"potencia_cv", "tipo", "numero_marchas", "paddle_shifters", "modos_direcao"}
    resultado = fastpath.extrair(texto_raptor, campos=campos)

    valores = {a.campo: a.valor for a in resultado.achados}
    assert valores["potencia_cv"] == 397
    assert valores["tipo"] == "automatica"
    assert valores["numero_marchas"] == 10
    assert valores["paddle_shifters"] is True
    assert len(valores["modos_direcao"]) == 4

    for achado in resultado.achados:
        assert achado.quote.strip(), f"{achado.campo} sem quote"
        assert grounding(achado.quote, texto_raptor).ok, f"{achado.campo}: quote não grounda"


def test_aceleracao_declarada_fica_com_a_citacao_que_prova_declarado(texto_raptor):
    """Defeito real: o registro repete "5,8" em três linhas (`valor_bruto`,
    `valor_normalizado`, `trecho`), e todas estão a alcance da âncora "0 a 100". Sem
    escolher a mais rica, a ordem de `finditer` podia entregar a citação pobre ("5,8 s"),
    e `claim_type.classificar` não tinha "declara" nem "medi/teste" para ler — a tela
    perdia o rótulo "declarado" que o próprio módulo `claim_type` existe para mostrar.
    """
    from pipeline import claim_type

    achados = fastpath.extrair_aceleracao_por_proximidade(
        texto_raptor, campos={"aceleracao_0_100_s"}
    )
    por_valor = {a.valor: a for a in achados}
    assert por_valor.keys() == {5.8, 6.5}

    tipo_5_8, _ = claim_type.classificar(por_valor[5.8].quote, raw_value=por_valor[5.8].valor_bruto)
    assert tipo_5_8 == "declarado", por_valor[5.8].quote

    tipo_6_5, _ = claim_type.classificar(por_valor[6.5].quote, raw_value=por_valor[6.5].valor_bruto)
    assert tipo_6_5 == "medido", por_valor[6.5].quote


def test_atributo_inexistente_no_texto_nao_vira_valor():
    """Critério 2: nunca valor sem quote — campo ausente simplesmente não aparece."""
    resultado = fastpath.extrair(
        "Uma picape muito bonita, sem nenhum número.",
        campos={"potencia_cv", "torque_nm", "capacidade_reboque_kg"},
    )
    assert resultado.achados == []
    assert resultado.fastpath_rate == 0.0
    assert set(resultado.campos_para_o_llm) == {
        "potencia_cv",
        "torque_nm",
        "capacidade_reboque_kg",
    }


def test_escalonamento_para_o_modelo_grande_tem_motivo():
    """Critério 3: > 3 tabelas ou ≥ 30% de nulos escala, e o motivo fica registrado."""
    escalar, motivo = prompt.deve_escalar(campos_pedidos=10, campos_nulos=0, n_tabelas=6)
    assert escalar and "6 tabelas" in motivo

    escalar, motivo = prompt.deve_escalar(campos_pedidos=10, campos_nulos=3, n_tabelas=1)
    assert escalar and "30%" in motivo

    escalar, motivo = prompt.deve_escalar(campos_pedidos=10, campos_nulos=2, n_tabelas=1)
    assert not escalar and motivo == ""


def test_pipeline_escala_e_registra_o_motivo(pdf_hilux):
    """O escalonamento acontece de verdade na orquestração, não só na regra."""
    documento = Documento(
        texto=pdf_hilux.markdown[:5000],
        source_id="toyota_pdf_my26",
        tier=1,
        n_tabelas=len(pdf_hilux.tabelas),
    )
    resultado = extrair_documento(documento, {"capacidade_reboque_kg", "garantia_meses"})
    assert resultado.escalou
    assert resultado.motivo_do_escalonamento
    assert resultado.custo_brl == 0.0, "LLM_FAKE=1: custo real zero, não estimado"


# ------------------------------------------- regressões dos regexes de docs/12 §6.8
def test_dez_velocidades_nao_vira_zero():
    """Defeito real: `(\\d)\\s?(velocidades)` casava "0 velocidades" em "10 velocidades".

    O valor errado vinha com quote que **grounda** ("0 velocidades" é substring), então
    passaria por todos os portões do projeto. É o pior tipo de defeito aqui.
    """
    achados = fastpath.extrair_de_texto(
        "Câmbio automático de 10 velocidades", campos={"numero_marchas"}
    )
    assert [a.valor for a in achados] == [10]


def test_zero_a_cem_nao_vira_velocidade_maxima_de_cem():
    """O ``100 km/h`` da aceleracao nao e a velocidade maxima do veiculo."""
    achados = fastpath.extrair_de_texto(
        "Aceleracao de 0 a 100 km/h: 10,4 s", campos={"velocidade_maxima_kmh"}
    )
    assert achados == []


def test_velocidade_maxima_explicitamente_rotulada_continua_sendo_lida():
    achados = fastpath.extrair_de_texto(
        "Velocidade m\u00e1xima: 190 km/h", campos={"velocidade_maxima_kmh"}
    )
    assert [a.valor for a in achados] == [190]


def test_ficha_em_linhas_rotulo_dois_pontos_preenche_dimensoes_consumo_e_chassi():
    texto = """Comprimento: 5,285 m
Largura: 1,820 m
Entre-eixos: 3,000 m
Altura: 1,795 m
Tanque de combustivel: 76 litros
Consumo urbano: 9,3 km/l
Consumo rodoviario: 10,3 km/l
Suspensao dianteira: Independente, bracos sobrepostos
Suspensao traseira: Eixo rigido, feixe de molas
Freios dianteiros: Discos ventilados
Freios traseiros: Tambor
Direcao: Hidraulica"""
    resultado = fastpath.extrair(
        texto,
        campos={
            "comprimento_mm",
            "largura_mm",
            "entre_eixos_mm",
            "altura_mm",
            "tanque_l",
            "consumo_urbano_kml",
            "consumo_rodoviario_kml",
            "suspensao_dianteira",
            "suspensao_traseira",
            "freios_dianteiros",
            "freios_traseiros",
            "direcao",
        },
    )
    valores = {a.campo: a.valor for a in resultado.achados}
    assert valores == {
        "comprimento_mm": 5285,
        "largura_mm": 1820,
        "entre_eixos_mm": 3000,
        "altura_mm": 1795,
        "tanque_l": 76,
        "consumo_urbano_kml": 9.3,
        "consumo_rodoviario_kml": 10.3,
        "suspensao_dianteira": "Independente, bracos sobrepostos",
        "suspensao_traseira": "Eixo rigido, feixe de molas",
        "freios_dianteiros": "Discos ventilados",
        "freios_traseiros": "Tambor",
        "direcao": "Hidraulica",
    }


def test_preco_com_marcador_de_nota_nao_vira_milhoes():
    """Defeito real: o texto salvo da Ford tem "R$ 499.0002" (marcador colado)."""
    achados = fastpath.extrair_de_texto("R$ 499.0002", campos={"preco_sugerido_brl"})
    assert [a.valor for a in achados] == [499000]
    assert "marcador de nota" in achados[0].notas
    assert achados[0].quote == "R$ 499.0002", "o quote é verbatim, mesmo com o marcador"


def test_preco_grande_de_verdade_nao_e_reinterpretado():
    """A regra do marcador só vale quando a leitura direta é implausível."""
    achados = fastpath.extrair_de_texto("R$ 1.234.567", campos={"preco_sugerido_brl"})
    assert [a.valor for a in achados] == [1234567]
    assert not achados[0].notas


def test_primeiro_modo_da_lista_nao_e_cortado():
    """Defeito real: o preenchimento guloso comia " selecionáveis – Nor" e virava "mal"."""
    achados = fastpath.extrair_modos(
        "7 modos de condução selecionáveis – Normal, Esportivo, Escorregadio, Lama/Terra",
        campos={"modos_conducao"},
    )
    assert achados
    assert achados[0].valor[0] == "normal"


def test_lama_terra_e_um_modo_so():
    """`/` não separa: a ontologia resolve "lama/terra" para `lama`.

    Separar acrescentaria um `terra` que não existe, e a lista da Raptor passaria a ter 8
    itens onde o gabarito tem 7.
    """
    achados = fastpath.extrair_modos(
        "modos de condução: Normal, Lama/Terra, Areia", campos={"modos_conducao"}
    )
    assert achados[0].valor == ["normal", "lama", "areia"]


def test_modo_quebrado_em_duas_linhas_pelo_pdf_nao_perde_o_resto_da_lista():
    """Defeito real na ficha da Raptor: o PDF quebra a linha em "Lama/" e continua em
    "Terra, Areia, Baja, Rock Crawl" na linha seguinte. O regex não cruza `\\n`, então
    parava em "Lama/" e devolvia 4 dos 7 modos — a página do site tem os 7, e a lista
    truncada virava divergência inventada contra uma fonte que concorda.
    """
    texto = (RAW / "ford_raptor_ficha_tecnica_oficial.txt").read_text(encoding="utf-8")
    achados = fastpath.extrair_modos(texto, campos={"modos_conducao"})
    assert achados
    assert achados[0].valor == [
        "normal",
        "sport",
        "escorregadio",
        "lama",
        "areia",
        "baja",
        "rock_crawl",
    ]
    assert grounding(achados[0].quote, texto).ok


def test_lista_sem_separador_e_cortada_na_proxima_coluna():
    """A Toyota escreve "Modos de seleção de condução Eco e Power" seguido da tabela."""
    achados = fastpath.extrair_modos(
        "• Modos de seleção de condução Eco e Power - •     •        •",
        campos={"modos_conducao"},
    )
    assert achados
    assert achados[0].valor == ["eco", "power"]


def test_farol_por_assinatura_em_led_sem_a_palavra_farol_por_perto():
    """Defeito real na página da S10: "a assinatura em LED" descreve o frontal do
    veículo (ao lado de "frente robusta" e "capô elevado"), mas nunca escreve a palavra
    "farol"/"faróis" — só regras que exigem esse termo ao lado do LED perdiam o campo,
    mesmo com prova oficial (tier 1) de que o farol é LED.
    """
    texto = (
        "A Chevrolet S10 revela sua força e imponência com uma frente robusta e capô "
        "elevado, além das linhas diferenciadas e da assinatura em LED."
    )
    achados = fastpath.extrair_farol_por_assinatura(texto, campos={"farois_tipo"})
    assert achados
    assert achados[0].valor == "LED"
    assert grounding(achados[0].quote, texto).ok


def test_assinatura_em_led_da_lanterna_traseira_nao_vira_farol():
    """ "Assinatura em LED" também é frase comum para a lanterna traseira — sem campo
    próprio para lanterna, aceitar isso como farol seria atribuir ao dianteiro um dado
    que a fonte deu do traseiro.
    """
    texto = "A lanterna traseira tem assinatura em LED, com efeito 3D."
    achados = fastpath.extrair_farol_por_assinatura(texto, campos={"farois_tipo"})
    assert achados == []


def test_ficha_da_toyota_precisa_da_regra_por_rotulo(pdf_hilux):
    """Defeito real: nenhum regex inline casa a ficha da Toyota.

    A unidade está no cabeçalho da linha ("Torque (kgf.m/rpm)"), não junto do número, e
    é a única fonte do projeto que publica rpm.
    """
    inline = fastpath.extrair_de_texto(
        pdf_hilux.markdown, campos={"torque_nm", "potencia_cv", "torque_rpm"}
    )
    assert not [a for a in inline if a.campo == "torque_rpm"]

    celulas = recortar(pdf_hilux, "SRX Plus AT").celulas
    por_rotulo = fastpath.extrair_de_celulas(celulas, campos={"torque_nm", "torque_rpm"})
    valores = {a.campo: a.valor for a in por_rotulo}
    assert valores["torque_nm"] == 499, "50,9 kgf.m convertido"
    assert valores["torque_rpm"] == 2800


def test_fastpath_por_rotulo_pega_a_coluna_da_versao_alvo(pdf_hilux):
    """A regra de composição do módulo: célula recortada, nunca página inteira.

    Na página, a linha de torque é "42,8 / 3.400   50,9 / 2.800" — o primeiro valor é da
    STD Power Pack MT. Atribuí-lo à SRX Plus seria a inferência proibida.
    """
    celulas = recortar(pdf_hilux, "SRX Plus AT").celulas
    valores = [a.valor for a in fastpath.extrair_de_celulas(celulas, campos={"torque_nm"})]
    assert 499 in valores
    assert 420 not in valores, "42,8 kgf.m é da versão manual, não da SRX Plus"


def test_torque_em_kgfm_com_rpm_extrai_o_par():
    """Defeito real: o regex de torque em kgfm não tinha `extras` de rpm, então perdia
    `torque_rpm` mesmo quando a fonte publica os dois juntos — ao contrário do formato em
    Nm, que já tinha a regra `torque_nm_com_rpm`. Trecho real, tier 3 (Webmotors, VW Amarok
    V6 Extreme 2026, `reports/quality/before-after.json`): "59,1 kgfm a 1400 rpm".
    """
    texto = "| Torque | 59,1 kgfm a 1400 rpm (D) |"
    achados = fastpath.extrair_de_texto(texto, campos={"torque_nm", "torque_rpm"})
    valores = {a.campo: a.valor for a in achados}
    assert valores["torque_nm"] == 580, "59,1 kgfm convertido"
    assert valores["torque_rpm"] == 1400
    for achado in achados:
        assert grounding(achado.quote, texto).ok


def test_numero_marchas_sai_da_celula_de_transmissao_da_tabela(pdf_hilux):
    """Defeito real: a célula de "Transmissão" ("Automática de 6 velocidades sequencial",
    coluna SRX Plus AT da ficha oficial da Hilux) preenche `tipo`, mas o rótulo de tabela
    só mapeia para **um** campo — `numero_marchas` nunca sai da mesma célula, mesmo estando
    ali, verbatim.
    """
    celulas = recortar(pdf_hilux, "SRX Plus AT").celulas
    achados = fastpath.extrair_de_celulas(celulas, campos={"numero_marchas"})
    valores = {a.campo: a.valor for a in achados}
    assert valores.get("numero_marchas") == 6
    for achado in achados:
        assert achado.campo != "numero_marchas" or grounding(achado.quote, pdf_hilux.markdown).ok


def test_amortecedores_aceita_descricao_da_suspensao_sem_amortecedor_especifico(pdf_hilux):
    """Decisão do dono: `amortecedores` aceita a descrição da suspensão quando a fonte não
    descreve o amortecedor em si. Caso real: a ficha oficial da Hilux descreve a geometria
    da suspensão dianteira/traseira e nunca escreve a palavra "amortecedor" — sem esta
    regra o campo fica `nao_encontrado` numa fonte tier 1 que na verdade responde.
    """
    celulas = recortar(pdf_hilux, "SRX Plus AT").celulas
    achados = fastpath.extrair_de_celulas(
        celulas, campos={"amortecedores"}, texto=pdf_hilux.markdown
    )
    valores = [a.valor for a in achados if a.campo == "amortecedores"]
    assert (
        "Independente, braços duplos triangulares, molas helicoidais e barra estabilizadora"
        in valores
    )
    for achado in achados:
        assert grounding(achado.quote, pdf_hilux.markdown).ok


def test_quote_de_celula_encurta_ate_ser_contiguo(pdf_hilux):
    """Célula que quebra de linha não é substring literal do texto com layout.

    O valor da suspensão traseira tem 11 palavras reconstruídas pela grade, e só as 7
    primeiras são contíguas no texto. Encurtar o quote mantém a regra ("trecho verbatim")
    em vez de afrouxá-la, e o valor segue completo.
    """
    valor = "Eixo rígido, molas semielípticas de duplo estágio e barra estabilizadora"
    assert not grounding(valor, pdf_hilux.markdown).ok
    quote = fastpath.quote_de_celula(valor, pdf_hilux.markdown)
    assert quote != valor
    assert valor.startswith(quote)
    assert grounding(quote, pdf_hilux.markdown).ok


def test_quote_de_celula_sem_texto_devolve_o_valor():
    assert fastpath.quote_de_celula("qualquer coisa") == "qualquer coisa"


def test_achado_sem_quote_e_rejeitado_na_construcao():
    with pytest.raises(ValueError, match="sem quote"):
        fastpath.Achado(campo="potencia_cv", valor=397, valor_bruto="397", quote="  ")


def test_quote_respeita_o_limite_de_25_palavras():
    linha = " ".join(f"palavra{i}" for i in range(60)) + " 397cv"
    achados = fastpath.extrair_de_texto(linha, campos={"potencia_cv"})
    assert achados
    assert len(achados[0].quote.split()) <= fastpath.MAX_PALAVRAS_QUOTE
    assert achados[0].quote in linha, "a janela tem de continuar sendo trecho contíguo"


# ------------------------------------------------------------------ provedor de LLM
def test_llm_fake_sem_fixture_nao_inventa():
    resposta = llm.extrair_json(prompt="pergunta que ninguém gravou", campos=["potencia_cv"])
    assert not resposta.ok
    assert resposta.dados == {}
    assert "não há fixture" in resposta.motivo
    assert resposta.uso.custo_brl == 0.0


def test_llm_fake_le_a_fixture_gravada(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "FIXTURES_LLM", tmp_path)
    corpo = "prompt de teste"
    campos = ["potencia_cv"]
    chave = llm.chave_de_fixture(modelo=llm.modelo_pequeno(), prompt=corpo, campos=campos)
    llm.gravar_fixture(
        chave,
        {
            "potencia_cv": {
                "raw_value": "397cv",
                "value": 397,
                "unit": "cv",
                "evidence_quote": "Potencia 397cv",
            }
        },
        meta={"origem": "teste"},
    )
    resposta = llm.extrair_json(prompt=corpo, campos=campos)
    assert resposta.ok
    assert resposta.dados["potencia_cv"]["value"] == 397
    assert resposta.uso.de_fixture
    assert resposta.uso.custo_brl == 0.0


def test_chave_de_fixture_muda_com_o_prompt():
    a = llm.chave_de_fixture(modelo="m", prompt="texto A", campos=["x"])
    b = llm.chave_de_fixture(modelo="m", prompt="texto B", campos=["x"])
    c = llm.chave_de_fixture(modelo="m", prompt="texto A", campos=["y"])
    assert len({a, b, c}) == 3


def test_custo_e_estimativa_declarada():
    uso = llm.Uso("claude-haiku-4-5-20251001", tokens_entrada=1_000_000, tokens_saida=0)
    assert uso.custo_usd > 0
    assert uso.to_dict()["custo_e_estimativa"] is True
    de_fixture = llm.Uso("claude-haiku-4-5-20251001", de_fixture=True)
    assert de_fixture.custo_usd == 0.0
    assert de_fixture.to_dict()["custo_e_estimativa"] is False


def test_sem_chave_e_sem_fake_nao_chama_nada(monkeypatch):
    """Sem chave e sem modo fake, o provedor **não chama nada** e diz por quê.

    O teste limpa toda chave conhecida, e não só a da Anthropic: apagar uma variável e
    deixar as outras já deixou este teste sair para a rede de verdade quando o `.env` da
    máquina apontou para outro provedor (ver `_desarma_provedor_real` no `conftest`).
    """
    monkeypatch.setenv("LLM_FAKE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    for nome in {"LLM_API_KEY", *(env for p in llm.PROVEDORES.values() for env in p.envs)}:
        monkeypatch.delenv(nome, raising=False)
    resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
    assert not resposta.ok
    assert "ANTHROPIC_API_KEY ausente" in resposta.motivo
    assert resposta.dados == {}


# ---------------------------------------------------------------------- prompt
def test_prompt_carrega_as_regras_inviolaveis():
    for regra in (
        "SOMENTE o que está escrito",
        "ATÉ 25 PALAVRAS",
        "Não parafraseie",
        "VÁRIAS versões",
        "não invente",
    ):
        assert regra.lower() in prompt.SISTEMA.lower(), regra


def test_prompt_do_usuario_nomeia_a_versao_e_os_campos():
    corpo = prompt.montar(
        texto="Potencia 397cv",
        campos=["potencia_cv", "modos_direcao"],
        marca="Ford",
        modelo="Ranger",
        versao="Raptor 3.0 V6 Bi-turbo 4WD AT",
        fonte="https://exemplo.test",
    )
    assert "Raptor 3.0 V6 Bi-turbo 4WD AT" in corpo
    assert '"potencia_cv"' in corpo
    assert '"modos_direcao"' in corpo
    assert "lista de strings" in corpo
    assert "Potencia 397cv" in corpo
    assert "https://exemplo.test" in corpo


def test_versao_do_prompt_e_registrada():
    assert prompt.VERSAO_DO_PROMPT


# ------------------------------------------------------------------ orquestração
def test_fastpath_resolve_antes_do_llm(texto_raptor):
    documento = Documento(texto=texto_raptor, source_id="ford", tier=1)
    resultado = extrair_documento(documento, {"potencia_cv", "torque_nm"})
    assert resultado.campos_do_fastpath == {"potencia_cv", "torque_nm"}
    assert resultado.usos == [], "campo resolvido por regex não vai ao LLM"
    assert resultado.fastpath_rate == 1.0


def test_candidatos_de_varias_fontes_sao_todos_preservados():
    """Reconciliação (WP-12) precisa ver todos para poder marcar `divergente`."""
    docs = [
        Documento(texto="Potencia 397cv", source_id="a", tier=1),
        Documento(texto="Potencia 400cv", source_id="b", tier=3),
    ]
    resultado = extrair_fontes(docs, {"potencia_cv"})
    valores = {c.valor for c in resultado.por_campo("potencia_cv")}
    assert valores == {397, 400}, "nenhum candidato pode ser descartado aqui"
    assert {c.tier for c in resultado.por_campo("potencia_cv")} == {1, 3}


def test_candidato_carrega_a_proveniencia():
    documento = Documento(
        texto="Potencia 397cv",
        source_id="ford_site",
        url="https://exemplo.test/raptor",
        tier=1,
        captured_at="2026-09-01",
    )
    candidato = extrair_documento(documento, {"potencia_cv"}).por_campo("potencia_cv")[0]
    assert candidato.source_id == "ford_site"
    assert candidato.url == "https://exemplo.test/raptor"
    assert candidato.tier == 1
    assert candidato.captured_at == "2026-09-01"
    assert candidato.do_fastpath


def test_permitir_llm_false_avisa_o_que_ficou_de_fora():
    documento = Documento(texto="Potencia 397cv", source_id="a", tier=1)
    resultado = extrair_documento(
        documento, {"potencia_cv", "capacidade_reboque_kg"}, permitir_llm=False
    )
    assert resultado.usos == []
    assert any("LLM desativado" in a for a in resultado.avisos)


def test_planejar_chamadas_nao_chama_nada_e_bate_a_chave():
    """O gravador de fixtures depende de a chave planejada ser a mesma que o pipeline usa."""
    documento = Documento(texto="Potencia 397cv", source_id="a", tier=1)
    planos = planejar_chamadas(documento, {"potencia_cv", "capacidade_reboque_kg"})
    assert planos
    assert all("potencia_cv" not in p.campos for p in planos), "o fast-path já resolveu"
    corpo = montar_prompt(documento, list(planos[0].campos))
    assert planos[0].chave == llm.chave_de_fixture(
        modelo=planos[0].modelo, prompt=corpo, campos=list(planos[0].campos)
    )


def test_planejar_nao_planeja_nada_quando_o_fastpath_resolve_tudo():
    documento = Documento(texto="Potencia 397cv", source_id="a", tier=1)
    assert planejar_chamadas(documento, {"potencia_cv"}) == []


# --------------------------------------------------- medida contra o gabarito
@pytest.mark.slow
def test_extracao_atinge_a_meta_de_field_accuracy(pdf_hilux):
    """A medida que interessa: valor certo **e** quote groundável, contra o gabarito.

    É a mesma conta que `field_accuracy` de `docs/09` faz, feita aqui sem passar pelo
    eval, para que a WP-10 tenha um portão próprio.

    **Campos de serviço ficam fora**, e não é para maquiar o número: eles não passam por
    aqui. `preco_fipe_brl`, `fipe_referencia` e o consumo do PBE vêm de conector — a FIPE
    de uma resposta de API e o consumo da coluna de uma tabela cuja linha não tem a
    palavra "km/l". Nenhuma regra de texto os resolve, por desenho
    (`pipeline/run.py`: `CAMPOS_DE_SERVICO`, `consultar_consumo`). Medi-los num portão do
    **fast-path** é medir a ausência de uma regra que não deve existir: com a Ranger
    Limited no gabarito v1.1, que tem os três, a taxa caiu de 0,952 para 0,881 sem que
    nenhuma regra tivesse piorado. Quem mede o pipeline inteiro é `make eval`.
    """
    fora_do_fastpath = {
        "preco_fipe_brl",
        "fipe_referencia",
        "consumo_urbano_kml",
        "consumo_rodoviario_kml",
    }
    gab = carregar_gabarito()
    acertos = medidos = 0
    for veiculo in gab.veiculos_com_atributos:
        snaps = snapshots_de(veiculo.id, FIXTURES)
        docs = []
        for s in snaps:
            celulas = ()
            if s.source_id == "toyota_pdf_my26_completo":
                celulas = tuple(recortar(pdf_hilux, veiculo.versao).celulas)
            docs.append(
                Documento(
                    texto=s.texto,
                    source_id=s.source_id,
                    url=s.url,
                    tier=s.tier,
                    captured_at=s.captured_at,
                    celulas=celulas,
                    n_tabelas=len(pdf_hilux.tabelas),
                )
            )
        alvo = {c.campo for c in veiculo.campos}
        resultado = extrair_fontes(
            docs,
            alvo,
            marca=veiculo.marca,
            modelo_veiculo=veiculo.modelo,
            versao=veiculo.versao,
        )
        textos = {s.source_id: s.texto for s in snaps}
        for campo in veiculo.campos:
            if not campo.avalia_valor or campo.campo in fora_do_fastpath:
                continue
            medidos += 1
            acertos += int(
                any(
                    comparar_qualquer(campo.campo, campo.valores_esperados, c.valor).igual
                    and grounding(c.quote, textos.get(c.source_id, "")).ok
                    for c in resultado.por_campo(campo.campo)
                )
            )
    taxa = acertos / medidos
    assert taxa >= 0.90, f"field_accuracy {taxa:.3f} ({acertos}/{medidos}) abaixo da meta"


@pytest.mark.slow
def test_nenhum_candidato_sem_grounding(pdf_hilux):
    """`grounding_rate` tem de ser 1,0: todo valor afirmado tem trecho localizável."""
    gab = carregar_gabarito()
    sem_grounding = []
    for veiculo in gab.veiculos_com_atributos:
        snaps = snapshots_de(veiculo.id, FIXTURES)
        textos = {s.source_id: s.texto for s in snaps}
        docs = []
        for s in snaps:
            celulas = ()
            if s.source_id == "toyota_pdf_my26_completo":
                celulas = tuple(recortar(pdf_hilux, veiculo.versao).celulas)
            docs.append(
                Documento(
                    texto=s.texto,
                    source_id=s.source_id,
                    url=s.url,
                    tier=s.tier,
                    celulas=celulas,
                )
            )
        resultado = extrair_fontes(docs, {c.campo for c in veiculo.campos})
        for candidato in resultado.candidatos:
            if not grounding(candidato.quote, textos.get(candidato.source_id, "")).ok:
                sem_grounding.append(f"{veiculo.id}/{candidato.campo}: {candidato.quote[:50]!r}")
    assert not sem_grounding, "valores sem evidência localizável:\n" + "\n".join(sem_grounding[:10])


# ------------------------------------------- ficha de PDF em colunas: o vão entre A e B
#
# Um avaliador olhou a ficha da Raptor em 12/09/2026 e viu **Dimensões e capacidades 0 de
# 7** — todos `nao_encontrado`. Os valores estão no PDF oficial já salvo, escritos assim:
#
#     Capacidade de carga (kg)                        715
#     Tanque de combustível (L)                        77
#     Comprimento do veículo (mm)                    5381
#
# e os seis rótulos já estão em `ROTULO_PARA_CAMPO`. Eles se perdiam num **vão entre os
# dois mecanismos de extração**, e o vão era silencioso:
#
# * o recorte por coluna (`version_slicer`) exige uma grade (`tables.json`) ao lado do
#   documento, e só um snapshot do repositório tem uma;
# * o par rótulo/valor (`pares_de_rotulo`) **desiste de propósito** quando o texto tem
#   layout de colunas — e com razão: naquele formato a linha percorre todas as versões, e
#   ler a primeira coluna daria à Hilux SRX Plus o número da STD.
#
# O que faltava era o terceiro caso: layout de colunas **com uma versão só**, em que rótulo
# e valor estão na mesma linha e não há ambiguidade nenhuma.
class TestFichaEmColunas:
    def _doc_da_raptor(self) -> str:
        return Path(
            "tests/fixtures/snapshots/ford_ranger_raptor_2026/"
            "2026-09-01T00-00-00Z/ford_ficha_tecnica/doc.md"
        ).read_text(encoding="utf-8")

    def test_a_raptor_responde_dimensoes_e_capacidades(self):
        texto = self._doc_da_raptor()
        achados = {a.campo: a for a in fastpath.extrair_de_pares(texto)}

        assert achados["comprimento_mm"].valor == 5381
        assert achados["entre_eixos_mm"].valor == 3270
        assert achados["capacidade_carga_kg"].valor == 715
        assert achados["tanque_l"].valor == 77
        assert achados["altura_mm"].valor == 1922
        assert achados["largura_mm"].valor == 2208

    def test_todo_quote_e_substring_literal_do_texto_salvo(self):
        """O contrato inviolável: nenhum valor entra sem trecho verbatim localizável."""
        texto = self._doc_da_raptor()
        for achado in fastpath.extrair_de_pares(texto):
            assert achado.quote in texto, achado

    def test_linha_com_varias_versoes_nao_vira_valor(self):
        """**A guarda que impede a regressão perigosa.**

        Na ficha multiversão da Hilux, "Capacidade de carga" tem quatro números na mesma
        linha (1.005 / 1.000 / 1.015 / 1.005) e "Altura" tem dois. Escolher o primeiro
        daria à SRX Plus o número de outra versão — com evidência que groundeia
        perfeitamente, e **nenhuma métrica do eval pegaria**, porque dimensões não estão no
        gabarito. Este teste é o único guarda-corpo automatizado desse risco.

        Esses campos continuam sendo respondidos pelo recorte de coluna, que sabe **qual**
        coluna é da versão.
        """
        caminho = Path("gabarito/raw/toyota_hilux_my26_p6_p7_layout.txt")
        if not caminho.exists():
            pytest.skip("fixture multiversão ausente")
        achados = {a.campo for a in fastpath.extrair_de_pares(caminho.read_text(encoding="utf-8"))}
        assert "capacidade_carga_kg" not in achados
        assert "altura_mm" not in achados

    def test_capacidade_de_imersao_nao_vira_capacidade_de_carga(self):
        """O vizinho perigoso, na própria fixture da Raptor (`Capacidade de imersão (mm)
        850`). Um casamento por prefixo afrouxado daria à Raptor carga útil de 850 kg —
        com evidência perfeita."""
        texto = self._doc_da_raptor()
        carga = next(
            a for a in fastpath.extrair_de_pares(texto) if a.campo == "capacidade_carga_kg"
        )
        assert carga.valor == 715
        assert "imers" not in carga.quote.lower()

    def test_texto_sem_layout_de_coluna_continua_pelo_caminho_antigo(self):
        """Contra-teste: a ficha em HTML linearizado (rótulo numa linha, valor na
        seguinte) não pode mudar de comportamento."""
        texto = "Potência\n250 cv @ 3.250rpm\n\nTorque\n600 Nm @ 1.750 rpm\n" + ("x\n" * 30)
        achados = {a.campo: a.valor for a in fastpath.extrair_de_pares(texto)}
        assert achados.get("potencia_cv") == 250


class TestFichaHtmlTabular:
    """Tabelas HTML reais chegam ao fast-path com uma tabulação entre as células."""

    def _ficha(self) -> str:
        linhas = [
            "Potência (cv)\t204",
            "Torque (kgfm)\t51,0",
            "Capacidade de carga (kg)\t1.023",
            "Capacidade de reboque (kg)\t3.500",
            "Capacidade do tanque (L)\t76",
            "Comprimento (mm)\t5.365",
            "Largura (mm)\t1.900",
            "Altura (mm)\t1.815",
            "Distância entre eixos (mm)\t3.085",
            "Prazo de garantia (meses)\t60",
        ]
        # `tem_layout_de_tabela` exige uma amostra representativa para não confundir
        # prosa com grade. As linhas de rodapé reproduzem a página completa.
        return "\n".join([*linhas, *("item de equipamento" for _ in range(30))])

    def test_tabulacao_e_reconhecida_como_coluna(self):
        texto = self._ficha()
        assert fastpath.tem_layout_de_tabela(texto)
        pares = fastpath.pares_em_linha(texto)
        assert ("Capacidade de carga (kg)", "1.023", "Capacidade de carga (kg)\t1.023") in pares

    def test_reboque_e_garantia_saem_por_regra_com_quote_literal(self):
        texto = self._ficha()
        achados = {a.campo: a for a in fastpath.extrair_de_pares(texto)}

        assert achados["capacidade_reboque_kg"].valor == 3500
        assert achados["garantia_meses"].valor == 60
        assert achados["capacidade_reboque_kg"].quote in texto
        assert achados["garantia_meses"].quote in texto

    def test_ontologia_resolve_rotulo_fora_do_mapa_manual(self):
        assert "prazo de garantia" not in fastpath.ROTULO_PARA_CAMPO
        assert fastpath.campo_do_rotulo("Prazo de garantia (meses)") == "garantia_meses"

    def test_mapa_manual_continua_ganhando_se_a_ontologia_discordar(self, monkeypatch):
        monkeypatch.setattr(fastpath, "resolve_attribute", lambda _rotulo: ("torque_nm", 100.0))
        assert fastpath.campo_do_rotulo("Potência (cv)") == "potencia_cv"
