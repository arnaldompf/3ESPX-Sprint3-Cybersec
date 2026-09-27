"""Conectores de linha vigente, por marca.

`conector_de("Toyota")` devolve o conector dedicado; marca desconhecida cai no
:class:`GenericConnector` (tier 3), que responde "linha vigente desconhecida" em vez de
adivinhar.
"""

from __future__ import annotations

from pipeline.connectors.base import (
    Connector,
    FonteBloqueada,
    LinhaVigenteIndisponivel,
    ResultadoLinha,
    SourceRef,
    VersionInfo,
    normalizar_versao,
    parse_lineup_md,
)
from pipeline.connectors.chevrolet import ChevroletConnector
from pipeline.connectors.ford import FordConnector
from pipeline.connectors.generic import GenericConnector
from pipeline.connectors.toyota import ToyotaConnector
from pipeline.connectors.vw import VWConnector

#: Aliases de marca que aparecem na entrada do usuário e nas fontes.
ALIASES: dict[str, str] = {
    "ford": "Ford",
    "toyota": "Toyota",
    "vw": "Volkswagen",
    "volkswagen": "Volkswagen",
    "chevrolet": "Chevrolet",
    "gm": "Chevrolet",
    "general motors": "Chevrolet",
}

CONECTORES: dict[str, type[Connector]] = {
    "Ford": FordConnector,
    "Toyota": ToyotaConnector,
    "Volkswagen": VWConnector,
    "Chevrolet": ChevroletConnector,
}


def marca_canonica(marca: str) -> str | None:
    """`"vw"` -> `"Volkswagen"`; marca desconhecida -> `None`."""
    return ALIASES.get(normalizar_versao(marca))


def conector_de(marca: str) -> Connector:
    """Conector da marca, ou o genérico (tier 3) quando não há um dedicado."""
    canonica = marca_canonica(marca)
    if canonica and canonica in CONECTORES:
        return CONECTORES[canonica]()
    return GenericConnector(marca)


__all__ = [
    "ALIASES",
    "CONECTORES",
    "ChevroletConnector",
    "Connector",
    "FonteBloqueada",
    "FordConnector",
    "GenericConnector",
    "LinhaVigenteIndisponivel",
    "ResultadoLinha",
    "SourceRef",
    "ToyotaConnector",
    "VWConnector",
    "VersionInfo",
    "conector_de",
    "marca_canonica",
    "normalizar_versao",
    "parse_lineup_md",
]
