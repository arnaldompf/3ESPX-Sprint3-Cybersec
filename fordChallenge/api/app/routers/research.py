"""`POST /research` e `GET /research/{id}/events` — o Pesquisador pela API.

**Assíncrono por natureza, e não por preferência de arquitetura.** Uma pesquisa leva até
três minutos: dez consultas, doze páginas a 1 req/s por domínio, uma chamada de LLM por
documento. Nenhuma requisição HTTP espera isso de pé. O `POST` devolve **202** com o id do
job, e a tela acompanha pelos eventos.

**`GET /events` serve os dois modos, e o cliente escolhe.** Com `Accept: text/event-stream`
ele responde SSE — que é o que a tela usa para o painel ao vivo. Sem isso, devolve JSON com
a trilha até agora, que é o que a CLI, o teste e quem audita depois precisam. Dois formatos
do **mesmo** objeto: se fossem dois contratos, a tela mostraria uma coisa e o registro
guardaria outra.

**Permissão: `criar_extracoes`.** Pesquisar é mais caro que consultar — sai para a internet
e gasta chamada de LLM — e por isso segue a mesma linha da extração na matriz de `docs/12`
§6.6: analista, gestor e admin. O vendedor **lê** a ficha que a pesquisa produziu; não
dispara uma.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from api.app.deps import SessaoDep, UsuarioDep, exige
from api.app.errors import ProblemaHTTP
from api.app.models import Job, JobStatus, ResearchEvent, ResearchRun
from api.app.permissions import Acao

router = APIRouter(tags=["pesquisador"])
identificacao_router = APIRouter(tags=["pesquisador"])


# ------------------------------------------------------------------- identificar
class IdentificarIn(BaseModel):
    """O que a pessoa digitou. `ano` sobrepõe o que estiver no texto."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"texto": "Triton", "ano": None}},
    )

    texto: str = Field(min_length=1, max_length=200)
    ano: int | None = Field(default=None, ge=1990, le=2100)


class OpcaoOut(BaseModel):
    valor: str
    detalhe: str = ""
    fontes: list[str] = Field(default_factory=list)
    tipo: str = "versao"
    marca: str = ""
    modelo: str = ""
    ano: int | None = None


class NoCatalogoOut(BaseModel):
    """O que já temos desta versão — para a conversa oferecer a ficha em vez de pesquisar."""

    version_id: str
    ano_modelo: int
    tem_ficha: bool
    campos_com_valor: int = 0
    #: A data mais recente entre os valores gravados e as cópias das fontes. É a linha
    #: sutil "de quando são os dados" que a tela mostra.
    coletado_em: str | None = None


class IdentificacaoOut(BaseModel):
    texto: str
    estado: str
    marca: str = ""
    modelo: str = ""
    versao: str = ""
    ano: int | None = None
    ano_origem: str = ""
    nome: str = ""
    pergunta: str = ""
    opcoes: list[OpcaoOut] = Field(default_factory=list)
    origem: str = ""
    consultas: list[str] = Field(default_factory=list)
    fontes: list[str] = Field(default_factory=list)
    motivo: str = ""
    uso: dict[str, Any] = Field(default_factory=dict)
    no_catalogo: NoCatalogoOut | None = None
    gasto_rodada: dict[str, Any] = Field(default_factory=dict)


