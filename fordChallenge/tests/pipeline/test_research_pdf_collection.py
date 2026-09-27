"""Regressões de integridade entre coleta, parser e retomada de PDFs."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.fetch import http
from pipeline.parse import pdf
from pipeline.research import run

URL = "https://www.ford.com.br/ranger/ficha.pdf"
RAW = b"%PDF-1.7\nbinary\x00\xff\x80\r\n%%EOF"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("REPLAY_MODE", "0")
    monkeypatch.setenv("RESEARCH_DOCUMENT_DIR", str(tmp_path / "originals"))
    monkeypatch.delenv("RESEARCH_EXTRACT_PROVIDER", raising=False)
    monkeypatch.setattr(http, "fetch", lambda *a, **k: pytest.fail("unexpected network"))


def test_textual_pdf_is_never_reencoded_as_original(monkeypatch):
    monkeypatch.setattr(pdf, "parse_pdf", lambda *a, **k: pytest.fail("decoded PDF parsed"))
    result = run._texto_da_pagina(URL, "%PDF-1.7 damaged decoded content", b"")
    assert isinstance(result, run.Coleta)
    assert "originais" in result.erro
    assert not result.documento_pdf


def test_original_is_preserved_before_parser_fails(monkeypatch, tmp_path):
    raw_path = tmp_path / "originals" / f"{hashlib.sha256(RAW).hexdigest()}.pdf"

    def fail_parser(data):
        assert data == RAW
        assert raw_path.read_bytes() == RAW
        raise pdf.PdfIlegivel("scan without OCR runtime")

    monkeypatch.setattr(pdf, "parse_pdf", fail_parser)
    monkeypatch.setattr(
        http,
        "fetch",
        lambda *a, **k: http.Resultado(
            url=URL,
            status="ok",
            conteudo=RAW,
            texto="decoded binary must not matter",
            captured_at="2026-09-15",
            http_status=200,
            headers={"content-type": "application/pdf"},
        ),
    )
    result = run._coletar_fonte(URL)
    assert result.erro
    assert not result.texto
    assert Path(result.raw_path).read_bytes() == RAW
    assert result.sha256_binario == hashlib.sha256(RAW).hexdigest()
    assert result.fetch_ok
    assert result.parse_status == "failed"


def test_pdf_replay_with_only_saved_markdown_remains_text(monkeypatch):
    monkeypatch.setenv("REPLAY_MODE", "1")
    text = "Ford Ranger Limited 2027\n" + "Potência: 250 cv\n" * 20
    monkeypatch.setattr(
        http,
        "fetch",
        lambda *a, **k: http.Resultado(url=URL, status="replay", texto=text, de_replay=True),
    )
    monkeypatch.setattr(pdf, "parse_pdf", lambda *a, **k: pytest.fail("replay markdown parsed"))
    result = run._coletar_fonte(URL)
    assert result.texto == text
    assert not result.raw_path
    assert not result.sha256_binario


def test_archived_pdf_retains_document_and_capture_date(monkeypatch):
    from pipeline.fetch import wayback

    doc = pdf.DocumentoPdf("Ford Ranger Limited 2027\n" * 20, ["table"], [], "pdfplumber")
    monkeypatch.setattr(pdf, "parse_pdf", lambda data: doc)
    monkeypatch.setattr(
        wayback,
        "buscar_arquivada",
        lambda url: SimpleNamespace(ok=True, captured_at="2026-09-01", texto="", conteudo=RAW),
    )
    result = run._pelo_arquivo(URL, ano=2027)
    assert isinstance(result, run.Coleta)
    assert result.documento_pdf is doc
    assert result.captured_at == "2026-09-01"
    assert result.via == "arquivo"
    assert Path(result.raw_path).read_bytes() == RAW


def test_mime_identifies_pdf_without_extension(monkeypatch):
    doc = pdf.DocumentoPdf("Ford Ranger Limited 2027\n" * 20, ["table"], [], "pdfplumber")
    monkeypatch.setattr(pdf, "parse_pdf", lambda data: doc)
    monkeypatch.setattr(
        http,
        "fetch",
        lambda *a, **k: http.Resultado(
            url="https://www.ford.com.br/download/123",
            status="ok",
            conteudo=RAW,
            headers={"content-type": "application/pdf"},
        ),
    )
    result = run._coletar_fonte("https://www.ford.com.br/download/123")
    assert result.documento_pdf is doc
    assert result.mime_type == "application/pdf"
    assert result.sha256_binario == hashlib.sha256(RAW).hexdigest()
