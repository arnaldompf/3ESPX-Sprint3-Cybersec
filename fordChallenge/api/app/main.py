"""Fábrica do app FastAPI do SpecRadar.

`create_app()` em vez de um `app` montado direto no import: os testes precisam de um app
por cenário (CORS diferente, rota que estoura ligada) e um app global impediria isso. O
`app` no fim do módulo existe porque `uvicorn api.app.main:app` (scripts/task.py) pede um
objeto, não uma fábrica.

Rotas públicas desta WP: `/api/v1/health`, `/docs` e `/openapi.json` (docs/04). Auth, RBAC
e rate limit são da WP-05; o `Limiter` do slowapi fica pendurado em `app.state` **sem
política aplicada**, para que a WP-05 só precise decorar rotas.
"""

from __future__ import annotations

import os

import structlog
from fastapi import APIRouter, FastAPI
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.cors import CORSMiddleware

from api.app.config import get_settings, versao_do_pacote
from api.app.errors import RESPOSTAS_PADRAO, registrar_handlers
from api.app.middleware import (
    CABECALHO_REQUEST_ID,
    CABECALHO_TEMPO,
    configurar_logs,
    registrar_middlewares,
)
from api.app.rate_limit import LimiteGeralMiddleware, limiter
from api.app.routers import (
    auth,
    benchmark,
    catalog,
    domain,
    extractions,
    health,
    insights,
    jobs,
    parity,
    radar,
    reports,
    research,
    scenarios,
    showroom,
    sources,
    users,
    vehicles,
)
from api.app.web import montar_web

#: Avisos da montagem do app. O que mais importa ver no log é `AUTH_ENABLED=false`:
#: é o que diz que esta instância aceita qualquer requisição sem credencial (D-204).
log_inicial = structlog.get_logger("specradar.api.montagem")

#: Versionamento na URL (docs/04). Recurso novo entra aqui, não na raiz.
PREFIXO = "/api/v1"

DESCRICAO = """
Inteligência competitiva automotiva **auditável**: a mesma ficha de especificações para
qualquer veículo, cada campo com status, proveniência e confiança.

**Como ler uma resposta desta API**

* Todo campo carrega uma etiqueta: `FATO` (observado, com evidência localizada na fonte),
  `INFERÊNCIA` (regra explícita e visível) ou `SIMULAÇÃO` (hipótese ou dado de demo).
* `desconhecido` é um estado de primeira classe, nunca um campo omitido. `nao_disponivel`
  (a fonte oficial afirma a ausência) e `nao_encontrado` (nenhuma fonte cita) são estados
  **distintos**.
* Fontes que discordam viram `divergente` com todos os valores preservados. A API não
  escolhe vencedor em silêncio.

**Erros** saem em `application/problem+json` (RFC 9457) com
`{type, title, status, detail, instance}`. `instance` é o `X-Request-ID` da resposta: é o
que correlaciona o erro com o log estruturado do servidor. Nenhuma resposta de erro devolve
o corpo enviado nem stack trace.
"""

TAGS: list[dict[str, str]] = [
    {
        "name": "saude",
        "description": "Disponibilidade do processo de API e do banco. Endpoint público.",
    },
]


def _montar_rota_de_excecao(app: FastAPI) -> None:
    """Rota que estoura de propósito, para exercitar o caminho do 500.

    Ligada só com `SPECRADAR_DEBUG_BOOM=1`, e lida de `os.environ` em vez de entrar em
    `Settings` deliberadamente: não é configuração do produto, é instrumento de teste.
    Fora de `Settings` ela não aparece no `.env.example` e ninguém a liga por engano ao
    copiar o arquivo para produção.
    """
    if os.environ.get("SPECRADAR_DEBUG_BOOM") != "1":
        return

    depuracao = APIRouter(tags=["saude"], include_in_schema=False)

    @depuracao.get("/_debug/boom")
    def _boom() -> None:
        raise RuntimeError("explosao proposital: SPECRADAR_DEBUG_BOOM=1")

    app.include_router(depuracao, prefix=PREFIXO)


