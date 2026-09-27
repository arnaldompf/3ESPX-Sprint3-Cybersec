"""WP-12 — reconciliação: de candidatos soltos para observações por campo.

Cada classe aqui trava um defeito que a orquestração cometeu de verdade. Os três piores,
em ordem de perigo:

1. normalizar o **texto bruto** em vez do valor extraído punha `aceleracao_0_100_s = 0.0`
   na ficha, com evidência que groundeia;
2. ler a **linha** de uma tabela em vez da coluna da versão fabricava uma divergência
   17"/18" que não existe na fonte;
3. o bullet de equipamento de **outra versão** entrava como se fosse desta.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from pipeline.extract.run import Candidato
from pipeline.normalize import NaoNormalizavel
from pipeline.reconcile import (
    agrupar,
    descobrir_secoes_de_versao,
    e_item_de_lista,
    filtrar_por_secao,
    observacao_de,
    preferir_celulas,
    reconciliar,
    secoes_da_versao,
)
from pipeline.schema import Status


def cand(campo, valor, **kw) -> Candidato:
    base = {
        "quote": kw.pop("quote", str(valor)),
        "origem": kw.pop("origem", "fastpath:teste"),
        "source_id": kw.pop("source_id", "fonte"),
        "tier": kw.pop("tier", 1),
    }
    return Candidato(campo=campo, valor=valor, **base, **kw)


class TestObservacaoDe:
    def test_normaliza_o_valor_extraido_nao_o_texto_bruto(self):
        # O defeito mais perigoso desta WP. O fast-path entrega valor=5.8 e
        # bruto="0 a 100 km/h em 5,8 segundos". Normalizar o bruto pega o PRIMEIRO
        # numero da frase e a ficha passa a afirmar 0,0 s com evidencia valida.
        o = observacao_de(
            cand("aceleracao_0_100_s", 5.8, valor_bruto="0 a 100 km/h em 5,8 segundos")
        )
        assert o.valor == 5.8

    def test_o_texto_bruto_vai_para_a_evidencia(self):
        o = observacao_de(cand("aceleracao_0_100_s", 5.8, valor_bruto="em 5,8 segundos"))
        assert o.raw_value == "em 5,8 segundos"

    def test_string_truncada_no_bruto_nao_vence_o_valor_parseado(self):
        o = observacao_de(cand("tipo", "automatica", valor_bruto="Transmissão\tAutomátic"))
        assert o.valor == "automatica"

    def test_conversao_de_unidade_acontece_sobre_o_valor(self):
        o = observacao_de(cand("torque_nm", 583, unidade="Nm", valor_bruto="59,4 kgfm"))
        assert o.valor == 583

    def test_valor_nulo_usa_o_bruto_para_ver_ausencia_declarada(self):
        # "—" na coluna da versão é a fonte dizendo que o item não existe. Só o bruto
        # carrega isso, e é o que separa `nao_disponivel` de `nao_encontrado`.
        o = observacao_de(cand("camera_360", None, valor_bruto="—", quote="Camera 360   —"))
        assert o.ausencia_declarada
        assert o.valor is None

    def test_valor_impossivel_de_normalizar_levanta_em_vez_de_forcar(self):
        with pytest.raises(NaoNormalizavel):
            observacao_de(cand("potencia_cv", None, valor_bruto=""))


class TestAgrupar:
    def test_agrupa_por_campo_preservando_discordantes(self):
        por_campo, recusados = agrupar(
            [
                cand("potencia_cv", 397, source_id="a"),
                cand("potencia_cv", 400, source_id="b"),
            ]
        )
        assert len(por_campo["potencia_cv"]) == 2
        assert not recusados

    def test_nao_normalizavel_sai_nomeado_em_vez_de_desaparecer(self):
        por_campo, recusados = agrupar([cand("potencia_cv", None, valor_bruto="")])
        assert not por_campo
        assert recusados and "potencia_cv" in recusados[0]


class TestPreferirCelulas:
    #: A linha real da ficha da Hilux: uma linha, três versões, três colunas.
    LINHA = 'Rodas    Aço estampado 17"   Liga leve 17"   Liga leve 18"'

    def test_celula_vence_texto_da_mesma_fonte_e_do_mesmo_campo(self):
        mantidos, descartados = preferir_celulas(
            [
                cand("rodas_aro_pol", 17, quote=self.LINHA),
                cand("rodas_aro_pol", 18, quote='Liga leve 18"', de_celula=True),
            ]
        )
        assert [c.valor for c in mantidos] == [18]
        assert descartados and "coluna da versão" in descartados[0]

    def test_divergencia_entre_FONTES_DIFERENTES_continua_existindo(self):
        # A guarda é estreita de propósito: outra fonte que discorde produz divergência
        # real, e divergência real é resultado, não ruído.
        mantidos, _ = preferir_celulas(
            [
                cand("rodas_aro_pol", 17, source_id="site"),
                cand("rodas_aro_pol", 18, source_id="pdf", de_celula=True),
            ]
        )
        assert sorted(c.valor for c in mantidos) == [17, 18]

    def test_outro_campo_da_mesma_fonte_nao_e_afetado(self):
        mantidos, _ = preferir_celulas(
            [
                cand("potencia_cv", 204, quote="Potencia 204cv"),
                cand("rodas_aro_pol", 18, de_celula=True),
            ]
        )
        assert len(mantidos) == 2

    def test_sem_celula_nenhuma_nada_e_descartado(self):
        candidatos = [cand("potencia_cv", 204), cand("potencia_cv", 207)]
        mantidos, descartados = preferir_celulas(candidatos)
        assert mantidos == candidatos
        assert not descartados


#: A página da S10, com as versões em blocos. `"• Rodas de liga leve 18”;"` é da Trail
#: Boss, e foi atribuído à High Country até esta guarda existir.
PAGINA_S10 = """Escolha a sua S10

