"""Fatos literais da página oficial, sem completar equipamentos por semelhança."""

import pytest

from pipeline.extract.fastpath import extrair


@pytest.mark.parametrize(
    ("text", "field", "value"),
    [
        (
            "Cada modo foi cuidadosamente calibrado para melhorar o desempenho da picape "
            "em qualquer terreno.",
            "carroceria",
            "Picape",
        ),
        ("Freio a disco nas 4 rodas", "freios_dianteiros", "disco"),
        ("| Freio a disco nas 4 rodas |  |", "freios_dianteiros", "disco"),
    ],
)
def test_extracts_literal_vehicle_description_and_all_wheel_disc_brakes(text, field, value):
    results = extrair(text, campos={field}).achados
    assert len(results) == 1
    assert results[0].valor == value
    assert results[0].quote in text
    assert text[results[0].inicio : results[0].fim] == results[0].valor_bruto


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("Veículos\nPicapes\nSUVs\nPerformance", "carroceria"),
        ("https://www.ford.com.br/picapes/ranger/", "carroceria"),
        ("Compare com a picape concorrente", "carroceria"),
        ("Freio a disco", "freios_dianteiros"),
        ("Freio a disco nas 2 rodas traseiras", "freios_dianteiros"),
        ("Disco ventilado na traseira", "freios_dianteiros"),
        ("Não possui freio a disco nas 4 rodas", "freios_dianteiros"),
    ],
)
def test_does_not_infer_body_from_navigation_or_front_brakes_from_rear(text, field):
    assert extrair(text, campos={field}).achados == []


def test_all_wheel_disc_phrase_does_not_invent_ventilation_or_rear_detail():
    values = {a.campo: a.valor for a in extrair("Freio a disco nas 4 rodas").achados}
    assert values["freios_dianteiros"] == "disco"
    assert "freios_traseiros" not in values


def test_requested_fields_still_restrict_new_rules():
    text = "Freio a disco nas 4 rodas\nMotor 250cv"
    assert {a.campo for a in extrair(text, campos={"potencia_cv"}).achados} == {"potencia_cv"}
