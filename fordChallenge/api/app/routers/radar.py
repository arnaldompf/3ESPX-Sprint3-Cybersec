"""`/alerts`, `/internal-references` e `/equivalents` — o Change Radar (WP-25).

Substitui as rotas de alerta que a WP-06 deixou em `domain.py`, e acrescenta o que faz do
Radar o diferencial: **impacto**, **reação por papel** e **as duas evidências**.

Permissões, pela matriz de `docs/12` §6.6:

* **ver alertas** — analista, gestor, admin. O vendedor **não**: `docs/12` §6.1 diz
  "Vendedor não vê", e a razão é de produto — o Radar é ferramenta de inteligência
  competitiva, não de conversa de loja. O vendedor recebe o resultado disso no
  argumentário;
* **referência interna** — gestor e admin, porque `docs/12` §7 classifica o material
  interno da Ford como **dado sensível**;
* **equivalentes** — gestor e admin: dizer que a Hilux SRX Plus compete com a Ranger
  diesel topo é decisão comercial, não cálculo.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Any

import structlog
from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from api.app.deps import SessaoDep, UsuarioDep, exige, exige_papel
from api.app.errors import ProblemaHTTP
from api.app.models import (
    Alert,
    AlertType,
    AuditLog,
    CompetitiveEvent,
    Equivalent,
    Evidence,
    InternalReference,
    Role,
    Version,
)
from api.app.permissions import Acao
from api.app.services import materiality_service, spec_assembler
from pipeline.materiality import engine as materiality_engine
from pipeline.radar import internal, tipos

log = structlog.get_logger(__name__)
router = APIRouter(tags=["radar"])

#: Teto do arquivo de referência interna. Planilha de ficha técnica não passa disso, e um
#: teto explícito evita que um CSV de 200 MB vire uma transação de banco de meia hora.
TAMANHO_MAXIMO_KB = 512


# --------------------------------------------------------------------------- saídas
class EvidenciaOut(BaseModel):
    evidence_id: str
    source_url: str
    tier: int
    quote: str
    captured_at: str
    raw_value: str | None = None
    page: int | None = None


class AlertaOut(BaseModel):
    id: str
    type: str
    version_id: str | None = None
    field: str | None = None
    old: Any = None
    new: Any = None
    created_at: str
    lido: bool
    tratado: bool
    is_simulated: bool
    """A tela **tem** de mostrar o rótulo SIMULAÇÃO quando isto é verdadeiro."""


class AlertaDetalhadoOut(AlertaOut):
    """O alerta com o que o Radar promete: impacto, reação e as duas evidências."""

    impact: dict[str, Any] | None = None
    reactions: dict[str, str] | None = None
    evidence_before: EvidenciaOut | None = None
    evidence_after: EvidenciaOut | None = None


class MarcarAlertaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: bool | None = None
    tratado: bool | None = None


class ReferenciaOut(BaseModel):
    id: str
    version_id: str
    field: str
    value_json: Any = None
    raw_value: str | None = None
    documento: str | None = None
    criado_em: str


class ImportacaoOut(BaseModel):
    """O resultado do upload: o que entrou, o que ficou de fora, e os alertas gerados."""

    importadas: int
    recusadas: list[str]
    """Linha por linha, com o motivo. Recusa silenciosa faria o gestor achar que subiu."""
    alertas_gerados: int
    divergencias: list[dict[str, Any]]


class EquivalenteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_version_id: str
    ford_version_id: str | None = None
    """`null` afirma **sem equivalente direto** — diferente de não ter cadastrado."""
    nota: str | None = Field(default=None, max_length=300)


class EquivalenteOut(BaseModel):
    id: str
    competitor_version_id: str
    ford_version_id: str | None = None
    nota: str | None = None
    criado_em: str


def _iso(valor: dt.datetime | None) -> str:
    return valor.isoformat() if isinstance(valor, dt.datetime) else ""


def _evidencia_out(sessao, evidence_id: str | None) -> EvidenciaOut | None:
    if not evidence_id:
        return None
    linha = sessao.get(Evidence, evidence_id)
    if linha is None:
        return None
    return EvidenciaOut(
        evidence_id=linha.id,
        source_url=linha.source_url,
        tier=linha.tier,
        quote=linha.quote,
        captured_at=_iso(linha.captured_at),
        raw_value=linha.raw_value,
        page=linha.page,
    )


def _alerta_out(alerta: Alert) -> AlertaOut:
    return AlertaOut(
        id=alerta.id,
        type=alerta.type,
        version_id=alerta.version_id,
        field=alerta.field,
        old=alerta.old,
        new=alerta.new,
        created_at=_iso(alerta.created_at),
        lido=alerta.lido,
        tratado=alerta.tratado,
        is_simulated=bool(alerta.is_simulated),
    )


# ---------------------------------------------------------------------------- alertas
@router.get(
    "/alerts",
    response_model=list[AlertaOut],
    summary="Alertas, mais recentes primeiro",
    dependencies=[Depends(exige(Acao.VER_ALERTAS))],
)
async def listar_alertas(
    sessao: SessaoDep,
    since: dt.datetime | None = Query(default=None, description="ISO 8601"),
    type: AlertType | None = Query(default=None, description="filtra por tipo"),
    competitor: str | None = Query(
        default=None, description="`version_id` do concorrente (filtro de `docs/12` §6.1)"
    ),
    incluir_simulados: bool = Query(
        default=True,
        description="Simulados vêm por padrão, sempre marcados. Desligue para ver só o real.",
    ),
    limite: int = Query(default=100, ge=1, le=500),
) -> list[AlertaOut]:
    consulta = select(Alert).order_by(Alert.created_at.desc()).limit(limite)
    if since is not None:
        consulta = consulta.where(Alert.created_at >= since.replace(tzinfo=None))
    if type is not None:
        consulta = consulta.where(Alert.type == type.value)
    if competitor:
        consulta = consulta.where(Alert.version_id == competitor)
    if not incluir_simulados:
        # `is_(False)` e não `== False`: alerta antigo pode ter `null` na coluna, e a
        # migração 0003 normalizou os existentes para `0`.
        consulta = consulta.where(Alert.is_simulated.is_(False))
    return [_alerta_out(a) for a in sessao.exec(consulta).all()]


@router.get(
    "/alerts/{alert_id}",
    response_model=AlertaDetalhadoOut,
    summary="Um alerta com impacto, reações e as duas evidências",
    dependencies=[Depends(exige(Acao.VER_ALERTAS))],
)
async def obter_alerta(alert_id: str, sessao: SessaoDep) -> AlertaDetalhadoOut:
    """O impacto e as reações vêm **guardados**, não recalculados.

    Recalcular na leitura daria outro número meses depois — o impacto depende dos preços
    e da tabela de equivalentes **daquele dia**, e o histórico deixaria de ser histórico.
    """
    alerta = sessao.get(Alert, alert_id)
    if alerta is None:
        raise ProblemaHTTP(404, f"Alerta {alert_id} não existe.")

    base = _alerta_out(alerta)
    return AlertaDetalhadoOut(
        **base.model_dump(),
        impact=alerta.impact_json,
        reactions=alerta.reactions_json,
        evidence_before=_evidencia_out(sessao, alerta.evidence_before_id or alerta.evidence_id),
        evidence_after=_evidencia_out(sessao, alerta.evidence_after_id),
    )


@router.patch(
    "/alerts/{alert_id}",
    response_model=AlertaOut,
    summary="Marca alerta como lido ou tratado",
    dependencies=[Depends(exige(Acao.VER_ALERTAS))],
)
async def marcar_alerta(
    alert_id: str, corpo: MarcarAlertaIn, sessao: SessaoDep, usuario: UsuarioDep
) -> AlertaOut:
    """ "Lido" é de quem lê; "tratado" é de gestor.

    A distinção não é burocracia: "lido" é estado pessoal de caixa de entrada, e "tratado"
    afirma que **alguém resolveu** a divergência — e a equipe inteira passa a confiar
    nisso.
    """
    alerta = sessao.get(Alert, alert_id)
    if alerta is None:
        raise ProblemaHTTP(404, f"Alerta {alert_id} não existe.")
    if corpo.tratado is not None and usuario.role not in {Role.GESTOR.value, Role.ADMIN.value}:
        raise ProblemaHTTP(
            403,
            "Marcar um alerta como tratado é de gestor: a equipe passa a confiar que a "
            "divergência foi resolvida.",
        )

    if corpo.read is not None:
        alerta.lido = corpo.read
    if corpo.tratado is not None:
        alerta.tratado = corpo.tratado
        alerta.tratado_em = dt.datetime.now(dt.UTC).replace(tzinfo=None) if corpo.tratado else None
        sessao.add(
            AuditLog(
                user_id=usuario.id,
                ator_email=usuario.email,
                acao="alerta_tratado" if corpo.tratado else "alerta_reaberto",
                alvo_tipo="alert",
                alvo_id=alerta.id,
                detalhe={"tipo": alerta.type, "campo": alerta.field},
            )
        )
    sessao.add(alerta)
    sessao.commit()
    sessao.refresh(alerta)
    return _alerta_out(alerta)


# ----------------------------------------------------------------- referência interna
@router.get(
    "/internal-references",
    response_model=list[ReferenciaOut],
    summary="Referências internas (tier 0) — dado sensível",
    dependencies=[Depends(exige_papel(Role.GESTOR, Role.ADMIN))],
)
async def listar_referencias(
    sessao: SessaoDep, version_id: str | None = Query(default=None)
) -> list[ReferenciaOut]:
    consulta = select(InternalReference).order_by(InternalReference.field)
    if version_id:
        consulta = consulta.where(InternalReference.version_id == version_id)
    return [
        ReferenciaOut(
            id=r.id,
            version_id=r.version_id,
            field=r.field,
            value_json=r.value_json,
            raw_value=r.raw_value,
            documento=r.documento,
            criado_em=_iso(r.criado_em),
        )
        for r in sessao.exec(consulta).all()
    ]


def _resolver_version_id(sessao, texto: str) -> str | None:
    """`versao` do arquivo → `version_id`. Aceita o id direto ou o nome exato.

    Casamento por **nome exato** e não fuzzy: aqui o arquivo é do gestor, e adivinhar a
    versão de uma planilha interna colocaria a referência no veículo errado — o que
    geraria uma divergência falsa e mandaria alguém corrigir um material que estava certo.
    """
    if sessao.get(Version, texto) is not None:
        return texto
    achada = sessao.exec(select(Version).where(Version.nome_exato == texto)).first()
    return achada.id if achada is not None else None


@router.post(
    "/internal-references",
    response_model=ImportacaoOut,
    status_code=201,
    summary="Sobe CSV/JSON com os valores internos e gera os alertas de divergência",
    dependencies=[Depends(exige_papel(Role.GESTOR, Role.ADMIN))],
)
async def importar_referencias(
    sessao: SessaoDep,
    gestor: UsuarioDep,
    arquivo: UploadFile = File(..., description="CSV ou JSON com {versao, campo, valor}"),
) -> ImportacaoOut:
    """Cada linha vira `internal_references` (tier 0) e é comparada com a ficha pública.

    Divergência gera alerta `referencia_interna_divergente` **com as duas evidências** —
    a citação do material interno e o trecho da fonte pública.
    """
    dados = await arquivo.read()
    if len(dados) > TAMANHO_MAXIMO_KB * 1024:
        raise ProblemaHTTP(
            422, f"Arquivo acima do teto de {TAMANHO_MAXIMO_KB} KB para referência interna."
        )
    try:
        texto = dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Planilha salva do Excel brasileiro costuma sair em cp1252. Recusar por encoding
        # faria o gestor não conseguir subir o arquivo que ele tem.
        try:
            texto = dados.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise ProblemaHTTP(
                422, "Não foi possível ler o arquivo: salve como UTF-8 ou CSV do Excel."
            ) from exc

    try:
        resultado = internal.importar(texto)
    except internal.ReferenciaInvalida as exc:
        raise ProblemaHTTP(422, str(exc)) from exc

    documento = arquivo.filename or "referencia-interna"
    por_versao: dict[str, dict[str, Any]] = {}
    raws: dict[str, dict[str, str]] = {}
    recusadas = list(resultado.recusadas)

    for linha in resultado.linhas:
        version_id = _resolver_version_id(sessao, linha.versao)
        if version_id is None:
            recusadas.append(
                f"versão {linha.versao!r} não existe no catálogo (use o nome exato ou o id)"
            )
            continue

        existente = sessao.exec(
            select(InternalReference).where(
                InternalReference.version_id == version_id,
                InternalReference.field == linha.campo,
            )
        ).first()
        if existente is not None:
            existente.value_json = linha.valor
            existente.raw_value = linha.raw_value[:300]
            existente.documento = documento[:200]
            existente.enviado_por = gestor.id
            sessao.add(existente)
        else:
            sessao.add(
                InternalReference(
                    version_id=version_id,
                    field=linha.campo,
                    value_json=linha.valor,
                    raw_value=linha.raw_value[:300],
                    documento=documento[:200],
                    enviado_por=gestor.id,
                )
            )
        por_versao.setdefault(version_id, {})[linha.campo] = linha.valor
        raws.setdefault(version_id, {})[linha.campo] = linha.raw_value

    sessao.commit()

    # Divergências: compara com a ficha pública já montada pelo `spec_assembler`.
    divergencias: list[dict[str, Any]] = []
    gerados = 0
    for version_id, internos in por_versao.items():
        ficha = spec_assembler.montar(sessao, version_id)
        publicos: dict[str, Any] = {}
        evidencias: dict[str, str | None] = {}
        for caminho, campo in ficha.itens():
            nome = caminho.split(".", 1)[-1]
            publicos[nome] = campo.value
            evidencias[nome] = campo.evidences[0].evidence_id if campo.evidences else None

        for divergencia in internal.comparar_com_publico(
            internos, publicos, documento=documento, raws=raws.get(version_id, {})
        ):
            alerta_detectado = tipos.da_divergencia_interna(divergencia)
            sessao.add(
                Alert(
                    type=alerta_detectado.type,
                    version_id=version_id,
                    field=divergencia.campo,
                    old=divergencia.valor_interno,
                    new=divergencia.valor_publico,
                    evidence_after_id=evidencias.get(divergencia.campo),
                    impact_json=alerta_detectado.impacto.to_dict(),
                    reactions_json=(
                        alerta_detectado.reacoes.to_dict() if alerta_detectado.reacoes else None
                    ),
                    is_simulated=False,
                )
            )
            divergencias.append(divergencia.to_dict())
            gerados += 1

    sessao.add(
        AuditLog(
            user_id=gestor.id,
            ator_email=gestor.email,
            acao="referencia_interna_importada",
            alvo_tipo="internal_reference",
            detalhe={
                "documento": documento,
                "importadas": resultado.total - len(recusadas) + len(resultado.recusadas),
                "recusadas": len(recusadas),
                "alertas": gerados,
            },
        )
    )
    sessao.commit()
    log.info("radar.referencia_importada", documento=documento, alertas=gerados)

    return ImportacaoOut(
        importadas=sum(len(c) for c in por_versao.values()),
        recusadas=recusadas,
        alertas_gerados=gerados,
        divergencias=divergencias,
    )


@router.get(
    "/internal-references/modelo.csv",
    summary="O CSV de exemplo, para o gestor não adivinhar o formato",
    dependencies=[Depends(exige_papel(Role.GESTOR, Role.ADMIN))],
)
async def modelo_csv() -> dict[str, str]:
    """Devolve o cabeçalho e uma linha de exemplo. Formato descoberto por tentativa é
    formato que gera arquivo recusado."""
    saida = io.StringIO()
    escritor = csv.writer(saida)
    escritor.writerow(internal.COLUNAS)
    escritor.writerow(["Raptor 3.0 V6 Bi-turbo 4WD AT", "potencia_cv", "397"])
    escritor.writerow(["Raptor 3.0 V6 Bi-turbo 4WD AT", "modos_amortecedor", "Normal, Sport, Baja"])
    return {"csv": saida.getvalue(), "colunas": ", ".join(internal.COLUNAS)}


# ------------------------------------------------------------------------ equivalentes
@router.get(
    "/equivalents",
    response_model=list[EquivalenteOut],
    summary="Concorrente → versão Ford equivalente",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
async def listar_equivalentes(sessao: SessaoDep) -> list[EquivalenteOut]:
    linhas = sessao.exec(select(Equivalent).order_by(Equivalent.criado_em)).all()
    return [
        EquivalenteOut(
            id=e.id,
            competitor_version_id=e.competitor_version_id,
            ford_version_id=e.ford_version_id,
            nota=e.nota,
            criado_em=_iso(e.criado_em),
        )
        for e in linhas
    ]


@router.post(
    "/equivalents",
    response_model=EquivalenteOut,
    status_code=201,
    summary="Cadastra a equivalência (decisão do gestor)",
    dependencies=[Depends(exige_papel(Role.GESTOR, Role.ADMIN))],
)
async def criar_equivalente(
    corpo: EquivalenteIn, sessao: SessaoDep, gestor: UsuarioDep
) -> EquivalenteOut:
    if sessao.get(Version, corpo.competitor_version_id) is None:
        raise ProblemaHTTP(404, f"Versão {corpo.competitor_version_id} não existe.")
    if corpo.ford_version_id and sessao.get(Version, corpo.ford_version_id) is None:
        raise ProblemaHTTP(404, f"Versão {corpo.ford_version_id} não existe.")
    if corpo.ford_version_id == corpo.competitor_version_id:
        raise ProblemaHTTP(422, "Uma versão não é equivalente a si mesma.")

    ja = sessao.exec(
        select(Equivalent).where(
            Equivalent.competitor_version_id == corpo.competitor_version_id,
            Equivalent.ford_version_id == corpo.ford_version_id,
        )
    ).first()
    if ja is not None:
        raise ProblemaHTTP(409, "Esta equivalência já está cadastrada.")

    linha = Equivalent(
        competitor_version_id=corpo.competitor_version_id,
        ford_version_id=corpo.ford_version_id,
        nota=corpo.nota,
        definido_por=gestor.id,
    )
    sessao.add(linha)
    sessao.flush()
    sessao.add(
        AuditLog(
            user_id=gestor.id,
            ator_email=gestor.email,
            acao="equivalencia_definida",
            alvo_tipo="equivalent",
            alvo_id=linha.id,
            detalhe={
                "concorrente": corpo.competitor_version_id,
                "ford": corpo.ford_version_id,
                "nota": corpo.nota,
            },
        )
    )
    sessao.commit()
    sessao.refresh(linha)
    return EquivalenteOut(
        id=linha.id,
        competitor_version_id=linha.competitor_version_id,
        ford_version_id=linha.ford_version_id,
        nota=linha.nota,
        criado_em=_iso(linha.criado_em),
    )


# ------------------------------------------------------ materialidade (WP-34)
class RegraDisparadaOut(BaseModel):
    id: str
    peso: float
    descricao: str
    detalhe: str = ""


class EventoOut(BaseModel):
    """O alerta com a leitura: materialidade, regras e posição na fila."""

    id: str
    alert_id: str
    version_id: str | None = None
    comparable_version_id: str | None = None
    materiality: str
    #: O que a faixa significa, lido de `rules.yaml`. A tela não repete a frase.
    significado: str
    pontos: float
    rules_fired: list[RegraDisparadaOut]
    parity_flips: list[dict[str, Any]]
    priority_rank: int
    versao_das_regras: str | None = None
    is_simulated: bool
    criado_em: str
    #: O alerta em si, para a fila não precisar de uma segunda chamada por linha.
    alerta: AlertaOut


@router.get(
    "/events",
    response_model=list[EventoOut],
    summary="Fila de prioridade: alertas com materialidade, ALTA primeiro",
    dependencies=[Depends(exige(Acao.VER_ALERTAS))],
)
def listar_eventos(
    sessao: SessaoDep,
    priority: str | None = Query(
        None,
        description="Filtra por faixa: ALTA, MEDIA, BAIXA ou RUIDO",
    ),
    incluir_ruido: bool = Query(
        True,
        description=(
            "Ruído vem por padrão, no fim da fila. Desligar esconde o que não pede ação — "
            "e o alerta continua existindo, com evidência."
        ),
    ),
    incluir_simulados: bool = Query(True),
    # Os mesmos três filtros de `/alerts`, com os mesmos nomes: a fila **substitui** a
    # lista na tela do Radar, e uma fila que não filtra obrigaria a tela a manter duas
    # consultas para a mesma informação — com dois resultados possíveis para a pergunta
    # "quantos alertas de preço FIPE existem?".
    since: dt.datetime | None = Query(default=None, description="ISO 8601"),
    type: AlertType | None = Query(default=None, description="filtra por tipo"),
    competitor: str | None = Query(
        default=None, description="`version_id` do concorrente (filtro de `docs/12` §6.1)"
    ),
    limite: int = Query(100, ge=1, le=500),
) -> list[EventoOut]:
    """A fila, ordenada por `priority_rank` (menor primeiro).

    **Avalia o que ainda não foi avaliado.** Um alerta gravado antes da WP-34 não tem
    evento; a fila o avalia na hora em vez de sumir com ele — um alerta invisível porque
    ninguém rodou o motor seria pior que um alerta sem materialidade.
    """
    if priority is not None and priority not in materiality_engine.FAIXAS:
        raise ProblemaHTTP(
            422,
            f"Faixa {priority!r} não existe. Válidas: {', '.join(materiality_engine.FAIXAS)}.",
        )

    consulta = select(Alert)
    if since is not None:
        consulta = consulta.where(Alert.created_at >= since.replace(tzinfo=None))
    if type is not None:
        consulta = consulta.where(Alert.type == type.value)
    if competitor:
        consulta = consulta.where(Alert.version_id == competitor)
    alertas = sessao.exec(consulta).all()
    eventos: list[tuple[CompetitiveEvent, Alert]] = []
    for alerta in alertas:
        if not incluir_simulados and alerta.is_simulated:
            continue
        evento = materiality_service.evento_de(sessao, alerta)
        if priority is not None and evento.materiality != priority:
            continue
        if not incluir_ruido and evento.materiality == materiality_engine.RUIDO:
            continue
        eventos.append((evento, alerta))

    eventos.sort(key=lambda par: (par[0].priority_rank, par[0].criado_em))
    return [
        EventoOut(
            id=evento.id,
            alert_id=evento.alert_id,
            version_id=evento.version_id,
            comparable_version_id=evento.comparable_version_id,
            materiality=evento.materiality,
            significado=materiality_service.significado_de(evento.materiality),
            pontos=evento.pontos,
            rules_fired=[RegraDisparadaOut(**r) for r in (evento.rules_fired or [])],
            parity_flips=list(evento.parity_flips or []),
            priority_rank=evento.priority_rank,
            versao_das_regras=evento.versao_das_regras,
            is_simulated=bool(evento.is_simulated),
            criado_em=_iso(evento.criado_em),
            alerta=_alerta_out(alerta),
        )
        for evento, alerta in eventos[:limite]
    ]


@router.get(
    "/alerts/{alerta_id}/trace",
    summary='A cadeia do "Por quê?": ação, regra, mudança, campo, evidências, snapshots',
    dependencies=[Depends(exige(Acao.VER_ALERTAS))],
)
def trace_do_alerta(alerta_id: str, sessao: SessaoDep) -> dict[str, Any]:
    """A cadeia inteira, **sem elo vazio**.

    Onde o dado não existe, o elo diz o motivo em vez de sair em branco: um elo que aponta
    para o nada é pior que um elo ausente, porque parece prova.
    """
    alerta = sessao.get(Alert, alerta_id)
    if alerta is None:
        raise ProblemaHTTP(404, f"Alerta {alerta_id!r} não existe.")
    return materiality_service.trace(sessao, alerta)
