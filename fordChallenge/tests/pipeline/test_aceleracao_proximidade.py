"""A regra de proximidade da aceleração 0–100 — e a divergência 5,8 × 6,5 da Raptor.

Esta é a **cena 4** da apresentação de 15/09, e até 09/09/2026 ela não saía da base: o
`ONBOARDING.md` registrava "não sai desta base, use os quatro campos divergentes reais".
O motivo era a forma da fonte, não a ausência do dado. O registro de coleta da Raptor traz
os dois valores, em entradas separadas:

    "trecho": "A Ford declara que a Ranger Raptor vai de 0 a 100 km/h em 5,8 segundos"
    "trecho": "No teste da Autoesporte, a picape cumpriu a marca em 6,5 s"

A regra antiga exigia "0 a 100" e o valor na **mesma frase**, e a segunda frase diz
"a marca" — o 0–100 nomeado antes. Lia o 5,8 e não lia o 6,5.

Os testes aqui guardam as duas coisas que a regra nova tem de fazer, e as três que ela
**não** pode fazer.
"""

from __future__ import annotations

import pytest

from pipeline.extract import fastpath
from pipeline.extract.fastpath import (
    ALCANCE_DA_ACELERACAO,
    FAIXA_DE_ACELERACAO,
    extrair_aceleracao_por_proximidade,
)
from pipeline.store import FIXTURES, snapshots_de


def _valores(texto: str) -> list[float]:
    return sorted(a.valor for a in extrair_aceleracao_por_proximidade(texto))


# ------------------------------------------------------------------ o que ela lê
def test_le_o_valor_da_frase_seguinte_sem_repetir_a_ancora():
    """ "A marca" é o 0–100 nomeado antes. O valor está a poucos caracteres dele."""
    texto = (
        "A Ford declara que a Ranger Raptor vai de 0 a 100 km/h em 5,8 segundos. "
        "No teste da Autoesporte, a picape cumpriu a marca em 6,5 s."
    )
    assert _valores(texto) == [5.8, 6.5]


@pytest.mark.parametrize(
    "ancora",
    ["0 a 100", "0-100", "0 - 100", "0 a 100 km/h", "0 até 100", "0 to 100"],
)
def test_aceita_as_grafias_da_ancora(ancora):
    assert _valores(f"aceleração de {ancora}: o teste marcou 7,1 s") == [7.1]


@pytest.mark.parametrize("escrita", ["6,5 s", "6,5s", "6,5 segundos", "6,5 seg"])
def test_aceita_as_escritas_do_valor(escrita):
    """`s\\b` sozinho não casa "5,8 segundos" — o `\\b` cai entre "s" e "e"."""
    assert _valores(f"de 0 a 100 km/h, a picape fez {escrita} no teste") == [6.5]


def test_a_citacao_e_trecho_contiguo_do_texto_salvo():
    """O grounding não é afrouxado: a citação continua sendo pedaço literal da fonte."""
    texto = "A picape vai de 0 a 100 km/h. No teste, cumpriu a marca em 6,5 s."
    (achado,) = extrair_aceleracao_por_proximidade(texto)
    assert achado.quote in texto
    assert "6,5" in achado.quote


def test_a_nota_diz_a_distancia_e_a_ancora():
    """Quem audita precisa saber **por que** o valor foi aceito."""
    texto = "de 0 a 100 km/h. No teste, 6,5 s."
    (achado,) = extrair_aceleracao_por_proximidade(texto)
    assert "caracteres de" in achado.notas
    assert "0 a 100" in achado.notas


# --------------------------------------------------------------- o que ela recusa
def test_sem_ancora_nao_le_nada():
    """Um valor em segundos solto não é aceleração: pode ser tempo de qualquer coisa."""
    assert _valores("o motor responde em 6,5 s de espera do turbo") == []


def test_valor_longe_da_ancora_fica_fora():
    texto = "0 a 100 km/h" + ("x" * (ALCANCE_DA_ACELERACAO + 50)) + " marcou 6,5 s"
    assert _valores(texto) == []


def test_quebra_de_paragrafo_encerra_o_assunto():
    """Linha vazia é fim de assunto. A âncora não alcança o parágrafo seguinte."""
    texto = "aceleração de 0 a 100 km/h\n\nO ciclo de recarga leva 6,5 s."
    assert _valores(texto) == []


@pytest.mark.parametrize("fora", ["2,5", "40,0"])
def test_valor_fora_da_faixa_plausivel_fica_fora(fora):
    """2,5 s não existe no segmento e 40 s é outra medida. Ver `FAIXA_DE_ACELERACAO`."""
    assert FAIXA_DE_ACELERACAO == (3.0, 30.0)
    assert _valores(f"de 0 a 100 km/h o teste marcou {fora} s") == []


def test_nao_confunde_medida_de_outra_unidade():
    """ "FOX 2,5 pol." tem número com vírgula perto da âncora e não é segundo."""
    texto = "de 0 a 100 km/h com suspensão FOX 2,5 pol. Live Valve"
    assert _valores(texto) == []


# ------------------------------------------------- a fonte real, na base real
def test_na_fonte_real_da_raptor_saem_os_dois_valores(monkeypatch):
    """O critério de aceite: 5,8 **e** 6,5 saem do registro de coleta salvo."""
    monkeypatch.setenv("REPLAY_MODE", "1")
    snap = next(
        s
        for s in snapshots_de("ford_ranger_raptor_2026", FIXTURES)
        if s.source_id == "registro_evidencias_raptor"
    )
    assert {5.8, 6.5} <= set(_valores(snap.texto))


def test_a_ficha_da_raptor_expoe_a_divergencia_com_as_duas_fontes(monkeypatch):
    """Ponta a ponta: a ficha sai `divergente`, com 5,8 no valor e 6,5 no conflito."""
    monkeypatch.setenv("REPLAY_MODE", "1")
    monkeypatch.setenv("LLM_FAKE", "1")
    from pipeline import run

    ficha = run.run("Ford", "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT")
    campo = ficha.get("desempenho.aceleracao_0_100_s")

    assert campo.status == "divergente", "os dois valores têm evidência; isto é divergência"
    assert campo.value == 5.8, "o declarado pela Ford é o valor principal"
    assert [c.value for c in campo.conflicts] == [6.5], "o medido fica visível como conflito"

    # E as duas citações são localizáveis na fonte, cada uma com a sua.
    assert any("5,8" in e.quote for e in campo.evidences)
    conflito = campo.conflicts[0]
    assert conflito.evidence is not None and "6,5" in conflito.evidence.quote


def test_a_regra_esta_no_funil_do_fastpath():
    """Regra que não entra em `extrair` não roda em produção nenhuma."""
    resultado = fastpath.extrair(
        "de 0 a 100 km/h a picape marcou 6,5 s", campos={"aceleracao_0_100_s"}
    )
    assert "aceleracao_por_proximidade" in {a.regra for a in resultado.achados}
