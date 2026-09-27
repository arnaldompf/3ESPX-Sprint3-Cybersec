"""Prepara revisão cega e audita prontidão; não extrai, não publica nem certifica."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matches(model: str, text: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", model.lower())
    return bool(re.search(r"\b" + r"[\W_]*".join(map(re.escape, tokens)) + r"\b", text.lower()))


def exposure_audit(root: Path, proposal: dict) -> dict:
    """Fixtures dirigidas comprovam uso; menções em código exigem revisão, não inocência."""
    families = {c["leakage_group"]: c["target"]["modelo"] for c in proposal["cases"]}
    audit = {family: {"prior_targets": [], "code_mentions": []} for family in families}
    for path in sorted((root / "tests/fixtures/search").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        vehicle = str(data.get("veiculo", ""))
        for family, model in families.items():
            if matches(model, vehicle):
                audit[family]["prior_targets"].append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "sha256": digest(path),
                        "target": vehicle,
                    }
                )
    # Não abre snapshots/checkpoints gigantes nem consulta o banco de produção.
    for folder in ("pipeline", "tests/pipeline", "tests/api"):
        for path in sorted((root / folder).rglob("*.py")):
            if path.name in {"test_independent_eval_protocol.py"}:
                continue
            text = path.read_text(encoding="utf-8")
            for family, model in families.items():
                if matches(model, text):
                    audit[family]["code_mentions"].append(
                        {"path": path.relative_to(root).as_posix(), "sha256": digest(path)}
                    )
    for entry in audit.values():
        entry["status"] = (
            "already_used_for_development"
            if entry["prior_targets"]
            else "manual_exposure_review_pending"
        )
    return audit


def prepare(root: Path, proposal_path: Path, fields: list[str]) -> tuple[dict, dict]:
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    exposure = exposure_audit(root, proposal)
    cases = []
    for case in proposal["cases"]:
        family = case["leakage_group"]
        used = exposure[family]["status"] == "already_used_for_development"
        split = (
            "development"
            if used or case["proposed_split"] == "development"
            else "candidate_pending_audit"
        )
        cases.append(
            {
                "id": case["id"],
                "target": case["target"],
                "leakage_group": family,
                "original_split": case["proposed_split"],
                "admissible_split_now": split,
                "primary_source_ids": case["primary_source_ids"],
                "source_documents": [],
                "identity_review": None,
                "field_reviews": {},
                "adjudicated": False,
            }
        )
    manifest = {
        "schema_version": 1,
        "status": "preparation_only",
        "certified": False,
        "frozen": False,
        "evaluation_executed": False,
        "precision": None,
        "proposal_sha256": digest(proposal_path),
        "fields": fields,
        "denominator": len(fields),
        "code_prompts_ontology_acervo_freeze": None,
        "document_near_duplicate_audit": None,
        "audit_scope": (
            "search-fixture targets + Python implementation/tests; "
            "production DB, old branches and private logs not audited"
        ),
        "exposure": exposure,
        "sources": proposal["sources"],
        "cases": cases,
    }
    packet = {
        "schema_version": 1,
        "purpose": "blind_source_review_without_predictions",
        "reviewer_id": None,
        "reviewed_without_predictions": None,
        "fields": fields,
        "label_states": ["present", "proven_absence", "conflict", "not_documented"],
        "field_review_shape": {
            "state": None,
            "value": None,
            "unit": None,
            "citations": [{"document_sha256": None, "quote": None, "page_or_table_cell": None}],
            "applicability": {
                "MY": None,
                "trim": None,
                "powertrain": None,
                "optional_package": None,
            },
        },
        "cases": [
            {
                "id": c["id"],
                "target": c["target"],
                "primary_source_ids": c["primary_source_ids"],
                "reviews": {},
            }
            for c in cases
        ],
    }
    return manifest, packet


def freeze_blockers(manifest: dict, root: Path) -> list[str]:
    """Pré-condições verificáveis; completar o arquivo não substitui revisão humana."""
    blockers = []
    if not manifest.get("code_prompts_ontology_acervo_freeze"):
        blockers.append("implementation_freeze_missing")
    if not manifest.get("document_near_duplicate_audit"):
        blockers.append("document_near_duplicate_audit_missing")
    fields = set(manifest["fields"])
    development = {
        c["leakage_group"] for c in manifest["cases"] if c["admissible_split_now"] == "development"
    }
    reserved = [c for c in manifest["cases"] if c["admissible_split_now"] == "reserved_approved"]
    if len(reserved) != 12:
        blockers.append("reserved_requires_12_reviewed_cases")
    for case in reserved:
        prefix = case["id"] + ":"
        if case["leakage_group"] in development:
            blockers.append(prefix + "family_overlap")
        audit = manifest["exposure"].get(case["leakage_group"], {})
        if audit.get("status") != "cleared_by_independent_audit" or audit.get("prior_targets"):
            blockers.append(prefix + "prior_exposure_not_cleared")
        if not case.get("identity_review") or not case.get("adjudicated"):
            blockers.append(prefix + "identity_or_adjudication_missing")
        documents = {}
        for doc in case.get("source_documents", []):
            path = (root / doc["path"]).resolve()
            if (
                not path.is_relative_to(root.resolve())
                or not path.is_file()
                or digest(path) != doc["sha256"]
            ):
                blockers.append(prefix + "invalid_document_hash_or_path")
                continue
            documents[doc["sha256"]] = doc
        if not documents:
            blockers.append(prefix + "no_frozen_original_sources")
        reviews = case.get("field_reviews", {})
        if set(reviews) != fields:
            blockers.append(prefix + "incomplete_54_field_review")
        for field, record in reviews.items():
            reviewers = record.get("reviewers", [])
            if len(
                {r for r in reviewers if isinstance(r, str) and r.strip()}
            ) < 2 or not record.get("reviewed_without_predictions"):
                blockers.append(prefix + field + ":independent_reviewers_missing")
            state = record.get("state")
            if state not in {"present", "proven_absence", "conflict", "not_documented"}:
                blockers.append(prefix + field + ":invalid_label_state")
            if state == "present" and record.get("value") is None:
                blockers.append(prefix + field + ":present_without_value")
            if state in {"present", "proven_absence", "conflict"}:
                citations = record.get("citations", [])
                if not citations or any(
                    c.get("document_sha256") not in documents
                    or not c.get("quote")
                    or not c.get("page_or_table_cell")
                    for c in citations
                ):
                    blockers.append(prefix + field + ":missing_primary_evidence_locator")
    return sorted(set(blockers))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--proposal", type=Path, default=Path("reports/quality/evaluation-split-proposal.json")
    )
    parser.add_argument("--output", type=Path, default=Path("reports/quality/independent-eval"))
    parser.add_argument(
        "--check", type=Path, help="Valida manifest editado sem gerar ou sobrescrever artefatos"
    )
    args = parser.parse_args()
    if args.check:
        manifest = json.loads(args.check.read_text(encoding="utf-8"))
        blockers = freeze_blockers(manifest, args.root.resolve())
        print(
            json.dumps(
                {"ready_for_external_freeze_review": not blockers, "blockers": blockers},
                ensure_ascii=False,
            )
        )
        return
    from pipeline.research.gaps import campos_procuraveis

    manifest, packet = prepare(args.root.resolve(), args.proposal, campos_procuraveis())
    manifest["freeze_blockers"] = freeze_blockers(manifest, args.root.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    for name, content in [("manifest.json", manifest), ("blind-review-template.json", packet)]:
        destination = args.output / name
        if destination.exists():
            raise FileExistsError(
                f"Preservar revisão existente: {destination}; escolha outro --output"
            )
        destination.write_text(
            json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "cases": len(manifest["cases"]),
                "fields": len(manifest["fields"]),
                "frozen": False,
                "evaluation_executed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
