"""`/users` — administração de usuários. Só `admin`, pela matriz de `docs/12` §6.6.

Duas regras que não são óbvias e evitam um pé no próprio pé:

* **admin não se rebaixa nem se desativa.** Um sistema onde o último admin se remove por
  acidente fica sem administração, e a recuperação é mexer no banco à mão;
* **senha nunca volta**, nem em eco, nem em log, nem no `audit_log`. O que fica registrado
  é *que* o usuário foi criado, por quem, e com qual papel.

Rebaixar papel tem efeito **imediato**: `deps.usuario_atual` relê o usuário do banco a
cada requisição, então o access que já está na mão do rebaixado perde o poder na hora, sem
esperar o TTL.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlmodel import select

from api.app.deps import SessaoDep, UsuarioDep, exige_papel
from api.app.errors import ProblemaHTTP
from api.app.models import AuditLog, Role, User
from api.app.security import hash_de_senha

log = structlog.get_logger(__name__)
router = APIRouter(
    prefix="/users",
    tags=["usuarios"],
    dependencies=[Depends(exige_papel(Role.ADMIN))],
)

#: Tamanho mínimo de senha. `docs/08` pede 12; abaixo disso o argon2 não salva ninguém.
TAMANHO_MINIMO_DA_SENHA = 12


class UsuarioOut(BaseModel):
    id: str
    email: str
    nome: str
    role: str
    ativo: bool


class CriarUsuarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    nome: str = Field(min_length=1, max_length=120)
    senha: str = Field(min_length=TAMANHO_MINIMO_DA_SENHA, max_length=200)
    role: Role = Role.VENDEDOR


class AlterarUsuarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role | None = None
    ativo: bool | None = None
    nome: str | None = Field(default=None, min_length=1, max_length=120)


def _saida(usuario: User) -> UsuarioOut:
    return UsuarioOut(
        id=usuario.id,
        email=usuario.email,
        nome=usuario.nome,
        role=usuario.role,
        ativo=usuario.ativo,
    )


@router.get("", response_model=list[UsuarioOut], summary="Lista usuários")
async def listar(sessao: SessaoDep, incluir_inativos: bool = False) -> list[UsuarioOut]:
    consulta = select(User).order_by(User.email)
    if not incluir_inativos:
        consulta = consulta.where(User.ativo)
    return [_saida(u) for u in sessao.exec(consulta).all()]


@router.post("", response_model=UsuarioOut, status_code=201, summary="Cria usuário")
async def criar(corpo: CriarUsuarioIn, sessao: SessaoDep, admin: UsuarioDep) -> UsuarioOut:
    ja_existe = sessao.exec(select(User).where(User.email == str(corpo.email))).first()
    if ja_existe is not None:
        raise ProblemaHTTP(409, f"Já existe usuário com o e-mail {corpo.email}.")

    usuario = User(
        email=str(corpo.email),
        nome=corpo.nome,
        password_hash=hash_de_senha(corpo.senha),
        role=corpo.role.value,
        ativo=True,
    )
    sessao.add(usuario)
    sessao.flush()
    sessao.add(
        AuditLog(
            user_id=admin.id,
            ator_email=admin.email,
            acao="usuario_criado",
            alvo_tipo="user",
            alvo_id=usuario.id,
            # O papel entra; a senha, nunca.
            detalhe={"email": usuario.email, "role": usuario.role},
        )
    )
    sessao.commit()
    sessao.refresh(usuario)
    log.info("users.criado", alvo=usuario.id, role=usuario.role, por=admin.id)
    return _saida(usuario)


@router.patch("/{user_id}", response_model=UsuarioOut, summary="Altera papel, nome ou estado")
async def alterar(
    user_id: str, corpo: AlterarUsuarioIn, sessao: SessaoDep, admin: UsuarioDep
) -> UsuarioOut:
    usuario = sessao.get(User, user_id)
    if usuario is None:
        raise ProblemaHTTP(404, f"Usuário {user_id} não existe.")

    if usuario.id == admin.id and (
        (corpo.role is not None and corpo.role is not Role.ADMIN) or corpo.ativo is False
    ):
        raise ProblemaHTTP(
            409,
            "Um admin não pode rebaixar nem desativar a própria conta. Peça a outro "
            "admin — senão o sistema pode ficar sem administração.",
        )

    mudancas: dict[str, str] = {}
    if corpo.role is not None and corpo.role.value != usuario.role:
        mudancas["role"] = f"{usuario.role} -> {corpo.role.value}"
        usuario.role = corpo.role.value
    if corpo.ativo is not None and corpo.ativo != usuario.ativo:
        mudancas["ativo"] = f"{usuario.ativo} -> {corpo.ativo}"
        usuario.ativo = corpo.ativo
    if corpo.nome is not None and corpo.nome != usuario.nome:
        mudancas["nome"] = "alterado"
        usuario.nome = corpo.nome

    if mudancas:
        sessao.add(usuario)
        sessao.add(
            AuditLog(
                user_id=admin.id,
                ator_email=admin.email,
                acao="usuario_alterado",
                alvo_tipo="user",
                alvo_id=usuario.id,
                detalhe=mudancas,
            )
        )
        sessao.commit()
        sessao.refresh(usuario)
        log.info("users.alterado", alvo=usuario.id, mudancas=mudancas, por=admin.id)
    return _saida(usuario)
