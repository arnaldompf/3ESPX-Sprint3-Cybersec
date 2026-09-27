"""Leitura retomável não confunde documento, configuração, lacunas ou falha."""

import json

import pytest

from pipeline import llm
from pipeline.extract import run
from pipeline.research.reading_state import EstadoLeitura


@pytest.fixture
def model(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "MAX_CHARS_POR_BLOCO", 90)
    monkeypatch.setattr(llm, "modelo_pequeno", lambda: "fake-small")
    monkeypatch.setattr(llm, "modelo_grande", lambda: "fake-large")

    def responder(**kwargs):
        calls.append(kwargs)
        return llm.RespostaLLM(dados={}, uso=llm.Uso(modelo=kwargs["modelo"]), ok=True)

    monkeypatch.setattr(llm, "extrair_json", responder)
    return calls


def document():
    return run.Documento(
        texto="\n\n".join(
            [
                "Menu " + "x" * 70,
                "Suspensão dianteira: informação incompleta " + "y" * 35,
                "Fim " + "z" * 70,
            ]
        ),
        source_id="manual",
        url="https://example.test/manual",
    )


def extract(state, doc=None, **kwargs):
    defaults = {
        "marca": "Ford",
        "modelo_veiculo": "Ranger",
        "versao": "Limited",
        "escalonar": False,
        "max_blocos": 1,
        "estado_leitura": state,
        "policy_version": "test-policy",
        "parser_version": "test-parser",
        "documento_sha256": "a" * 64,
    }
    defaults.update(kwargs)
    return run.extrair_documento(doc or document(), {"amortecedores"}, **defaults)


def test_resume_after_serialization_without_repeating(model):
    state = EstadoLeitura()
    first = extract(state)
    resumed = EstadoLeitura.from_dict(json.loads(json.dumps(state.to_dict())))
    second = extract(resumed)
    third = extract(resumed)
    fourth = extract(resumed)
    assert len(model) == 3
    assert len({c["prompt"] for c in model}) == 3
    assert first.leitura["pendentes"] == 2
    assert second.leitura["pendentes"] == 1
    assert third.leitura["pendentes"] == 0
    assert fourth.leitura["usados"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"versao": "XLT"},
        {"policy_version": "test-policy2"},
        {"parser_version": "parser2"},
        {"documento_sha256": "b" * 64},
        {"configuracao_alvo": {"mercado": "AR"}},
    ],
)
def test_changed_context_does_not_inherit_completion(model, change):
    state = EstadoLeitura()
    original = extract(state)
    changed = extract(state, **change)
    assert len(model) == 2
    assert original.leitura["contexto_id"] != changed.leitura["contexto_id"]


def test_same_claimed_digest_different_actual_text_invalidates(model):
    state = EstadoLeitura()
    original = extract(state)
    doc = document()
    doc.texto += "\nDocumento corrigido"
    changed = extract(state, doc)
    assert original.leitura["contexto_id"] != changed.leitura["contexto_id"]


def test_success_with_no_claim_still_completes_block(model):
    state = EstadoLeitura()
    result = extract(state)
    assert not result.candidatos
    assert len(result.leitura["concluidos_nesta_chamada"]) == 1


@pytest.mark.parametrize("failure", ["provider", "provider_exception", "timeout"])
def test_failed_block_is_retryable_and_success_is_not_repeated(model, monkeypatch, failure):
    state = EstadoLeitura()
    first = extract(state)
    good = llm.extrair_json

    def broken(**kwargs):
        if failure == "timeout":
            raise TimeoutError("prazo esgotado")
        if failure == "provider_exception":
            raise llm.SemProvedor("sem chave")
        return llm.RespostaLLM(ok=False, motivo="sem chave")

    monkeypatch.setattr(llm, "extrair_json", broken)
    failed = extract(state)
    assert failed.leitura["concluidos"] == first.leitura["concluidos"]
    assert failed.leitura["falhas"]
    monkeypatch.setattr(llm, "extrair_json", good)
    retried = extract(state)
    assert retried.leitura["usados"] == failed.leitura["usados"]
    assert retried.leitura["usados"] != first.leitura["usados"]


def test_disabled_llm_does_not_consume_pending(model):
    state = EstadoLeitura()
    result = extract(state, permitir_llm=False)
    assert not model
    assert not result.leitura["concluidos"]
    assert result.leitura["pendentes"] == 3


def test_different_fields_get_independent_context(model):
    state = EstadoLeitura()
    first = run.extrair_documento(
        document(), {"amortecedores"}, estado_leitura=state, max_blocos=1, escalonar=False
    )
    other = run.extrair_documento(
        document(), {"camera_360"}, estado_leitura=state, max_blocos=1, escalonar=False
    )
    assert first.leitura["contexto_id"] != other.leitura["contexto_id"]
    assert len(model) == 2


def test_nested_target_configuration_survives_json(model):
    state = EstadoLeitura()
    config = {"mercado": "BR", "evidencias": ("index-a",), "pacote_opcional": ""}
    first = extract(state, configuracao_alvo=config)
    restored = EstadoLeitura.from_dict(json.loads(json.dumps(state.to_dict())))
    second = extract(restored, configuracao_alvo=config)
    assert second.leitura["contexto_id"] == first.leitura["contexto_id"]
    assert second.leitura["usados"] != first.leitura["usados"]