def _no_catalogo(sessao: SessaoDep, ident) -> NoCatalogoOut | None:
    """A versão do catálogo que corresponde à identificação, se existir.

    Pelo `version_id` quando a identificação saiu do catálogo; senão, por marca, modelo,
    ano e o **nome canônico** da versão — que é como uma pesquisa anterior a teria gravado.
    """
    from sqlalchemy import func

    from api.app.models import Brand, Snapshot, SpecValue, VehicleModel, Version
    from pipeline.version_names import chave_de_versao

    versao_row = None
    if ident.version_id:
        versao_row = sessao.get(Version, ident.version_id)
    elif ident.marca and ident.modelo and ident.versao and ident.ano:
        candidatas = sessao.exec(
            select(Version)
            .join(VehicleModel, VehicleModel.id == Version.model_id)
            .join(Brand, Brand.id == VehicleModel.brand_id)
            .where(
                Brand.nome == ident.marca,
                VehicleModel.nome == ident.modelo,
                Version.ano_modelo == int(ident.ano),
            )
        ).all()
        procurada = chave_de_versao(ident.modelo, ident.versao)
        iguais = [v for v in candidatas if chave_de_versao(ident.modelo, v.nome_exato) == procurada]
        versao_row = iguais[0] if len(iguais) == 1 else None
    if versao_row is None:
        return None

    valores = sessao.exec(select(SpecValue).where(SpecValue.version_id == versao_row.id)).all()
    # **Campos distintos, não linhas.** Um campo `divergente` grava uma linha por valor
    # concorrente (é assim que a tela mostra "a fonte A diz X, a B diz Y"), e contar linhas
    # fazia a conversa anunciar "69 campos com valor" numa ficha que tem 55 campos.
    from api.app.services.spec_assembler import montar
    from pipeline.research.gaps import medir

    com_valor = medir(montar(sessao, versao_row.id)).com_valor
    datas = [v.atualizado_em for v in valores if v.atualizado_em is not None]
    ultima_captura = sessao.exec(
        select(func.max(Snapshot.captured_at)).where(Snapshot.version_id == versao_row.id)
    ).one()
    if ultima_captura is not None:
        datas.append(ultima_captura)
    coletado = max(datas).isoformat() if datas else None
    return NoCatalogoOut(
        version_id=versao_row.id,
        ano_modelo=versao_row.ano_modelo,
        tem_ficha=bool(valores),
        campos_com_valor=com_valor,
        coletado_em=coletado,
    )


