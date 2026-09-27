"""Benchmark: de uma versão Ford ao conjunto de concorrentes que vale comparar.

O módulo responde a **uma** pergunta — *contra quem esta Ford briga?* — e para de
propósito ali. Quem decide se um par específico é comparável é `pipeline/comparables.py`,
pelos sete critérios versionados; quem monta a matriz é `pipeline/parity.py`. Separar as
três coisas é o que permite trocar a régua sem reescrever o mapa.
"""

from pipeline.benchmark.segments import (
    Concorrente,
    Segmento,
    SegmentoDesconhecido,
    carregar,
    concorrentes_de,
    consulta_de_descoberta,
    segmento_de,
)

__all__ = [
    "Concorrente",
    "Segmento",
    "SegmentoDesconhecido",
    "carregar",
    "concorrentes_de",
    "consulta_de_descoberta",
    "segmento_de",
]
