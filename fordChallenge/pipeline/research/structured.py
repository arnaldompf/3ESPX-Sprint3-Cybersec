"""Consulta do PBE independente da busca genérica, indexada por hash da edição."""

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from pipeline import deadline
from pipeline.connectors import pbe
from pipeline.fetch import http


def pbe_source():
    with deadline.budget(25):
        return _pbe_source()


def _pbe_source():
    from pipeline.research.run import Fonte

    if http.modo_replay():
        return None
    index = http.fetch(pbe.URL_PAGINA_DOS_CICLOS, timeout=deadline.timeout(15), tentativas=1)
    if not index.ok:
        raise ValueError(f"índice PBE: {index.status}")
    editions = pbe.descobrir_tabelas(index.texto)
    if not editions:
        raise ValueError("índice PBE sem edição reconhecida")
    edition = editions[0]
    response = http.fetch(edition.url, timeout=deadline.timeout(20), tentativas=1)
    if not response.ok:
        raise ValueError(f"edição PBE: {response.status}")
    digest = hashlib.sha256(response.conteudo).hexdigest()
    directory = Path("data/pbe-index") / digest
    directory.mkdir(parents=True, exist_ok=True)
    cache = directory / "rows.json"
    if cache.exists():
        rows = json.loads(cache.read_text(encoding="utf-8"))
    else:
        (directory / "source.pdf").write_bytes(response.conteudo)
        parsed = subprocess.run(
            [sys.executable, "-m", "pipeline.parse.isolated", "--pbe"],
            input=response.conteudo,
            capture_output=True,
            check=True,
            timeout=deadline.timeout(45),
        )
        rows = json.loads(parsed.stdout)["linhas"]
        cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    metadata = {
        "url": edition.url,
        "ciclo": edition.ciclo,
        "sha256": digest,
        "captured_at": datetime.now(UTC).isoformat(),
    }
    (directory / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    text = "\n".join(rows)
    return Fonte(
        url=edition.url,
        tier=2,
        motivo="PBE: edição indexada por hash",
        consulta="conector PBE direto",
        texto=text,
        tipo="pbe",
        baixada=True,
        captured_at=metadata["captured_at"],
        sha256=hashlib.sha256(text.encode()).hexdigest(),
    )
