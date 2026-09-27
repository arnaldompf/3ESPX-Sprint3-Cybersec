"""Pending PDF text must not re-enter extraction after a rejected sidecar."""

import json
import subprocess
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from pipeline import deadline, run, snapshots
from pipeline.parse.pdf import DocumentoPdf, Tabela
from pipeline.research import reprocess
from pipeline.research import run as research
from pipeline.store import Snapshot


def pending_document():
    native = "Ford Ranger Limited MY2027 Brasil"
    ocr = "Camera 360: Sim (OCR pendente)"
    return DocumentoPdf(
        native + "\n\n" + ocr,
        [native, ocr],
        [Tabela(1, [["Versão", "Limited"], ["Motor", "3.0"]])],
        "pdfplumber+rapidocr",
        diagnosticos=[
            {"pagina": 1, "status": "complete"},
            {
                "pagina": 2,
                "status": "needs_review",
                "motor": "rapidocr",
                "native_text": "",
                "ocr_text": ocr,
            },
        ],
        status="partial",
    )


def snapshot(tmp_path, text):
    (tmp_path / "doc.md").write_text(text, encoding="utf-8")
    return Snapshot(
        "v",
        "s",
        "2026-09-14",
        tmp_path,
        {"tipo": "pdf_oficial", "sha256": snapshots.sha256_de(text)},
    )


@pytest.mark.parametrize("sidecar", ["full_ocr", "malformed", "tables_only"])
def test_rejected_pdf_cannot_fall_back_to_text_or_connector_snapshot(tmp_path, sidecar):
    doc = pending_document()
    snap = snapshot(tmp_path, doc.markdown)
    if sidecar == "tables_only":
        (tmp_path / "tables.json").write_text(doc.tables_json(), encoding="utf-8")
    else:
        (tmp_path / "documento.json").write_text(
            "not json" if sidecar == "malformed" else json.dumps(asdict(doc)),
            encoding="utf-8",
        )
    documents, accepted, warnings = run.documentos_de("v", "Limited", snapshots=[snap])
    assert documents == []
    assert accepted == []
    assert any("s:" in warning and "PDF" in warning for warning in warnings)


def test_partial_pdf_with_safe_saved_text_keeps_native_page_and_table(tmp_path):
    doc = pending_document()
    snap = snapshot(tmp_path, doc.texto_para_extracao())
    (tmp_path / "documento.json").write_text(json.dumps(asdict(doc)), encoding="utf-8")
    documents, accepted, warnings = run.documentos_de("v", "Limited", snapshots=[snap])
    assert accepted == [snap] and not warnings
    assert len(documents) == 1 and documents[0].texto == doc.texto_para_extracao()
    assert "OCR pendente" not in documents[0].texto
    assert documents[0].n_tabelas == 1 and documents[0].celulas


def test_collection_deadline_uses_tree_cancellation(monkeypatch):
    process = SimpleNamespace(pid=12345)

    def communicate(**kwargs):
        raise subprocess.TimeoutExpired("local PDF worker", 0.01)

    process.communicate = communicate
    terminated = []
    monkeypatch.setattr(reprocess.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(reprocess, "_encerrar", lambda p: terminated.append(p.pid))
    with deadline.budget(0.5):
        result = research._texto_da_pagina("https://ford.com.br/ficha.pdf", "", b"%PDF-1.7")
    assert result.parse_status == "failed"
    assert terminated == [12345]


def test_collection_offline_worker_preserves_diagnostics_and_safe_text(monkeypatch):
    doc = pending_document()
    calls = []

    def execute(data, pages, timeout):
        calls.append((data, pages, timeout))
        return asdict(doc)

    monkeypatch.setattr(reprocess, "_executar", execute)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("unmanaged parser subprocess")
    )
    with deadline.budget(5):
        result = research._texto_da_pagina("https://ford.com.br/ficha.pdf", "", b"%PDF-1.7")
    assert calls and calls[0][:2] == (b"%PDF-1.7", None)
    assert 0 < calls[0][2] <= 5
    assert result.texto == doc.texto_para_extracao()
    assert result.documento_pdf.diagnosticos == doc.diagnosticos
    assert result.parse_status == "partial"
