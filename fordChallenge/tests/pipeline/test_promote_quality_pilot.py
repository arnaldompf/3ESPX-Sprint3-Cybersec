import hashlib
import sqlite3
from datetime import UTC, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from api.app.models import Brand, FieldDecision, Source, SpecValue, VehicleModel, Version
from api.app.models import Evidence as EvidenceRow
from api.app.models import Snapshot as SnapshotRow
from pipeline.schema import Conflict, Evidence, SpecField, Status
from scripts.promote_quality_pilot import promote

URL = "https://www.vw.com.br/pt/carros/amarok.html"


def fixture_db(path, version_id):
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Brand(id="brand", nome="Volkswagen"))
        session.add(VehicleModel(id="model", brand_id="brand", nome="Amarok"))
        session.add(
            Version(id=version_id, model_id="model", nome_exato="V6 Extreme", ano_modelo=2026)
        )
        session.add(
            Version(id="unrelated", model_id="model", nome_exato="V6 Highline", ano_modelo=2026)
        )
        session.commit()
    return engine


def add_claim(session, directory, version_id, name, value, year):
    quote = f"Potência: {value} cv" if name == "potencia_cv" else f"Rodas: {value} polegadas"
    text = f"# Volkswagen Amarok V6 Extreme {year}\n{quote}\n"
    path = directory / f"{name}-{year}.md"
    path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode()).hexdigest()
    source = session.exec(select(Source).where(Source.url == URL)).first()
    if source is None:
        source = Source(url=URL, tipo="pagina_oficial", tier=1, dominio="www.vw.com.br")
        session.add(source)
        session.flush()
    snapshot = SnapshotRow(
        source_id=source.id,
        version_id=version_id,
        url=URL,
        captured_at=datetime(2026, 9, 14, tzinfo=UTC),
        text_path=str(path),
        sha256=digest,
    )
    session.add(snapshot)
    session.flush()
    evidence = EvidenceRow(
        snapshot_id=snapshot.id,
        source_url=URL,
        quote=quote,
        tier=1,
        captured_at=snapshot.captured_at,
        raw_value=str(value),
    )
    session.add(evidence)
    session.flush()
    session.add(
        SpecValue(
            version_id=version_id,
            field=name,
            value_json=value,
            unit="cv" if name == "potencia_cv" else "pol",
            status="verificado",
            confidence=0.9,
            evidence_id=evidence.id,
        )
    )
    return Evidence(
        evidence_id=evidence.id,
        snapshot_id=snapshot.id,
        source_url=URL,
        quote=quote,
        tier=1,
        captured_at=snapshot.captured_at.isoformat(),
        raw_value=str(value),
    )


