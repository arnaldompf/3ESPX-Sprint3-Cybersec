"""O sinal de vida do worker.

**O defeito.** Um avaliador pediu o documento do cliente e a tela girou até desistir. O
worker tinha morrido, e **nada no sistema sabia disso**: nem quem olhava a tela, nem
`/health`, nem quem administra a máquina. A tela dizia "quem cuida da máquina precisa
religar o processador de fila" — jargão, e inútil: quem lê aquela frase é um vendedor.

**Por que uma tabela nova, e não uma coluna em `jobs`.** `jobs.atualizado_em` só se move
quando existe job. Com a fila vazia — o estado normal — não há linha para carimbar, e
"nenhum job recente" fica indistinguível de "worker morto". O batimento é gravado **mesmo
sem trabalho a fazer**, e é exatamente essa a informação que faltava.

Uma linha só, com `id` fixo: a pergunta é "está vivo agora?", não "esteve vivo quando?".

`sa.String` e `sa.DateTime` sem timezone, como nas migrações anteriores: roda igual em
Postgres 16 e SQLite.

Revision ID: 0008_worker_heartbeat
Revises: 0007_tipo_de_afirmacao
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_worker_heartbeat"
down_revision: str | None = "0007_tipo_de_afirmacao"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeat",
        sa.Column("id", sa.String(length=20), primary_key=True),
        sa.Column("visto_em", sa.DateTime(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("jobs_concluidos", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeat")
