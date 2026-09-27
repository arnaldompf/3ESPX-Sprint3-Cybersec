"""Repositório de valores da ficha.

`upsert` trata `(version_id, field)` como chave: a ficha tem uma linha por campo, e a
recoleta atualiza essa linha em vez de acumular histórico (histórico de mudança é
`alerts`, WP-25). A tabela não tem `UNIQUE` nessa dupla porque a reconciliação precisa
poder segurar valores concorrentes; a unicidade é escolha de quem escreve, feita aqui.

O repositório não valida a regra "nenhum valor sem evidência": ela é do pipeline, que é
quem tem o texto da fonte na mão para conferir. Aqui só se grava o que já foi decidido.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlmodel import Session, select

from api.app.models import SpecValue


def get(sessao: Session, spec_value_id: str) -> SpecValue | None:
    return sessao.get(SpecValue, spec_value_id)


def get_por_campo(sessao: Session, *, version_id: str, field: str) -> SpecValue | None:
    return sessao.exec(
        select(SpecValue).where(SpecValue.version_id == version_id, SpecValue.field == field)
    ).first()


def listar_por_versao(sessao: Session, version_id: str) -> list[SpecValue]:
    return list(
        sessao.exec(
            select(SpecValue).where(SpecValue.version_id == version_id).order_by(SpecValue.field)  # type: ignore[arg-type]
        )
    )


def upsert(
    sessao: Session,
    *,
    version_id: str,
    field: str,
    value_json: Any = None,
    status: str,
    confidence: float = 0.0,
    unit: str | None = None,
    evidence_id: str | None = None,
    extraction_id: str | None = None,
) -> SpecValue:
    """Grava o campo da versão, criando ou substituindo a linha existente."""
    valor = get_por_campo(sessao, version_id=version_id, field=field)
    if valor is None:
        valor = SpecValue(version_id=version_id, field=field, status=status)
    valor.value_json = value_json
    valor.status = status
    valor.confidence = confidence
    valor.unit = unit
    valor.evidence_id = evidence_id
    valor.extraction_id = extraction_id
    valor.atualizado_em = dt.datetime.now(dt.UTC)
    sessao.add(valor)
    sessao.flush()
    return valor
