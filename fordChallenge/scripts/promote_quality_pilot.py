"""Promove provas locais entre identidades existentes; simula com rollback por padrão.

Não copia bancos, usuários ou jobs. Aplicação exige backup SQLite novo e todas as
provas publicadas precisam passar novamente pela auditoria de identidade e conteúdo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlmodel import Session, select

from api.app.models import Brand, Source, VehicleModel, Version
from api.app.models import Evidence as EvidenceRow
from api.app.models import Snapshot as SnapshotRow
from api.app.services.spec_assembler import montar
from pipeline.identity import VehicleTarget
from pipeline.persist import fundir_valores, gravar_snapshot
from pipeline.publication import POLICY_VERSION, choose
from pipeline.research.gaps import campos_procuraveis, medir
from pipeline.schema import SpecField, Status, empty_spec
from scripts.audit_quality import check_proof


def _engine(path: Path, *, readonly: bool):
    mode = "ro" if readonly else "rw"
    uri = f"{path.as_uri()}?mode={mode}"
    return create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(uri, uri=True, timeout=30),
    )


def _same_file(a: Path, b: Path) -> bool:
    return a == b or (a.exists() and b.exists() and os.path.samefile(a, b))


def _identity(session: Session, version_id: str) -> VehicleTarget:
    version = session.get(Version, version_id)
    model = session.get(VehicleModel, version.model_id) if version else None
    brand = session.get(Brand, model.brand_id) if model else None
    if not version or not model or not brand:
        raise ValueError(f"versão de origem inexistente ou identidade incompleta: {version_id}")
    return VehicleTarget(
        brand.nome, model.nome, version.nome_exato, version.ano_modelo, version.mercado
    )


def _destination(session: Session, target: VehicleTarget) -> str:
    matches = session.exec(
        select(Version)
        .join(VehicleModel, VehicleModel.id == Version.model_id)
        .join(Brand, Brand.id == VehicleModel.brand_id)
        .where(
            Brand.nome == target.marca,
            VehicleModel.nome == target.modelo,
            Version.nome_exato == target.versao,
            Version.ano_modelo == target.ano_modelo,
            Version.mercado == target.mercado,
        )
    ).all()
    if len(matches) != 1:
        raise ValueError(f"identidade deve existir exatamente uma vez no destino: {target}")
    return matches[0].id


def _assertions(cell):
    if cell.status not in {Status.VERIFICADO, Status.DIVERGENTE} or cell.value is None:
        return []
    return [(cell.value, e) for e in cell.evidences] + [
        (c.value, c.evidence) for c in cell.conflicts
    ]


def _validated(session: Session, version_id: str, target: VehicleTarget, spec):
    """Filtra cada prova, inclusive conflitos; conserva ligação exata ao snapshot."""
    filtered = empty_spec()
    rejected = []
    accepted = {}
    fields = set(campos_procuraveis())
    for path, cell in spec.itens():
        field = path.rsplit(".", 1)[-1]
        if field not in fields:
            continue
        claims, texts = [], {}
        for value, evidence in _assertions(cell):
            record = session.get(EvidenceRow, evidence.evidence_id)
            snapshot = (
                session.get(SnapshotRow, evidence.snapshot_id) if evidence.snapshot_id else None
            )
            candidate = {
                **evidence.model_dump(mode="json"),
                "value": value,
                "status": str(cell.status),
                "unit": cell.unit,
                "text_path": snapshot.text_path if snapshot else None,
                "sha256": snapshot.sha256 if snapshot else None,
            }
            reason = ""
            if not record or record.snapshot_id != evidence.snapshot_id:
                reason = "evidencia_sem_ligacao_materializada_ao_snapshot"
            elif not snapshot or snapshot.version_id not in {None, version_id}:
                reason = "snapshot_de_outra_versao_ou_ausente"
            elif snapshot.url != evidence.source_url or record.source_url != evidence.source_url:
                reason = "url_da_evidencia_diverge_do_snapshot"
            elif record.quote != evidence.quote or record.tier != evidence.tier:
                reason = "envelope_diverge_da_evidencia_materializada"
            try:
                audit = check_proof(field, candidate, target)
            except (OSError, UnicodeError, ValueError) as exc:
                audit = {"valid": False, "reason": f"erro_ao_ler_prova: {exc}"}
            if reason or not audit["valid"]:
                rejected.append(
                    {
                        "field": field,
                        "value": value,
                        "evidence_id": evidence.evidence_id,
                        "snapshot_id": evidence.snapshot_id,
                        "source_url": evidence.source_url,
                        "reason": reason or audit["reason"],
                        "audit": audit,
                    }
                )
                continue
            # Paths point to immutable captures, never a reconstructed quotation file.
            source_path = Path(snapshot.text_path).resolve(strict=True)
            source_text = source_path.read_text(encoding="utf-8")
            if hashlib.sha256(source_text.encode()).hexdigest() != snapshot.sha256:
                raise ValueError(f"snapshot mudou durante auditoria: {source_path}")
            texts[evidence.evidence_id] = source_text
            claims.append(
                SpecField.verificado(value, evidence.model_copy(deep=True), unit=cell.unit)
            )
            accepted[evidence.evidence_id] = (snapshot, source_path)
        decision = choose(
            field, claims, target=target, source_texts=texts, require_source_proof=True
        )
        filtered.set(path, decision)
    # Only snapshots backing assertions surviving the shared publication policy travel.
    retained = {e.evidence_id for _, cell in filtered.itens() for _, e in _assertions(cell)}
    return filtered, {key: accepted[key] for key in retained}, rejected


def _register_captures(source: Session, destination: Session, target_id: str, spec, accepted):
    copied, mapping = {}, {}
    for evidence_id, (snapshot, source_path) in accepted.items():
        if snapshot.id not in copied:
            text = source_path.read_text(encoding="utf-8")
            if hashlib.sha256(text.encode()).hexdigest() != snapshot.sha256:
                raise ValueError(f"snapshot mudou antes da cópia: {source_path}")
            source_row = source.get(Source, snapshot.source_id)
            gravar_snapshot(
                destination,
                url=snapshot.url,
                tier=source_row.tier if source_row else 5,
                tipo=source_row.tipo if source_row else "desconhecido",
                captured_at=snapshot.captured_at,
                sha256=snapshot.sha256,
                text_path=str(source_path),
                http_status=snapshot.http_status,
                version_id=target_id,
            )
            destination.flush()
            matches = destination.exec(
                select(SnapshotRow).where(
                    SnapshotRow.version_id == target_id,
                    SnapshotRow.url == snapshot.url,
                    SnapshotRow.captured_at == snapshot.captured_at,
                    SnapshotRow.sha256 == snapshot.sha256,
                )
            ).all()
            if len(matches) != 1:
                raise ValueError("snapshot destino ausente ou ambíguo após registro")
            dest = matches[0]
            existing_path = Path(dest.text_path) if dest.text_path else None
            existing_text = (
                existing_path.read_text(encoding="utf-8")
                if existing_path and existing_path.is_file()
                else ""
            )
            if (
                not existing_text
                or hashlib.sha256(existing_text.encode()).hexdigest() != snapshot.sha256
            ):
                raise ValueError("snapshot existente não preserva o mesmo conteúdo com hash válido")
            # Preserve original raw artifacts when the source has them; never synthesize.
            for attribute in ("raw_path", "screenshot_path"):
                original = getattr(snapshot, attribute)
                if original and Path(original).is_file() and not getattr(dest, attribute):
                    setattr(dest, attribute, str(Path(original).resolve()))
            destination.add(dest)
            copied[snapshot.id] = dest
        mapping[evidence_id] = copied[snapshot.id]
    snapshots = {}
    for _, cell in spec.itens():
        for _, evidence in _assertions(cell):
            dest = mapping[evidence.evidence_id]
            evidence.snapshot_id = dest.id
            evidence.captured_at = dest.captured_at.isoformat()
            evidence.evidence_id = uuid4().hex
            # Explicit snapshot_id disambiguates older/newer captures sharing one URL.
            snapshots[dest.url] = (dest.id, dest.captured_at)
    return snapshots, [
        {
            "source_snapshot_id": original,
            "target_snapshot_id": row.id,
            "url": row.url,
            "captured_at": row.captured_at.isoformat(),
            "sha256": row.sha256,
            "text_path": row.text_path,
        }
        for original, row in copied.items()
    ]


def _backup(database: Path, destination: Path):
    """SQLite online backup to a reserved new file, while caller holds the writer lock."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    with (
        sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as source,
        sqlite3.connect(destination) as backup,
    ):
        source.backup(backup)
        if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("backup SQLite não passou no integrity_check")
    return {
        "path": str(destination),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }


def _write_report(path: Path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _protect_capture_paths(session: Session, output: Path):
    # --output is an arbitrary user path. A JSON capture must never become a report.
    for snapshot in session.exec(select(SnapshotRow)).all():
        for name in ("text_path", "raw_path", "screenshot_path"):
            original = getattr(snapshot, name)
            if original and _same_file(Path(original).resolve(), output):
                raise ValueError("--output não pode sobrescrever uma captura de evidência")


def promote(source_db, target_db, version_ids, output, *, apply=False, backup=None):
    source_db, target_db = Path(source_db).resolve(), Path(target_db).resolve()
    output = Path(output).resolve()
    backup = Path(backup).resolve() if backup else None
    if not source_db.is_file() or not target_db.is_file():
        raise ValueError("origem e destino precisam ser arquivos SQLite existentes")
    if _same_file(source_db, target_db):
        raise ValueError("origem e destino não podem ser o mesmo banco")
    protected = [source_db, target_db, *([backup] if backup else [])]
    if (
        output.is_dir()
        or output.suffix.lower() != ".json"
        or any(_same_file(output, p) for p in protected)
    ):
        raise ValueError("--output precisa ser JSON e não pode sobrescrever banco ou backup")
    if apply and not backup:
        raise ValueError("--apply exige --backup apontando para um caminho novo")
    if backup and (backup.exists() or any(_same_file(backup, p) for p in (source_db, target_db))):
        raise ValueError("o caminho de backup precisa ser novo")
    requested = list(dict.fromkeys(version_ids))
    if not requested:
        raise ValueError("informe pelo menos um --version-id de origem")
    report = {
        "policy": POLICY_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "source_db": str(source_db),
        "target_db": str(target_db),
        "applied": False,
        "requested_apply": apply,
        "backup": None,
        "network_calls": 0,
        "llm_calls": 0,
        "certified_90_percent": False,
        "independent_precision": None,
        "vehicles": [],
        "errors": [],
    }
    source_engine, target_engine = (
        _engine(source_db, readonly=True),
        _engine(target_db, readonly=False),
    )
    try:
        with Session(source_engine) as source, Session(target_engine) as destination:
            _protect_capture_paths(source, output)
            _protect_capture_paths(destination, output)
            destination.connection().exec_driver_sql("BEGIN IMMEDIATE")
            try:
                pairs = [(version_id, _identity(source, version_id)) for version_id in requested]
                mapped = [(sid, target, _destination(destination, target)) for sid, target in pairs]
                if len({dest for _, _, dest in mapped}) != len(mapped):
                    raise ValueError("mais de uma origem aponta para a mesma identidade de destino")
                if apply:
                    report["backup"] = _backup(target_db, backup)
                for source_id, target, target_id in mapped:
                    original = montar(source, source_id)
                    before = montar(destination, target_id)
                    _, _, before_rejected = _validated(destination, target_id, target, before)
                    filtered, accepted, rejected = _validated(source, source_id, target, original)
                    snapshots, copied = _register_captures(
                        source, destination, target_id, filtered, accepted
                    )
                    merged = fundir_valores(
                        destination,
                        version_id=target_id,
                        spec=filtered,
                        snapshots=snapshots,
                        require_source_proof=True,
                        rejected_evidences={p["evidence_id"]: p["reason"] for p in before_rejected},
                    )
                    after = montar(destination, target_id)
                    _, _, final_rejected = _validated(destination, target_id, target, after)
                    report["vehicles"].append(
                        {
                            "target": asdict(target),
                            "source_version_id": source_id,
                            "target_version_id": target_id,
                            "source_coverage": medir(original).to_dict(),
                            "validated_source_coverage": medir(filtered).to_dict(),
                            "before": before.to_dict(),
                            "after": after.to_dict(),
                            "before_coverage": medir(before).to_dict(),
                            "after_coverage": medir(after).to_dict(),
                            "rejected_proofs": rejected,
                            "rejected_previous_proofs": before_rejected,
                            "final_rejected_proofs": final_rejected,
                            "copied_snapshots": copied,
                            "persistence": merged.to_dict(),
                        }
                    )
                    if merged.erros or final_rejected:
                        report["errors"].append(
                            {
                                "version_id": target_id,
                                "reason": "envelope_final_requer_correcao",
                                "invalid_proofs": len(final_rejected),
                                "persistence": merged.erros,
                            }
                        )
                # Keep a reviewable report before deciding whether this transaction may commit.
                report["ready_to_apply"] = not report["errors"]
                _write_report(output, report)
                if apply and report["ready_to_apply"]:
                    destination.commit()
                    report["applied"] = True
                    report["transaction"] = "committed"
                else:
                    destination.rollback()
                    report["transaction"] = "rolled_back"
            except Exception as exc:
                destination.rollback()
                report["transaction"] = "rolled_back"
                report["ready_to_apply"] = False
                report["errors"].append({"type": type(exc).__name__, "reason": str(exc)})
            _write_report(output, report)
    finally:
        source_engine.dispose()
        target_engine.dispose()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--target-db", type=Path, required=True)
    parser.add_argument("--version-id", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    try:
        report = promote(
            args.source_db,
            args.target_db,
            args.version_id,
            args.output,
            apply=args.apply,
            backup=args.backup,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "applied": report["applied"],
                "ready_to_apply": report["ready_to_apply"],
                "errors": report["errors"],
            }
        )
    )
    return 0 if report["ready_to_apply"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
