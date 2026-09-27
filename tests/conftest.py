"""Testes da camada de segurança contra a solução real em `fordChallenge/`.

Rodar da raiz do repositório, com o ambiente Python da solução:

    uv run --project fordChallenge pytest
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# Banco descartável e nada de rede: valores fixados ANTES de qualquer import da solução,
# porque a configuração dela é lida e cacheada no import.
_TMP = Path(tempfile.mkdtemp(prefix="specradar-testes-seguranca-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'testes.db'}"
os.environ["REPLAY_MODE"] = "1"
os.environ["LLM_FAKE"] = "1"
for _var in ("APP_ENV", "AUTH_ENABLED", "RATE_LIMIT_ENABLED", "METRICS_TOKEN", "JWT_SECRET"):
    os.environ.pop(_var, None)

from seguranca.solucao import preparar_importacao  # noqa: E402

preparar_importacao()

from api.app import rate_limit  # noqa: E402
from api.app.config import get_settings  # noqa: E402

from seguranca.metricas import REGISTRO  # noqa: E402


@pytest.fixture(autouse=True)
def _isolamento():
    get_settings.cache_clear()
    rate_limit.limiter.reset()
    REGISTRO.zerar()
    yield
    get_settings.cache_clear()
    rate_limit.limiter.reset()


@pytest.fixture
def ambiente(monkeypatch):
    """Define variáveis de ambiente e invalida o cache de configuração da solução."""

    def aplicar(**variaveis: str) -> None:
        for nome, valor in variaveis.items():
            monkeypatch.setenv(nome, valor)
        get_settings.cache_clear()

    return aplicar
