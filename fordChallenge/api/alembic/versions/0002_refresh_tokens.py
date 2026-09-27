"""WP-05: tabela `refresh_tokens` — revogacao por `jti` e cadeia de rotacao.

Por que uma tabela e nao uma coluna em `users`: um usuario tem varias sessoes ao mesmo
tempo (celular, tablet do showroom, navegador), e uma coluna so guardaria a ultima. Sair
de uma sessao derrubaria as outras, o que empurra o usuario a nunca sair.

`substituido_por` e auto-referencia logica (nao ha FK): o token que substituiu pode ainda
nao existir no instante do insert do antecessor, e uma FK aqui obrigaria a ordem inversa
sem ganho nenhum de integridade real.

Tipos escolhidos para rodar igual em Postgres 16 e SQLite, como na 0001: `sa.String` e
`sa.DateTime` sem timezone (o lado Python sempre grava UTC).

Revision ID: 0002_refresh_tokens
Revises: 0001_modelo_inicial
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_refresh_tokens"
down_revision: str | None = "0001_modelo_inicial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("jti", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("expira_em", sa.DateTime(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("revogado_em", sa.DateTime(), nullable=True),
        sa.Column("substituido_por", sa.String(length=64), nullable=True),
        sa.Column("motivo_da_revogacao", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_refresh_tokens_user_id_users"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
