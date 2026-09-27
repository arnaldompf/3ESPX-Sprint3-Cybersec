"""Aplica somente a garantia da cadeia local; simulação com rollback por padrão."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, select

from api.app.models import Evidence as EvidenceRow
from api.app.models import Snapshot
from api.app.services.spec_assembler import montar
from pipeline.connectors import vw_manual_warranty as warranty
from pipeline.persist import fundir_valores, gravar_snapshot
from pipeline.reconcile import reconciliar
from pipeline.research.gaps import medir
from pipeline.schema import StandardSpec, empty_spec
from scripts.audit_quality import check_proof
from scripts.promote_quality_pilot import (
    _backup,
    _engine,
    _identity,
    _protect_capture_paths,
    _write_report,
)


class WarrantyOnlySpec(StandardSpec):
    """Modelo canônico cuja projeção autorizada contém exatamente um campo."""

    def itens(self):
        yield "comercial.garantia_meses", self.comercial["garantia_meses"]


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _state(session):
    """Impressões por linha de todas as tabelas; conteúdos privados não entram no relatório."""
    conn = session.connection()
    tables = [
        r[0]
        for r in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    result = {}
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        keys = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(" + quoted + ")") if r[5]]
        rows = {}
        # Nome lido do catálogo SQLite e delimitado/escapado como identificador.
        for record in conn.exec_driver_sql("SELECT * FROM " + quoted).mappings():  # noqa: S608
            row = dict(record)
            key = tuple(row[k] for k in keys) if keys else (_sha(row),)
            rows[str(key)] = {
                "hash": _sha(row),
                "scope": {
                    k: row.get(k)
                    for k in (
                        "version_id",
                        "field",
                        "url",
                        "source_url",
                        "quote",
                        "snapshot_id",
                        "sha256",
                    )
                },
            }
        result[table] = rows
    return result


def _check_changes(before, after, *, version_id, url, quote, snapshot_id, digest):
    allowed, refused, protected_before, protected_after = [], [], {}, {}
    for table in before.keys() | after.keys():
        b, a = before.get(table, {}), after.get(table, {})
        for key in b.keys() | a.keys():
            old, new = b.get(key), a.get(key)
            if old == new:
                protected_before[table + key] = protected_after[table + key] = old["hash"]
                continue
            change = "insert" if old is None else "delete" if new is None else "update"
            scope = (new or old)["scope"]
            ok = (
                table in {"spec_values", "field_observations", "field_decisions"}
                and all(
                    row["scope"]["version_id"] == version_id
                    and row["scope"]["field"] == warranty.FIELD
                    for row in (old, new)
                    if row is not None
                )
                and (table == "spec_values" or change == "insert")
            ) or (
                change == "insert"
                and (
                    (table == "sources" and scope["url"] == url)
                    or (
                        table == "snapshots"
                        and scope["version_id"] == version_id
                        and scope["url"] == url
                        and scope["sha256"] == digest
                    )
                    or (
                        table == "evidences"
                        and scope["source_url"] == url
                        and scope["quote"] == quote
                        and scope["snapshot_id"] == snapshot_id
                    )
                )
            )
            (allowed if ok else refused).append({"table": table, "change": change, "key": key})
            if not ok:
                if old:
                    protected_before[table + key] = old["hash"]
                if new:
                    protected_after[table + key] = new["hash"]
    return {
        "valid": not refused,
        "unexpected": refused,
        "allowed_changes": dict(Counter(x["table"] + ":" + x["change"] for x in allowed)),
        "unrelated_before_sha256": _sha(protected_before),
        "unrelated_after_sha256": _sha(protected_after),
    }


def apply_warranty(database, version_id, envelope, output, *, apply=False, backup=None):
    database, envelope, output = (Path(p).resolve() for p in (database, envelope, output))
    backup = Path(backup).resolve() if backup else None
    if not database.is_file() or not envelope.is_file():
        raise ValueError("banco e cadeia local precisam existir")
    if (
        output.exists()
        or output.suffix.lower() != ".json"
        or output in {database, envelope, backup}
    ):
        raise ValueError("--output precisa ser JSON novo e separado de banco, cadeia e backup")
    if apply and (not backup or backup.exists() or backup in {database, envelope, output}):
        raise ValueError("--apply exige --backup em caminho novo e separado")
    text = envelope.read_text(encoding="utf-8")
    proof = warranty.read(text)
    if proof is None:
        raise ValueError("cadeia local ou PDF original não passou na verificação integral")
    url = proof.metadata["pdf_url"]
    digest = hashlib.sha256(text.encode()).hexdigest()
    timestamp = datetime.fromisoformat(proof.metadata["pdf_captured_at"])
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    report = {
        "applied": False,
        "requested_apply": apply,
        "backup": None,
        "errors": [],
        "network_calls": 0,
        "llm_calls": 0,
        "certified_90_percent": False,
        "database": str(database),
        "version_id": version_id,
        "field": warranty.FIELD,
        "envelope": str(envelope),
        "sha256": digest,
        "pdf_sha256": proof.metadata["pdf_sha256"],
        "pdf_captured_at_original": proof.metadata["pdf_captured_at"],
        "index_captured_at": proof.metadata["index_captured_at"],
    }
    engine = _engine(database, readonly=False)
    try:
        with Session(engine) as session:
            _protect_capture_paths(session, output)
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            try:
                target = _identity(session, version_id)
                candidates = warranty.candidatos(text, url, target, "vw-manual-warranty")
                if len(candidates) != 1:
                    raise ValueError("a cadeia não prova uma garantia para a identidade de destino")
                candidate = candidates[0]
                audit_candidate = {
                    "source_url": url,
                    "quote": candidate.quote,
                    "value": candidate.valor,
                    "unit": "meses",
                    "text_path": str(envelope),
                    "sha256": digest,
                }
                report["proof_audit"] = check_proof(warranty.FIELD, audit_candidate, target)
                if not report["proof_audit"]["valid"]:
                    raise ValueError("a prova nova não passou na auditoria")
                if apply:
                    report["backup"] = _backup(database, backup)
                before, before_state = montar(session, version_id), _state(session)
                result = reconciliar(
                    candidates,
                    textos={candidate.source_id: text},
                    campos=[warranty.FIELD],
                    target=target,
                )
                spec = WarrantyOnlySpec.model_validate(empty_spec().model_dump())
                spec.set("comercial.garantia_meses", result.decisoes[warranty.FIELD].spec)
                gravar_snapshot(
                    session,
                    url=url,
                    tier=1,
                    tipo="garantia",
                    captured_at=timestamp,
                    sha256=digest,
                    text_path=str(envelope),
                    http_status=200,
                    version_id=version_id,
                )
                session.flush()
                snapshot = session.exec(
                    select(Snapshot).where(
                        Snapshot.version_id == version_id,
                        Snapshot.url == url,
                        Snapshot.captured_at == timestamp,
                        Snapshot.sha256 == digest,
                    )
                ).one()
                existing_text = Path(snapshot.text_path).read_text(encoding="utf-8")
                if hashlib.sha256(existing_text.encode()).hexdigest() != digest:
                    raise ValueError("captura prévia com conteúdo inválido")
                if not snapshot.raw_path:
                    snapshot.raw_path = proof.metadata["pdf_path"]
                    session.add(snapshot)
                cell = spec.comercial[warranty.FIELD]
                for evidence in cell.evidences:
                    evidence.snapshot_id = snapshot.id
                persistence = fundir_valores(
                    session,
                    version_id=version_id,
                    spec=spec,
                    snapshots={url: (snapshot.id, snapshot.captured_at)},
                    require_source_proof=True,
                )
                if persistence.erros:
                    raise ValueError(persistence.erros)
                after = montar(session, version_id)
                final = after.comercial[warranty.FIELD]
                final_audits = []
                for evidence in final.evidences:
                    original = session.get(Snapshot, evidence.snapshot_id)
                    materialized = session.get(EvidenceRow, evidence.evidence_id)
                    if (
                        original is None
                        or original.version_id != version_id
                        or original.url != evidence.source_url
                        or materialized is None
                        or materialized.snapshot_id != original.id
                        or materialized.quote != evidence.quote
                        or materialized.source_url != original.url
                    ):
                        raise ValueError("evidência final sem vínculo ao snapshot da versão")
                    final_audits.append(
                        check_proof(
                            warranty.FIELD,
                            {
                                **evidence.model_dump(),
                                "value": final.value,
                                "unit": final.unit,
                                "text_path": original.text_path,
                                "sha256": original.sha256,
                            },
                            target,
                        )
                    )
                if (
                    final.value != candidate.valor
                    or not final_audits
                    or not all(a["valid"] for a in final_audits)
                ):
                    raise ValueError("publicação final da garantia não passou na auditoria")
                changes = _check_changes(
                    before_state,
                    _state(session),
                    version_id=version_id,
                    url=url,
                    quote=candidate.quote,
                    snapshot_id=snapshot.id,
                    digest=digest,
                )
                report.update(
                    target=asdict(target),
                    before=before.comercial[warranty.FIELD].model_dump(mode="json"),
                    after=final.model_dump(mode="json"),
                    before_coverage=medir(before).to_dict(),
                    after_coverage=medir(after).to_dict(),
                    final_audits=final_audits,
                    isolation=changes,
                    persistence=persistence.to_dict(),
                )
                if (
                    not changes["valid"]
                    or changes["unrelated_before_sha256"] != changes["unrelated_after_sha256"]
                ):
                    raise ValueError("houve alteração fora da garantia e suas novas provas")
                report["ready_to_apply"] = True
                _write_report(output, report)
                if apply:
                    session.commit()
                    report["applied"], report["transaction"] = True, "committed"
                else:
                    session.rollback()
                    report["transaction"] = "rolled_back"
            except Exception as exc:
                session.rollback()
                report.update(ready_to_apply=False, transaction="rolled_back")
                report["errors"].append({"type": type(exc).__name__, "reason": str(exc)})
            _write_report(output, report)
    finally:
        engine.dispose()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    try:
        result = apply_warranty(
            args.database,
            args.version_id,
            args.envelope,
            args.output,
            apply=args.apply,
            backup=args.backup,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "ready_to_apply": result["ready_to_apply"],
                "applied": result["applied"],
                "errors": result["errors"],
                "output": str(args.output),
            }
        )
    )
    return 0 if result["ready_to_apply"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
