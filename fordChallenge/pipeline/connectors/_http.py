"""HTTP educado mínimo — **provisório**, substituído pelo fetcher da WP-08.

A WP-07 precisa buscar a página de linha vigente ao vivo, mas o fetcher completo
(Crawl4AI, snapshots, cache por dia) é escopo da WP-08. Este módulo faz o mínimo que a
regra do projeto exige, e nada além:

* **robots.txt honrado** antes de qualquer requisição — proibido é `blocked_by_robots`,
  não "tenta de outro jeito";
* **1 requisição por segundo por domínio**, contado em processo;
* **user-agent identificado** de `SPECRADAR_USER_AGENT`;
* **403/CAPTCHA vira `FonteBloqueada`** — nunca rotação de IP ou de UA;
* **`REPLAY_MODE=1` bloqueia a rede por completo**: qualquer chamada levanta.

Quando a WP-08 entrar, os conectores passam a chamar `pipeline.fetch` e este arquivo sai.
"""

from __future__ import annotations

import os
import time
import urllib.robotparser
from urllib.parse import urlparse

import httpx

from pipeline.connectors.base import FonteBloqueada, modo_replay

TIMEOUT_S = 30.0
#: último instante de requisição por domínio, para o limitador de 1 req/s
_ultimo_acesso: dict[str, float] = {}
_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}


class RedeProibidaEmReplay(RuntimeError):
    """Tentativa de acessar a rede com `REPLAY_MODE=1`.

    Levanta de propósito: replay que "cai para a rede" quando falta um snapshot deixa
    de ser determinístico e a demo passa a depender de wi-fi.
    """


class BloqueadoPorRobots(FonteBloqueada):
    """O robots.txt do domínio proíbe esta rota."""


def user_agent() -> str:
    return os.environ.get(
        "SPECRADAR_USER_AGENT", "SpecRadar/0.1 (FIAP Challenge Ford; contato: nao-informado)"
    )


def _robots(dominio: str, esquema: str) -> urllib.robotparser.RobotFileParser | None:
    if dominio in _robots_cache:
        return _robots_cache[dominio]
    parser = urllib.robotparser.RobotFileParser()
    url = f"{esquema}://{dominio}/robots.txt"
    try:
        resposta = httpx.get(url, timeout=10.0, headers={"User-Agent": user_agent()})
        if resposta.status_code >= 400:
            # sem robots.txt legível, o padrão é permitir (RFC 9309)
            _robots_cache[dominio] = None
            return None
        parser.parse(resposta.text.splitlines())
    except httpx.HTTPError:
        _robots_cache[dominio] = None
        return None
    _robots_cache[dominio] = parser
    return parser


def permitido(url: str) -> bool:
    """O robots.txt do domínio permite esta URL para o nosso user-agent?"""
    partes = urlparse(url)
    parser = _robots(partes.netloc, partes.scheme or "https")
    if parser is None:
        return True
    return parser.can_fetch(user_agent(), url)


def _espera_o_limite(dominio: str) -> None:
    rps = float(os.environ.get("FETCH_RATE_LIMIT_RPS", "1") or 1)
    intervalo = 1.0 / max(rps, 0.01)
    agora = time.monotonic()
    anterior = _ultimo_acesso.get(dominio)
    if anterior is not None:
        falta = intervalo - (agora - anterior)
        if falta > 0:
            time.sleep(falta)
    _ultimo_acesso[dominio] = time.monotonic()


def get_text(url: str, *, timeout: float = TIMEOUT_S) -> str:
    """Busca o HTML de uma URL, educadamente. Levanta em replay ou se bloqueado."""
    if modo_replay():
        raise RedeProibidaEmReplay(
            f"REPLAY_MODE=1 e alguem tentou buscar {url}. "
            "Em replay o pipeline usa apenas snapshots e fixtures."
        )
    if not permitido(url):
        raise BloqueadoPorRobots(f"robots.txt proibe {url}")
    dominio = urlparse(url).netloc
    _espera_o_limite(dominio)
    try:
        resposta = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent(), "Accept-Language": "pt-BR,pt;q=0.9"},
        )
    except httpx.HTTPError as exc:
        raise FonteBloqueada(f"erro de rede em {url}: {exc}") from exc
    if resposta.status_code in {401, 403, 429} or resposta.status_code >= 500:
        raise FonteBloqueada(f"HTTP {resposta.status_code} em {url}")
    texto = resposta.text
    if _parece_captcha(texto):
        raise FonteBloqueada(f"anti-bot/CAPTCHA em {url}")
    return texto


def _parece_captcha(html: str) -> bool:
    marcas = ("captcha", "are you a human", "cf-challenge", "verifique que voce e humano")
    trecho = html[:4000].lower()
    return any(m in trecho for m in marcas)
