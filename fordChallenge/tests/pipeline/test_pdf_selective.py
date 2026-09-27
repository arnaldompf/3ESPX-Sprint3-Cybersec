"""Regression cases for partial PDFs, geometry and offline OCR contracts."""

from types import SimpleNamespace as NS

import pytest

from pipeline.parse import pdf


def test_docling_adapter_keeps_header_and_spans():
    cells = [
        NS(
            text="Versão",
            start_row_offset_idx=0,
            start_col_offset_idx=0,
            row_span=1,
            col_span=1,
            column_header=True,
            row_header=False,
            bbox=None,
        ),
        NS(
            text="Limited",
            start_row_offset_idx=0,
            start_col_offset_idx=1,
            row_span=1,
            col_span=2,
            column_header=True,
            row_header=False,
            bbox=None,
        ),
        NS(
            text="250 cv",
            start_row_offset_idx=1,
            start_col_offset_idx=1,
            row_span=1,
            col_span=2,
            column_header=False,
            row_header=False,
            bbox=None,
        ),
    ]
    table = NS(data=NS(num_rows=2, num_cols=3, table_cells=cells), prov=[NS(page_no=9, bbox=None)])
    got = pdf._tabela_docling(table, 0)
    assert got.linhas[0] == ["Versão", "Limited", ""]
    assert got.linha_de_cabecalho() == 0
    assert got.spans == {"0:1": 2, "1:1": 2}
    assert got.celulas[1]["column_header"]
    assert got.pagina == 9


def test_docling_bbox_origin_is_preserved():
    bbox = NS(l=2, t=90, r=40, b=80, coord_origin=NS(value="BOTTOMLEFT"))
    cell = NS(
        text="V6",
        start_row_offset_idx=0,
        start_col_offset_idx=0,
        row_span=1,
        col_span=1,
        column_header=False,
        row_header=False,
        bbox=bbox,
    )
    table = NS(data=NS(num_rows=1, num_cols=1, table_cells=[cell]), prov=[NS(page_no=2, bbox=bbox)])
    got = pdf._tabela_docling(table, 3)
    assert got.celulas[0]["bbox"] == [2, 90, 40, 80]
    assert got.celulas[0]["coord_origin"] == "BOTTOMLEFT"


def test_geometry_roundtrip_and_old_positional_contract():
    old = pdf.Tabela(2, [["a"]], 3, {"0:0": 2})
    assert old.celulas == []
    old.celulas = [{"row": 0, "col": 0, "bbox": [1, 2, 3, 4], "row_span": 2}]
    old.bbox = [1, 2, 3, 4]
    assert pdf.Tabela.from_dict(old.to_dict()) == old
    doc = pdf.DocumentoPdf("a", ["a"], [old], "pdfplumber")
    assert doc.status == "complete"


def test_tiled_scan_quality_uses_union_not_biggest_image():
    from pipeline.parse.pdf_quality import diagnosticar_pagina

    images = [
        {"x0": c * 10, "x1": (c + 1) * 10, "top": r * 10, "bottom": (r + 1) * 10}
        for c in range(10)
        for r in range(10)
    ]
    page = NS(bbox=(-0.0, 0, 100, 100), chars=[{}] * 43, images=images)
    got = diagnosticar_pagina(page, 2, "App Ford", [])
    assert got["q_pdf"]["image_union_ratio"] == 1.0
    assert got["status"] == "needs_ocr"
    assert got["pagina"] == 2


def test_image_union_handles_overlap_and_shifted_page():
    from pipeline.parse.pdf_quality import area_uniao

    assert area_uniao([[-10, 20, 40, 70], [15, 20, 65, 70]], [-10, 20, 90, 120]) == 3750


def test_empty_page_is_explicit_without_ocr():
    from pipeline.parse.pdf_quality import diagnosticar_pagina

    got = diagnosticar_pagina(NS(bbox=(0, 0, 100, 100), chars=[], images=[]), 1, "", [])
    assert got["status"] == "empty"


def test_cascade_only_ocr_deficient_page_and_preserves_native(monkeypatch):
    doc = pdf.DocumentoPdf(
        "native\n\nApp",
        ["native", "App"],
        [],
        "pdfplumber",
        diagnosticos=[{"pagina": 1, "status": "complete"}, {"pagina": 2, "status": "needs_ocr"}],
    )
    monkeypatch.setattr(pdf, "_MOTORES", {"pdfplumber": lambda _: doc})
    calls = []

    def ocr(data, page, **kwargs):
        calls.append(page)
        return {
            "status": "needs_review",
            "text": "Reduzida 4L",
            "regions": [{"text": "Reduzida 4L", "bbox": [1, 2, 3, 4], "confidence": 0.98}],
            "motor": "rapidocr",
        }

    monkeypatch.setattr(pdf, "_ocr_pagina", ocr)
    got = pdf.parse_pdf(b"%PDF test", motor="pdfplumber")
    assert calls == [2]
    assert got.paginas[0] == "native"
    assert "Reduzida 4L" in got.paginas[1]
    assert got.status == "partial"
    assert got.diagnosticos[1]["status"] == "needs_review"
    assert got.diagnosticos[1]["regioes"][0]["bbox"] == [1, 2, 3, 4]
    assert got.texto_para_extracao() == "native\n\nApp"
    assert "Reduzida 4L" in got.markdown


