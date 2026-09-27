"""O ano da ficha não pode ser resgatado por URL, anúncio ou recomendação."""

import hashlib
import json
from pathlib import Path

import pytest

from pipeline.identity import Applicability, VehicleTarget, assess, authoritative_model_years

FIXTURES = Path(__file__).parents[1] / "fixtures" / "quality"
URL = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=36635"
TARGET = VehicleTarget("Volkswagen", "Amarok", "V6 Extreme", 2026)


def test_snapshot_real_cnw_2025_nao_e_amarok_2026():
    metadata = json.loads((FIXTURES / "cnw-amarok-extreme-2025.json").read_text(encoding="utf-8"))
    data = (FIXTURES / "cnw-amarok-extreme-2025.md").read_bytes()
    assert hashlib.sha256(data).hexdigest() == metadata["sha256"]
    result = assess(TARGET, data.decode("utf-8"), url=URL)
    assert result.status == Applicability.INCOMPATIBLE
    assert "ano_modelo_incompativel" in result.reasons
    assert result.observed["anos_modelo"] == [2025]
    assert result.observed["anos_modelo_autoritativos"] == [2025]
    assert authoritative_model_years(data.decode("utf-8"), TARGET) == {2025}


def test_snapshot_real_continua_aplicavel_ao_proprio_ano_2025():
    text = (FIXTURES / "cnw-amarok-extreme-2025.md").read_text(encoding="utf-8")
    result = assess(VehicleTarget("Volkswagen", "Amarok", "V6 Extreme", 2025), text, url=URL)
    assert result.status == Applicability.COMPATIBLE


@pytest.mark.parametrize(
    "text",
    [
        "Volkswagen Amarok Extreme V6 2025 Brasil\nVeja também\nVolkswagen Amarok Extreme V6 2026",
        "Volkswagen Amarok Extreme V6 Brasil\n| Ano | 2025 |\n"
        "[Amarok](https://example.com/?anofim=2026)",
        "Volkswagen Amarok Extreme V6 Brasil\nAno\n2025\nÚltimas notícias\nAmarok MY2026",
        "Volkswagen Amarok Extreme V6 2026 Brasil\n| Ano-modelo | 2025 |",
        "Volkswagen Amarok Extreme V6 2025 Brasil\n| Ano-modelo | 2026 |",
    ],
)
def test_ano_explicito_incompativel_nao_e_compensado_por_ocorrencia_do_alvo(text):
    result = assess(TARGET, text, url=URL)
    assert result.status == Applicability.INCOMPATIBLE
    assert any("ano_modelo" in reason for reason in result.reasons)


@pytest.mark.parametrize(
    "peripheral",
    [
        "[Amarok](https://example.com/?ano=2026)",
        "![Volkswagen Amarok](https://example.com/amarok-2026.jpg)",
        "Veja também\nVolkswagen Amarok Extreme V6 2026",
        "Últimas notícias\nAmarok ano-modelo 2026",
    ],
)
def test_ano_apenas_periferico_nao_comprova_ano_da_ficha(peripheral):
    result = assess(TARGET, "Volkswagen Amarok Extreme V6 Brasil\n" + peripheral, url=URL)
    assert result.status == Applicability.INSUFFICIENT
    assert "identidade_ausente:ano_modelo" in result.reasons


def test_ano_correto_no_titulo_nao_herda_copyright_ou_recomendacao():
    result = assess(
        TARGET,
        "Volkswagen Amarok Extreme V6 2026 Brasil\nCopyright 2025\n"
        "Veja também\nVolkswagen Amarok Extreme V6 2025",
        url=URL,
    )
    assert result.status == Applicability.COMPATIBLE
    assert result.observed["anos_modelo"] == [2026]


def test_ano_fabricacao_nao_substitui_ano_modelo():
    result = assess(
        TARGET,
        "Volkswagen Amarok Extreme V6 Brasil\n| Ano de fabricação | 2025 |\n| Ano-modelo | 2026 |",
        url=URL,
    )
    assert result.status == Applicability.COMPATIBLE


@pytest.mark.parametrize(
    "text",
    [
        "Volkswagen Amarok Brasil MY2025\n| Versões | Highline | Extreme |\n| Ano | 2025 | 2026 |",
        "Volkswagen Amarok Extreme V6 Brasil MY2025\n| Equipamento | Highline | Extreme |",
        "Volkswagen Amarok Extreme V6 Brasil\n| Ano | 2025 | 2026 |",
        "Volkswagen Amarok Extreme V6 Brasil MY2025\nVolkswagen Amarok Extreme V6 Brasil MY2026",
    ],
)
def test_helper_de_publicacao_nao_atribui_ano_global_de_documento_multiversao(text):
    assert authoritative_model_years(text, TARGET) == set()


def test_multiplas_identificacoes_do_mesmo_veiculo_com_anos_diferentes_exigem_recorte():
    result = assess(
        TARGET,
        "Volkswagen Amarok Extreme V6 Brasil MY2025\nVolkswagen Amarok Extreme V6 Brasil MY2026",
        url=URL,
    )
    assert result.status == Applicability.INCOMPATIBLE
    assert "ano_modelo_conflitante" in result.reasons
