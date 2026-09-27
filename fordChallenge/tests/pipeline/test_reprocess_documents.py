"""Offline, integrity and incremental-page contracts for preserved originals."""

import hashlib
import io
import json
import socket
import subprocess
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.parse.pdf import DocumentoPdf, Tabela
from pipeline.research import reprocess
from pipeline.research.run import Fonte
from scripts.reprocess_research_documents import reprocessar_checkpoint


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def fonte(tmp_path):
    raw = tmp_path / "original.pdf"
    raw.write_bytes(b"%PDF-1.7\nfixture parser mocked\n")
    return Fonte(
        "https://www.vw.com.br/manual.pdf",
        1,
        "oficial",
        "Amarok 2026",
        texto="texto legado",
        sha256=sha(b"texto legado"),
        raw_path=str(raw),
        sha256_binario=sha(raw.read_bytes()),
        captured_at="2026-09-14T00:00:00Z",
        e_pdf=True,
        tipo="pdf_oficial",
        http_status=200,
    )


def document(pages=None, diagnostics=None):
    pages = pages or ["Ford Ranger Limited 2027 — texto digital"]
    return DocumentoPdf(
        "\n\n".join(pages),
        pages,
        [],
        "pdfplumber",
        diagnosticos=diagnostics
        or [{"pagina": n, "status": "complete"} for n in range(1, len(pages) + 1)],
    )


def test_success_copy_preserves_original_metadata(fonte, monkeypatch):
    original = asdict(fonte)
    raw_bytes = Path(fonte.raw_path).read_bytes()
    monkeypatch.setattr(reprocess, "_executar", lambda *args: asdict(document()))
    result = reprocess.reprocessar_fonte(fonte)
    assert result is not fonte and asdict(fonte) == original
    assert Path(fonte.raw_path).read_bytes() == raw_bytes
    assert result.fetch_ok and result.baixada and result.parse_status == "complete"
    assert result.sha256 == sha(result.texto.encode())
    for name in ["url", "tier", "motivo", "consulta", "raw_path", "captured_at", "tipo"]:
        assert getattr(result, name) == getattr(fonte, name)


@pytest.mark.parametrize(
    "kind,status",
    [
        ("hash", "hash_mismatch"),
        ("signature", "invalid_signature"),
        ("missing", "missing_original"),
        ("empty_path", "missing_original"),
    ],
)
def test_integrity_failure_never_calls_parser(fonte, monkeypatch, kind, status):
    if kind == "hash":
        fonte.sha256_binario = "a" * 64
    elif kind == "signature":
        Path(fonte.raw_path).write_bytes(b"<html>not a PDF</html>")
    elif kind == "missing":
        fonte.raw_path += ".missing"
    else:
        fonte.raw_path = ""
    monkeypatch.setattr(reprocess, "_executar", lambda *args: pytest.fail("parser called"))
    original = asdict(fonte)
    result = reprocess.reprocessar_fonte(fonte)
    assert result.parse_status == status
    assert not result.fetch_ok and not result.baixada and result.texto == ""
    assert result.documento_pdf is None and asdict(fonte) == original


def test_missing_legacy_binary_hash_is_computed(fonte, monkeypatch):
    fonte.sha256_binario = ""
    monkeypatch.setattr(reprocess, "_executar", lambda *args: asdict(document()))
    result = reprocess.reprocessar_fonte(fonte)
    assert result.sha256_binario == sha(Path(fonte.raw_path).read_bytes())


@pytest.mark.parametrize(
    "error,status",
    [
        (subprocess.TimeoutExpired("worker", 1), "timeout"),
        (ValueError("bad json"), "failed"),
        (OSError("not available"), "failed"),
    ],
)
def test_worker_failure_keeps_verified_fetch_but_no_stale_text(fonte, monkeypatch, error, status):
    def fail(*args):
        raise error

    monkeypatch.setattr(reprocess, "_executar", fail)
    result = reprocess.reprocessar_fonte(fonte)
    assert result.parse_status == status and result.fetch_ok
    assert result.texto == "" and not result.baixada
    assert fonte.texto == "texto legado"


