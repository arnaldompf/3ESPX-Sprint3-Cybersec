"""Pesquisa auditável de uma configuração existente, com orçamento explícito."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=420)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--pages", type=int, default=30)
    parser.add_argument("--llm-calls", type=int, default=6)
    parser.add_argument("--resume-from", type=Path)
    args = parser.parse_args()
    if not args.database.is_file() or args.output.exists():
        parser.error("banco deve existir e relatório de saída deve ser novo")

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    from sqlmodel import Session, create_engine

    from api.app.models import Brand, ResearchRun, VehicleModel, Version
    from api.app.routers.research import gravar
    from api.app.services.spec_assembler import montar
    from pipeline.research import gaps
    from pipeline.research.persistir import persistir_pesquisa
    from pipeline.research.run import pesquisar

    engine = create_engine("sqlite:///" + args.database.resolve().as_posix())
    with Session(engine) as session:
        version = session.get(Version, args.version_id)
        if version is None:
            parser.error("configuração não existe neste banco")
        model = session.get(VehicleModel, version.model_id)
        brand = session.get(Brand, model.brand_id)
        identity = {"marca": brand.nome, "modelo": model.nome, "versao": version.nome_exato}
        year = version.ano_modelo
        before = montar(session, version.id)
        row = ResearchRun(**identity, version_id=version.id, provedor_de_busca="configurado")
        session.add(row)
        session.commit()
        run_id = row.id

    args.output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output.with_suffix(".checkpoint.json")
    if args.resume_from:
        # load() ainda exige a mesma identidade/política; os contadores são acumulados.
        if checkpoint.exists():
            parser.error("checkpoint de saída já existe")
        checkpoint.write_bytes(args.resume_from.read_bytes())
    try:
        result = pesquisar(
            **identity,
            ano=year,
            orcamento=gaps.Orcamento(
                rodadas=args.rounds,
                paginas=args.pages,
                segundos=args.seconds,
                chamadas_llm=args.llm_calls,
            ),
            checkpoint_path=str(checkpoint),
            ao_evento=lambda e: print(f"{e.decorrido:6.1f}s {e.tipo}: {e.texto}", flush=True),
        )
        with Session(engine) as session:
            saved = persistir_pesquisa(session, result, run_id=run_id, **identity, ano_modelo=year)
            if not saved.ok:
                raise RuntimeError("; ".join(saved.erros))
            gravar(session, run_id, result, gravacao=saved)
            session.commit()
            after = montar(session, args.version_id)
        report = {
            "run_id": run_id,
            "database": str(args.database.resolve()),
            "target": {**identity, "ano_modelo": year, "version_id": args.version_id},
            "before": before.model_dump(mode="json"),
            "after": after.model_dump(mode="json"),
            "before_coverage": gaps.medir(before).to_dict(),
            "after_coverage": gaps.medir(after).to_dict(),
            "research": result.to_dict(),
            "persistence": saved.to_dict(),
            "independent_precision": None,
            "certified_90_percent": False,
        }
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"run_id": run_id, "coverage": report["after_coverage"]}), flush=True)
    except Exception as exc:
        with Session(engine) as session:
            row = session.get(ResearchRun, run_id)
            row.status, row.erro = "falhou", f"{type(exc).__name__}: {exc}"[:2000]
            session.add(row)
            session.commit()
        raise


if __name__ == "__main__":
    main()
