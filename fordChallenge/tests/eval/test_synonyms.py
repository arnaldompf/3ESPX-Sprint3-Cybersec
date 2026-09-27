"""WP-11 / docs/09 — sinônimos: os quatro casos que a spec nomeia, e por quê.

`docs/09` lista `tests/eval/test_synonyms.py` com "volante→direção; aletas→paddle;
kgfm→Nm; hp→cv". Cada um veio de um **erro real** registrado em `gabarito/README.md`: um
agente genérico marcou `nao_encontrado` para os modos de direção porque procurou a palavra
"volante", e perdeu "Paddle Shifters" embora estivesse na fonte.
"""

from __future__ import annotations

import pytest

from pipeline.eval.compare import comparar_lista, comparar_valor
from pipeline.eval.gabarito import carregar_gabarito
from pipeline.normalize import normalizar_campo
from pipeline.ontology import (
    canonicalizar_lista,
    resolve_attribute,
    resolve_attribute_path,
    resolve_unit,
    resolve_value,
)
from pipeline.units import to_cv, to_nm


@pytest.fixture(scope="module")
def gab():
    return carregar_gabarito()


# ---------------------------------------------- os quatro casos nomeados em docs/09
def test_volante_resolve_para_direcao():
    """O erro-âncora: o slide diz "modos de **volante**", a ficha diz "modos de **direção**".

    Um agente genérico procurou a palavra "volante", não achou, e marcou
    `nao_encontrado` — quando o dado estava lá com outro nome.
    """
    assert resolve_attribute("modos de volante")[0] == "modos_direcao"
    assert resolve_attribute("modos do volante")[0] == "modos_direcao"
    assert resolve_attribute("steering modes")[0] == "modos_direcao"
    assert resolve_attribute_path("modos de volante")[0] == "modos.modos_direcao"


def test_aletas_resolve_para_paddle_shifters():
    """O segundo erro real: "Manus perdeu 'Paddle Shifters' embora estivesse na fonte"."""
    for termo in ("aletas", "aletas no volante", "borboletas", "paddle shift"):
        assert resolve_attribute(termo)[0] == "paddle_shifters", termo


def test_kgfm_vira_nm():
    assert to_nm(50.9, "kgfm") == pytest.approx(499, abs=1)
    for grafia in ("kgfm", "kgf.m", "kgf·m", "mkgf", "KGF.M", "kgm"):
        assert to_nm(50.9, grafia) == pytest.approx(499, abs=1), grafia
    assert resolve_unit("torque", "kgf.m") == "Nm"
    assert normalizar_campo("torque_nm", "50,9", unidade="kgfm").valor == 499


def test_hp_vira_cv():
    assert to_cv(258, "hp") == pytest.approx(262, abs=1)
    assert resolve_unit("potencia", "hp") == "cv"
    assert resolve_unit("potencia", "kW") == "cv"
    assert normalizar_campo("potencia_cv", 258, unidade="hp").valor == pytest.approx(262, abs=1)


# --------------------------------------------------------- sinônimos de valor
@pytest.mark.parametrize(
    ("campo", "bruto", "canonico"),
    [
        ("modos_conducao", "Esportivo", "sport"),
        ("modos_conducao", "lama/terra", "lama"),
        ("modos_direcao", "Comfort", "conforto"),
        ("modos_amortecedor", "Off-Road", "off_road"),
        ("tipo", "AT", "automatica"),
        ("tipo_tracao", "4WD", "4x4"),
        ("tipo_tracao", "4Motion", "4x4 permanente"),
        ("adas_nome_comercial", "TSS", "Toyota Safety Sense"),
        ("pneus_tipo", "All-Terrain", "AT"),
        ("aspiracao", "Bi-Turbo", "biturbo"),
    ],
)
def test_sinonimo_de_valor(campo, bruto, canonico):
    assert resolve_value(campo, bruto) == canonico


def test_lista_com_grafias_diferentes_e_o_mesmo_conjunto():
    """O caso do gabarito: slide e ficha usam palavras diferentes para o mesmo conjunto."""
    da_ficha = canonicalizar_lista(
        "modos_conducao",
        ["Normal", "Esportivo", "Escorregadio", "Lama/Terra", "Areia", "Baja", "Rock Crawl"],
    )
    do_slide = canonicalizar_lista(
        "modos_conducao",
        ["normal", "sport", "escorregadio", "lama", "areia", "rock_crawl", "baja"],
    )
    assert set(da_ficha) == set(do_slide)
    assert comparar_lista("modos_conducao", da_ficha, do_slide).igual


def test_lama_terra_e_um_modo_nao_dois():
    """Separar em "lama" e "terra" faria a lista da Raptor ter 8 itens; o gabarito tem 7."""
    assert canonicalizar_lista("modos_conducao", ["Lama/Terra"]) == ["lama"]


# ---------------------------------------------- contra os valores do gabarito
def test_modos_da_raptor_batem_com_o_gabarito_apos_sinonimos(gab):
    """Os quatro campos de modos da Raptor, comparados como conjunto após sinônimos."""
    raptor = gab.por_id("ford_ranger_raptor_2026")
    for caminho in (
        "modos.modos_conducao",
        "modos.modos_direcao",
        "modos.modos_escapamento",
        "modos.modos_amortecedor",
    ):
        campo = raptor.por_caminho(caminho)
        assert campo is not None and campo.valor
        canonicos = canonicalizar_lista(campo.campo, campo.valor)
        assert set(canonicos) == set(campo.valor), (
            f"{caminho}: o gabarito já está canônico, e a canonicalização é idempotente"
        )


def test_sinonimos_registrados_no_gabarito_funcionam(gab):
    """O gabarito declara os sinônimos que usou; o código tem de honrá-los."""
    raptor = gab.por_id("ford_ranger_raptor_2026")
    modos = raptor.por_caminho("modos.modos_conducao")
    assert modos.sinonimos, "o gabarito registra os sinônimos usados neste campo"
    for bruto, esperado in modos.sinonimos.items():
        assert resolve_value("modos_conducao", bruto) == esperado, bruto


def test_torque_convertido_do_gabarito_bate(gab):
    """A Hilux traz `valor_bruto` "50,9 kgf.m" e `esperado` 499 Nm."""
    hilux = gab.por_id("toyota_hilux_srx_plus_at_2026")
    torque = hilux.por_caminho("motorizacao.torque_nm")
    assert torque.valor_bruto and "kgf" in torque.valor_bruto.lower()
    assert torque.conversao and "9,80665" in torque.conversao
    convertido = to_nm(torque.valor_bruto.split()[0], "kgfm")
    assert comparar_valor("torque_nm", torque.valor, convertido).igual


def test_termo_desconhecido_nao_inventa_campo():
    """Sinônimo ausente vira `extras`, nunca um campo canônico errado."""
    assert resolve_attribute("cor do porta-luvas de um jato")[0] is None
    assert resolve_attribute("ganchos de reboque")[0] is None, (
        "gancho de reboque não é capacidade de reboque"
    )
