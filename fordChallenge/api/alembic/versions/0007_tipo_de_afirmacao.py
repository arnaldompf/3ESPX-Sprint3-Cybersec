"""O tipo da afirmação na evidência: declarado × medido × listado.

**O defeito, como ele aparecia na tela.** A ficha da Ranger Raptor mostra dois valores para
a aceleração 0–100 — 5,8 s e 6,5 s — e escrevia, ao lado, *"As fontes divergem. Os dois
valores, com a evidência de cada:"*. Só que **a fonte é uma só**: a mesma matéria da
Autoesporte registra o número que a Ford declara e o que a revista cronometrou. As duas
evidências têm a mesma `source_url`, byte a byte.

Não são duas fontes discordando; é uma fonte registrando duas coisas diferentes — e a
diferença entre elas é justamente o argumento que a página oferece a quem vende. Chamar
isso de "as fontes divergem" erra o fato e joga fora o argumento.

Faltava onde guardar a distinção: `evidences` tinha `source_url`, `tier`, `quote`,
`captured_at`, `raw_value`, `snapshot_id` e `page`, e nada que dissesse **o que a fonte
estava fazendo** ao dizer aquele número.

**Nullable e sem `server_default`, de propósito.** Um default `"listado"` afirmaria, em
toda evidência já gravada, algo que ninguém observou — e o produto inteiro se apoia em não
fazer isso. `NULL` aqui é `desconhecido`, que é estado de primeira classe: o tipo só entra
quando um termo literal do trecho verbatim o sustenta (`pipeline/claim_type.py`).

`sa.String` sem sintaxe de dialeto, como nas migrações anteriores: roda igual em
Postgres 16 e SQLite.

Revision ID: 0007_tipo_de_afirmacao
Revises: 0006_nomes_de_versao_canonicos
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_tipo_de_afirmacao"
down_revision: str | None = "0006_nomes_de_versao_canonicos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evidences",
        sa.Column("tipo_de_afirmacao", sa.String(length=12), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evidences", "tipo_de_afirmacao")
