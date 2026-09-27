"""Regressões de aplicação, semântica, migração e publicação concorrente."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine, select

from api.app.models import Brand, FieldDecision, VehicleModel, Version
from api.app.services.spec_assembler import montar
from pipeline import deadline
from pipeline.persist import fundir_valores
from pipeline.schema import Evidence, SpecField, Status, empty_spec
from pipeline.semantics import rejection_reason, validate_number


@pytest.mark.parametrize(
    ("field", "value", "quote", "unit", "expected"),
    [
        ("airbags_qtd", 7, "Sete airbags de série", None, True),
        ("airbags_qtd", 6, "Sete airbags de série", None, False),
        ("preco_sugerido_brl", 499000, "R$ 499.0002", "BRL", True),
        ("torque_nm", 600, "Torque máximo de 61,2 kgfm", "Nm", True),
        ("torque_nm", 61.2, "Torque máximo de 61,2 kgfm", "Nm", False),
        ("potencia_cv", 250, "Potência 200 cv", "cv", False),
    ],
)
def test_numero_precisa_corresponder_ao_trecho(field, value, quote, unit, expected):
    assert validate_number(field, value, quote, unit) is expected


@pytest.mark.parametrize(
    ("field", "quote"),
    [
        ("deslocamento_l", "Capacidade de óleo: 6 litros"),
        ("rodas_aro_pol", "Acessório opcional: aro 15"),
        ("garantia_meses", "Garantia da bateria: 24 meses"),
        ("largura_mm", "Largura com espelhos: 2208 mm"),
        ("preco_sugerido_brl", "Oferta CNPJ R$ 299.000"),
    ],
)
def test_atributos_de_contexto_diferente_nao_sao_equivalentes(field, quote):
    assert rejection_reason(field, quote)


def test_tela_multimidia_nao_e_aro():
    assert rejection_reason("rodas_aro_pol", "Sync 4, 12 (pol.), Apple CarPlay")


def test_lista_de_adas_precisa_de_prova_de_cada_item():
    from pipeline.extract.run import Candidato
    from pipeline.normalize import NaoNormalizavel
    from pipeline.reconcile import observacao_de

    with pytest.raises(NaoNormalizavel):
        observacao_de(
            Candidato(
                "adas_itens",
                ["alerta_de_colisao", "trafego_cruzado"],
                "Alerta de colisão frontal",
                "llm",
            )
        )


def test_espera_do_trinco_respeita_prazo():
    lock = threading.Lock()
    lock.acquire()
    start = time.monotonic()
    try:
        with deadline.budget(0.03), pytest.raises(TimeoutError), deadline.locked(lock):
            pytest.fail("não poderia adquirir o trinco")
    finally:
        lock.release()
    assert time.monotonic() - start < 0.5


def test_migracao_sqlite_vai_e_volta_preservando_dados(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("api/alembic.ini")
    command.upgrade(config, "0009_research_runs")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO brands (id,nome,criado_em) VALUES ('ford','Ford','2026-09-14')"
        )
    command.upgrade(config, "head")
    assert "field_decisions" in inspect(engine).get_table_names()
    command.downgrade(config, "0009_research_runs")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT nome FROM brands").scalar() == "Ford"
    engine.dispose()


def test_duas_publicacoes_da_mesma_versao_nao_perdem_a_fonte_melhor(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent.db'}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        brand = Brand(nome="Ford")
        session.add(brand)
        session.flush()
        model = VehicleModel(nome="Ranger", brand_id=brand.id)
        session.add(model)
        session.flush()
        version = Version(model_id=model.id, nome_exato="Limited", ano_modelo=2027)
        session.add(version)
        session.commit()
        version_id = version.id
    barrier = threading.Barrier(2)

    def publish(value, tier):
        field = SpecField.verificado(
            value,
            Evidence(
                evidence_id=str(value),
                source_url=f"https://fonte{tier}.com.br/ficha",
                quote=f"Potência {value} cv",
                tier=tier,
                captured_at="2026-09-14",
            ),
            unit="cv",
        )
        spec = empty_spec()
        spec.set("motorizacao.potencia_cv", field)
        barrier.wait(timeout=10)
        with Session(engine) as session:
            fundir_valores(session, version_id=version_id, spec=spec, snapshots={})
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish, 250, 1), pool.submit(publish, 200, 3)]
        for future in futures:
            future.result(timeout=20)
    with Session(engine) as session:
        field = montar(session, version_id).get("motorizacao.potencia_cv")
        assert field.value == 250 and field.status == Status.VERIFICADO
        assert session.exec(select(FieldDecision).where(FieldDecision.field == "potencia_cv")).all()
    engine.dispose()