@pytest.mark.parametrize("pages", [[0], [-1], [True], ["2"]])
def test_invalid_page_flags_fail_early(fonte, pages):
    with pytest.raises(ValueError):
        reprocess.reprocessar_fonte(fonte, paginas=pages)


def test_out_of_range_page_is_error_not_complete(fonte, monkeypatch):
    monkeypatch.setattr(reprocess, "_executar", lambda *args: asdict(document()))
    result = reprocess.reprocessar_fonte(fonte, paginas=[2])
    assert result.parse_status == "invalid_pages" and result.fetch_ok


def test_pending_ocr_saved_but_not_sent_to_extraction(fonte, monkeypatch):
    doc = document(
        ["Digital original\nOCR inventado 500 cv"],
        [
            {
                "pagina": 1,
                "status": "needs_review",
                "native_text": "Digital original",
                "ocr_text": "OCR inventado 500 cv",
                "ocr": {"motor": "rapidocr"},
            }
        ],
    )
    doc.status = "partial"
    monkeypatch.setattr(reprocess, "_executar", lambda *args: asdict(doc))
    result = reprocess.reprocessar_fonte(fonte)
    assert result.texto == "Digital original"
    assert "500 cv" in result.documento_pdf.markdown
    assert result.parse_status == "partial"


def test_resume_after_serialization_keeps_unselected_page_and_native_tables(fonte, monkeypatch):
    old = document(
        ["Página um trabalhada", "Digital dois"],
        [
            {"pagina": 1, "status": "complete", "regioes": [{"text": "um"}]},
            {"pagina": 2, "status": "needs_ocr", "native_text": "Digital dois"},
        ],
    )
    old.status = "partial"
    old.tabelas = [Tabela(1, [["Original"]])]
    fonte.documento_pdf = old
    fonte.texto = old.texto_para_extracao()
    fonte.sha256 = sha(fonte.texto.encode())
    fonte = Fonte(**json.loads(json.dumps(asdict(fonte))))
    calls = []

    def parse(data, pages, timeout):
        calls.append(pages)
        return asdict(document(["Digital um relido", "Página dois nova"]))

    monkeypatch.setattr(reprocess, "_executar", parse)
    result = reprocess.reprocessar_fonte(fonte)
    assert calls == [[2]]
    assert result.documento_pdf.paginas == ["Página um trabalhada", "Página dois nova"]
    assert result.documento_pdf.tabelas[0].linhas == [["Original"]]
    assert result.documento_pdf.diagnosticos[0]["regioes"] == [{"text": "um"}]


def test_explicit_pages_sorted_unique_and_empty_means_no_ocr(fonte, monkeypatch):
    calls = []

    def parse(data, pages, timeout):
        calls.append(pages)
        return asdict(document(["one", "two", "three"]))

    monkeypatch.setattr(reprocess, "_executar", parse)
    reprocess.reprocessar_fonte(fonte, paginas=[3, 1, 3])
    reprocess.reprocessar_fonte(fonte, paginas=[])
    assert calls == [[1, 3], []]


def test_report_is_new_and_original_bytes_unchanged(fonte, monkeypatch, tmp_path):
    monkeypatch.setattr(reprocess, "_executar", lambda *args: asdict(document()))
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps({"policy": "quality-test", "target": {"ano": 2026}, "fontes": [asdict(fonte)]}),
        encoding="utf-8",
    )
    original = checkpoint.read_bytes()
    raw_original = Path(fonte.raw_path).read_bytes()
    output = tmp_path / "report.json"
    result = reprocessar_checkpoint(checkpoint, output)
    assert result["status"] == "complete" and result["coverage_gain"] is None
    assert result["policy"] == "quality-test" and result["target"] == {"ano": 2026}
    assert result["llm_calls"] == result["network_calls"] == result["database_writes"] == 0
    assert checkpoint.read_bytes() == original
    assert Path(fonte.raw_path).read_bytes() == raw_original
    text = Path(result["documentos"][0]["text_path"]).read_bytes()
    assert sha(text) == result["documentos"][0]["sha256_texto"]
    resumed = reprocessar_checkpoint(output, tmp_path / "report-next.json", paginas=[1])
    assert resumed["status"] == "complete"
    with pytest.raises(FileExistsError):
        reprocessar_checkpoint(checkpoint, output)