S10 LTZ
A partir de R$ 333.690
• Ar-condicionado digital;

Trail Boss
A partir de R$ 341.290
• Suspensão Exclusiva Ironman;
• Rodas de liga leve 18”;

S10 High Country
A partir de R$ 348.790
• Teto solar;
"""


class TestFiltrarPorSecao:
    OUTRAS: ClassVar[list[str]] = ["S10 LTZ", "Trail Boss", "S10 Z71"]

    def test_bullet_de_outra_versao_e_descartado(self):
        mantidos, descartados = filtrar_por_secao(
            [cand("rodas_aro_pol", 18, quote="• Rodas de liga leve 18”;", source_id="s10")],
            textos={"s10": PAGINA_S10},
            alvo="S10 High Country",
            outras=self.OUTRAS,
        )
        assert not mantidos
        assert "Trail Boss" in descartados[0]

    def test_bullet_da_versao_pedida_fica(self):
        mantidos, _ = filtrar_por_secao(
            [cand("teto_solar", True, quote="• Teto solar;", source_id="s10")],
            textos={"s10": PAGINA_S10},
            alvo="S10 High Country",
            outras=self.OUTRAS,
        )
        assert len(mantidos) == 1

    def test_fato_da_linha_inteira_nao_e_bullet_e_por_isso_fica(self):
        # Sem esta condição a guarda derrubava `combustivel`, `potencia_cv` e `aspiracao`:
        # a página declara o motor uma vez, num parágrafo que por acaso cai depois do
        # nome de alguma versão. Fato da linha não é "de outra versão".
        texto = "Trail Boss\nA partir de R$ 341.290\nMotor 2.8 turbodiesel em toda a linha"
        mantidos, descartados = filtrar_por_secao(
            [cand("aspiracao", "turbo", quote="Motor 2.8 turbodiesel", source_id="s10")],
            textos={"s10": texto + "\nS10 High Country\n"},
            alvo="S10 High Country",
            outras=self.OUTRAS,
        )
        assert len(mantidos) == 1
        assert not descartados

    def test_sem_identificar_a_dona_o_candidato_fica(self):
        # A reportagem escreve "Volkswagen Amarok Extreme" onde o catálogo diz
        # "V6 Extreme": o nome literal não casa e nenhuma outra versão titula o trecho.
        # Descartar em "não sei dizer" custava o preço certo da Amarok.
        texto = "* **Volkswagen Amarok Extreme** - R$ 379.990\nV6 Extreme na tabela\nV6 Highline"
        mantidos, _ = filtrar_por_secao(
            [
                cand(
                    "preco_sugerido_brl",
                    379990,
                    quote="* **Volkswagen Amarok Extreme** - R$ 379.990",
                    source_id="ae",
                )
            ],
            textos={"ae": texto},
            alvo="V6 Extreme",
            outras=["V6 Highline", "V6 Comfortline"],
        )
        assert len(mantidos) == 1

    def test_citacao_repetida_nao_tem_posicao_definida_e_fica(self):
        texto = "Trail Boss\n• LED\nS10 High Country\n• LED\n"
        mantidos, _ = filtrar_por_secao(
            [cand("farois_tipo", "LED", quote="• LED", source_id="s10")],
            textos={"s10": texto},
            alvo="S10 High Country",
            outras=self.OUTRAS,
        )
        assert len(mantidos) == 1

    def test_descobre_o_nome_real_da_secao_quando_o_pedido_e_mais_detalhado(self):
        texto = """Mitsubishi L200 Triton Sport Outdoor GLS 2.4 AT: rodas aro 18
