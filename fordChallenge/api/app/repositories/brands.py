"""Repositório de marcas e modelos.

Fino de propósito: recebe uma `Session` e só fala com ela. Nenhuma regra de negócio
mora aqui — resolver versão, decidir status, calcular confiança é trabalho do pipeline;
misturar as duas coisas é o que transforma repositório em god object.

Modelos (`models`) ficam neste arquivo, e não em um `models.py` próprio, porque marca e
modelo formam um único nível de catálogo: quem cria um sempre acaba de criar o outro, e
um segundo arquivo só duplicaria os mesmos dois lookups.

`upsert` faz `flush`, nunca `commit`: quem abriu a transação decide quando confirmar.
"""

from __future__ import annotations

from sqlmodel import Session, select

from api.app.models import Brand, VehicleModel


def get(sessao: Session, brand_id: str) -> Brand | None:
    return sessao.get(Brand, brand_id)


def get_by_nome(sessao: Session, nome: str) -> Brand | None:
    return sessao.exec(select(Brand).where(Brand.nome == nome)).first()


def listar(sessao: Session) -> list[Brand]:
    return list(sessao.exec(select(Brand).order_by(Brand.nome)))  # type: ignore[arg-type]


def upsert(sessao: Session, *, nome: str) -> Brand:
    """Devolve a marca de `nome`, criando-a se não existir (idempotente)."""
    existente = get_by_nome(sessao, nome)
    if existente is not None:
        return existente
    marca = Brand(nome=nome)
    sessao.add(marca)
    sessao.flush()
    return marca


def get_modelo(sessao: Session, *, brand_id: str, nome: str) -> VehicleModel | None:
    return sessao.exec(
        select(VehicleModel).where(VehicleModel.brand_id == brand_id, VehicleModel.nome == nome)
    ).first()


def listar_modelos(sessao: Session, brand_id: str) -> list[VehicleModel]:
    return list(
        sessao.exec(
            select(VehicleModel)
            .where(VehicleModel.brand_id == brand_id)
            .order_by(VehicleModel.nome)  # type: ignore[arg-type]
        )
    )


def upsert_modelo(
    sessao: Session, *, brand_id: str, nome: str, segmento: str | None = None
) -> VehicleModel:
    existente = get_modelo(sessao, brand_id=brand_id, nome=nome)
    if existente is not None:
        if segmento and existente.segmento != segmento:
            existente.segmento = segmento
            sessao.add(existente)
            sessao.flush()
        return existente
    modelo = VehicleModel(brand_id=brand_id, nome=nome, segmento=segmento)
    sessao.add(modelo)
    sessao.flush()
    return modelo
