"""Offline PDF reprocessing report; never publishes or rewrites the input checkpoint.

Example: python scripts/reprocess_research_documents.py --checkpoint saved.json
    --output reports/local-reparse.json --page 9
The report's fontes can be passed back to this command for another selected page.
It is a document artifact, not a ready-to-publish research checkpoint.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import asdict, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.research.reprocess import reprocessar_fonte  # noqa: E402


def _write_new(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _local(path: Path) -> Path:
    if str(path).startswith(("\\\\", "//")) or "://" in str(path):
        raise ValueError("entrada e saída precisam ser caminhos locais")
    return path.resolve()


def reprocessar_checkpoint(
    checkpoint: Path, output: Path, *, paginas: list[int] | None = None, timeout: float = 60
) -> dict:
    from pipeline.research.run import Fonte

    checkpoint = _local(checkpoint)
    output = _local(output)
    original = checkpoint.read_bytes()
    payload = json.loads(original)
    if not isinstance(payload, dict) or not isinstance(payload.get("fontes"), list):
        raise ValueError("entrada precisa conter a lista fontes do checkpoint")
    documents_dir = output.with_name(output.stem + ".documents")
    protected = {checkpoint}
    for source in payload["fontes"]:
        if not isinstance(source, dict):
            raise ValueError("fonte inválida no checkpoint")
        if source.get("raw_path"):
            raw_path = Path(source["raw_path"])
            if not str(raw_path).startswith(("\\\\", "//")) and "://" not in str(raw_path):
                protected.add(raw_path.resolve())
    if output in protected or any(
        documents_dir == p or documents_dir in p.parents for p in protected
    ):
        raise ValueError("saída não pode substituir checkpoint ou documentos originais")
    if output.exists() or documents_dir.exists():
        raise FileExistsError("saída deve ser nova; versões anteriores são preservadas")
    if paginas is not None and any(type(p) is not int or p < 1 for p in paginas):
        raise ValueError("páginas físicas devem ser inteiros positivos")
    known = {f.name for f in fields(Fonte)}
    sources = copy.deepcopy(payload["fontes"])
    report = {
        "schema_version": 1,
        "artifact_type": "offline_pdf_reprocess_report",
        "checkpoint_origem": str(checkpoint),
        "checkpoint_sha256": hashlib.sha256(original).hexdigest(),
        "target": payload.get("target"),
        "policy": payload.get("policy"),
        "paginas_solicitadas": paginas,
        "pagina_semantica": "páginas físicas base 1; seleção de OCR/layout; digital integral",
        "network_calls": 0,
        "llm_calls": 0,
        "database_writes": 0,
        "coverage_gain": None,
        "certified": False,
        "fontes": sources,
        "documentos": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    documents_dir.mkdir()
    for index, source in enumerate(sources):
        is_pdf = (
            source.get("e_pdf")
            or source.get("mime_type") == "application/pdf"
            or str(source.get("raw_path", "")).lower().endswith(".pdf")
            or str(source.get("url", "")).split("?", 1)[0].lower().endswith(".pdf")
        )
        if not is_pdf:
            continue
        fonte = Fonte(**{key: value for key, value in source.items() if key in known})
        result = reprocessar_fonte(fonte, paginas=paginas, timeout=timeout)
        source.update(asdict(result))
        # The original remains the capture identity; no derived text gets its path.
        record = {
            "indice": index,
            "url": result.url,
            "raw_path": result.raw_path,
            "sha256_binario": result.sha256_binario,
            "sha256_texto": result.sha256,
            "parse_status": result.parse_status,
            "fetch_ok": result.fetch_ok,
            "erro": result.erro,
            "before": {
                "parse_status": fonte.parse_status,
                "sha256": fonte.sha256,
                "schema_version": (payload["fontes"][index].get("documento_pdf") or {}).get(
                    "schema_version", 1
                ),
            },
        }
        if result.documento_pdf is not None:
            prefix = f"{index:04d}-{result.sha256_binario[:12]}"
            text_path = documents_dir / (prefix + ".txt")
            document_path = documents_dir / (prefix + ".json")
            _write_new(text_path, result.texto)
            _write_new(document_path, json.dumps(asdict(result.documento_pdf), ensure_ascii=False))
            record.update(text_path=str(text_path), documento_path=str(document_path))
        report["documentos"].append(record)
    statuses = [item["parse_status"] for item in report["documentos"]]
    errors = sum(s not in {"complete", "partial"} for s in statuses)
    report["contagem"] = {
        "complete": statuses.count("complete"),
        "partial": statuses.count("partial"),
        "errors": errors,
        "pdfs": len(statuses),
        "outras_fontes": len(sources) - len(statuses),
    }
    report["status"] = "errors" if errors else ("partial" if "partial" in statuses else "complete")
    if checkpoint.read_bytes() != original:
        raise RuntimeError("checkpoint de entrada mudou durante o reprocessamento")
    _write_new(output, json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--page", type=int, action="append")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    try:
        report = reprocessar_checkpoint(
            args.checkpoint, args.output, paginas=args.page, timeout=args.timeout
        )
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        parser.exit(2, f"reprocessamento não concluído: {exc}\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": report["status"],
                "contagem": report["contagem"],
            },
            ensure_ascii=True,
        )
    )
    return 2 if report["status"] == "errors" else 0


if __name__ == "__main__":
    raise SystemExit(main())