@identificacao_router.post(
    "/research/identify",
    response_model=IdentificacaoOut,
    summary="De um texto solto ao veículo — perguntando quando há dúvida",
    description=(
        "Recebe o que a pessoa digitou (`Triton`, `S10 High`, `a picape nova da RAM`) e "
        "devolve o veículo identificado, **ou** a pergunta a fazer com as opções que as fontes "
        "sustentam. Gasta até três buscas e uma chamada de modelo pequeno; nenhuma das duas "
        "quando o catálogo já responde. Opção sem fonte nunca chega à resposta."
    ),
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
def identificar_veiculo(corpo: IdentificarIn, sessao: SessaoDep) -> IdentificacaoOut:
    from api.app.routers.catalog import linhas_do_catalogo
    from pipeline import llm
    from pipeline.research import identificar

    ident = identificar.identificar(
        corpo.texto,
        catalogo=linhas_do_catalogo(sessao),
        ano=corpo.ano,
        so_catalogo=os.environ.get("RESEARCH_ENABLED", "").strip().lower()
        not in {"1", "true", "sim"},
    )
    dados = ident.to_dict()
    dados.pop("version_id", None)
    dados.pop("tem_ficha", None)
    return IdentificacaoOut(
        **dados,
        no_catalogo=_no_catalogo(sessao, ident) if ident.estado == identificar.RESOLVIDO else None,
        gasto_rodada=llm.gasto_da_rodada(),
    )


class PesquisaIn(BaseModel):
    """O pedido. `extra="forbid"`: campo que não está aqui é erro, não é ignorado."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "marca": "Volkswagen",
                "modelo": "Amarok",
                "versao": "V6 Highline",
                "rodadas": 2,
                "paginas": 12,
                "segundos": 180,
            }
        },
    )

    #: Nenhum dos três é obrigatório sozinho: o edital pede "marca, modelo, versão + lista
    #: livre de atributos", não que os três primeiros sejam preenchidos em toda chamada.
    #: Quem só quer "potência e torque" de um veículo já identificado por `atributos` (ou
    #: por uma pesquisa anterior) não deveria ter de repetir marca/modelo.
    marca: str = Field(default="", max_length=80)
    modelo: str = Field(default="", max_length=120)
    versao: str = Field(default="", max_length=200)
    ano: int | None = Field(default=None, ge=1990, le=2100)
    #: Texto livre por item ("cavalos", "modos de volante"); resolvido para campo
    #: canônico em `criar()` antes de entrar na fila. Vazio = ficha inteira, como sempre.
    atributos: list[str] = Field(default_factory=list, max_length=30)
    #: O orçamento. Os padrões são os da demonstração de 15/09; quem chama pode apertar.
    rodadas: int = Field(default=2, ge=1, le=5)
    paginas: int = Field(default=12, ge=1, le=40)
    segundos: float = Field(default=180.0, ge=10.0, le=900.0)


class PesquisaAceita(BaseModel):
    """O 202. `events_url` vem pronta para a tela não ter de montar endereço."""

    run_id: str
    job_id: str
    status: str
    events_url: str


class ContinuarIn(BaseModel):
    """Tetos acumulados, incluindo a pesquisa anterior."""

    model_config = ConfigDict(extra="forbid")
    rodadas: int = Field(default=5, ge=1, le=5)
    paginas: int = Field(default=40, ge=1, le=40)
    segundos: float = Field(default=900.0, ge=10.0, le=900.0)


class EventoOut(BaseModel):
    ordem: int
    tipo: str
    texto: str
    etiqueta: str
    rodada: int
    decorrido: float
    dados: dict[str, Any] = Field(default_factory=dict)


class TrilhaOut(BaseModel):
    run_id: str
    status: str
    veiculo: str
    motivo_da_parada: str
    campos_com_valor: int
    campos_alvo: int
    paginas: int
    rodadas: int
    segundos: float
    #: A versão do catálogo em que a ficha foi gravada. `None` enquanto a pesquisa roda, e
    #: também quando ela acabou sem nada para gravar — `erro` diz por quê.
    version_id: str | None = None
    tokens: int = 0
    custo_brl: float = 0.0
    erro: str | None = None
    continuacao_disponivel: bool = False
    eventos: list[EventoOut]


def _run_ou_404(sessao: SessaoDep, run_id: str) -> ResearchRun:
    linha = sessao.get(ResearchRun, run_id)
    if linha is None:
        raise ProblemaHTTP(
            status_code=404,
            detail="Não há pesquisa com este identificador.",
            titulo="Pesquisa não encontrada",
        )
    return linha


def _resolver_atributos(atributos: list[str], *, marca: str) -> list[str]:
    """Texto livre -> campos canônicos, na ordem pedida, sem repetir e sem inventar.

    Termo sem match aceitável (`resolve_attribute` devolve `None`) é descartado aqui: a
    pesquisa vai atrás dos campos que reconhece, e a extração livre (`extras.<slug>`)
    continua sendo o caminho do texto que a ontologia não sabe nomear — este filtro só
    decide **o que pedir ao pesquisador**, não o que o extrator aceita depois.
    """
    from pipeline import ontology

    vistos: list[str] = []
    for texto in atributos:
        campo, _score = ontology.resolve_attribute(texto, marca=marca or None)
        if campo and campo not in vistos:
            vistos.append(campo)
    return vistos


@router.post(
    "/research",
    status_code=202,
    response_model=PesquisaAceita,
    summary="Pesquisar um veículo que não está no catálogo",
    description=(
        "Enfileira uma pesquisa e responde **202** com o id. Uma pesquisa leva até três "
        "minutos; acompanhe por `GET /research/{id}/events`, que fala SSE quando o "
        "`Accept` pede e JSON quando não pede."
    ),
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
def criar(corpo: PesquisaIn, sessao: SessaoDep, usuario: UsuarioDep) -> PesquisaAceita:
    linha = ResearchRun(
        marca=corpo.marca.strip(),
        modelo=corpo.modelo.strip(),
        versao=corpo.versao.strip(),
        status="pendente",
    )
    sessao.add(linha)
    sessao.flush()

    # A pesquisa roda no worker, como a extração e o relatório. O caminho é o mesmo, e é
    # deliberado: um segundo mecanismo de fila seria um segundo lugar para um job travar.
    job = Job(
        tipo="research",
        status=JobStatus.PENDENTE.value,
        payload={
            "run_id": linha.id,
            "marca": linha.marca,
            "modelo": linha.modelo,
            "versao": linha.versao,
            "ano": corpo.ano,
            "atributos": _resolver_atributos(corpo.atributos, marca=linha.marca),
            "rodadas": corpo.rodadas,
            "paginas": corpo.paginas,
            "segundos": corpo.segundos,
            "pedido_por": getattr(usuario, "id", ""),
        },
    )
    sessao.add(job)
    sessao.commit()
    sessao.refresh(linha)

    return PesquisaAceita(
        run_id=linha.id,
        job_id=job.id,
        status=linha.status,
        events_url=f"/api/v1/research/{linha.id}/events",
    )


@router.get(
    "/research/{run_id}",
    response_model=TrilhaOut,
    summary="O estado de uma pesquisa",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
def ver(run_id: str, sessao: SessaoDep) -> TrilhaOut:
    return _montar(sessao, _run_ou_404(sessao, run_id))


def _job_do_run(sessao, run_id: str) -> Job | None:
    return sessao.exec(
        select(Job).where(Job.tipo == "research", Job.payload["run_id"].as_string() == run_id)
    ).first()


def _pode_continuar(sessao, linha: ResearchRun) -> bool:
    import json

    from pipeline.research.checkpoint import job_path

    if linha.status not in {"concluida", "falhou"}:
        return False
    job = _job_do_run(sessao, linha.id)
    if not job or (job.payload or {}).get("continuation_job_id"):
        return False
    payload = job.payload or {}
    if not payload.get("ano"):
        return False
    try:
        saved = json.loads(job_path(job.id).read_text(encoding="utf-8"))
        spent = saved.get("budget_spent", {})
        return (
            float(spent.get("decorrido", 0)) < 900
            and int(spent.get("rodadas_gastas", 0)) < 5
            and int(spent.get("paginas_gastas", 0)) < 40
        )
    except (ValueError, OSError):
        return False


@router.post(
    "/research/{run_id}/continue",
    status_code=202,
    response_model=PesquisaAceita,
    summary="Continuar a pesquisa aproveitando as fontes já processadas",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
def continuar(
    run_id: str, corpo: ContinuarIn, sessao: SessaoDep, usuario: UsuarioDep
) -> PesquisaAceita:
    import json

    from sqlalchemy import update

    from pipeline.research.checkpoint import job_path, load
    from pipeline.research.planner import Alvo

    linha = _run_ou_404(sessao, run_id)
    # A escrita serializa cliques concorrentes em SQLite e bloqueia a linha em PostgreSQL.
    sessao.exec(
        update(ResearchRun).where(ResearchRun.id == run_id).values(status=ResearchRun.status)
    )
    sessao.expire_all()
    linha = _run_ou_404(sessao, run_id)
    anterior = _job_do_run(sessao, run_id)
    if anterior is None or linha.status not in {"concluida", "falhou"}:
        raise ProblemaHTTP(status_code=409, detail="A pesquisa ainda não pode ser retomada.")
    payload = anterior.payload or {}
    existente = sessao.get(Job, payload.get("continuation_job_id", ""))
    if existente is not None:
        child_run_id = existente.payload["run_id"]
        return PesquisaAceita(
            run_id=child_run_id,
            job_id=existente.id,
            status=existente.status,
            events_url=f"/api/v1/research/{child_run_id}/events",
        )
    if not payload.get("ano"):
        raise ProblemaHTTP(status_code=409, detail="Falta o ano-modelo confirmado para retomar.")
    target = Alvo(marca=linha.marca, modelo=linha.modelo, versao=linha.versao, ano=payload["ano"])
    try:
        saved = load(str(job_path(anterior.id)), target)
    except (ValueError, OSError):
        raise ProblemaHTTP(
            status_code=409, detail="O checkpoint não é compatível com esta pesquisa."
        ) from None
    if saved is None:
        raise ProblemaHTTP(status_code=409, detail="Esta pesquisa não tem checkpoint disponível.")
    spent = saved.get("budget_spent", {})
    if (
        corpo.segundos <= float(spent.get("decorrido", 0))
        or corpo.paginas <= int(spent.get("paginas_gastas", 0))
        or corpo.rodadas <= int(spent.get("rodadas_gastas", 0))
    ):
        raise ProblemaHTTP(status_code=409, detail="O orçamento acumulado já foi consumido.")
    nova_linha = ResearchRun(
        marca=linha.marca, modelo=linha.modelo, versao=linha.versao, status="pendente"
    )
    sessao.add(nova_linha)
    sessao.flush()
    job = Job(
        tipo="research",
        status=JobStatus.PENDENTE.value,
        payload={
            "run_id": nova_linha.id,
            "marca": linha.marca,
            "modelo": linha.modelo,
            "versao": linha.versao,
            "ano": payload["ano"],
            **corpo.model_dump(),
            "pedido_por": getattr(usuario, "id", ""),
            "continued_from": run_id,
        },
    )
    # Cada continuação tem seu arquivo; o checkpoint anterior permanece auditável.
    path = job_path(job.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    anterior.payload = {**payload, "continuation_job_id": job.id}
    sessao.add(anterior)
    sessao.add(job)
    sessao.commit()
    return PesquisaAceita(
        run_id=nova_linha.id,
        job_id=job.id,
        status=nova_linha.status,
        events_url=f"/api/v1/research/{nova_linha.id}/events",
    )


@router.get(
    "/research/{run_id}/events",
    summary="A trilha da pesquisa — SSE ou JSON, conforme o `Accept`",
    description=(
        "Com `Accept: text/event-stream`, transmite os eventos conforme acontecem (é o que "
        "o painel ao vivo usa). Sem isso, devolve a trilha até agora em JSON. **O mesmo "
        "objeto nos dois formatos**: o que a tela mostra é o que fica registrado."
    ),
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
def eventos(run_id: str, sessao: SessaoDep, request: Request):
    linha = _run_ou_404(sessao, run_id)
    if "text/event-stream" in (request.headers.get("accept") or ""):
        return StreamingResponse(
            _transmitir(sessao, linha.id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                # Sem isto, um proxy que compre buffer segura a trilha inteira e o painel
                # ao vivo vira um painel que aparece pronto no fim.
                "X-Accel-Buffering": "no",
            },
        )
    return _montar(sessao, linha)


def _eventos_de(sessao: SessaoDep, run_id: str, depois_de: int = -1) -> list[ResearchEvent]:
    return list(
        sessao.exec(
            select(ResearchEvent)
            .where(ResearchEvent.run_id == run_id, ResearchEvent.ordem > depois_de)
            .order_by(ResearchEvent.ordem)
        )
    )


def _montar(sessao: SessaoDep, linha: ResearchRun) -> TrilhaOut:
    return TrilhaOut(
        run_id=linha.id,
        status=linha.status,
        veiculo=f"{linha.marca} {linha.modelo} {linha.versao}".strip(),
        motivo_da_parada=linha.motivo_da_parada,
        campos_com_valor=linha.campos_com_valor,
        campos_alvo=linha.campos_alvo,
        paginas=linha.paginas,
        rodadas=linha.rodadas,
        segundos=linha.segundos,
        version_id=linha.version_id,
        tokens=linha.tokens,
        custo_brl=linha.custo_brl,
        erro=linha.erro,
        continuacao_disponivel=_pode_continuar(sessao, linha),
        eventos=[
            EventoOut(
                ordem=e.ordem,
                tipo=e.tipo,
                texto=e.texto,
                etiqueta=e.etiqueta,
                rodada=e.rodada,
                decorrido=e.decorrido,
                dados=e.dados or {},
            )
            for e in _eventos_de(sessao, linha.id)
        ],
    )


#: De quanto em quanto tempo o SSE procura evento novo.
#:
#: Um segundo. A pesquisa produz um punhado de eventos por segundo no pico; consultar mais
#: rápido só gastaria banco, e mais devagar faria o painel parecer travado — que é
#: exatamente a sensação que ele existe para evitar.
INTERVALO_DO_SSE = 1.0

#: Teto de vida da conexão. Quinze segundos acima do orçamento máximo de uma pesquisa.
TETO_DO_SSE = 915.0


def _transmitir(sessao: SessaoDep, run_id: str):
    """Gerador do `text/event-stream`. Envia o que ainda não foi enviado, e para no fim.

    Reconexão é por `ordem`: o cliente que cair volta e recebe tudo — a trilha é curta
    (algumas dezenas de eventos) e reenviar é mais simples, e mais confiável, do que
    guardar cursor de sessão.
    """
    import json
    import time

    ultima = -1
    inicio = time.monotonic()
    while True:
        for evento in _eventos_de(sessao, run_id, ultima):
            ultima = evento.ordem
            corpo = json.dumps(
                {
                    "ordem": evento.ordem,
                    "tipo": evento.tipo,
                    "texto": evento.texto,
                    "etiqueta": evento.etiqueta,
                    "rodada": evento.rodada,
                    "decorrido": evento.decorrido,
                    "dados": evento.dados or {},
                },
                ensure_ascii=False,
            )
            yield f"event: {evento.tipo}\ndata: {corpo}\n\n"
            if evento.tipo == "fim":
                return

        linha = sessao.get(ResearchRun, run_id)
        if linha is not None and linha.status in {"concluida", "falhou"}:
            # O run acabou e não sobrou evento: pode ter falhado antes do `fim`.
            yield f'event: fim\ndata: {{"tipo":"fim","texto":"{linha.status}"}}\n\n'
            return
        if time.monotonic() - inicio > TETO_DO_SSE:
            yield 'event: fim\ndata: {"tipo":"fim","texto":"tempo de conexão esgotado"}\n\n'
            return

        sessao.rollback()  # solta a transação antes de dormir, senão o SQLite trava
        time.sleep(INTERVALO_DO_SSE)


def linha_de_evento(run_id: str, evento) -> ResearchEvent:
    """Um `Evento` da trilha como linha de `research_events`. O worker e o `gravar` usam a
    mesma função: duas construções divergiriam justamente no campo que ninguém olha."""
    tipo = getattr(evento.tipo, "value", evento.tipo)
    return ResearchEvent(
        run_id=run_id,
        ordem=evento.ordem,
        tipo=str(tipo),
        texto=evento.texto[:1000],
        etiqueta=evento.etiqueta,
        rodada=evento.rodada,
        decorrido=evento.decorrido,
        dados=evento.dados,
    )


def gravar(sessao, run_id: str, resultado, *, gravacao=None) -> None:
    """Fecha o run: grava o que **ainda não** está na trilha e o estado final, num commit.

    Desde 13/09/2026 os eventos chegam à tabela enquanto a pesquisa acontece (o worker os
    grava um a um, por uma sessão própria). Aqui entra o que faltou — o `fim` sempre, e
    qualquer passo que a escrita ao vivo tenha perdido — deduplicado por `ordem`.

    **O `fim` sai no mesmo commit de `status="concluida"` e de `version_id`.** Quem faz
    polling e vê o `fim` pode ir buscar a versão gravada sem corrida: se os dois fossem
    commits separados, a tela veria a pesquisa acabar e a ficha ainda não existir.

    `gravacao` é o que `pipeline.research.persistir.persistir_pesquisa` devolveu, quando a
    ficha foi para o catálogo: `version_id` e os erros, se houve.
    """
    linha = sessao.get(ResearchRun, run_id)
    if linha is None:
        return

    ja_gravadas = set(
        sessao.exec(select(ResearchEvent.ordem).where(ResearchEvent.run_id == run_id)).all()
    )
    for evento in resultado.trilha.eventos:
        if evento.ordem in ja_gravadas:
            continue
        sessao.add(linha_de_evento(run_id, evento))

    linha.status = "concluida"
    linha.motivo_da_parada = resultado.motivo_da_parada.value
    linha.rodadas = resultado.orcamento.rodadas_gastas
    linha.paginas = resultado.orcamento.paginas_gastas
    linha.consultas = len(resultado.trilha.consultas)
    linha.campos_com_valor = resultado.cobertura.com_valor
    linha.campos_alvo = resultado.cobertura.total
    linha.segundos = resultado.orcamento.decorrido
    medicao = getattr(resultado, "medicao", None)
    if medicao is not None:
        linha.tokens = int(medicao.tokens_entrada + medicao.tokens_saida)
        linha.custo_brl = round(float(medicao.custo_brl), 6)
    if gravacao is not None:
        if getattr(gravacao, "version_id", None):
            linha.version_id = gravacao.version_id
        erros = list(getattr(gravacao, "erros", []) or [])
        if erros:
            linha.erro = "; ".join(erros)[:2000]
    linha.concluido_em = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    sessao.add(linha)
    sessao.commit()
