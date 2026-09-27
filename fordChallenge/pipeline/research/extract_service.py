"""Tavily Extract opcional, com cache íntegro e reserva no orçamento de serviços."""

import hashlib
import json
import os
from contextlib import suppress
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from pipeline import deadline
from pipeline.fetch.http import _escreve_atomico, modo_replay
from pipeline.research import service_budget

calls = ContextVar("extract_calls", default=0)
CACHE = Path(os.environ.get("RESEARCH_EXTRACT_CACHE_DIR") or "data/extract-service")


def caminho_de_cache(url: str) -> Path:
    key = hashlib.sha256(("tavily|advanced|markdown|" + url.rstrip("/")).encode()).hexdigest()
    return CACHE / datetime.now(UTC).strftime("%Y-%m-%d") / f"{key}.json"


def _le_cache(url: str):
    from pipeline.research.run import Coleta

    try:
        data = json.loads(caminho_de_cache(url).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("cache_version") != 1:
            return None
        if data.get("url", "").rstrip("/") != url.rstrip("/"):
            return None
        text = data.get("texto")
        if not isinstance(text, str) or not text:
            return None
        digest = hashlib.sha256(text.encode()).hexdigest()
        if data.get("sha256") != digest:
            return None
        captured_at = data.get("captured_at")
        if not isinstance(captured_at, str):
            return None
        datetime.fromisoformat(captured_at)
        return Coleta(
            texto=text,
            via="tavily_extract_cache",
            captured_at=captured_at,
            sha256=digest,
            http_status=200,
            creditos=0,
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _grava_cache(url, result):
    # Persistir só a página extraída e sua proveniência. Não copiar resposta arbitrária,
    # credenciais, requisição, identificador da conta ou payload para o checkpoint.
    data = {
        "cache_version": 1,
        "url": url,
        "texto": result.texto,
        "captured_at": result.captured_at,
        "sha256": result.sha256,
    }
    # Cache indisponível não descarta uma extração que já foi paga.
    with suppress(OSError):
        _escreve_atomico(caminho_de_cache(url), json.dumps(data, ensure_ascii=False).encode())


def _api_key():
    preferred = os.environ.get("TAVILY_API_KEY", "").strip()
    if preferred:
        return preferred
    provider = (os.environ.get("SEARCH_PROVIDER") or "").strip().lower()
    if provider in {"", "tavily", "replay"}:
        return os.environ.get("SEARCH_API_KEY", "").strip()
    return ""  # Não enviar chave de Exa/Brave para outro serviço.


def collect(url):
    if urlparse(url).path.lower().endswith(".pdf"):
        return None  # PDF precisa preservar células e spans do documento original.
    if modo_replay() or os.environ.get("RESEARCH_EXTRACT_PROVIDER") != "tavily":
        return None
    cached = _le_cache(url)
    if cached is not None:
        return cached
    key = _api_key()
    if calls.get() >= 2 or not key:
        return None
    from pipeline.research.run import Coleta

    try:
        remaining = deadline.timeout(20)
        if remaining < 2:
            return None
        receipt = service_budget.reserve(
            "tavily", "extract", service_budget.TAVILY_EXTRACT_ADVANCED_USD
        )
        calls.set(calls.get() + 1)
        response = httpx.post(
            "https://api.tavily.com/extract",
            headers={"Authorization": "Bearer " + key},
            json={
                "urls": [url],
                "extract_depth": "advanced",
                "format": "markdown",
                "timeout": min(15, remaining),
                "include_usage": True,
            },
            timeout=remaining,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        service_budget.settle_tavily(receipt, payload)
        results = payload.get("results", [])
        if not isinstance(results, list):
            return None
        for result in results:
            if (
                isinstance(result, dict)
                and isinstance(result.get("url"), str)
                and result["url"].rstrip("/") == url.rstrip("/")
                and isinstance(result.get("raw_content"), str)
                and result["raw_content"]
            ):
                text = result["raw_content"]
                collected = Coleta(
                    texto=text,
                    via="tavily_extract",
                    captured_at=datetime.now(UTC).isoformat(),
                    sha256=hashlib.sha256(text.encode()).hexdigest(),
                    http_status=200,
                    creditos=receipt.to_dict()["usage"].get("credits", 0),
                )
                _grava_cache(url, collected)
                return collected
    except (httpx.HTTPError, ValueError, TimeoutError, service_budget.BudgetExceeded):
        return None
    return None
