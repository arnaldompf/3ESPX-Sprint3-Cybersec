"""As lacunas e o orçamento: a parada é aritmética, não opinião.

Nos quatro motores de busca estudados em 12/09/2026, a rodada termina quando o modelo diz
"acho que já tenho o bastante". Aqui a pergunta tem resposta exata — quantos dos 58 campos
ainda não têm valor —, e é isso que estes testes fixam.
"""

from __future__ import annotations

from pipeline.research import gaps
from pipeline.schema import SpecField, Status, empty_spec


def _com(campos: dict[str, object]):
    """Uma ficha com os campos pedidos preenchidos."""
    spec = empty_spec(job_id="teste")
    for caminho, valor in campos.items():
        if isinstance(valor, SpecField):
            spec.set(caminho, valor)
        else:
            spec.set(caminho, SpecField(value=valor, status=Status.NAO_VERIFICADO))
    return spec


class TestCobertura:
    def test_ficha_vazia_e_zero_e_tudo_falta(self):
        cobertura = gaps.medir(empty_spec(job_id="t"))
        assert cobertura.com_valor == 0
        assert cobertura.fracao == 0.0
        assert len(cobertura.faltando) == cobertura.total

    def test_marca_modelo_e_versao_nao_contam_como_lacuna(self):
        """Eles são a **entrada** da pesquisa. Procurá-los seria perguntar ao buscador algo
        que já sabemos, e contá-los faria a cobertura nunca fechar."""
        for campo in ("marca", "modelo", "versao", "ano_modelo"):
            assert campo in gaps.NAO_SE_PROCURA
            assert campo not in gaps.campos_procuraveis()

    def test_campo_declarado_ausente_pela_fonte_conta_como_respondido(self):
        """A montadora afirmar que a versão não tem reboque **é** uma resposta.

        Continuar procurando por ela gastaria página para confirmar uma ausência que a
        fonte já declarou — e o orçamento é de doze páginas.
        """
        spec = empty_spec(job_id="t")
        spec.set(
            "dimensoes.capacidade_reboque_kg",
            SpecField(value=None, status=Status.NAO_DISPONIVEL),
        )
        cobertura = gaps.medir(spec)
        assert cobertura.declarados_ausentes == 1
        assert "capacidade_reboque_kg" not in cobertura.faltando
        assert cobertura.respondidos == cobertura.com_valor + 1

    def test_campo_nao_encontrado_continua_sendo_lacuna(self):
        """A diferença entre os dois vazios é o produto: `nao_disponivel` é resposta,
        `nao_encontrado` é trabalho por fazer."""
        spec = empty_spec(job_id="t")
        spec.set("dimensoes.tanque_l", SpecField(value=None, status=Status.NAO_ENCONTRADO))
        assert "tanque_l" in gaps.medir(spec).faltando

    def test_o_filtro_de_campos_reduz_o_denominador(self):
        cobertura = gaps.medir(empty_spec(job_id="t"), ["potencia_cv", "torque_nm"])
        assert cobertura.total == 2


class TestOrcamento:
    def test_o_padrao_e_o_da_demonstracao(self):
        o = gaps.Orcamento()
        assert (o.rodadas, o.paginas, o.segundos) == (2, 12, 180.0)

    def test_estoura_por_rodadas(self):
        o = gaps.Orcamento(rodadas=2)
        o.rodadas_gastas = 2
        assert o.estourou() is gaps.Motivo.RODADAS

    def test_estoura_por_paginas(self):
        o = gaps.Orcamento(paginas=12)
        o.paginas_gastas = 12
        assert o.estourou() is gaps.Motivo.PAGINAS

    def test_dentro_do_orcamento_nao_estoura(self):
        assert gaps.Orcamento().estourou() is None

    def test_paginas_restantes_nunca_e_negativo(self):
        o = gaps.Orcamento(paginas=3)
        o.paginas_gastas = 5
        assert o.paginas_restantes == 0


