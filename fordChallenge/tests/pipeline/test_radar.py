"""WP-25 — Change Radar: tipos, impacto por regra, reação por papel, referência interna.

O que estes testes protegem, além dos critérios de aceite:

* **impacto é regra, não modelo** — e uma regra que erra a conta é pior que nenhuma. Há
  teste para divisão por zero, para "sem equivalente cadastrado" e para o sinal do gap;
* **nenhum alerta sem evidência** (nota da spec);
* **direção do ponto de vista da Ford** — preço do concorrente caindo é ruim para a Ford,
  e a reação sugerida depende disso. Um alerta que dissesse "favorece a Ford" quando o
  preço da própria Ranger subiu seria pior que nenhum alerta.
"""

from __future__ import annotations

import pytest

from pipeline.radar import impact, internal, reactions, tipos
from pipeline.schema import Conflict, Evidence, SpecField, Status, empty_spec

CSV_DO_SLIDE = """versao,campo,valor
Raptor 3.0 V6 Bi-turbo 4WD AT,potencia_cv,397
Raptor 3.0 V6 Bi-turbo 4WD AT,modos_amortecedor,"Normal, Sport, Baja"
Raptor 3.0 V6 Bi-turbo 4WD AT,potencia_rpm,5650
"""


def evidencia(**kw) -> Evidence:
    base = {
        "evidence_id": "e1",
        "source_url": "https://www.ford.com.br/picapes/ranger-raptor/",
        "tier": 1,
        "quote": "Potência 397cv",
        "captured_at": "2026-09-01T00:00:00Z",
    }
    return Evidence(**{**base, **kw})


def ficha_com(campo: str, valor, *, status=Status.VERIFICADO, ev: Evidence | None = None):
    spec = empty_spec(job_id="teste")
    evidencias = [ev or evidencia()] if status in {Status.VERIFICADO, Status.DIVERGENTE} else []
    conflitos = (
        [Conflict(value="outro", evidence=evidencias[0])] if status is Status.DIVERGENTE else []
    )
    spec.set(
        campo,
        SpecField(
            value=valor,
            status=status,
            confidence=0.9,
            evidences=evidencias,
            conflicts=conflitos,
        ),
    )
    return spec


class TestCriteriosDeAceite:
    def test_preco_fipe_novo_gera_alerta_com_before_after_e_delta_pct(self):
        """Critério: FIPE de referência nova → alerta `preco_fipe` com delta_pct."""
        antes = ficha_com("comercial.preco_fipe_brl", 452540)
        depois = ficha_com("comercial.preco_fipe_brl", 460000)

        detectados = tipos.detectar(antes, depois)
        assert len(detectados) == 1
        alerta = detectados[0]
        assert alerta.type == "preco_fipe"
        assert (alerta.old, alerta.new) == (452540, 460000)
        assert alerta.impacto.delta == 7460
        assert alerta.impacto.delta_pct == pytest.approx(1.65, abs=0.01)
        assert alerta.tem_evidencia

    def test_referencia_interna_divergente_traz_os_dois_valores(self):
        """Critério: slide diz "Baja", fonte pública diz "Off-Road" → alerta com os dois."""
        internos = {"modos_amortecedor": ["normal", "sport", "baja"]}
        publicos = {"modos_amortecedor": ["normal", "sport", "off_road"]}

        divergencias = internal.comparar_com_publico(
            internos, publicos, documento="slide-raptor.pdf"
        )
        assert len(divergencias) == 1

        alerta = tipos.da_divergencia_interna(divergencias[0])
        assert alerta.type == "referencia_interna_divergente"
        assert "baja" in str(alerta.old)
        assert "off_road" in str(alerta.new)
        # A evidência do lado interno aponta para o documento do cliente.
        assert alerta.evidencia_antes is not None
        assert alerta.evidencia_antes.source_url.startswith("interno://")
        assert "slide-raptor.pdf" in alerta.evidencia_antes.source_url

    def test_alerta_de_preco_com_equivalente_calcula_gap_e_traz_4_reacoes(self):
        """Critério: com equivalente cadastrado, `gap_depois` calculado e 4 reações."""
        resultado = impact.calcular(
            campo="preco_sugerido_brl",
            antes=348790,
            depois=329990,
            preco_ford=340000,
        )
        assert resultado.gap_antes == pytest.approx(-8790)
        assert resultado.gap_depois == pytest.approx(10010)

        sugeridas = reactions.sugerir("preco_oficial", resultado.direcao).to_dict()
        assert set(sugeridas) == set(reactions.PAPEIS)
        assert all(texto.strip() for texto in sugeridas.values())


