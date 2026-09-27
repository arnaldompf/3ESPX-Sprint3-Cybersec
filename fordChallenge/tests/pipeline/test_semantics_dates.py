"""Datas comerciais têm calendário e significado, além de correspondência textual."""

import pytest

from pipeline.semantics import validate_date


@pytest.mark.parametrize(
    "field,value,quote",
    [
        ("preco_data", "2026-09-14", "Capturado em14/09/2026"),
        ("preco_data", "2026-09-14", "Publicado em 14/09/2026"),
        ("preco_data", "2026-09-14", "Artigo sobre oferta vigente publicado em 14/09/2026"),
        ("preco_data", "2026-09-14", "Data de publicação dos preços: 14/09/2026"),
        ("preco_data", "2026-09-14", "Preço vigente: 14/09/2026 (data de captura)"),
        ("preco_data", "2026-09-14", "2026-09-14"),
        ("preco_data", "2026-09-14", "Oferta vigente: setembro de 2026"),
        ("fipe_referencia", "2026-09", "Copyright2026-09-14"),
        ("fipe_referencia", "2026-09", "Data de publicação da tabela FIPE: 2026-09-14"),
        ("fipe_referencia", "2026-09", "Tabela FIPE consultada em 2026-09-14"),
        ("fipe_referencia", "2026-09", "MesReferencia: 2026-09-14 (copyright)"),
        ("fipe_referencia", "2026-02", "Referência: 31/02/2026"),
        ("fipe_referencia", "2026-02", "Referência: 2026-02-31"),
        ("fipe_referencia", "2026-02", "Referência: 31 de fevereiro de 2026"),
        ("preco_data", "2026-02-31", "Oferta vigente: 31/02/2026"),
        ("preco_data", "2026-02-29", "Oferta vigente: 2026-02-29"),
        ("preco_data", "2026-04-31", "Oferta vigente: 31 de abril de 2026"),
        ("fipe_referencia", "2026-13", "Referência: 13/2026"),
        ("fipe_referencia", "2026-00", "Referência: 00/2026"),
        ("fipe_referencia", "2026-09-14", "Referência: 2026-09-14"),
        ("preco_data", "2026-09", "Oferta vigente: 2026-09"),
        ("preco_data", "20260914", "Oferta vigente: 2026-09-14"),
        ("preco_data", "2026-09-14", "Oferta vigente: https://exemplo.com/2026-09-14"),
        ("fipe_referencia", "2026-09", '"MesReferencia":"outubro de 2026"'),
        ("preco_data", "2026-09-15", "Oferta vigente em 14/09/2026; capturado em 15/09/2026"),
    ],
)
def test_rejects_invalid_or_unrelated_dates(field, value, quote):
    assert not validate_date(field, value, quote)


@pytest.mark.parametrize(
    "field,value,quote",
    [
        ("preco_data", "2026-09-14", "Oferta vigente: 2026-09-14"),
        ("preco_data", "2026-09-14", "Oferta vigente em 14/09/2026"),
        ("preco_data", "2026-09-14", "Preços válidos a partir de 14 de setembro de 2026"),
        ("preco_data", "2026-09-01", "Data do preço: 1º de setembro de 2026"),
        ("preco_data", "2024-02-29", "Preço vigente: 29/02/2024"),
        ("preco_data", "2026-03-14", "Preço atualizado em 14 de março de 2026"),
        ("preco_data", "2026-09-14", '"preco_data":"2026-09-14"'),
        ("preco_data", "2026-09-14", "Vigência da oferta: 14/09/2026"),
        ("fipe_referencia", "2026-09", '"MesReferencia":"setembro de 2026"'),
        ("fipe_referencia", "2026-09", "Mês de referência: 09/2026"),
        ("fipe_referencia", "2026-09", "Referência FIPE: 2026-09"),
        ("fipe_referencia", "2026-09", "Tabela FIPE setembro de 2026"),
        ("fipe_referencia", "2026-09", "Referência: 2026-09-14"),
        ("fipe_referencia", "2026-09", "Referência: 14 de setembro de 2026"),
        ("fipe_referencia", "2024-02", "Referência: 29/02/2024"),
        ("fipe_referencia", "2026-03", "Mês de referência\n\nmarço de 2026"),
        ("fipe_referencia", "2026-09", "Copyright 2026. Mês de referência: setembro de 2026"),
        ("preco_data", "2026-09-14", "Oferta vigente em 14/09/2026; capturado em 15/09/2026"),
        ("preco_data", "2026-09-14", "Capturado em 15/09/2026. Oferta vigente em 14/09/2026"),
    ],
)
def test_accepts_valid_dates_attached_to_the_commercial_field(field, value, quote):
    assert validate_date(field, value, quote)


def test_non_date_fields_and_absence_are_not_interpreted_as_dates():
    assert validate_date("preco_sugerido_brl", 346900, "R$ 346.900")
    assert validate_date("preco_data", None, "")
