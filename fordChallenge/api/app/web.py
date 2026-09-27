"""Serve o build estático do `web/` em `/app`, com fallback de SPA.

Duas coisas que só se acertam pensando:

* **fallback de SPA:** `/app/consulta` não é arquivo — é rota do React Router. Sem o
  fallback, recarregar a página numa rota interna daria 404, que é o defeito mais comum de
  SPA servida por back-end. O fallback devolve o `index.html` para **qualquer** caminho
  sob `/app` que não seja arquivo existente;

* **o fallback NÃO cobre `/api`.** Um 404 de API tem de continuar sendo `problem+json`, e
  não HTML: um cliente que pede `/api/v1/nao-existe` e recebe uma página React não
  consegue nem descobrir que errou o endereço. Como o roteador é montado sob `/app`, isso
  já é verdade por construção — e há teste travando.

Quando `web/dist` não existe, a rota não é montada e `/app` responde 404 com uma
explicação de como construir. É o estado normal num clone recém-feito, e vale dizer o
comando em vez de deixar o desenvolvedor procurando.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

RAIZ = Path(__file__).resolve().parents[2]
DIST = RAIZ / "web" / "dist"
PREFIXO_WEB = "/app"

INSTRUCAO = (
    "O front-end nao esta construido. Rode: cd web && npm ci && npm run build "
    "(o build sai em web/dist e esta no .gitignore)."
)


class SpaStaticFiles(StaticFiles):
    """`StaticFiles` que devolve o `index.html` quando o caminho não é arquivo.

    É o que faz `/app/ficha/abc123` funcionar ao ser recarregado: o navegador pede aquele
    caminho ao servidor, e é o React Router — não o back-end — que sabe o que ele
    significa.
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except Exception:
            # Qualquer coisa que não seja arquivo servível cai no index. O
            # `StaticFiles` levanta `HTTPException(404)` aqui, e capturar largo mantém o
            # comportamento estável entre versões do Starlette.
            indice = DIST / "index.html"
            if indice.exists():
                return FileResponse(indice)
            raise


def montar_web(app: FastAPI) -> bool:
    """Monta o front-end em `/app`. Devolve `False` quando não há build.

    Chamada **depois** dos roteadores de API de propósito: montar antes faria o
    `StaticFiles` capturar caminhos que pertencem à API.
    """
    if not (DIST / "index.html").exists():

        @app.get(PREFIXO_WEB, include_in_schema=False)
        @app.get(f"{PREFIXO_WEB}/{{caminho:path}}", include_in_schema=False)
        async def _sem_build(_request: Request, caminho: str = "") -> JSONResponse:
            return JSONResponse(
                {
                    "type": "/problemas/front-end-ausente",
                    "title": "Front-end não construído",
                    "status": 404,
                    "detail": INSTRUCAO,
                    "instance": caminho,
                },
                status_code=404,
                media_type="application/problem+json",
            )

        return False

    app.mount(PREFIXO_WEB, SpaStaticFiles(directory=DIST, html=True), name="web")
    return True