class TestImpacto:
    def test_gap_positivo_significa_ford_mais_cara(self):
        """A leitura que o vendedor precisa: quanto ele tem de justificar."""
        resultado = impact.calcular(
            campo="preco_sugerido_brl", antes=300000, depois=300000, preco_ford=350000
        )
        assert resultado.gap_depois == 50000

    def test_sem_equivalente_nao_ha_gap_e_o_motivo_diz_por_que(self):
        """Inventar um par para exibir um número compararia o que não se compara."""
        resultado = impact.calcular(campo="preco_sugerido_brl", antes=300000, depois=310000)
        assert resultado.gap_antes is None
        assert resultado.gap_depois is None
        assert "equivalente" in resultado.motivo_sem_gap

    def test_valor_anterior_zero_nao_produz_percentual_infinito(self):
        """ "Subiu infinito por cento" não é informação."""
        resultado = impact.calcular(campo="preco_sugerido_brl", antes=0, depois=348790)
        assert resultado.delta == 348790
        assert resultado.delta_pct is None
        assert "zero" in resultado.motivo_sem_delta
        # Ganhar valor a partir de zero é material, ainda que sem percentual.
        assert resultado.material

    def test_valor_ausente_nao_produz_delta(self):
        resultado = impact.calcular(campo="preco_sugerido_brl", antes=None, depois=348790)
        assert resultado.delta is None
        assert resultado.motivo_sem_delta

    def test_mudanca_de_texto_e_material_mesmo_sem_delta(self):
        """ "Off-Road" → "Baja" importa, e não tem delta."""
        resultado = impact.calcular(
            campo="modos_amortecedor", antes=["normal", "off_road"], depois=["normal", "baja"]
        )
        assert resultado.delta is None
        assert resultado.material

    def test_mudanca_igual_nao_e_material(self):
        resultado = impact.calcular(campo="tipo_tracao", antes="4x4", depois="4x4")
        assert not resultado.material

    def test_variacao_abaixo_do_limiar_nao_e_material(self):
        """Meio por cento no preço de picape é arredondamento de tabela.

        Alerta que dispara por arredondamento treina o usuário a ignorar alertas.
        """
        resultado = impact.calcular(campo="preco_sugerido_brl", antes=348790, depois=348800)
        assert abs(resultado.delta_pct) < impact.LIMIAR_DE_MATERIALIDADE_PCT
        assert not resultado.material

    class TestDirecao:
        def test_preco_do_concorrente_caindo_desfavorece_a_ford(self):
            resultado = impact.calcular(
                campo="preco_sugerido_brl", antes=348790, depois=329990, e_do_concorrente=True
            )
            assert resultado.direcao == "desfavorece_ford"

        def test_preco_do_concorrente_subindo_favorece_a_ford(self):
            resultado = impact.calcular(
                campo="preco_sugerido_brl", antes=329990, depois=348790, e_do_concorrente=True
            )
            assert resultado.direcao == "favorece_ford"

        def test_preco_da_propria_ford_subindo_DESFAVORECE_a_ford(self):
            """O inverso, e é por isso que a função pergunta de quem é o preço.

            Um alerta dizendo "favorece a Ford" porque o preço da Ranger subiu seria pior
            que nenhum alerta.
            """
            resultado = impact.calcular(
                campo="preco_sugerido_brl", antes=499000, depois=520000, e_do_concorrente=False
            )
            assert resultado.direcao == "desfavorece_ford"

        def test_campo_nao_comercial_fica_neutro(self):
            resultado = impact.calcular(campo="potencia_cv", antes=397, depois=400)
            assert resultado.direcao == "neutro"

    def test_dimensoes_afetadas_vem_do_mapa_de_produto(self):
        resultado = impact.calcular(campo="torque_nm", antes=583, depois=600)
        assert set(resultado.dimensoes_afetadas) == {"desempenho", "carga"}

    def test_campo_sem_dimensao_mapeada_devolve_lista_vazia(self):
        resultado = impact.calcular(campo="farois_tipo", antes="LED", depois="Matrix LED")
        assert resultado.dimensoes_afetadas == []

    def test_booleano_nao_e_tratado_como_numero(self):
        # `True` vale 1 em Python, e um delta de "1" para paddle shifters seria absurdo.
        resultado = impact.calcular(campo="paddle_shifters", antes=False, depois=True)
        assert resultado.delta is None
        assert resultado.material


