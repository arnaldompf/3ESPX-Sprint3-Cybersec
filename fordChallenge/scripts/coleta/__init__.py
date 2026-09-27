"""Coleta ao vivo — os scripts que saem para a rede.

Separados de `scripts/` porque **saem para a internet**: nenhum deles roda no CI, e
nenhum é chamado por teste. O que eles produzem entra no repositório por dois caminhos
declarados: `data/snapshots/` (a captura, com o bruto ao lado) e `gabarito/raw/` (o texto
que `scripts/build_fixtures.py` transforma em fixture de replay).
"""
