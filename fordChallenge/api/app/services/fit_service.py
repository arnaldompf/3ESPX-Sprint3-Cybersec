"""Adaptador entre o banco e o Customer Need Engine.

Lê as fichas, monta os mapas de atributos, chama `pipeline/fit/engine.py` e
`usage_cost.py`, e devolve o bloco `fit` do `POST /comparisons`. A regra de aderência fica
no pipeline, testável sem banco; aqui só há tradução.

**A origem do consumo vem da evidência, não de um palpite.** O `usage_cost` precisa saber
se o consumo é `pbe`, `oficial` ou `informado`, senão a frase fixa diria "declarado pela
montadora" sobre um número medido pelo Inmetro. A tabela `evidences` **não** guarda
`source_id` (só `source_url`, `tier`, `quote`), então o sinal disponível é a própria
citação: a redação obrigatória do PBEV ("percorre X km/l na cidade") é inconfundível, e é
ela que `pipeline/connectors/pbe.py` recorta. Reconhecer pelo trecho é menos elegante que
por um campo dedicado e usa o dado que existe hoje, em vez de exigir migração.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlmodel import Session, select

from api.app.models import Brand, Evidence, SpecValue, VehicleModel, Version
from api.app.services import spec_assembler
from pipeline import comparables
from pipeline.fit import dimensions, engine, ranges, usage_cost


def _rotulo(sessao: Session, version: Version | None) -> str:
    if version is None:
        return ""
    modelo = sessao.get(VehicleModel, version.model_id)
    marca = sessao.get(Brand, modelo.brand_id) if modelo else None
    partes = [p for p in (marca.nome if marca else "", modelo.nome if modelo else "") if p]
    return " ".join([*partes, version.nome_exato]).strip()


def _origem_do_consumo(sessao: Session, version_id: str) -> dict[str, str]:
    """Campo de consumo → origem (`pbe` | `oficial`), lida da evidência gravada.

    O que **não** está aqui: um default "pbe" otimista. Campo sem evidência de fonte
    conhecida fica fora do mapa, e o `usage_cost` assume `oficial` — que é o mais fraco dos
    dois e, portanto, o único palpite seguro.
    """
    campos = ("consumo_urbano_kml", "consumo_rodoviario_kml")
    linhas = sessao.exec(
        select(SpecValue, Evidence)
        .join(Evidence, Evidence.id == SpecValue.evidence_id, isouter=True)
        .where(SpecValue.version_id == version_id, SpecValue.field.in_(campos))  # type: ignore[attr-defined]
    ).all()
    saida: dict[str, str] = {}
    for valor, evidencia in linhas:
        if evidencia is None:
            continue
        # `source_url` guarda a página; a fatia do PBEV é reconhecida pelo trecho, que traz
        # a redação obrigatória do programa. É o sinal mais confiável disponível no banco.
        if "percorre" in (evidencia.quote or "") and "km/l" in (evidencia.quote or ""):
            saida[valor.field] = "pbe"
    return saida


def montar(
    sessao: Session,
    *,
    base_version_id: str,
    concorrentes: list[str],
    perfil: engine.NeedsProfile,
    consumo_informado: dict[str, float] | None = None,
    data: dt.date | None = None,
) -> dict[str, Any]:
    """O bloco `fit` da resposta: aderência e custo de uso, por concorrente."""
    informado = consumo_informado or {}
    faixas = ranges.carregar()
    config = dimensions.carregar()

    base = sessao.get(Version, base_version_id)
    spec_base = spec_assembler.montar(sessao, base_version_id)
    atributos_base = comparables.atributos_de_spec(
        spec_base, versao=base.nome_exato if base else ""
    )
    rotulo_base = _rotulo(sessao, base)

    custo_base = usage_cost.calcular(
        atributos=atributos_base,
        km_mes=perfil.km_mes,
        precos={
            "diesel": perfil.combustivel_preco.diesel,
            "gasolina": perfil.combustivel_preco.gasolina,
        },
        version_id=base_version_id,
        rotulo=rotulo_base,
        informado_kml=informado.get(base_version_id),
        origem_por_campo=_origem_do_consumo(sessao, base_version_id),
        data=data,
    )

    saida: dict[str, Any] = {
        "rotulo": config.rotulo_obrigatorio,
        "versao_das_dimensoes": config.versao,
        "versao_das_faixas": faixas.versao,
        "perfil": perfil.model_dump(mode="json"),
        "pesos": engine.pesos_de(perfil, config=config),
        "base": {"version_id": base_version_id, "rotulo": rotulo_base},
        "usage_cost_base": custo_base.to_dict(),
        "concorrentes": [],
    }

    for version_id in concorrentes:
        version = sessao.get(Version, version_id)
        spec = spec_assembler.montar(sessao, version_id)
        atributos = comparables.atributos_de_spec(
            spec, versao=version.nome_exato if version else ""
        )
        rotulo = _rotulo(sessao, version)

        aderencia = engine.avaliar(atributos_base, atributos, perfil, config=config, faixas=faixas)
        custo = usage_cost.calcular(
            atributos=atributos,
            km_mes=perfil.km_mes,
            precos={
                "diesel": perfil.combustivel_preco.diesel,
                "gasolina": perfil.combustivel_preco.gasolina,
            },
            version_id=version_id,
            rotulo=rotulo,
            informado_kml=informado.get(version_id),
            origem_por_campo=_origem_do_consumo(sessao, version_id),
            data=data,
        )
        saida["concorrentes"].append(
            {
                "version_id": version_id,
                "rotulo": rotulo,
                "aderencia": aderencia.to_dict(),
                "usage_cost": custo.to_dict(),
                "custo_comparado": usage_cost.comparar(custo_base, custo).to_dict(),
            }
        )

    return saida


def dimensoes_para_a_tela() -> dict[str, Any]:
    """A tabela de dimensões como o front-end a consome. Uma tabela só, no back-end."""
    config = dimensions.carregar()
    faixas = ranges.carregar()
    return {
        "versao": config.versao,
        "versao_das_faixas": faixas.versao,
        "pesos_por_rank": list(config.pesos_por_rank),
        "cobertura_minima": config.cobertura_minima,
        "usos": list(config.usos),
        "rotulo_obrigatorio": config.rotulo_obrigatorio,
        "dimensoes": [
            {
                "id": dimensao.id,
                "rotulo": dimensao.rotulo,
                "campos": [
                    {
                        "campo": campo.campo,
                        "tipo": campo.tipo,
                        "direcao": campo.direcao,
                        # A faixa vai junto: é ela que explica por que 397 cv vale 10, e
                        # sem ela o "ver como foi calculado" fica pela metade.
                        "faixa": (
                            faixas.de(campo.campo).to_dict()
                            if faixas.de(campo.campo) is not None
                            else None
                        ),
                    }
                    for campo in dimensao.campos
                ],
            }
            for dimensao in config.dimensoes.values()
        ],
    }
