"""Referência interna da Raptor versus evidência pública aplicável.

O valor público prevalece sobre a referência interna. Contestação inferior permanece
rastreável; falta de suporte não é contradição. O gabarito histórico alegava 4/4,
mas a aplicação das regras de identidade e grounding sustenta apenas 2/4.
"""

from __future__ import annotations

import pytest

from pipeline.eval.gabarito import carregar_gabarito
from pipeline.run import TIER_REFERENCIA_INTERNA, referencia_interna, run
from pipeline.schema import Status

VERSION_ID = "ford_ranger_raptor_2026"


@pytest.fixture(scope="module")
def veiculo():
    return carregar_gabarito().por_id(VERSION_ID)


@pytest.fixture(scope="module")
def ficha():
    return run(
        "Ford",
        "Ranger",
        "Raptor 3.0 V6 Bi-turbo 4WD AT",
        version_id=VERSION_ID,
        job_id="teste:slide",
    )


class TestSlideComoFonte:
    def test_o_slide_existe_como_documento_de_entrada(self):
        documento = referencia_interna(VERSION_ID)
        assert documento is not None
        assert documento.texto.strip()

    def test_o_slide_entra_com_tier_abaixo_de_toda_fonte_publica(self):
        # T1 oficial, T2 FIPE, T3 imprensa. O slide é T4: documento interno sem
        # verificação editorial. É esse tier que faz o valor público vencer e o do slide
        # ir para `conflicts` — com tier alto, o produto se inverteria e passaria a
        # confirmar o erro do deck.
        documento = referencia_interna(VERSION_ID)
        assert documento.tier == TIER_REFERENCIA_INTERNA == 4

    def test_o_slide_se_declara_documento_interno(self):
        # Quem abrir a fonte tem de ver o que ela é. Rótulo de procedência é regra.
        assert "NÃO é fonte pública" in referencia_interna(VERSION_ID).texto

    def test_o_slide_aparece_nas_fontes_consultadas_da_ficha(self, ficha):
        assert "referencia_interna" in ficha.meta.sources_checked

    def test_o_slide_traz_as_afirmacoes_que_o_gabarito_registrou(self, veiculo):
        # Os itens do deck, um por linha. O gabarito anotou 26 mapeamentos campo→valor
        # sobre 16 linhas distintas, porque uma linha ("V6 3.0L Nano bi turbo") responde
        # por quatro campos.
        texto = referencia_interna(VERSION_ID).texto
        distintos = {str(c.slide_ford) for c in veiculo.campos_com_slide}
        assert len(veiculo.campos_com_slide) == 26
        assert len(distintos) == 16
        for esperado in ("V6 3.0L Nano bi turbo", "5650", "3500", "Baja", "Matrix LED"):
            assert esperado in texto, esperado


class TestAplicabilidadeDaReferencia:
    def test_modos_direcao_com_ano_no_titulo_da_versao_sao_publicados(self, ficha):
        # A captura antiga não prova o ano-modelo no conteúdo; não se fabrica a identidade.
        campo = ficha.get("modos.modos_direcao")
        assert campo.status is Status.VERIFICADO
        assert campo.value == ["normal", "conforto", "sport", "off_road"]

    def test_fonte_inferior_nao_muda_decisao_publica(self, ficha, veiculo):
        campo = ficha.get("modos.modos_amortecedor")
        esperado = next(c for c in veiculo.campos if c.campo == "modos_amortecedor")
        assert campo.value == esperado.valor
        assert campo.status is Status.VERIFICADO

    @pytest.mark.parametrize("caminho", ["motorizacao.potencia_rpm", "motorizacao.torque_rpm"])
    def test_numero_que_so_o_slide_afirmava_agora_vem_de_fonte_publica(self, ficha, caminho):
        """Fase 2 do plano 18/18 (CarrosNaWeb, tier 3, 2026-09-15): os dois rpm que só o
        slide interno afirmava agora têm fonte pública real. O valor não é mais `None`
        — e continua não vindo do slide: a evidência aponta para o CarrosNaWeb, tier 3,
        nunca para `referencia_interna` (tier 4)."""
        campo = ficha.get(caminho)
        assert campo.value is not None
        assert all(e.tier == 3 for e in campo.evidences)
        assert all("carrosnaweb" in e.source_url for e in campo.evidences)

    def test_eval_nao_alega_divergencias_sem_prova(self, veiculo, ficha):
        """`_avalia_divergencias_do_slide` só conta "divergência exposta" quando o
        `StandardSpec` grava `conflicts` — e o slide (tier 4) nunca compete de igual
        para igual com uma fonte pública: ele simplesmente perde, sem virar conflito
        registrado. Por desenho, nenhum dos 3 alvos (2 modos + `potencia_rpm`, que
        passou de "ausente" para "diverge do slide" com o CarrosNaWeb) produz achado
        por essa via — o valor público vence silenciosamente, que é a regra correta.
        """
        from pipeline.eval.run import _avalia_divergencias_do_slide

        achadas, alvos, detalhes = _avalia_divergencias_do_slide(veiculo, ficha)
        assert alvos == 3
        assert achadas == 0
        assert detalhes == []


class TestOndeOSlideConcorda:
    """Concordância também tem de funcionar: alarme que dispara sempre não serve."""

    @pytest.mark.parametrize(
        ("caminho", "esperado"),
        [
            ("motorizacao.potencia_cv", 397),
            ("motorizacao.torque_nm", 583),
            ("transmissao.numero_marchas", 10),
            ("exterior.farois_tipo", "Matrix LED"),
        ],
    )
    def test_slide_de_acordo_com_a_fonte_publica_nao_gera_divergencia(
        self, ficha, caminho, esperado
    ):
        campo = ficha.get(caminho)
        assert campo.value == esperado, caminho
        assert campo.status is not Status.DIVERGENTE, caminho

    def test_o_typo_de_preco_do_slide_nao_contamina_o_preco(self, ficha):
        # O deck escreve "R$499.00" (typo real, registrado no gabarito). O valor certo é
        # R$ 499.000, e vem da página oficial. Um leitor ingênuo do slide leria 499 reais.
        campo = ficha.get("comercial.preco_sugerido_brl")
        assert campo.value == 499000
        assert campo.status is Status.VERIFICADO
