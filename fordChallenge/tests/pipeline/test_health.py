"""WP-33 — Saúde do Conhecimento: as regras, sem banco.

A nota da spec é "sempre explicar por que um campo falta. Nunca '89% verdadeiro'", e é o
que estes testes cercam: cada indicador com denominador, cada campo problemático com
motivo, o status decidido por uma **regra nomeada**, e o texto fixo que impede o número de
ser lido como probabilidade de verdade.

A ordem das regras também está sob teste. Se "sem campo nenhum" não vencer "tem conflito",
uma ficha **vazia** sai como `OK` por não ter conflito — o pior resultado possível, porque
nada acusa.
"""

from __future__ import annotations

import datetime as dt

import pytest

from pipeline import health
from pipeline.health import INSUFICIENTE, OK, REVISAR, LinhaDeCampo

AGORA = dt.datetime(2026, 9, 9, 12, 0, 0)


def linha(campo: str, status: str = "verificado", **kw) -> LinhaDeCampo:
    kw.setdefault("tier", 1)
    kw.setdefault("captured_at", AGORA - dt.timedelta(days=1))
    return LinhaDeCampo(campo=campo, status=status, **kw)


def avaliar(linhas, **kw):
    kw.setdefault("agora", AGORA)
    kw.setdefault("limiar_de_dias", 30)
    return health.avaliar(linhas, **kw)


class TestOTextoFixo:
    def test_e_literal_e_nao_promete_verdade(self):
        """`docs/13` §3, palavra por palavra."""
        assert health.TEXTO_FIXO == "indicador operacional do MVP, não probabilidade de verdade"

    def test_acompanha_toda_avaliacao(self):
        assert avaliar([linha("potencia_cv")]).texto_fixo == health.TEXTO_FIXO

    def test_nenhum_indicador_e_probabilidade(self):
        """Nada de "89% verdadeiro": a fração é de **campos**, com o denominador ao lado."""
        saude = avaliar([linha("potencia_cv"), linha("torque_nm", "nao_encontrado")])
        assert saude.verificados.valor == 1
        assert saude.verificados.de == 2
        assert saude.verificados.fracao == 0.5

    def test_denominador_zero_da_fracao_None_e_nao_zero(self):
        """`0.0` afirmaria "nenhum campo verificado de muitos". `None` diz "não medimos"."""
        assert health.Indicador(0, 0).fracao is None
        assert health.Indicador(0, 10).fracao == 0.0


class TestCadaCampoComMotivo:
    def test_campo_desatualizado_diz_ha_quantos_dias(self):
        velho = linha("preco_sugerido_brl", captured_at=AGORA - dt.timedelta(days=45))
        saude = avaliar([velho])
        assert saude.desatualizados.valor == 1
        problema = saude.desatualizados.campos[0]
        assert problema.campo == "preco_sugerido_brl"
        assert "45 dias" in problema.motivo
        assert "30 dias" in problema.detalhe

    def test_campo_sem_data_de_coleta_conta_como_desatualizado(self):
        """Chamá-lo de atual assumiria que a coleta é de hoje, sem nenhuma evidência disso."""
        saude = avaliar([linha("potencia_cv", captured_at=None)])
        assert saude.desatualizados.valor == 1
        assert "sem data de coleta" in saude.desatualizados.campos[0].motivo

    def test_campo_no_limiar_exato_ainda_esta_atual(self):
        """30 dias com limiar 30 **não** é desatualizado: o corte é "acima de"."""
        no_limiar = avaliar([linha("x", captured_at=AGORA - dt.timedelta(days=30))])
        passou = avaliar([linha("x", captured_at=AGORA - dt.timedelta(days=31))])
        assert no_limiar.desatualizados.valor == 0
        assert passou.desatualizados.valor == 1

    def test_conflito_nomeia_o_campo(self):
        saude = avaliar([linha("modos_amortecedor", "divergente")])
        assert saude.conflitos.valor == 1
        assert saude.conflitos.campos[0].campo == "modos_amortecedor"
        assert "discordam" in saude.conflitos.campos[0].motivo

    def test_fonte_bloqueada_nomeia_a_url_e_nao_sugere_contornar(self):
        saude = avaliar([linha("x")], bloqueadas=["https://media.gm.com/brasil"])
        assert saude.fontes_bloqueadas.valor == 1
        problema = saude.fontes_bloqueadas.campos[0]
        assert problema.campo == "https://media.gm.com/brasil"
        assert "nunca contornada" in problema.detalhe
        for proibido in ("proxy", "user-agent", "burlar"):
            assert proibido not in problema.detalhe.lower()

    def test_url_bloqueada_repetida_conta_uma_vez(self):
        saude = avaliar([linha("x")], bloqueadas=["https://a", "https://a", "https://b"])
        assert saude.fontes_bloqueadas.valor == 2