def test_ocr_unavailable_is_partial_not_silent_success(monkeypatch):
    doc = pdf.DocumentoPdf(
        "App", ["App"], [], "pdfplumber", diagnosticos=[{"pagina": 1, "status": "needs_ocr"}]
    )
    monkeypatch.setattr(pdf, "_MOTORES", {"pdfplumber": lambda _: doc})
    monkeypatch.setattr(
        pdf,
        "_ocr_pagina",
        lambda *a, **kw: {"status": "dependency_unavailable", "reason": "missing local runtime"},
    )
    got = pdf.parse_pdf(b"%PDF test", motor="pdfplumber")
    assert got.status == "partial"
    assert got.diagnosticos[0]["status"] == "dependency_unavailable"
    assert got.avisos


def test_ocr_budget_leaves_pending_pages_visible(monkeypatch):
    doc = pdf.DocumentoPdf(
        "",
        ["", ""],
        [],
        "pdfplumber",
        diagnosticos=[{"pagina": n, "status": "needs_ocr"} for n in [1, 2]],
    )
    monkeypatch.setattr(pdf, "_MOTORES", {"pdfplumber": lambda _: doc})
    monkeypatch.setattr(
        pdf,
        "_ocr_pagina",
        lambda *a, **kw: {"status": "needs_review", "text": "OCR", "regions": []},
    )
    got = pdf.parse_pdf(b"%PDF test", motor="pdfplumber", max_paginas_ocr=1)
    assert got.diagnosticos[1]["status"] == "needs_ocr"
    assert got.status == "partial"


def test_forced_docling_requires_explicit_local_artifacts(monkeypatch):
    monkeypatch.delenv("PDF_DOCLING_ARTIFACTS_PATH", raising=False)
    with pytest.raises(pdf.PdfIlegivel, match="loca"):
        pdf._com_docling(b"%PDF test")


def test_ocr_configuration_rejects_missing_models_without_download(tmp_path):
    from pipeline.parse.pdf_ocr import modelos_locais

    with pytest.raises(FileNotFoundError):
        modelos_locais(tmp_path)


def test_ocr_worker_timeout_is_structured(monkeypatch):
    import subprocess

    from pipeline.parse import pdf_ocr

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("worker", 1)

    monkeypatch.setattr(pdf_ocr.subprocess, "run", timeout)
    monkeypatch.setattr(pdf_ocr, "disponibilidade", lambda: (True, ""))
    result = pdf_ocr.ocr_pagina(b"%PDF test", 4, timeout=1)
    assert result["status"] == "timeout"
    assert result["pagina"] == 4


def test_ocr_disabled_does_not_launch_worker(monkeypatch):
    monkeypatch.setenv("PDF_OCR_ENABLED", "0")
    monkeypatch.delenv("PDF_DOCLING_ARTIFACTS_PATH", raising=False)
    doc = pdf.DocumentoPdf(
        "", [""], [], "pdfplumber", diagnosticos=[{"pagina": 1, "status": "needs_ocr"}]
    )
    monkeypatch.setattr(pdf, "_MOTORES", {"pdfplumber": lambda _: doc})
    monkeypatch.setattr(pdf, "_ocr_pagina", lambda *a, **k: pytest.fail("must not run OCR"))
    got = pdf.parse_pdf(b"%PDF test", motor="pdfplumber")
    assert got.status == "partial"
    assert got.diagnosticos[0]["status"] == "needs_ocr"


def test_raster_table_ocr_requires_layout_not_false_completion(monkeypatch):
    monkeypatch.delenv("PDF_DOCLING_ARTIFACTS_PATH", raising=False)
    doc = pdf.DocumentoPdf(
        "",
        [""],
        [],
        "pdfplumber",
        diagnosticos=[{"pagina": 1, "status": "needs_ocr", "q_pdf": {"empty_tables": 2}}],
    )
    monkeypatch.setattr(pdf, "_MOTORES", {"pdfplumber": lambda _: doc})
    monkeypatch.setattr(
        pdf,
        "_ocr_pagina",
        lambda *a, **k: {"status": "needs_review", "text": "XLT Limited 2000 2300", "regions": []},
    )
    got = pdf.parse_pdf(b"%PDF test", motor="pdfplumber")
    assert got.diagnosticos[0]["status"] == "needs_layout"
    assert got.tabelas == []


def test_page_selection_preserves_original_page_number(monkeypatch):
    doc = pdf.DocumentoPdf(
        "",
        ["", ""],
        [],
        "pdfplumber",
        diagnosticos=[{"pagina": n, "status": "needs_ocr"} for n in [1, 2]],
    )
    monkeypatch.setattr(pdf, "_MOTORES", {"pdfplumber": lambda _: doc})
    calls = []

    def ocr(data, page, **kw):
        calls.append(page)
        return {"status": "needs_review", "text": "second", "regions": []}

    monkeypatch.setattr(pdf, "_ocr_pagina", ocr)
    got = pdf.parse_pdf(b"%PDF test", motor="pdfplumber", paginas_ocr=[2])
    assert calls == [2]
    assert got.paginas == ["", "second"]


