"""Change Radar: os alertas tipados, o impacto comercial e a reação sugerida.

O diferencial nº 1 do produto (`docs/12` §6.1): *"o que mudou no mercado, com prova,
impacto e o que fazer"*. Três módulos, cada um com uma responsabilidade:

* `tipos.py` — classifica a mudança nos sete tipos de `docs/12` §6.1 e monta o alerta com
  **as duas** evidências;
* `impact.py` — o impacto comercial, por regra: delta, percentual, gap antes/depois contra
  o equivalente Ford, dimensões afetadas;
* `reactions.py` — a reação sugerida por papel (marketing, vendas, produto, CI), de uma
  tabela de regras;
* `internal.py` — a referência interna do cliente (tier 0) e a divergência contra a fonte
  pública.

**Nada aqui usa LLM**, e a spec é explícita nisso. A razão é simples: o impacto é uma
subtração e a reação sugere ação sobre dinheiro. Subtração que um modelo pode errar não
deveria passar por um modelo, e conselho que muda entre execuções faria duas pessoas
lerem o mesmo alerta e agirem diferente.

**Nenhum alerta nasce sem evidência** (nota da spec). É a mesma regra da ficha: valor sem
procedência não existe, e um alerta é uma afirmação sobre dois valores.
"""

from pipeline.radar.impact import Impacto, calcular
from pipeline.radar.internal import (
    TIER_INTERNO,
    Divergencia,
    ReferenciaInvalida,
    comparar_com_publico,
    importar,
)
from pipeline.radar.reactions import PAPEIS, Reacoes, sugerir
from pipeline.radar.tipos import AlertaDetectado, classificar, detectar

__all__ = [
    "PAPEIS",
    "TIER_INTERNO",
    "AlertaDetectado",
    "Divergencia",
    "Impacto",
    "Reacoes",
    "ReferenciaInvalida",
    "calcular",
    "classificar",
    "comparar_com_publico",
    "detectar",
    "importar",
    "sugerir",
]
