"""O leitor continua blocos, preserva candidatos e grava progresso com o checkpoint."""

import json

import pytest

from pipeline import llm
from pipeline.extract import run as extract
from pipeline.research import checkpoint, gaps, run
from pipeline.research.events import Trilha
from pipeline.research.planner import Alvo
from pipeline.research.reading_state import EstadoLeitura
from pipeline.schema import empty_spec


@pytest.fixture
def reading(monkeypatch):
    monkeypatch.setenv("LLM_FAKE", "1")
    monkeypatch.setattr(extract, "MAX_CHARS_POR_BLOCO", 160)
    blocks = [
        "Ford Ranger Limited 2027 Brasil\nPaddle shifters: disponível.\n",
        "Ford Ranger Limited 2027 Brasil\nPaddle shifters: informação complementar.\n",
    ]
    monkeypatch.setattr(extract, "dividir_em_blocos", lambda *a, **k: blocks)
    monkeypatch.setattr(extract, "_do_fastpath", lambda *a, **k: [])
    calls = []

    def model(doc, campos, **kw):
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
        return ([candidate] if len(calls) == 1 else []), llm.Uso(modelo="test"), "", True

    monkeypatch.setattr(extract, "_do_llm", model)
    target = Alvo("Ford", "Ranger", "Limited", 2027)
    reader = run.Leitor(target, gaps.Orcamento(chamadas_llm=4), Trilha())
    reader.fipe_somente_snapshots = True
    doc = extract.Documento(
        "\n".join(blocks),
        source_id="official",
        url="https://www.ford.com.br/ranger/limited-2027/",
        tier=1,
        captured_at="2026-09-15",
    )
    return reader, doc, calls


def test_second_read_visits_next_block_without_losing_candidates(reading):
    reader, doc, calls = reading
    reader.ler([doc], campos=["paddle_shifters"])
    first = list(reader.candidatos[doc.source_id])
    assert first
    reader.ler([doc], campos=["paddle_shifters"])
    reader.ler([doc], campos=["paddle_shifters"])
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert reader.candidatos[doc.source_id] == first


def test_checkpoint_restores_block_frontier_with_candidates(reading, tmp_path):
    reader, doc, calls = reading
    reader.ler([doc], campos=["paddle_shifters"])
    file = tmp_path / "checkpoint.json"
    checkpoint.save(str(file), reader.alvo, [], reader, empty_spec(), set())
    saved = json.loads(file.read_text(encoding="utf-8"))
    restored = run.Leitor(reader.alvo, gaps.Orcamento(), Trilha())
    restored.fipe_somente_snapshots = True
    restored.estado_leitura = EstadoLeitura.from_dict(saved["estado_leitura"])
    restored.leituras = saved["leituras"]
    restored.candidatos = {
        key: [extract.Candidato(**candidate) for candidate in candidates]
        for key, candidates in saved["candidatos"].items()
    }
    restored.textos = saved["textos"]
    restored.ler([doc], campos=["paddle_shifters"])
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert len(restored.candidatos[doc.source_id]) == 1


def test_changed_document_does_not_keep_stale_candidates(reading):
    reader, doc, calls = reading
    reader.ler([doc], campos=["paddle_shifters"])
    assert reader.candidatos[doc.source_id]
    doc.texto = doc.texto.replace("disponível", "indeterminado")
    reader.ler([doc], campos=["paddle_shifters"])
    assert len(calls) == 2
    assert not reader.candidatos[doc.source_id]
