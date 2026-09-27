"""Cadastro de documentos por aplicação e finalidade; sem respostas preenchidas."""

import os
from pathlib import Path

import yaml

from pipeline.research.search import Achado


def known_sources(target) -> list[Achado]:
    path = Path(os.environ.get("RESEARCH_SOURCE_REGISTRY", "pipeline/research/acervo.yaml"))
    records = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []
    return [
        Achado(
            url=r["url"],
            titulo=r.get("titulo", ""),
            provedor="acervo",
            snippet="",
            posicao=0,
            consulta="acervo cadastrado",
        )
        for r in records or []
        if r.get("marca") == target.marca
        and r.get("modelo") == target.modelo
        and (not r.get("versoes") or target.versao in r["versoes"])
        and (not r.get("anos_modelo") or target.ano in r["anos_modelo"])
    ]