Mitsubishi L200 Triton Sport HPE-S 2.4 AT: farois de LED
Mitsubishi L200 Triton Sport Terra 2.4 AT: rodas aro 20"""
        alvo, outras = descobrir_secoes_de_versao(
            texto,
            marca="Mitsubishi",
            modelo="Triton",
            versao="HPE-S 2.4 Turbodiesel AT6 4x4",
        )
        assert alvo == "Mitsubishi L200 Triton Sport HPE-S 2.4 AT"
        assert "Mitsubishi L200 Triton Sport Terra 2.4 AT" in outras


class TestSecoesDaVersao:
    def test_nao_aplicavel_quando_o_alvo_nao_e_nomeado(self):
        _, aplicavel = secoes_da_versao("Trail Boss\n• LED", "S10 High Country", ["Trail Boss"])
        assert not aplicavel

    def test_nao_aplicavel_quando_nenhuma_outra_versao_e_nomeada(self):
        _, aplicavel = secoes_da_versao("S10 High Country\n• LED", "S10 High Country", ["Z71"])
        assert not aplicavel

    def test_secao_vai_do_nome_ate_a_proxima_versao(self):
        secoes, aplicavel = secoes_da_versao(PAGINA_S10, "S10 High Country", ["Trail Boss"])
        assert aplicavel
        inicio, fim = secoes[0]
        assert PAGINA_S10[inicio:fim].startswith("S10 High Country")


class TestEItemDeLista:
    @pytest.mark.parametrize("linha", ["• Rodas 18”", "- Rodas 18”", "* Rodas", "1. Rodas"])
    def test_reconhece_marcadores(self, linha):
        assert e_item_de_lista(linha, 2)

    def test_paragrafo_nao_e_item_de_lista(self):
        assert not e_item_de_lista("Motor 2.8 turbodiesel em toda a linha", 6)


class TestReconciliar:
    def test_campo_sem_candidato_vira_nao_encontrado_explicito(self):
        resultado = reconciliar(
            [],
            textos={"a": "texto"},
            campos=["potencia_cv"],
            sources_checked=["a"],
        )
        decisao = resultado.decisoes["potencia_cv"]
        assert decisao.status is Status.NAO_ENCONTRADO
        assert decisao.spec.value is None

    def test_fontes_consultadas_viajam_com_a_decisao(self):
        resultado = reconciliar([], textos={}, campos=["potencia_cv"], sources_checked=["a", "b"])
        assert resultado.sources_checked == ["a", "b"]

    def test_duas_fontes_concordantes_sobem_a_confianca(self):
        resultado = reconciliar(
            [
                cand("potencia_cv", 397, quote="Potencia 397cv", source_id="a", tier=1),
                cand("potencia_cv", 397, quote="397 cv", source_id="b", tier=3),
            ],
            textos={"a": "Potencia 397cv", "b": "tem 397 cv"},
            campos=["potencia_cv"],
        )
        decisao = resultado.decisoes["potencia_cv"]
        assert decisao.status is Status.VERIFICADO
        assert decisao.spec.confidence > 0.90

    def test_valores_incompativeis_de_tier_1_viram_divergente(self):
        resultado = reconciliar(
            [
                cand("potencia_cv", 397, quote="Potencia 397cv", source_id="a", tier=1),
                cand("potencia_cv", 400, quote="Potencia 400cv", source_id="b", tier=1),
            ],
            textos={"a": "Potencia 397cv", "b": "Potencia 400cv"},
            campos=["potencia_cv"],
        )
        decisao = resultado.decisoes["potencia_cv"]
        assert decisao.status is Status.DIVERGENTE
        assert decisao.spec.conflicts
