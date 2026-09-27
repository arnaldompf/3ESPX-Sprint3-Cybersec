"""WP-07 — o caso negativo do resolvedor, medido contra o gabarito.

`docs/09` põe `resolver_accuracy = 1,0` como meta e define o caso: a Hilux GR-Sport tem
de virar `versao_inexistente` com `SRX Plus AT` nas alternativas; os outros quatro
veículos têm de virar `encontrada`.

Este teste lê o `resultado_esperado` do gabarito em vez de repetir os valores aqui —
duas cópias da verdade-terra divergiriam no primeiro ajuste.
"""

from __future__ import annotations

import pytest

from pipeline.eval.gabarito import carregar_gabarito
from pipeline.resolver import resolve


@pytest.fixture(scope="module")
def gab():
    return carregar_gabarito()


def test_gr_sport_reproduz_o_resultado_esperado_do_gabarito(gab):
    grs = gab.por_id("toyota_hilux_gr_sport_2026_inexistente")
    esperado = grs.resultado_esperado
    assert esperado is not None

    r = resolve(grs.marca, grs.modelo, grs.versao)

    assert r.status == esperado.status
    assert esperado.sugestao_equivalente in r.alternatives
    for fragmento in esperado.mensagem_contem:
        assert fragmento in r.mensagem, f"mensagem sem {fragmento!r}: {r.mensagem}"


def test_alternativas_sao_exatamente_a_linha_vigente_do_gabarito(gab):
    grs = gab.por_id("toyota_hilux_gr_sport_2026_inexistente")
    r = resolve(grs.marca, grs.modelo, grs.versao)
    assert set(r.alternatives) == set(grs.nomes_da_linha_vigente)


def test_ultimo_ano_fipe_e_pendencia_declarada_da_wp13(gab):
    """O gabarito espera 2024; o conector FIPE é da WP-13.

    O teste trava a **pendência**, não um valor inventado: enquanto a WP-13 não entra,
    `fipe_last_year` é `None` e isso está escrito em `pendencias`. Quando a WP-13 entrar,
    este teste falha e obriga a atualizar a expectativa — que é o comportamento correto.
    """
    grs = gab.por_id("toyota_hilux_gr_sport_2026_inexistente")
    assert grs.resultado_esperado.ultimo_ano_fipe == 2024
    r = resolve(grs.marca, grs.modelo, grs.versao)
    assert r.fipe_last_year is None
    assert any("WP-13" in p for p in r.pendencias)


@pytest.mark.parametrize(
    "vid",
    [
        "ford_ranger_raptor_2026",
        "toyota_hilux_srx_plus_at_2026",
        "vw_amarok_v6_extreme_2026",
        "chevrolet_s10_high_country_2027",
    ],
)
def test_os_quatro_veiculos_do_gabarito_resolvem(gab, vid):
    """`resolver_accuracy`: os que existem têm de ser `encontrada`."""
    veiculo = gab.por_id(vid)
    r = resolve(veiculo.marca, veiculo.modelo, veiculo.versao)
    assert r.status == "encontrada", f"{veiculo.versao!r} -> {r.status} ({r.mensagem})"
    assert r.matched_version


def test_resolver_accuracy_do_gabarito_e_1_0(gab):
    """A métrica agregada de `docs/09`, calculada aqui sem passar pelo eval."""
    acertos = 0
    for veiculo in gab.veiculos:
        r = resolve(veiculo.marca, veiculo.modelo, veiculo.versao)
        if veiculo.e_caso_negativo:
            esperado = veiculo.resultado_esperado
            ok = r.status == esperado.status and esperado.sugestao_equivalente in r.alternatives
        else:
            ok = r.status == "encontrada"
        acertos += int(ok)
    assert acertos == len(gab.veiculos), f"{acertos}/{len(gab.veiculos)}"


def test_o_pipeline_nao_extrai_atributos_de_versao_fora_de_linha(gab):
    """A razão de o Passo 0 vir primeiro: nada de ficha bonita de carro que saiu de linha."""
    grs = gab.por_id("toyota_hilux_gr_sport_2026_inexistente")
    r = resolve(grs.marca, grs.modelo, grs.versao)
    assert r.versao_resolvida is None
    assert grs.campos == (), "o gabarito não espera atributo nenhum para o caso negativo"
