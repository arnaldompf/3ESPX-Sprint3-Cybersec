#!/usr/bin/env bash
# WP-31 — web app responsivo com as etiquetas FATO / INFERENCIA / SIMULACAO.
#
# Comando da spec:
#   set -e; cd web && npm ci && npx tsc --noEmit && npx eslint . && npx vitest run \
#       && npm run build && test -d dist
#
# Acrescentado: os criterios de aceite conferidos direto, o FastAPI servindo o build em
# /app com fallback de SPA, e a regra visual do produto (nenhum numero sem etiqueta).
#
# PLAYWRIGHT NAO ENTRA. O comando da spec nao o inclui, e a razao de eu nao ter
# acrescentado e concreta: ele baixa navegadores (centenas de MB) na primeira execucao, e
# a regra da noite e "rede so o necessario". Um portao que so passa depois de um download
# de 300 MB nao e portao — e um obstaculo que a proxima pessoa desliga. O criterio de
# 390 px esta coberto em `web/src/test/viewport.test.tsx`, que mede as classes CSS onde o
# problema nasce; `web/e2e/viewport.spec.ts` esta escrito para quem quiser rodar no
# navegador (`npm run e2e`), e esta declarado como nao verificado.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ=$(pwd)

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1

echo "== [1/7] node e npm =="
node -v
npm -v

echo "== [2/7] dependencias =="
cd "$RAIZ/web"
# `npm ci` exige o lock em sincronia com o package.json, que e o que se quer num portao.
npm ci --no-fund --no-audit >/dev/null
echo "   ok: node_modules a partir do package-lock.json"

echo "== [3/7] tipos e lint =="
npx tsc --noEmit
npx eslint .
echo "   ok: zero erro de tipo e de lint"

echo "== [4/7] testes de componente =="
npx vitest run

echo "== [5/7] build =="
npm run build >/dev/null
test -d dist
test -f dist/index.html
# "Sem bibliotecas de UI pesadas" (notas da spec) fica verificavel, e nao so declarada.
TAMANHO=$(find dist/assets -name '*.js' -exec ls -l {} \; | awk '{soma += $5} END {print int(soma/1024)}')
echo "   ok: dist/ construido, $TAMANHO KB de JS"
test "$TAMANHO" -lt 600 || { echo "FALTA: $TAMANHO KB de JS e muito para 'sem UI pesada'"; exit 1; }

echo "== [6/7] a regra visual: nenhum numero sem etiqueta =="
cd "$RAIZ"
$UV run python -c "
import pathlib, re, sys

fonte = pathlib.Path('web/src/components/FieldRow.tsx').read_text(encoding='utf-8')
# A Badge tem de ser INCONDICIONAL na linha do campo: se ela estiver dentro de um
# ternario ou de um && , existe um caminho em que um valor aparece sem etiqueta.
assert '<Badge etiqueta={etiqueta}' in fonte, 'a linha do campo perdeu a Badge'
trecho = fonte[fonte.index('<Badge etiqueta={etiqueta}') - 200 : fonte.index('<Badge etiqueta={etiqueta}')]
assert '&&' not in trecho.split('</div>')[-1], 'a Badge ficou condicional'

etiqueta = pathlib.Path('web/src/lib/etiqueta.ts').read_text(encoding='utf-8')
# is_simulated vence qualquer status, e a checagem vem ANTES do mapa.
assert etiqueta.index('is_simulated') < etiqueta.index('POR_STATUS[campo.status]')
# Os seis status do schema estao mapeados.
from pipeline.schema import Status
for s in Status:
    assert f'{s.value}:' in etiqueta, f'status {s.value} sem etiqueta mapeada'
print(f'   ok: Badge incondicional, is_simulated com precedencia, {len(list(Status))} status mapeados')
"

echo "== [7/7] o FastAPI serve /app com fallback de SPA =="
$UV run pytest -q tests/api/test_web.py

echo "WP-31 OK"
