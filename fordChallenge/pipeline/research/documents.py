"""Originais de PDF endereçados pelo conteúdo, antes de qualquer leitura."""

import hashlib
import os
import tempfile
from pathlib import Path


def preservar_pdf(dados: bytes) -> tuple[str, str]:
    """Devolve caminho absoluto e hash binário; nunca deriva bytes de texto."""
    if not dados.startswith(b"%PDF"):
        raise ValueError("bytes originais sem assinatura PDF")
    digest = hashlib.sha256(dados).hexdigest()
    directory = Path(os.environ.get("RESEARCH_DOCUMENT_DIR", "data/research-documents"))
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{digest}.pdf"
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise ValueError("original preservado com hash divergente")
        return str(destination.resolve()), digest
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as temporary:
        path = Path(temporary.name)
        temporary.write(dados)
    try:
        path.replace(destination)
    finally:
        path.unlink(missing_ok=True)
    return str(destination.resolve()), digest
