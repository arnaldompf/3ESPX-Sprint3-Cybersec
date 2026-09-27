import datetime as dt
import hashlib
import json

import pytest
from sqlmodel import Session, SQLModel, create_engine

from api.app.models import Brand, Snapshot, Source, VehicleModel, Version
from api.app.models import Evidence as EvidenceRow
from api.app.services.spec_assembler import montar
from pipeline.identity import VehicleTarget
from pipeline.persist import fundir_valores
from pipeline.publication import choose
from pipeline.schema import Evidence, SpecField, empty_spec
from pipeline.semantics import validate_date


@pytest.mark.parametrize(
    "field,value,quote,ok",
    [
        ("preco_data", "2026-09-10", "R$ 346.900", False),
        ("preco_data", "2026-09-10", "Oferta vigente em 10/09/2026", True),
        ("preco_data", "2026-09-10", "Referência: setembro de 2026", False),
        ("preco_data", "2026-09-10", "Oferta vigente: 2026-09-10", True),
        ("fipe_referencia", "2026-09", '"MesReferencia": "setembro de 2026"', True),
        ("fipe_referencia", "2026-09", '"MesReferencia": "outubro de 2026"', False),
    ],
)
def test_data_precisa_de_prova(field, value, quote, ok):
    assert validate_date(field, value, quote) == ok


def cell(value, quote, *, url="https://www.ford.com.br/ranger", unit=None):
    return SpecField.verificado(
        value,
        Evidence(
            evidence_id="incoming",
            source_url=url,
            tier=1,
            quote=quote,
            captured_at="2026-09-14",
        ),
        unit=unit,
    )


def test_ano_em_link_de_recomendacao_nao_salva_ficha_legada():
    source = "Volkswagen Amarok V6 Extreme 2025\n| Ano | 2025 |\nTanque | 80 litros\n[Amarok 2026](https://exemplo.com/2026)"
    previous = cell(80, "Tanque | 80 litros", unit="l")
    target = VehicleTarget("Volkswagen", "Amarok", "V6 Extreme", 2026)
    result = choose("tanque_l", [previous], target=target, source_texts={"incoming": source})
    assert result.value is None
    assert "ano_modelo" in result.notes


def test_preco_fipe_zero_km_nao_vira_preco_do_my_pedido():
    source = json.dumps(
        {
            "CodigoFipe": "003497-5",
            "AnoModelo": 32000,
            "Valor": "R$ 343.735,00",
            "MesReferencia": "setembro de 2026",
        }
    )
    previous = cell(343735, '"Valor": "R$ 343.735,00"', unit="BRL")
    target = VehicleTarget("Ford", "Ranger", "Limited", 2027)
    result = choose("preco_fipe_brl", [previous], target=target, source_texts={"incoming": source})
    assert result.value is None
    assert "ano_fipe" in result.notes


def test_eds_preserva_limite_de_significado_na_publicacao():
    result = choose(
        "bloqueio_diferencial", [cell(True, "Bloqueio eletrônico do diferencial (EDS)")]
    )
    assert result.value is True
    assert "não comprova bloqueio mecânico" in result.notes


def test_converter_metros_nao_aumenta_precisao_declarada():
    result = choose("largura_mm", [cell(1950, "Largura 1,95 m", unit="mm")])
    assert result.value == 1950
    assert "2 casa(s)" in result.notes
    assert "não acrescenta precisão" in result.notes


def test_auditoria_pode_recusar_prova_legada_sem_descartar_prova_valida():
    old = cell(200, "Potência 200 cv", unit="cv")
    old.evidences[0].evidence_id = "legacy"
    valid = cell(250, "Potência 250 cv", unit="cv", url="https://revista.com.br/ficha")
    valid.evidences[0].tier = 3
    result = choose("potencia_cv", [old, valid], rejected_evidences={"legacy": "ano_incompativel"})
    assert result.value == 250
    assert result.evidences[0].evidence_id == "incoming"
    assert old.value == 200 and old.evidences[0].evidence_id == "legacy"


def test_nova_captura_nao_reaponta_a_prova_da_decisao_anterior(tmp_path):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        brand = Brand(nome="Ford")
        session.add(brand)
        session.flush()
        model = VehicleModel(nome="Ranger", brand_id=brand.id)
        session.add(model)
        session.flush()
        version = Version(model_id=model.id, nome_exato="Limited 3.0 V6", ano_modelo=2027)
        source = Source(
            url="https://www.ford.com.br/ranger",
            tipo="html",
            tier=1,
            dominio="www.ford.com.br",
            robots_ok=True,
        )
        session.add_all([version, source])
        session.flush()
        old_id = None
        for index, horsepower in enumerate([250, 200]):
            text = f"Ford Ranger Limited 3.0 V6 2027\nPotência {horsepower} cv"
            path = tmp_path / f"source-{index}.txt"
            path.write_text(text, encoding="utf-8")
            snapshot = Snapshot(
                source_id=source.id,
                version_id=version.id,
                url=source.url,
                captured_at=dt.datetime(2026, 9, 14, index),
                text_path=str(path),
                sha256=hashlib.sha256(text.encode()).hexdigest(),
            )
            session.add(snapshot)
            session.flush()
            spec = empty_spec()
            value = cell(horsepower, f"Potência {horsepower} cv", unit="cv")
            # Igual autoridade expõe conflito; ambas as provas devem conservar a captura.
            spec.set("motorizacao.potencia_cv", value)
            fundir_valores(
                session,
                version_id=version.id,
                spec=spec,
                snapshots={source.url: (snapshot.id, snapshot.captured_at)},
            )
            session.commit()
            if not index:
                old_id = snapshot.id
        actual = montar(session, version.id).motorizacao["potencia_cv"]
        proofs = {
            actual.value: actual.evidences[0],
            **{c.value: c.evidence for c in actual.conflicts},
        }
        assert proofs[250].snapshot_id == old_id
        stored = session.get(EvidenceRow, proofs[250].evidence_id)
        assert stored.snapshot_id == old_id
        assert proofs[200].snapshot_id == snapshot.id
