"""Reextrai capturas existentes sem rede/IA e revalida a publicação com a política atual.

O checkpoint antigo fornece somente documentos originais: candidatos e decisões antigas
não são tratados como válidos pela nova política. --apply exige backup SQLite novo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--checkpoint", action="append", required=True, type=Path)
    parser.add_argument("--pbe-cache", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if not args.database.is_file() or args.output.exists():
        parser.error("o banco deve existir e o relatório deve ser novo")
    if args.apply and (not args.backup or args.backup.exists()):
        parser.error("--apply exige --backup em arquivo novo")

    # Não há coleta: os clientes de rede estão bloqueados abaixo. A escrita das
    # cópias verificadas precisa estar habilitada para fontes novas do cache.
    os.environ["REPLAY_MODE"] = "0"
    os.environ["LLM_FAKE"] = "1"
    from sqlmodel import Session, create_engine, select

    from api.app.models import Brand, VehicleModel, Version
    from api.app.services.spec_assembler import montar
    from pipeline.parse.pdf import DocumentoPdf, Tabela
    from pipeline.publication import POLICY_VERSION
    from pipeline.research import gaps, planner
    from pipeline.research.events import Trilha
    from pipeline.research.persistir import persistir_pesquisa
    from pipeline.research.run import Fonte, Leitor, Resultado, _documentos_de

    if args.apply:
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(args.database) as original, sqlite3.connect(args.backup) as backup:
            original.backup(backup)
    report = {
        "policy": POLICY_VERSION,
        "applied": args.apply,
        "backup": str(args.backup or ""),
        "network_calls": 0,
        "llm_calls": 0,
        "certified_90_percent": False,
        "independent_precision": None,
        "vehicles": [],
    }
    engine = create_engine("sqlite:///" + args.database.resolve().as_posix())
    with (
        Session(engine) as session,
        patch("pipeline.fetch.http.fetch", side_effect=AssertionError("rede desabilitada")),
        patch("pipeline.connectors.fipe.price", side_effect=AssertionError("serviço desabilitado")),
    ):
        for checkpoint_path in args.checkpoint:
            saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            target = planner.Alvo(**saved["target"])
            version = session.exec(
                select(Version)
                .join(VehicleModel)
                .join(Brand)
                .where(
                    Brand.nome == target.marca,
                    VehicleModel.nome == target.modelo,
                    Version.nome_exato == target.versao,
                    Version.ano_modelo == target.ano,
                )
            ).one()
            before = montar(session, version.id)
            sources = []
            for raw in saved["fontes"]:
                if not raw["baixada"] or not raw["texto"]:
                    continue
                if hashlib.sha256(raw["texto"].encode()).hexdigest() != raw["sha256"]:
                    raise ValueError("hash incompatível no checkpoint: " + raw["url"])
                if raw.get("documento_pdf"):
                    pdf = raw["documento_pdf"]
                    pdf["tabelas"] = [Tabela.from_dict(t) for t in pdf["tabelas"]]
                    raw["documento_pdf"] = DocumentoPdf(**pdf)
                sources.append(Fonte(**raw))
            if args.pbe_cache:
                metadata = json.loads((args.pbe_cache / "metadata.json").read_text())
                pdf = args.pbe_cache / "source.pdf"
                if hashlib.sha256(pdf.read_bytes()).hexdigest() != metadata["sha256"]:
                    raise ValueError("hash do PDF PBE não confere")
                rows = json.loads((args.pbe_cache / "rows.json").read_text(encoding="utf-8"))
                text = "\n".join(rows)
                sources.append(
                    Fonte(
                        url=metadata["url"],
                        tier=2,
                        tipo="pbe",
                        consulta="cache oficial",
                        motivo="Reextração do PDF oficial preservado por SHA256",
                        texto=text,
                        sha256=hashlib.sha256(text.encode()).hexdigest(),
                        captured_at=metadata["captured_at"],
                        baixada=True,
                        raw_path=str(pdf.resolve()),
                    )
                )
            budget = gaps.Orcamento(chamadas_llm=0, segundos=120, paginas=0, rodadas=0)
            trail = Trilha()
            reader = Leitor(target, budget, trail, fipe_somente_snapshots=True)
            spec, warnings = reader.ler(
                _documentos_de(sources, target), campos=gaps.campos_procuraveis(), fontes=sources
            )
            result = Resultado(
                target.marca,
                target.modelo,
                target.versao,
                spec,
                trail,
                gaps.medir(spec),
                budget,
                gaps.Motivo.SEM_PROGRESSO,
                fontes=sources,
                avisos=warnings,
            )
            persistence = persistir_pesquisa(
                session,
                result,
                run_id="offline-revalidation",
                marca=target.marca,
                modelo=target.modelo,
                versao=target.versao,
                ano_modelo=target.ano,
            )
            if not persistence.ok:
                raise ValueError(persistence.erros)
            after = montar(session, version.id)
            report["vehicles"].append(
                {
                    "target": saved["target"],
                    "version_id": version.id,
                    "checkpoint": str(checkpoint_path),
                    "source_policy": saved["policy"],
                    "before_coverage": gaps.medir(before).to_dict(),
                    "after_coverage": gaps.medir(after).to_dict(),
                    "before": before.model_dump(mode="json"),
                    "after": after.model_dump(mode="json"),
                    "persistence": persistence.to_dict(),
                    "warnings": warnings,
                    "sources": [
                        {
                            "url": f.url,
                            "sha256": f.sha256,
                            "captured_at": f.captured_at,
                            "raw_path": f.raw_path,
                        }
                        for f in sources
                    ],
                }
            )
        if args.apply:
            session.commit()
        else:
            session.rollback()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            [{"target": v["target"], "coverage": v["after_coverage"]} for v in report["vehicles"]],
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
