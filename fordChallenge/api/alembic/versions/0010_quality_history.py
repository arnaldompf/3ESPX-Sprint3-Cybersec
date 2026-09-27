"""Observações e decisões auditáveis, sem alterar o schema público de especificações."""
from alembic import op
import sqlalchemy as sa

revision = '0010_quality_history'
down_revision = '0009_research_runs'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('versions', sa.Column('mercado', sa.String(8), nullable=False, server_default='BR'))
    op.add_column('versions', sa.Column('identidade_estado', sa.String(40), nullable=False,
                                      server_default='pendente_reavaliacao'))
    op.add_column('versions', sa.Column('configuracao_json', sa.JSON(), nullable=False,
                                      server_default='{}'))
    op.create_table('field_observations',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('version_id', sa.String(), sa.ForeignKey('versions.id'), nullable=False),
        sa.Column('field', sa.String(), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False, unique=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('validation', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_field_observations_version_id', 'field_observations', ['version_id'])
    op.create_table('field_decisions',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('version_id', sa.String(), sa.ForeignKey('versions.id'), nullable=False),
        sa.Column('field', sa.String(), nullable=False),
        sa.Column('policy_version', sa.String(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('observation_ids', sa.JSON(), nullable=False),
        sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_field_decisions_version_id', 'field_decisions', ['version_id'])


def downgrade():
    op.drop_table('field_decisions')
    op.drop_table('field_observations')
    with op.batch_alter_table('versions') as batch:
        batch.drop_column('configuracao_json')
        batch.drop_column('identidade_estado')
        batch.drop_column('mercado')
