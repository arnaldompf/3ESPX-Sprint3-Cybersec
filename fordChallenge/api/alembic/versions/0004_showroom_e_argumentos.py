"""WP-27: sessoes de showroom (sem PII) e argumentario aprovado pelo gestor.

Duas tabelas novas, nenhuma alteracao em tabela existente — o que torna esta migracao
segura de aplicar com a API no ar.

**A ausencia de PII e estrutural.** Nao ha coluna de nome, telefone, e-mail ou CPF em
`showroom_sessions`, e nao ha porque nao pode haver: `docs/12` §6.5 e explicito, e uma
coluna "observacoes" livre acabaria com o nome do cliente dentro dela na terceira semana de
uso. O que se guarda e o par comparado, o perfil (que ja e anonimo) e o desfecho.

Tipos escolhidos para rodar igual em Postgres 16 e SQLite, como nas migracoes anteriores:
`sa.String`, `sa.JSON` (nunca `JSONB`), `sa.DateTime` sem timezone.

Revision ID: 0004_showroom_e_argumentos
Revises: 0003_change_radar
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_showroom_e_argumentos"
down_revision: str | None = "0003_change_radar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------- sessoes de showroom
    op.create_table(
        "showroom_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("dealer_id", sa.String(length=64), nullable=True),
        sa.Column("vendedor_id", sa.String(length=64), nullable=True),
        sa.Column("ford_version_id", sa.String(length=64), nullable=False),
        sa.Column("competitor_version_ids", sa.JSON(), nullable=True),
        sa.Column("needs_profile_json", sa.JSON(), nullable=True),
        sa.Column("comparison_id", sa.String(length=200), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("motivos", sa.JSON(), nullable=True),
        sa.Column("atributo_decisivo", sa.String(length=80), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["vendedor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["ford_version_id"], ["versions.id"]),
    )
    op.create_index("ix_showroom_sessions_dealer_id", "showroom_sessions", ["dealer_id"])
    op.create_index("ix_showroom_sessions_vendedor_id", "showroom_sessions", ["vendedor_id"])
    op.create_index(
        "ix_showroom_sessions_ford_version_id", "showroom_sessions", ["ford_version_id"]
    )
    op.create_index("ix_showroom_sessions_outcome", "showroom_sessions", ["outcome"])
    op.create_index("ix_showroom_sessions_is_simulated", "showroom_sessions", ["is_simulated"])
    # `created_at` indexado porque `?since=` e o filtro de toda consulta de insights.
    op.create_index("ix_showroom_sessions_created_at", "showroom_sessions", ["created_at"])

    # ------------------------------------------------------- argumentario por par
    op.create_table(
        "argument_templates",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("ford_version_id", sa.String(length=64), nullable=False),
        sa.Column("competitor_version_id", sa.String(length=64), nullable=False),
        sa.Column("textos", sa.JSON(), nullable=True),
        sa.Column("aprovado", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("travado", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("aprovado_por", sa.String(length=64), nullable=True),
        sa.Column("nota", sa.String(length=300), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ford_version_id"], ["versions.id"]),
        sa.ForeignKeyConstraint(["competitor_version_id"], ["versions.id"]),
        sa.ForeignKeyConstraint(["aprovado_por"], ["users.id"]),
        # Um argumento por par: o texto que vale para Ranger x Hilux nao vale para
        # Ranger x S10, e duas linhas para o mesmo par deixariam a resposta ambigua.
        sa.UniqueConstraint("ford_version_id", "competitor_version_id", name="uq_argumento_par"),
    )
    op.create_index(
        "ix_argument_templates_ford_version_id", "argument_templates", ["ford_version_id"]
    )
    op.create_index(
        "ix_argument_templates_competitor_version_id",
        "argument_templates",
        ["competitor_version_id"],
    )
    op.create_index("ix_argument_templates_travado", "argument_templates", ["travado"])


def downgrade() -> None:
    # Ordem inversa da criacao. Os indices caem com a tabela no SQLite e no Postgres.
    op.drop_index("ix_argument_templates_travado", table_name="argument_templates")
    op.drop_index("ix_argument_templates_competitor_version_id", table_name="argument_templates")
    op.drop_index("ix_argument_templates_ford_version_id", table_name="argument_templates")
    op.drop_table("argument_templates")

    op.drop_index("ix_showroom_sessions_created_at", table_name="showroom_sessions")
    op.drop_index("ix_showroom_sessions_is_simulated", table_name="showroom_sessions")
    op.drop_index("ix_showroom_sessions_outcome", table_name="showroom_sessions")
    op.drop_index("ix_showroom_sessions_ford_version_id", table_name="showroom_sessions")
    op.drop_index("ix_showroom_sessions_vendedor_id", table_name="showroom_sessions")
    op.drop_index("ix_showroom_sessions_dealer_id", table_name="showroom_sessions")
    op.drop_table("showroom_sessions")
