"""Audita os 54 campos das duas configurações piloto, sem rede nem escrita no banco.

O gabarito histórico é comparador auxiliar. Sem revisão independente da aplicação das
fontes e conjunto reservado, o relatório não emite certificado de precisão ≥99%.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

from pipeline.eval.compare import comparar_valor
from pipeline.eval.gabarito import carregar_gabarito
from pipeline.ground import locate
from pipeline.identity import Applicability, VehicleTarget, assess, claim_rejection
from pipeline.publication import POLICY_VERSION
from pipeline.research.gaps import campos_procuraveis
from pipeline.semantics import rejection_reason, validate_date, validate_list, validate_number


def proofs(conn, version_id, field, fallback):
    """Audita todas as provas da decisão pública, inclusive as não projetadas em SQL."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='field_decisions'").fetchone():
        return fallback
    row = conn.execute(
        "SELECT payload FROM field_decisions WHERE version_id=? AND field=? "
        "ORDER BY criado_em DESC,id DESC LIMIT 1",
        (version_id, field),
    ).fetchone()
    if row is None:
        return fallback
    payload = json.loads(row[0])
    result = []
    for evidence in payload.get("evidences", []):
        snapshot = conn.execute(
            "SELECT text_path,sha256 FROM snapshots WHERE id=?", (evidence.get("snapshot_id"),)
        ).fetchone()
        result.append(
            {
                "value": payload.get("value"),
                "status": payload["status"],
                "unit": payload.get("unit"),
                **evidence,
                "text_path": snapshot[0] if snapshot else None,
                "sha256": snapshot[1] if snapshot else None,
            }
        )
    return result or [
        {
            "value": payload.get("value"),
            "status": payload["status"],
            "unit": payload.get("unit"),
            "text_path": None,
            "source_url": "",
            "quote": "",
        }
    ]


def check_proof(name, candidate, target):
    source = Path(candidate["text_path"]) if candidate.get("text_path") else None
    text = source.read_text(encoding="utf-8") if source and source.exists() else ""
    quote = candidate.get("quote") or ""
    identity = assess(target, text, url=candidate.get("source_url") or "")
    from pipeline.connectors import vw_manual_warranty
    from pipeline.connectors.ford_warranty import supports as warranty_supports
    from pipeline.connectors.pbe import supports as pbe_supports
    from pipeline.identity import IdentityAssessment

    if warranty_supports(name, target, text, candidate.get("source_url") or "", quote):
        identity = IdentityAssessment(Applicability.COMPATIBLE, ("garantia_modelo_ano_explicitos",))
    scoped_vw_warranty = vw_manual_warranty.supports(
        name, target, text, candidate.get("source_url") or "", quote, candidate["value"]
    )
    if scoped_vw_warranty:
        identity = IdentityAssessment(
            Applicability.COMPATIBLE, ("garantia_geral_com_elo_indice_oficial_my_pdf",)
        )
    scoped_pbe = pbe_supports(
        name, target, text, candidate.get("source_url") or "", quote, candidate["value"]
    )
    if scoped_pbe:
        identity = IdentityAssessment(
            Applicability.COMPATIBLE, ("linha_oficial_pbe_versao_my_exatos",)
        )
    grounded = locate(quote, text).ok
    hash_ok = bool(text and hashlib.sha256(text.encode()).hexdigest() == candidate.get("sha256"))
    reason = (
        (
            "cadeia_garantia_vw_invalida_ou_campo_fora_do_escopo"
            if vw_manual_warranty.is_chain(text) and not scoped_vw_warranty
            else None
        )
        or claim_rejection(
            target, quote, source_text="" if (scoped_pbe or scoped_vw_warranty) else text
        )
        or rejection_reason(name, quote, url=candidate.get("source_url") or "")
    )
    if not hash_ok:
        reason = "snapshot_ausente_ou_hash_invalido"
    elif not grounded:
        reason = "evidencia_nao_localizada"
    elif identity.status != Applicability.COMPATIBLE:
        reason = "incompatibilidade_ou_identidade_insuficiente"
    elif not validate_number(name, candidate["value"], quote, candidate.get("unit")):
        reason = reason or "normalizacao_sem_suporte"
    elif not validate_list(name, candidate["value"], quote):
        reason = reason or "itens_sem_prova_no_trecho_publicado"
    elif not validate_date(name, candidate["value"], quote):
        reason = reason or "data_sem_prova_no_trecho_publicado"
    return {
        "source_url": candidate.get("source_url"),
        "grounded": grounded,
        "hash_ok": hash_ok,
        "applicability": {"status": identity.status, "reasons": identity.reasons},
        "valid": not reason,
        "reason": reason or "",
    }