def create_app() -> FastAPI:
    """Monta a aplicação: logs, erros, middlewares, CORS e rotas."""
    settings = get_settings()
    configurar_logs(settings.log_level)

    app = FastAPI(
        title="SpecRadar API",
        description=DESCRICAO,
        version=versao_do_pacote(),
        openapi_tags=TAGS,
        openapi_url="/openapi.json",
        docs_url="/docs",
        # Uma página de documentação, não duas: o ReDoc não acrescenta nada aqui e cada
        # rota pública a mais é superfície a mais para manter no CSP.
        redoc_url=None,
    )

    registrar_handlers(app)

    # CORS adicionado **antes** de `registrar_middlewares` e portanto por dentro dele: assim
    # a resposta de preflight, que o CORSMiddleware devolve sem chamar a rota, ainda sai com
    # `X-Request-ID` e com os headers de segurança.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.origens_cors),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", CABECALHO_REQUEST_ID],
        expose_headers=[CABECALHO_REQUEST_ID, CABECALHO_TEMPO, "X-Total-Count"],
        max_age=600,
    )
    registrar_middlewares(app)

    # O limite de requisições **só entra na pilha quando está ligado** (D-206). Com
    # `RATE_LIMIT_ENABLED=false`, que é o padrão desta fase, nenhum dos dois middlewares é
    # registrado: o limite sai do caminho de execução em vez de virar um contador com teto
    # alto que ainda custa uma passagem por requisição — e nenhuma tela pode voltar 429.
    #
    # Ligado, a instância vem de `api/app/rate_limit.py` e é a MESMA que o decorador de
    # `/auth/login` usa: duas instâncias dariam dois contadores independentes, e o limite
    # de 5/min do login não valeria. `default_limits` fica com o limite geral de docs/04
    # (60/min), e a chave é o usuário quando há token e o IP quando não há — o IP sozinho
    # faria um vendedor esgotar a cota da concessionária inteira.
    app.state.limiter = limiter
    if settings.rate_limit_enabled:
        app.add_middleware(SlowAPIMiddleware)
        # O middleware do slowapi nao alcanca os roteadores incluidos nesta versao do
        # FastAPI (ver `LimiteGeralMiddleware`), entao o limite geral de docs/04 e
        # aplicado por nos.
        app.add_middleware(LimiteGeralMiddleware)

    app.include_router(health.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    # Identificar no catálogo é parte da Consulta e não sai para a internet. A rota existe
    # mesmo com o Pesquisador desligado; nesse caso ela chama o identificador em modo
    # `so_catalogo` e nunca tenta busca/modelo.
    app.include_router(research.identificacao_router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    # O Pesquisador (WP-41): atrás de `RESEARCH_ENABLED`, porque ele sai para a
    # internet e gasta chamada de LLM — e a demo tem de poder rodar sem nenhum dos dois.
    if os.environ.get("RESEARCH_ENABLED", "").strip().lower() in {"1", "true", "sim"}:
        app.include_router(research.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    # `/auth/me` existe sempre — é o que a barra lateral lê para dizer quem está olhando.
    # O resto do `/auth` (login, refresh, logout) só é montado com `AUTH_ENABLED=1`: sem
    # autenticação não há senha a digitar, e uma rota de login que não serve para nada
    # continuaria anunciando no `/openapi.json` uma porta que não existe (D-204).
    app.include_router(
        auth.montar(settings.auth_enabled), prefix=PREFIXO, responses=RESPOSTAS_PADRAO
    )
    if not settings.auth_enabled:
        log_inicial.info(
            "auth_desligada",
            detalhe=(
                "AUTH_ENABLED=false: a API nao pede token, nao devolve 401/403 e le o "
                "papel do cabecalho X-Role. Ligue AUTH_ENABLED=1 para o fluxo de docs/04."
            ),
        )
    app.include_router(users.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    app.include_router(catalog.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    app.include_router(vehicles.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    app.include_router(extractions.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    app.include_router(domain.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    app.include_router(sources.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    app.include_router(radar.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    app.include_router(parity.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    # O Benchmark (FASE 3): atrás de `BENCHMARK_ENABLED`, pela mesma razão do Pesquisador
    # — capacidade nova entra atrás de interruptor até a apresentação passar, para que
    # desligá-la seja uma variável de ambiente e não um `git revert` às pressas.
    if os.environ.get("BENCHMARK_ENABLED", "").strip().lower() in {"1", "true", "sim"}:
        app.include_router(benchmark.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    app.include_router(scenarios.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    app.include_router(insights.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    app.include_router(showroom.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    app.include_router(reports.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    app.include_router(jobs.router, prefix=PREFIXO, responses=RESPOSTAS_PADRAO)
    _montar_rota_de_excecao(app)

    # O front-end vem DEPOIS dos roteadores de API: montado antes, o `StaticFiles`
    # capturaria caminhos que pertencem a `/api`.
    montar_web(app)
    return app


app = create_app()
