"""`/extractions` e `/extractions/from-image` — cria job, devolve **202**.

Por que 202 e não 200: a extração é assíncrona (o worker da WP-14 consome a fila). O
`Location` aponta para `/jobs/{id}`, que é onde o cliente acompanha. Responder 200 com a
ficha exigiria rodar o pipeline dentro do request — trinta segundos de HTTP e um timeout
de proxy no meio.

**Idempotência por (versão, dia)**: pedir a mesma extração duas vezes no mesmo dia devolve
o **mesmo** job, não um novo. Sem isso, um duplo clique na tela dispara duas coletas
completas — e coleta é o que gasta cota de site e dinheiro de LLM. `force_refresh=true`
força um job novo, para o caso de o site ter mudado no meio do dia.
"""

from __future__ import annotations

import datetime as dt
import hashlib

import structlog
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from api.app.deps import SessaoDep, UsuarioDep, exige
from api.app.errors import ProblemaHTTP
from api.app.models import Job, JobStatus
from api.app.permissions import Acao

log = structlog.get_logger(__name__)
router = APIRouter(tags=["extracoes"], dependencies=[Depends(exige(Acao.CRIAR_EXTRACOES))])

#: Onde o upload de imagem é guardado. Em `data/`, que o `.gitignore` ignora.
from pathlib import Path  # noqa: E402 - depois do router para o modulo ler de cima a baixo

DIR_UPLOADS = Path(__file__).resolve().parents[3] / "data" / "uploads"
#: Teto do upload. Foto de ficha técnica tirada de celular não passa disso.
TAMANHO_MAXIMO_MB = 12
#: Tipos aceitos no `from-image`. Lista fechada: aceitar qualquer coisa é convite a
#: usar o endpoint como armazenamento de arquivo arbitrário.
TIPOS_DE_IMAGEM = ("image/jpeg", "image/png", "image/webp", "application/pdf")


class ExtracaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marca: str = Field(min_length=1, max_length=80)
    modelo: str = Field(min_length=1, max_length=80)
    versao: str = Field(min_length=1, max_length=160)
    attributes: list[str] | None = None
    force_refresh: bool = False


class JobCriado(BaseModel):
    job_id: str
    status: str
    location: str
    reaproveitado: bool = False
    """`True` quando a idempotência devolveu um job que já existia."""


def _chave_de_idempotencia(marca: str, modelo: str, versao: str, dia: str) -> str:
    """`(versão, dia)` reduzido a um hash curto, para caber no payload e ser indexável."""
    alvo = f"{marca}|{modelo}|{versao}|{dia}".lower()
    return hashlib.sha256(alvo.encode()).hexdigest()[:16]


def _job_do_dia(sessao, chave: str) -> Job | None:
    return sessao.exec(
        select(Job).where(Job.tipo == "extract", Job.payload["chave"].as_string() == chave)
    ).first()


def _criar_job(sessao, *, tipo: str, payload: dict) -> Job:
    job = Job(tipo=tipo, status=JobStatus.PENDENTE.value, payload=payload)
    sessao.add(job)
    sessao.commit()
    sessao.refresh(job)
    return job


@router.post(
    "/extractions",
    response_model=JobCriado,
    status_code=202,
    summary="Enfileira uma extração",
)
async def criar(
    corpo: ExtracaoIn, sessao: SessaoDep, usuario: UsuarioDep, response: Response
) -> JobCriado:
    dia = dt.date.today().isoformat()
    chave = _chave_de_idempotencia(corpo.marca, corpo.modelo, corpo.versao, dia)

    if not corpo.force_refresh:
        existente = _job_do_dia(sessao, chave)
        if existente is not None:
            # Mesmo pedido no mesmo dia: o mesmo job. Coleta gasta cota de site e
            # dinheiro de LLM, e duplo clique não pode custar duas.
            response.headers["Location"] = f"/api/v1/jobs/{existente.id}"
            return JobCriado(
                job_id=existente.id,
                status=existente.status,
                location=f"/api/v1/jobs/{existente.id}",
                reaproveitado=True,
            )

    job = _criar_job(
        sessao,
        tipo="extract",
        payload={
            "marca": corpo.marca,
            "modelo": corpo.modelo,
            "versao": corpo.versao,
            "attributes": corpo.attributes,
            "chave": chave,
            "dia": dia,
            "solicitado_por": usuario.id,
            "force_refresh": corpo.force_refresh,
        },
    )
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    log.info("extractions.enfileirada", job_id=job.id, por=usuario.id)
    return JobCriado(job_id=job.id, status=job.status, location=f"/api/v1/jobs/{job.id}")


@router.post(
    "/extractions/from-image",
    response_model=JobCriado,
    status_code=202,
    summary="Enfileira uma extração a partir de foto de ficha técnica",
)
async def criar_de_imagem(
    sessao: SessaoDep,
    usuario: UsuarioDep,
    response: Response,
    image: UploadFile = File(..., description="Foto ou PDF da ficha técnica"),
    marca: str | None = Form(default=None),
    modelo: str | None = Form(default=None),
    versao: str | None = Form(default=None),
) -> JobCriado:
    """Salva o arquivo e enfileira. O OCR é do worker, não do request.

    O arquivo é gravado com o **sha256 do conteúdo** como nome: dois envios da mesma foto
    não geram dois arquivos, e o nome que o usuário deu não vira caminho no disco — nome
    de arquivo vindo de fora é o vetor clássico de escrita fora do diretório.
    """
    if image.content_type not in TIPOS_DE_IMAGEM:
        raise ProblemaHTTP(
            422,
            f"Tipo {image.content_type!r} não aceito. Aceitos: {', '.join(TIPOS_DE_IMAGEM)}.",
        )

    dados = await image.read()
    if len(dados) > TAMANHO_MAXIMO_MB * 1024 * 1024:
        raise ProblemaHTTP(
            422, f"Arquivo de {len(dados) / 1e6:.1f} MB acima do teto de {TAMANHO_MAXIMO_MB} MB."
        )
    if not dados:
        raise ProblemaHTTP(422, "Arquivo vazio.")

    sha = hashlib.sha256(dados).hexdigest()
    extensao = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(
        image.content_type or "", ".pdf"
    )
    DIR_UPLOADS.mkdir(parents=True, exist_ok=True)
    destino = DIR_UPLOADS / f"{sha}{extensao}"
    if not destino.exists():
        destino.write_bytes(dados)

    job = _criar_job(
        sessao,
        tipo="extract_from_image",
        payload={
            "arquivo": destino.name,
            "sha256": sha,
            "content_type": image.content_type,
            "bytes": len(dados),
            # O nome original fica registrado como **dado**, nunca como caminho.
            "nome_enviado": image.filename,
            "marca": marca,
            "modelo": modelo,
            "versao": versao,
            "solicitado_por": usuario.id,
        },
    )
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    log.info("extractions.imagem_enfileirada", job_id=job.id, sha256=sha[:12])
    return JobCriado(job_id=job.id, status=job.status, location=f"/api/v1/jobs/{job.id}")
