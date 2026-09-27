"""Publicação conserva a captura exata e rejeita proveniência quebrada."""

import datetime as dt
import hashlib
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from api.app.models import Brand, Snapshot, Source, SpecValue, VehicleModel, Version
from api.app.models import Evidence as EvidenceRow
from api.app.services.spec_assembler import montar
from pipeline.persist import fundir_valores, gravar_snapshot
from pipeline.schema import Evidence, SpecField, Status, empty_spec


@pytest.fixture
def catalog():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        brand = Brand(nome="Ford")
        session.add(brand)
        session.flush()
        models = [VehicleModel(nome=name, brand_id=brand.id) for name in ("Ranger", "F-150")]
        session.add_all(models)
        session.flush()
        versions = [
            Version(model_id=model.id, nome_exato="Limited", ano_modelo=2027) for model in models
        ]
        session.add_all(versions)
        source = Source(
            url="https://www.ford.com.br/configurador",
            dominio="www.ford.com.br",
            tipo="html",
            tier=1,
        )
        session.add(source)
        session.flush()
        yield session, versions[0], versions[1], source
    engine.dispose()


def capture(session, version, source, tmp_path, *, name, power=250, day=14, model="Ranger"):
    text = f"Ford {model} Limited 2027 Brasil\nPotência {power} cv"
    path = tmp_path / f"{name}.txt"
    path.write_text(text, encoding="utf-8")
    snapshot = Snapshot(
        source_id=source.id,
        version_id=version.id,
        url=source.url,
        text_path=str(path),
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        captured_at=dt.datetime(2026, 9, day),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def spec_from(snapshot, *, power=250):
    spec = empty_spec()
    spec.set(
        "motorizacao.potencia_cv",
        SpecField.verificado(
            power,
            Evidence(
                evidence_id="not-yet-materialized",
                snapshot_id=snapshot.id,
                source_url=snapshot.url,
                tier=1,
                captured_at=snapshot.captured_at.isoformat(),
                quote=f"Potência {power} cv",
            ),
            unit="cv",
        ),
    )
    return spec


def test_snapshot_explicito_anterior_prevalece_ao_mapa_mais_recente(catalog, tmp_path):
    session, target, _, source = catalog
    old = capture(session, target, source, tmp_path, name="old", day=1)
    new = capture(session, target, source, tmp_path, name="new", power=200)
    fundir_valores(
        session,
        version_id=target.id,
        spec=spec_from(old),
        snapshots={source.url: (new.id, new.captured_at)},
        require_source_proof=True,
    )
    session.commit()
    actual = montar(session, target.id).motorizacao["potencia_cv"]
    assert actual.status == Status.VERIFICADO
    assert actual.value == 250
    assert actual.evidences[0].snapshot_id == old.id
    stored = session.get(EvidenceRow, actual.evidences[0].evidence_id)
    assert stored.snapshot_id == old.id
    assert stored.captured_at == old.captured_at


def test_snapshot_explicito_de_outra_versao_nao_e_prova_do_alvo(catalog, tmp_path):
    session, target, other, source = catalog
    foreign = capture(session, other, source, tmp_path, name="foreign", model="F-150")
    fundir_valores(
        session,
        version_id=target.id,
        spec=spec_from(foreign),
        snapshots={},
        require_source_proof=True,
    )
    session.commit()
    actual = montar(session, target.id).motorizacao["potencia_cv"]
    assert actual.value is None
    assert actual.status == Status.NAO_VERIFICADO
    assert "snapshot" in actual.notes


@pytest.mark.parametrize("invalidated", ["hash", "version", "url"])
def test_revalidacao_legada_recusa_snapshot_corrompido_ou_de_outra_identidade(
    catalog, tmp_path, invalidated
):
    session, target, other, source = catalog
    snapshot = capture(session, target, source, tmp_path, name="original")
    fundir_valores(
        session,
        version_id=target.id,
        spec=spec_from(snapshot),
        snapshots={},
        require_source_proof=True,
    )
    session.commit()
    before = montar(session, target.id).motorizacao["potencia_cv"]
    assert before.status == Status.VERIFICADO
    evidence_id = before.evidences[0].evidence_id
    if invalidated == "hash":
        snapshot.sha256 = "0" * 64
    elif invalidated == "version":
        snapshot.version_id = other.id
    else:
        snapshot.url = "https://www.ford.com.br/outro-documento"
    session.add(snapshot)
    session.commit()
    fundir_valores(
        session,
        version_id=target.id,
        spec=empty_spec(),
        snapshots={},
        require_source_proof=True,
    )
    session.commit()
    actual = montar(session, target.id).motorizacao["potencia_cv"]
    assert actual.value is None
    assert actual.status == Status.NAO_VERIFICADO
    assert "snapshot" in actual.notes
    # A decisão deixa de publicar; a evidência original permanece auditável.
    stored = session.get(EvidenceRow, evidence_id)
    assert stored is not None
    assert stored.snapshot_id == snapshot.id
    assert stored.quote == "Potência 250 cv"


@pytest.mark.parametrize("matching_content", [True, False])
def test_reparo_do_caminho_exige_mesmo_hash_e_preserva_identidade_da_captura(
    catalog, tmp_path, matching_content
):
    session, target, _, source = catalog
    original = "Ford Ranger Limited 2027 Brasil\nPotência 250 cv"
    digest = hashlib.sha256(original.encode()).hexdigest()
    captured_at = dt.datetime(2026, 9, 1, 12, 34, 56)
    arguments = {
        "url": source.url,
        "version_id": target.id,
        "tier": 1,
        "tipo": "html",
        "captured_at": captured_at,
        "sha256": digest,
        "http_status": 200,
    }
    assert gravar_snapshot(session, **arguments, text_path=None)
    session.commit()
    snapshot = session.exec(select(Snapshot)).one()
    original_id = snapshot.id
    stored_reference = EvidenceRow(
        snapshot_id=original_id, source_url=source.url, tier=1, quote="Potência 250 cv"
    )
    session.add(stored_reference)
    session.commit()
    restored = tmp_path / "restored.txt"
    restored.write_text(
        original if matching_content else original.replace("250", "200"),
        encoding="utf-8",
        newline="\n",
    )
    assert not gravar_snapshot(session, **arguments, text_path=str(restored))
    session.commit()
    actual = session.exec(select(Snapshot)).one()
    assert actual.id == original_id
    assert actual.captured_at == captured_at
    assert actual.sha256 == digest
    assert actual.url == source.url and actual.version_id == target.id
    assert actual.source_id == source.id and actual.http_status == 200
    assert actual.text_path == (str(restored) if matching_content else None)
    assert session.get(EvidenceRow, stored_reference.id).snapshot_id == original_id


def test_cache_do_snapshot_nao_dispensa_correspondencia_da_url_de_cada_evidencia(catalog, tmp_path):
    session, target, _, source = catalog
    snapshot = capture(session, target, source, tmp_path, name="shared")
    path = Path(snapshot.text_path)
    text = path.read_text(encoding="utf-8") + "\nTorque 500 Nm"
    path.write_text(text, encoding="utf-8", newline="\n")
    snapshot.sha256 = hashlib.sha256(text.encode()).hexdigest()
    session.add(snapshot)
    stored = []
    for field, value, unit, quote, url in [
        ("potencia_cv", 250, "cv", "Potência 250 cv", source.url),
        ("torque_nm", 500, "Nm", "Torque 500 Nm", "https://www.ford.com.br/outra-fonte"),
    ]:
        evidence = EvidenceRow(snapshot_id=snapshot.id, source_url=url, tier=1, quote=quote)
        session.add(evidence)
        session.flush()
        stored.append(evidence.id)
        session.add(
            SpecValue(
                version_id=target.id,
                field=field,
                value_json=value,
                unit=unit,
                status="verificado",
                confidence=0.9,
                evidence_id=evidence.id,
            )
        )
    session.commit()
    fundir_valores(
        session,
        version_id=target.id,
        spec=empty_spec(),
        snapshots={},
        require_source_proof=True,
    )
    session.commit()
    spec = montar(session, target.id)
    assert spec.motorizacao["potencia_cv"].status == Status.VERIFICADO
    assert spec.motorizacao["potencia_cv"].value == 250
    torque = spec.motorizacao["torque_nm"]
    assert torque.status == Status.NAO_VERIFICADO
    assert torque.value is None and "snapshot" in torque.notes
    assert all(session.get(EvidenceRow, evidence_id) is not None for evidence_id in stored)
