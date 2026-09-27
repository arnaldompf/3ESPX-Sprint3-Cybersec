#!/usr/bin/env bash
# WP-02 — loader do gabarito, fixtures de replay e eval harness.
#
# Comando da spec:
#   set -e; uv run pytest -q tests/eval/test_compare.py; uv run specradar eval --replay;
#   python -c "import json;d=json.load(open('reports/eval.json'));assert 'field_accuracy' in d['aggregate']"
#
# Acrescentado: as fixtures conferem com gabarito/raw/ (elas sao geradas, nao copiadas),
# e as 9 metricas de docs/09 aparecem no relatorio. O eval e o oraculo do projeto: se ele
# roda mas nao mede, o verde nao vale nada.
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1 REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/6] ruff =="
$UV run ruff check pipeline tests/eval scripts
$UV run ruff format --check pipeline tests/eval scripts

echo "== [2/6] testes do eval =="
$UV run pytest -q tests/eval/test_compare.py tests/eval/test_gabarito.py \
  tests/eval/test_run.py tests/eval/test_fixtures.py

echo "== [3/6] fixtures conferem com gabarito/raw/ =="
$UV run python scripts/build_fixtures.py --check

echo "== [4/6] specradar eval --replay =="
$UV run specradar eval --replay

echo "== [5/6] relatorios tem as 9 metricas de docs/09 =="
$UV run python -c "
import json
d = json.load(open('reports/eval.json', encoding='utf-8'))
agg = d['aggregate']
esperadas = ['field_accuracy','status_fidelity','hallucination_rate','grounding_rate',
             'coverage','resolver_accuracy','slide_divergences_found',
             'time_per_vehicle_s','cost_per_vehicle_brl']
faltando = [m for m in esperadas if m not in agg]
assert not faltando, f'metricas ausentes: {faltando}'
assert 'field_accuracy' in d['aggregate']
assert agg['coverage']['valor'] == 1.0, agg['coverage']
# denominador visivel: metrica sem n aparece como null, nunca como zero
for nome in esperadas[:7]:
    m = agg[nome]
    assert (m['n'] == 0) == (m['valor'] is None), (nome, m)
print(f'   ok: {len(esperadas)} metricas, coverage=1.0, denominadores coerentes')
"

echo "== [6/6] eval.md e legivel e expoe o que ficou fora =="
$UV run python -c "
md = open('reports/eval.md', encoding='utf-8').read()
for marca in ['Relat', 'Agregado', 'Por ve', 'Resolvedor de vers', 'Fora da avalia']:
    assert marca in md, f'secao ausente no eval.md: {marca}'
print('   ok: relatorio completo')
"

echo "WP-02 OK"
