"""Garantia geral por modelo/MY não herda a cobertura dos componentes."""

from dataclasses import replace

import pytest

from pipeline.connectors.ford_warranty import candidatos, supports
from pipeline.identity import VehicleTarget

URL = "https://www.ford.com.br/servico-ao-cliente/garantia/"
TARGET = VehicleTarget("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT", 2027)
TEXT = """Garantia Ford
Ranger 2027
Prazo de Cobertura
(Garantia Contratual)
5 anos / Sem limite de Km
Bateria
1 ano / Sem limite de Km
Amortecedor
2 anos ou 50.000km
Ranger Raptor 2026
Prazo de Cobertura
(Garantia Contratual)
3 anos / Sem limite de Km
"""


def test_extrai_somente_prazo_contratual_com_proveniencia():
    result = candidatos(TEXT, URL, TARGET, source_id="snapshot-id", captured_at="2026-09-14")
    assert len(result) == 1
    item = result[0]
    assert (item.campo, item.valor, item.unidade) == ("garantia_meses", 60, "meses")
    assert item.valor_bruto == "5 anos"
    assert item.quote in TEXT
    assert "Ranger 2027" in item.quote
    assert "Garantia Contratual" in item.quote
    assert "Bateria" not in item.quote and "Amortecedor" not in item.quote
    assert (item.source_id, item.url, item.tier) == ("snapshot-id", URL, 1)
    assert item.captured_at == "2026-09-14"
    assert item.source_text == TEXT
    assert supports("garantia_meses", TARGET, TEXT, URL, item.quote)


@pytest.mark.parametrize("years,expected", [(1, 12), (3, 36), (7, 84)])
def test_converte_numero_lido_sem_resposta_fixa(years, expected):
    text = TEXT.replace("5 anos", f"{years} {'ano' if years == 1 else 'anos'}")
    assert candidatos(text, URL, TARGET)[0].valor == expected


@pytest.mark.parametrize(
    "target",
    [
        replace(TARGET, ano_modelo=2026),
        replace(TARGET, ano_modelo=None),
        replace(TARGET, modelo="Maverick"),
        replace(TARGET, versao="Raptor 3.0 V6", ano_modelo=2027),
        replace(TARGET, marca="Volkswagen"),
        replace(TARGET, mercado="AR"),
    ],
)
def test_exige_modelo_ano_e_mercado_exatos(target):
    assert candidatos(TEXT, URL, target) == []


def test_raptor_so_aceita_seu_proprio_cabecalho():
    target = replace(TARGET, versao="Raptor 3.0 V6", ano_modelo=2026)
    item = candidatos(TEXT, URL, target)[0]
    assert item.valor == 36
    assert "Ranger Raptor 2026" in item.quote


@pytest.mark.parametrize(
    "url",
    [
        "https://www.ford.com.co/servico-ao-cliente/garantia/",
        "https://ford.com.br.example.org/servico-ao-cliente/garantia/",
        "https://www.ford.com.br/acessorios/garantia/",
        "http://www.ford.com.br/servico-ao-cliente/garantia/",
        "https://user:password@www.ford.com.br/servico-ao-cliente/garantia/",
        "https://user@www.ford.com.br/servico-ao-cliente/garantia/",
        "https://[invalid/servico-ao-cliente/garantia/",
        "https://www.ford.com.br:invalid/servico-ao-cliente/garantia/",
        "https://www.ford.com.br:8443/servico-ao-cliente/garantia/",
    ],
)
def test_restringe_endpoint_oficial_https(url):
    assert candidatos(TEXT, url, TARGET) == []


@pytest.mark.parametrize(
    "text",
    [
        TEXT.replace("Ranger 2027", "Ranger 2026"),
        TEXT.replace("(Garantia Contratual)", "Bateria"),
        "Ranger 2027\nBateria\n1 ano\nAmortecedor\n2 anos",
        "Copyright 2027 Ford\nRanger\nPrazo de Cobertura\n(Garantia Contratual)\n5 anos",
        "Ranger 2027\nRaptor 2027\nPrazo de Cobertura\n(Garantia Contratual)\n5 anos",
    ],
)
def test_nao_herda_ano_de_copyright_nem_garantia_de_componente(text):
    assert candidatos(text, URL, TARGET) == []


def test_supports_nao_libera_outro_campo_nem_quote_sem_escopo():
    quote = candidatos(TEXT, URL, TARGET)[0].quote
    assert not supports("amortecedores", TARGET, TEXT, URL, quote)
    assert not supports("garantia_meses", TARGET, TEXT, URL, "5 anos")
    assert not supports("garantia_meses", TARGET, TEXT, URL, quote.replace("5 anos", "8 anos"))
    assert not supports("garantia_meses", TARGET, TEXT, URL, "")


def test_html_e_markdown_preservam_o_escopo_sem_scripts():
    html = """<h3>Ranger 2027</h3><h4>Prazo de Cobertura<br>(Garantia Contratual)</h4>
    <h4>5 anos / Sem limite de Km</h4><h4>Bateria</h4><p>1 ano</p>
    <script>Ranger 2027\nPrazo de Cobertura\n(Garantia Contratual)\n9 anos</script>"""
    item = candidatos(html, URL, TARGET)[0]
    assert item.valor == 60
    assert item.quote in item.source_text
    assert supports("garantia_meses", TARGET, html, URL, item.quote)
    markdown = "### Ranger 2027\n\n#### Prazo de Cobertura\n(Garantia Contratual)\n\n#### 5 anos"
    assert candidatos(markdown, URL, TARGET)[0].valor == 60


def test_periodos_contraditorios_sao_preservados_para_reconciliar():
    text = TEXT + "\n" + TEXT.replace("5 anos", "7 anos")
    assert {x.valor for x in candidatos(text, URL, TARGET)} == {60, 84}
