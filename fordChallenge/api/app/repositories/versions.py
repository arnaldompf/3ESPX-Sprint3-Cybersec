"""Repositório de versões.

A chave natural é `(model_id, nome_exato, ano_modelo)` — a mesma da `UniqueConstraint` da
tabela. Não existe busca difusa aqui: casar "GR-Sport" com "SRX Plus AT" é decisão do
resolvedor (WP-07), que precisa devolver `versao_inexistente` com alternativas, e não de
uma query que escolhe sozinha.
"""

from __future__ import annotations

import datetime as dt

from sqlmodel import Session, select

from api.app.models import Version


def get(sessao: Session, version_id: str) -> Version | None:
    return sessao.get(Version, version_id)


def get_por_nome(
    sessao: Session, *, model_id: str, nome_exato: str, ano_modelo: int
) -> Version | None:
    return sessao.exec(
        select(Version).where(
            Version.model_id == model_id,
            Version.nome_exato == nome_exato,
            Version.ano_modelo == ano_modelo,
        )
    ).first()


def listar_por_modelo(
    sessao: Session, model_id: str, *, apenas_em_linha: bool = False
) -> list[Version]:
    consulta = select(Version).where(Version.model_id == model_id)
    if apenas_em_linha:
        consulta = consulta.where(Version.in_lineup == True)  # noqa: E712  (SQL, não Python)
    return list(sessao.exec(consulta.order_by(Version.nome_exato)))  # type: ignore[arg-type]


def upsert(
    sessao: Session,
    *,
    model_id: str,
    nome_exato: str,
    ano_modelo: int,
    codigo_fipe: str | None = None,
    in_lineup: bool | None = None,
    lineup_checked_at: dt.datetime | None = None,
) -> Version:
    """Cria ou atualiza a versão.

    Só sobrescreve o que veio preenchido: `None` significa "não tenho informação sobre
    isso agora", nunca "apague o que estava lá" — apagar dado conferido por omissão de
    um chamador seria perda silenciosa.
    """
    versao = get_por_nome(sessao, model_id=model_id, nome_exato=nome_exato, ano_modelo=ano_modelo)
    if versao is None:
        versao = Version(model_id=model_id, nome_exato=nome_exato, ano_modelo=ano_modelo)
    if codigo_fipe is not None:
        versao.codigo_fipe = codigo_fipe
    if in_lineup is not None:
        versao.in_lineup = in_lineup
    if lineup_checked_at is not None:
        versao.lineup_checked_at = lineup_checked_at
    sessao.add(versao)
    sessao.flush()
    return versao
