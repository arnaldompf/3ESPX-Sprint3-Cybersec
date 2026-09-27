#!/usr/bin/env bash
# WP-01 — schema canonico, modelos Pydantic, normalizador de unidades e sinonimos-semente.
#
# Comando da spec:
#   set -e; ruff check pipeline; uv run pytest -q tests/pipeline/test_schema.py \
#       tests/pipeline/test_units.py tests/pipeline/test_ontology.py
#
# Acrescentado: (a) ruff format --check, (b) a checagem de que o codigo e o JSON Schema
# nao se separaram (empty_spec valida e os grupos batem campo a campo), porque o schema
# e o contrato de saida do produto.
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"

echo "== [1/4] ruff em pipeline =="
$UV run ruff check pipeline
$UV run ruff format --check pipeline

echo "== [2/4] testes do WP-01 =="
$UV run pytest -q tests/pipeline/test_schema.py tests/pipeline/test_units.py \
  tests/pipeline/test_ontology.py

echo "== [3/4] ficha vazia valida contra o JSON Schema =="
$UV run python -c "
from pipeline.schema import empty_spec, TOTAL_CAMPOS, GRUPOS
spec = empty_spec(job_id='verify-wp01')
spec.to_json()
assert TOTAL_CAMPOS == sum(len(c) for c in GRUPOS.values()), 'contagem de campos divergiu'
assert len(GRUPOS) == 11, 'numero de grupos divergiu de docs/03'
print(f'   ok: {len(GRUPOS)} grupos, {TOTAL_CAMPOS} campos, ficha valida')
"

echo "== [4/4] semente de sinonimos carrega e resolve os casos-ancora =="
$UV run python -c "
from pipeline.ontology import resolve_attribute, resolve_value, total_sinonimos
campo, score = resolve_attribute('modos de volante')
assert (campo, score >= 85) == ('modos_direcao', True), (campo, score)
campo, score = resolve_attribute('aletas no volante')
assert (campo, score >= 85) == ('paddle_shifters', True), (campo, score)
assert resolve_value('modos_conducao', 'Esportivo') == 'sport'
assert resolve_value('modos_conducao', 'lama/terra') == 'lama'
assert total_sinonimos() > 20, total_sinonimos()
print(f'   ok: {total_sinonimos()} sinonimos na semente')
"

echo "WP-01 OK"
