"""WP-07 — Passo 0: resolvedor de versão e conectores de linha vigente.

Os quatro casos de aceite da spec, mais as regressões que a sonda encontrou.
Tudo em `REPLAY_MODE=1`: nenhum teste toca a rede.
"""

from __future__ import annotations

import pytest

from pipeline.connectors import (
    ChevroletConnector,
    FordConnector,
    GenericConnector,
    ToyotaConnector,
    VWConnector,
    conector_de,
    marca_canonica,
    parse_lineup_md,
)
from pipeline.connectors.base import (
    LinhaVigenteIndisponivel,
    normalizar_versao,
)
from pipeline.resolver import linha_vigente, resolve


# ------------------------------------------------------------------------ normalização
@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("SRX Plus AT", "srx plus"),
        ("Raptor 3.0 V6 Bi-turbo 4WD AT", "raptor 3.0 v6 bi turbo"),
        ("S10 High Country", "s10 high country"),
        ("GR-Sport", "gr sport"),
        ("4×4 Diesel MT", "diesel"),
        ("  Trail   Boss ", "trail boss"),
    ],
)
def test_normalizar_versao_remove_o_que_nao_distingue(bruto, esperado):
    assert normalizar_versao(bruto) == esperado


def test_marca_canonica_resolve_aliases():
    assert marca_canonica("vw") == "Volkswagen"
    assert marca_canonica("GM") == "Chevrolet"
    assert marca_canonica("ford") == "Ford"
    assert marca_canonica("Fiat") is None


def test_conector_de_marca_desconhecida_cai_no_generico():
    assert isinstance(conector_de("Fiat"), GenericConnector)
    assert isinstance(conector_de("Toyota"), ToyotaConnector)
    assert isinstance(conector_de("vw"), VWConnector)
    assert isinstance(conector_de("GM"), ChevroletConnector)
    assert isinstance(conector_de("Ford"), FordConnector)


# ------------------------------------------------------------------ critérios de aceite
def test_gr_sport_e_versao_inexistente_com_srx_plus_nas_alternativas():
    """Caso negativo do gabarito: a versão saiu de linha."""
    r = resolve("Toyota", "Hilux", "GR-Sport")
    assert r.status == "versao_inexistente"
    assert r.matched_version is None
    assert "SRX Plus AT" in r.alternatives
    assert len(r.alternatives) == 5
    assert "não está na linha vigente" in r.mensagem
    assert "SRX Plus" in r.mensagem


def test_s10_high_country_e_encontrada():
    r = resolve("Chevrolet", "S10", "high country")
    assert r.status == "encontrada"
    assert r.matched_version == "S10 High Country"


def test_raptor_4x4_e_encontrada():
    """O vendedor digita o apelido; o catálogo tem o nome longo."""
    r = resolve("Ford", "Ranger", "Raptor 4x4")
    assert r.status == "encontrada"
    assert r.matched_version == "Raptor 3.0 V6 Bi-turbo 4WD AT"


def test_amarok_extreme_resolve_para_v6_extreme():
    r = resolve("VW", "Amarok", "Extreme")
    assert r.status == "encontrada"
    assert r.matched_version == "V6 Extreme"


# ----------------------------------------------------------------------- regressões
def test_pedido_completo_nao_vira_ambiguo_por_subconjunto_de_tokens():
    """Regressão: `token_set_ratio` puro dava 100 para "SRX Plus" x "SRX".

    O scorer devolve 100 quando um conjunto de tokens é subconjunto do outro, em qualquer
    direção — e "SRX Plus AT" empatava com "SRX AT", virando `ambigua`. Quem pede
    "SRX Plus" não aceita "SRX".
    """
    r = resolve("Toyota", "Hilux", "SRX Plus AT")
    assert r.status == "encontrada"
    assert r.matched_version == "SRX Plus AT"

    r2 = resolve("Toyota", "Hilux", "SRX AT")
    assert r2.status == "encontrada"
    assert r2.matched_version == "SRX AT"


def test_pedido_vago_e_ambiguo_e_nao_escolhe_em_silencio():
    """ "S10" casa com sete versões; o sistema devolve as opções, não um chute."""
    r = resolve("Chevrolet", "S10", "S10")
    assert r.status == "ambigua"
    assert r.matched_version is None
    assert len(r.alternatives) >= 6
    assert "não escolhe em silêncio" in r.mensagem


def test_typo_no_pedido_ainda_resolve():
    r = resolve("Toyota", "Hilux", "SRX Pluss")
    assert r.status == "encontrada"
    assert r.matched_version == "SRX Plus AT"
    assert 85 <= r.score < 100


