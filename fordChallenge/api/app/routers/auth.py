"""`/auth` — login, refresh com rotação, e `/auth/me`.

O que este módulo faz de diferente do login de manual:

* **a resposta de falha é a mesma** para "e-mail não existe" e "senha errada", com o mesmo
  status e o mesmo texto. Distinguir é um oráculo de enumeração de contas: um atacante
  descobre quem trabalha na empresa sem acertar uma senha;
* **o refresh é rotacionado**: usar um refresh o revoga e emite outro. Refresh de vida
  longa que continua valendo depois de usado é credencial de longa duração disfarçada;
* **reuso de refresh já rotacionado revoga a família inteira.** É o sinal clássico de
  token vazado — o legítimo e o atacante disputam o mesmo `jti`, e o segundo a chegar
  denuncia o roubo. Revogar só o apresentado deixaria o ladrão com a cadeia nova;
* **`audit_log` grava login, falha de login e criação de usuário**, com o e-mail ao lado
  do `user_id` (auditoria tem de continuar legível depois de o usuário sumir).

O rate limit de 5/min por IP no login está aqui como decorador; o limite geral por usuário
autenticado está em `api/app/main.py`.

**Nesta fase `AUTH_ENABLED=false` é o padrão (D-204).** `montar()` então devolve um roteador
com **só** `/auth/me` — que responde quem é o papel declarado em `X-Role`, para a barra
lateral ter o que mostrar. Login, refresh e logout não são montados: sem autenticação não
há senha a digitar, e uma rota de login que não serve para nada continuaria anunciando no
`/openapi.json` uma porta que não existe. `AUTH_ENABLED=1` devolve o módulo inteiro.

A entrada sem senha do modo demonstração (`/auth/demo-login`, D-185) **foi removida**: ela
existia para a apresentação não parar numa tela de login, e agora não há tela de login.
"""

from __future__ import annotations

import datetime as dt

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlmodel import select

from api.app.config import get_settings
from api.app.deps import SessaoDep, UsuarioDep
from api.app.errors import ProblemaHTTP
from api.app.models import AuditLog, RefreshToken, User
from api.app.rate_limit import limiter
from api.app.security import (
    TokenInvalido,
    criar_token,
    hash_de_senha,
    ler_token,
    precisa_rehash,
    senha_confere,
)

log = structlog.get_logger(__name__)

#: A mesma frase para credencial inexistente e senha errada. **Não** especializar.
FALHA_DE_LOGIN = "E-mail ou senha inválidos."


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    senha: str = Field(min_length=1, max_length=200)


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1)


