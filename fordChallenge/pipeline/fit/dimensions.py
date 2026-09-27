"""Leitura e validação de `dimensions.yaml`.

Separado do motor porque a tabela é **dado de produto**: o gestor da Ford lê aquele arquivo
e discorda de uma linha, e a discordância vira um commit em vez de um pedido de mudança de
software. Este módulo só garante que o arquivo é coerente antes de ser usado.

As validações não são burocracia. Cada uma corresponde a uma forma de a nota sair errada
**em silêncio**: tipo de nota desconhecido faria o campo ser ignorado sem aviso; campo fora
do schema canônico nunca casaria com valor nenhum; ordinal sem `ordem` daria nota zero a
todos os valores; e peso que não soma 100 faria a aderência total ter um teto diferente de
10 sem que a tela soubesse.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ARQUIVO = Path(__file__).resolve().parent / "dimensions.yaml"

#: Os tipos de nota que o motor sabe calcular.
TIPOS = ("numerico", "booleano", "contagem", "ordinal", "presenca_de_termo")

#: As direções válidas para campo numérico.
DIRECOES = ("maior", "menor")


class DimensaoInvalida(ValueError):
    """O YAML de dimensões está incoerente. Falhar alto: ver o docstring do módulo."""


@dataclass(frozen=True)
class CampoDaDimensao:
    campo: str
    tipo: str
    direcao: str | None = None
    ordem: tuple[str, ...] = ()
    termos: tuple[str, ...] = ()


@dataclass(frozen=True)
class Dimensao:
    id: str
    rotulo: str
    campos: tuple[CampoDaDimensao, ...]


@dataclass
class Config:
    versao: str
    pesos_por_rank: tuple[int, ...]
    cobertura_minima: float
    dimensoes: dict[str, Dimensao] = field(default_factory=dict)
    usos: tuple[str, ...] = ()
    rotulo_obrigatorio: str = ""

    def campo_a_dimensoes(self) -> dict[str, list[str]]:
        """Campo → dimensões em que ele pesa. Um campo pode pesar em mais de uma."""
        mapa: dict[str, list[str]] = {}
        for nome, dimensao in self.dimensoes.items():
            for campo in dimensao.campos:
                mapa.setdefault(campo.campo, []).append(nome)
        return mapa


@functools.lru_cache(maxsize=2)
def carregar(caminho: str | None = None) -> Config:
    """Lê e **valida** o YAML. Em cache: o arquivo não muda em tempo de execução."""
    origem = Path(caminho) if caminho else ARQUIVO
    dados: dict[str, Any] = yaml.safe_load(origem.read_text(encoding="utf-8")) or {}

    pesos = tuple(int(p) for p in dados.get("pesos_por_rank", []))
    if not pesos:
        raise DimensaoInvalida("`pesos_por_rank` vazio: sem pesos não há aderência")
    if sum(pesos) != 100:
        raise DimensaoInvalida(
            f"`pesos_por_rank` soma {sum(pesos)}, não 100: a aderência total teria um teto "
            "diferente de 10 e a tela não saberia disso"
        )

    from pipeline.schema import GRUPOS

    canonicos = {campo for campos in GRUPOS.values() for campo in campos}

    dimensoes: dict[str, Dimensao] = {}
    for nome, bruto in (dados.get("dimensoes") or {}).items():
        campos: list[CampoDaDimensao] = []
        for item in bruto.get("campos", []):
            tipo = str(item.get("tipo", ""))
            campo = str(item.get("campo", ""))
            if tipo not in TIPOS:
                raise DimensaoInvalida(
                    f"dimensão {nome!r}, campo {campo!r}: tipo {tipo!r} desconhecido "
                    f"(conhecidos: {', '.join(TIPOS)})"
                )
            if campo not in canonicos:
                raise DimensaoInvalida(
                    f"dimensão {nome!r}: campo {campo!r} não existe no schema canônico; "
                    "ele nunca casaria com valor nenhum"
                )
            direcao = item.get("direcao")
            if tipo == "numerico" and direcao not in DIRECOES:
                raise DimensaoInvalida(
                    f"dimensão {nome!r}, campo {campo!r}: campo numérico precisa de "
                    f"`direcao` ({' ou '.join(DIRECOES)})"
                )
            if tipo == "ordinal" and not item.get("ordem"):
                raise DimensaoInvalida(
                    f"dimensão {nome!r}, campo {campo!r}: ordinal sem `ordem` daria nota "
                    "zero a todos os valores"
                )
            if tipo == "presenca_de_termo" and not item.get("termos"):
                raise DimensaoInvalida(
                    f"dimensão {nome!r}, campo {campo!r}: `presenca_de_termo` sem `termos`"
                )
            campos.append(
                CampoDaDimensao(
                    campo=campo,
                    tipo=tipo,
                    direcao=str(direcao) if direcao else None,
                    ordem=tuple(str(o) for o in item.get("ordem", ())),
                    termos=tuple(str(t) for t in item.get("termos", ())),
                )
            )
        if not campos:
            raise DimensaoInvalida(f"dimensão {nome!r} sem campo nenhum")
        dimensoes[str(nome)] = Dimensao(
            id=str(nome), rotulo=str(bruto.get("rotulo") or nome), campos=tuple(campos)
        )

    if not dimensoes:
        raise DimensaoInvalida("nenhuma dimensão declarada")

    rotulo = str(dados.get("rotulo_obrigatorio", "")).strip()
    if not rotulo:
        raise DimensaoInvalida(
            "`rotulo_obrigatorio` vazio: `docs/12` §6.2 exige o rótulo em toda saída do "
            "motor, e sem ele 'aderência 8,4' se lê como nota de qualidade"
        )

    return Config(
        versao=str(dados.get("versao", "sem versao")),
        pesos_por_rank=pesos,
        cobertura_minima=float(dados.get("cobertura_minima", 0.5)),
        dimensoes=dimensoes,
        usos=tuple(str(u) for u in dados.get("usos", ())),
        rotulo_obrigatorio=rotulo,
    )