def test_document_diagnostics_survive_json_roundtrip():
    import json
    from dataclasses import asdict

    doc = pdf.DocumentoPdf(
        "x",
        ["x"],
        [pdf.Tabela(1, [["x"]])],
        "pdfplumber",
        [{"pagina": 1, "status": "needs_review"}],
        "partial",
        ["pending"],
    )
    assert pdf.DocumentoPdf.from_dict(json.loads(json.dumps(asdict(doc)))) == doc


def test_real_digital_table_has_cell_geometry():
    from pathlib import Path

    pytest.importorskip("pdfplumber")
    source = (
        Path(__file__).resolve().parents[2] / "gabarito/raw/toyota_hilux_my26_ficha_oficial.pdf"
    )
    doc = pdf._com_pdfplumber(source.read_bytes())
    table = next(t for t in doc.tabelas if t.linha_de_cabecalho() is not None)
    assert table.bbox and table.celulas
    assert all(len(c["bbox"]) == 4 and c["pagina"] == table.pagina for c in table.celulas)
    assert any(c["column_header"] for c in table.celulas)


def test_missing_ocr_runtime_does_not_spawn(monkeypatch):
    from pipeline.parse import pdf_ocr

    monkeypatch.setattr(pdf_ocr, "disponibilidade", lambda: (False, "missing"))
    monkeypatch.setattr(pdf_ocr.subprocess, "run", lambda *a, **k: pytest.fail("must not spawn"))
    assert pdf_ocr.ocr_pagina(b"%PDF test", 1)["status"] == "dependency_unavailable"


def test_decorative_empty_grid_does_not_invalidate_useful_native_table():
    from pipeline.parse.pdf_quality import diagnosticar_pagina

    page = NS(bbox=(0, 0, 100, 100), chars=[{}] * 400, images=[])
    empty = NS(rows=[1, 2], columns=[1, 2], extract=lambda: [["", ""], ["", ""]])
    valid = NS(
        rows=[1, 2],
        columns=[1, 2],
        extract=lambda: [["Versão", "Limited"], ["Pneus", "255/65 R18"]],
    )
    got = diagnosticar_pagina(page, 1, "native table", [empty, valid])
    assert got["status"] == "complete"
    assert got["q_pdf"]["empty_tables"] == 1


def test_ocr_byte_limit_is_enforced_before_worker(monkeypatch):
    from pipeline.parse import pdf_ocr

    monkeypatch.setattr(pdf_ocr, "MAX_BYTES", 10)
    monkeypatch.setattr(pdf_ocr.subprocess, "run", lambda *a, **k: pytest.fail("must not spawn"))
    assert pdf_ocr.ocr_pagina(b"%PDF" + b"x" * 7, 1)["status"] == "resource_limit"


def test_zero_ocr_budget_does_not_launch_worker(monkeypatch):
    doc = pdf.DocumentoPdf(
        "", [""], [], "pdfplumber", diagnosticos=[{"pagina": 1, "status": "needs_ocr"}]
    )
    monkeypatch.setattr(pdf, "_MOTORES", {"pdfplumber": lambda _: doc})
    monkeypatch.setattr(pdf, "_ocr_pagina", lambda *a, **k: pytest.fail("must not run OCR"))
    assert pdf.parse_pdf(b"%PDF test", motor="pdfplumber", orcamento_ocr=0).status == "partial"


def test_pending_docling_grade_does_not_bypass_text_filter():
    native = pdf.Tabela(1, [["Versão", "Limited"], ["Torque", "600 Nm"]], motor="pdfplumber")
    generated = pdf.Tabela(1, [["Versão", "Limited"], ["Peso", "2357 kg"]], motor="docling")
    doc = pdf.DocumentoPdf(
        "2357 kg",
        ["2357 kg"],
        [generated],
        "docling",
        diagnosticos=[
            {
                "pagina": 1,
                "motor": "docling",
                "status": "needs_review",
                "native_text": "600 Nm",
                "native_tables": [native.to_dict()],
                "layout_text": "2357 kg",
            }
        ],
    )
    assert doc.texto_para_extracao() == "600 Nm"
    assert doc.tabelas_para_extracao() == [native]
    assert doc.tabelas == [generated]


def test_legacy_markdown_contract_remains_unchanged():
    doc = pdf.DocumentoPdf("original markdown", ["different page representation"])
    assert doc.texto_para_extracao() == "original markdown"


def test_known_ocr_without_native_artifact_fails_closed():
    doc = pdf.DocumentoPdf(
        "invented year 2027",
        ["invented year 2027"],
        diagnosticos=[{"pagina": 1, "motor": "pdfplumber+rapidocr", "status": "needs_review"}],
    )
    assert doc.texto_para_extracao() == ""