def test_carroceria_no_pedido_nao_impede_o_match():
    """Regressão: o gabarito chama a versão de "SRX Plus AT (Cabine Dupla)".

    A página `hilux-cabine-dupla` não repete a carroceria no nome de cada versão, então
    exigir cobertura **total** dos tokens do pedido rejeitava o nome correto. Cobertura
    fracionária com o máximo único resolve.
    """
    r = resolve("Toyota", "Hilux", "SRX Plus AT (Cabine Dupla)")
    assert r.status == "encontrada"
    assert r.matched_version == "SRX Plus AT"


def test_carroceria_que_faz_parte_do_nome_continua_valendo():
    """Contraponto: na Chevrolet, "Cabine Simples" **é** o nome da versão."""
    r = resolve("Chevrolet", "S10", "S10 Cabine Simples")
    assert r.status == "encontrada"
    assert r.matched_version == "S10 CABINE SIMPLES"


@pytest.mark.parametrize(
    ("marca", "modelo", "versao", "status"),
    [
        ("Toyota", "Hilux", "SRV", "encontrada"),
        ("Chevrolet", "S10", "Trail Boss", "encontrada"),
        # "XLT Diesel" era caso negativo enquanto a linha da Ranger tinha uma entrada
        # só (a Raptor). Com a coleta de 2026-09-10 a XLT 3.0 V6 Diesel 4WD AT existe,
        # e o resolvedor encontrá-la é o comportamento certo. O caso negativo passa a
        # ser uma versão que a Ford **não** vende: a Ranger Storm saiu de linha.
        ("Ford", "Ranger", "XLT Diesel", "encontrada"),
        ("Ford", "Ranger", "Storm 3.0 V6", "versao_inexistente"),
        ("Ford", "Ranger", "Raptor", "encontrada"),
    ],
)
def test_matriz_de_resolucao(marca, modelo, versao, status):
    assert resolve(marca, modelo, versao).status == status


def test_pedido_mais_especifico_que_a_linha_nao_resolve():
    """Pedir "Raptor Baja Edition" não pode resolver para a Raptor comum."""
    r = resolve("Ford", "Ranger", "Raptor Baja Edition Especial")
    assert r.status == "versao_inexistente"


def test_marca_sem_conector_nao_e_exibida_como_generico():
    """Regressão: a mensagem dizia "linha vigente de generico Toro"."""
    r = resolve("Fiat", "Toro", "Ranch")
    assert r.status == "versao_inexistente"
    assert "Fiat Toro" in r.mensagem
    assert "generico" not in r.mensagem
    assert r.alternatives == ()
    assert "desconhecida" in r.nota_da_linha


def test_resolucao_carrega_a_proveniencia():
    r = resolve("Toyota", "Hilux", "SRX Plus AT")
    assert r.sources
    assert all(u.startswith("http") for u in r.sources)
    assert r.versao_resolvida is not None
    assert r.versao_resolvida.ano_modelo == 2026


def test_fipe_last_year_e_pendencia_declarada():
    """`docs/05` deixa o campo opcional até a WP-13; a pendência é explícita."""
    r = resolve("Toyota", "Hilux", "GR-Sport")
    assert r.fipe_last_year is None
    assert any("WP-13" in p for p in r.pendencias)


def test_to_dict_serializa_o_essencial():
    d = resolve("Toyota", "Hilux", "GR-Sport").to_dict()
    assert d["status"] == "versao_inexistente"
    assert "SRX Plus AT" in d["alternatives"]
    assert d["matched_version"] is None
    assert isinstance(d["pendencias"], list)


# --------------------------------------------------------------------------- conectores
def test_linha_vigente_da_hilux_tem_as_cinco_versoes():
    linha = linha_vigente("Toyota", "Hilux")
    nomes = [v.nome_exato for v in linha.versoes]
    assert nomes == ["STD Power Pack AT", "SR AT", "SRV AT", "SRX AT", "SRX Plus AT"]
    assert all(v.ano_modelo == 2026 for v in linha.versoes)
    assert "GR-Sport" in linha.nota, "a fixture tem de dizer que a GR-Sport não está aqui"


