"""A API do SpecRadar endurecida para produção — `uvicorn seguranca.app_segura:app`.

Monta a mesma aplicação de `fordChallenge/api/app/main.py` (`create_app()`) e acrescenta
quatro controles, cada um ligado a um risco medido na solução:

1. **Trava de produção** (`validar_configuracao`). A solução sobe com `AUTH_ENABLED=false`
   e `RATE_LIMIT_ENABLED=false` por padrão — é o que a demo precisa, e é o que não pode
   chegar em produção por esquecimento. Com `APP_ENV=producao`, configuração insegura
   **impede a partida**, com a lista do que corrigir.

2. **Rate limit com chave verificada** (`chave_do_limite_verificada`). Na solução, a chave
   do limitador é o `sub` do JWT lido **sem verificar assinatura** (`api/app/rate_limit.py`).
   O comentário de lá supõe que um token forjado "só compete por uma cota alheia" — mas o
   atacante escolhe um `sub` novo a cada requisição e ganha uma cota nova a cada vez:
   o limite de 60/min vira ilimitado (demonstrado em `tests/test_rate_limit.py`). Aqui a
   chave só é o usuário quando o token é válido; qualquer outro caso conta pelo IP.

3. **Eventos de segurança e auditoria** (`EventosDeSegurancaMiddleware`). A solução loga
   cada requisição (`http.request`) e o login (`auth.login`, `auth.login_falhou`). Faltava
   o evento que a resposta a incidentes procura: 401/403 (`seguranca.acesso_negado`), 429
   (`seguranca.limite_excedido`) e escrita em recurso crítico (`auditoria.alteracao_critica`).
   O IP entra **pseudonimizado** (HMAC-SHA256): correlaciona ataques sem guardar o dado
   pessoal em claro (LGPD art. 13 §4 / art. 12).

4. **`/metrics`** para o Prometheus: requisições, latência, eventos de segurança, fila de
   jobs do pipeline e as métricas de qualidade do último eval de ML. Só responde para
   rede interna ou com `Authorization: Bearer $METRICS_TOKEN`; o proxy público
   (`infra/Caddyfile`) nem encaminha a rota.

Também liga a proteção de SSRF no coletor do pipeline (`seguranca.ssrf`), porque a pesquisa
ao vivo pode rodar dentro do processo da API.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import time
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, Response

from seguranca.metricas import REGISTRO
from seguranca.segredos import carregar_segredos_de_arquivo
from seguranca.solucao import preparar_importacao

carregar_segredos_de_arquivo()
SOLUCAO = preparar_importacao()

from api.app import rate_limit  # noqa: E402
from api.app.config import Settings, get_settings  # noqa: E402
from api.app.main import create_app  # noqa: E402
from api.app.security import SegredoInvalido, TokenInvalido, ler_token  # noqa: E402

_log = structlog.get_logger("specradar.seguranca")

AMBIENTES_DE_PRODUCAO = frozenset({"producao", "production", "prod"})

#: Prefixos cuja escrita é "alteração crítica" no plano de monitoramento: usuários e papéis,
#: fontes de coleta, referência interna/equivalências e publicação. `/auth` fica de fora de
#: propósito: login não altera nada, e a solução já emite `auth.login`, `auth.login_falhou`,
#: `auth.refresh_reusado` e `auth.logout` com o motivo.
PREFIXOS_CRITICOS = (
    "/api/v1/users",
    "/api/v1/sources",
    "/api/v1/domain",
)
METODOS_DE_ESCRITA = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# ------------------------------------------------------------------- 1. trava de produção
class ConfiguracaoInsegura(RuntimeError):
    """Configuração que não pode ir para produção. A mensagem lista todos os problemas."""


def em_producao() -> bool:
    return os.environ.get("APP_ENV", "").strip().lower() in AMBIENTES_DE_PRODUCAO


def problemas_de_configuracao(settings: Settings) -> list[str]:
    """O que impede esta configuração de rodar em produção. Lista vazia = pode subir."""
    problemas: list[str] = []
    if not settings.auth_enabled:
        problemas.append("AUTH_ENABLED=false: a API aceitaria qualquer requisição sem token")
    if not settings.rate_limit_enabled:
        problemas.append("RATE_LIMIT_ENABLED=false: login e API sem limite de requisições")
    if len((settings.jwt_secret or "").encode()) < 32:
        problemas.append("JWT_SECRET ausente ou com menos de 32 bytes")
    for origem in settings.origens_cors:
        if origem.startswith("http://"):
            problemas.append(f"CORS_ORIGINS contém origem sem TLS: {origem}")
    if settings.database_url.startswith("sqlite"):
        problemas.append("DATABASE_URL aponta para SQLite; produção usa Postgres")
    if os.environ.get("SPECRADAR_DEBUG_BOOM") == "1":
        problemas.append("SPECRADAR_DEBUG_BOOM=1 expõe uma rota de depuração")
    if not os.environ.get("METRICS_TOKEN"):
        problemas.append("METRICS_TOKEN ausente: /metrics ficaria só com a regra de rede")
    return problemas


def validar_configuracao(settings: Settings | None = None) -> None:
    """Em produção, levanta `ConfiguracaoInsegura`; fora dela, só avisa no log."""
    problemas = problemas_de_configuracao(settings or get_settings())
    if not problemas:
        return
    if em_producao():
        raise ConfiguracaoInsegura(
            "Configuração insegura para APP_ENV=producao:\n- " + "\n- ".join(problemas)
        )
    _log.warning("seguranca.configuracao_de_desenvolvimento", problemas=problemas)


# ------------------------------------------------------------- 2. rate limit verificado
def chave_do_limite_verificada(request: Request) -> str:
    """`user:<sub>` só com access token **válido**; `ip:<addr>` em qualquer outro caso."""
    autorizacao = request.headers.get("Authorization", "")
    if autorizacao.lower().startswith("bearer "):
        try:
            claims = ler_token(autorizacao[7:].strip(), tipo_esperado="access")
            return f"user:{claims.sub}"
        except (TokenInvalido, SegredoInvalido):
            pass
    return f"ip:{get_remote_address(request)}"


#: A chave como a solução a escreveu, guardada antes da troca (os testes a usam para
#: demonstrar a vulnerabilidade).
CHAVE_ORIGINAL_DA_SOLUCAO = rate_limit.chave_do_limite


def corrigir_chave_do_limite() -> None:
    """Troca a chave no limitador único da solução e no middleware que a usa."""
    rate_limit.chave_do_limite = chave_do_limite_verificada
    rate_limit.limiter._key_func = chave_do_limite_verificada


# ------------------------------------------------------- 3. eventos de segurança e métricas
_CHAVE_PSEUDONIMO = (os.environ.get("LOG_PSEUDONIMO_KEY") or secrets.token_hex(32)).encode()


def pseudonimo_de_ip(endereco: str | None) -> str:
    """HMAC-SHA256 truncado do IP. Mesmo IP → mesmo pseudônimo, sem guardar o IP."""
    if not endereco:
        return "desconhecido"
    return hmac.new(_CHAVE_PSEUDONIMO, endereco.encode(), hashlib.sha256).hexdigest()[:16]


def _modelo_da_rota(request: Request, status: int) -> str:
    """`/api/v1/vehicles/{vehicle_id}/specs`, nunca `/api/v1/vehicles/abc123/specs`.

    O `route.path` desta versão do FastAPI é relativo ao roteador incluído (`/health`, sem
    o prefixo), então o modelo é reconstruído do caminho real: cada segmento que é valor
    de um parâmetro da rota volta a ser o nome dele.
    """
    caminho = request.url.path
    if caminho == "/app" or caminho.startswith("/app/"):
        return "/app/*"
    if request.scope.get("route") is None:
        # O 429 do limitador sai antes do roteamento. Caminho concreto não vira rótulo:
        # um atacante com caminhos aleatórios criaria uma série por requisição.
        return "bloqueada_pelo_rate_limit" if status == 429 else "nao_roteada"
    parametros = {str(v): k for k, v in (request.scope.get("path_params") or {}).items()}
    return "/".join(f"{{{parametros[s]}}}" if s in parametros else s for s in caminho.split("/"))


def _papel(request: Request) -> str:
    autorizacao = request.headers.get("Authorization", "")
    if autorizacao.lower().startswith("bearer "):
        try:
            return ler_token(autorizacao[7:].strip(), tipo_esperado="access").role
        except (TokenInvalido, SegredoInvalido):
            return "token_invalido"
    return (request.headers.get("X-Role") or "sem_papel").strip().lower()[:20]


class EventosDeSegurancaMiddleware(BaseHTTPMiddleware):
    """O mais externo da pilha: vê o status final, inclusive o 429 do limitador."""

    async def dispatch(self, request: Request, call_next) -> Response:
        inicio = time.perf_counter()
        resposta = await call_next(request)
        duracao = time.perf_counter() - inicio
        caminho = request.url.path
        if caminho == "/metrics":
            return resposta

        status = resposta.status_code
        rota = _modelo_da_rota(request, status)
        REGISTRO.incrementar(
            "specradar_http_requisicoes_total",
            metodo=request.method,
            rota=rota,
            status=str(status),
        )
        REGISTRO.observar("specradar_http_latencia_segundos", duracao, rota=rota)

        contexto = {
            "request_id": getattr(request.state, "request_id", None),
            "metodo": request.method,
            "rota": caminho,
            "status": status,
            "papel": _papel(request),
            "origem": pseudonimo_de_ip(get_remote_address(request)),
        }
        if status in (401, 403):
            REGISTRO.incrementar("specradar_eventos_seguranca_total", tipo="acesso_negado")
            _log.warning("seguranca.acesso_negado", **contexto)
        elif status == 429:
            REGISTRO.incrementar("specradar_eventos_seguranca_total", tipo="limite_excedido")
            _log.warning("seguranca.limite_excedido", **contexto)
        if request.method in METODOS_DE_ESCRITA and caminho.startswith(PREFIXOS_CRITICOS):
            REGISTRO.incrementar("specradar_eventos_seguranca_total", tipo="alteracao_critica")
            _log.info("auditoria.alteracao_critica", **contexto)
        return resposta


# ----------------------------------------------------------------------- 4. /metrics
def _rede_interna(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host == "testclient"
    return ip.is_loopback or ip.is_private


def _autorizado_para_metricas(request: Request) -> bool:
    esperado = os.environ.get("METRICS_TOKEN", "")
    enviado = request.headers.get("Authorization", "")
    if esperado and hmac.compare_digest(enviado.encode(), f"Bearer {esperado}".encode()):
        return True
    return not esperado and _rede_interna(request)


def _coletar_fila_de_jobs() -> None:
    from api.app.db import session_scope
    from api.app.models import Job
    from sqlalchemy import func
    from sqlmodel import select

    REGISTRO.limpar_gauge("specradar_jobs")
    with session_scope() as sessao:
        for status, total in sessao.exec(select(Job.status, func.count()).group_by(Job.status)):
            REGISTRO.definir("specradar_jobs", float(total), status=str(status))


def _coletar_eval(arquivo: Path) -> None:
    if not arquivo.exists():
        return
    # `aggregate` é o bloco do relatório de `pipeline/eval/run.py` (`python -m pipeline.cli eval`).
    dados_do_eval = json.loads(arquivo.read_text(encoding="utf-8"))
    metricas = dados_do_eval.get("aggregate") or dados_do_eval.get("metricas") or {}
    for nome, dados in metricas.items():
        valor = dados.get("valor") if isinstance(dados, dict) else None
        if isinstance(valor, int | float):
            REGISTRO.definir("specradar_eval_metrica", float(valor), metrica=nome)


def montar_metricas(app: FastAPI, arquivo_eval: Path) -> None:
    """`/metrics` fora da cota do rate limit — medido: sem isso o Prometheus, que raspa do
    mesmo IP a cada 15 s, disputava a cota de 60/min e recebia 429. A rota já é protegida
    por token e por rede, e não toca dado de negócio."""
    if "/metrics" not in rate_limit.ISENTAS:
        rate_limit.ISENTAS = (*rate_limit.ISENTAS, "/metrics")

    @app.get("/metrics", include_in_schema=False)
    @rate_limit.limiter.exempt
    def metricas(request: Request) -> Response:
        if not _autorizado_para_metricas(request):
            return PlainTextResponse("não encontrado\n", status_code=404)
        for nome, coletor in (
            ("jobs", _coletar_fila_de_jobs),
            ("eval", lambda: _coletar_eval(arquivo_eval)),
        ):
            try:
                coletor()
                REGISTRO.definir("specradar_coleta_metricas_falhou", 0.0, coletor=nome)
            except Exception as exc:  # noqa: BLE001 - métrica nunca derruba a rota
                REGISTRO.definir("specradar_coleta_metricas_falhou", 1.0, coletor=nome)
                _log.warning("metricas.coletor_falhou", coletor=nome, erro=type(exc).__name__)
        return PlainTextResponse(
            REGISTRO.exportar(), media_type="text/plain; version=0.0.4; charset=utf-8"
        )


# ---------------------------------------------------------------------------- fábrica
def criar_app_segura() -> FastAPI:
    from seguranca.ssrf import proteger_pipeline

    settings = get_settings()
    validar_configuracao(settings)
    corrigir_chave_do_limite()
    proteger_pipeline()
    app = create_app()
    app.add_middleware(EventosDeSegurancaMiddleware)
    montar_metricas(app, SOLUCAO / "reports" / "eval.json")
    _log.info(
        "seguranca.app_montada",
        producao=em_producao(),
        auth=settings.auth_enabled,
        rate_limit=settings.rate_limit_enabled,
    )
    return app


app = criar_app_segura()
