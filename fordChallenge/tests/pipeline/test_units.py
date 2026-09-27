"""WP-01 — conversões de unidade e parsing pt-BR.

Os casos de aceite vieram de `specs/WP-01.md` e de valores reais do gabarito
(Raptor: 397 cv / 583 Nm / 285/70 R17 / R$ 499.000).
"""

from __future__ import annotations

import pytest

from pipeline.units import (
    UnidadeDesconhecida,
    parse_number_ptbr,
    parse_price,
    parse_rpm,
    parse_tire,
    to_cv,
    to_cv_exact,
    to_litros,
    to_mm,
    to_nm,
    to_nm_exact,
)


# ---------------------------------------------------------------------------- potência
def test_to_cv_converte_hp_criterio_de_aceite():
    assert to_cv(258, "hp") == pytest.approx(262, abs=1)


def test_to_cv_identidade_e_kw():
    assert to_cv(397, "cv") == 397
    assert to_cv(397, "CV") == 397
    assert to_cv(190, "kW") == pytest.approx(258, abs=1)
    assert to_cv(190, "ps") == 190


def test_to_cv_exact_nao_arredonda():
    assert to_cv_exact(258, "hp") == pytest.approx(261.586, abs=0.01)


def test_to_cv_unidade_desconhecida_levanta():
    with pytest.raises(UnidadeDesconhecida):
        to_cv(100, "watts")


# ------------------------------------------------------------------------------ torque
def test_to_nm_converte_kgfm_criterio_de_aceite():
    assert to_nm(50.9, "kgfm") == pytest.approx(499, abs=1)


def test_to_nm_aceita_as_tres_grafias_de_kgfm():
    for unidade in ("kgfm", "kgf.m", "mkgf", "kgf·m", "KGF.M"):
        assert to_nm(50.9, unidade) == pytest.approx(499, abs=1)


def test_to_nm_identidade_e_lbft():
    assert to_nm(583, "Nm") == 583
    assert to_nm(583, "N.m") == 583
    assert to_nm(430, "lb-ft") == pytest.approx(583, abs=1)


def test_to_nm_exact_nao_arredonda():
    assert to_nm_exact(50.9, "kgfm") == pytest.approx(499.158, abs=0.01)


# ------------------------------------------------------------------------ números pt-BR
@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("1.234,5", 1234.5),
        ("1.234", 1234.0),
        ("1.234.567", 1234567.0),
        ("397", 397.0),
        ("5,8", 5.8),
        ("397 cv", 397.0),
        ("Potencia 397cv", 397.0),
        # `3.0` passava mesmo com o defeito abaixo, porque a casa decimal era zero: o
        # truncamento dava 3.0, que é a resposta certa por acidente.
        ("3.0", 3.0),
        ("-12,5", -12.5),
        (583, 583.0),
        # Decimal com PONTO. Estas linhas existem por um defeito medido: a alternativa do
        # ponto vinha depois de `\d+(?:,\d+)?` no regex, que casa "5" sozinho em "5.8" —
        # a alternância é preguiçosa, então o ramo do ponto nunca rodava e "5.8 segundos"
        # virava 5.0. Número errado com confiança de número certo.
        ("5.8", 5.8),
        ("5.8 segundos", 5.8),
        ("12.5 s", 12.5),
        ('Amortecedores FOX 2.5" Racing', 2.5),
        ("0.5", 0.5),
        ("-5.8", -5.8),
        # E o mesmo erro pelo outro lado: sem o `(?!\d)`, "12.3456" casava o milhar
        # "12.345" e perdia o último dígito.
        ("12.3456", 12.3456),
    ],
)
def test_parse_number_ptbr(bruto, esperado):
    assert parse_number_ptbr(bruto) == pytest.approx(esperado)


def test_ponto_com_tres_casas_continua_sendo_milhar():
    """A correção do decimal não pode reinterpretar preço.

    `R$ 348.790` é trezentos e quarenta e oito mil, não 348 vírgula 790 — e é a forma em
    que **todo** preço de tabela brasileiro aparece. Um decimal aqui erraria por mil vezes.
    """
    assert parse_number_ptbr("R$ 348.790") == 348790.0
    assert parse_number_ptbr("499.000") == 499000.0
    assert parse_number_ptbr("1.234.567,89") == pytest.approx(1234567.89)


def test_parse_number_ptbr_sem_numero_levanta():
    with pytest.raises(ValueError, match="nenhum número"):
        parse_number_ptbr("não disponível")


# ------------------------------------------------------------------------------- preço
def test_parse_price_criterio_de_aceite():
    assert parse_price("R$ 499.000") == 499000


def test_parse_price_variacoes():
    assert parse_price("R$499.000,00") == 499000
    assert parse_price("452.540") == 452540
    assert parse_price("R$ 452.540,00") == 452540
    assert parse_price("a partir de R$ 499.000") == 499000
    assert parse_price(499000) == 499000


def test_parse_price_sem_numero_levanta():
    with pytest.raises(ValueError):
        parse_price("sob consulta")


# --------------------------------------------------------------------------------- rpm
def test_parse_rpm():
    assert parse_rpm("5.650 rpm") == 5650
    assert parse_rpm("3.500 a 4.500 rpm") == 3500
    assert parse_rpm(5650) == 5650


# ------------------------------------------------------------------------------- pneus
def test_parse_tire_criterio_de_aceite():
    pneu = parse_tire("285/70 R17")
    assert (pneu.largura_mm, pneu.perfil, pneu.aro_pol) == (285, 70, 17)
    assert pneu.medida == "285/70 R17"


def test_parse_tire_variacoes_de_grafia():
    for bruto in ("285/70R17", "285/70 r 17", "pneus 285/70 R17 AT General Grabber"):
        assert parse_tire(bruto).medida == "285/70 R17"


def test_parse_tire_invalido_levanta():
    with pytest.raises(ValueError, match="pneu"):
        parse_tire("aro 17 de liga leve")


# ------------------------------------------------------------------------ comprimentos
def test_to_mm_e_to_litros():
    assert to_mm(5381, "mm") == 5381
    assert to_mm(2.5, "m") == 2500
    assert to_mm(17, "pol") == 432
    assert to_litros(80, "l") == 80.0
    assert to_litros(3000, "cc") == 3.0
    with pytest.raises(UnidadeDesconhecida):
        to_mm(10, "leguas")


def test_to_mm_nao_multiplica_o_que_ja_esta_em_milimetros():
    """Medido em 13/09/2026: o modelo devolveu `value=5285` com `unit="m"` para
    "Comprimento: 5,285 m" — converteu o número e copiou a unidade do texto. Multiplicar de
    novo gravava 5.285.000 mm como FATO. Um carro não tem 5.285 metros."""
    assert to_mm(5285, "m") == 5285
    assert to_mm("1.820", "m") == 1820
    # O caso legítimo continua legítimo.
    assert to_mm("5,285", "m") == 5285
    assert to_mm(2.5, "metros") == 2500
