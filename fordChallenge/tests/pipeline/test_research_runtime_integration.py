"""Custos sobrevivem à retomada; documentos locais não exigem nova busca."""

import json
from dataclasses import replace

from pipeline.parse.pdf import DocumentoPdf
from pipeline.research import checkpoint, gaps, planner, run, service_budget
from pipeline.research.events import Trilha
from pipeline.schema import empty_spec


def test_service_reservation_is_saved_before_request_and_restored(tmp_path, monkeypatch):
    path = str(tmp_path / "run.json")
    monkeypatch.setenv("RESEARCH_SERVICES_MAX_CALLS", "1")
    monkeypatch.setenv("RESEARCH_SERVICES_MAX_USD", "0.008")
    monkeypatch.setattr("pipeline.research.acervo.known_sources", lambda _: [])
    monkeypatch.setattr(planner, "primeira_rodada", lambda _: [planner.Consulta("q", 1, "teste")])
    monkeypatch.setattr(planner, "consultas_de_lacuna", lambda *a, **k: [])
    calls = []

    def search(*a, **kw):
        active = service_budget.current_budget()
        active.reserve("tavily", "search", 0.008)
        saved = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
        assert saved["services_budget"]["calls"] == 1
        calls.append(active)
        return run.busca.Resposta("q", "tavily")

    monkeypatch.setattr(run.busca, "buscar", search)
    result = run.pesquisar(
        "Ford",
        "Ranger",
        "Limited",
        ano=2027,
        campos=["paddle_shifters"],
        checkpoint_path=path,
        orcamento=gaps.Orcamento(rodadas=1, chamadas_llm=0),
    )
    assert result.servicos["calls"] == 1
    assert result.to_dict()["servicos"]["accounted_usd"] == 0.008
    assert service_budget.current_budget() is None
    resumed = run.pesquisar(
        "Ford",
        "Ranger",
        "Limited",
        ano=2027,
        campos=["paddle_shifters"],
        checkpoint_path=path,
        orcamento=gaps.Orcamento(rodadas=1, chamadas_llm=0),
    )
    assert resumed.servicos == result.servicos
    assert len(calls) == 1


def test_legacy_pdf_reprocessed_once_but_review_pending_not_repeated(monkeypatch):
    target = planner.Alvo("Ford", "Ranger", "Limited", 2027)
    reader = run.Leitor(target, gaps.Orcamento(chamadas_llm=0), Trilha())
    source = run.Fonte(
        "https://ford.com.br/ficha.pdf",
        1,
        "oficial",
        "q",
        texto="anterior",
        baixada=True,
        raw_path="original.pdf",
        documento_pdf=DocumentoPdf(
            motor="pdfplumber",
            markdown="anterior",
            tabelas=[],
            paginas=["anterior"],
            schema_version=1,
        ),
    )
    reader.textos[source.source_id] = "anterior"
    reader.leituras[source.source_id] = {"pendentes": 1}
    updated = replace(
        source,
        texto="novo",
        parse_status="partial",
        documento_pdf=DocumentoPdf(
            motor="pdfplumber", markdown="novo", tabelas=[], paginas=["novo"], status="partial"
        ),
    )
    calls = []

    def reprocess(fonte, **kw):
        calls.append(fonte)
        return updated

    monkeypatch.setattr("pipeline.research.reprocess.reprocessar_fonte", reprocess)
    sources = [source]
    assert run._retomar_pdfs(sources, reader)
    assert sources == [updated]
    assert source.source_id not in reader.leituras
    assert not run._retomar_pdfs(sources, reader)
    assert len(calls) == 1


def test_exhausted_budget_does_not_reparse_legacy_pdf(monkeypatch):
    reader = run.Leitor(planner.Alvo("Ford", "Ranger"), gaps.Orcamento(segundos=0), Trilha())
    source = run.Fonte("https://ford.com.br/ficha.pdf", 1, "oficial", "q", raw_path="x.pdf")
    monkeypatch.setattr(
        "pipeline.research.reprocess.reprocessar_fonte",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("fora do prazo")),
    )
    assert not run._retomar_pdfs([source], reader)


def test_legacy_checkpoint_default_parser_schema_is_not_upgraded_implicitly(tmp_path, monkeypatch):
    reader = run.Leitor(
        planner.Alvo("Ford", "Ranger", "Limited", 2027), gaps.Orcamento(rodadas=0), Trilha()
    )
    source = run.Fonte(
        "https://ford.com.br/ficha.pdf",
        1,
        "oficial",
        "q",
        documento_pdf=DocumentoPdf(
            motor="pdfplumber", markdown="texto", tabelas=[], paginas=["texto"]
        ),
    )
    path = str(tmp_path / "legacy.json")
    checkpoint.save(path, reader.alvo, [source], reader, empty_spec(), set())
    payload = json.loads((tmp_path / "legacy.json").read_text(encoding="utf-8"))
    del payload["fontes"][0]["documento_pdf"]["schema_version"]
    (tmp_path / "legacy.json").write_text(json.dumps(payload), encoding="utf-8")
    result = run.pesquisar(
        "Ford",
        "Ranger",
        "Limited",
        ano=2027,
        campos=["paddle_shifters"],
        orcamento=gaps.Orcamento(rodadas=0),
        checkpoint_path=path,
    )
    assert result.fontes[0].documento_pdf.schema_version == 1
