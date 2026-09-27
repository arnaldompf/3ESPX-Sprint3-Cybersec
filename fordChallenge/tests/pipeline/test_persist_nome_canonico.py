"""`resolver_version_id` acha a versão mesmo quando a fonte escreve o nome de outro jeito.

O defeito medido em 11/09/2026, antes desta regra existir: `specradar extract Chevrolet S10
"High Country" --persistir` imprimia **17 campos com valor** e gravava **zero**. O
resolvedor devolvia `matched_version="S10 High Country"` (o nome como a página da GM
escreve), o catálogo guardava `"High Country"` (o canônico, desde a migração 0006), a busca
por nome exato não achava nada e a ficha ia para o lixo com um aviso no fim da saída.

A segunda tentativa não afrouxa nada: é a mesma função determinística dos dois lados. Os
testes abaixo prendem as duas pontas — que ela acha o que é o mesmo carro, e que ela
**não** escolhe quando há ambiguidade.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlmodel import Session, SQLModel, create_engine

from pipeline.persist import resolver_version_id
from pipeline.run import JobContext


@pytest.fixture
def sessao(tmp_path: Path):
    from api.app.models import Brand, VehicleModel, Version  # noqa: F401  (registra as tabelas)

    motor = create_engine(f"sqlite:///{(tmp_path / 'persist.db').as_posix()}")
    SQLModel.metadata.create_all(motor)
    with Session(motor) as s:
        yield s


def _catalogo(s: Session, *nomes: str) -> dict[str, str]:
    from api.app.models import Brand, VehicleModel, Version

    marca = Brand(nome="Chevrolet")
    s.add(marca)
    s.flush()
    modelo = VehicleModel(brand_id=marca.id, nome="S10")
    s.add(modelo)
    s.flush()
    ids: dict[str, str] = {}
    for nome in nomes:
        versao = Version(model_id=modelo.id, nome_exato=nome, ano_modelo=2027, in_lineup=True)
        s.add(versao)
        s.flush()
        ids[nome] = versao.id
    s.commit()
    return ids


class _Resolucao:
    """O mínimo que `resolver_version_id` lê da resolução."""

    def __init__(self, matched_version: str) -> None:
        self.matched_version = matched_version


def _contexto(versao: str, matched: str) -> JobContext:
    ctx = JobContext(marca="Chevrolet", modelo="S10", versao=versao)
    ctx.resolucao = _Resolucao(matched)  # type: ignore[assignment]
    return ctx


def test_acha_pelo_nome_exato_quando_ele_bate(sessao: Session) -> None:
    ids = _catalogo(sessao, "High Country")
    achado = resolver_version_id(sessao, _contexto("High Country", "High Country"))
    assert achado == ids["High Country"]


def test_acha_pelo_nome_canonico_quando_a_fonte_repete_o_modelo(sessao: Session) -> None:
    """O caso que perdia a ficha inteira da S10."""
    ids = _catalogo(sessao, "High Country")
    achado = resolver_version_id(sessao, _contexto("High Country", "S10 High Country"))
    assert achado == ids["High Country"]


def test_nao_confunde_versoes_diferentes(sessao: Session) -> None:
    _catalogo(sessao, "LTZ", "Z71")
    assert resolver_version_id(sessao, _contexto("Trail Boss", "S10 Trail Boss")) is None


def test_nome_exato_vence_a_chave_canonica(sessao: Session) -> None:
    """Banco ainda não migrado tem as duas grafias; a exata é a resposta certa."""
    ids = _catalogo(sessao, "High Country", "S10 High Country")
    achado = resolver_version_id(sessao, _contexto("High Country", "S10 High Country"))
    assert achado == ids["S10 High Country"]


def test_ambiguidade_nao_e_resolvida_no_sorteio(sessao: Session) -> None:
    """Duas linhas com a mesma chave e nenhuma com o nome exato: não se escolhe.

    Gravar numa das duas por ordem de consulta poria a ficha da S10 num registro ou no
    outro conforme o dia. O erro com o nome do veículo é o que leva alguém a rodar a
    migração 0006, que é a correção de verdade.
    """
    _catalogo(sessao, "High Country", "S10 High Country")
    assert resolver_version_id(sessao, _contexto("High Country", "HIGH COUNTRY")) is None


def test_version_id_explicito_continua_vencendo(sessao: Session) -> None:
    ids = _catalogo(sessao, "High Country")
    ctx = _contexto("High Country", "outra coisa qualquer")
    ctx.version_id = ids["High Country"]
    assert resolver_version_id(sessao, ctx) == ids["High Country"]


def test_a_data_nao_entra_na_conta(sessao: Session) -> None:
    """Guarda-chuva: o casamento é por nome, não por `criado_em`."""
    from api.app.models import Version

    ids = _catalogo(sessao, "High Country")
    linha = sessao.get(Version, ids["High Country"])
    assert linha is not None
    linha.criado_em = dt.datetime(2020, 1, 1)
    sessao.add(linha)
    sessao.commit()
    assert resolver_version_id(sessao, _contexto("High Country", "S10 High Country")) == linha.id


def test_a_consulta_nao_vaza_para_outro_modelo(sessao: Session) -> None:
    from api.app.models import Brand, VehicleModel, Version

    _catalogo(sessao, "High Country")
    outra = Brand(nome="Toyota")
    sessao.add(outra)
    sessao.flush()
    hilux = VehicleModel(brand_id=outra.id, nome="Hilux")
    sessao.add(hilux)
    sessao.flush()
    sessao.add(
        Version(model_id=hilux.id, nome_exato="High Country", ano_modelo=2027, in_lineup=True)
    )
    sessao.commit()

    achado = resolver_version_id(sessao, _contexto("High Country", "S10 High Country"))
    with sessao.connection() as conexao:
        marca = conexao.execute(
            sa.text(
                "SELECT b.nome FROM versions v JOIN models m ON m.id = v.model_id "
                "JOIN brands b ON b.id = m.brand_id WHERE v.id = :i"
            ),
            {"i": achado},
        ).scalar_one()
    assert marca == "Chevrolet"
