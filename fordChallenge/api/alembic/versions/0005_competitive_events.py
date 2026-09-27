"""WP-34: `competitive_events` — o alerta enriquecido com materialidade e prioridade.

Uma tabela nova, nenhuma alteracao em tabela existente: segura de aplicar com a API no ar.

**Por que tabela separada de `alerts`.** O alerta e o FATO ("o preco mudou de X para Y",
com as duas evidencias) e nao muda. O evento e a LEITURA daquele fato ("isto e ALTA porque
entrou na faixa de preco"), e a leitura muda quando as regras ou os pesos de
`pipeline/materiality/rules.yaml` mudam. Guardar as duas coisas na mesma linha faria um
ajuste de peso reescrever o historico do que aconteceu.

`versao_das_regras` fica gravado por isso: um evento avaliado sob a regua de setembro nao
se confunde com um de outubro, e o "Por que?" mostra qual regua valia.

Tipos escolhidos para rodar igual em Postgres 16 e SQLite, como nas migracoes anteriores:
`sa.String`, `sa.JSON` (nunca `JSONB`), `sa.DateTime` sem timezone.

Revision ID: 0005_competitive_events
Revises: 0004_showroom_e_argumentos
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_competitive_events"
down_revision: str | None = "0004_showroom_e_argumentos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "competitive_events",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("alert_id", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.String(length=64), nullable=True),
        sa.Column("comparable_version_id", sa.String(length=64), nullable=True),
        sa.Column("materiality", sa.String(length=10), nullable=False),
        sa.Column("pontos", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("rules_fired", sa.JSON(), nullable=True),
        sa.Column("parity_flips", sa.JSON(), nullable=True),
        sa.Column("priority_rank", sa.Integer(), nullable=False, server_default=sa.text("3000")),
        sa.Column("versao_das_regras", sa.String(length=40), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"]),
        sa.ForeignKeyConstraint(["comparable_version_id"], ["versions.id"]),
    )
    op.create_index("ix_competitive_events_alert_id", "competitive_events", ["alert_id"])
    op.create_index("ix_competitive_events_version_id", "competitive_events", ["version_id"])
    op.create_index("ix_competitive_events_materiality", "competitive_events", ["materiality"])
    # `priority_rank` indexado porque a fila ordena por ele em toda consulta.
    op.create_index("ix_competitive_events_priority_rank", "competitive_events", ["priority_rank"])
    op.create_index("ix_competitive_events_is_simulated", "competitive_events", ["is_simulated"])
    op.create_index("ix_competitive_events_criado_em", "competitive_events", ["criado_em"])


def downgrade() -> None:
    op.drop_index("ix_competitive_events_criado_em", table_name="competitive_events")
    op.drop_index("ix_competitive_events_is_simulated", table_name="competitive_events")
    op.drop_index("ix_competitive_events_priority_rank", table_name="competitive_events")
    op.drop_index("ix_competitive_events_materiality", table_name="competitive_events")
    op.drop_index("ix_competitive_events_version_id", table_name="competitive_events")
    op.drop_index("ix_competitive_events_alert_id", table_name="competitive_events")
    op.drop_table("competitive_events")
