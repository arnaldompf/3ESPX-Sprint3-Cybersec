"""Reparse preserved PDFs offline, returning copies without publication or file writes.

Page numbers are physical, one-based OCR/layout selections. Digital parsing still
reads the complete PDF; a selection must never masquerade as a complete document.
The worker uses only installed parsers and existing local model files.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.parse.pdf import DocumentoPdf
    from pipeline.research.run import Fonte

MAX_BYTES = 50 * 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _paginas(paginas: list[int] | None) -> list[int] | None:
    if paginas is None:
        return None
    if not isinstance(paginas, list) or any(type(p) is not int or p < 1 for p in paginas):
        raise ValueError("páginas devem ser inteiros físicos positivos (base 1)")
    return sorted(set(paginas))


def _documento(value) -> DocumentoPdf | None:
    from pipeline.parse.pdf import DocumentoPdf

    if isinstance(value, DocumentoPdf):
        return copy.deepcopy(value)
    if isinstance(value, dict):
        try:
            return DocumentoPdf.from_dict(value)
        except (TypeError, ValueError, KeyError):
            return None
    return None


def _texto(documento: DocumentoPdf) -> str:
    # Pending OCR remains in the derived document, never in extraction input.
    return documento.texto_para_extracao()


def _encerrar(processo: subprocess.Popen) -> None:
    """Kill the worker tree, including a running local OCR/layout subprocess."""
    if os.name == "nt":
        executable = Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32/taskkill.exe"
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(  # noqa: S603 - system process tool, fixed args, integer PID
                [str(executable), "/PID", str(processo.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(processo.pid, signal.SIGKILL)
    if processo.poll() is None:
        processo.kill()
    processo.communicate(timeout=5)


def _executar(dados: bytes, paginas: list[int] | None, timeout: float) -> dict:
    command = [sys.executable, "-m", "pipeline.research.reprocess", "--worker"]
    if paginas is not None:
        command.append("--selected-pages")
        for page in paginas:
            command.extend(["--page", str(page)])
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    options = (
        {"creationflags": subprocess.CREATE_NO_WINDOW}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    processo = subprocess.Popen(  # noqa: S603 - fixed Python module, bytes through stdin
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        **options,
    )
    try:
        stdout, _ = processo.communicate(input=dados, timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        _encerrar(processo)
        raise
    if processo.returncode:
        raise ValueError("worker de PDF encerrou com erro")
    payload = json.loads(stdout)
    if not isinstance(payload, dict):
        raise ValueError("resposta do worker não é documento")
    return payload


def _mesclar_paginas(
    anterior: DocumentoPdf, novo: DocumentoPdf, paginas: list[int]
) -> DocumentoPdf:
    """Keep previously processed pages byte-for-byte when continuing another page."""
    selected = set(paginas)
    if len(anterior.paginas) != len(novo.paginas):
        raise ValueError("quantidade de páginas mudou para o mesmo PDF")
    old_diags = {d["pagina"]: d for d in anterior.diagnosticos}
    new_diags = {d["pagina"]: d for d in novo.diagnosticos}
    for n in range(1, len(novo.paginas) + 1):
        if n not in selected:
            novo.paginas[n - 1] = anterior.paginas[n - 1]
            if n in old_diags:
                new_diags[n] = copy.deepcopy(old_diags[n])
    novo.tabelas = [t for t in anterior.tabelas if t.pagina not in selected] + [
        t for t in novo.tabelas if t.pagina in selected
    ]
    novo.diagnosticos = [new_diags[n] for n in sorted(new_diags)]
    novo.markdown = "\n\n".join(novo.paginas)
    novo.status = (
        "partial"
        if any(d.get("status") not in {"complete", "empty"} for d in novo.diagnosticos)
        else "complete"
    )
    novo.avisos = list(dict.fromkeys([*anterior.avisos, *novo.avisos]))
    return novo


def reprocessar_fonte(
    fonte: Fonte, *, paginas: list[int] | None = None, timeout: float = 60
) -> Fonte:
    """Return a copied Fonte with verified original bytes and a fresh local parse.

    Failures are explicit parse_status codes, fetch_ok reports verified local bytes,
    and failed parses expose no previous text as a successful new extraction.
    Existing schema-2 documents with a matching text/binary hash can resume selected
    pages. With no selection, their incomplete pages are the OCR/layout targets.
    """
    selected = _paginas(paginas)
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout deve ser positivo e finito")
    result = copy.deepcopy(fonte)
    result.texto = ""
    result.sha256 = ""
    result.documento_pdf = None
    result.baixada = False
    result.fetch_ok = False

    def failure(status: str, message: str) -> Fonte:
        result.parse_status = status
        result.erro = message
        return result

    if not fonte.raw_path:
        return failure("missing_original", "PDF original não preservado")
    if str(fonte.raw_path).startswith(("\\\\", "//")) or "://" in str(fonte.raw_path):
        return failure("missing_original", "reprocessamento exige caminho de arquivo local")
    path = Path(fonte.raw_path)
    try:
        if not path.is_file():
            return failure("missing_original", "arquivo original local ausente")
        if path.stat().st_size > MAX_BYTES:
            return failure("resource_limit", "PDF excede limite de 50 MiB")
        data = path.read_bytes()
    except OSError:
        return failure("missing_original", "arquivo original local não pôde ser lido")
    if len(data) > MAX_BYTES:
        return failure("resource_limit", "PDF excede limite de 50 MiB")
    if not data.startswith(b"%PDF-"):
        return failure("invalid_signature", "arquivo original não tem assinatura PDF")
    binary_sha = _sha(data)
    if fonte.sha256_binario and fonte.sha256_binario.lower() != binary_sha:
        return failure("hash_mismatch", "hash do arquivo original diverge da captura")
    result.sha256_binario = binary_sha
    result.fetch_ok = True
    result.e_pdf = True
    result.mime_type = "application/pdf"
    anterior = _documento(fonte.documento_pdf)
    try:
        resumable = (
            anterior is not None
            and anterior.schema_version == 2
            and fonte.sha256_binario.lower() == binary_sha
            and fonte.sha256 == _sha(_texto(anterior).encode("utf-8"))
        )
    except (TypeError, AttributeError, KeyError, ValueError):
        resumable = False
    if selected is None and resumable:
        selected = [
            d["pagina"]
            for d in anterior.diagnosticos
            if d.get("status") not in {"complete", "empty"}
        ]
    try:
        from pipeline.parse.pdf import DocumentoPdf

        documento = DocumentoPdf.from_dict(_executar(data, selected, timeout))
        if documento.schema_version != 2 or documento.status not in {"partial", "complete"}:
            raise ValueError("schema/status do worker inválido")
        if selected and max(selected) > documento.n_paginas:
            return failure("invalid_pages", "página solicitada fora do PDF original")
        if resumable and selected is not None:
            documento = _mesclar_paginas(anterior, documento, selected)
        texto = _texto(documento)
    except subprocess.TimeoutExpired:
        return failure("timeout", "tempo limite do parser local; original preservado")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return failure("failed", "parser local indisponível ou documento inválido")
    result.documento_pdf = documento
    result.texto = texto
    result.sha256 = _sha(texto.encode("utf-8"))
    result.baixada = bool(texto.strip())
    result.parse_status = documento.status
    result.erro = ""
    return result


def _worker() -> None:
    import argparse
    import contextlib
    import socket
    from dataclasses import asdict

    def no_network(*args, **kwargs):
        raise RuntimeError("rede desabilitada no reprocessamento local")

    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    socket.create_connection = no_network
    socket.getaddrinfo = no_network
    socket.gethostbyname = no_network
    socket.gethostbyname_ex = no_network
    socket.gethostbyaddr = no_network
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true", required=True)
    parser.add_argument("--selected-pages", action="store_true")
    parser.add_argument("--page", action="append", type=int, default=[])
    args = parser.parse_args()
    from pipeline.parse.pdf import parse_pdf

    selected = _paginas(args.page) if args.selected_pages else None
    with contextlib.redirect_stdout(sys.stderr):
        doc = parse_pdf(sys.stdin.buffer.read(), paginas_ocr=selected)
    sys.stdout.write(json.dumps(asdict(doc), ensure_ascii=True))


if __name__ == "__main__":
    _worker()
