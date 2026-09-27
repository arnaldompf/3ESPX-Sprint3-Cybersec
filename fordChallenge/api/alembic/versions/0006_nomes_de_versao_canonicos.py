"""Nomes de versão canônicos e fusão das duplicatas do catálogo.

**O defeito, como ele aparecia na tela.** O rótulo de um veículo é
`marca + modelo + nome_exato` (sete serviços montam essa string). Com `nome_exato` repetindo
o modelo, a tela mostrava **"Chevrolet S10 S10 High Country"**. Pior: o mesmo carro estava
no catálogo **duas vezes** — `"High Country"` (zero campos) e `"S10 High Country"` (a ficha
inteira), `"SRX Plus AT"` (a ficha) e `"SRX Plus AT (Cabine Dupla)"` (zero campos). Os
seletores ordenam por nome, então a opção oferecida primeiro era, nos dois casos, a linha
**vazia** — e era daí que vinha o painel de cenário sem preço no Simulador.

**O que esta migração faz.** Para cada versão, calcula o nome canônico
(`pipeline.version_names`). Quando duas versões do mesmo modelo e ano-modelo chegam ao
mesmo nome, elas são a mesma versão: **sobrevive a que tem ficha** (mais `spec_values`,
desempatando por mais evidência e, por fim, pela mais antiga), as referências da outra são
repontuadas para ela, o código FIPE não se perde e a linha vazia é removida.

**Por que ela é reversível de verdade.** Antes de escrever qualquer coisa,
`version_name_backup` recebe uma linha por versão existente, com o nome e o código FIPE como
estavam. O `downgrade` devolve nome e FIPE, recria com o mesmo `id` as linhas removidas e
desfaz cada repontuação, registrada uma a uma em `version_merge_backup`. Migração de dados
sem volta é migração que ninguém tem coragem de rodar.

A ordem do `downgrade` custou uma execução para aparecer e está comentada lá: recriar a
linha removida antes de devolver os nomes viola a única de
`(model_id, nome_exato, ano_modelo)`, porque a sobrevivente ainda ocupa o nome canônico.

Tipos escolhidos para rodar igual em Postgres 16 e SQLite, como nas migrações anteriores:
`sa.String`, `sa.DateTime` sem timezone, nenhuma sintaxe específica de dialeto.

Revision ID: 0006_nomes_de_versao_canonicos
Revises: 0005_competitive_events
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from pipeline.version_names import nome_canonico_de_versao

revision: str = "0006_nomes_de_versao_canonicos"
down_revision: str | None = "0005_competitive_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Cada coluna que aponta para `versions.id`. Repontuar é o que permite apagar a duplicata
#: sem perder nada; a lista é explícita (e não descoberta por reflexão) para que acrescentar
#: uma tabela nova com FK para `versions` exija olhar para cá em vez de falhar em silêncio.
REFERENCIAS: tuple[tuple[str, str], ...] = (
    ("spec_values", "version_id"),
    ("extractions", "version_id"),
    ("alerts", "version_id"),
    ("equivalents", "version_id"),
    ("equivalents", "ford_version_id"),
    ("internal_references", "version_id"),
    ("showroom_sessions", "ford_version_id"),
    ("showroom_sessions", "competitor_version_id"),
    ("competitive_events", "version_id"),
    ("competitive_events", "comparable_version_id"),
)


def _referencias_presentes(conexao: sa.Connection) -> list[tuple[str, str]]:
    """Só os pares (tabela, coluna) que existem neste banco."""
    inspetor = sa.inspect(conexao)
    tabelas = set(inspetor.get_table_names())
    presentes: list[tuple[str, str]] = []
    for tabela, coluna in REFERENCIAS:
        if tabela in tabelas and coluna in {c["name"] for c in inspetor.get_columns(tabela)}:
            presentes.append((tabela, coluna))
    return presentes


def upgrade() -> None:
    conexao = op.get_bind()

    op.create_table(
        "version_name_backup",
        sa.Column("version_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("nome_anterior", sa.String(length=200), nullable=False),
        sa.Column("codigo_fipe_anterior", sa.String(length=32), nullable=True),
        sa.Column("removida", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        # A linha inteira, para poder recriá-la idêntica se ela for a absorvida.
        sa.Column("model_id", sa.String(length=64), nullable=True),
        sa.Column("ano_modelo", sa.Integer(), nullable=True),
        sa.Column("in_lineup", sa.Boolean(), nullable=True),
        sa.Column("lineup_checked_at", sa.DateTime(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=True),
        sa.Column("absorvida_por", sa.String(length=64), nullable=True),
    )
    op.create_table(
        "version_merge_backup",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("tabela", sa.String(length=64), nullable=False),
        sa.Column("coluna", sa.String(length=64), nullable=False),
        sa.Column("linha_id", sa.String(length=64), nullable=False),
        sa.Column("version_id_anterior", sa.String(length=64), nullable=False),
    )

    versoes = (
        conexao.execute(
            sa.text(
                "SELECT v.id, v.model_id, v.nome_exato, v.ano_modelo, v.codigo_fipe, "
                "       v.in_lineup, v.lineup_checked_at, v.criado_em, m.nome AS modelo "
                "FROM versions v JOIN models m ON m.id = v.model_id"
            )
        )
        .mappings()
        .all()
    )

    # 1) a fotografia do antes, COMPLETA e antes de qualquer escrita. É o que faz o
    #    `downgrade` devolver o banco exatamente como estava, e não "quase".
    for linha in versoes:
        conexao.execute(
            sa.text(
                "INSERT INTO version_name_backup (version_id, nome_anterior, "
                "codigo_fipe_anterior, removida, model_id, ano_modelo, in_lineup, "
                "lineup_checked_at, criado_em) VALUES (:id, :nome, :fipe, 0, :model_id, "
                ":ano, :lineup, :conferido, :criado)"
            ),
            {
                "id": linha["id"],
                "nome": linha["nome_exato"],
                "fipe": linha["codigo_fipe"],
                "model_id": linha["model_id"],
                "ano": linha["ano_modelo"],
                "lineup": linha["in_lineup"],
                "conferido": linha["lineup_checked_at"],
                "criado": linha["criado_em"],
            },
        )

    # 2) o nome canônico de cada versão, e quem cai em qual chave
    canonicos: dict[str, str] = {}
    por_chave: dict[tuple[str, int, str], list[dict]] = {}
    for linha in versoes:
        canonico = nome_canonico_de_versao(linha["modelo"], linha["nome_exato"])
        canonicos[linha["id"]] = canonico
        chave = (linha["model_id"], int(linha["ano_modelo"]), canonico.lower())
        por_chave.setdefault(chave, []).append(dict(linha))

    referencias = _referencias_presentes(conexao)
    tem_spec_values = any(t == "spec_values" for t, _ in referencias)

    def _riqueza(version_id: str) -> tuple[int, int]:
        """(campos com valor, campos com evidência) — o critério de quem sobrevive."""
        if not tem_spec_values:
            return (0, 0)
        achado = (
            conexao.execute(
                sa.text(
                    "SELECT COUNT(*) AS campos, "
                    "       SUM(CASE WHEN evidence_id IS NOT NULL THEN 1 ELSE 0 END) AS com_evid "
                    "FROM spec_values WHERE version_id = :v"
                ),
                {"v": version_id},
            )
            .mappings()
            .first()
        )
        return (int(achado["campos"] or 0), int(achado["com_evid"] or 0))

    # 3) fusão das duplicatas
    for grupo in por_chave.values():
        if len(grupo) < 2:
            continue
        # Sobrevive a mais rica; empate pela mais antiga, que é a estável entre execuções.
        ordenadas = sorted(
            grupo,
            key=lambda linha: (
                -_riqueza(linha["id"])[0],
                -_riqueza(linha["id"])[1],
                str(linha["criado_em"] or ""),
                linha["id"],
            ),
        )
        vencedora, perdedoras = ordenadas[0], ordenadas[1:]
        for perdedora in perdedoras:
            for tabela, coluna in referencias:
                alvos = (
                    conexao.execute(
                        sa.text(f"SELECT id FROM {tabela} WHERE {coluna} = :v"),  # noqa: S608
                        {"v": perdedora["id"]},
                    )
                    .scalars()
                    .all()
                )
                for linha_id in alvos:
                    conexao.execute(
                        sa.text(
                            "INSERT INTO version_merge_backup "
                            "(tabela, coluna, linha_id, version_id_anterior) "
                            "VALUES (:t, :c, :l, :v)"
                        ),
                        {"t": tabela, "c": coluna, "l": linha_id, "v": perdedora["id"]},
                    )
                if alvos:
                    conexao.execute(
                        sa.text(
                            f"UPDATE {tabela} SET {coluna} = :novo WHERE {coluna} = :velho"  # noqa: S608, E501
                        ),
                        {"novo": vencedora["id"], "velho": perdedora["id"]},
                    )
            # O código FIPE identifica o VEÍCULO, não a linha do catálogo: perdê-lo ao
            # apagar a duplicata tiraria da S10 o código que a FIPE usa para cotá-la.
            if perdedora["codigo_fipe"] and not vencedora["codigo_fipe"]:
                conexao.execute(
                    sa.text("UPDATE versions SET codigo_fipe = :f WHERE id = :v"),
                    {"f": perdedora["codigo_fipe"], "v": vencedora["id"]},
                )
                vencedora["codigo_fipe"] = perdedora["codigo_fipe"]
            conexao.execute(
                sa.text(
                    "UPDATE version_name_backup SET removida = 1, absorvida_por = :absorvida "
                    "WHERE version_id = :id"
                ),
                {"absorvida": vencedora["id"], "id": perdedora["id"]},
            )
            conexao.execute(sa.text("DELETE FROM versions WHERE id = :v"), {"v": perdedora["id"]})

    # 4) renomeia o que sobrou
    for version_id, canonico in canonicos.items():
        conexao.execute(
            sa.text("UPDATE versions SET nome_exato = :novo WHERE id = :id AND nome_exato <> :novo"),
            {"novo": canonico, "id": version_id},
        )


def downgrade() -> None:
    conexao = op.get_bind()
    if "version_name_backup" not in set(sa.inspect(conexao).get_table_names()):
        return

    fotografia = (
        conexao.execute(
            sa.text(
                "SELECT version_id, nome_anterior, codigo_fipe_anterior, removida, model_id, "
                "       ano_modelo, in_lineup, lineup_checked_at, criado_em "
                "FROM version_name_backup"
            )
        )
        .mappings()
        .all()
    )

    # 1) devolve nome e FIPE das que sobreviveram. Vem PRIMEIRO: recriar a linha absorvida
    #    antes disso viola a única de (model_id, nome_exato, ano_modelo), porque a
    #    sobrevivente ainda está ocupando o nome canônico que a absorvida vai querer de volta.
    for linha in fotografia:
        if linha["removida"]:
            continue
        conexao.execute(
            sa.text("UPDATE versions SET nome_exato = :nome, codigo_fipe = :fipe WHERE id = :id"),
            {
                "nome": linha["nome_anterior"],
                "fipe": linha["codigo_fipe_anterior"],
                "id": linha["version_id"],
            },
        )

    # 2) recria as linhas absorvidas, com o mesmo id
    for linha in fotografia:
        if not linha["removida"]:
            continue
        conexao.execute(
            sa.text(
                "INSERT INTO versions (id, model_id, nome_exato, ano_modelo, codigo_fipe, "
                "in_lineup, lineup_checked_at, criado_em) VALUES (:id, :model_id, :nome, "
                ":ano, :fipe, :lineup, :conferido, :criado)"
            ),
            {
                "id": linha["version_id"],
                "model_id": linha["model_id"],
                "nome": linha["nome_anterior"],
                "ano": linha["ano_modelo"],
                "fipe": linha["codigo_fipe_anterior"],
                "lineup": linha["in_lineup"],
                "conferido": linha["lineup_checked_at"],
                "criado": linha["criado_em"],
            },
        )

    # 3) desfaz as repontuações, na ordem inversa à que foram feitas
    movimentos = (
        conexao.execute(
            sa.text(
                "SELECT tabela, coluna, linha_id, version_id_anterior "
                "FROM version_merge_backup ORDER BY id DESC"
            )
        )
        .mappings()
        .all()
    )
    for movimento in movimentos:
        conexao.execute(
            sa.text(
                f"UPDATE {movimento['tabela']} SET {movimento['coluna']} = :v "  # noqa: S608
                "WHERE id = :l"
            ),
            {"v": movimento["version_id_anterior"], "l": movimento["linha_id"]},
        )

    op.drop_table("version_merge_backup")
    op.drop_table("version_name_backup")
