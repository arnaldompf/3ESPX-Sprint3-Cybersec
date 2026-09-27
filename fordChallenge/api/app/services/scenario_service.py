"""Adaptador entre o banco e o simulador. **Só leitura.**

Monta os mapas de `parity.valores_de_spec` a partir das fichas, chama
`pipeline/scenarios.py` e serializa. A regra fica no pipeline, testável sem banco; aqui só
há tradução — e, deliberadamente, nenhuma escrita.

**Por que a comparabilidade entra aqui e não no motor.** O aviso de par não comparável
(`pipeline/comparables.py`) é sobre os veículos **reais**, não sobre a hipótese: se a Raptor
não é comparável com a Hilux hoje, um corte de 5% no preço da Hilux não muda isso. O aviso
viaja no cenário para não desaparecer justamente na tela em que alguém está imaginando um
futuro — mas é calculado uma vez, sobre a realidade.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from api.app.models import Brand, VehicleModel, Version
from api.app.services import spec_assembler
from pipeline import comparables, parity, scenarios
from pipeline.fit.engine import NeedsProfile


def _rotulo(sessao: Session, version: Version) -> str:
    modelo = sessao.get(VehicleModel, version.model_id)
    marca = sessao.get(Brand, modelo.brand_id) if modelo else None
    partes = [p for p in (marca.nome if marca else "", modelo.nome if modelo else "") if p]
    return " ".join([*partes, version.nome_exato]).strip()


def _lado(sessao: Session, version: Version) -> scenarios.Lado:
    spec = spec_assembler.montar(sessao, version.id)
    return scenarios.Lado(
        version_id=version.id,
        rotulo=_rotulo(sessao, version),
        valores=parity.valores_de_spec(spec),
    )


def _comparabilidade(sessao: Session, ford: Version, concorrente: Version) -> dict[str, Any]:
    """O aviso de comparabilidade do par **real**, para viajar no cenário."""
    atributos_ford = comparables.atributos_de_spec(
        spec_assembler.montar(sessao, ford.id), versao=ford.nome_exato
    )
    atributos_conc = comparables.atributos_de_spec(
        spec_assembler.montar(sessao, concorrente.id), versao=concorrente.nome_exato
    )
    resultado = comparables.avaliar(atributos_ford, atributos_conc)
    # A forma é a **mesma** de `/parity` (`ComparabilidadeOut`), com um campo a mais: a
    # tela usa um componente só para o aviso nas duas rotas, e um formato reduzido aqui
    # obrigaria a um segundo componente — que divergiria do primeiro na próxima revisão.
    return {
        "version_id": concorrente.id,
        "rotulo": _rotulo(sessao, concorrente),
        **resultado.to_dict(),
        "escopo": (
            "avaliado sobre os valores reais dos dois veículos; a hipótese do cenário não "
            "torna um par comparável nem deixa de tornar"
        ),
    }


def simular(
    sessao: Session,
    *,
    ford: Version,
    concorrentes: list[Version],
    overrides: list[scenarios.Override],
    perfil: NeedsProfile | None = None,
    grupos: list[str] | None = None,
) -> dict[str, Any]:
    """Lê as fichas, roda o cenário e devolve o dicionário da resposta."""
    lado_ford = _lado(sessao, ford)
    lados_concorrentes = [_lado(sessao, c) for c in concorrentes]

    resultado = scenarios.simular(
        ford=lado_ford,
        concorrentes=lados_concorrentes,
        overrides=overrides,
        perfil=perfil,
        grupos=grupos,
    )

    dados = resultado.to_dict()
    dados["ford"] = {"version_id": ford.id, "rotulo": lado_ford.rotulo}

    # O aviso de comparabilidade entra nas duas colunas do mesmo par: a tela mostra os dois
    # painéis lado a lado, e o aviso presente só num deles pareceria ter mudado com a
    # hipótese.
    comparabilidades = {c.id: _comparabilidade(sessao, ford, c) for c in concorrentes}
    for painel in (*dados["atual"], *dados["cenario"]):
        painel["coluna"]["comparabilidade"] = comparabilidades.get(painel["version_id"])

    return dados
