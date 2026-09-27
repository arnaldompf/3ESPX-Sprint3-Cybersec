"""Cabeçalho curto identifica acabamento; motor parecido não troca a versão."""

import pytest

from pipeline.parse.version_slicer import coluna_da_versao

LIMITED = "Limited 3.0 V6 Diesel 4WD AT"


@pytest.mark.parametrize(
    "headers,expected",
    [
        (["Limited"], 1),
        (["XLT 3.0 V6 Diesel", "Limited"], 2),
        (["XLT 3.0 V6 Diesel"], None),
        (["Limited Plus", "Limited"], 2),
        (["Limited+", "Limited"], 2),
        (["Limited + Kit Opcional", "Limited"], 2),
        (["Limited Plus"], None),
        (["Limited 2.0 Diesel", "Limited 3.0 V6 Diesel"], 2),
        (["Limited 2.0 Diesel"], None),
        (["Limited 3.0 V6 Gasolina"], None),
        (["Limited 3.0 V6 Diesel MT", "Limited 3.0 V6 Diesel AT"], 2),
        (["Limited 3.0 V6 Diesel 4x2", "Limited 3.0 V6 Diesel 4x4"], 2),
        (["Limited ano-modelo 2027"], 1),
        (["Limited", "Limited"], None),
    ],
)
def test_identidade_do_acabamento_prevalece(headers, expected):
    assert coluna_da_versao(["Versão", *headers], LIMITED) == expected


def test_plus_nao_herda_limited_sem_pacote():
    assert coluna_da_versao(["Versão", "Limited"], "Limited Plus 3.0 V6 Diesel") is None
    assert coluna_da_versao(["Versão", "Limited+"], "Limited Plus 3.0 V6 Diesel") == 1


def test_mesmo_acabamento_ano_explicito_errado_nao_casa():
    assert coluna_da_versao(["Versão", "Limited 2026"], LIMITED + " 2027") is None
    assert coluna_da_versao(["Versão", "Limited 2027"], LIMITED + " 2027") == 1


def test_transmissao_distingue_colunas_power_pack():
    headers = ["Versão", "STD Power Pack MT", "STD Power Pack AT"]
    assert coluna_da_versao(headers, "STD Power Pack AT (Cabine Dupla)") == 2
    assert coluna_da_versao(headers, "STD Power Pack") is None


def test_acabamentos_desconhecidos_exigem_identidade_em_vez_de_fuzzy():
    assert coluna_da_versao(["Versão", "HPE-S 2.4 Diesel", "HPE 2.4 Diesel"], "HPE-S AT") == 1
    assert coluna_da_versao(["Versão", "HPE-S 2.4 Diesel"], "HPE 2.4 Diesel") is None
    assert coluna_da_versao(["Versão", "SRX", "SRV"], "SR AT") is None


def test_carrocerias_explicitas_diferentes_nao_se_misturam():
    assert coluna_da_versao(["Versão", "XL CS", "XL CD"], "XL AT (Cabine Dupla)") == 2


def test_sem_acabamento_nome_so_mecanico_nao_escolhe_coluna():
    assert coluna_da_versao(["Versão", "Limited 3.0 V6 Diesel"], "3.0 V6 Diesel AT") is None