class TestNaoConfirmado:
    def test_so_conta_tier_3_ou_pior(self):
        """Tier 1 e 2 confirmam: montadora e FIPE/PBE."""
        assert avaliar([linha("x", tier=1)]).nao_confirmados.valor == 0
        assert avaliar([linha("x", tier=2)]).nao_confirmados.valor == 0
        assert avaliar([linha("x", tier=3)]).nao_confirmados.valor == 1
        assert avaliar([linha("x", tier=4)]).nao_confirmados.valor == 1

    def test_o_motivo_diz_que_tem_evidencia_mas_nao_e_a_montadora(self):
        problema = avaliar([linha("x", tier=3)]).nao_confirmados.campos[0]
        assert "tier 3" in problema.motivo
        assert "não é a montadora" in problema.detalhe

    def test_campo_sem_tier_nao_e_contado_como_nao_confirmado(self):
        """Sem tier não se afirma nada sobre a fonte — nem que confirma, nem que não."""
        assert avaliar([linha("x", tier=None)]).nao_confirmados.valor == 0


class TestOStatusVemDeUmaRegraNomeada:
    def test_ficha_vazia_e_INSUFICIENTE_pela_regra_sem_campos(self):
        """A ordem das regras: "sem campo" tem de vencer "sem conflito"."""
        saude = avaliar([])
        assert saude.status == INSUFICIENTE
        assert saude.regra_do_status == "sem_campos"
        assert "Rode a extração" in saude.explicacao_do_status

    def test_menos_da_metade_verificada_e_INSUFICIENTE(self):
        linhas = [linha("a")] + [linha(f"n{i}", "nao_encontrado") for i in range(3)]
        saude = avaliar(linhas)
        assert saude.status == INSUFICIENTE
        assert saude.regra_do_status == "poucos_verificados"
        assert "cobertura" in saude.explicacao_do_status

    def test_conflito_e_REVISAR(self):
        saude = avaliar([linha("a", "divergente"), linha("b")])
        assert saude.status == REVISAR
        assert saude.regra_do_status == "tem_conflito"

    def test_desatualizado_e_REVISAR_e_a_explicacao_distingue_velho_de_errado(self):
        saude = avaliar([linha("a", captured_at=AGORA - dt.timedelta(days=99)), linha("b")])
        assert saude.status == REVISAR
        assert saude.regra_do_status == "tem_desatualizado"
        assert "não está errado" in saude.explicacao_do_status.lower()

    def test_fonte_bloqueada_e_REVISAR_e_explica_o_nao_encontrado(self):
        saude = avaliar([linha("a"), linha("b")], bloqueadas=["https://media.gm.com/brasil"])
        assert saude.status == REVISAR
        assert saude.regra_do_status == "tem_fonte_bloqueada"
        assert "nao_encontrado" in saude.explicacao_do_status

    def test_nao_confirmado_e_REVISAR(self):
        saude = avaliar([linha("a", tier=3), linha("b", tier=1)])
        assert saude.status == REVISAR
        assert saude.regra_do_status == "tem_nao_confirmado"

    def test_sem_pendencia_e_OK_e_a_explicacao_nao_promete_correcao(self):
        saude = avaliar([linha("a"), linha("b")])
        assert saude.status == OK
        assert saude.regra_do_status == "sem_pendencia"
        assert "não que a ficha está certa" in saude.explicacao_do_status

    def test_toda_regra_tem_nome_status_valido_e_explicacao(self):
        for regra in health.REGRAS_DO_STATUS:
            assert regra.nome
            assert regra.status in health.STATUS
            assert len(regra.explicacao) > 40, f"{regra.nome} sem explicação útil"

    def test_a_ultima_regra_e_pega_tudo(self):
        """Sem uma regra terminal, um estado não previsto sairia com o status default."""
        assert health.REGRAS_DO_STATUS[-1].condicao(avaliar([])) is True
        assert health.REGRAS_DO_STATUS[-1].status == OK


