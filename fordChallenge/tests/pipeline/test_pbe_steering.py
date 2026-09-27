import json
from pathlib import Path

import pytest

from pipeline.connectors import pbe
from pipeline.identity import VehicleTarget
from pipeline.publication import choose
from pipeline.reconcile import reconciliar
from pipeline.run import JobContext, consultar_consumo
from pipeline.schema import Status
from pipeline.store import Snapshot

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/pbe/amarok_my26_steering.json").read_text(
        encoding="utf-8"
    )
)
TEXT = "\n".join(FIXTURE["rows"])
URL = FIXTURE["source_url"]
TARGET = VehicleTarget("Volkswagen", "Amarok", "V6 Extreme", 2026)


def test_original_pbe_row_decodes_steering_using_original_legend():
    candidates = pbe.candidatos_direcao(TEXT, URL, TARGET)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.valor == "Hidráulica"
    assert candidate.valor_bruto == "H"
    assert candidate.quote in TEXT
    assert len(candidate.quote) <= 300
    assert "EXTREME (MY26)" in candidate.quote
    assert pbe.direcao_comprovada(TEXT, candidate.quote, candidate.valor, TARGET, URL)
    assert not pbe.direcao_comprovada(TEXT, candidate.quote, "Elétrica", TARGET, URL)


@pytest.mark.parametrize(
    "code,value", [("E", "Elétrica"), ("M", "Mecânica"), ("E-H", "Eletro-hidráulica")]
)
def test_other_defined_codes_use_their_own_legend(code, value):
    text = TEXT.replace("A - 8 S H D", f"A - 8 S {code} D")
    assert pbe.candidatos_direcao(text, URL, TARGET)[0].valor == value


def test_supports_only_three_fields_matching_exact_row_and_original_column():
    row = next(r for r in FIXTURE["rows"] if "EXTREME" in r)
    for field, value in [
        ("direcao", "Hidráulica"),
        ("consumo_urbano_kml", 8.1),
        ("consumo_rodoviario_kml", 9.4),
    ]:
        assert pbe.supports(field, TARGET, TEXT, URL, row, value)
    assert not pbe.supports("consumo_urbano_kml", TARGET, TEXT, URL, row, 8.7)
    assert not pbe.supports("consumo_rodoviario_kml", TARGET, TEXT, URL, row, 8.1)
    assert not pbe.supports(
        "consumo_urbano_kml", TARGET, TEXT.replace("Cidade", "Sem cabeçalho"), URL, row, 8.1
    )
    assert not pbe.supports("consumo_urbano_kml", TARGET, TEXT, URL, "8,1 9,4 8,7", 8.1)
    assert not pbe.supports(
        "consumo_urbano_kml", TARGET, TEXT, URL, row.replace("EXTREME", "HIGH"), 8.1
    )
    assert not pbe.supports("tanque_l", TARGET, TEXT, URL, row, 80)
    assert not pbe.supports(
        "consumo_urbano_kml",
        VehicleTarget("Volkswagen", "Amarok", "V6 Extreme", 2025),
        TEXT,
        URL,
        row,
        8.1,
    )


@pytest.mark.parametrize(
    "text",
    [
        TEXT.replace("EXTREME (MY26)", "EXTREME (MY25)"),
        TEXT.replace("EXTREME (MY26)", "EXTREME (MY27)"),
        TEXT.replace("EXTREME (MY26)", "EXTREME"),
        TEXT.replace("EXTREME (MY26)", "EXTREME PLUS (MY26)"),
        TEXT.replace("EXTREME (MY26)", "EXTREME (MY26) (MY25)"),
        TEXT.replace("Hidráulica", "Sem legenda"),
        TEXT.replace("Direção", "Outra coluna"),
        TEXT.replace("A - 8 S H D", "A - 8 S D H"),
        TEXT + "\n" + next(r for r in FIXTURE["rows"] if "EXTREME" in r),
    ],
)
def test_missing_identity_legend_wrong_column_or_duplicate_abstains(text):
    assert pbe.candidatos_direcao(text, URL, TARGET) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/table.pdf",
        URL.replace("https://", "http://"),
        URL.replace("www.gov.br", "user:password@www.gov.br"),
        "https://[broken",
        URL.replace("www.gov.br", "www.gov.br:invalid"),
    ],
)
def test_nonofficial_or_malformed_source_abstains(url):
    assert pbe.candidatos_direcao(TEXT, url, TARGET) == []


def test_existing_measured_connector_reconciles_and_publishes_real_pbe_direction(tmp_path):
    (tmp_path / "page.md").write_text(TEXT, encoding="utf-8")
    ctx = JobContext("Volkswagen", "Amarok", "V6 Extreme", ano=2026)
    ctx.snapshots = [
        Snapshot("amarok", "pbe", "2026-09-14", tmp_path, {"tipo": "pbe", "tier": 2, "url": URL})
    ]
    candidates = consultar_consumo(ctx)
    assert {c.campo for c in candidates} == {
        "direcao",
        "consumo_urbano_kml",
        "consumo_rodoviario_kml",
    }
    result = reconciliar(candidates, textos=ctx.textos, campos=["direcao"], target=TARGET)
    cell = result.decisoes["direcao"].spec
    published = choose(
        "direcao", [cell], target=TARGET, source_texts={e.evidence_id: TEXT for e in cell.evidences}
    )
    assert published.value == "Hidráulica"
    assert published.status == Status.VERIFICADO
    assert published.evidences[0].quote in TEXT
    assert "H=Hidráulica" in published.notes
    assert "Legenda literal:" in published.notes
    assert pbe.direcao_comprovada(TEXT, published.evidences[0].quote, published.value, TARGET, URL)


def test_exact_pbe_row_survives_another_vehicle_heading_in_full_source(tmp_path):
    # Whole-table identity must not assign the following long PBE row to this heading.
    text = TEXT.replace(
        "Picape VW AMAROK V6 COMFORT",
        "# Ford Ranger Limited 3.0 V6 2027\n\nPicape VW AMAROK V6 COMFORT",
    )
    (tmp_path / "page.md").write_text(text, encoding="utf-8")
    ctx = JobContext("Volkswagen", "Amarok", "V6 Extreme", ano=2026)
    ctx.snapshots = [
        Snapshot("amarok", "pbe", "2026-09-14", tmp_path, {"tipo": "pbe", "tier": 2, "url": URL})
    ]
    expected = {"direcao": "Hidráulica", "consumo_urbano_kml": 8.1, "consumo_rodoviario_kml": 9.4}
    result = reconciliar(
        consultar_consumo(ctx), textos=ctx.textos, campos=list(expected), target=TARGET
    )
    for key, value in expected.items():
        cell = result.decisoes[key].spec
        published = choose(
            key, [cell], target=TARGET, source_texts={e.evidence_id: text for e in cell.evidences}
        )
        assert published.status == Status.VERIFICADO
        assert published.value == value
        assert all(
            pbe.supports(key, TARGET, text, URL, e.quote, value) for e in published.evidences
        )
