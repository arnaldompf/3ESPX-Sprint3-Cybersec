"""Texto OCR pendente não pode servir de prova para sua própria publicação."""

from pipeline.parse.pdf import DocumentoPdf, Tabela
from pipeline.research import run
from pipeline.research.planner import Alvo


def test_document_builder_uses_only_extractable_text_and_tables(monkeypatch):
    native = "Ford Ranger Limited 2027 Brasil"
    ocr = "Paddle shifters: Sim\nCâmera 360: Sim"
    unsafe = Tabela(2, [["Versão", "Limited"], ["Paddle shifters", "Sim"]])
    doc = DocumentoPdf(native + "\n" + ocr, [native, ocr], [unsafe], "pdfplumber")
    monkeypatch.setattr(DocumentoPdf, "texto_para_extracao", lambda self: native, raising=False)
    monkeypatch.setattr(DocumentoPdf, "tabelas_para_extracao", lambda self: [], raising=False)
    source = run.Fonte(
        "https://www.ford.com.br/ranger/ficha.pdf",
        1,
        "oficial",
        "acervo",
        texto=doc.markdown,
        baixada=True,
        tipo="pdf_oficial",
        documento_pdf=doc,
    )
    documents = run._documentos_de([source], Alvo("Ford", "Ranger", "Limited", 2027))
    assert documents[0].texto == native
    assert documents[0].n_tabelas == 0
    assert not documents[0].celulas


def test_collection_returns_safe_text_but_preserves_full_ocr(monkeypatch):
    from pipeline.parse import pdf

    native = "Ford Ranger Limited 2027 Brasil"
    doc = DocumentoPdf(native + "\nCâmera 360: Sim", [native], [], "pdfplumber")
    monkeypatch.setattr(DocumentoPdf, "texto_para_extracao", lambda self: native, raising=False)
    monkeypatch.setattr(pdf, "parse_pdf", lambda data: doc)
    result = run._texto_da_pagina("https://ford.com.br/ficha.pdf", "", b"%PDF-1.7")
    assert result.texto == native
    assert "Câmera 360" in result.documento_pdf.markdown