class TestReacoes:
    def test_todo_tipo_de_alerta_tem_reacao_mapeada(self):
        from api.app.models import AlertType

        for tipo in AlertType:
            sugeridas = reactions.sugerir(tipo.value).to_dict()
            assert set(sugeridas) == set(reactions.PAPEIS), tipo
            assert all(t.strip() for t in sugeridas.values()), tipo
            assert sugeridas != reactions.SEM_REGRA.to_dict(), f"{tipo.value} sem regra"

    def test_direcao_desconhecida_cai_na_neutra_do_mesmo_tipo(self):
        sugeridas = reactions.sugerir("preco_oficial", "direcao_inventada")
        assert sugeridas.vendas
        assert sugeridas != reactions.SEM_REGRA

    def test_tipo_desconhecido_ADMITE_que_nao_ha_regra(self):
        """Conselho inventado sobre dinheiro é pior que a admissão de que não há conselho."""
        sugeridas = reactions.sugerir("tipo_que_nao_existe")
        assert sugeridas == reactions.SEM_REGRA
        assert "Mapear" in sugeridas.ci

    def test_as_reacoes_de_preco_mudam_com_a_direcao(self):
        cai = reactions.sugerir("preco_oficial", "desfavorece_ford")
        sobe = reactions.sugerir("preco_oficial", "favorece_ford")
        assert cai.marketing != sobe.marketing

    def test_fonte_bloqueada_nao_pede_para_burlar(self):
        """ADR-7: bloqueio vira estado, nunca truque. Nem no texto da sugestão."""
        sugeridas = reactions.sugerir("fonte_bloqueada").to_dict()
        texto = " ".join(sugeridas.values()).lower()
        for proibido in ("burlar", "contornar", "bypass", "proxy", "user-agent"):
            assert proibido not in texto, proibido
        assert "sem contorná-lo" in sugeridas["ci"].lower()

    def test_os_textos_sao_curtos_e_acionaveis(self):
        """Nota da spec: "em português, curtos, acionáveis"."""
        for (tipo, _direcao), sugeridas in reactions.TABELA.items():
            for papel, texto in sugeridas.to_dict().items():
                assert len(texto) <= 120, f"{tipo}/{papel}: {len(texto)} caracteres"
                assert texto[0].isupper(), f"{tipo}/{papel} não começa com maiúscula"


class TestClassificacao:
    @pytest.mark.parametrize(
        ("campo", "esperado"),
        [
            ("preco_sugerido_brl", "preco_oficial"),
            ("preco_fipe_brl", "preco_fipe"),
            ("fipe_referencia", "preco_fipe"),
            ("potencia_cv", "campo_alterado"),
            (None, "campo_alterado"),
        ],
    )
    def test_o_tipo_vem_do_campo(self, campo, esperado):
        assert tipos.classificar(campo) == esperado

    def test_fonte_bloqueada_tem_tipo_proprio(self):
        assert tipos.classificar("potencia_cv", status_novo="bloqueada") == "fonte_bloqueada"


class TestNenhumAlertaSemEvidencia:
    def test_alerta_sem_nenhuma_das_duas_evidencias_e_descartado(self):
        """A nota final da spec. Alerta é afirmação sobre dois valores."""
        antes = ficha_com("motorizacao.potencia_cv", 397, status=Status.NAO_VERIFICADO)
        depois = ficha_com("motorizacao.potencia_cv", 400, status=Status.NAO_VERIFICADO)
        assert tipos.detectar(antes, depois, exigir_evidencia=True) == []

    def test_uma_ponta_provada_basta(self):
        """Campo que GANHA valor não tinha evidência antes, e o alerta é legítimo."""
        antes = ficha_com("motorizacao.potencia_cv", None, status=Status.NAO_ENCONTRADO)
        depois = ficha_com("motorizacao.potencia_cv", 397)
        detectados = tipos.detectar(antes, depois)
        assert len(detectados) == 1
        assert detectados[0].evidencia_depois is not None

    def test_o_alerta_guarda_a_evidencia_das_DUAS_pontas(self):
        antes = ficha_com(
            "motorizacao.potencia_cv", 397, ev=evidencia(evidence_id="velha", quote="397cv")
        )
        depois = ficha_com(
            "motorizacao.potencia_cv", 400, ev=evidencia(evidence_id="nova", quote="400cv")
        )
        alerta = tipos.detectar(antes, depois)[0]
        assert alerta.evidencia_antes.quote == "397cv"
        assert alerta.evidencia_depois.quote == "400cv"