def test_document_defaults_carry_original_hash_and_parser(model):
    state = EstadoLeitura()
    doc = document()
    doc.sha256_original = "c" * 64
    doc.parser_version = "pdf-schema2-pdfplumber"
    first = run.extrair_documento(
        doc, {"amortecedores"}, estado_leitura=state, max_blocos=1, escalonar=False
    )
    saved = state.contextos[first.leitura["contexto_id"]]["identidade"]
    assert saved["sha256_original"] == "c" * 64
    assert saved["parser"] == "pdf-schema2-pdfplumber"


def test_relevance_is_applied_before_budget(model):
    state = EstadoLeitura()
    doc = document()
    doc.texto += "\n\nAmortecedores: descrição indisponível nesta seção"
    extract(state, doc)
    assert "Amortecedores: descrição" in model[0]["prompt"]
    assert "Menu " not in model[0]["prompt"]


def test_zero_budget_keeps_all_pending(model):
    result = extract(EstadoLeitura(), max_blocos=0)
    assert result.leitura["pendentes"] == 3
    assert not model


def test_all_requested_fields_stay_in_each_block(model, monkeypatch):
    calls = []

    def responder(**kwargs):
        calls.append(kwargs)
        return llm.RespostaLLM(
            ok=True, dados={"amortecedores": {"value": "passivos", "evidence_quote": "passivos"}}
        )

    monkeypatch.setattr(llm, "extrair_json", responder)
    result = extract(EstadoLeitura(), max_blocos=2)
    assert len(calls) == 2
    assert calls[0]["campos"] == calls[1]["campos"] == ["amortecedores"]
    assert len(result.candidatos) == 2


def test_fastpath_reads_entire_document_even_with_one_llm_block(model):
    doc = document()
    doc.texto += "\n\nTanque de combustível: 80 litros"
    result = run.extrair_documento(
        doc,
        {"tanque_l", "amortecedores"},
        estado_leitura=EstadoLeitura(),
        max_blocos=1,
        escalonar=False,
    )
    assert any(c.campo == "tanque_l" and c.valor == 80 for c in result.candidatos)
    assert model[0]["campos"] == ["amortecedores"]


def test_call_budget_counts_escalation_and_resume_large_pass(model):
    state = EstadoLeitura()
    doc = run.Documento(texto="Especificação sem números", source_id="small")
    first = extract(state, doc, escalonar=True)
    assert len(model) == 1
    assert first.leitura["pendentes"] == 1
    second = extract(state, doc, escalonar=True)
    assert len(model) == 2
    assert model[-1]["modelo"] == "fake-large"
    assert second.leitura["pendentes"] == 0


def test_deserialization_rejects_forged_context_key(model):
    state = EstadoLeitura()
    extract(state)
    payload = state.to_dict()
    value = next(iter(payload["contextos"].values()))
    payload["contextos"] = {"0" * 64: value}
    with pytest.raises(ValueError):
        EstadoLeitura.from_dict(payload)


def test_fixture_success_does_not_skip_real_provider_read(model, monkeypatch):
    state = EstadoLeitura()
    monkeypatch.setenv("LLM_FAKE", "1")
    first = extract(state)
    monkeypatch.setenv("LLM_FAKE", "0")
    second = extract(state)
    assert first.leitura["contexto_id"] != second.leitura["contexto_id"]
    assert len(model) == 2


def test_repeated_equal_blocks_have_distinct_positions(model):
    state = EstadoLeitura()
    text = "Amortecedor " + "w" * 70
    doc = run.Documento(texto="\n\n".join([text, text]), source_id="duplicate")
    result = extract(state, doc, max_blocos=2)
    assert len(result.leitura["usados"]) == len(set(result.leitura["usados"])) == 2
    assert result.leitura["pendentes"] == 0


def test_provider_message_is_not_saved_in_state(model, monkeypatch):
    state = EstadoLeitura()
    secret = "fixture-private-token-never-log"
    monkeypatch.setattr(llm, "extrair_json", lambda **kw: llm.RespostaLLM(ok=False, motivo=secret))
    result = extract(state)
    assert result.leitura["falhas"][0]["motivo"] == "provider_failure"
    assert secret not in json.dumps(state.to_dict())
    assert secret not in " ".join(result.avisos)


def test_model_change_invalidates_completed_pass(model, monkeypatch):
    state = EstadoLeitura()
    first = extract(state)
    monkeypatch.setattr(llm, "modelo_pequeno", lambda: "other-model")
    second = extract(state)
    assert first.leitura["contexto_id"] != second.leitura["contexto_id"]


def test_deserialization_rejects_completion_for_other_fields(model):
    state = EstadoLeitura()
    extract(state)
    payload = state.to_dict()
    context = next(iter(payload["contextos"].values()))
    next(iter(context["sucessos"].values()))["campos"] = ["camera_360"]
    with pytest.raises(ValueError, match="outros campos"):
        EstadoLeitura.from_dict(payload)


def test_large_failure_retries_only_large_pass_after_json(model, monkeypatch):
    state = EstadoLeitura()
    doc = run.Documento(texto="Especificação sem números", source_id="small")
    extract(state, doc, escalonar=True)
    success = llm.extrair_json
    monkeypatch.setattr(llm, "extrair_json", lambda **kw: llm.RespostaLLM(ok=False))
    failed = extract(state, doc, escalonar=True)
    restored = EstadoLeitura.from_dict(json.loads(json.dumps(state.to_dict())))
    monkeypatch.setattr(llm, "extrair_json", success)
    retried = extract(restored, doc, escalonar=True)
    assert failed.leitura["usados"] == retried.leitura["usados"]
    assert model[-1]["modelo"] == "fake-large"
    assert retried.leitura["pendentes"] == 0
