"""Dependências de autenticação e autorização das rotas.

**Nesta fase o padrão é `AUTH_ENABLED=false` (D-204): a API não pede token, não devolve
401 e não devolve 403.** Quem chama declara o papel em `X-Role` e o papel serve só para
*filtrar* o que é por papel — o vendedor vê as sessões de showroom que ele registrou. O
que cada perfil vê na tela é decisão da tela (`web/src/lib/permissoes.ts`), que carrega a
mesma matriz de `docs/12` §6.6.

Com `AUTH_ENABLED=1` tudo abaixo volta a valer como em `docs/04`, e é por isso que o
código continua aqui inteiro, com os testes dele. Três coisas que valem explicar desse
caminho, porque nenhuma é a escolha automática:

* **usuário desativado dá 401, não 403.** 403 significa "você é você, mas não pode isto",
  e responder isso a uma conta desativada confirma que a conta existe. Desativado é
  "não autenticado", ponto;
* **a autorização pergunta pela ação**, via `api.app.permissions`,
  que carrega a matriz de `docs/12` §6.6. `exige(Acao.X)` em vez de
  `require_role("gestor")` — a matriz não é linear, e um papel numérico não a expressa
  (o vendedor abre sessão de showroom e o analista não);
* **o 403 diz quais papéis alcançam a ação.** Não é vazamento: a matriz é contrato
  público de `docs/12`, e a alternativa ("acesso negado") custa uma ida ao suporte.

`OAuth2PasswordBearer` está aqui só pelo que ele dá de graça no OpenAPI (o botão
*Authorize* do `/docs`). O fluxo é o de `docs/04`: JSON em `/auth/login`, não form-encoded.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from api.app.config import get_settings
from api.app.db import get_session
from api.app.errors import ProblemaHTTP
from api.app.models import Role, User
from api.app.papel import papel_do_pedido, usuario_do_papel
from api.app.permissions import Acao, Escopo, escopo_de, papeis_com
from api.app.security import Claims, TokenInvalido, ler_token

#: `auto_error=False`: quem monta o problem+json é este módulo, não o FastAPI — a resposta
#: de erro tem de sair no formato único de `api/app/errors.py`.
esquema_bearer = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

SessaoDep = Annotated[Session, Depends(get_session)]
TokenDep = Annotated[str | None, Depends(esquema_bearer)]


def autenticacao_ligada() -> bool:
    """`AUTH_ENABLED` do ambiente. Uma leitura só, para os testes poderem virar a chave."""
    return get_settings().auth_enabled


def claims_atuais(request: Request, token: TokenDep) -> Claims:
    """Valida o token do header e devolve os claims. 401 com o motivo no título."""
    if not token:
        raise ProblemaHTTP(
            401,
            "Requisição sem credencial. Envie `Authorization: Bearer <token>`.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return ler_token(token, tipo_esperado="access")
    except TokenInvalido as exc:
        raise ProblemaHTTP(
            401,
            exc.detalhe,
            titulo=exc.titulo,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


ClaimsDep = Annotated[Claims, Depends(claims_atuais)]


def usuario_atual(request: Request, sessao: SessaoDep, token: TokenDep) -> User:
    """Quem está chamando.

    Com autenticação **desligada** (o padrão desta fase): a identidade do papel declarado
    em `X-Role`, lida de `users`. Nenhum token é pedido e nenhum 401 sai daqui.

    Com autenticação **ligada**: o usuário do token, conferido **no banco** a cada
    requisição. Confiar só no claim `role` deixaria um rebaixamento de papel valer apenas
    depois de o access expirar — com TTL de 30 min, um ex-admin seguiria admin por meia
    hora, e a consulta é por chave primária.
    """
    if not autenticacao_ligada():
        return usuario_do_papel(sessao, papel_do_pedido(request))

    claims = claims_atuais(request, token)
    usuario = sessao.get(User, claims.sub)
    if usuario is None or not usuario.ativo:
        raise ProblemaHTTP(
            401,
            "Credencial não corresponde a um usuário ativo.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return usuario


UsuarioDep = Annotated[User, Depends(usuario_atual)]


def exige(acao: Acao):
    """Dependência que autoriza uma **ação** da matriz de `docs/12` §6.6.

    >>> @router.post("/extractions", dependencies=[Depends(exige(Acao.CRIAR_EXTRACOES))])

    Devolve o usuário, para a rota poder filtrar por escopo quando ele é `PROPRIOS`.

    Com `AUTH_ENABLED=false` ela **não nega**: devolve o usuário do papel declarado e
    deixa a rota filtrar. A matriz continua valendo onde ela filtra (`escopo_de`), que é
    o que separa "o vendedor vê as próprias sessões" de "o vendedor vê todas".
    """

    def verificador(usuario: UsuarioDep) -> User:
        if not autenticacao_ligada():
            return usuario
        if escopo_de(usuario.role, acao) is Escopo.NENHUM:
            permitidos = ", ".join(sorted(p.value for p in papeis_com(acao)))
            raise ProblemaHTTP(
                403,
                f"O papel {usuario.role!r} não tem permissão para {acao.value!r}. "
                f"Papéis com acesso: {permitidos}.",
            )
        return usuario

    return verificador


def exige_papel(*papeis: Role):
    """Autoriza por papel explícito, para rota que **é** de um papel, não de uma ação.

    Existe para o `/users` de admin, onde a ação e o papel coincidem por definição. Fora
    desse caso, prefira `exige(Acao...)`: papel é função, não nível.

    Como `exige`, não nega nada com `AUTH_ENABLED=false`.
    """
    permitidos = {Role(p).value for p in papeis}

    def verificador(usuario: UsuarioDep) -> User:
        if not autenticacao_ligada():
            return usuario
        if usuario.role not in permitidos:
            raise ProblemaHTTP(
                403,
                f"O papel {usuario.role!r} não alcança esta rota. "
                f"Papéis com acesso: {', '.join(sorted(permitidos))}.",
            )
        return usuario

    return verificador


def agora_utc() -> dt.datetime:
    """Instante atual em UTC. Um ponto só, para o teste poder substituir."""
    return dt.datetime.now(dt.UTC)