class TestADecisaoDeContinuar:
    def _cobertura(self, com_valor: int, faltando: int) -> gaps.Cobertura:
        return gaps.Cobertura(
            total=com_valor + faltando,
            com_valor=com_valor,
            declarados_ausentes=0,
            faltando=tuple(f"campo_{i}" for i in range(faltando)),
        )

    def test_sem_lacuna_para_por_cobertura(self):
        continua, motivo = gaps.vale_outra_rodada(
            self._cobertura(10, 5), self._cobertura(15, 0), gaps.Orcamento()
        )
        assert not continua
        assert motivo is gaps.Motivo.COBERTURA

    def test_rodada_que_nao_rendeu_nada_para_o_laco(self):
        """Uma rodada sem **nenhum** campo novo é o sinal mais honesto de que a fonte não
        tem o que falta. Insistir custa e não rende, e o custo sai da próxima pesquisa."""
        continua, motivo = gaps.vale_outra_rodada(
            self._cobertura(10, 5), self._cobertura(10, 5), gaps.Orcamento()
        )
        assert not continua
        assert motivo is gaps.Motivo.SEM_PROGRESSO

    def test_progresso_com_lacuna_e_orcamento_manda_continuar(self):
        continua, motivo = gaps.vale_outra_rodada(
            self._cobertura(10, 8), self._cobertura(14, 4), gaps.Orcamento()
        )
        assert continua
        assert motivo is None

    def test_o_orcamento_vence_ate_o_progresso(self):
        """O limite duro vem **antes** de qualquer julgamento: uma pesquisa que está indo
        bem e estourou o relógio estourou o relógio."""
        o = gaps.Orcamento(paginas=2)
        o.paginas_gastas = 2
        continua, motivo = gaps.vale_outra_rodada(self._cobertura(10, 8), self._cobertura(20, 4), o)
        assert not continua
        assert motivo is gaps.Motivo.PAGINAS

    def test_todo_motivo_tem_frase_em_portugues_de_quem_le(self):
        cobertura = self._cobertura(30, 5)
        for motivo in gaps.Motivo:
            frase = gaps.explicar(motivo, cobertura, gaps.Orcamento())
            assert len(frase) > 20, motivo
            assert "_" not in frase, motivo


class TestOOrcamentoDoModelo:
    def test_o_padrao_e_quatro_chamadas(self):
        orc = gaps.Orcamento()
        assert orc.chamadas_llm == 4
        assert orc.chamadas_llm_restantes == 4

    def test_restantes_nunca_e_negativo_e_sai_no_dict(self):
        orc = gaps.Orcamento(chamadas_llm=2)
        orc.chamadas_llm_gastas = 5
        assert orc.chamadas_llm_restantes == 0
        assert orc.to_dict()["chamadas_llm_gastas"] == 5
        assert orc.to_dict()["chamadas_llm"] == 2

    def test_gastar_a_cota_do_modelo_NAO_estoura_o_orcamento(self):
        """A regra por regex continua lendo; o que acaba é só o modelo."""
        orc = gaps.Orcamento(chamadas_llm=1)
        orc.chamadas_llm_gastas = 1
        assert orc.estourou() is None


class TestOsMotivosDoModelo:
    def test_sem_saldo_e_teto_tem_frase_propria(self):
        cobertura = gaps.medir(empty_spec(job_id="t"))
        sem_saldo = gaps.explicar(gaps.Motivo.MODELO_SEM_SALDO, cobertura, gaps.Orcamento())
        teto = gaps.explicar(gaps.Motivo.TETO_DE_GASTO, cobertura, gaps.Orcamento())
        assert "saldo" in sem_saldo and "regra" in sem_saldo
        assert "teto" in teto and "nenhuma chamada" in teto
        assert sem_saldo != teto

    def test_os_valores_cabem_na_coluna_do_banco(self):
        """`ResearchRun.motivo_da_parada` tem 20 caracteres."""
        for motivo in gaps.Motivo:
            assert len(motivo.value) <= 20, motivo


class TestOLimiteNoMeioDaColeta:
    def test_a_ultima_rodada_permitida_ainda_coleta(self):
        """O defeito de 13/09/2026: com `rodadas=1`, a rodada em curso já conta como gasta
        e `estourou()` acusava RODADAS antes da primeira página. A coleta olha só páginas e
        tempo."""
        orc = gaps.Orcamento(rodadas=1, paginas=6, segundos=60)
        orc.rodadas_gastas = 1
        assert orc.estourou() is gaps.Motivo.RODADAS
        assert orc.estourou_na_coleta() is None

    def test_paginas_e_tempo_continuam_valendo_na_coleta(self):
        import time

        orc = gaps.Orcamento(rodadas=5, paginas=2, segundos=60)
        orc.paginas_gastas = 2
        assert orc.estourou_na_coleta() is gaps.Motivo.PAGINAS
        orc = gaps.Orcamento(rodadas=5, paginas=20, segundos=60)
        orc._inicio = time.monotonic() - 3600
        assert orc.estourou_na_coleta() is gaps.Motivo.TEMPO
