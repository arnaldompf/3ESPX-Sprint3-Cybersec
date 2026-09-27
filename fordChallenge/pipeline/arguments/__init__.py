"""Argumentário verificado (WP-27): três pontos com nota fiscal, e um de atenção.

O caminho padrão é o **template determinístico** (`template.py`): ele funciona sem rede,
sem chave de API e sem LLM, e cada frase carrega os `evidence_id` que a sustentam. O LLM é
bônus (`llm_rewrite.py`), e passa por um **verificador** (`verify.py`) que confere se todo
número, unidade e nome de item do texto existe nas células — falhou, volta o template.

A ordem importa: um argumentário que só funciona com LLM é um argumentário que não funciona
na hora em que a rede cai no showroom.
"""
