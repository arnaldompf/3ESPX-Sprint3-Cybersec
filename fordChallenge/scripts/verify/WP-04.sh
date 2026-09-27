#!/usr/bin/env bash
# WP-04 -- nucleo da API: app, settings, erros padronizados, health, OpenAPI.
#
# Comando da spec:
#   set -e; uv run pytest -q tests/api/test_core.py
#   uv run python -c "from api.app.main import app; import json; json.dumps(app.openapi())"
#
# Acrescentado, cada item por um motivo:
#   (a) ruff check + format, escopados em api/ e tests/api/ como no WP-01 e no WP-03: o
#       verify de uma WP nao deve quebrar por arquivo em voo de outra trilha.
#   (b) o 404 saindo em `application/problem+json` com `instance` == X-Request-ID, que e o
#       segundo criterio de aceite e nao aparece no comando da spec.
#   (c) o 500 sem stack trace na resposta, com a rota de excecao ligada por
#       SPECRADAR_DEBUG_BOOM=1 -- terceiro criterio de aceite.
#   (d) banco proprio (data/verify_wp04.db), apagado no fim: /health abre conexao de
#       verdade e o verify nao mexe no banco de dev de ninguem.
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"

BANCO="data/verify_wp04.db"
export DATABASE_URL="sqlite:///./${BANCO}"
export CORS_ORIGINS="http://localhost:5173"
export LOG_LEVEL=INFO
export REPLAY_MODE=1
export LLM_FAKE=1

mkdir -p data
limpar() { rm -f "$BANCO"; }
trap limpar EXIT

echo "== [1/5] ruff em api e tests/api =="
$UV run ruff check api tests/api
$UV run ruff format --check api tests/api

echo "== [2/5] testes do WP-04 =="
$UV run pytest -q tests/api/test_core.py

echo "== [3/5] OpenAPI serializa em JSON =="
$UV run python -c "
from api.app.main import app; import json; json.dumps(app.openapi())
esquema = app.openapi()
assert esquema['info']['title'] == 'SpecRadar API', esquema['info']['title']
assert esquema['info']['version'], 'version vazia no OpenAPI'
assert esquema['info']['description'].strip(), 'description vazia no OpenAPI'
assert 'saude' in {t['name'] for t in esquema['tags']}, esquema['tags']
assert '/api/v1/_debug/boom' not in esquema['paths'], 'rota de excecao vazou para o schema'
saude = esquema['paths']['/api/v1/health']['get']['responses']
exemplo = saude['404']['content']['application/problem+json']['example']
assert exemplo['status'] == 404 and exemplo['instance'], exemplo
assert 'Problema' in esquema['components']['schemas']
print('   ok: OpenAPI ' + esquema['info']['version'] + ' serializa, com tags e exemplos de erro')
"

echo "== [4/5] health 200 e 404 em problem+json =="
$UV run python -c "
from fastapi.testclient import TestClient
from api.app.main import create_app

with TestClient(create_app()) as cliente:
    saude = cliente.get('/api/v1/health')
    assert saude.status_code == 200, saude.status_code
    corpo = saude.json()
    assert corpo['db']['ok'] is True, corpo['db']
    assert corpo['db']['dialeto'] == 'sqlite', corpo['db']
    assert corpo['version'], corpo
    assert corpo['etiqueta'] == 'FATO', corpo
    assert '${DATABASE_URL}' not in saude.text, 'a URL do banco vazou no /health'
    assert saude.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'Strict-Transport-Security' not in saude.headers, 'HSTS nao entra em dev'

    erro = cliente.get('/api/v1/nao-existe')
    assert erro.status_code == 404, erro.status_code
    tipo = erro.headers['content-type']
    assert tipo.startswith('application/problem+json'), tipo
    problema = erro.json()
    assert problema['instance'] == erro.headers['X-Request-ID'], problema
    assert {'type','title','status','detail','instance'} <= set(problema), problema
print('   ok: /health = 200 com db e version; 404 em problem+json com instance = request-id')
"

echo "== [5/5] 500 sem stack trace (SPECRADAR_DEBUG_BOOM=1) =="
SPECRADAR_DEBUG_BOOM=1 $UV run python -c "
from fastapi.testclient import TestClient
from api.app.main import create_app

with TestClient(create_app(), raise_server_exceptions=False) as cliente:
    resposta = cliente.get('/api/v1/_debug/boom')
assert resposta.status_code == 500, resposta.status_code
assert resposta.headers['content-type'].startswith('application/problem+json')
corpo = resposta.json()
assert corpo['instance'] == resposta.headers['X-Request-ID'], corpo
for marca in ('Traceback', 'RuntimeError', 'main.py', 'line ', 'raise '):
    assert marca not in resposta.text, 'stack trace vazou na resposta: ' + marca
print('   ok: 500 em problem+json, sem stack trace, com instance para correlacao')
"

echo "WP-04 OK"