class TokensOut(BaseModel):
    """Par de tokens. `expires_in` em segundos, como manda o uso de OAuth2."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - nome do esquema OAuth2, nao segredo
    expires_in: int


class UsuarioOut(BaseModel):
    id: str
    email: str
    nome: str
    role: str
    ativo: bool


def _auditar(
    sessao,
    *,
    acao: str,
    usuario: User | None = None,
    email: str | None = None,
    detalhe: dict | None = None,
) -> None:
    """Grava a trilha. Nunca recebe senha, nem hash, nem token."""
    sessao.add(
        AuditLog(
            user_id=usuario.id if usuario else None,
            ator_email=(usuario.email if usuario else email),
            acao=acao,
            alvo_tipo="user",
            alvo_id=usuario.id if usuario else None,
            detalhe=detalhe,
        )
    )


def _emitir(sessao, usuario: User) -> TokensOut:
    """Emite o par e registra o `jti` do refresh, para poder revogá-lo depois."""
    access, claims_access = criar_token(sub=usuario.id, role=usuario.role, tipo="access")
    refresh, claims_refresh = criar_token(sub=usuario.id, role=usuario.role, tipo="refresh")
    sessao.add(
        RefreshToken(
            jti=claims_refresh.jti,
            user_id=usuario.id,
            expira_em=claims_refresh.expira_em.replace(tzinfo=None),
        )
    )
    return TokensOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=claims_access.exp - claims_access.iat,
    )


def _revogar_familia(sessao, user_id: str, *, motivo: str) -> int:
    """Revoga todos os refresh ativos do usuário. Devolve quantos."""
    ativos = sessao.exec(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revogado_em.is_(None)
        )
    ).all()
    agora = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    for linha in ativos:
        linha.revogado_em = agora
        linha.motivo_da_revogacao = motivo[:120]
        sessao.add(linha)
    return len(ativos)


async def login(request: Request, corpo: LoginIn, sessao: SessaoDep) -> TokensOut:
    """200 com o par de tokens; 401 com a **mesma** mensagem para qualquer falha."""
    usuario = sessao.exec(select(User).where(User.email == str(corpo.email))).first()

    senha_ok = usuario is not None and senha_confere(corpo.senha, usuario.password_hash)
    if usuario is None or not usuario.ativo or not senha_ok:
        # O motivo real vai para o log estruturado (o time precisa dele); a resposta, não.
        motivo = (
            "email_inexistente"
            if usuario is None
            else ("usuario_inativo" if not usuario.ativo else "senha_incorreta")
        )
        _auditar(
            sessao,
            acao="login_falhou",
            usuario=usuario if usuario is not None else None,
            email=str(corpo.email),
            detalhe={"motivo": motivo},
        )
        sessao.commit()
        log.info("auth.login_falhou", motivo=motivo)
        raise ProblemaHTTP(401, FALHA_DE_LOGIN, headers={"WWW-Authenticate": "Bearer"})

    if precisa_rehash(usuario.password_hash):
        # Parâmetros do argon2 subiram desde o cadastro. É o único momento em que a senha
        # em claro está disponível para re-hashear sem incomodar o usuário.
        usuario.password_hash = hash_de_senha(corpo.senha)

    usuario.ultimo_login_em = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    tokens = _emitir(sessao, usuario)
    _auditar(sessao, acao="login", usuario=usuario)
    sessao.add(usuario)
    sessao.commit()
    log.info("auth.login", user_id=usuario.id, role=usuario.role)
    return tokens


async def refresh(corpo: RefreshIn, sessao: SessaoDep) -> TokensOut:
    """Emite um par novo e **revoga** o refresh apresentado.

    Reuso de um refresh já rotacionado revoga a família inteira: é o sinal de token
    vazado, e nesse caso derrubar todas as sessões do usuário é a resposta certa.
    """
    try:
        claims = ler_token(corpo.refresh_token, tipo_esperado="refresh")
    except TokenInvalido as exc:
        raise ProblemaHTTP(401, exc.detalhe, titulo=exc.titulo) from exc

    linha = sessao.get(RefreshToken, claims.jti)
    if linha is None:
        raise ProblemaHTTP(401, "Refresh desconhecido. Faça login novamente.")
    if linha.revogado_em is not None:
        revogados = _revogar_familia(
            sessao, linha.user_id, motivo=f"reuso do refresh {claims.jti} ja rotacionado"
        )
        _auditar(
            sessao,
            acao="refresh_reusado",
            email=None,
            detalhe={"jti": claims.jti, "sessoes_revogadas": revogados},
        )
        sessao.commit()
        log.warning("auth.refresh_reusado", jti=claims.jti, revogados=revogados)
        raise ProblemaHTTP(
            401,
            "Este refresh já foi usado. Todas as sessões foram encerradas por segurança; "
            "faça login novamente.",
            titulo="Refresh reutilizado",
        )

    usuario = sessao.get(User, linha.user_id)
    if usuario is None or not usuario.ativo:
        raise ProblemaHTTP(401, "Credencial não corresponde a um usuário ativo.")

    tokens = _emitir(sessao, usuario)
    novo_jti = ler_token(tokens.refresh_token, tipo_esperado="refresh").jti
    linha.revogado_em = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    linha.motivo_da_revogacao = "rotacionado"
    linha.substituido_por = novo_jti
    sessao.add(linha)
    sessao.commit()
    log.info("auth.refresh", user_id=usuario.id)
    return tokens


async def logout(usuario: UsuarioDep, sessao: SessaoDep) -> None:
    """Revoga **todos** os refresh do usuário.

    Encerrar só a sessão atual exigiria o refresh no corpo, e quem faz logout normalmente
    tem só o access em mão. Entre pedir o refresh e derrubar tudo, derrubar tudo é o que
    o usuário espera de "sair".
    """
    revogados = _revogar_familia(sessao, usuario.id, motivo="logout")
    _auditar(sessao, acao="logout", usuario=usuario, detalhe={"sessoes_revogadas": revogados})
    sessao.commit()
    log.info("auth.logout", user_id=usuario.id, revogados=revogados)


async def me(usuario: UsuarioDep) -> UsuarioOut:
    return UsuarioOut(
        id=usuario.id,
        email=usuario.email,
        nome=usuario.nome,
        role=usuario.role,
        ativo=usuario.ativo,
    )


#: `login` decorado com o limite de 5/min, **uma vez por processo**.
_login_com_limite = None


def _entrada_de_login():
    """O `login` com o limite de `docs/04`, decorado uma vez só.

    Memoizado por bug medido. `limiter.limit(...)` **registra** o limite numa lista que o
    slowapi guarda pelo nome do endpoint; decorar a cada `create_app()` registra o mesmo
    limite de novo, e o slowapi passa a conferir e incrementar o contador uma vez por
    registro. A suíte monta dezenas de apps, e a sexta montagem fazia **um** login custar
    seis batidas: `/auth/login` respondia 429 na primeira tentativa de 318 testes, com a
    falha aparecendo no `setup` de fixtures a arquivos de distância da causa.
    """
    global _login_com_limite
    if _login_com_limite is None:
        _login_com_limite = limiter.limit(lambda: get_settings().rate_limit_login)(login)
    return _login_com_limite


def montar(auth_enabled: bool) -> APIRouter:
    """O roteador de `/auth` deste app — e só ele, montado a cada chamada.

    **Um `APIRouter` novo por chamada**, e não um singleton de módulo, pelo mesmo motivo
    que fazia o modo demonstração vazar: `create_app()` roda dezenas de vezes na suíte, e
    mutar um roteador de módulo faria a configuração do primeiro app valer para todos os
    seguintes — um teste com `AUTH_ENABLED=1` ligaria login para o resto da sessão.

    Com `auth_enabled=False` (o padrão desta fase, D-204) sai só `/auth/me`: a barra
    lateral precisa dizer quem está olhando, e quem está olhando é o papel de `X-Role`.
    Login, refresh e logout não existem nem no `/openapi.json` — o que não está montado
    não pode ser chamado nem descoberto.

    O limite de 5/min do login é aplicado **aqui**, e não como decorador de módulo: com
    `RATE_LIMIT_ENABLED=false` ele não entra, e o limite fica de fato fora do caminho de
    execução (D-206), em vez de continuar contando numa pilha que ninguém consulta.
    """
    roteador = APIRouter(prefix="/auth", tags=["autenticacao"])
    roteador.add_api_route(
        "/me",
        me,
        methods=["GET"],
        response_model=UsuarioOut,
        summary="Quem sou eu",
    )
    if not auth_enabled:
        return roteador

    roteador.add_api_route(
        "/login",
        _entrada_de_login() if get_settings().rate_limit_enabled else login,
        methods=["POST"],
        response_model=TokensOut,
        summary="Autentica e emite o par de tokens",
    )
    roteador.add_api_route(
        "/refresh",
        refresh,
        methods=["POST"],
        response_model=TokensOut,
        summary="Rotaciona o refresh",
    )
    roteador.add_api_route(
        "/logout",
        logout,
        methods=["POST"],
        status_code=204,
        summary="Encerra todas as sessões do usuário",
    )
    return roteador
