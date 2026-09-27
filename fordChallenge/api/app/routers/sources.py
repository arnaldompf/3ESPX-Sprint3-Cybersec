"""`/sources` — as fontes de coleta. Só `admin`, pela matriz de `docs/12` §6.6.

Duas regras que este roteador impõe, e as duas são do ADR-7 (scraping educado):

* **`robots_ok` não é editável pela API.** Ele é o resultado de ler o `robots.txt` do
  domínio, e quem faz isso é `pipeline/fetch/http.py` na hora da coleta. Deixar um humano
  marcar `robots_ok=true` à mão criaria o caminho exato que a regra proíbe: alguém com
  pressa "libera" um domínio que o robots nega;
* **`bloqueada` é estado, não configuração.** Um 403 ou CAPTCHA marca a fonte como
  bloqueada com o motivo, e o campo volta a `ativa` quando uma coleta funciona — não
  quando alguém decide que deveria funcionar. Reativar à mão é permitido (o bloqueio pode
  ter sido temporário), mas `motivo` fica no histórico e a data de checagem é zerada.
"""

from __future__ import annotations

from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from api.app.deps import SessaoDep, UsuarioDep, exige_papel
from api.app.errors import ProblemaHTTP
from api.app.models import AuditLog, Role, Source, SourceStatus
from pipeline.schema import CONFIANCA_POR_TIER

log = structlog.get_logger(__name__)
router = APIRouter(
    prefix="/sources",
    tags=["fontes"],
    dependencies=[Depends(exige_papel(Role.ADMIN))],
)

#: Tipos de fonte que `docs/05` reconhece, com o tier de cada um.
TIPOS = (
    "site_oficial",
    "pdf_oficial",
    "configurador",
    "tabela_fipe",
    "pbe_inmetro",
    "midia",
    "forum",
)


class FonteOut(BaseModel):
    id: str
    url: str
    tipo: str
    tier: int
    dominio: str
    robots_ok: bool
    status: str
    motivo: str | None = None
    ultima_checagem_em: str | None = None
    confianca_base: float
    """A confiança que o tier desta fonte concede (`pipeline.schema`)."""


class CriarFonteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=8, max_length=1000)
    tipo: str
    tier: int = Field(ge=1, le=5)


class AlterarFonteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: int | None = Field(default=None, ge=1, le=5)
    status: SourceStatus | None = None
    motivo: str | None = Field(default=None, max_length=300)
    # `robots_ok` **não** entra: ver o docstring do módulo.


def _saida(fonte: Source) -> FonteOut:
    return FonteOut(
        id=fonte.id,
        url=fonte.url,
        tipo=fonte.tipo,
        tier=fonte.tier,
        dominio=fonte.dominio,
        robots_ok=fonte.robots_ok,
        status=fonte.status,
        motivo=fonte.motivo,
        ultima_checagem_em=(
            fonte.ultima_checagem_em.isoformat() if fonte.ultima_checagem_em else None
        ),
        confianca_base=CONFIANCA_POR_TIER.get(fonte.tier, 0.0),
    )


@router.get("", response_model=list[FonteOut], summary="Lista fontes")
async def listar(
    sessao: SessaoDep,
    status: SourceStatus | None = Query(default=None),
    dominio: str | None = Query(default=None),
) -> list[FonteOut]:
    consulta = select(Source).order_by(Source.dominio, Source.url)
    if status is not None:
        consulta = consulta.where(Source.status == status.value)
    if dominio:
        consulta = consulta.where(Source.dominio.ilike(f"%{dominio}%"))
    return [_saida(f) for f in sessao.exec(consulta).all()]


@router.post("", response_model=FonteOut, status_code=201, summary="Cadastra fonte")
async def criar(corpo: CriarFonteIn, sessao: SessaoDep, admin: UsuarioDep) -> FonteOut:
    """Cadastra com `robots_ok=False`: quem responde por isso é a coleta, não o cadastro."""
    if corpo.tipo not in TIPOS:
        raise ProblemaHTTP(422, f"Tipo {corpo.tipo!r} desconhecido. Aceitos: {', '.join(TIPOS)}.")
    dominio = (urlparse(corpo.url).hostname or "").lower()
    if not dominio:
        raise ProblemaHTTP(422, f"URL sem domínio reconhecível: {corpo.url!r}.")

    if sessao.exec(select(Source).where(Source.url == corpo.url)).first() is not None:
        raise ProblemaHTTP(409, f"Fonte já cadastrada: {corpo.url}")

    fonte = Source(
        url=corpo.url,
        tipo=corpo.tipo,
        tier=corpo.tier,
        dominio=dominio,
        # Nasce em `False` **sempre**. A verificação de robots.txt é da coleta.
        robots_ok=False,
        status=SourceStatus.ATIVA.value,
    )
    sessao.add(fonte)
    sessao.flush()
    sessao.add(
        AuditLog(
            user_id=admin.id,
            ator_email=admin.email,
            acao="fonte_criada",
            alvo_tipo="source",
            alvo_id=fonte.id,
            detalhe={"url": fonte.url, "tier": fonte.tier, "tipo": fonte.tipo},
        )
    )
    sessao.commit()
    sessao.refresh(fonte)
    log.info("sources.criada", source_id=fonte.id, dominio=dominio, por=admin.id)
    return _saida(fonte)


@router.patch("/{source_id}", response_model=FonteOut, summary="Altera tier ou estado da fonte")
async def alterar(
    source_id: str, corpo: AlterarFonteIn, sessao: SessaoDep, admin: UsuarioDep
) -> FonteOut:
    fonte = sessao.get(Source, source_id)
    if fonte is None:
        raise ProblemaHTTP(404, f"Fonte {source_id} não existe.")

    mudancas: dict[str, str] = {}
    if corpo.tier is not None and corpo.tier != fonte.tier:
        mudancas["tier"] = f"{fonte.tier} -> {corpo.tier}"
        fonte.tier = corpo.tier
    if corpo.status is not None and corpo.status.value != fonte.status:
        mudancas["status"] = f"{fonte.status} -> {corpo.status.value}"
        fonte.status = corpo.status.value
        if corpo.status is SourceStatus.ATIVA:
            # Reativação à mão: a data de checagem é zerada, porque ninguém coletou ainda.
            # Manter a antiga afirmaria que a fonte respondeu, e ela não respondeu.
            fonte.ultima_checagem_em = None
    if corpo.motivo is not None:
        mudancas["motivo"] = "alterado"
        fonte.motivo = corpo.motivo

    if mudancas:
        sessao.add(fonte)
        sessao.add(
            AuditLog(
                user_id=admin.id,
                ator_email=admin.email,
                acao="fonte_alterada",
                alvo_tipo="source",
                alvo_id=fonte.id,
                detalhe=mudancas,
            )
        )
        sessao.commit()
        sessao.refresh(fonte)
        log.info("sources.alterada", source_id=fonte.id, mudancas=mudancas, por=admin.id)
    return _saida(fonte)


@router.get("/{source_id}", response_model=FonteOut, summary="Uma fonte")
async def obter(source_id: str, sessao: SessaoDep) -> FonteOut:
    fonte = sessao.get(Source, source_id)
    if fonte is None:
        raise ProblemaHTTP(404, f"Fonte {source_id} não existe.")
    return _saida(fonte)