@pytest.fixture
def databases(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    source_engine = fixture_db(source, "src-amarok")
    target_engine = fixture_db(target, "dest-amarok")
    with Session(source_engine) as session:
        good = add_claim(session, tmp_path, "src-amarok", "potencia_cv", 258, 2026)
        wrong = add_claim(session, tmp_path, "src-amarok", "potencia_cv", 300, 2025)
        add_claim(session, tmp_path, "src-amarok", "rodas_aro_pol", 20, 2025)
        decision = SpecField(
            value=258,
            unit="cv",
            status=Status.DIVERGENTE,
            confidence=0.9,
            evidences=[good],
            conflicts=[Conflict(value=300, evidence=wrong)],
        )
        session.add(
            FieldDecision(
                version_id="src-amarok",
                field="potencia_cv",
                policy_version="test",
                payload=decision.model_dump(mode="json"),
            )
        )
        session.commit()
    source_engine.dispose()
    target_engine.dispose()
    return source, target


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_dry_run_maps_identity_filters_wrong_year_conflict_and_rolls_back(databases, tmp_path):
    source, target = databases
    initial = digest(target), digest(source)
    report = promote(source, target, ["src-amarok"], tmp_path / "preview.json")
    assert not report["applied"]
    assert report["ready_to_apply"], report["errors"]
    assert report["transaction"] == "rolled_back"
    assert (digest(target), digest(source)) == initial
    vehicle = report["vehicles"][0]
    assert vehicle["target_version_id"] == "dest-amarok"
    assert vehicle["after"]["motorizacao"]["potencia_cv"]["value"] == 258
    assert vehicle["after"]["motorizacao"]["potencia_cv"]["status"] == "verificado"
    assert vehicle["after"]["exterior"]["rodas_aro_pol"]["value"] is None
    assert len(vehicle["rejected_proofs"]) == 2
    assert len(vehicle["copied_snapshots"]) == 1


def test_apply_requires_new_backup_and_remaps_only_accepted_proof(databases, tmp_path):
    source, target = databases
    with pytest.raises(ValueError, match="backup"):
        promote(source, target, ["src-amarok"], tmp_path / "no-backup.json", apply=True)
    backup = tmp_path / "before.db"
    report = promote(
        source, target, ["src-amarok"], tmp_path / "applied.json", apply=True, backup=backup
    )
    assert report["applied"], report["errors"]
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT COUNT(*) FROM spec_values").fetchone()[0] == 0
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT COUNT(*) FROM versions").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
        assert db.execute("SELECT DISTINCT version_id FROM snapshots").fetchall() == [
            ("dest-amarok",)
        ]
        assert (
            db.execute("SELECT COUNT(*) FROM spec_values WHERE version_id='unrelated'").fetchone()[
                0
            ]
            == 0
        )
        new_id = db.execute("SELECT id FROM evidences").fetchone()[0]
    with sqlite3.connect(source) as db:
        assert db.execute("SELECT 1 FROM evidences WHERE id=?", (new_id,)).fetchone() is None
    with pytest.raises(ValueError, match="novo"):
        promote(source, target, ["src-amarok"], tmp_path / "retry.json", apply=True, backup=backup)


def test_missing_destination_identity_aborts_without_writes(databases, tmp_path):
    source, target = databases
    with sqlite3.connect(target) as db:
        db.execute("UPDATE versions SET ano_modelo=2025 WHERE id='dest-amarok'")
    initial = digest(target)
    result = promote(source, target, ["src-amarok"], tmp_path / "missing.json")
    assert not result["ready_to_apply"]
    assert not result["applied"]
    assert digest(target) == initial


def test_same_db_and_output_aliases_are_refused(databases, tmp_path):
    source, target = databases
    with pytest.raises(ValueError, match="mesmo banco"):
        promote(source, source, ["src-amarok"], tmp_path / "bad.json")
    with pytest.raises(ValueError, match="output"):
        promote(source, target, ["src-amarok"], target)


def test_tampered_snapshot_is_discarded(databases, tmp_path):
    source, target = databases
    (tmp_path / "potencia_cv-2026.md").write_text("changed", encoding="utf-8")
    report = promote(source, target, ["src-amarok"], tmp_path / "tampered.json")
    vehicle = report["vehicles"][0]
    assert vehicle["after_coverage"]["com_valor"] == 0
    assert vehicle["copied_snapshots"] == []
    assert any(
        p["reason"] == "snapshot_ausente_ou_hash_invalido" for p in vehicle["rejected_proofs"]
    )


def test_existing_capture_at_another_path_is_reused_by_content_hash(databases, tmp_path):
    source, target = databases
    source_engine = create_engine(f"sqlite:///{source.as_posix()}")
    target_engine = create_engine(f"sqlite:///{target.as_posix()}")
    with Session(source_engine) as src, Session(target_engine) as dst:
        snapshot = src.exec(
            select(SnapshotRow).where(
                SnapshotRow.text_path == str(tmp_path / "potencia_cv-2026.md")
            )
        ).one()
        clone = tmp_path / "another-immutable-copy.md"
        clone.write_text(
            (tmp_path / "potencia_cv-2026.md").read_text(encoding="utf-8"), encoding="utf-8"
        )
        src_row = Source(url=URL, tipo="pagina_oficial", tier=1, dominio="www.vw.com.br")
        dst.add(src_row)
        dst.flush()
        dst.add(
            SnapshotRow(
                source_id=src_row.id,
                version_id="dest-amarok",
                url=URL,
                captured_at=snapshot.captured_at,
                sha256=snapshot.sha256,
                text_path=str(clone),
            )
        )
        dst.commit()
    source_engine.dispose()
    target_engine.dispose()
    report = promote(source, target, ["src-amarok"], tmp_path / "equivalent.json")
    assert report["ready_to_apply"], report["errors"]
    assert report["vehicles"][0]["copied_snapshots"][0]["text_path"] == str(clone)


def test_legacy_proof_with_insufficient_identity_is_excluded_before_merge(databases, tmp_path):
    source, target = databases
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    engine = create_engine(f"sqlite:///{target.as_posix()}")
    with Session(engine) as session:
        evidence = add_claim(session, legacy, "dest-amarok", "potencia_cv", 100, 2026)
        snapshot = session.get(SnapshotRow, evidence.snapshot_id)
        text = "# Volkswagen Amarok 2026\nPotência: 100 cv\n"
        (legacy / "potencia_cv-2026.md").write_text(text, encoding="utf-8")
        snapshot.sha256 = hashlib.sha256(text.encode()).hexdigest()
        session.add(snapshot)
        session.commit()
    engine.dispose()
    report = promote(source, target, ["src-amarok"], tmp_path / "legacy-preview.json")
    assert report["ready_to_apply"], report["errors"]
    vehicle = report["vehicles"][0]
    assert vehicle["after"]["motorizacao"]["potencia_cv"]["value"] == 258
    assert vehicle["after"]["motorizacao"]["potencia_cv"]["status"] == "verificado"
    assert vehicle["rejected_previous_proofs"][0]["evidence_id"] == evidence.evidence_id
    assert vehicle["final_rejected_proofs"] == []
