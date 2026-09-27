"""Bounded, network-disabled OCR workers using explicit existing local models.

No package/model installation is performed. The original PDF remains unchanged.
OCR coordinates describe the rendered page; OCR never establishes vehicle scope.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path

MODEL_FILES = {
    "Det.model_path": "PP-OCRv6_det_small.onnx",
    "Cls.model_path": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "Rec.model_path": "PP-OCRv6_rec_small.onnx",
}
MAX_BYTES = 50 * 1024 * 1024
MAX_PIXELS = 8_000_000


def modelos_locais(directory: Path | None = None) -> dict[str, str]:
    if directory is None:
        configured = os.environ.get("PDF_OCR_MODEL_DIR", "")
        if configured:
            directory = Path(configured)
        else:
            spec = importlib.util.find_spec("rapidocr")
            if spec is None or not spec.origin:
                raise FileNotFoundError("rapidocr não instalado")
            directory = Path(spec.origin).parent / "models"
    models = {key: str((directory / filename).resolve()) for key, filename in MODEL_FILES.items()}
    for path in models.values():
        if not Path(path).is_file():
            raise FileNotFoundError(f"modelo OCR local ausente: {Path(path).name}")
    return models


def disponibilidade() -> tuple[bool, str]:
    for name in ("rapidocr", "onnxruntime", "pypdfium2"):
        if importlib.util.find_spec(name) is None:
            return False, f"dependência OCR não instalada: {name}"
    try:
        modelos_locais()
    except FileNotFoundError as exc:
        return False, str(exc)
    return True, ""


def ocr_pagina(
    dados: bytes, pagina: int, *, timeout: float = 25, max_pixels: int = MAX_PIXELS
) -> dict:
    base = {
        "pagina": pagina,
        "motor": "rapidocr",
        "source_sha256": hashlib.sha256(dados).hexdigest(),
    }
    if len(dados) > MAX_BYTES or pagina < 1:
        return {**base, "status": "resource_limit", "reason": "limite de bytes/página OCR"}
    available, reason = disponibilidade()
    if not available:
        return {**base, "status": "dependency_unavailable", "reason": reason}
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    try:
        response = subprocess.run(  # noqa: S603 - interpreter/module fixed; PDF bytes via stdin
            [
                sys.executable,
                "-m",
                "pipeline.parse.pdf_ocr",
                str(pagina),
                str(min(MAX_PIXELS, max_pixels)),
            ],
            input=dados,
            capture_output=True,
            timeout=max(0.1, timeout),
            env=env,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
    except subprocess.TimeoutExpired:
        return {**base, "status": "timeout", "reason": "tempo limite do worker OCR"}
    except OSError as exc:
        return {**base, "status": "dependency_unavailable", "reason": type(exc).__name__}
    if response.returncode:
        return {**base, "status": "error", "reason": "worker OCR encerrou com erro"}
    try:
        result = json.loads(response.stdout)
        if not isinstance(result, dict):
            raise ValueError("invalid result")
        return {**base, **result}
    except (ValueError, UnicodeDecodeError):
        return {**base, "status": "error", "reason": "resposta OCR inválida"}


def _no_network(*args, **kwargs):
    raise RuntimeError("downloads e rede desabilitados no worker PDF")


def _bloquear_rede() -> None:
    import socket

    socket.socket.connect = _no_network
    socket.socket.connect_ex = _no_network
    socket.create_connection = _no_network
    # Block RapidOCR's downloader even when it would attempt a missing dictionary.
    try:
        from rapidocr.utils.download_file import DownloadFile

        DownloadFile.run = _no_network
    except ImportError:
        pass


def docling_local(dados: bytes, *, pagina: int | None = None, timeout: float = 30) -> dict:
    configured = os.environ.get("PDF_DOCLING_ARTIFACTS_PATH", "")
    if not configured or not Path(configured).is_dir():
        return {
            "status": "dependency_unavailable",
            "reason": "artefatos locais Docling não configurados",
        }
    if len(dados) > MAX_BYTES:
        return {"status": "resource_limit", "reason": "limite de bytes Docling"}
    env = os.environ.copy()
    env.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        OMP_NUM_THREADS="2",
        PDF_DOCLING_PAGE_TIMEOUT=str(min(55, max(1, timeout))),
    )
    try:
        response = subprocess.run(  # noqa: S603 - fixed local worker; no shell
            [sys.executable, "-m", "pipeline.parse.pdf_ocr", "--docling", str(pagina or 0)],
            input=dados,
            capture_output=True,
            timeout=max(0.1, timeout),
            env=env,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        result = json.loads(response.stdout)
        if response.returncode or not isinstance(result, dict):
            raise ValueError("worker inválido")
        return result
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "tempo limite do worker Docling"}
    except (OSError, ValueError, UnicodeDecodeError):
        return {"status": "error", "reason": "worker Docling indisponível ou resposta inválida"}


def _run(dados: bytes, page_no: int, max_pixels: int) -> dict:
    _bloquear_rede()
    from importlib.metadata import version

    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr import RapidOCR

    models = modelos_locais()
    params = {
        **models,
        "EngineConfig.onnxruntime.use_cuda": False,
        "EngineConfig.onnxruntime.use_dml": False,
        "EngineConfig.onnxruntime.intra_op_num_threads": 2,
        "EngineConfig.onnxruntime.inter_op_num_threads": 2,
        "Global.log_level": "error",
    }
    engine = RapidOCR(params=params)
    document = pdfium.PdfDocument(dados)
    try:
        if not 1 <= page_no <= len(document):
            return {"status": "error", "reason": "página OCR fora do documento"}
        page = document[page_no - 1]
        width, height = page.get_size()
        if width <= 0 or height <= 0 or max_pixels < 1:
            return {"status": "resource_limit", "reason": "dimensões inválidas"}
        scale = min(2.0, math.sqrt(max_pixels / (width * height)) * 0.999)
        if scale < 0.25:
            return {"status": "resource_limit", "reason": "página excede área renderizável"}
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil().convert("RGB")
        result = engine(np.asarray(image))
        regions = []
        texts = result.txts if result.txts is not None else []
        for text, confidence, box in zip(
            texts,
            result.scores if result.scores is not None else [],
            result.boxes if result.boxes is not None else [],
            strict=True,
        ):
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            regions.append(
                {
                    "text": str(text),
                    "confidence": float(confidence),
                    "bbox": [min(xs) / scale, min(ys) / scale, max(xs) / scale, max(ys) / scale],
                    "polygon_pixels": box.tolist(),
                    "coord_origin": "render_top_left",
                    "pagina": page_no,
                }
            )
        return {
            "status": "needs_review" if regions else "empty_ocr",
            "text": "\n".join(r["text"] for r in regions),
            "regions": regions,
            "render": {
                "width_pt": width,
                "height_pt": height,
                "width_px": image.width,
                "height_px": image.height,
                "scale": scale,
                "rotation": page.get_rotation(),
                "bbox_pdfium": list(page.get_bbox()),
                "coord_origin": "render_top_left",
            },
            "models": {
                key: {
                    "filename": Path(path).name,
                    "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                }
                for key, path in models.items()
            },
            "runtime": "onnxruntime CPU, 2 threads",
            "versions": {name: version(name) for name in ("rapidocr", "onnxruntime", "pypdfium2")},
        }
    finally:
        document.close()


def main() -> None:
    # Only JSON reaches stdout; libraries sometimes print initialization notices.
    import contextlib

    data = sys.stdin.buffer.read(MAX_BYTES + 1)
    try:
        if len(data) > MAX_BYTES:
            result = {"status": "resource_limit", "reason": "limite de bytes OCR"}
        else:
            with contextlib.redirect_stdout(sys.stderr):
                if sys.argv[1] == "--docling":
                    _bloquear_rede()
                    from dataclasses import asdict

                    from pipeline.parse.pdf import _docling_inprocess

                    doc = _docling_inprocess(data, int(sys.argv[2]) or None)
                    result = {"status": "parsed", "documento": asdict(doc)}
                else:
                    result = _run(data, int(sys.argv[1]), min(MAX_PIXELS, int(sys.argv[2])))
    except (ImportError, FileNotFoundError) as exc:
        result = {"status": "dependency_unavailable", "reason": str(exc)}
    except Exception as exc:
        result = {
            "status": "error",
            "reason": f"worker OCR: {type(exc).__name__}: {str(exc)[:300]}",
        }
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
