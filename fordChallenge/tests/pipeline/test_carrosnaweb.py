"""CarrosNaWeb (tier 3): o conector fecha `torque_rpm`/`potencia_rpm` do Raptor e a
aceleração/suspensão dos demais alvos — determinístico, sem rede (o conector só recebe
texto já salvo).

Fixtures reais em `gabarito/raw/carrosnaweb_*.md`, no formato de tabela markdown que a
coleta por navegador de fato produz para esta fonte (conferido em snapshots de pesquisa
ao vivo já salvos no repo). Valores conferidos ao vivo em 2026-09-15.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.connectors import carrosnaweb
from pipeline.eval.compare import grounding
from pipeline.identity import VehicleTarget

ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "gabarito" / "raw"

RAPTOR_URL = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=46982"
LIMITED_URL = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=49974"
LIMITED_PLUS_URL = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=49975"
S10_URL = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=47930"


def _texto(nome: str) -> str:
    return (RAW / nome).read_text(encoding="utf-8")


TEXTO_RAPTOR = _texto("carrosnaweb_ranger_raptor_2026.md")
TEXTO_LIMITED = _texto("carrosnaweb_ranger_limited_2027.md")
TEXTO_LIMITED_PLUS = _texto("carrosnaweb_ranger_limited_plus_2027_negativo.md")
TEXTO_S10 = _texto("carrosnaweb_s10_high_country_2027.md")
TEXTO_HILUX = _texto("carrosnaweb_hilux_srx_plus_2026.md")
TEXTO_AMAROK = _texto("carrosnaweb_amarok_v6_extreme_2026.md")

RAPTOR = VehicleTarget(marca="Ford", modelo="Ranger", versao="Raptor 3.0 V6", ano_modelo=2026)
LIMITED = VehicleTarget(marca="Ford", modelo="Ranger", versao="Limited 3.0 V6", ano_modelo=2027)
S10 = VehicleTarget(marca="Chevrolet", modelo="S10", versao="High Country 2.8", ano_modelo=2027)


def test_candidatos_do_raptor_tem_quote_verbatim_e_tier_3():
    resultado = carrosnaweb.candidatos(TEXTO_RAPTOR, RAPTOR_URL, RAPTOR)
    assert resultado, "esperava ao menos um candidato do Raptor"
    for candidato in resultado:
        assert candidato.tier == 3
        # `source_text` é o texto (sem sintaxe de link markdown) que o conector de fato
        # usou para extrair — é nele que o quote precisa ser substring literal, o mesmo
        # texto que fica salvo como evidência.
        assert candidato.quote in candidato.source_text
        assert grounding(candidato.quote, candidato.source_text).ok


def test_raptor_fecha_torque_nm_e_torque_rpm():
    valores = {c.campo: c.valor for c in carrosnaweb.candidatos(TEXTO_RAPTOR, RAPTOR_URL, RAPTOR)}
    assert valores["torque_nm"] == 583, "59,4 kgfm convertido"
    assert valores["torque_rpm"] == 3500


def test_raptor_nunca_le_potencia_cv_mas_le_potencia_rpm():
    valores = {c.campo: c.valor for c in carrosnaweb.candidatos(TEXTO_RAPTOR, RAPTOR_URL, RAPTOR)}
    assert "potencia_cv" not in valores
    assert valores["potencia_rpm"] == 6250


def test_aceleracao_da_limited_e_da_s10():
    valores_limited = {
        c.campo: c.valor for c in carrosnaweb.candidatos(TEXTO_LIMITED, LIMITED_URL, LIMITED)
    }
    valores_s10 = {c.campo: c.valor for c in carrosnaweb.candidatos(TEXTO_S10, S10_URL, S10)}
    assert valores_limited["aceleracao_0_100_s"] == 9.2
    assert valores_s10["aceleracao_0_100_s"] == 9.4


def test_nenhum_candidato_para_os_quatro_modos():
    proibidos = {"modos_conducao", "modos_direcao", "modos_escapamento", "modos_amortecedor"}
    resultado = carrosnaweb.candidatos(TEXTO_RAPTOR, RAPTOR_URL, RAPTOR)
    assert not {c.campo for c in resultado} & proibidos


def test_recusa_ficha_my2025_contra_alvo_my2026():
    """Não há uma ficha real MY2025 do Raptor salva — a mesma ficha real MY2026 contra
    um alvo que pede 2025 já exercita a guarda: `assess` não acha 2025 em `anos_modelo`.
    """
    alvo_2025 = VehicleTarget(
        marca="Ford", modelo="Ranger", versao="Raptor 3.0 V6", ano_modelo=2025
    )
    assert carrosnaweb.candidatos(TEXTO_RAPTOR, RAPTOR_URL, alvo_2025) == []


def test_recusa_ficha_limited_plus_contra_alvo_limited():
    """Armadilha real do projeto: `49975` é a Limited Plus, vizinha de `49974`."""
    assert carrosnaweb.candidatos(TEXTO_LIMITED_PLUS, LIMITED_PLUS_URL, LIMITED) == []


def test_recusa_url_fora_de_fichadetalhe():
    proibidas = [
        "https://www.carrosnaweb.com.br/resultcompara.asp?c1=46982&c2=49974",
        "https://www.carrosnaweb.com.br/resultnotas.asp?codigo=46982",
        "http://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=46982",  # http, não https
        "https://www.carrosnaweb.com.br.evil.com/fichadetalhe.asp?codigo=46982",
        "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=46982&extra=1",
    ]
    for url in proibidas:
        assert carrosnaweb.candidatos(TEXTO_RAPTOR, url, RAPTOR) == [], url


def test_supports_reprova_quote_adulterado():
    resultado = carrosnaweb.candidatos(TEXTO_RAPTOR, RAPTOR_URL, RAPTOR)
    torque = next(c for c in resultado if c.campo == "torque_nm")
    assert carrosnaweb.supports(
        "torque_nm", RAPTOR, TEXTO_RAPTOR, RAPTOR_URL, torque.quote, torque.valor
    )
    adulterado = torque.quote.replace("59,4", "99,9")
    assert not carrosnaweb.supports(
        "torque_nm", RAPTOR, TEXTO_RAPTOR, RAPTOR_URL, adulterado, torque.valor
    )


@pytest.mark.parametrize(
    ("texto", "url", "alvo"),
    [
        (TEXTO_HILUX, "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=41190", None),
        (TEXTO_AMAROK, "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=44849", None),
    ],
)
def test_suspensao_ou_amortecedores_sai_da_ficha_quando_a_fonte_nao_descreve_amortecedor(
    texto, url, alvo
):
    target = VehicleTarget(
        marca="Toyota" if "Hilux" in texto else "Volkswagen",
        modelo="Hilux" if "Hilux" in texto else "Amarok",
        versao="SRX Plus 2.8" if "Hilux" in texto else "Extreme 3.0 V6",
        ano_modelo=2026,
    )
    campos = {c.campo for c in carrosnaweb.candidatos(texto, url, target)}
    assert {"suspensao_dianteira", "suspensao_traseira"} & campos or "amortecedores" in campos
