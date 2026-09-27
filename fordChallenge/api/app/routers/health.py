"""`GET /api/v1/health` — o único endpoint desta WP, público por contrato (docs/04).

Responde **200 mesmo com o banco fora do ar**, com `db.ok = false` e `status =
"degradado"`. Não é otimismo: o status HTTP aqui é a disponibilidade do processo de API, e
quem decide tirar a instância do balanceador é o orquestrador, lendo o corpo. Um 503 faria
o critério de aceite da spec ("200 com `db` e `version`") depender de o banco estar de pé.
O corpo é honesto; o código é sobre quem respondeu.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlmodel import Session

from api.app.config import descrever_banco, get_settings, versao_do_pacote
from api.app.db import database_url, engine
from api.app.models import WorkerHeartbeat

router = APIRouter(tags=["saude"])


class BancoOut(BaseModel):
    """Estado do banco. Dialeto e nome, nunca a URL de conexão."""

    ok: bool
    dialeto: str
    nome: str
    erro: str | None = None


class WorkerOut(BaseModel):
    """O worker está vivo?

    **Por que isto está no health** (12/09/2026): um avaliador pediu o documento do cliente
    e a tela girou até desistir. O worker tinha morrido, e nada no sistema sabia — nem quem
    olhava a tela, nem este endpoint, nem quem administra a máquina. Quem cuida da máquina
    precisa de um lugar para perguntar "está de pé?", e este é o lugar.

    `visto_em` é `null` quando o worker **nunca** subiu contra este banco. É diferente de
    "subiu e morreu", e a diferença importa para quem investiga.
    """

    ok: bool
    visto_em: str | None = None
    ha_quantos_segundos: float | None = None
    pid: int | None = None
    motivo: str | None = None


class SaudeOut(BaseModel):
    """Resposta do health check."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "version": "0.1.0",
                "db": {"ok": True, "dialeto": "sqlite", "nome": "dev.db", "erro": None},
                "etiqueta": "FATO",
                "auth_enabled": False,
            }
        }
    )

    status: Literal["ok", "degradado"]
    version: str
    db: BancoOut
    #: Etiqueta obrigatória em toda informação que chega ao cliente (CLAUDE.md). O health é
    #: observação direta — `SELECT 1` respondeu ou não —, logo FATO e nunca INFERÊNCIA.
    etiqueta: Literal["FATO"] = "FATO"
    #: Autenticação ligada (D-204). Publicado **de propósito** num endpoint público: com
    #: ela desligada a API não pede credencial em rota nenhuma, e quem administra a
    #: máquina tem de poder descobrir isso sem ler o `.env`. É o mesmo motivo pelo qual
    #: `demo_mode` era publicado antes — a pergunta continua sendo "esta porta está
    #: aberta?", só mudou o nome da chave que a responde.
    auth_enabled: bool = False
    #: O worker da fila. Sem ele, nenhum documento do cliente sai.
    worker: WorkerOut
    #: O Pesquisador (WP-41) está montado? A tela lê daqui para decidir se oferece o botão.
    #:
    #: Publicado no health, e não numa variável de build do front, porque o bundle da demo
    #: é gerado antes de a máquina do dia estar configurada — e um recurso que exige
    #: reconstruir o bundle para ligar é um recurso que não se liga na hora.
    research_enabled: bool = False
    #: O Benchmark competitivo (FASE 3) está montado?
    #:
    #: Pela mesma razão do `research_enabled`, e para o mesmo fim: **a tela precisa saber
    #: antes de chamar.** Sem isto, a tela de Benchmark pede a rota, recebe 404 e o
    #: navegador registra um erro de console — que o portão `qa/e2e` reprova, e com razão:
    #: erro de console é indistinguível de defeito para quem está olhando.
    benchmark_enabled: bool = False


def _testar_banco(url: str) -> tuple[bool, str | None]:
    """`SELECT 1`. Em caso de falha devolve só o **nome** da exceção.

    Nunca `str(exc)`: a mensagem do SQLAlchemy costuma trazer a URL de conexão inteira, e
    como `/health` é público isso entregaria a DSN com usuário e senha a quem pedir.
    """
    try:
        with engine(url).connect() as conexao:
            conexao.execute(text("SELECT 1")).scalar_one()
    except Exception as exc:
        return False, type(exc).__name__
    return True, None


def _olhar_worker(url: str) -> WorkerOut:
    """Lê o último batimento. Nunca levanta: o health responde 200 mesmo com o banco fora.

    `status` da API **não** degrada por causa do worker: a API está de pé, e dizer o
    contrário faria um monitor externo reiniciar o processo errado. O que o worker fora do
    ar quebra é a geração de documento, e é isso que este bloco informa.
    """
    from pipeline.worker import TOLERANCIA_DO_BATIMENTO_S

    try:
        with Session(engine(url)) as sessao:
            linha = sessao.get(WorkerHeartbeat, "worker")
    except Exception as exc:
        return WorkerOut(
            ok=False, motivo=f"não foi possível ler o sinal de vida ({type(exc).__name__})"
        )

    if linha is None:
        return WorkerOut(ok=False, motivo="o worker nunca subiu contra este banco")

    agora = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    visto = linha.visto_em
    idade = (agora - visto).total_seconds()
    vivo = idade <= TOLERANCIA_DO_BATIMENTO_S
    return WorkerOut(
        ok=vivo,
        visto_em=visto.isoformat(),
        ha_quantos_segundos=round(idade, 1),
        pid=linha.pid,
        motivo=None if vivo else f"último sinal de vida há {idade:.0f} s",
    )


@router.get(
    "/health",
    response_model=SaudeOut,
    summary="Disponibilidade da API e do banco",
    description=(
        "Público. Responde 200 mesmo com o banco indisponível: `db.ok` e `status` "
        "reportam o estado real, e a URL de conexão nunca é exposta."
    ),
)
def health() -> SaudeOut:
    url = database_url()
    ok, erro = _testar_banco(url)
    banco = descrever_banco(url)
    return SaudeOut(
        status="ok" if ok else "degradado",
        version=versao_do_pacote(),
        db=BancoOut(ok=ok, dialeto=banco["dialeto"], nome=banco["nome"], erro=erro),
        auth_enabled=get_settings().auth_enabled,
        worker=_olhar_worker(url),
        research_enabled=os.environ.get("RESEARCH_ENABLED", "").strip().lower()
        in {"1", "true", "sim"},
        benchmark_enabled=os.environ.get("BENCHMARK_ENABLED", "").strip().lower()
        in {"1", "true", "sim"},
    )
