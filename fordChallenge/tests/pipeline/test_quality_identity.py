import json
from pathlib import Path

import pytest

from pipeline.identity import Applicability, VehicleTarget, assess


@pytest.mark.parametrize("source,reason", [(0, "mercado"), (1, "motor"), (2, "acessorio")])
def test_documentos_reais_incompativeis(source, reason):
    root = Path("tests/fixtures/quality")
    item = json.loads((root / "baseline.json").read_text(encoding="utf-8"))["sources"][source]
    target = (
        VehicleTarget("Volkswagen", "Amarok", "V6 Extreme", 2026)
        if source == 2
        else VehicleTarget("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT", 2027)
    )
    result = assess(target, (root / item["file"]).read_text(encoding="utf-8"), url=item["url"])
    assert result.status == Applicability.INCOMPATIBLE
    assert any(reason in r for r in result.reasons)


def test_publicacao_2026_pode_descrever_modelo_2027():
    target = VehicleTarget("Ford", "Ranger", "Limited 3.0 V6", 2027)
    result = assess(
        target, "Publicado em 2026. Ford Ranger Limited 3.0 V6, ano-modelo 2027 Brasil."
    )
    assert result.status == Applicability.COMPATIBLE


def test_captura_nao_confirma_ano():
    target = VehicleTarget("Ford", "Ranger", "Limited 3.0 V6", 2027)
    result = assess(target, "Ford Ranger Limited 3.0 V6 Brasil. Captura: 2027-01-01")
    assert result.status == Applicability.INSUFFICIENT


@pytest.mark.parametrize(
    "descricao,reason",
    [
        ("Transmissão: manual", "transmissao_incompativel"),
        ("Tração: 4x2", "tracao_incompativel"),
    ],
)
def test_nome_igual_nao_supera_contradicao_de_cambio_ou_tracao(descricao, reason):
    target = VehicleTarget("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT", 2027)
    result = assess(target, "Ford Ranger Limited 3.0 V6 Diesel 4WD AT Brasil MY2027.\n" + descricao)
    assert result.status == Applicability.INCOMPATIBLE
    assert reason in result.reasons


def test_manual_do_proprietario_nao_significa_cambio_manual():
    target = VehicleTarget("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT", 2027)
    result = assess(
        target,
        "Ford Ranger Limited 3.0 V6 Diesel 4WD AT Brasil MY2027.\n"
        "Manual do proprietário. Transmissão automática. Tração integral.",
    )
    assert result.status == Applicability.COMPATIBLE


def test_limited_plus_nao_e_limited_mesmo_com_motorizacao_e_ano_iguais():
    from pathlib import Path

    from pipeline.identity import Applicability, VehicleTarget, assess

    text = Path("tests/fixtures/quality/live-source-3.txt").read_text(encoding="utf-8")
    result = assess(
        VehicleTarget("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT", 2027),
        text,
        url="https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=49975",
    )
    assert result.status == Applicability.INCOMPATIBLE
