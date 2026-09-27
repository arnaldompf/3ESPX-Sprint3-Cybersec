"""Erros da API em `application/problem+json` (RFC 9457).

Três invioláveis moram neste arquivo:

* **Nunca stack trace na resposta.** O traceback vai para o log estruturado; o cliente
  recebe `instance` — o request-id — e com ele o suporte acha o log. Traceback na resposta
  entrega caminho de arquivo, versão de biblioteca e nome de variável a quem pediu.
* **Nunca o corpo da requisição de volta.** Nem no 422: a resposta diz *quais* campos
  falharam e por quê, jamais o valor recebido. Eco de corpo é vazamento de dado do usuário
  (LGPD) e, num corpo mal-formado, é o corpo inteiro voltando dentro de `input`.
* **Formato único.** `{type, title, status, detail, instance, errors?}` de
  `docs/04_API_CONTRATO.md` para tudo: 404 do roteador, 422 do Pydantic, 429 do rate limit
  e 500 de bug. Cliente que sabe ler um erro sabe ler todos.
"""

from __future__ import annotations

import traceback
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.app.middleware import CABECALHO_REQUEST_ID, HEADERS_SEGURANCA, id_da_requisicao

TIPO_CONTEUDO = "application/problem+json"

#: `type` é URI de referência (RFC 9457 §3.1.1). Relativo de propósito: não existe host
#: público de documentação de erro do SpecRadar, e um URI absoluto inventado aqui seria um
#: link morto no contrato.
TIPOS: dict[int, str] = {
    400: "/problemas/corpo-invalido",
    401: "/problemas/nao-autenticado",
    403: "/problemas/papel-insuficiente",
    404: "/problemas/nao-encontrado",
    409: "/problemas/conflito",
    422: "/problemas/validacao",
    429: "/problemas/rate-limit",
    500: "/problemas/erro-interno",
}

TITULOS: dict[int, str] = {
    400: "Corpo inválido",
    401: "Não autenticado",
    403: "Papel insuficiente",
    404: "Não encontrado",
    409: "Conflito",
    422: "Falha de validação",
    429: "Limite de requisições excedido",
    500: "Erro interno",
}

#: Fixo, e sem nenhuma informação sobre a exceção: o cliente não tem o que fazer com o tipo
#: do erro interno, e quem tem (o time) acha tudo pelo request-id.
DETALHE_500 = (
    "Erro interno ao processar a requisição. Guarde o valor de `instance` e procure "
    "o log estruturado por ele."
)
DETALHE_422 = (
    "Um ou mais campos não passaram na validação. Os campos estão em `errors`; "
    "os valores enviados não são repetidos aqui."
)
DETALHE_429 = "Muitas requisições. Aguarde antes de tentar novamente."

_log = structlog.get_logger("specradar.api")


class CampoInvalido(BaseModel):
    """Um campo reprovado na validação, **sem** o valor que chegou."""

    campo: str
    regra: str
    mensagem: str


class Problema(BaseModel):
    """Envelope de erro de toda a API (RFC 9457 / docs/04).

    Declarado como modelo, e não montado só como dicionário, para aparecer em
    `components/schemas` do OpenAPI: quem gera cliente a partir do contrato precisa do
    formato do erro tanto quanto do formato do sucesso.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": TIPOS[404],
                "title": TITULOS[404],
                "status": 404,
                "detail": "Não encontrado",
                "instance": "0f7c1b9a4d8e4a2f9c3b5d6e7f801234",
            }
        }
    )

    type: str
    title: str
    status: int
    detail: str
    instance: str
    errors: list[CampoInvalido] | None = None


def _titulo(status: int) -> str:
    return TITULOS.get(status, "Erro")


def _tipo(status: int) -> str:
    return TIPOS.get(status, f"/problemas/http-{status}")


def resposta_problema(
    request: Request,
    status: int,
    detail: str,
    *,
    errors: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
    titulo: str | None = None,
) -> JSONResponse:
    """Monta a resposta de erro. Único ponto de saída de erro da API.

    Carimba `X-Request-ID` e os headers de segurança aqui e não só no middleware porque a
    resposta de 500 nasce no `ServerErrorMiddleware`, fora da cadeia: sem isto, o pior erro
    do sistema seria o único sem header de correlação nem de segurança.
    """
    request_id = id_da_requisicao(request)
    corpo: dict[str, Any] = {
        "type": _tipo(status),
        # O titulo padrao vem do status. O override existe para os casos em que o cliente
        # tem o que FAZER com a distincao: "Token expirado" pede renovacao, "Nao
        # autenticado" pede login. Os dois sao 401, e a diferenca esta no titulo
        # (criterio de aceite da WP-05).
        "title": titulo or _titulo(status),
        "status": status,
        "detail": detail,
        "instance": request_id,
    }
    if errors:
        corpo["errors"] = errors
    cabecalhos = {
        CABECALHO_REQUEST_ID: request_id,
        **HEADERS_SEGURANCA,
        **(headers or {}),
    }
    return JSONResponse(corpo, status_code=status, media_type=TIPO_CONTEUDO, headers=cabecalhos)


def _campo_invalido(erro: dict[str, Any]) -> dict[str, str]:
    """Converte um erro do Pydantic descartando o valor recebido.

    `input` (o valor literal que chegou) e `ctx` ficam fora. O cliente já sabe o que
    mandou; devolver isso transforma a mensagem de erro em eco do corpo — e num JSON
    quebrado o `input` é o corpo inteiro.
    """
    localizacao = ".".join(str(parte) for parte in erro.get("loc", ())) or "(corpo)"
    return {
        "campo": localizacao,
        "regra": str(erro.get("type", "invalido")),
        "mensagem": str(erro.get("msg", "")),
    }


class ProblemaHTTP(HTTPException):
    """`HTTPException` com **título** próprio, para o problem+json.

    O título padrão vem do status (`TITULOS`), e isso cobre quase tudo. A excecao é
    quando dois erros do mesmo status pedem reações diferentes de quem chamou: token
    expirado (renove) e token ausente (faça login) são os dois 401, e o cliente precisa
    distinguir sem interpretar texto livre.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        titulo: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.titulo = titulo


