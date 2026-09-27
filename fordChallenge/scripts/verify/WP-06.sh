#!/usr/bin/env bash
# WP-06 — recursos REST do dominio, spec_assembler e OpenAPI.
#
# Comando da spec:
#   set -e; uv run pytest -q tests/api/test_resources.py tests/api/test_contract_schema.py
#   uv run python scripts/export_openapi.py && test -f reports/openapi.json
#
# Acrescentado: os tres criterios de aceite conferidos direto, e a regra que da nome ao
# spec_assembler — o filtro `attributes` esconde VALOR, nunca campo.
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1

echo "== [1/6] ruff =="
$UV run ruff check api pipeline scripts tests
$UV run ruff format --check api pipeline scripts tests

echo "== [2/6] testes da spec =="
$UV run pytest -q tests/api/test_resources.py tests/api/test_contract_schema.py

echo "== [3/6] os tres criterios de aceite =="
$UV run pytest -q tests/api -k "CriteriosDeAceite" 2>&1 | tail -3

echo "== [4/6] OpenAPI exportado e conferido =="
$UV run python scripts/export_openapi.py
test -f reports/openapi.json
$UV run python scripts/export_openapi.py --check

echo "== [5/6] o filtro esconde VALOR, nunca campo =="
$UV run python -c "
from pipeline.schema import GRUPOS
from api.app.services.spec_assembler import NOTA_NAO_PEDIDO, campos_pedidos

# O parser do parametro aceita as duas formas que cliente HTTP de verdade usa.
assert campos_pedidos('potencia_cv,torque_nm') == {'potencia_cv', 'torque_nm'}
assert campos_pedidos(['potencia_cv', 'torque_nm']) == {'potencia_cv', 'torque_nm'}
assert campos_pedidos(['motorizacao.potencia_cv']) == {'potencia_cv'}
assert campos_pedidos(None) is None, 'sem filtro = ficha inteira'
assert campos_pedidos('') is None, 'filtro vazio = ficha inteira, nao ficha vazia'
assert 'solicitado' in NOTA_NAO_PEDIDO and 'attributes' in NOTA_NAO_PEDIDO
print(f'   ok: filtro parseado nas duas formas; {sum(len(c) for c in GRUPOS.values())} campos sempre presentes')
"

echo "== [6/6] a matriz marca diff quando um lado esta vazio =="
$UV run python -c "
from api.app.services.spec_assembler import _difere
from pipeline.schema import SpecField, Status

cheio = SpecField(value=397, status=Status.NAO_VERIFICADO)
outro = SpecField(value=204, status=Status.NAO_VERIFICADO)
vazio = SpecField(value=None, status=Status.NAO_ENCONTRADO)

assert _difere(cheio, outro) is True, 'valores diferentes tem de divergir'
assert _difere(cheio, cheio) is False
assert _difere(cheio, vazio) is True, 'vazio contra valor E divergencia'
assert _difere(vazio, vazio) is False, 'dois vazios nao divergem'
print('   ok: \"o concorrente tem e nos nao sabemos\" aparece como diff')
"

echo "WP-06 OK"
