"""A migração 0006 funde as duplicatas do catálogo e sabe voltar atrás.

Migração de dados é o tipo de código que roda uma vez, em produção, sem ninguém olhando.
Este teste roda as duas direções num SQLite descartável e compara o **antes** com o
**depois do downgrade**, linha a linha: se a volta não é idêntica à ida, a migração não é
reversível, por mais que o docstring diga que é.

O cenário é o do catálogo real: uma versão com ficha e uma vazia para o mesmo carro, com o
código FIPE na vazia — que é a combinação que apaga informação se a fusão for ingênua.
"""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

RAIZ = Path(__file__).resolve().parents[2]
ANTERIOR = "0005_competitive_events"
ESTA = "0006_nomes_de_versao_canonicos"


def _config(url: str) -> Config:
    config = Config(str(RAIZ / "api" / "alembic.ini"))
    config.set_main_option("script_location", str(RAIZ / "api" / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _id() -> str:
    return uuid.uuid4().hex


@pytest.fixture
def banco(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    arquivo = tmp_path / "migracao.db"
    url = f"sqlite:///{arquivo.as_posix()}"
    # `env.py` lê a URL do ambiente; sem isto a migração iria para o banco de dev.
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _fotografia(motor: sa.Engine) -> list[tuple]:
    with motor.connect() as conexao:
        return [
            tuple(linha)
            for linha in conexao.execute(
                sa.text(
                    "SELECT id, model_id, nome_exato, ano_modelo, codigo_fipe, in_lineup "
                    "FROM versions ORDER BY id"
                )
            ).all()
        ]


def _semear_catalogo_com_duplicatas(motor: sa.Engine) -> dict[str, str]:
    """Uma S10 em duas linhas: a que tem ficha chama-se `S10 High Country`, a vazia tem a FIPE."""
    ids = {
        "marca": _id(),
        "modelo": _id(),
        "com_ficha": _id(),
        "vazia": _id(),
        "outra": _id(),
    }
    agora = dt.datetime(2026, 9, 10, 12, 0, 0)
    with motor.begin() as conexao:
        conexao.execute(
            sa.text("INSERT INTO brands (id, nome, criado_em) VALUES (:i, 'Chevrolet', :q)"),
            {"i": ids["marca"], "q": agora},
        )
        conexao.execute(
            sa.text(
                "INSERT INTO models (id, brand_id, nome, criado_em) VALUES (:i, :b, 'S10', :q)"
            ),
            {"i": ids["modelo"], "b": ids["marca"], "q": agora},
        )
        for chave, nome, fipe in (
            ("com_ficha", "S10 High Country", None),
            ("vazia", "High Country", "004464-4"),
            ("outra", "S10 LTZ", None),
        ):
            conexao.execute(
                sa.text(
                    "INSERT INTO versions (id, model_id, nome_exato, ano_modelo, codigo_fipe, "
                    "in_lineup, criado_em) VALUES (:i, :m, :n, 2027, :f, 1, :q)"
                ),
                {"i": ids[chave], "m": ids["modelo"], "n": nome, "f": fipe, "q": agora},
            )
        conexao.execute(
            sa.text(
                "INSERT INTO spec_values (id, version_id, field, value_json, status, "
                "confidence, criado_em, atualizado_em) VALUES (:i, :v, 'potencia_cv', '207', "
                "'verificado', 0.9, :q, :q)"
            ),
            {"i": _id(), "v": ids["com_ficha"], "q": agora},
        )
    return ids


def test_funde_duplicata_mantendo_a_que_tem_ficha(banco: str) -> None:
    config = _config(banco)
    command.upgrade(config, ANTERIOR)
    motor = sa.create_engine(banco)
    ids = _semear_catalogo_com_duplicatas(motor)

    command.upgrade(config, ESTA)

    with motor.connect() as conexao:
        linhas = conexao.execute(
            sa.text("SELECT id, nome_exato, codigo_fipe FROM versions ORDER BY nome_exato")
        ).all()
    nomes = [linha[1] for linha in linhas]
    assert nomes == ["High Country", "LTZ"], "o modelo não pode continuar repetido no nome"

    sobrevivente = next(linha for linha in linhas if linha[1] == "High Country")
    assert sobrevivente[0] == ids["com_ficha"], "quem tem a ficha é quem fica"
    assert sobrevivente[2] == "004464-4", "o código FIPE da linha apagada não se perde"

    with motor.connect() as conexao:
        campos = conexao.execute(
            sa.text("SELECT COUNT(*) FROM spec_values WHERE version_id = :v"),
            {"v": ids["com_ficha"]},
        ).scalar_one()
    assert campos == 1, "a ficha continua apontando para a versão que sobreviveu"


def test_downgrade_devolve_o_banco_exatamente_como_estava(banco: str) -> None:
    config = _config(banco)
    command.upgrade(config, ANTERIOR)
    motor = sa.create_engine(banco)
    _semear_catalogo_com_duplicatas(motor)

    antes = _fotografia(motor)
    command.upgrade(config, ESTA)
    assert _fotografia(motor) != antes, "o teste não prova nada se a ida não mudou nada"
    command.downgrade(config, ANTERIOR)

    assert _fotografia(motor) == antes


def test_downgrade_apaga_as_tabelas_de_backup(banco: str) -> None:
    config = _config(banco)
    command.upgrade(config, ANTERIOR)
    motor = sa.create_engine(banco)
    _semear_catalogo_com_duplicatas(motor)
    command.upgrade(config, ESTA)
    command.downgrade(config, ANTERIOR)

    with motor.connect() as conexao:
        tabelas = set(sa.inspect(conexao).get_table_names())
    assert "version_name_backup" not in tabelas
    assert "version_merge_backup" not in tabelas


def test_repontua_as_referencias_da_linha_absorvida(banco: str) -> None:
    """Se a duplicata tiver dado, ele migra para a sobrevivente em vez de sumir."""
    config = _config(banco)
    command.upgrade(config, ANTERIOR)
    motor = sa.create_engine(banco)
    ids = _semear_catalogo_com_duplicatas(motor)
    alerta = _id()
    with motor.begin() as conexao:
        conexao.execute(
            sa.text(
                "INSERT INTO alerts (id, type, version_id, field, created_at, lido, "
                "tratado, is_simulated) VALUES (:i, 'preco_tabela', :v, "
                "'preco_sugerido_brl', :q, 0, 0, 0)"
            ),
            {"i": alerta, "v": ids["vazia"], "q": dt.datetime(2026, 9, 10, 12, 0, 0)},
        )

    command.upgrade(config, ESTA)

    with motor.connect() as conexao:
        dono = conexao.execute(
            sa.text("SELECT version_id FROM alerts WHERE id = :i"), {"i": alerta}
        ).scalar_one()
    assert dono == ids["com_ficha"]

    command.downgrade(config, ANTERIOR)
    with motor.connect() as conexao:
        dono = conexao.execute(
            sa.text("SELECT version_id FROM alerts WHERE id = :i"), {"i": alerta}
        ).scalar_one()
    assert dono == ids["vazia"], "a volta devolve o alerta para a versão de origem"