def audit(database: Path) -> dict:
    conn = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    vehicles = conn.execute("""SELECT v.id, b.nome marca, m.nome modelo,
        v.nome_exato versao, v.ano_modelo FROM versions v
        JOIN models m ON m.id=v.model_id JOIN brands b ON b.id=m.brand_id
        WHERE (m.nome='Ranger' AND v.nome_exato LIKE '%Limited%')
           OR (m.nome='Amarok' AND v.nome_exato LIKE '%Extreme%')""").fetchall()
    gold = carregar_gabarito()
    report = {
        "policy_version": POLICY_VERSION,
        "mode": "banco_e_snapshots_locais",
        "code": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_changes": bool(
            subprocess.check_output(["git", "diff", "--name-only"], stderr=subprocess.DEVNULL)
        ),
        "certificado": False,
        "precisao_independente": None,
        "limitacoes": [
            "gabarito histórico parcial; não equivale a 54 campos revisados",
            "piloto reservado de 12 configurações ainda não possui gabarito independente",
        ],
        "vehicles": [],
    }
    for vehicle in vehicles:
        target = VehicleTarget(
            vehicle["marca"], vehicle["modelo"], vehicle["versao"], vehicle["ano_modelo"]
        )
        expected = next(
            (
                v
                for v in gold.veiculos
                if v.marca == target.marca
                and v.modelo == target.modelo
                and v.ano_modelo == target.ano_modelo
                and (
                    "limited" in v.versao.lower()
                    if "Limited" in target.versao
                    else "extreme" in v.versao.lower()
                )
            ),
            None,
        )
        expected_fields = {c.campo: c for c in expected.campos} if expected else {}
        rows = conn.execute(
            """SELECT sv.field, sv.value_json, sv.status, sv.unit,
            e.source_url,e.quote,e.tier,s.text_path,s.sha256 FROM spec_values sv
            LEFT JOIN evidences e ON e.id=sv.evidence_id
            LEFT JOIN snapshots s ON s.id=e.snapshot_id WHERE sv.version_id=?""",
            (vehicle["id"],),
        ).fetchall()
        fields = []
        for name in campos_procuraveis():
            candidates = [dict(r) for r in rows if r["field"] == name]
            for c in candidates:
                try:
                    c["value"] = (
                        json.loads(c["value_json"])
                        if isinstance(c["value_json"], str)
                        else c["value_json"]
                    )
                except ValueError:
                    c["value"] = c["value_json"]
                c.pop("value_json", None)
            candidates = proofs(conn, vehicle["id"], name, candidates)
            values = [c for c in candidates if c["value"] is not None]
            item = {
                "field": name,
                "published": values,
                "result": "desconhecido",
                "reason": "documento_sem_informacao_suficiente",
                "gold_matches": False,
            }
            if (
                any(c["status"] == "divergente" for c in candidates)
                or len({repr(c["value"]) for c in values}) > 1
            ):
                item.update(
                    result="conflito", reason="conflito_legitimo_ou_dado_legado_a_reavaliar"
                )
            elif values:
                c = values[0]
                item["proof_checks"] = [check_proof(name, value, target) for value in values]
                valid = any(p["valid"] for p in item["proof_checks"])
                item["gold_matches"] = bool(
                    name in expected_fields
                    and comparar_valor(name, expected_fields[name].valor, c["value"]).igual
                )
                if not valid:
                    item.update(result="pendente", reason="nenhuma_prova_publicada_suficiente")
                elif c["status"] != "verificado":
                    item.update(result="pendente", reason="status_nao_verificado")
                elif item["gold_matches"]:
                    item.update(result="correto_no_gabarito_com_aplicabilidade", reason="")
                else:
                    item.update(
                        result="pendente", reason="gabarito_independente_ausente_ou_divergente"
                    )
            fields.append(item)
        correct = sum(f["result"] == "correto_no_gabarito_com_aplicabilidade" for f in fields)
        report["vehicles"].append(
            {
                "target": dict(vehicle),
                "fields": fields,
                "denominator": 54,
                "correct_with_evidence": correct,
                "correct_fill": correct / 54,
                "published_fields": sum(
                    bool(f["published"])
                    and all(c["status"] == "verificado" for c in f["published"])
                    for f in fields
                ),
                "conflicted_fields": sum(f["result"] == "conflito" for f in fields),
                "evidence_supported_fields": sum(
                    bool(f.get("proof_checks"))
                    and any(p["valid"] for p in f["proof_checks"])
                    and all(c["status"] == "verificado" for c in f["published"])
                    for f in fields
                ),
                "matches_historical_gold": sum(f["gold_matches"] for f in fields),
                "target_49_met": correct >= 49,
            }
        )
    conn.close()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/quality/pilot.json"))
    args = parser.parse_args()
    report = audit(args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            [
                {
                    **v["target"],
                    "publicados": v["published_fields"],
                    "corretos_com_aplicabilidade": v["correct_with_evidence"],
                    "total": 54,
                }
                for v in report["vehicles"]
            ],
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
