"""Busca opcional, retenção permitida e custo controlado sem chamadas externas."""

import json
import socket

import httpx
import pytest

from pipeline.research import search, service_budget


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("REPLAY_MODE", "0")
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("SEARCH_API_KEY", "test-generic-key")
    for key in ("EXA_API_KEY", "SEARCH_BRAVE_STORAGE_RIGHTS", "SEARCH_TAVILY_DEPTH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(search, "CACHE", tmp_path / "search")

    def network_forbidden(*args, **kwargs):
        raise AssertionError("rede sem dublê")

    monkeypatch.setattr(httpx, "post", network_forbidden)
    monkeypatch.setattr(httpx, "get", network_forbidden)
    monkeypatch.setattr(socket, "socket", network_forbidden)


def fake_response(url, payload):
    return httpx.Response(200, json=payload, request=httpx.Request("POST", url))


def test_exa_descobre_urls_com_chave_propria_e_sem_comprar_contents(monkeypatch):
    calls = []
    monkeypatch.setenv("EXA_API_KEY", "test-exa-key")

    def post(url, **kw):
        calls.append((url, kw))
        return fake_response(
            url,
            {
                "results": [{"url": "https://ford.com.br/ficha.pdf", "title": "Ficha"}],
                "costDollars": {"total": 0.006},
            },
        )

    monkeypatch.setattr(httpx, "post", post)
    with service_budget.scope(max_usd=0.007, max_calls=1) as budget:
        response = search.buscar(
            "Ranger ficha Brasil", provedor="exa", quantos=100, dominios=("ford.com.br",)
        )
    assert response.ok and response.achados[0].snippet == ""
    url, kw = calls[0]
    assert url == "https://api.exa.ai/search"
    assert kw["headers"]["x-api-key"] == "test-exa-key"
    assert kw["json"]["numResults"] == 10
    assert kw["json"]["includeDomains"] == ["ford.com.br"]
    assert kw["json"]["userLocation"] == "BR"
    assert "contents" not in kw["json"]
    assert "language" not in kw["json"]
    assert response.custo_previsto_usd == budget.accounted_usd == 0.007
    assert response.custo_real_usd is None
    assert response.provider_estimate_usd == 0.006


def test_chave_generica_exa_so_com_search_provider_exa(monkeypatch):
    with service_budget.scope() as budget:
        unavailable = search.buscar("consulta", provedor="exa")
    assert not unavailable.ok and budget.calls == 0
    monkeypatch.setenv("SEARCH_PROVIDER", "exa")
    monkeypatch.setattr(httpx, "post", lambda url, **kw: fake_response(url, {"results": []}))
    with service_budget.scope() as budget:
        available = search.buscar("consulta", provedor="exa")
    assert available.ok and budget.calls == 1


@pytest.mark.parametrize(
    ("depth", "price", "credits"), [("basic", 0.008, 1), ("advanced", 0.016, 2)]
)
def test_tavily_reserva_antes_http_e_acerta_so_usage_explicita(monkeypatch, depth, price, credits):
    monkeypatch.setenv("SEARCH_TAVILY_DEPTH", depth)
    with service_budget.scope(max_usd=price, max_calls=1) as budget:

        def post(url, **kw):
            assert budget.accounted_usd == price and budget.calls == 1
            assert kw["json"]["search_depth"] == depth
            assert kw["json"]["include_usage"] is True
            assert kw["json"]["language"] == "pt"
            return fake_response(url, {"results": [], "usage": {"credits": credits}})

        monkeypatch.setattr(httpx, "post", post)
        response = search.buscar("consulta")
    assert response.custo_previsto_usd == response.custo_real_usd == price
    assert response.usage == {"credits": float(credits)}


def test_cachehit_consumo_zero_e_nao_precisa_chave(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: fake_response(url, {"results": []}))
    search.buscar("consulta")
    monkeypatch.delenv("SEARCH_API_KEY")
    with service_budget.scope(max_usd=0, max_calls=0) as budget:
        cached = search.buscar("consulta")
    assert cached.ok and cached.do_cache
    assert cached.custo_previsto_usd == 0 and cached.custo_real_usd is None
    assert budget.calls == 0


def test_budget_negado_impede_http_e_retorna_estado_explicito():
    with service_budget.scope(max_usd=0.007, max_calls=10) as budget:
        response = search.buscar("consulta")
    assert response.orcamento_excedido and not response.ok
    assert budget.calls == 0


def test_timeout_preserva_reserva_e_erro_nao_expoe_payload(monkeypatch):
    def post(*args, **kwargs):
        raise httpx.ReadTimeout("test-generic-key cliente identificado payload privado")

    monkeypatch.setattr(httpx, "post", post)
    with service_budget.scope(max_usd=0.008, max_calls=3) as budget:
        first = search.buscar("consulta")
        second = search.buscar("outra")
    assert not first.ok and second.orcamento_excedido
    assert budget.accounted_usd == first.custo_previsto_usd == 0.008
    assert first.custo_real_usd is None
    assert "test-generic-key" not in first.erro and "cliente identificado" not in first.erro


@pytest.mark.parametrize("name", ["tavily", "brave", "exa", "searxng", "duckduckgo"])
def test_classes_diretas_nao_burlam_replay(monkeypatch, name):
    monkeypatch.setenv("REPLAY_MODE", "1")
    with service_budget.scope() as budget, pytest.raises(search.RedeProibidaEmReplay):
        search.montar(name).buscar("consulta")
    assert budget.calls == 0


@pytest.mark.parametrize("opt_in", [False, True])
def test_brave_nao_persiste_nem_le_resultados_sem_direito_de_armazenamento(monkeypatch, opt_in):
    if opt_in:
        monkeypatch.setenv("SEARCH_BRAVE_STORAGE_RIGHTS", "1")
    calls = []

    def get(url, **kw):
        calls.append(url)
        return fake_response(url, {"web": {"results": [{"url": "https://ford.com.br"}]}})

    monkeypatch.setattr(httpx, "get", get)
    with service_budget.scope() as budget:
        search.buscar("consulta", provedor="brave")
        second = search.buscar("consulta", provedor="brave")
    assert len(calls) == (1 if opt_in else 2)
    assert second.do_cache is opt_in
    assert budget.accounted_usd == (0.005 if opt_in else 0.010)
    assert search.caminho_de_cache("consulta", "brave").exists() is opt_in


def test_brave_ignora_cache_legado_quando_optin_foi_retirado(monkeypatch):
    path = search.caminho_de_cache("consulta", "brave")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"achados": [{"url": "https://old.test"}]}), encoding="utf-8")
    monkeypatch.setenv("REPLAY_MODE", "1")
    with pytest.raises(search.RedeProibidaEmReplay):
        search.buscar("consulta", provedor="brave")


def test_profundidade_advanced_nao_reaproveita_cache_basic(monkeypatch):
    basic = search.caminho_de_cache("consulta", "tavily")
    monkeypatch.setenv("SEARCH_TAVILY_DEPTH", "advanced")
    assert search.caminho_de_cache("consulta", "tavily") != basic


def test_falha_no_checkpoint_da_reserva_impede_http():
    def cannot_save():
        raise OSError("checkpoint não gravado")

    with service_budget.scope(max_usd=0.008, max_calls=1) as budget:
        budget.on_change = cannot_save
        response = search.buscar("consulta")
    assert not response.ok and "OSError" in response.erro
    assert budget.calls == 1 and budget.accounted_usd == 0.008
