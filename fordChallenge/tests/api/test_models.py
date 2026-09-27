"""Critérios de aceite da WP-03: modelo de dados, migração e seed.

Os testes valem contra **um SQLite descartável por teste** (fixture `sqlite_url` do
`tests/conftest.py`), nunca contra o banco de dev: seed é idempotente, mas apagar e
recriar o banco de alguém enquanto se roda a suíte não é.

Dois pontos merecem explicação, porque não são óbvios:

* a migração é exercida **pelo Alembic** (`command.upgrade`), não por
  `SQLModel.metadata.create_all`. O que roda em produção é a migração; se ela e os
  modelos divergirem, o teste tem de acusar — daí a comparação de nomes de tabela.
* a senha do admin nunca aparece literal aqui. Ela vem de `ADMIN_PASSWORD` (o
  `conftest` garante um valor de teste), porque segredo em código é proibido mesmo
  em teste.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, select

from pipeline.schema import Status

ROOT = Path(__file__).resolve().parent.parent.parent

#: As 13 tabelas de `docs/02` (Modelo de dados). `alembic_version` é da ferramenta.
TABELAS_ESPERADAS = {
    "brands",
    "models",
    "versions",
    "sources",
    "snapshots",
    "extractions",
    "spec_values",
    "evidences",
    "synonyms",
    "jobs",
    "users",
    "alerts",
    "audit_log",
}


def _config_alembic() -> Config:
    """Config do Alembic com `script_location` absoluto (o teste pode rodar de qualquer cwd)."""
    cfg = Config(str(ROOT / "api" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "api" / "alembic"))
    return cfg


@pytest.fixture
def banco_migrado(sqlite_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Banco vazio levado a `head` pelo Alembic, com `DATABASE_URL` apontando para ele."""
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    command.upgrade(_config_alembic(), "head")
    return sqlite_url


# --------------------------------------------------------------------------------------
# Engine e sessões
# --------------------------------------------------------------------------------------
def test_database_url_vem_do_ambiente(monkeypatch: pytest.MonkeyPatch):
    """Sem `DATABASE_URL`, cai no SQLite de dev — nunca em uma URL embutida com senha."""
    from api.app.db import URL_PADRAO, database_url

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url() == URL_PADRAO
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/outro.db")
    assert database_url() == "sqlite:///./data/outro.db"


def test_session_scope_faz_rollback_no_erro(sqlite_url: str, monkeypatch: pytest.MonkeyPatch):
    """Script que morre no meio não pode deixar meia carga gravada."""
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    from api.app.db import criar_engine, get_session, session_scope
    from api.app.models import Brand

    engine = criar_engine(sqlite_url)
    SQLModel.metadata.create_all(engine)
    engine.dispose()

    with pytest.raises(RuntimeError), session_scope(sqlite_url) as sessao:
        sessao.add(Brand(nome="Toyota"))
        raise RuntimeError("falha no meio da carga")

    # `get_session` é a dependência do FastAPI: sessão por request, commit de quem escreve.
    gerador = get_session()
    sessao = next(gerador)
    sessao.add(Brand(nome="Ford"))
    sessao.commit()
    with contextlib.suppress(StopIteration):
        next(gerador)

    with session_scope(sqlite_url) as sessao:
        nomes = {b.nome for b in sessao.exec(select(Brand))}
    assert nomes == {"Ford"}, "o rollback não desfez a inserção da transação que falhou"


# --------------------------------------------------------------------------------------
# Modelos (rápido: não toca no Alembic)
# --------------------------------------------------------------------------------------
def test_metadata_declara_as_treze_tabelas():
    import api.app.models  # noqa: F401  (registra as tabelas no metadata)

    assert set(SQLModel.metadata.tables) >= TABELAS_ESPERADAS


def test_indices_obrigatorios_estao_declarados():
    """`(version_id, field)`, `(url, captured_at)` e `jobs.status` são exigência da spec."""
    import api.app.models  # noqa: F401

    def colunas_dos_indices(tabela: str) -> list[list[str]]:
        return [[c.name for c in idx.columns] for idx in SQLModel.metadata.tables[tabela].indexes]

    assert ["version_id", "field"] in colunas_dos_indices("spec_values")
    assert ["url", "captured_at"] in colunas_dos_indices("snapshots")
    assert ["status"] in colunas_dos_indices("jobs")