class TestReferenciaInterna:
    def test_o_tier_zero_e_rotulo_de_origem_e_NAO_posicao_na_ordenacao(self):
        """O 0 de `docs/12` §6.1 nomeia a origem; ele não ordena.

        Na ordenação do projeto **menor é mais forte** (1 = montadora), então um 0
        comparado como tier faria o slide do cliente vencer o site oficial — e o produto
        confirmaria o erro do deck com ar de autoridade. Quem responde "quanto vale contra
        as outras fontes" é o `TIER_REFERENCIA_INTERNA = 4` do pipeline, que está **abaixo**
        de oficial, FIPE e imprensa, como deve.
        """
        from pipeline.run import TIER_REFERENCIA_INTERNA

        assert internal.TIER_INTERNO == 0
        assert TIER_REFERENCIA_INTERNA > 3

    def test_importa_csv_e_canonicaliza(self):
        resultado = internal.importar(CSV_DO_SLIDE)
        valores = {linha.campo: linha.valor for linha in resultado.linhas}
        assert valores["potencia_cv"] == 397
        assert valores["modos_amortecedor"] == ["normal", "sport", "baja"]

    def test_importa_json(self):
        resultado = internal.importar('[{"versao": "X", "campo": "potencia_cv", "valor": 397}]')
        assert resultado.total == 1

    def test_aceita_json_embrulhado_em_objeto(self):
        resultado = internal.importar(
            '{"linhas": [{"versao": "X", "campo": "potencia_cv", "valor": 397}]}'
        )
        assert resultado.total == 1

    def test_csv_com_ponto_e_virgula_do_excel_brasileiro(self):
        """Errar o separador leria a linha como uma coluna e a mensagem não ajudaria."""
        resultado = internal.importar("versao;campo;valor\nRaptor;potencia_cv;397\n", formato="csv")
        assert resultado.total == 1

    def test_campo_fora_do_schema_e_recusado_COM_O_NOME(self):
        """Recusa silenciosa faria o gestor achar que a linha entrou."""
        resultado = internal.importar("versao,campo,valor\nX,cor_do_forro,preto\n", formato="csv")
        assert resultado.total == 0
        assert "cor_do_forro" in resultado.recusadas[0]

    def test_coluna_obrigatoria_ausente_levanta_com_a_lista(self):
        with pytest.raises(internal.ReferenciaInvalida, match="campo"):
            internal.importar("versao,valor\nX,397\n", formato="csv")

    def test_arquivo_vazio_levanta(self):
        with pytest.raises(internal.ReferenciaInvalida, match="vazio"):
            internal.importar("")

    def test_json_invalido_levanta_com_o_motivo(self):
        with pytest.raises(internal.ReferenciaInvalida, match="JSON"):
            internal.importar("[{quebrado", formato="json")


class TestDivergenciaInterna:
    def test_valor_igual_nao_gera_divergencia(self):
        assert internal.comparar_com_publico({"potencia_cv": 397}, {"potencia_cv": 397}) == []

    def test_397_e_397_ponto_zero_NAO_divergem(self):
        """A comparação é a MESMA do eval.

        Com `!=`, `397` e `397.0` gerariam divergência inexistente — e alerta falso é o
        jeito mais rápido de fazer alguém parar de ler alertas.
        """
        assert internal.comparar_com_publico({"potencia_cv": 397}, {"potencia_cv": 397.0}) == []

    def test_campo_ausente_na_fonte_publica_nao_gera_divergencia(self):
        """Não há discordância entre um valor e uma ausência: isso é lacuna de coleta."""
        assert internal.comparar_com_publico({"potencia_cv": 397}, {}) == []
        assert internal.comparar_com_publico({"potencia_cv": 397}, {"potencia_cv": None}) == []

    def test_valores_diferentes_geram_divergencia_com_os_dois_lados(self):
        (divergencia,) = internal.comparar_com_publico(
            {"potencia_cv": 400}, {"potencia_cv": 397}, documento="slide.pdf"
        )
        assert divergencia.valor_interno == 400
        assert divergencia.valor_publico == 397
        assert divergencia.documento == "slide.pdf"
