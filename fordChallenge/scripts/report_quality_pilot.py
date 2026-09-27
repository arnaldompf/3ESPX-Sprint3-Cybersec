"""Relatório da continuação dos dois pilotos, comparado ao aceite interativo salvo."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from pipeline.identity import VehicleTarget, claim_rejection
from pipeline.semantics import rejection_reason
from scripts.audit_quality import audit


def write_report(database: Path, output: Path) -> dict:
    before = json.loads((output / "before-after.json").read_text(encoding="utf-8"))
    final = audit(database)
    revalidation_path = output / "claim-revalidation.json"
    revalidated = (
        json.loads(revalidation_path.read_text(encoding="utf-8"))["vehicles"]
        if revalidation_path.exists()
        else []
    )
    (output / "deep-audit.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = {
        "certificado": False,
        "independent_precision": None,
        "mode": "web_ao_vivo_continuacao_pela_interface",
        "denominator": 54,
        "targets": [],
    }
    lines = [
        "# Campos, provas e lacunas dos pilotos",
        "",
        "Cobertura publicada não equivale a precisão independente. A auditoria automática",
        "confere a prova e compara com o gabarito histórico parcial; não certifica os 54 campos.",
        "Os motivos abaixo são diagnósticos desta execução, não prova de inexistência pública.",
        "",
    ]
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        for vehicle in final["vehicles"]:
            target = vehicle["target"]
            prior = next(t for t in before["targets"] if t["target"]["id"] == target["id"])
            prior_fields = {f["field"]: f for f in prior["fields"]}
            corrections = {
                c["field"].split(".")[-1]: c
                for v in revalidated
                if v["version_id"] == target["id"]
                for c in v["changes"]
            }
            runs = conn.execute(
                "SELECT * FROM research_runs WHERE version_id=? AND criado_em >= ? "
                "ORDER BY criado_em",
                (target["id"], prior["live_run"]["criado_em"]),
            ).fetchall()
            exported_runs = []
            gaps = {}
            for run in runs:
                events = []
                for event in conn.execute(
                    "SELECT tipo,texto,decorrido,dados FROM research_events "
                    "WHERE run_id=? ORDER BY ordem",
                    (run["id"],),
                ):
                    events.append({**dict(event), "dados": json.loads(event["dados"])})
                end = next((e["dados"] for e in events if e["tipo"] == "fim"), {})
                gaps.update({g["campo"]: g for g in end.get("lacunas", [])})
                job = conn.execute(
                    "SELECT id,payload FROM jobs WHERE json_extract(payload,'$.run_id')=?",
                    (run["id"],),
                ).fetchone()
                exported_runs.append(
                    {
                        **dict(run),
                        "job_id": job["id"] if job else None,
                        "parent_run_id": json.loads(job["payload"]).get("continued_from")
                        if job
                        else None,
                        "events": events,
                        "costs": end.get("custos_servicos", {}),
                        "llm_measurement": end.get("medicao", {}),
                    }
                )
            fields = []
            for field in vehicle["fields"]:
                name = field["field"]
                pub = field["published"]
                after = pub[0]["value"] if pub else None
                status = pub[0]["status"] if pub else "nao_encontrado"
                old = prior_fields[name]
                gap = gaps.get(name, old.get("research_gap"))
                correction = corrections.get(name)
                if after is None and correction:
                    identity = VehicleTarget(
                        target["marca"], target["modelo"], target["versao"], target["ano_modelo"]
                    )
                    rejected_proofs = correction["before"]["evidences"]
                    reasons = [
                        claim_rejection(identity, e["quote"])
                        or rejection_reason(name, e["quote"], url=e["source_url"])
                        for e in rejected_proofs
                    ]
                    gap = {
                        **(gap or {}),
                        "etapa_em_que_parou": "revalidacao_semantica",
                        "motivo_da_rejeicao": [r for r in reasons if r],
                        "evidencias_rejeitadas": rejected_proofs,
                        "proxima_estrategia": "localizar prova do atributo e contexto corretos",
                    }
                fields.append(
                    {
                        **field,
                        "before_baseline": old["before"],
                        "after_interactive": old["after"],
                        "after_deep": after,
                        "published_status": status,
                        "previous_value_changed": old["before"] is not None
                        and old["before"] != after,
                        "deep_new_field": old["after"] is None and after is not None,
                        "research_gap": gap,
                    }
                )
            published = sum(
                f["after_deep"] is not None and f["published_status"] == "verificado"
                for f in fields
            )
            summary = {
                "target": target,
                "before_baseline": prior["before_published"],
                "after_interactive": prior["after_published"],
                "after_deep": published,
                "previous_values_changed": sum(f["previous_value_changed"] for f in fields),
                "deep_new_fields": [f["field"] for f in fields if f["deep_new_field"]],
                "deep_new_verified_fields": [
                    f["field"]
                    for f in fields
                    if f["deep_new_field"] and f["published_status"] == "verificado"
                ],
                "conflicts": [f["field"] for f in fields if f["published_status"] == "divergente"],
                "fields": fields,
                "runs": exported_runs,
            }
            report["targets"].append(summary)
            lines.extend(
                [
                    f"## {target['marca']} {target['modelo']} {target['versao']} "
                    f"— MY{target['ano_modelo']}",
                    "",
                    f"Inicial: {summary['before_baseline']}/54; "
                    f"interativa: {summary['after_interactive']}/54; "
                    f"após continuação: {published}/54. Valores anteriores alterados: "
                    f"{summary['previous_values_changed']}.",
                    "",
                    "| Campo | Valor publicado | Situação da auditoria | Motivo / próxima ação |",
                    "|---|---|---|---|",
                ]
            )
            for field in fields:
                value = (
                    json.dumps(field["after_deep"], ensure_ascii=False)
                    if field["after_deep"] is not None
                    else "—"
                )
                gap = field["research_gap"] or {}
                reason = (
                    field["reason"]
                    or "Prova e gabarito histórico compatíveis; revisão independente pendente."
                )
                if field["after_deep"] is None:
                    next_step = gap.get("proxima_estrategia", "localizar prova aplicável")
                    reason = f"{gap.get('etapa_em_que_parou', reason)} → {next_step}"
                    if gap.get("motivo_da_rejeicao"):
                        reason += "; " + "; ".join(gap["motivo_da_rejeicao"])
                cells = [field["field"], value, field["result"], reason]
                lines.append(
                    "| "
                    + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells)
                    + " |"
                )
            lines.append("")
    (output / "deep-before-after.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "lacunas.md").write_text("\n".join(lines), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/quality"))
    args = parser.parse_args()
    result = write_report(args.database, args.output)
    print(
        json.dumps(
            [
                {k: v for k, v in t.items() if k not in {"fields", "runs"}}
                for t in result["targets"]
            ],
            ensure_ascii=False,
        )
    )
