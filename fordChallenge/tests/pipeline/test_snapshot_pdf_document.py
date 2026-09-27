"""A leitura do snapshot usa a grade persistida, sem depender de fixture externa."""

import json
from dataclasses import asdict

from pipeline import run, snapshots
from pipeline.parse.pdf import DocumentoPdf, Tabela
from pipeline.store import Snapshot


def test_reads_local_pdf_geometry_and_page_text(tmp_path):
    text = "first page\n\nsecond page"
    table = Tabela(2, [["Versão", "Limited"], ["Motor", "3.0"]])
    parsed = DocumentoPdf(text, ["first page", "second page"], [table], "pdfplumber")
    (tmp_path / "doc.md").write_text(text, encoding="utf-8")
    (tmp_path / "documento.json").write_text(json.dumps(asdict(parsed)), encoding="utf-8")
    snap = Snapshot("v", "s", "2026-09-15", tmp_path, {"sha256": snapshots.sha256_de(text)})
    restored = run._documento_pdf_de(snap)
    assert restored is not None
    assert restored.paginas == parsed.paginas
    assert restored.tabelas[0].pagina == 2
    assert restored.tabelas[0].linhas == table.linhas


def test_rejects_parser_json_that_is_not_the_saved_text(tmp_path):
    (tmp_path / "doc.md").write_text("saved source", encoding="utf-8")
    parsed = DocumentoPdf("other edition", ["other edition"], [], "pdfplumber")
    (tmp_path / "documento.json").write_text(json.dumps(asdict(parsed)), encoding="utf-8")
    snap = Snapshot("v", "s", "2026-09-15", tmp_path, {})
    assert run._documento_pdf_de(snap) is None
