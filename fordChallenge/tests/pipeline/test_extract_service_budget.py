"""Extração paga só inicia com reserva e não repete cobrança por cache íntegro."""

import json

import httpx
import pytest

from pipeline import deadline
from pipeline.research import extract_service, service_budget

URL = "https://ford.com.br/ficha"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLAY_MODE", "0")
    monkeypatch.setenv("RESEARCH_EXTRACT_PROVIDER", "tavily")
    monkeypatch.setenv("SEARCH_API_KEY", "test-key")
    monkeypatch.setattr(extract_service, "CACHE", tmp_path / "extract", raising=False)
    token = extract_service.calls.set(0)

    def forbidden(*args, **kwargs):
        raise AssertionError("rede não dublada")

    monkeypatch.setattr(httpx, "post", forbidden)
    yield
    extract_service.calls.reset(token)


def respond(monkeypatch, payload=None):
    calls = []
    payload = payload or {
        "results": [{"url": URL, "raw_content": "Potência 250 cv"}],
        "usage": {"credits": 2},
    }

    def post(url, **kw):
        calls.append(kw)
        assert service_budget.current_budget().accounted_usd >= 0.016
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    return calls


def test_extract_e_search_compartilham_o_mesmo_teto():
    with service_budget.scope(max_usd=0.020, max_calls=30) as budget:
        budget.reserve("tavily", "search", 0.008)
        assert extract_service.collect(URL) is None
    assert budget.calls == 1 and extract_service.calls.get() == 0


def test_cache_hit_custa_zero_e_preserva_data_e_hash_da_captura(monkeypatch):
    requests = respond(monkeypatch)
    with service_budget.scope() as budget:
        first = extract_service.collect(URL)
    assert budget.accounted_usd == budget.actual_usd == 0.016
    monkeypatch.delenv("SEARCH_API_KEY")
    with service_budget.scope(max_usd=0, max_calls=0) as budget:
        second = extract_service.collect(URL)
    assert second is not None
    assert second.texto == first.texto and second.sha256 == first.sha256
    assert second.captured_at == first.captured_at
    assert second.creditos == 0 and budget.calls == 0
    assert len(requests) == 1


def test_corromper_cache_exige_recoleta_com_nova_reserva(monkeypatch):
    requests = respond(monkeypatch)
    with service_budget.scope() as budget:
        extract_service.collect(URL)
        arquivo = extract_service.caminho_de_cache(URL)
        meta = json.loads(arquivo.read_text(encoding="utf-8"))
        meta["texto"] = "valor adulterado"
        arquivo.write_text(json.dumps(meta), encoding="utf-8")
        result = extract_service.collect(URL)
    assert result.texto == "Potência 250 cv"
    assert len(requests) == budget.calls == 2


def test_erro_http_incerto_conserva_reserva(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ReadTimeout("test-key")

    monkeypatch.setattr(httpx, "post", fail)
    with service_budget.scope() as budget:
        assert extract_service.collect(URL) is None
    assert budget.calls == 1 and budget.accounted_usd == 0.016
    assert budget.actual_usd is None


@pytest.mark.parametrize("reason", ["replay", "key", "deadline", "pdf", "pdf_fragment", "disabled"])
def test_sem_chamada_nao_reserva_creditos(monkeypatch, reason):
    if reason == "replay":
        monkeypatch.setenv("REPLAY_MODE", "1")
    elif reason == "key":
        monkeypatch.delenv("SEARCH_API_KEY")
    elif reason == "disabled":
        monkeypatch.setenv("RESEARCH_EXTRACT_PROVIDER", "")
    with service_budget.scope() as budget, deadline.budget(0 if reason == "deadline" else 30):
        url = URL + ".pdf#page=2" if reason == "pdf_fragment" else URL
        assert extract_service.collect(URL + ".pdf" if reason == "pdf" else url) is None
    assert budget.calls == 0 and extract_service.calls.get() == 0


def test_usage_ausente_nao_e_gratuidade(monkeypatch):
    respond(monkeypatch, {"results": [{"url": URL, "raw_content": "Potência 250 cv"}]})
    with service_budget.scope() as budget:
        result = extract_service.collect(URL)
    assert result is not None
    assert budget.accounted_usd == 0.016 and budget.actual_usd is None


def test_resposta_de_outra_url_nao_vira_cache_de_evidencia(monkeypatch):
    respond(
        monkeypatch,
        {
            "results": [{"url": "https://outro.test", "raw_content": "dados"}],
            "usage": {"credits": 2},
        },
    )
    with service_budget.scope() as budget:
        assert extract_service.collect(URL) is None
    assert budget.accounted_usd == 0.016
    assert not extract_service.caminho_de_cache(URL).exists()


def test_extract_nao_envia_chave_exa_para_tavily(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "exa")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with service_budget.scope() as budget:
        assert extract_service.collect(URL) is None
    assert budget.calls == 0
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    requests = respond(monkeypatch)
    with service_budget.scope():
        assert extract_service.collect(URL) is not None
    assert requests[0]["headers"]["Authorization"] == "Bearer test-tavily-key"