def test_spec_values_aceita_todos_os_status_do_schema(sqlite_url: str):
    """`status` é o vocabulário de `pipeline.schema.Status` — inclusive os dois vazios."""
    from api.app.db import criar_engine
    from api.app.models import Brand, SpecValue, VehicleModel, Version

    engine = criar_engine(sqlite_url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sessao:
        marca = Brand(nome="Ford")
        sessao.add(marca)
        sessao.flush()
        modelo = VehicleModel(brand_id=marca.id, nome="Ranger")
        sessao.add(modelo)
        sessao.flush()
        versao = Version(model_id=modelo.id, nome_exato="Raptor 4WD AT", ano_modelo=2026)
        sessao.add(versao)
        sessao.flush()
        for i, status in enumerate(Status):
            sessao.add(
                SpecValue(
                    version_id=versao.id,
                    field=f"campo_{i}",
                    value_json=None,
                    status=status.value,
                    confidence=0.0,
                )
            )
        sessao.commit()
        gravados = {
            sv.status
            for sv in sessao.exec(select(SpecValue).where(SpecValue.version_id == versao.id))
        }
    engine.dispose()
    assert gravados == {s.value for s in Status}


def test_value_json_guarda_qualquer_valor_canonico(sqlite_url: str):
    """`value_json` recebe número, texto, booleano e lista — o canônico do WP-01 é heterogêneo."""
    from api.app.db import criar_engine
    from api.app.models import Brand, SpecValue, VehicleModel, Version

    engine = criar_engine(sqlite_url)
    SQLModel.metadata.create_all(engine)
    valores = [397, "Raptor", True, ["sport", "lama"]]
    with Session(engine) as sessao:
        marca = Brand(nome="Ford")
        sessao.add(marca)
        sessao.flush()
        modelo = VehicleModel(brand_id=marca.id, nome="Ranger")
        sessao.add(modelo)
        sessao.flush()
        versao = Version(model_id=modelo.id, nome_exato="Raptor 4WD AT", ano_modelo=2026)
        sessao.add(versao)
        sessao.flush()
        for i, valor in enumerate(valores):
            sessao.add(
                SpecValue(
                    version_id=versao.id,
                    field=f"campo_{i}",
                    value_json=valor,
                    status=Status.VERIFICADO.value,
                    confidence=0.9,
                )
            )
        sessao.commit()
        lidos = [
            sv.value_json
            for sv in sessao.exec(select(SpecValue).order_by(SpecValue.field))  # type: ignore[arg-type]
        ]
    engine.dispose()
    assert lidos == valores


# --------------------------------------------------------------------------------------
# Migração + seed (lentos: sobem o Alembic)
# --------------------------------------------------------------------------------------
@pytest.mark.slow
def test_migracao_cria_as_tabelas_e_os_indices(banco_migrado: str):
    from api.app.db import criar_engine

    engine = criar_engine(banco_migrado)
    inspetor = inspect(engine)
    tabelas = set(inspetor.get_table_names())
    indices = {
        tabela: [idx["column_names"] for idx in inspetor.get_indexes(tabela)]
        for tabela in ("spec_values", "snapshots", "jobs")
    }
    engine.dispose()

    faltando = TABELAS_ESPERADAS - tabelas
    assert not faltando, f"a migração não criou: {sorted(faltando)}"
    # A migração é escrita à mão; se um modelo novo não entrar nela, o banco de produção
    # fica sem a tabela e só se descobre em runtime. Aqui se descobre no teste.
    assert set(SQLModel.metadata.tables) >= TABELAS_ESPERADAS
    assert ["version_id", "field"] in indices["spec_values"]
    assert ["url", "captured_at"] in indices["snapshots"]
    assert ["status"] in indices["jobs"]


@pytest.mark.slow
def test_seed_em_banco_vazio_cria_marcas_sinonimos_e_admin(banco_migrado: str):
    from api.app.db import criar_engine
    from api.app.models import Brand, Synonym, User, Version
    from api.app.seed import main as seed_main

    assert seed_main() == 0

    engine = criar_engine(banco_migrado)
    with Session(engine) as sessao:
        marcas = {b.nome for b in sessao.exec(select(Brand))}
        sinonimos = list(sessao.exec(select(Synonym)))
        admins = list(sessao.exec(select(User).where(User.role == "admin")))
        versoes = {v.nome_exato for v in sessao.exec(select(Version))}
    engine.dispose()

    assert marcas == {"Ford", "Toyota", "Volkswagen", "Chevrolet"}
    assert len(sinonimos) > 20, f"esperado > 20 sinônimos, veio {len(sinonimos)}"
    # A semente tem sinônimo de campo e de valor; os dois têm de estar no banco.
    assert {s.tipo for s in sinonimos} == {"campo", "valor"}
    assert len(admins) == 1
    assert "Raptor 3.0 V6 Bi-turbo 4WD AT" in versoes


@pytest.mark.slow
def test_seed_e_idempotente(banco_migrado: str):
    from api.app.db import criar_engine
    from api.app.models import Brand, Synonym, User, VehicleModel, Version
    from api.app.seed import main as seed_main

    def contagens() -> dict[str, int]:
        engine = criar_engine(banco_migrado)
        with Session(engine) as sessao:
            saida = {
                tabela.__name__: len(list(sessao.exec(select(tabela))))
                for tabela in (Brand, VehicleModel, Version, Synonym, User)
            }
        engine.dispose()
        return saida

    assert seed_main() == 0
    primeira = contagens()
    assert seed_main() == 0
    assert contagens() == primeira


@pytest.mark.slow
def test_admin_nao_guarda_senha_em_texto_puro(banco_migrado: str):
    from api.app.db import criar_engine
    from api.app.models import User
    from api.app.seed import main as seed_main

    senha = os.environ["ADMIN_PASSWORD"]  # nunca literal no código (regra inviolável)
    assert seed_main() == 0

    engine = criar_engine(banco_migrado)
    with Session(engine) as sessao:
        admin = sessao.exec(select(User).where(User.email == os.environ["ADMIN_EMAIL"])).one()
    engine.dispose()

    assert admin.password_hash.startswith("$argon2"), "o hash tem de ser argon2"
    assert senha not in admin.password_hash
    assert admin.ativo is True
    assert admin.role == "admin"


@pytest.mark.slow
def test_downgrade_base_e_upgrade_head_sem_erro(sqlite_url: str, monkeypatch: pytest.MonkeyPatch):
    from api.app.db import criar_engine

    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    cfg = _config_alembic()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = criar_engine(sqlite_url)
    restantes = set(inspect(engine).get_table_names()) & TABELAS_ESPERADAS
    engine.dispose()
    assert not restantes, f"downgrade deixou tabelas para trás: {sorted(restantes)}"

    command.upgrade(cfg, "head")
    engine = criar_engine(sqlite_url)
    tabelas = set(inspect(engine).get_table_names())
    engine.dispose()
    assert tabelas >= TABELAS_ESPERADAS


@pytest.mark.slow
def test_seed_cria_sessoes_simuladas_todas_marcadas(
    banco_migrado: str, capsys: pytest.CaptureFixture[str]
):
    """`--simulated-sessions` passou a criar as sessões na WP-27, **todas marcadas**.

    Até a WP-26 este teste afirmava o contrário: o seed **avisava** que a opção era da
    WP-27 e não inventava dado de uso. O aviso era a resposta certa enquanto a tabela não
    existia — e o teste mudou de lado no dia em que ela passou a existir, que é o
    comportamento esperado de um teste que descreve intenção.

    O que **não** mudou: nenhuma linha sai sem `is_simulated=true`.
    """
    from sqlmodel import select

    from api.app.db import session_scope
    from api.app.models import ShowroomSession
    from api.app.seed import main as seed_main

    assert seed_main(simulated_sessions=5) == 0
    saida = capsys.readouterr().out
    assert "SIMULADA" in saida
    assert "is_simulated=true" in saida

    with session_scope() as sessao:
        linhas = sessao.exec(select(ShowroomSession)).all()
        assert len(linhas) == 5
        assert all(linha.is_simulated for linha in linhas)


# --------------------------------------------------------------------------------------
# Repositórios (finos: só falam com a sessão)
# --------------------------------------------------------------------------------------
def test_repositorios_fazem_upsert_sem_duplicar(sqlite_url: str):
    from api.app.db import criar_engine
    from api.app.models import JobStatus
    from api.app.repositories import brands, jobs, spec_values, versions

    engine = criar_engine(sqlite_url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sessao:
        marca = brands.upsert(sessao, nome="Ford")
        assert brands.upsert(sessao, nome="Ford").id == marca.id
        assert brands.get_by_nome(sessao, "Ford") is not None
        assert [b.nome for b in brands.listar(sessao)] == ["Ford"]

        modelo = brands.upsert_modelo(sessao, brand_id=marca.id, nome="Ranger")
        versao = versions.upsert(
            sessao, model_id=modelo.id, nome_exato="Raptor 4WD AT", ano_modelo=2026
        )
        assert (
            versions.upsert(
                sessao, model_id=modelo.id, nome_exato="Raptor 4WD AT", ano_modelo=2026
            ).id
            == versao.id
        )

        sv = spec_values.upsert(
            sessao,
            version_id=versao.id,
            field="potencia_cv",
            value_json=397,
            status=Status.VERIFICADO.value,
            confidence=0.9,
            unit="cv",
        )
        sv2 = spec_values.upsert(
            sessao,
            version_id=versao.id,
            field="potencia_cv",
            value_json=400,
            status=Status.DIVERGENTE.value,
            confidence=0.5,
        )
        assert sv.id == sv2.id
        assert sv2.value_json == 400
        assert len(spec_values.listar_por_versao(sessao, versao.id)) == 1

        job = jobs.criar(sessao, tipo="extract", payload={"version_id": versao.id})
        assert job.status == JobStatus.PENDENTE.value
        assert [j.id for j in jobs.listar_por_status(sessao, JobStatus.PENDENTE.value)] == [job.id]
        assert jobs.get(sessao, job.id) is not None
    engine.dispose()
