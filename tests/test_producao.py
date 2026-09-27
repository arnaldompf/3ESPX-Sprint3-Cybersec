"""Trava de produção: configuração de demonstração não sobe com APP_ENV=producao."""

from __future__ import annotations

import pytest
from api.app.config import Settings

from seguranca.app_segura import (
    ConfiguracaoInsegura,
    problemas_de_configuracao,
    validar_configuracao,
)
from tests.constantes import SEGREDO_DE_TESTE

CONFIGURACAO_SEGURA = {
    "AUTH_ENABLED": "1",
    "RATE_LIMIT_ENABLED": "1",
    "JWT_SECRET": SEGREDO_DE_TESTE,
    "CORS_ORIGINS": "https://specradar.exemplo.com.br",
    "DATABASE_URL": "postgresql+psycopg://specradar@db:5432/specradar",
    "METRICS_TOKEN": "token-de-metricas",
}


def test_padrao_da_demo_e_barrado_em_producao(ambiente):
    ambiente(APP_ENV="producao")

    with pytest.raises(ConfiguracaoInsegura) as erro:
        validar_configuracao(Settings())

    mensagem = str(erro.value)
    assert "AUTH_ENABLED=false" in mensagem
    assert "RATE_LIMIT_ENABLED=false" in mensagem
    assert "JWT_SECRET" in mensagem
    assert "http://localhost:5173" in mensagem


def test_padrao_da_demo_so_avisa_fora_de_producao(ambiente):
    validar_configuracao(Settings())  # não levanta


def test_configuracao_segura_sobe_em_producao(ambiente):
    ambiente(APP_ENV="producao", **CONFIGURACAO_SEGURA)

    assert problemas_de_configuracao(Settings()) == []
    validar_configuracao(Settings())


@pytest.mark.parametrize(
    ("variavel", "valor", "trecho"),
    [
        ("JWT_SECRET", "curto", "JWT_SECRET"),
        ("CORS_ORIGINS", "http://specradar.exemplo.com.br", "sem TLS"),
        ("DATABASE_URL", "sqlite:///x.db", "SQLite"),
        ("SPECRADAR_DEBUG_BOOM", "1", "depuração"),
    ],
)
def test_cada_desvio_e_apontado(ambiente, variavel, valor, trecho):
    ambiente(APP_ENV="producao", **{**CONFIGURACAO_SEGURA, variavel: valor})

    problemas = problemas_de_configuracao(Settings())

    assert len(problemas) == 1
    assert trecho in problemas[0]
