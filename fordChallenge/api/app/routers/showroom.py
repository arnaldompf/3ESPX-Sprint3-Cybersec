"""`/comparisons/{id}/arguments` e `/showroom-sessions` — o ciclo do vendedor (WP-27).

**A sessão não aceita dado pessoal, e a recusa é estrutural.** `SessaoIn` tem
`extra="forbid"`: um `POST` com `nome_do_cliente` ou `telefone` recebe **422**, e não um
201 que grava o campo em silêncio. `docs/12` §6.5 pede sem PII, e a única forma de garantir
isso é o schema recusar — uma revisão de código não pega o dia em que alguém acrescentar o
campo.

**Escopo `proprios` para o vendedor** (`docs/12` §6.6): ele registra e lê **as próprias**
sessões. Não é privacidade do cliente (não há cliente aqui), é de trabalho: a taxa de
fechamento de um colega não é informação dele.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import select

from api.app.deps import SessaoDep, UsuarioDep, exige, exige_papel
from api.app.errors import ProblemaHTTP
from api.app.models import (
    MOTIVOS_DE_SESSAO,
    AuditLog,
    Role,
    ShowroomOutcome,
    ShowroomSession,
    Version,
)
from api.app.permissions import Acao, Escopo, escopo_de
from api.app.services import argument_service
from pipeline.fit.engine import NeedsProfile

log = structlog.get_logger(__name__)
router = APIRouter(tags=["showroom"])


# --------------------------------------------------------------------------- entradas
class ArgumentosIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    needs_profile: NeedsProfile | None = None
    permitir_llm: bool = True
    """Desligar força o template. Útil para a demo e para o teste de determinismo."""


class AprovacaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    textos: list[str] | None = None
    aprovado: bool = True
    travado: bool = False
    nota: str | None = Field(default=None, max_length=300)


class SessaoIn(BaseModel):
    """A sessão de showroom. **Sem PII, por construção** — ver o docstring do módulo."""

    model_config = ConfigDict(extra="forbid")

    ford_version_id: str
    competitor_version_ids: list[str] = Field(default_factory=list, max_length=6)
    needs_profile: NeedsProfile | None = None
    comparison_id: str | None = Field(default=None, max_length=200)
    dealer_id: str | None = Field(default=None, max_length=64)
    outcome: str = ShowroomOutcome.EM_ANDAMENTO.value
    motivos: list[str] = Field(default_factory=list)
    atributo_decisivo: str | None = Field(default=None, max_length=80)

    @field_validator("outcome")
    @classmethod
    def _desfecho_valido(cls, valor: str) -> str:
        validos = {o.value for o in ShowroomOutcome}
        if valor not in validos:
            raise ValueError(f"desfecho {valor!r} inválido. Válidos: {', '.join(sorted(validos))}.")
        return valor

    @field_validator("motivos")
    @classmethod
    def _motivos_do_vocabulario(cls, valor: list[str]) -> list[str]:
        desconhecidos = [m for m in valor if m not in MOTIVOS_DE_SESSAO]
        if desconhecidos:
            raise ValueError(
                f"motivo desconhecido: {', '.join(desconhecidos)}. "
                f"Válidos: {', '.join(MOTIVOS_DE_SESSAO)}."
            )
        return valor


class SessaoPatch(BaseModel):
    """O fecho da sessão: três toques (`docs/12` §6.5)."""

    model_config = ConfigDict(extra="forbid")

    outcome: str | None = None
    motivos: list[str] | None = None
    atributo_decisivo: str | None = Field(default=None, max_length=80)

    @field_validator("outcome")
    @classmethod
    def _desfecho_valido(cls, valor: str | None) -> str | None:
        if valor is None:
            return valor
        validos = {o.value for o in ShowroomOutcome}
        if valor not in validos:
            raise ValueError(f"desfecho {valor!r} inválido. Válidos: {', '.join(sorted(validos))}.")
        return valor

    @field_validator("motivos")
    @classmethod
    def _motivos_do_vocabulario(cls, valor: list[str] | None) -> list[str] | None:
        if valor is None:
            return valor
        desconhecidos = [m for m in valor if m not in MOTIVOS_DE_SESSAO]
        if desconhecidos:
            raise ValueError(
                f"motivo desconhecido: {', '.join(desconhecidos)}. "
                f"Válidos: {', '.join(MOTIVOS_DE_SESSAO)}."
            )
        return valor


# --------------------------------------------------------------------------- saídas
class SessaoOut(BaseModel):
    id: str
    dealer_id: str | None = None
    vendedor_id: str | None = None
    ford_version_id: str
    competitor_version_ids: list[str]
    needs_profile_json: dict[str, Any] | None = None
    comparison_id: str | None = None
    outcome: str
    motivos: list[str]
    atributo_decisivo: str | None = None
    is_simulated: bool
    created_at: str
    updated_at: str | None = None


def _out(linha: ShowroomSession) -> SessaoOut:
    return SessaoOut(
        id=linha.id,
        dealer_id=linha.dealer_id,
        vendedor_id=linha.vendedor_id,
        ford_version_id=linha.ford_version_id,
        competitor_version_ids=list(linha.competitor_version_ids or []),
        needs_profile_json=linha.needs_profile_json,
        comparison_id=linha.comparison_id,
        outcome=linha.outcome,
        motivos=list(linha.motivos or []),
        atributo_decisivo=linha.atributo_decisivo,
        is_simulated=bool(linha.is_simulated),
        created_at=linha.created_at.isoformat() if linha.created_at else "",
        updated_at=linha.updated_at.isoformat() if linha.updated_at else None,
    )


# --------------------------------------------------------------------------- argumentos
@router.post(
    "/comparisons/{comparison_id}/arguments",
    summary="3 pontos Ford + 1 do concorrente, cada um com evidência",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
async def gerar_argumentos(
    comparison_id: str, corpo: ArgumentosIn, sessao: SessaoDep
) -> dict[str, Any]:
    """O argumentário do par. `comparison_id` é `fordVersionId:competitorVersionId`.

    Sem `needs_profile`, o motor usa um perfil vazio — e aí **não há dimensão priorizada**,
    então o argumentário sai com os avisos dizendo isso em vez de escolher prioridades pelo
    usuário. Priorizar por conta própria seria decidir o que importa para um cliente que
    ninguém entrevistou.
    """
    try:
        ford_id, conc_id = argument_service.par_de(comparison_id)
    except argument_service.ParInvalido as exc:
        raise ProblemaHTTP(422, str(exc)) from exc

    for version_id in (ford_id, conc_id):
        if sessao.get(Version, version_id) is None:
            raise ProblemaHTTP(404, f"Versão {version_id!r} não existe.")
    if ford_id == conc_id:
        raise ProblemaHTTP(422, "O par não pode ter a mesma versão nas duas pontas.")

    perfil = corpo.needs_profile or NeedsProfile()
    resposta = argument_service.montar(
        sessao,
        ford_version_id=ford_id,
        competitor_version_id=conc_id,
        perfil=perfil,
        permitir_llm=corpo.permitir_llm,
    )
    log.info(
        "argumentos.gerados",
        comparison_id=comparison_id,
        gerado_por=resposta["gerado_por"],
        pontos=len(resposta["pontos"]),
    )
    return resposta


@router.put(
    "/comparisons/{comparison_id}/arguments",
    summary="Gestor aprova, edita ou trava o argumentário do par",
    dependencies=[Depends(exige_papel(Role.GESTOR, Role.ADMIN))],
)
async def aprovar_argumentos(
    comparison_id: str, corpo: AprovacaoIn, sessao: SessaoDep, gestor: UsuarioDep
) -> dict[str, Any]:
    """Aprovar dá o selo; **travar** faz a resposta ignorar template e reescrita.

    Travar sem texto não faz sentido e é recusado: seria "trave o que o sistema gerar", que
    é o contrário de travar.
    """
    try:
        ford_id, conc_id = argument_service.par_de(comparison_id)
    except argument_service.ParInvalido as exc:
        raise ProblemaHTTP(422, str(exc)) from exc
    for version_id in (ford_id, conc_id):
        if sessao.get(Version, version_id) is None:
            raise ProblemaHTTP(404, f"Versão {version_id!r} não existe.")
    if corpo.travado and not corpo.textos:
        raise ProblemaHTTP(
            422,
            "Travar exige `textos`: travar sem texto seria travar o que o sistema gerar, "
            "que é o contrário de travar.",
        )

    linha = argument_service.registrar_aprovacao(
        sessao,
        ford_version_id=ford_id,
        competitor_version_id=conc_id,
        textos=corpo.textos,
        aprovado=corpo.aprovado,
        travado=corpo.travado,
        usuario_id=gestor.id,
        nota=corpo.nota,
    )
    sessao.add(
        AuditLog(
            user_id=gestor.id,
            ator_email=gestor.email,
            acao="argumento_aprovado",
            alvo_tipo="argument_template",
            alvo_id=linha.id,
            detalhe={
                "par": comparison_id,
                "travado": corpo.travado,
                "textos": len(corpo.textos or []),
            },
        )
    )
    sessao.commit()
    return {
        "id": linha.id,
        "comparison_id": comparison_id,
        "aprovado": linha.aprovado,
        "travado": linha.travado,
        "textos": list(linha.textos or []),
        "selo": "aprovado pelo Product Marketing" if linha.aprovado else "",
    }


# --------------------------------------------------------------------------- sessões
@router.post(
    "/showroom-sessions",
    response_model=SessaoOut,
    status_code=201,
    summary="Registra uma sessão de showroom (sem PII)",
    dependencies=[Depends(exige(Acao.CRIAR_SESSAO_SHOWROOM))],
)
async def criar_sessao(corpo: SessaoIn, sessao: SessaoDep, usuario: UsuarioDep) -> SessaoOut:
    """Cria a sessão. O `vendedor_id` vem do **token**, não do corpo.

    Deixar o cliente informar quem atendeu permitiria registrar sessão no nome de outro
    vendedor, e a taxa de fechamento por pessoa deixaria de significar algo.
    """
    if sessao.get(Version, corpo.ford_version_id) is None:
        raise ProblemaHTTP(404, f"Versão Ford {corpo.ford_version_id!r} não existe.")
    for version_id in corpo.competitor_version_ids:
        if sessao.get(Version, version_id) is None:
            raise ProblemaHTTP(404, f"Concorrente {version_id!r} não existe.")

    linha = ShowroomSession(
        dealer_id=corpo.dealer_id,
        vendedor_id=usuario.id,
        ford_version_id=corpo.ford_version_id,
        competitor_version_ids=list(corpo.competitor_version_ids),
        needs_profile_json=(
            corpo.needs_profile.model_dump(mode="json") if corpo.needs_profile else None
        ),
        comparison_id=corpo.comparison_id,
        outcome=corpo.outcome,
        motivos=list(corpo.motivos),
        atributo_decisivo=corpo.atributo_decisivo,
        is_simulated=False,
    )
    sessao.add(linha)
    sessao.commit()
    sessao.refresh(linha)
    log.info("showroom.sessao_criada", sessao_id=linha.id, outcome=linha.outcome)
    return _out(linha)


@router.patch(
    "/showroom-sessions/{sessao_id}",
    response_model=SessaoOut,
    summary="Fecha a sessão: desfecho, motivos e atributo decisivo",
    dependencies=[Depends(exige(Acao.CRIAR_SESSAO_SHOWROOM))],
)
async def atualizar_sessao(
    sessao_id: str, corpo: SessaoPatch, sessao: SessaoDep, usuario: UsuarioDep
) -> SessaoOut:
    """Três toques. O vendedor só altera as **próprias** sessões (escopo `proprios`)."""
    linha = sessao.get(ShowroomSession, sessao_id)
    if linha is None:
        raise ProblemaHTTP(404, f"Sessão {sessao_id!r} não existe.")
    # O sinal de "só o seu" é o escopo de `ver_insights` na matriz de `docs/12` §6.6: o
    # vendedor tem escopo `proprios` lá. `criar_sessao_showroom` dá a ele escopo `todos`,
    # que é sobre **criar** — usá-lo aqui deixaria um vendedor reescrever o desfecho da
    # conversa de um colega, e a taxa de fechamento por pessoa deixaria de significar algo.
    if (
        escopo_de(usuario.role, Acao.VER_INSIGHTS) is Escopo.PROPRIOS
        and linha.vendedor_id != usuario.id
    ):
        raise ProblemaHTTP(403, "Esta sessão é de outro vendedor.")
    if linha.is_simulated:
        # Sessão de demonstração é imutável: editá-la faria o painel misturar dado semeado
        # com dado de uso, e o rótulo SIMULAÇÃO deixaria de dizer a verdade sobre a linha.
        raise ProblemaHTTP(422, "Sessão simulada não é editável (dado de demonstração).")

    if corpo.outcome is not None:
        linha.outcome = corpo.outcome
    if corpo.motivos is not None:
        linha.motivos = list(corpo.motivos)
    if corpo.atributo_decisivo is not None:
        linha.atributo_decisivo = corpo.atributo_decisivo
    linha.updated_at = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    sessao.add(linha)
    sessao.commit()
    sessao.refresh(linha)
    return _out(linha)


@router.get(
    "/showroom-sessions",
    response_model=list[SessaoOut],
    summary="As sessões registradas (vendedor vê só as próprias)",
    dependencies=[Depends(exige(Acao.VER_INSIGHTS))],
)
async def listar_sessoes(
    sessao: SessaoDep,
    usuario: UsuarioDep,
    incluir_simuladas: bool = Query(True, description="Vêm por padrão, sempre marcadas"),
    limite: int = Query(100, ge=1, le=500),
) -> list[SessaoOut]:
    """**Ler** é `ver_insights`, não `criar_sessao_showroom`.

    A diferença não é acadêmica: pela matriz de `docs/12` §6.6, o **analista não cria**
    sessão de showroom (ele não atende no salão) mas **lê** insights — e é ele quem precisa
    dos dados para o Product Marketing. Exigir a ação de criar para listar barraria
    justamente quem usa a informação.
    """
    consulta = select(ShowroomSession).order_by(ShowroomSession.created_at.desc())  # type: ignore[attr-defined]
    if escopo_de(usuario.role, Acao.VER_INSIGHTS) is Escopo.PROPRIOS:
        consulta = consulta.where(ShowroomSession.vendedor_id == usuario.id)
    if not incluir_simuladas:
        consulta = consulta.where(ShowroomSession.is_simulated == False)  # noqa: E712
    return [_out(linha) for linha in sessao.exec(consulta.limit(limite)).all()]