class TestContagemPorCampoENaoPorLinha:
    def test_um_campo_divergente_com_tres_valores_e_UM_conflito(self):
        """A regra recebe uma linha por campo — e o adaptador do banco garante isso.

        Contar por linha faria o painel piorar a cada fonte nova consultada, punindo
        exatamente o comportamento que se quer.
        """
        saude = avaliar([linha("modos_conducao", "divergente"), linha("outro")])
        assert saude.conflitos.valor == 1

    def test_o_denominador_dos_indicadores_e_campos_COM_valor(self):
        """Não faz sentido dizer "3 de 58 desatualizados" quando só 2 têm valor."""
        linhas = [linha("a"), linha("b")] + [linha(f"n{i}", "nao_encontrado") for i in range(2)]
        saude = avaliar(linhas)
        assert saude.verificados.de == 4
        assert saude.desatualizados.de == 2
        assert saude.conflitos.de == 2


class TestUltimaAtualizacao:
    def test_e_a_data_mais_recente_entre_os_campos_com_valor(self):
        linhas = [
            linha("a", captured_at=dt.datetime(2026, 8, 1)),
            linha("b", captured_at=dt.datetime(2026, 9, 1)),
        ]
        assert avaliar(linhas).ultima_atualizacao == "2026-09-01T00:00:00"

    def test_sem_data_nenhuma_fica_None_e_nao_agora(self):
        assert avaliar([linha("a", captured_at=None)]).ultima_atualizacao is None

    def test_data_com_fuso_e_comparada_em_utc(self):
        """Evidência gravada com `tzinfo` não pode dar `TypeError` no meio do painel."""
        com_fuso = linha("a", captured_at=dt.datetime(2026, 9, 8, tzinfo=dt.UTC))
        assert avaliar([com_fuso]).desatualizados.valor == 0


class TestCobertura:
    def test_os_campos_destacados_incluem_rpm(self):
        """Por que rpm: a Toyota publica rotação e as outras três não (medido nesta base)."""
        assert "potencia_rpm" in health.CAMPOS_DESTACADOS
        assert "torque_rpm" in health.CAMPOS_DESTACADOS

    def test_o_indicador_de_cobertura_serializa_com_denominador(self):
        c = health.CoberturaDaMarca(marca="Ford", versoes_mapeadas=2)
        c.campos_com_fonte_oficial = health.Indicador(28, 58)
        dados = c.to_dict()
        assert dados["campos_com_fonte_oficial"]["de"] == 58
        assert dados["versoes_mapeadas"] == 2


class TestSerializacao:
    def test_o_dicionario_tem_tudo_que_a_tela_precisa(self):
        saude = avaliar([linha("a", "divergente"), linha("b")], version_id="v1", rotulo="Ford X")
        dados = saude.to_dict()
        for chave in (
            "version_id",
            "rotulo",
            "verificados",
            "desatualizados",
            "conflitos",
            "nao_confirmados",
            "fontes_bloqueadas",
            "ultima_atualizacao",
            "status",
            "regra_do_status",
            "explicacao_do_status",
            "limiar_de_dias",
            "texto_fixo",
        ):
            assert chave in dados, chave
        assert dados["conflitos"]["campos"][0]["campo"] == "a"

    @pytest.mark.parametrize("limiar", [7, 30, 90])
    def test_o_limiar_usado_viaja_na_resposta(self, limiar):
        """Sem isso, "3 desatualizados" não diz desatualizados **em relação a quê**."""
        assert avaliar([linha("a")], limiar_de_dias=limiar).limiar_de_dias == limiar
