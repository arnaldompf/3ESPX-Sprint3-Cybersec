"""Customer Need Engine (WP-26): "qual carro para ESTE cliente?", com os pesos à vista.

O motor não diz qual picape é melhor — diz o quanto cada uma atende **ao perfil que o
vendedor digitou**, e é por isso que toda saída carrega o rótulo obrigatório de
`docs/12` §6.2: "Aderência ao perfil informado — não é um ranking de qualidade". Trocar o
perfil muda o número sem nada mudar no carro.

Os quatro módulos:

* `dimensions.py` + `dimensions.yaml` — campo → dimensão, direção e tipo de nota;
* `ranges.py` + `scoring_ranges.yaml` — a faixa contra a qual um valor vira nota 0–10,
  versionada e recalculada só por comando explícito;
* `engine.py` — perfil → pesos → notas → dimensões → aderência, com a decomposição;
* `usage_cost.py` — o custo mensal de combustível, com a fonte do consumo e a ressalva.
"""
