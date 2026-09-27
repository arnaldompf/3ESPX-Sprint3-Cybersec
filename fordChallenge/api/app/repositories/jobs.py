"""Repositório da fila.

A fila é a própria tabela `jobs` (ADR-3: sem Redis). Este arquivo só lê e escreve linhas;
a política de consumo — quantas tentativas, backoff, quem pega o quê — é do worker
(WP-14). Aqui não há `SELECT ... FOR UPDATE SKIP LOCKED` por isso: seria decisão de
concorrência, não acesso a dado, e o SQLite de dev não a suporta de todo modo.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlmodel import Session, select

from api.app.models import Job, JobStatus


def get(sessao: Session, job_id: str) -> Job | None:
    return sessao.get(Job, job_id)


def listar_por_status(sessao: Session, status: str, *, limite: int = 100) -> list[Job]:
    return list(
        sessao.exec(
            select(Job)
            .where(Job.status == status)
            .order_by(Job.criado_em)  # type: ignore[arg-type]
            .limit(limite)
        )
    )


def criar(
    sessao: Session,
    *,
    tipo: str = "extract",
    payload: dict[str, Any] | None = None,
    status: str = JobStatus.PENDENTE.value,
) -> Job:
    job = Job(tipo=tipo, payload=payload or {}, status=status)
    sessao.add(job)
    sessao.flush()
    return job


def atualizar(sessao: Session, job: Job, **campos: Any) -> Job:
    """Aplica os campos informados e marca `atualizado_em`.

    Recebe o objeto, não o id, para não esconder um `get` extra de quem já o tem em mão.
    """
    for nome, valor in campos.items():
        setattr(job, nome, valor)
    job.atualizado_em = dt.datetime.now(dt.UTC)
    sessao.add(job)
    sessao.flush()
    return job
