"""`/vehicles` e `/vehicles/{id}/specs` — a ficha, que é o produto.

A rota `/specs` é o critério de aceite mais importante da WP-06: a resposta valida no JSON
Schema canônico e **os campos não pedidos vêm com `status`, não omitidos**. A montagem
está em `api/app/services/spec_assembler.py`, com o porquê escrito lá.

`/vehicles` chama "vehicle" o que o banco chama `versions`, seguindo `docs/04`. Não é
inconsistência: para quem consulta, o objeto de interesse é o veículo concreto
("Ranger Raptor 3.0 V6 2026"), e é exatamente uma versão de um ano-modelo.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import select

from api.app.deps import SessaoDep, exige
from api.app.errors import ProblemaHTTP
from api.app.models import Brand, VehicleModel, Version
from api.app.permissions import Acao
from api.app.services import spec_assembler
from pipeline.schema import StandardSpec, resumo_validacao_edital

router = APIRouter(tags=["veiculos"], dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))])


class VeiculoOut(BaseModel):
    """A versão com marca e modelo já resolvidos — quem consulta pensa no veículo."""

    id: str
    marca: str
    modelo: str
    versao: str
    ano_modelo: int
    codigo_fipe: str | None = None
    in_lineup: bool


def _consulta_de_veiculos():
    return (
        select(Version, VehicleModel, Brand)
        .join(VehicleModel, VehicleModel.id == Version.model_id)
        .join(Brand, Brand.id == VehicleModel.brand_id)
    )


def _saida(version: Version, modelo: VehicleModel, marca: Brand) -> VeiculoOut:
    return VeiculoOut(
        id=version.id,
        marca=marca.nome,
        modelo=modelo.nome,
        versao=version.nome_exato,
        ano_modelo=version.ano_modelo,
        codigo_fipe=version.codigo_fipe,
        in_lineup=version.in_lineup,
    )


@router.get("/vehicles", response_model=list[VeiculoOut], summary="Lista veículos")
async def listar(
    sessao: SessaoDep,
    marca: str | None = Query(default=None),
    modelo: str | None = Query(default=None),
    limite: int = Query(default=100, ge=1, le=500),
) -> list[VeiculoOut]:
    consulta = _consulta_de_veiculos()
    if marca:
        consulta = consulta.where(Brand.nome.ilike(f"%{marca}%"))
    if modelo:
        consulta = consulta.where(VehicleModel.nome.ilike(f"%{modelo}%"))
    consulta = consulta.order_by(Brand.nome, VehicleModel.nome, Version.nome_exato).limit(limite)
    return [_saida(v, m, b) for v, m, b in sessao.exec(consulta).all()]


@router.get("/vehicles/{version_id}", response_model=VeiculoOut, summary="Um veículo")
async def obter(version_id: str, sessao: SessaoDep) -> VeiculoOut:
    linha = sessao.exec(_consulta_de_veiculos().where(Version.id == version_id)).first()
    if linha is None:
        raise ProblemaHTTP(404, f"Veículo {version_id} não existe.")
    return _saida(*linha)


@router.get(
    "/vehicles/{version_id}/specs",
    response_model=StandardSpec,
    summary="A ficha padronizada da versão",
)
async def specs(
    version_id: str,
    sessao: SessaoDep,
    attributes: list[str] | None = Query(
        default=None,
        description=(
            "Filtra **valores**, não campos: os não pedidos continuam na resposta, sem "
            "valor e com `status=nao_verificado`. Aceita `a,b` e repetição do parâmetro."
        ),
    ),
) -> StandardSpec:
    if sessao.get(Version, version_id) is None:
        raise ProblemaHTTP(404, f"Veículo {version_id} não existe.")
    return spec_assembler.montar(sessao, version_id, attributes=attributes)


@router.get(
    "/vehicles/{version_id}/validacao-edital",
    summary="Quantos campos do slide de validação do edital a ficha comprova",
    description=(
        "Separa o que o edital pede para validar (`docs/01_REQUISITOS_EDITAL.md`, slide "
        "da Ranger Raptor) do resto dos 54 campos — sem excluir os outros, só destacando "
        "estes. Cada vazio vem com o status real (`nao_encontrado` != `nao_disponivel`)."
    ),
)
async def validacao_edital(version_id: str, sessao: SessaoDep) -> dict:
    if sessao.get(Version, version_id) is None:
        raise ProblemaHTTP(404, f"Veículo {version_id} não existe.")
    spec = spec_assembler.montar(sessao, version_id)
    return resumo_validacao_edital(spec)
