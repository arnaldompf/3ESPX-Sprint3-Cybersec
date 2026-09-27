"""WP-03: modelo de dados inicial (13 tabelas de docs/02).

Escrita à mão, não gerada: o autogenerate do Alembic é útil para conferir, mas a primeira
migração define o contrato do banco e vale mais legível do que automática. A ordem de
criação vai de pai para filha (`api.app.models.ORDEM_DAS_TABELAS`); o `downgrade` percorre
ao contrário e derruba tudo, porque `downgrade base` → `upgrade head` é critério de aceite.

Tipos escolhidos para rodar igual em Postgres 16 e SQLite: `sa.String` (sem `UUID` nativo),
`sa.JSON` (nunca `JSONB`), `sa.DateTime` sem timezone — o fuso é responsabilidade do lado
Python, que sempre grava UTC.

Revision ID: 0001_modelo_inicial
Revises: None
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_modelo_inicial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------------------------------------------------------------- catálogo
    op.create_table(
        "brands",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("nome", sa.String(length=80), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brands_nome", "brands", ["nome"], unique=True)

    op.create_table(
        "models",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("brand_id", sa.String(), nullable=False),
        sa.Column("nome", sa.String(length=80), nullable=False),
        sa.Column("segmento", sa.String(length=60), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brand_id", "nome", name="uq_models_brand_nome"),
    )
    op.create_index("ix_models_brand_id", "models", ["brand_id"], unique=False)

    op.create_table(
        "versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("nome_exato", sa.String(length=160), nullable=False),
        sa.Column("ano_modelo", sa.Integer(), nullable=False),
        sa.Column("codigo_fipe", sa.String(length=40), nullable=True),
        sa.Column("in_lineup", sa.Boolean(), nullable=False),
        sa.Column("lineup_checked_at", sa.DateTime(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", "nome_exato", "ano_modelo", name="uq_versions_nome_ano"),
    )
    op.create_index("ix_versions_model_id", "versions", ["model_id"], unique=False)
    op.create_index("ix_versions_ano_modelo", "versions", ["ano_modelo"], unique=False)
    op.create_index("ix_versions_codigo_fipe", "versions", ["codigo_fipe"], unique=False)

    # ------------------------------------------------------------------ coleta
    op.create_table(
        "sources",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("dominio", sa.String(length=200), nullable=False),
        sa.Column("robots_ok", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("motivo", sa.String(length=300), nullable=True),
        sa.Column("ultima_checagem_em", sa.DateTime(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.CheckConstraint("tier BETWEEN 1 AND 5", name="ck_sources_tier"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sources_url", "sources", ["url"], unique=True)
    op.create_index("ix_sources_dominio", "sources", ["dominio"], unique=False)
    op.create_index("ix_sources_status", "sources", ["status"], unique=False)

    # -------------------------------------------------------------- operação
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column("tentativas", sa.Integer(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.Column("iniciado_em", sa.DateTime(), nullable=True),
        sa.Column("concluido_em", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # Índice exigido pela spec: é por ele que o worker pega o próximo pendente.
    op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("ultimo_login_em", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"], unique=False)

    op.create_table(
        "snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("raw_path", sa.String(length=500), nullable=True),
        sa.Column("text_path", sa.String(length=500), nullable=True),
        sa.Column("screenshot_path", sa.String(length=500), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_snapshots_source_id", "snapshots", ["source_id"], unique=False)
    op.create_index("ix_snapshots_version_id", "snapshots", ["version_id"], unique=False)
    op.create_index("ix_snapshots_sha256", "snapshots", ["sha256"], unique=False)
    # Índice exigido pela spec: "o que esta URL dizia naquele dia" (auditoria e replay).
    op.create_index(
        "ix_snapshots_url_captured_at", "snapshots", ["url", "captured_at"], unique=False
    )

    op.create_table(
        "extractions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("modelo_llm", sa.String(length=120), nullable=False),
        sa.Column("prompt_versao", sa.String(length=40), nullable=True),
        sa.Column("tokens_entrada", sa.Integer(), nullable=False),
        sa.Column("tokens_saida", sa.Integer(), nullable=False),
        sa.Column("custo_usd", sa.Float(), nullable=False),
        sa.Column("latencia_ms", sa.Integer(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_extractions_job_id", "extractions", ["job_id"], unique=False)
    op.create_index("ix_extractions_version_id", "extractions", ["version_id"], unique=False)

    op.create_table(
        "evidences",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("snapshot_id", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("quote", sa.String(length=300), nullable=False),
        sa.Column("offset", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("raw_value", sa.String(length=300), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.CheckConstraint("tier BETWEEN 1 AND 5", name="ck_evidences_tier"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidences_snapshot_id", "evidences", ["snapshot_id"], unique=False)

    # -------------------------------------------------------------------- ficha
    op.create_table(
        "spec_values",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("field", sa.String(length=80), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=True),
        sa.Column("extraction_id", sa.String(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidences.id"]),
        sa.ForeignKeyConstraint(["extraction_id"], ["extractions.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Índice exigido pela spec: a leitura da ficha é sempre "campos desta versão".
    op.create_index(
        "ix_spec_values_version_field", "spec_values", ["version_id", "field"], unique=False
    )
    op.create_index("ix_spec_values_status", "spec_values", ["status"], unique=False)
    op.create_index("ix_spec_values_evidence_id", "spec_values", ["evidence_id"], unique=False)
    op.create_index("ix_spec_values_extraction_id", "spec_values", ["extraction_id"], unique=False)

    op.create_table(
        "synonyms",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("termo", sa.String(length=200), nullable=False),
        sa.Column("campo_canonico", sa.String(length=80), nullable=False),
        sa.Column("valor_canonico", sa.String(length=120), nullable=True),
        sa.Column("marca", sa.String(length=80), nullable=True),
        sa.Column("tipo", sa.String(length=10), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_synonyms_termo", "synonyms", ["termo"], unique=False)
    op.create_index("ix_synonyms_campo_canonico", "synonyms", ["campo_canonico"], unique=False)
    op.create_index("ix_synonyms_termo_tipo", "synonyms", ["termo", "tipo"], unique=False)

    # ------------------------------------------------------- alertas e auditoria
    op.create_table(
        "alerts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("field", sa.String(length=80), nullable=True),
        sa.Column("old", sa.JSON(), nullable=True),
        sa.Column("new", sa.JSON(), nullable=True),
        sa.Column("evidence_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("lido", sa.Boolean(), nullable=False),
        sa.Column("tratado", sa.Boolean(), nullable=False),
        sa.Column("tratado_em", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidences.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_type", "alerts", ["type"], unique=False)
    op.create_index("ix_alerts_version_id", "alerts", ["version_id"], unique=False)
    op.create_index("ix_alerts_evidence_id", "alerts", ["evidence_id"], unique=False)
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"], unique=False)

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("ator_email", sa.String(length=254), nullable=True),
        sa.Column("acao", sa.String(length=80), nullable=False),
        sa.Column("alvo_tipo", sa.String(length=40), nullable=True),
        sa.Column("alvo_id", sa.String(length=64), nullable=True),
        sa.Column("detalhe", sa.JSON(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"], unique=False)
    op.create_index("ix_audit_log_acao", "audit_log", ["acao"], unique=False)
    op.create_index("ix_audit_log_criado_em", "audit_log", ["criado_em"], unique=False)


def downgrade() -> None:
    """Derruba tudo, na ordem inversa. `drop_table` já remove os índices da tabela."""
    for tabela in (
        "audit_log",
        "alerts",
        "synonyms",
        "spec_values",
        "evidences",
        "extractions",
        "snapshots",
        "users",
        "jobs",
        "sources",
        "versions",
        "models",
        "brands",
    ):
        op.drop_table(tabela)
