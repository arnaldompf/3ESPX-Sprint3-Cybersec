"""Repara duas decisões com capturas existentes: código FIPE e provas do Safer Tag.

Não coleta fontes nem altera outros campos. Prévia transacional com rollback por
padrão; --apply exige backup novo. Evidências recusadas permanecem no histórico.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from sqlmodel import Session

from api.app.models import Evidence as EvidenceRow
from api.app.models import Snapshot
from api.app.services.spec_assembler import montar
from pipeline.persist import fundir_valores
from pipeline.reconcile import reconciliar
from pipeline.research.gaps import medir
from pipeline.research.run import Fonte, _SnapshotDaPesquisa
from pipeline.run import JobContext, consultar_comerciais
from pipeline.schema import StandardSpec, Status, empty_spec
from scripts.apply_vw_manual_warranty import _sha, _state
from scripts.audit_quality import check_proof
from scripts.promote_quality_pilot import (
    _backup,
    _engine,
    _identity,
    _protect_capture_paths,
    _write_report,
)

FIELDS = {"codigo_fipe", "adas_nome_comercial"}


class DeltaSpec(StandardSpec):
    def itens(self):
        yield "identificacao.codigo_fipe", self.identificacao["codigo_fipe"]
        yield "seguranca.adas_nome_comercial", self.seguranca["adas_nome_comercial"]


def _original(session, snapshot_id, version_id):
    snapshot = session.get(Snapshot, snapshot_id)
    if snapshot is None or snapshot.version_id != version_id or not snapshot.text_path:
        raise ValueError("snapshot ausente, sem caminho ou pertencente a outra versão")
    text = Path(snapshot.text_path).read_text(encoding="utf-8")
    if hashlib.sha256(text.encode()).hexdigest() != snapshot.sha256:
        raise ValueError("snapshot original com hash incompatível")
    return snapshot, text


def _audit(session, version_id, field, value, unit, evidence, target):
    original, _ = _original(session, evidence.snapshot_id, version_id)
    materialized = session.get(EvidenceRow, evidence.evidence_id)
    if (
        materialized is None
        or materialized.snapshot_id != original.id
        or materialized.source_url != original.url
        or materialized.quote != evidence.quote
        or original.url != evidence.source_url
    ):
        raise ValueError("assertion sem identidade materializada entre EvidenceRow e Snapshot")
    result = check_proof(
        field,
        {
            **evidence.model_dump(),
            "value": value,
            "unit": unit,
            "text_path": original.text_path,
            "sha256": original.sha256,
        },
        target,
    )
    return {"field": field, "evidence_id": evidence.evidence_id, "value": value, **result}


def _isolation(before, after, version_id, allowed_proofs):
    accepted, refused, protected_before, protected_after = [], [], {}, {}
    for table in before.keys() | after.keys():
        b, a = before.get(table, {}), after.get(table, {})
        for key in b.keys() | a.keys():
            old, new = b.get(key), a.get(key)
            if old == new:
                protected_before[table + key] = protected_after[table + key] = old["hash"]
                continue
            change = "insert" if old is None else "delete" if new is None else "update"
            scoped = all(
                row["scope"]["version_id"] == version_id and row["scope"]["field"] in FIELDS
                for row in (old, new)
                if row is not None
            )
            scope = (new or old)["scope"]
            ok = (
                table in {"spec_values", "field_observations", "field_decisions"}
                and scoped
                and (table == "spec_values" or change == "insert")
            ) or (
                table == "evidences"
                and change == "insert"
                and (scope["snapshot_id"], scope["source_url"], scope["quote"]) in allowed_proofs
            )
            (accepted if ok else refused).append({"table": table, "key": key, "change": change})
            if not ok:
                if old:
                    protected_before[table + key] = old["hash"]
                if new:
                    protected_after[table + key] = new["hash"]
    return {
        "valid": not refused,
        "unexpected": refused,
        "allowed_changes": dict(Counter(x["table"] + ":" + x["change"] for x in accepted)),
        "unrelated_before_sha256": _sha(protected_before),
        "unrelated_after_sha256": _sha(protected_after),
    }


def apply_delta(
    database, version_id, fipe_snapshot_id, reject_evidence_ids, output, *, apply=False, backup=None
):
    database, output = Path(database).resolve(), Path(output).resolve()
    backup = Path(backup).resolve() if backup else None
    if (
        not database.is_file()
        or output.exists()
        or output.suffix.lower() != ".json"
        or output in {database, backup}
    ):
        raise ValueError("banco deve existir; relatório JSON deve ser novo e separado")
    if apply and (not backup or backup.exists() or backup in {database, output}):
        raise ValueError("--apply exige --backup novo e separado")
    requested = set(reject_evidence_ids)
    if not requested:
        raise ValueError("informe a assertion recusada já revisada")
    report = {
        "applied": False,
        "requested_apply": apply,
        "backup": None,
        "errors": [],
        "database": str(database),
        "version_id": version_id,
        "fields": sorted(FIELDS),
        "network_calls": 0,
        "llm_calls": 0,
        "certified_90_percent": False,
    }
    engine = _engine(database, readonly=False)
    try:
        with Session(engine) as session:
            _protect_capture_paths(session, output)
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            try:
                target = _identity(session, version_id)
                before = montar(session, version_id)
                baseline = _state(session)
                source, text = _original(session, fipe_snapshot_id, version_id)
                source_adapter = _SnapshotDaPesquisa(
                    Fonte(
                        url=source.url,
                        texto=text,
                        tier=2,
                        tipo="fipe",
                        baixada=True,
                        motivo="captura local auditada",
                        consulta="offline",
                        sha256=source.sha256,
                        captured_at=source.captured_at.isoformat(),
                    )
                )
                context = JobContext(
                    target.marca,
                    target.modelo,
                    target.versao,
                    ano=target.ano_modelo,
                    snapshots=[source_adapter],
                )
                candidates = [
                    c
                    for c in consultar_comerciais(context, somente_snapshots=True)
                    if c.campo == "codigo_fipe"
                ]
                if len(candidates) != 1:
                    raise ValueError(
                        "a captura não fornece código FIPE para a identidade de destino"
                    )
                candidate = candidates[0]
                first_audit = check_proof(
                    "codigo_fipe",
                    {
                        "source_url": source.url,
                        "quote": candidate.quote,
                        "value": candidate.valor,
                        "text_path": source.text_path,
                        "sha256": source.sha256,
                    },
                    target,
                )
                if not first_audit["valid"]:
                    raise ValueError(
                        "código FIPE não passou na auditoria: " + first_audit["reason"]
                    )
                previous = before.seguranca["adas_nome_comercial"]
                if previous.status != Status.VERIFICADO or previous.conflicts:
                    raise ValueError("revisão espera nome ADAS já verificado sem conflito")
                old_audits = [
                    _audit(
                        session,
                        version_id,
                        "adas_nome_comercial",
                        previous.value,
                        previous.unit,
                        e,
                        target,
                    )
                    for e in previous.evidences
                ]
                rejected = {a["evidence_id"]: a["reason"] for a in old_audits if not a["valid"]}
                if set(rejected) != requested:
                    raise ValueError(
                        "assertions inválidas atuais diferem dos IDs revisados: "
                        + str(sorted(rejected))
                    )
                retained = [
                    e.model_copy(deep=True)
                    for e in previous.evidences
                    if e.evidence_id not in rejected
                ]
                if not retained:
                    raise ValueError("nenhuma prova válida sustentaria o nome ADAS")
                result = reconciliar(
                    candidates,
                    textos={candidate.source_id: text},
                    campos=["codigo_fipe"],
                    target=target,
                )
                spec = DeltaSpec.model_validate(empty_spec().model_dump())
                spec.set("identificacao.codigo_fipe", result.decisoes["codigo_fipe"].spec)
                fipe_cell = spec.identificacao["codigo_fipe"]
                for evidence in fipe_cell.evidences:
                    evidence.snapshot_id = source.id
                    evidence.captured_at = source.captured_at.isoformat()
                valid_adas = previous.model_copy(deep=True)
                valid_adas.evidences = retained
                spec.set("seguranca.adas_nome_comercial", valid_adas)
                allowed_proofs = {
                    (e.snapshot_id, e.source_url, e.quote)
                    for _, cell in spec.itens()
                    for e in cell.evidences
                }
                snapshots = {}
                for _, cell in spec.itens():
                    for evidence in cell.evidences:
                        snap, _ = _original(session, evidence.snapshot_id, version_id)
                        snapshots[evidence.source_url] = (snap.id, snap.captured_at)
                if apply:
                    report["backup"] = _backup(database, backup)
                persistence = fundir_valores(
                    session,
                    version_id=version_id,
                    spec=spec,
                    snapshots=snapshots,
                    require_source_proof=True,
                    rejected_evidences=rejected,
                )
                if persistence.erros:
                    raise ValueError(persistence.erros)
                after = montar(session, version_id)
                audits = []
                for path, cell in after.itens():
                    field = path.rsplit(".", 1)[-1]
                    if field not in FIELDS:
                        continue
                    if cell.status != Status.VERIFICADO or cell.conflicts or not cell.evidences:
                        raise ValueError("campo reparado não ficou verificado: " + field)
                    audits.extend(
                        _audit(session, version_id, field, cell.value, cell.unit, e, target)
                        for e in cell.evidences
                    )
                if not audits or not all(a["valid"] for a in audits):
                    raise ValueError("prova final reprovada")
                if (
                    after.identificacao["codigo_fipe"].value != candidate.valor
                    or after.seguranca["adas_nome_comercial"].value != previous.value
                ):
                    raise ValueError("valor final divergiu do patch revisado")
                isolation = _isolation(baseline, _state(session), version_id, allowed_proofs)
                report.update(
                    target=asdict(target),
                    fipe_snapshot_id=source.id,
                    fipe_audit=first_audit,
                    rejected_evidences=rejected,
                    previous_adas_audits=old_audits,
                    final_audits=audits,
                    before_coverage=medir(before).to_dict(),
                    after_coverage=medir(after).to_dict(),
                    before={
                        p: c.model_dump(mode="json")
                        for p, c in before.itens()
                        if p.rsplit(".", 1)[-1] in FIELDS
                    },
                    after={
                        p: c.model_dump(mode="json")
                        for p, c in after.itens()
                        if p.rsplit(".", 1)[-1] in FIELDS
                    },
                    isolation=isolation,
                    persistence=persistence.to_dict(),
                )
                if (
                    not isolation["valid"]
                    or isolation["unrelated_before_sha256"] != isolation["unrelated_after_sha256"]
                ):
                    raise ValueError("mudança fora dos dois campos e suas provas")
                report["ready_to_apply"] = True
                _write_report(output, report)
                if apply:
                    session.commit()
                    report.update(applied=True, transaction="committed")
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
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--fipe-snapshot-id", required=True)
    parser.add_argument("--reject-evidence-id", action="append", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    try:
        report = apply_delta(
            args.database,
            args.version_id,
            args.fipe_snapshot_id,
            args.reject_evidence_id,
            args.output,
            apply=args.apply,
            backup=args.backup,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "ready_to_apply": report["ready_to_apply"],
                "applied": report["applied"],
                "errors": report["errors"],
            }
        )
    )
    return 0 if report["ready_to_apply"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
