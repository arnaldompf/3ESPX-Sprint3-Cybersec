#!/usr/bin/env bash
# WP-08 — fetcher educado: robots.txt, rate limit, snapshots e replay.
#
# Comando da spec:
#   set -e; REPLAY_MODE=1 uv run pytest -q tests/pipeline/test_fetch.py -m "not live"
#
# Acrescentado: uma prova dura de que REPLAY_MODE=1 nao acessa a rede — o socket e morto
# no processo antes do fetch. "Nao faz requisicao" verificado por mock e uma promessa
# sobre o mock; com o socket morto, e uma promessa sobre o processo.
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1 REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/5] ruff =="
$UV run ruff check pipeline tests/pipeline
$UV run ruff format --check pipeline tests/pipeline

echo "== [2/5] testes do fetcher (sem os marcados live) =="
$UV run pytest -q tests/pipeline/test_fetch.py -m "not live"

echo "== [3/5] replay com o socket morto =="
$UV run python -c "
# Importar ANTES de matar o socket: httpx e anyio tocam socket na importacao, e
# substituir a classe antes disso quebra o import com erro que nao tem nada a ver.
from pipeline.fetch import http
from pipeline.snapshots import SnapshotMissing

import socket
def proibido(*a, **k):
    raise AssertionError('houve tentativa de acesso a rede')
socket.socket = proibido
socket.create_connection = proibido

r = http.fetch('https://www.ford.com.br/picapes/ranger-raptor/raptor-4wd-at/')
assert r.status == 'replay', r.status
assert '397' in r.texto
try:
    http.fetch('https://exemplo.test/sem-snapshot')
except SnapshotMissing:
    pass
else:
    raise SystemExit('ERRO: URL sem snapshot deveria levantar SnapshotMissing')
print('   ok: replay resolveu por snapshot e a ausencia levantou, sem socket')
"

echo "== [4/5] indice por URL prefere a pagina oficial ao registro de evidencia =="
$UV run python -c "
from pipeline.snapshots import snapshot_de_url, todos_os_snapshots_de_url
from pipeline.store import FIXTURES
url = 'https://www.toyota.com.br/modelos/hilux-cabine-dupla'
todos = todos_os_snapshots_de_url(url, [FIXTURES])
assert len(todos) >= 2, todos
melhor = snapshot_de_url(url, [FIXTURES])
assert melhor.tipo == 'pagina_oficial', melhor.tipo
print(f'   ok: {len(todos)} snapshots para a URL, escolhido {melhor.source_id}')
"

echo "== [5/5] o caminho de navegador esta declarado, instalado ou nao =="
REPLAY_MODE=0 $UV run python -c "
from pipeline.fetch import browser
if browser.disponivel():
    print('   ok: extra collect instalado (Crawl4AI presente)')
else:
    r = browser.fetch_browser('https://exemplo.test/x')
    assert 'crawl4ai-setup' in r.motivo, r.motivo
    print('   ok: extra collect ausente, e o motivo diz exatamente o que instalar')
"
# e, em replay, o navegador manda usar o snapshot em vez de abrir Chromium
$UV run python -c "
from pipeline.fetch import browser
r = browser.fetch_browser('https://www.ford.com.br/picapes/ranger/')
assert not r.ok and 'REPLAY_MODE' in r.motivo, r.motivo
print('   ok: em replay o navegador remete ao snapshot')
"

echo "WP-08 OK"