@pytest.mark.parametrize("target", ["checkpoint", "raw"])
def test_report_cannot_overwrite_original(fonte, tmp_path, target):
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps({"fontes": [asdict(fonte)]}), encoding="utf-8")
    output = checkpoint if target == "checkpoint" else Path(fonte.raw_path)
    before = output.read_bytes()
    with pytest.raises(ValueError):
        reprocessar_checkpoint(checkpoint, output)
    assert output.read_bytes() == before


def test_real_local_parser_worker(tmp_path, monkeypatch):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    path = tmp_path / "blank.pdf"
    writer.write(path)
    monkeypatch.setenv("PDF_OCR_ENABLED", "0")
    monkeypatch.setenv("PDF_MOTOR", "pdfplumber")
    fonte = Fonte("https://example.com/blank.pdf", 1, "test", "", raw_path=str(path))
    result = reprocess.reprocessar_fonte(fonte, paginas=[], timeout=30)
    assert result.fetch_ok and result.documento_pdf.schema_version == 2
    assert result.parse_status in {"complete", "partial"}


def test_real_corrupt_pdf_fails_explicitly(fonte, monkeypatch):
    monkeypatch.setenv("PDF_OCR_ENABLED", "0")
    result = reprocess.reprocessar_fonte(fonte, timeout=20)
    assert result.fetch_ok and result.parse_status == "failed"
    assert not result.texto and result.documento_pdf is None


def test_worker_blocks_network_and_passes_page_flags(monkeypatch, capsys):
    from pipeline.parse import pdf

    for name in [
        "create_connection",
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "gethostbyaddr",
    ]:
        monkeypatch.setattr(socket, name, getattr(socket, name))
    for name in ["connect", "connect_ex"]:
        monkeypatch.setattr(socket.socket, name, getattr(socket.socket, name))
    monkeypatch.setattr(
        reprocess.sys,
        "argv",
        ["worker", "--worker", "--selected-pages", "--page", "2", "--page", "2"],
    )
    monkeypatch.setattr(reprocess.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"%PDF-1.7")))

    def parse(data, **kwargs):
        assert data == b"%PDF-1.7" and kwargs["paginas_ocr"] == [2]
        with pytest.raises(RuntimeError, match="rede desabilitada"):
            socket.create_connection(("example.com", 443))
        with pytest.raises(RuntimeError, match="rede desabilitada"):
            socket.getaddrinfo("example.com", 443)
        return document()

    monkeypatch.setattr(pdf, "parse_pdf", parse)
    reprocess._worker()
    assert json.loads(capsys.readouterr().out)["schema_version"] == 2


def test_executor_timeout_kills_worker_tree(monkeypatch):
    calls = []
    process = SimpleNamespace(pid=12345)

    def communicate(**kwargs):
        raise subprocess.TimeoutExpired("fixed worker", 0.01)

    process.communicate = communicate

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return process

    terminated = []
    monkeypatch.setattr(reprocess.subprocess, "Popen", popen)
    monkeypatch.setattr(reprocess, "_encerrar", lambda p: terminated.append(p.pid))
    with pytest.raises(subprocess.TimeoutExpired):
        reprocess._executar(b"%PDF-1.7", [], 0.01)
    assert terminated == [12345]
    assert calls[0][0][-1] == "--selected-pages"
    assert calls[0][1]["env"]["HF_HUB_OFFLINE"] == "1"
    assert calls[0][1]["stdin"] == subprocess.PIPE


def test_unc_path_is_rejected_before_read(monkeypatch, fonte):
    fonte.raw_path = "\\\\server\\share\\original.pdf"
    monkeypatch.setattr(Path, "is_file", lambda self: pytest.fail("network file read"))
    result = reprocess.reprocessar_fonte(fonte)
    assert result.parse_status == "missing_original" and not result.fetch_ok


def test_unc_checkpoint_is_rejected_before_resolve(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "resolve", lambda self: pytest.fail("UNC resolution"))
    with pytest.raises(ValueError, match="caminhos locais"):
        reprocessar_checkpoint(Path("\\\\server\\share\\checkpoint.json"), tmp_path / "out.json")
