"""O limitador, num módulo só — para rota e app usarem a **mesma** instância.

`slowapi` guarda o estado no objeto `Limiter`. Criar um no `main.py` e outro no roteador
daria dois contadores independentes: o decorador da rota contaria numa conta e o
middleware noutra, e o limite de 5/min do login simplesmente não valeria.

A chave do limite é **o usuário quando há token, o IP quando não há**. `docs/04` pede
60/min por usuário autenticado e 5/min no login por IP, e as duas coisas não cabem numa
chave só: antes do login não existe usuário, e depois dele o IP é compartilhado por toda
a concessionária — um vendedor esgotaria a cota dos colegas.

Ler o `sub` do token aqui é **sem verificar assinatura** de propósito: é chave de
contador, não decisão de acesso. Um token forjado só consegue... competir por uma cota
alheia, e a autorização de verdade acontece depois, em `deps.py`. Verificar assinatura no
limitador colocaria criptografia no caminho de toda requisição, inclusive das barradas.
"""

from __future__ import annotations

import jwt
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from api.app.config import get_settings


def chave_do_limite(request: Request) -> str:
    """`user:<id>` quando há Bearer legível; `ip:<addr>` no resto."""
    autorizacao = request.headers.get("Authorization", "")
    if autorizacao.lower().startswith("bearer "):
        token = autorizacao[7:].strip()
        try:
            corpo = jwt.decode(token, options={"verify_signature": False})
        except jwt.InvalidTokenError:
            corpo = {}
        sub = corpo.get("sub")
        if sub:
            return f"user:{sub}"
    return f"ip:{get_remote_address(request)}"


#: A instância única, com o limite geral de `docs/04` (60/min) vindo do ambiente.
#:
#: O limite é um **callable** e não a string: `default_limits` é lido na construção, e o
#: `Limiter` aqui é criado no import do módulo — com a string, o valor de `.env` do
#: primeiro import valeria para sempre, e um teste que precisa de outro limite não teria
#: como pedir. Callable resolve por requisição, e `slowapi` suporta os dois.
limiter = Limiter(
    key_func=chave_do_limite,
    default_limits=[lambda: get_settings().rate_limit_default],
)


#: Rotas que **não** entram no limite geral. `/health` é sondado por orquestrador a cada
#: poucos segundos; limitá-lo faria o balanceador tirar a instância do ar por excesso de
#: zelo. `/docs` e `/openapi.json` são documentação, e já passam pelo middleware do
#: slowapi.
ISENTAS = ("/api/v1/health", "/docs", "/openapi.json", "/docs/oauth2-redirect")

#: O arquivo estático do web app **não** gasta a cota da API (D-187).
#:
#: Defeito medido pelo `web-smoke`: o limite de 60/min de `docs/04` é para a API, mas
#: `/app/assets/index-*.css` passava pela mesma conta. Cada carregamento de tela custa
#: dois arquivos além das chamadas de dado, e ao trocar de aba algumas vezes seguidas a
#: folha de estilo começava a voltar **429 `application/problem+json`** — o navegador
#: recusava aplicá-la ("not a supported stylesheet MIME type") e a tela ficava em branco.
#:
#: Ou seja: o limite que existe para proteger a API derrubava a tela. Arquivo estático
#: sai da conta; **tudo sob `/api` continua contando**, e é lá que está o custo real.
PREFIXO_ISENTO = "/app"


class LimiteGeralMiddleware(BaseHTTPMiddleware):
    """O limite geral de `docs/04` (60/min), aplicado por nós.

    Por que não o `SlowAPIMiddleware`: nesta versão do FastAPI os roteadores incluídos
    aparecem como `_IncludedRouter`, e o middleware do slowapi não consegue resolver o
    endpoint deles — resultado, ele limita `/docs` (rota Starlette pura) e **ignora**
    `/api/v1/*`, que é justamente o que precisa de limite. Medido: com 3/min, `/docs`
    devolvia 429 na 4ª e `/api/v1/health` respondia 200 cinco vezes.
    """

    async def dispatch(self, request: Request, call_next):
        caminho = request.url.path
        if caminho in ISENTAS or request.method == "OPTIONS":
            return await call_next(request)
        if caminho == PREFIXO_ISENTO or caminho.startswith(PREFIXO_ISENTO + "/"):
            return await call_next(request)

        item = parse(get_settings().rate_limit_default)
        chave = chave_do_limite(request)
        if not limiter.limiter.hit(item, "geral", chave):
            # Resposta **devolvida**, não exceção levantada. Exceção de dentro de um
            # `BaseHTTPMiddleware` não passa pela cadeia de handlers do FastAPI: o
            # `ServerErrorMiddleware` a captura e o cliente recebe **500** no lugar do
            # 429. Medido: `/auth/me` devolvia 500 na quarta requisição.
            #
            # Sai pelo mesmo `resposta_problema` de todo erro do projeto, então o corpo é
            # o mesmo `problem+json` do 429 do slowapi — quem consome não distingue de
            # onde o limite veio, e não deve.
            from api.app.errors import DETALHE_429, resposta_problema

            return resposta_problema(request, 429, DETALHE_429)
        return await call_next(request)
