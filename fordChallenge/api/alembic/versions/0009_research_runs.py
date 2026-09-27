"""O Pesquisador: `research_runs` e `research_events`.

**Por que a trilha é uma tabela, e não um log.** A promessa do SpecRadar é que o que se vê
na tela é o que aconteceu. O painel ao vivo mostra cada consulta, cada URL considerada e o
motivo de cada descarte; se isso vivesse só num arquivo de log, a auditoria três dias
depois dependeria de alguém ter guardado o arquivo — e de saber lê-lo.

`research_events` guarda **inclusive as URLs descartadas**, com o motivo. Mostrar só o que
deu certo faria a tela parecer mais limpa e a pesquisa, menos conferível.

`motivo_da_parada` é `NOT NULL` por padrão vazio, mas o código nunca grava vazio: "acabou"
não é resposta, e a diferença entre "a fonte não tem" e "não deu tempo" é o produto.

Tipos escolhidos para rodar igual em Postgres 16 e SQLite, como nas migrações anteriores.

Revision ID: 0009_research_runs
Revises: 0008_worker_heartbeat
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_research_runs"
down_revision: str | None = "0008_worker_heartbeat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("marca", sa.String(length=80), nullable=False),
        sa.Column("modelo", sa.String(length=120), nullable=False),
        sa.Column("versao", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("version_id", sa.String(length=64), sa.ForeignKey("versions.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="executando"),
        sa.Column("provedor_de_busca", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("motivo_da_parada", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("rodadas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paginas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consultas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("campos_com_valor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("campos_alvo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("segundos", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("custo_brl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("erro", sa.String(length=2000), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("concluido_em", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_research_runs_status", "research_runs", ["status"])
    op.create_index("ix_research_runs_version_id", "research_runs", ["version_id"])

    op.create_table(
        "research_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id", sa.String(length=64), sa.ForeignKey("research_runs.id"), nullable=False
        ),
        sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("texto", sa.String(length=1000), nullable=False),
        sa.Column("etiqueta", sa.String(length=12), nullable=False, server_default="FATO"),
        sa.Column("rodada", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("decorrido", sa.Float(), nullable=False, server_default="0"),
        sa.Column("dados", sa.JSON(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_research_events_run_id", "research_events", ["run_id"])
    op.create_index("ix_research_events_tipo", "research_events", ["tipo"])


def downgrade() -> None:
    op.drop_index("ix_research_events_tipo", table_name="research_events")
    op.drop_index("ix_research_events_run_id", table_name="research_events")
    op.drop_table("research_events")
    op.drop_index("ix_research_runs_version_id", table_name="research_runs")
    op.drop_index("ix_research_runs_status", table_name="research_runs")
    op.drop_table("research_runs")
