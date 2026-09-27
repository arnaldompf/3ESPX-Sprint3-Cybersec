#!/usr/bin/env bash
# WP-07 — Passo 0: resolvedor de versao e conectores de linha vigente.
#
# Comando da spec:
#   set -e; REPLAY_MODE=1 uv run pytest -q tests/pipeline/test_resolver.py \
#       tests/eval/test_resolver_negative.py
#
# Acrescentado: os parsers do caminho ao vivo (que rodam sem rede), a garantia de que
# REPLAY_MODE=1 realmente bloqueia HTTP, e a checagem de que as fixtures de linha vigente
# conferem com o gerador. Fonte bloqueada continua sendo status, nunca truque.
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1 REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/6] ruff =="
$UV run ruff check pipeline tests/pipeline tests/eval scripts
$UV run ruff format --check pipeline tests/pipeline tests/eval scripts

echo "== [2/6] testes do resolvedor =="
$UV run pytest -q tests/pipeline/test_resolver.py tests/eval/test_resolver_negative.py

echo "== [3/6] parsers do caminho ao vivo (sem rede) =="
$UV run pytest -q tests/pipeline/test_connectors_live_parsers.py

echo "== [4/6] fixtures de linha vigente conferem com o gerador =="
$UV run python scripts/build_fixtures.py --check

echo "== [5/6] os quatro criterios de aceite da spec =="
$UV run python -c "
from pipeline.resolver import resolve

r = resolve('Toyota', 'Hilux', 'GR-Sport')
assert r.status == 'versao_inexistente', r.status
assert 'SRX Plus AT' in r.alternatives, r.alternatives
assert 'nao esta na linha vigente' in r.mensagem.replace('ã','a').replace('á','a'), r.mensagem

r = resolve('Chevrolet', 'S10', 'high country')
assert (r.status, r.matched_version) == ('encontrada', 'S10 High Country'), r

r = resolve('Ford', 'Ranger', 'Raptor 4x4')
assert r.status == 'encontrada', r
assert r.matched_version.startswith('Raptor 3.0 V6 Bi-turbo'), r.matched_version

r = resolve('VW', 'Amarok', 'Extreme')
assert (r.status, r.matched_version) == ('encontrada', 'V6 Extreme'), r
print('   ok: GR-Sport negativo, S10/Raptor/Amarok resolvidas')
"

echo "== [6/6] REPLAY_MODE=1 bloqueia a rede =="
$UV run python -c "
from pipeline.connectors import _http
try:
    _http.get_text('https://www.ford.com.br/picapes/ranger/')
except _http.RedeProibidaEmReplay as exc:
    print(f'   ok: {exc}'[:110])
else:
    raise SystemExit('ERRO: houve tentativa de rede em REPLAY_MODE=1')
"

echo "WP-07 OK"