def test_linha_vigente_da_ranger_veio_da_coleta_de_10_de_setembro():
    """A linha da Ranger deixou de ter uma entrada só.

    Até 2026-09-09 a fixture tinha **apenas** a Raptor, porque a coleta original salvou
    a página da VERSÃO e não a do modelo — e era isso que impedia escolher a "Ranger
    diesel topo de linha". A coleta de 2026-09-10 trouxe o comparador de versões do
    próprio site da Ford, com as 11 diesel e o "a partir de" de cada uma.

    O teste guarda as duas coisas que importam: a linha tem as diesel **com preço**, e a
    de maior preço é a que a escolha automática aponta.
    """
    linha = linha_vigente("Ford", "Ranger")
    nomes = [v.nome_exato for v in linha.versoes]
    assert "Raptor 3.0 V6 Bi-turbo 4WD AT" in nomes
    assert "Limited 3.0 V6 Diesel 4WD AT" in nomes

    diesel = [v for v in linha.versoes if "diesel" in v.nome_exato.lower()]
    assert len(diesel) == 11, "as 11 diesel do comparador"
    assert all(v.preco_a_partir_brl for v in diesel), "toda diesel tem 'a partir de'"

    topo = max(diesel, key=lambda v: v.preco_a_partir_brl or 0)
    assert (topo.nome_exato, topo.preco_a_partir_brl) == (
        "Limited 3.0 V6 Diesel 4WD AT",
        346900,
    )
    assert "2026-09-10" in linha.captured_at


def test_linha_vigente_traz_precos_reais_quando_a_fonte_traz():
    linha = linha_vigente("Chevrolet", "S10")
    precos = {v.nome_exato: v.preco_a_partir_brl for v in linha.versoes}
    assert precos["S10 High Country"] == 348790
    assert precos["S10 CABINE SIMPLES"] == 265690
    assert all(p is not None for p in precos.values())


def test_hilux_sem_preco_na_fonte_fica_none_e_nao_zero():
    linha = linha_vigente("Toyota", "Hilux")
    assert all(v.preco_a_partir_brl is None for v in linha.versoes)


def test_fixture_ausente_levanta_em_vez_de_devolver_linha_vazia():
    with pytest.raises(LinhaVigenteIndisponivel, match="sem fixture"):
        ToyotaConnector().lineup_replay("Corolla Cross")


def test_generico_devolve_linha_desconhecida_sem_levantar():
    linha = GenericConnector("Fiat").lineup("Toro")
    assert linha.versoes == []
    assert "desconhecida" in linha.nota


def test_parse_lineup_md_le_o_cabecalho_e_a_tabela():
    texto = (
        "# Linha vigente — Marca Modelo\n"
        "\n"
        "**URL:** https://exemplo.test/modelo\n"
        "**Coletado em:** 2026-09-01\n"
        "**Derivado de:** fonte/qualquer.md\n"
        "\n"
        "> **Atenção:** aviso relevante\n"
        "\n"
        "| nome_exato | ano_modelo | preco_a_partir_brl | url |\n"
        "|---|---|---|---|\n"
        "| Alfa | 2026 | 100000 | https://exemplo.test/a |\n"
        "| Beta | 2026 |  | https://exemplo.test/b |\n"
    )
    linha = parse_lineup_md(texto, marca="Marca", modelo="Modelo")
    assert linha.url == "https://exemplo.test/modelo"
    assert linha.captured_at == "2026-09-01"
    assert linha.origem == "fonte/qualquer.md"
    assert linha.nota == "aviso relevante"
    assert [v.nome_exato for v in linha.versoes] == ["Alfa", "Beta"]
    assert linha.versoes[0].preco_a_partir_brl == 100000
    assert linha.versoes[1].preco_a_partir_brl is None


# ------------------------------------------------------------------------------ fontes
def test_fontes_da_raptor_incluem_o_pdf_de_ficha_tecnica():
    linha = linha_vigente("Ford", "Ranger")
    fontes = FordConnector().sources(linha.versoes[0])
    tipos = {f.tipo for f in fontes}
    assert "pagina_oficial" in tipos
    assert "pdf_oficial" in tipos
    assert all(f.tier == 1 for f in fontes)


def test_fontes_da_hilux_priorizam_o_pdf_que_publica_rpm():
    """Lição 3 do gabarito: só a Toyota publica rpm, e só no PDF."""
    linha = linha_vigente("Toyota", "Hilux")
    srx = next(v for v in linha.versoes if v.nome_exato == "SRX Plus AT")
    fontes = ToyotaConnector().sources(srx)
    assert fontes[0].tipo == "pdf_oficial"
    assert "media.toyota.com.br" in fontes[0].url


