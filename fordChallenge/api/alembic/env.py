"""Ambiente do Alembic.

Três coisas aqui não são boilerplate e explicam por que o arquivo é assim:

* **A URL vem de `os.environ`**, não do `alembic.ini`. Segredo (e credencial de banco é
  segredo) só em `.env` — deixar `sqlalchemy.url` preenchido no `.ini` versionado seria
  vazamento por construção. Sem `DATABASE_URL`, cai no SQLite de dev.
* **`render_as_batch=True`.** O SQLite não sabe fazer `ALTER TABLE` de coluna; o modo
  batch recria a tabela por trás. Sem isso, a primeira migração que altere uma coluna
  passa no Postgres e falha aqui — e é aqui que se desenvolve.
* **`api.app.models` é importado só pelo efeito colateral** de registrar as tabelas em
  `SQLModel.metadata`. Sem o import, o autogenerate acha que o banco tem tabelas a mais
  e escreve uma migração que apaga tudo.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

RAIZ = Path(__file__).resolve().parent.parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from sqlmodel import SQLModel  # noqa: E402

import api.app.models  # noqa: E402, F401  (importar registra as 13 tabelas no metadata)
from api.app.db import database_url  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _url() -> str:
    url = database_url()
    if url.startswith("sqlite"):
        arquivo = url.replace("sqlite:///", "", 1)
        if arquivo and arquivo != ":memory:":
            Path(arquivo).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return url


def run_migrations_offline() -> None:
    """Gera SQL sem conectar (`alembic upgrade head --sql`)."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Conecta e aplica."""
    secao = config.get_section(config.config_ini_section, {})
    secao["sqlalchemy.url"] = _url()
    conectavel = engine_from_config(secao, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with conectavel.connect() as conexao:
        context.configure(
            connection=conexao,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    conectavel.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
