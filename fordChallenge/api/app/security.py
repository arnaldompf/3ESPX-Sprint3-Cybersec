"""Senhas (argon2id) e tokens (JWT HS256). O único lugar que assina e valida.

Decisões que moldam o módulo, todas de `docs/04` e `docs/08`:

* **argon2id**, não bcrypt: é o vencedor do PHC e o recomendado atual da OWASP para
  senha nova. O parâmetro fica no `PasswordHasher` padrão da biblioteca — mexer nele sem
  medir na máquina de produção é chute, e um chute para baixo é pior que o default;
* **`JWT_SECRET` com no mínimo 32 bytes, validado na partida**. Segredo curto em HS256 é
  força bruta viável, e um sistema que aceita segredo fraco em silêncio é pior que um que
  não sobe;
* **`jti` em todo token**, e o do refresh vive numa tabela. Sem `jti` não existe
  revogação: "trocar o segredo" derruba todas as sessões, e é a única alternativa;
* **a mensagem de erro de login não distingue** "usuário não existe" de "senha errada".
  A diferença é um oráculo de enumeração de contas.

O relógio entra por parâmetro (`agora`) em vez de `datetime.now()` direto: é o que permite
testar expiração sem congelar o tempo do processo — e um teste que mexe no relógio global
contamina o que roda depois dele.
"""

from __future__ import annotations

import datetime as dt
import secrets
from dataclasses import dataclass
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from api.app.config import get_settings

ALGORITMO = "HS256"
#: Tamanho mínimo do segredo, em bytes. `docs/04` pede ≥ 32.
TAMANHO_MINIMO_DO_SEGREDO = 32
#: Tipos de token. O `type` viaja no claim para um refresh não passar por access.
TipoDeToken = Literal["access", "refresh"]

_hasher = PasswordHasher()


class SegredoInvalido(RuntimeError):
    """`JWT_SECRET` ausente ou curto demais. Levanta na partida, não no primeiro login."""


class TokenInvalido(Exception):
    """Token que não passou na validação, com o motivo em `titulo` para o problem+json."""

    def __init__(self, detalhe: str, *, titulo: str = "Token inválido") -> None:
        super().__init__(detalhe)
        self.detalhe = detalhe
        self.titulo = titulo


class TokenExpirado(TokenInvalido):
    """Expirou. É erro separado porque o cliente **sabe o que fazer**: renovar."""

    def __init__(self) -> None:
        super().__init__("O token expirou. Renove com /auth/refresh.", titulo="Token expirado")


# ------------------------------------------------------------------------------ senha
def hash_de_senha(senha: str) -> str:
    """Hash argon2id. Nunca devolve nem registra a senha."""
    if not senha:
        raise ValueError("senha vazia não é hasheável")
    return _hasher.hash(senha)


def senha_confere(senha: str, hash_armazenado: str) -> bool:
    """Confere a senha. Hash corrompido é `False`, não exceção.

    Um hash inválido no banco não pode virar 500: isso diria ao atacante que aquele
    usuário existe e tem cadastro estranho. Falha de conferência é falha de login.
    """
    try:
        return _hasher.verify(hash_armazenado, senha)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def precisa_rehash(hash_armazenado: str) -> bool:
    """O hash foi feito com parâmetros mais fracos que os atuais?"""
    try:
        return _hasher.check_needs_rehash(hash_armazenado)
    except (InvalidHashError, ValueError):
        return False


# ------------------------------------------------------------------------------ token
def segredo() -> str:
    """O segredo de assinatura, validado. Levanta se ausente ou curto."""
    valor = get_settings().jwt_secret or ""
    if len(valor.encode()) < TAMANHO_MINIMO_DO_SEGREDO:
        raise SegredoInvalido(
            f"JWT_SECRET tem {len(valor.encode())} bytes; o mínimo é "
            f"{TAMANHO_MINIMO_DO_SEGREDO}. Gere com "
            '`python -c "import secrets; print(secrets.token_urlsafe(48))"`'
        )
    return valor


def novo_jti() -> str:
    """Identificador único do token, para revogação."""
    return secrets.token_urlsafe(16)


@dataclass(frozen=True)
class Claims:
    """O conteúdo verificado de um token."""

    sub: str
    role: str
    tipo: TipoDeToken
    jti: str
    exp: int
    iat: int

    @property
    def expira_em(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.exp, dt.UTC)


def criar_token(
    *,
    sub: str,
    role: str,
    tipo: TipoDeToken = "access",
    ttl: dt.timedelta | None = None,
    jti: str | None = None,
    agora: dt.datetime | None = None,
) -> tuple[str, Claims]:
    """Assina um token e devolve `(token, claims)`.

    `ttl` negativo é permitido de propósito: é como um teste produz um token expirado sem
    mexer no relógio do processo.
    """
    settings = get_settings()
    instante = agora or dt.datetime.now(dt.UTC)
    duracao = ttl
    if duracao is None:
        duracao = (
            dt.timedelta(minutes=settings.jwt_access_ttl_min)
            if tipo == "access"
            else dt.timedelta(days=settings.jwt_refresh_ttl_days)
        )
    claims = Claims(
        sub=sub,
        role=role,
        tipo=tipo,
        jti=jti or novo_jti(),
        exp=int((instante + duracao).timestamp()),
        iat=int(instante.timestamp()),
    )
    corpo: dict[str, Any] = {
        "sub": claims.sub,
        "role": claims.role,
        "type": claims.tipo,
        "jti": claims.jti,
        "exp": claims.exp,
        "iat": claims.iat,
    }
    return jwt.encode(corpo, segredo(), algorithm=ALGORITMO), claims


def ler_token(token: str, *, tipo_esperado: TipoDeToken | None = None) -> Claims:
    """Valida assinatura, expiração e tipo. Levanta `TokenInvalido` com o motivo.

    O `tipo_esperado` não é zelo: sem ele, um refresh (7 dias) serviria como access, e o
    TTL curto do access — que é a razão de ele existir — deixaria de valer.
    """
    try:
        corpo = jwt.decode(token, segredo(), algorithms=[ALGORITMO])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpirado() from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalido("Token malformado ou assinatura inválida.") from exc

    faltando = [c for c in ("sub", "role", "type", "jti", "exp", "iat") if c not in corpo]
    if faltando:
        raise TokenInvalido(f"Token sem os claims obrigatórios: {', '.join(faltando)}.")
    if tipo_esperado and corpo["type"] != tipo_esperado:
        raise TokenInvalido(
            f"Token de tipo {corpo['type']!r} onde se espera {tipo_esperado!r}.",
            titulo="Tipo de token inválido",
        )
    return Claims(
        sub=str(corpo["sub"]),
        role=str(corpo["role"]),
        tipo=corpo["type"],
        jti=str(corpo["jti"]),
        exp=int(corpo["exp"]),
        iat=int(corpo["iat"]),
    )
