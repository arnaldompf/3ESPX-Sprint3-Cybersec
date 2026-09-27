import json

from scripts.independent_eval_protocol import exposure_audit, freeze_blockers, prepare


def proposal():
    return {
        "sources": {},
        "cases": [
            {
                "id": "toro",
                "leakage_group": "fiat_toro",
                "target": {"modelo": "Toro"},
                "proposed_split": "reserved_proposal",
                "primary_source_ids": [],
            }
        ],
    }


def test_geracao_nova_nao_apaga_exposicao_da_familia(tmp_path):
    search = tmp_path / "tests/fixtures/search"
    search.mkdir(parents=True)
    (search / "old.json").write_text(
        json.dumps({"veiculo": "Fiat Toro Ranch 2.0 Diesel 2024"}), encoding="utf-8"
    )
    p = tmp_path / "proposal.json"
    p.write_text(json.dumps(proposal()), encoding="utf-8")
    manifest, packet = prepare(tmp_path, p, ["potencia_cv"])
    assert manifest["cases"][0]["admissible_split_now"] == "development"
    assert not manifest["frozen"] and not manifest["evaluation_executed"]
    assert packet["cases"][0]["reviews"] == {}
    assert manifest["precision"] is None


def test_nenhuma_ocorrencia_nao_equivale_a_ausencia_de_vazamento(tmp_path):
    result = exposure_audit(tmp_path, proposal())
    assert result["fiat_toro"]["status"] == "manual_exposure_review_pending"


def test_revisor_repetido_e_hash_falso_impedem_congelamento(tmp_path):
    p = tmp_path / "proposal.json"
    p.write_text(json.dumps(proposal()), encoding="utf-8")
    manifest, _ = prepare(tmp_path, p, ["potencia_cv"])
    case = manifest["cases"][0]
    case["admissible_split_now"] = "reserved_approved"
    case["identity_review"] = {"reviewer": "r1"}
    case["adjudicated"] = True
    original = tmp_path / "source.txt"
    original.write_text("Potência 200 cv", encoding="utf-8")
    case["source_documents"] = [{"path": "source.txt", "sha256": "0" * 64}]
    case["field_reviews"] = {
        "potencia_cv": {
            "state": "present",
            "value": 200,
            "reviewers": ["r1", "r1"],
            "reviewed_without_predictions": True,
            "citations": [],
        }
    }
    blockers = freeze_blockers(manifest, tmp_path)
    assert "toro:invalid_document_hash_or_path" in blockers
    assert "toro:potencia_cv:independent_reviewers_missing" in blockers
    assert "toro:potencia_cv:missing_primary_evidence_locator" in blockers
    assert "toro:prior_exposure_not_cleared" in blockers
