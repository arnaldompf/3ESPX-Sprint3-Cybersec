"""Fumaça do WP-00: os pacotes importam e o banco configurado aceita conexão.

O banco de dev nesta máquina é SQLite (DECISOES_NOITE.md D-05); em CI e em produção
é Postgres. O teste é agnóstico: usa `DATABASE_URL` e faz `SELECT 1`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent.parent


def test_pacotes_importam():
    import api
    import pipeline

    assert api.__version__
    assert pipeline.__version__


def test_estrutura_minima_do_repo():
    for caminho in (
        "pyproject.toml",
        ".env.example",
        ".gitignore",
        "Makefile",
        "scripts/task.py",
        "infra/docker-compose.yml",
        ".github/workflows/ci.yml",
        "schema/canonical_spec.schema.json",
        "gabarito/gabarito_v1.json",
    ):
        assert (ROOT / caminho).exists(), f"falta {caminho}"


def test_banco_aceita_conexao():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL não definida (copie .env.example para .env)")
    if url.startswith("sqlite"):
        (ROOT / "data").mkdir(exist_ok=True)
    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1
    engine.dispose()


def test_segredos_nao_versionados():
    """O .env nunca pode estar rastreado pelo git (regra inviolável)."""
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for padrao in (".env", ".venv/", "node_modules/", "data/", "dist/", "reports/*.json"):
        assert padrao in gitignore, f"{padrao} não está no .gitignore"
