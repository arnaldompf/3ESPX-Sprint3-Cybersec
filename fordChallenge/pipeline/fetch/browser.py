"""Coleta com navegador real (Crawl4AI/Playwright) — o fetcher previsto em `docs/05`.

Por que um navegador, e por que isso **não** é contornar bloqueio: `docs/05` especifica
"Crawl4AI (Playwright headless)" como *o* coletor de HTML do projeto, desde antes de
qualquer bloqueio aparecer. Três das quatro montadoras recusam cliente HTTP simples na
borda (Ford, Toyota e Chevrolet responderam 403 a `httpx` na noite de 08/09), e páginas de
montadora montam a lista de versões por JavaScript — sem navegador não há o que parsear.
O que continua proibido é o que sempre foi: forjar identidade. O user-agent segue sendo o
nosso, com contato, e o robots.txt segue sendo consultado antes.

Se a resposta com navegador **também** for 403 ou trouxer verificação anti-bot, o
resultado é `blocked` e para aí.

Instalação (fora do CI, que roda em replay):

    uv sync --extra collect
    uv run crawl4ai-setup       # baixa o Chromium do Playwright

Sem o extra instalado, :func:`disponivel` devolve `False` e :func:`fetch_browser` devolve
um resultado `erro` explicando o que falta — nunca um silêncio.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pipeline import deadline
from pipeline.fetch import http

#: Seletores comuns de banner de cookies nos sites das montadoras BR.
SELETORES_DE_COOKIE = (
    "#onetrust-accept-btn-handler",
    "button#onetrust-accept-btn-handler",
    ".onetrust-close-btn-handler",
    "button[aria-label='Aceitar todos os cookies']",
    "button[aria-label='Aceitar cookies']",
    "button[data-testid='cookie-accept-all']",
    "#adopt-accept-all-button",
    ".cookie-accept",
    "#cookie-accept",
)

TIMEOUT_MS = 45_000

#: Marcas de bloqueio na **mensagem de erro** do Crawl4AI (não no corpo da página).
#: Quando o escudo responde antes do HTML, não há corpo para `http.parece_antibot` ler.
MARCAS_DE_BLOQUEIO_NA_MENSAGEM = (
    "anti-bot",
    "antibot",
    "akamai",
    "cloudflare",
    "blocked",
    "forbidden",
    "403",
    "429",
    "captcha",
)


def _mensagem_de_bloqueio(mensagem: str) -> bool:
    """A mensagem de erro do navegador denuncia um escudo, e não uma falha de rede?"""
    texto = mensagem.lower()
    return any(marca in texto for marca in MARCAS_DE_BLOQUEIO_NA_MENSAGEM)


@dataclass
class ResultadoNavegador:
    url: str
    status: str
    markdown: str = ""
    html: str = ""
    screenshot: bytes | None = None
    url_final: str = ""
    http_status: int | None = None
    motivo: str = ""
    avisos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == http.STATUS_OK


def disponivel() -> bool:
    """O extra `collect` (Crawl4AI + Playwright) está instalado?"""
    try:
        import crawl4ai  # noqa: F401
    except ImportError:
        return False
    return True


def _motivo_indisponivel() -> str:
    return (
        "Crawl4AI não está instalado. Rode `uv sync --extra collect` e "
        "`uv run crawl4ai-setup` (baixa o Chromium). O CI roda em REPLAY_MODE=1 e "
        "não precisa disso."
    )


async def fetch_browser_async(
    url: str,
    *,
    screenshot: bool = True,
    timeout_ms: int = TIMEOUT_MS,
) -> ResultadoNavegador:
    """Abre a URL num Chromium headless, espera a rede parar e devolve markdown + print."""
    if http.modo_replay():
        return ResultadoNavegador(
            url=url,
            status=http.STATUS_ERRO,
            motivo="REPLAY_MODE=1: use pipeline.fetch.http.fetch, que resolve por snapshot",
        )
    if not disponivel():
        return ResultadoNavegador(url=url, status=http.STATUS_ERRO, motivo=_motivo_indisponivel())

    # robots.txt antes de abrir o navegador: a regra não depende da ferramenta.
    if not http.permitido_por_robots(url):
        return ResultadoNavegador(
            url=url,
            status=http.STATUS_BLOQUEADO_ROBOTS,
            motivo=f"robots.txt proíbe esta rota para {http.user_agent()}",
        )

    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

    js_cookies = ";".join(
        f"try{{document.querySelector({s!r})?.click()}}catch(e){{}}" for s in SELETORES_DE_COOKIE
    )
    navegador = BrowserConfig(headless=True, user_agent=http.user_agent(), verbose=False)
    execucao = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        wait_until="networkidle",
        page_timeout=timeout_ms,
        screenshot=screenshot,
        js_code=[js_cookies],
        scan_full_page=True,
    )

    http._espera_o_limite(url)  # o limitador de 1 req/s vale para o navegador também
    async with AsyncWebCrawler(config=navegador) as crawler:
        resposta = await crawler.arun(url=url, config=execucao)

    if not getattr(resposta, "success", False):
        codigo_falha = getattr(resposta, "status_code", None)
        mensagem = str(getattr(resposta, "error_message", "") or "falha no navegador")
        # O Crawl4AI reconhece o escudo (Akamai, Cloudflare) e devolve `success=False`
        # com o motivo na mensagem, sem HTML nenhum. Sem esta leitura, o bloqueio saía
        # como `erro` — e `erro` convida a nova tentativa, que é exatamente o que a regra
        # de `docs/02` ADR-7 proíbe. Medido em 10/09/2026 na Ford:
        # "Blocked by anti-bot protection: Akamai block (Reference #)" com http 403.
        if codigo_falha in {401, 403, 429} or _mensagem_de_bloqueio(mensagem):
            return ResultadoNavegador(
                url=url,
                status=http.STATUS_BLOQUEADO,
                http_status=codigo_falha,
                motivo=(
                    f"o site recusou também o navegador ({mensagem}). Bloqueio vira "
                    "status; nenhuma tentativa de forjar identidade."
                ),
            )
        return ResultadoNavegador(
            url=url,
            status=http.STATUS_ERRO,
            http_status=codigo_falha,
            motivo=mensagem,
        )

    html = getattr(resposta, "html", "") or ""
    markdown = str(getattr(resposta, "markdown", "") or "")
    codigo = getattr(resposta, "status_code", None)

    if codigo in {401, 403, 429} or http.parece_antibot(html) or http.parece_antibot(markdown):
        return ResultadoNavegador(
            url=url,
            status=http.STATUS_BLOQUEADO,
            http_status=codigo,
            motivo=(
                "o site recusou também o navegador (403/anti-bot). Bloqueio vira status; "
                "nenhuma tentativa de forjar identidade."
            ),
        )

    tiro = getattr(resposta, "screenshot", None)
    if isinstance(tiro, str):  # crawl4ai devolve base64
        import base64

        tiro = base64.b64decode(tiro)

    return ResultadoNavegador(
        url=url,
        status=http.STATUS_OK,
        markdown=markdown,
        html=html,
        screenshot=tiro,
        url_final=str(getattr(resposta, "url", url) or url),
        http_status=codigo,
        motivo="coletado com navegador headless",
    )


def fetch_browser(url: str, **kw) -> ResultadoNavegador:
    """Versão síncrona de :func:`fetch_browser_async`."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:

        async def bounded():
            return await asyncio.wait_for(
                fetch_browser_async(url, **kw), timeout=deadline.timeout(60)
            )

        return asyncio.run(bounded())
    raise RuntimeError("fetch_browser chamado de dentro de um event loop; use fetch_browser_async")
