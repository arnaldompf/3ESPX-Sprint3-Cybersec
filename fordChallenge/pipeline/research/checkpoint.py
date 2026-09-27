"""Checkpoint atômico por execução; inclui fontes e candidatos, nunca segredos."""

import json
import os
from dataclasses import asdict
from pathlib import Path

from pipeline.publication import POLICY_VERSION


def job_path(job_id: str) -> Path:
    """Caminho controlado pelo servidor; o cliente nunca informa um arquivo."""
    if not job_id.isalnum():
        raise ValueError("identificador de job inválido")
    return (
        Path(os.environ.get("RESEARCH_CHECKPOINT_DIR", "data/research-checkpoints"))
        / f"{job_id}.json"
    )


def save(path: str, target, fontes, leitor, spec, consultas) -> None:
    if not path:
        return
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "policy": POLICY_VERSION,
        "target": asdict(target),
        "fontes": [asdict(f) for f in fontes],
        "candidatos": {k: [asdict(c) for c in v] for k, v in leitor.candidatos.items()},
        "textos": leitor.textos,
        "estado_leitura": leitor.estado_leitura.to_dict(),
        "leituras": leitor.leituras,
        "spec": spec.model_dump(mode="json"),
        "consultas": sorted(consultas),
        "pending": getattr(leitor, "pending", []),
        "budget_spent": leitor.orcamento.to_dict(),
        "services_budget": leitor.services_budget.to_dict(),
    }
    temporary = file.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(file)


def load(path: str, target) -> dict | None:
    if not path or not Path(path).exists():
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("policy") != POLICY_VERSION or payload.get("target") != asdict(target):
        raise ValueError("checkpoint de outra identidade ou versão da política")
    return payload