async def tratar_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """404 do roteador e todo `HTTPException` levantado de propósito pela aplicação."""
    assert isinstance(exc, StarletteHTTPException)  # garantido pelo registro do handler
    detalhe = exc.detail if isinstance(exc.detail, str) and exc.detail else _titulo(exc.status_code)
    # `exc.headers` preserva coisas como `WWW-Authenticate` no 401 (WP-05).
    return resposta_problema(
        request,
        exc.status_code,
        detalhe,
        headers=exc.headers,
        titulo=getattr(exc, "titulo", None),
    )


async def tratar_validacao(request: Request, exc: Exception) -> JSONResponse:
    """422 do Pydantic no mesmo envelope dos outros erros."""
    assert isinstance(exc, RequestValidationError)
    campos = [_campo_invalido(erro) for erro in exc.errors()]
    return resposta_problema(request, 422, DETALHE_422, errors=campos)


async def tratar_rate_limit(request: Request, exc: Exception) -> JSONResponse:
    """429 do slowapi. A política em si é da WP-05; o formato do erro é desta WP."""
    assert isinstance(exc, RateLimitExceeded)
    return resposta_problema(request, 429, DETALHE_429)


async def tratar_excecao_nao_tratada(request: Request, exc: Exception) -> JSONResponse:
    """Qualquer bug: 500 com detalhe fixo. O traceback fica **só** no log."""
    request_id = id_da_requisicao(request)
    _log.error(
        "http.erro_nao_tratado",
        request_id=request_id,
        metodo=request.method,
        rota=request.url.path,
        excecao=type(exc).__name__,
        traceback="".join(traceback.format_exception(exc)),
    )
    return resposta_problema(request, 500, DETALHE_500)


def registrar_handlers(app: FastAPI) -> None:
    """Pendura os quatro handlers no app.

    `StarletteHTTPException` e não `fastapi.HTTPException`: o 404 de rota inexistente é
    levantado pelo roteador do Starlette, e registrar só a subclasse do FastAPI deixaria
    justamente o critério de aceite do 404 caindo no handler default, em `application/json`.
    """
    app.add_exception_handler(StarletteHTTPException, tratar_http_exception)
    app.add_exception_handler(RequestValidationError, tratar_validacao)
    app.add_exception_handler(RateLimitExceeded, tratar_rate_limit)
    app.add_exception_handler(Exception, tratar_excecao_nao_tratada)


def _exemplo(
    status: int, detail: str, errors: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    corpo: dict[str, Any] = {
        "type": _tipo(status),
        "title": _titulo(status),
        "status": status,
        "detail": detail,
        "instance": "0f7c1b9a4d8e4a2f9c3b5d6e7f801234",
    }
    if errors:
        corpo["errors"] = errors
    return corpo


def _resposta_documentada(
    status: int, detail: str, errors: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    return {
        "model": Problema,
        "description": _titulo(status),
        "content": {TIPO_CONTEUDO: {"example": _exemplo(status, detail, errors)}},
    }


#: Respostas de erro documentadas em toda rota (`include_router(..., responses=...)`).
#: Os exemplos existem para que o `/docs` mostre o envelope real, e não um schema vazio.
RESPOSTAS_PADRAO: dict[int | str, dict[str, Any]] = {
    400: _resposta_documentada(400, "O corpo enviado não é JSON válido."),
    401: _resposta_documentada(401, "Token ausente, expirado ou inválido."),
    403: _resposta_documentada(403, "Seu papel não permite esta operação."),
    404: _resposta_documentada(404, "Recurso não encontrado."),
    422: _resposta_documentada(
        422,
        DETALHE_422,
        errors=[
            {
                "campo": "body.attributes",
                "regra": "too_long",
                "mensagem": "List should have at most 50 items",
            }
        ],
    ),
    429: _resposta_documentada(429, DETALHE_429),
    500: _resposta_documentada(500, DETALHE_500),
}
