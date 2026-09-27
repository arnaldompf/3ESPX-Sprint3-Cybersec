"""WP-25: Change Radar — alertas tipados, referencia interna (tier 0) e equivalentes.

Tres mudancas, e a ordem importa: `internal_references` e `equivalents` apontam para
`versions` e `users`, que a 0001 ja criou.

Sobre `alerts`: as colunas novas nascem **nullable**, inclusive `is_simulated`, que depois
recebe o default. Alterar coluna existente para NOT NULL com default em SQLite exige
recriar a tabela (`render_as_batch`), e para um campo booleano com default `false` isso
seria trabalho sem ganho — `is_simulated IS NULL` e `is_simulated = 0` significam a mesma
coisa aqui (alerta real), e o modelo garante o `False` em toda escrita nova.

Tipos escolhidos para rodar igual em Postgres 16 e SQLite, como nas migracoes anteriores:
`sa.String`, `sa.JSON` (nunca `JSONB`), `sa.DateTime` sem timezone.

Revision ID: 0003_change_radar
Revises: 0002_refresh_tokens
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_change_radar"
down_revision: str | None = "0002_refresh_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: As colunas novas de `alerts`, com o tipo de cada uma.
COLUNAS_DE_ALERTS = (
    ("evidence_before_id", sa.String(length=64)),
    ("evidence_after_id", sa.String(length=64)),
    ("impact_json", sa.JSON()),
    ("reactions_json", sa.JSON()),
    ("is_simulated", sa.Boolean()),
)


def upgrade() -> None:
    # ---------------------------------------------------------------- alerts estendido
    with op.batch_alter_table("alerts") as lote:
        for nome, tipo in COLUNAS_DE_ALERTS:
            lote.add_column(sa.Column(nome, tipo, nullable=True))
    op.create_index("ix_alerts_is_simulated", "alerts", ["is_simulated"])
    # Alerta ja existente e alerta real: `is_simulated` fica em `false` e nao em `null`,
    # para consulta com filtro booleano nao precisar de `IS NULL OR = 0`.
    op.execute("UPDATE alerts SET is_simulated = 0 WHERE is_simulated IS NULL")

    # ------------------------------------------------------- referencia interna (T0)
    op.create_table(
        "internal_references",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("field", sa.String(length=80), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("raw_value", sa.String(length=300), nullable=True),
        sa.Column("documento", sa.String(length=200), nullable=True),
        sa.Column("enviado_por", sa.String(length=64), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"], ["versions.id"], name="fk_internal_references_version_id"
        ),
        sa.ForeignKeyConstraint(
            ["enviado_por"], ["users.id"], name="fk_internal_references_enviado_por"
        ),
        # Um valor interno por (versao, campo): duas linhas para o mesmo campo seriam
        # duas verdades internas, e o produto nao teria o que comparar com a publica.
        sa.UniqueConstraint("version_id", "field", name="uq_internal_references_versao_campo"),
    )
    op.create_index("ix_internal_references_version_id", "internal_references", ["version_id"])
    op.create_index("ix_internal_references_field", "internal_references", ["field"])

    # ------------------------------------------------------------------- equivalentes
    op.create_table(
        "equivalents",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("competitor_version_id", sa.String(length=64), nullable=False),
        # Nullable de proposito: "sem equivalente direto" e resposta legitima (a Raptor
        # nao tem par entre as picapes diesel de trabalho).
        sa.Column("ford_version_id", sa.String(length=64), nullable=True),
        sa.Column("nota", sa.String(length=300), nullable=True),
        sa.Column("definido_por", sa.String(length=64), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["competitor_version_id"], ["versions.id"], name="fk_equivalents_competitor"
        ),
        sa.ForeignKeyConstraint(["ford_version_id"], ["versions.id"], name="fk_equivalents_ford"),
        sa.ForeignKeyConstraint(["definido_por"], ["users.id"], name="fk_equivalents_definido_por"),
        sa.UniqueConstraint(
            "competitor_version_id", "ford_version_id", name="uq_equivalents_par"
        ),
    )
    op.create_index("ix_equivalents_competitor", "equivalents", ["competitor_version_id"])
    op.create_index("ix_equivalents_ford", "equivalents", ["ford_version_id"])


def downgrade() -> None:
    op.drop_index("ix_equivalents_ford", table_name="equivalents")
    op.drop_index("ix_equivalents_competitor", table_name="equivalents")
    op.drop_table("equivalents")

    op.drop_index("ix_internal_references_field", table_name="internal_references")
    op.drop_index("ix_internal_references_version_id", table_name="internal_references")
    op.drop_table("internal_references")

    op.drop_index("ix_alerts_is_simulated", table_name="alerts")
    with op.batch_alter_table("alerts") as lote:
        for nome, _tipo in reversed(COLUNAS_DE_ALERTS):
            lote.drop_column(nome)
