"""Independent regression cases for the reader/checkpoint integration review."""

from dataclasses import replace

import pytest

from pipeline import llm
from pipeline.extract import run as extract
from pipeline.research import gaps, run
from pipeline.research.events import Trilha
from pipeline.research.planner import Alvo


@pytest.fixture
def completed_reader(monkeypatch):
    monkeypatch.setenv("LLM_FAKE", "1")
    monkeypatch.setattr(extract, "_do_fastpath", lambda *a, **k: [])
    text = "Ford Ranger Limited 2027 Brasil\nPaddle shifters: disponível."
    monkeypatch.setattr(extract, "dividir_em_blocos", lambda *a, **k: [text])
    calls = []

    def model(doc, campos, **kwargs):
        calls.append(doc.texto)
        candidate = extract.Candidato(
            campo="paddle_shifters",
            valor=True,
            quote="Paddle shifters: disponível.",
            origem="llm:test",
            source_id=doc.source_id,
            source_text=doc.texto,
            url=doc.url,
            tier=doc.tier,
            captured_at=doc.captured_at,
        )
        return [candidate], llm.Uso(modelo="test"), "", True

    monkeypatch.setattr(extract, "_do_llm", model)
    reader = run.Leitor(Alvo("Ford", "Ranger", "Limited", 2027), gaps.Orcamento(), Trilha())
    reader.fipe_somente_snapshots = True
    doc = extract.Documento(
        text,
        source_id="official",
        tier=1,
        url="https://www.ford.com.br/ranger/limited-2027/",
        captured_at="2026-09-14T00:00:00Z",
    )
    reader.ler([doc], campos=["paddle_shifters"])
    assert reader.candidatos[doc.source_id] and len(calls) == 1
    return reader, doc, calls


@pytest.mark.parametrize("change", [{"tier": 2}, {"captured_at": "2026-09-15T00:00:00Z"}])
def test_metadata_change_does_not_erase_completed_candidates(completed_reader, change):
    reader, doc, _calls = completed_reader
    updated = replace(doc, **change)
    reader.ler([updated], campos=["paddle_shifters"])
    assert reader.candidatos[doc.source_id], "metadata-only change erased completed LLM candidates"
    assert all(
        c.tier == updated.tier and c.captured_at == updated.captured_at
        for c in reader.candidatos[doc.source_id]
    )


def test_switching_fixture_to_real_reaches_new_extractor_context(completed_reader, monkeypatch):
    reader, doc, calls = completed_reader
    monkeypatch.setenv("LLM_FAKE", "0")
    reader.ler([doc], campos=["paddle_shifters"])
    assert len(calls) == 2, "reader shortcut hid the extractor's real-provider context"


def test_changed_system_prompt_reaches_new_extractor_context(completed_reader, monkeypatch):
    reader, doc, calls = completed_reader
    monkeypatch.setattr(extract.prompt, "SISTEMA", extract.prompt.SISTEMA + "\nRegra nova.")
    reader.ler([doc], campos=["paddle_shifters"])
    assert len(calls) == 2, "reader shortcut hid the extractor's new prompt context"


def test_fixture_candidates_do_not_survive_empty_real_response(completed_reader, monkeypatch):
    reader, doc, _calls = completed_reader
    monkeypatch.setenv("LLM_FAKE", "0")
    monkeypatch.setattr(extract, "_do_llm", lambda *a, **k: ([], llm.Uso(modelo="test"), "", True))
    reader.ler([doc], campos=["paddle_shifters"])
    assert reader.candidatos[doc.source_id] == []


def test_source_invalidation_preserves_other_document_context(completed_reader):
    reader, doc, _calls = completed_reader
    context_key, context = next(iter(reader.estado_leitura.contextos.items()))
    import copy

    other = copy.deepcopy(context)
    other["identidade"]["source_id"] = "another-source"
    from pipeline.research.reading_state import digest

    other_key = digest(other["identidade"])
    reader.estado_leitura.contextos[other_key] = other
    reader.estado_leitura.invalidar_fonte(doc.source_id)
    assert context_key not in reader.estado_leitura.contextos
    assert reader.estado_leitura.contextos[other_key] == other


def test_preserved_unparsed_pdf_is_eligible_for_resume(monkeypatch):
    from pipeline.parse.pdf import DocumentoPdf

    source = run.Fonte(
        "https://www.ford.com.br/manual.pdf",
        1,
        "oficial",
        "q",
        raw_path="preserved.pdf",
        e_pdf=True,
        parse_status="not_parsed",
    )
    reader = run.Leitor(Alvo("Ford", "Ranger", "Limited", 2027), gaps.Orcamento(), Trilha())
    calls = []

    def parse(fonte, **kwargs):
        calls.append(fonte.url)
        return replace(fonte, documento_pdf=DocumentoPdf("digital"), texto="digital")

    monkeypatch.setattr("pipeline.research.reprocess.reprocessar_fonte", parse)
    assert run._retomar_pdfs([source], reader)
    assert calls == [source.url]


def test_legacy_html_source_is_not_reprocessed_as_pdf(tmp_path, monkeypatch):
    raw = tmp_path / "original.html"
    raw.write_text("<html>Ford Ranger Limited 2027 Brasil</html>", encoding="utf-8")
    source = run.Fonte(
        "https://www.ford.com.br/ranger/",
        1,
        "oficial",
        "q",
        texto="Ford Ranger Limited 2027 Brasil",
        baixada=True,
        raw_path=str(raw),
        parse_status="",
        e_pdf=False,
    )
    reader = run.Leitor(Alvo("Ford", "Ranger", "Limited", 2027), gaps.Orcamento(), Trilha())
    reader.textos[source.source_id] = source.texto
    monkeypatch.setattr(
        "pipeline.research.reprocess.reprocessar_fonte",
        lambda *a, **k: pytest.fail("HTML entered PDF reprocessor"),
    )
    assert not run._retomar_pdfs([source], reader)
    assert reader.textos[source.source_id] == source.texto