def test_fontes_da_s10_registram_a_sala_de_imprensa_bloqueada():
    """CAPTCHA vira status na lista de fontes; nunca é requisitada."""
    linha = linha_vigente("Chevrolet", "S10")
    hc = next(v for v in linha.versoes if v.nome_exato == "S10 High Country")
    fontes = ChevroletConnector().sources(hc)
    bloqueada = next(f for f in fontes if f.tipo == "sala_de_imprensa")
    assert "media.gm.com" in bloqueada.url
    assert "bloqueada" in bloqueada.nota
    assert "CAPTCHA" in bloqueada.nota


def test_fontes_da_amarok_declaram_a_ausencia_de_pdf():
    linha = linha_vigente("VW", "Amarok")
    extreme = next(v for v in linha.versoes if v.nome_exato == "V6 Extreme")
    fontes = VWConnector().sources(extreme)
    assert not any(f.tipo == "pdf_oficial" for f in fontes)
    imprensa = next(f for f in fontes if f.tipo == "imprensa")
    assert imprensa.tier == 3
    assert "não publica PDF" in imprensa.nota


# ------------------------------------------------------------------- rede em replay
def test_replay_nunca_toca_a_rede():
    """Garantia dura: em `REPLAY_MODE=1`, qualquer tentativa de HTTP levanta."""
    from pipeline.connectors import _http

    with pytest.raises(_http.RedeProibidaEmReplay):
        _http.get_text("https://www.ford.com.br/picapes/ranger/")


def test_urls_dos_conectores_seguem_o_padrao_de_docs05():
    assert FordConnector().url_do_modelo("Ranger") == "https://www.ford.com.br/picapes/ranger/"
    assert (
        ToyotaConnector().url_do_modelo("Hilux")
        == "https://www.toyota.com.br/modelos/hilux-cabine-dupla"
    )
    assert VWConnector().url_do_modelo("Amarok") == "https://www.vw.com.br/pt/carros/amarok.html"
    assert ChevroletConnector().url_do_modelo("S10") == "https://www.chevrolet.com.br/picapes/s10"


# ------------------------------------------- a frase que o vendedor lê não é a do log
#
# Um avaliador usou o sistema em 12/09/2026 e leu, na recusa da GR-Sport: "é o caso
# negativo do resolvedor. Preços não constam na página salva (status pendente_coleta no
# gabarito v1)". A frase é verdadeira e está no lugar errado: nasceu como nota de
# proveniência para quem escreve o código, e a `Resolution` a carregava até a tela.
#
# A fronteira que faltava é a mesma que `web/src/lib/erros.ts` já aplica aos erros de
# HTTP: esta camada traduz, não repassa. `nota_da_linha` continua no objeto para quem
# consome por dentro; o que sai na `mensagem` é português de quem vende picape.
TERMOS_DE_DENTRO = (
    "caso negativo",
    "resolvedor",
    "gabarito",
    "pendente_coleta",
    "fixture",
    "conector",
    "observação da coleta",
    "traceback",
    "none",
)


def _vazamentos(frase: str) -> list[str]:
    return [t for t in TERMOS_DE_DENTRO if t in frase.lower()]


def test_recusa_da_gr_sport_nao_vaza_vocabulario_interno():
    r = resolve("Toyota", "Hilux", "GR-Sport")
    assert r.status == "versao_inexistente"
    assert _vazamentos(r.mensagem) == [], f"a frase mostrada ao vendedor vaza: {r.mensagem}"
    # O que a tela PRECISA continuar dizendo (contrato do gabarito e do e2e).
    assert "não está na linha vigente" in r.mensagem
    assert "SRX Plus AT" in r.mensagem
    assert "Não encontrado não é o mesmo que não existe" in r.mensagem


def test_marca_sem_conector_nao_mostra_a_excecao_ao_usuario():
    """A mensagem da exceção é diagnóstico; ela ia inteira para a tela."""
    r = resolve("Fiat", "Toro", "Ultra 2.0 Diesel AT9")
    assert _vazamentos(r.mensagem) == [], f"a frase mostrada ao vendedor vaza: {r.mensagem}"
    assert "Nenhuma versão da linha vigente foi obtida" in r.mensagem
    # …e o diagnóstico continua disponível por dentro, para quem investiga.
    assert r.nota_da_linha


def test_a_proveniencia_nao_se_perde_junto_com_a_nota():
    """Tirar a nota interna não pode tirar a data da coleta: isso trocaria um defeito de
    linguagem por um defeito de transparência, que é pior num produto cuja promessa é
    'evidência com data'."""
    r = resolve("Toyota", "Hilux", "GR-Sport")
    assert "consultada em" in r.mensagem.lower()
