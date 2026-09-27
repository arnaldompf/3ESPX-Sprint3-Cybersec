"""Observabilidade e headers de segurança de toda resposta da API.

O que este módulo garante, e por quê:

* **`X-Request-ID` em toda resposta** (docs/04). O id do cliente é aceito — é assim que um
  request atravessa web app, API e worker com um só identificador — mas **sanitizado**:
  header é entrada de usuário, e um valor com espaço ou quebra de linha dentro contamina
  o log de quem o lê linha por linha.
* **Um evento por requisição, em JSON** (docs/08): `request_id`, método, rota, status e
  latência. Sem query string, sem corpo e sem IP — o log fica 90 dias e não é lugar de
  dado do usuário (LGPD).
* **Headers de segurança aplicados aqui**, e não delegados a um proxy que talvez exista na
  frente. HSTS **não** entra: em dev a API é HTTP, e um `Strict-Transport-Security` fixa o
  navegador em HTTPS para `localhost`, quebrando o web app na máquina de quem desenvolve.
  Em produção quem termina o TLS (Caddy/Traefik, docs/08) é quem envia o HSTS.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CABECALHO_REQUEST_ID = "X-Request-ID"
CABECALHO_TEMPO = "X-Response-Time-ms"

#: Formato aceito num request-id vindo de fora: o suficiente para UUID, ULID e trace-id de
#: proxy, e nada que possa abrir linha nova ou header novo no log.
_REQUEST_ID_ACEITO = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

#: CSP das rotas de API: a resposta é JSON, então nada precisa ser carregado.
CSP_API = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

#: CSP do `/docs`. O Swagger UI carrega JS/CSS de CDN e usa estilo inline; com o CSP da API
#: a página abre em branco e a documentação pública que docs/04 promete deixa de existir.
CSP_DOCS = (
    "default-src 'none'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)
ROTAS_DE_DOCUMENTACAO = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc"})

#: CSP do web app em `/app`. Defeito real e medido (D-184): com o `CSP_API`, o Chrome
#: **baixava** o `index.html` e **bloqueava** o módulo JS e a folha de estilo — a página
#: abria em branco, `#root` com 0 caracteres, e o console dizia exatamente isto:
#:
#:   Loading the script '.../app/assets/index-*.js' violates the following Content
#:   Security Policy directive: "default-src 'none'". Note that 'script-src-elem' was not
#:   explicitly set, so 'default-src' is used as a fallback.
#:
#: `curl` não aplica CSP, e era só com `curl` que a rota tinha sido conferida: os três
#: recursos respondiam 200 com o content-type certo, e ainda assim a tela era branca.
#:
#: O que cada diretiva libera, e por que nenhuma a mais:
#:
#: * `script-src 'self'` — o bundle é servido pelo próprio FastAPI, sem CDN e sem inline;
#: * `style-src 'self' 'unsafe-inline'` — a folha é própria, mas duas barras de progresso
#:   calculam a largura em `style={{ width }}` (Saude.tsx, Showroom.tsx), e atributo
#:   `style` conta como inline. Trocar isso por classe exigiria 101 classes de largura;
#: * `img-src 'self' data:` — os ícones inline do Vite viram `data:`;
#: * `connect-src 'self'` — o `fetch` do front bate em `/api/v1`, mesma origem. Vale
#:   dizer o que ele NÃO permite: nenhum outro host. Exfiltração por `fetch` segue barrada;
#: * `form-action 'self'` — o formulário de login posta para a própria origem;
#: * `frame-ancestors 'none'` — segue proibido embutir o app em iframe (clickjacking).
CSP_APP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)

#: Prefixo do web app. Mesma constante de `api/app/web.py`, repetida aqui de propósito:
#: importar `web.py` no middleware criaria dependência circular (o `web.py` importa o
#: `FastAPI` que o `main.py` monta), e o teste `test_csp_cobre_o_prefixo_do_web` trava as
#: duas juntas — se uma mudar sem a outra, ele falha.
PREFIXO_DO_WEB_APP = "/app"

#: Exportado porque o handler de 500 também precisa carimbá-los: quando a exceção sobe até
#: o `ServerErrorMiddleware` do Starlette, a resposta não volta pelos middlewares e ficaria
#: sem header de segurança nenhum. Um dicionário, dois pontos de aplicação.
HEADERS_SEGURANCA: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": CSP_API,
}

_log = structlog.get_logger("specradar.api")

ProximoHandler = Callable[[Request], Awaitable[Response]]


def configurar_logs(nivel: str = "INFO") -> None:
    """Liga o structlog em JSON, no nível de `LOG_LEVEL` (docs/08).

    `cache_logger_on_first_use=False` é a escolha que menos parece importar e mais importa:
    com o cache ligado, um logger já usado guarda a cadeia de processadores antiga, e o
    `structlog.testing.capture_logs` deixa de ver o que o código loga — a suíte passaria
    verde sem testar log nenhum.
    """
    niveis = logging.getLevelNamesMapping()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            niveis.get(nivel.strip().upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def _sanitizar_request_id(bruto: str | None) -> str:
    """Devolve o id do cliente se ele for aceitável; senão, um novo."""
    if bruto and _REQUEST_ID_ACEITO.match(bruto):
        return bruto
    return uuid.uuid4().hex


def id_da_requisicao(request: Request) -> str:
    """Request-id desta requisição — sempre um valor, nunca `None`.

    Guardado em `request.state`, que é respaldado pelo `scope` da requisição. É o que
    permite ao handler de 500 recuperar o mesmo id, mesmo rodando fora da cadeia de
    middlewares: `instance` no corpo do erro e `X-Request-ID` no header têm de ser o mesmo
    número, ou a correlação com o log não existe.
    """
    atual = getattr(request.state, "request_id", None)
    if isinstance(atual, str) and atual:
        return atual
    novo = _sanitizar_request_id(request.headers.get(CABECALHO_REQUEST_ID))
    request.state.request_id = novo
    return novo


class ObservabilidadeMiddleware(BaseHTTPMiddleware):
    """Request-id, tempo de resposta e o evento `http.request` de cada requisição."""

    async def dispatch(self, request: Request, call_next: ProximoHandler) -> Response:
        request_id = id_da_requisicao(request)
        # O bind no contexto serve aos *outros* módulos: qualquer log emitido durante a
        # requisição sai com `request_id` sem precisar receber o valor por parâmetro.
        structlog.contextvars.bind_contextvars(request_id=request_id)
        inicio = time.perf_counter()
        try:
            resposta = await call_next(request)
            duracao_ms = (time.perf_counter() - inicio) * 1000
            resposta.headers[CABECALHO_REQUEST_ID] = request_id
            resposta.headers[CABECALHO_TEMPO] = f"{duracao_ms:.2f}"
            _log.info(
                "http.request",
                # Explícito além do contexto: `capture_logs` desliga o `merge_contextvars`,
                # e um campo que só existe via contexto não é testável.
                request_id=request_id,
                metodo=request.method,
                # `url.path` e não `url`: query string pode carregar dado do usuário.
                rota=request.url.path,
                status=resposta.status_code,
                duracao_ms=round(duracao_ms, 2),
            )
            return resposta
        finally:
            # Nos dois caminhos, inclusive quando a rota estoura: sem o unbind, o
            # request-id vaza para a próxima requisição atendida no mesmo contexto.
            structlog.contextvars.unbind_contextvars("request_id")


class SegurancaMiddleware(BaseHTTPMiddleware):
    """Headers de segurança de docs/04, com CSP próprio no `/docs` e no `/app`.

    Três políticas, uma por tipo de resposta, e a mais fechada é a padrão: JSON não
    carrega nada (`CSP_API`), a documentação carrega de CDN (`CSP_DOCS`), o web app
    carrega o que ele mesmo serve (`CSP_APP`). Rota nova nasce com a política de API.
    """

    async def dispatch(self, request: Request, call_next: ProximoHandler) -> Response:
        resposta = await call_next(request)
        headers = dict(HEADERS_SEGURANCA)
        caminho = request.url.path
        if caminho in ROTAS_DE_DOCUMENTACAO:
            headers["Content-Security-Policy"] = CSP_DOCS
        elif caminho == PREFIXO_DO_WEB_APP or caminho.startswith(PREFIXO_DO_WEB_APP + "/"):
            # `== "/app"` além do prefixo com barra porque a primeira resposta que o
            # navegador recebe é o 307 de `/app` para `/app/`, e o resto do app pende dele.
            headers["Content-Security-Policy"] = CSP_APP
        for nome, valor in headers.items():
            # `setdefault`: se o handler de erro já carimbou, o dele vale.
            resposta.headers.setdefault(nome, valor)
        return resposta


def registrar_middlewares(app: FastAPI) -> None:
    """Segurança por dentro, observabilidade por fora.

    `add_middleware` empilha de dentro para fora — o último adicionado é o primeiro a ver
    a requisição. A observabilidade tem de ser a mais externa da dupla para que a latência
    que ela mede inclua tudo o que vem depois dela.
    """
    app.add_middleware(SegurancaMiddleware)
    app.add_middleware(ObservabilidadeMiddleware)
