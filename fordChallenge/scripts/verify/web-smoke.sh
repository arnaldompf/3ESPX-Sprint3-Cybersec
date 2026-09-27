#!/usr/bin/env bash
# web-smoke — todas as 8 rotas, nos 4 papeis, abertas num Chromium de verdade (D-188).
#
# O portao que faltava. Em 11/09/2026 as rotas respondiam 200, o content-type estava
# certo, `tests/api/test_web.py` passava — e a tela abria BRANCA no Chrome: a CSP
# `default-src 'none'` bloqueava o bundle (D-184). `curl` e o `TestClient` nao aplicam
# CSP; navegador aplica. Daqui em diante, "funciona" so vale com print renderizado.
#
# O que este script faz:
#   1. confere que ha build (`web/dist`) e Chromium;
#   2. sobe uma API propria, numa porta propria, em REPLAY_MODE=1;
#   3. chama `scripts/verify/web_smoke.py`, que troca de papel CLICANDO no seletor da barra
#      lateral e abre as 8 rotas, exigindo <h1> visivel, zero erro de console e print
#      nao-branco;
#   4. derruba a API que subiu (e so ela).
#
# Rede: nenhuma. REPLAY_MODE=1 bloqueia socket; o Chromium fala so com 127.0.0.1.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ=$(pwd)
export PYTHONUTF8=1

PORTA=${PORTA_DO_SMOKE:-8011}
BASE="http://127.0.0.1:${PORTA}"
PASTA="$RAIZ/.tmp/web-smoke"
BANCO_ARQ="$PASTA/smoke.db"
LOG="$PASTA/api.log"
mkdir -p "$PASTA"

PY="$RAIZ/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$RAIZ/.venv/bin/python"
[ -x "$PY" ] || { echo "FALTA: nao existe .venv. Rode: uv sync"; exit 1; }

echo "== [1/5] pre-requisitos =="
if [ ! -f "$RAIZ/web/dist/index.html" ]; then
  echo "SALTADO: web/dist ausente. Construa antes:  cd web && npm ci && npm run build"
  exit 0
fi
if ! "$PY" -c "import playwright, PIL" >/dev/null 2>&1; then
  echo "SALTADO: playwright ou pillow ausentes no .venv."
  exit 0
fi
if ! "$PY" - <<'EOF' >/dev/null 2>&1
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    p.chromium.launch().close()
EOF
then
  echo "SALTADO: Chromium do Playwright nao instalado. Rode:  .venv/Scripts/python -m playwright install chromium"
  exit 0
fi
echo "   ok: build presente, playwright + chromium prontos"

echo "== [2/5] base descartavel =="
# Banco proprio: o smoke NAO pode depender de (nem sujar) a base do onboarding.
rm -f "$BANCO_ARQ"
# Em Windows o `bash.exe` pode ser o WSL, enquanto o Python da venv é Win32. Passar
# `/mnt/c/...` ao Python produz `C:/mnt/c/...`; além disso o stdout Win32 termina em CRLF
# e o `\r` acabava dentro da URL. Resolver o caminho relativo no próprio Python e limpar
# o terminador deixa o smoke igual no Git Bash, WSL e Linux.
BANCO_URL=$("$PY" -c "import pathlib; print('sqlite:///' + pathlib.Path('.tmp/web-smoke/smoke.db').resolve().as_posix())" | tr -d '\r')
export DATABASE_URL="$BANCO_URL"
export REPLAY_MODE=1
export LLM_FAKE=1
# O padrao do produto desde D-204: sem autenticacao e sem limite de requisicoes. Escrito
# aqui e nao deixado por omissao porque o `.env` da maquina e lido pelo pydantic-settings.
export AUTH_ENABLED=0
export RATE_LIMIT_ENABLED=0
"$PY" scripts/demo/preparar_base.py --banco "$BANCO_URL" --sem-papeis >/dev/null
echo "   ok: base montada em .tmp/web-smoke/smoke.db"

echo "== [3/5] API na porta $PORTA =="
"$PY" -m uvicorn api.app.main:app --host 127.0.0.1 --port "$PORTA" >"$LOG" 2>&1 &
PID_API=$!
# O trap garante que a API morre mesmo se o smoke falhar no meio.
limpar() { kill "$PID_API" >/dev/null 2>&1 || true; wait "$PID_API" 2>/dev/null || true; }
trap limpar EXIT

PRONTA=0
for _ in $(seq 1 60); do
  if curl -fsS "$BASE/api/v1/health" >/dev/null 2>&1; then PRONTA=1; break; fi
  sleep 0.5
done
if [ "$PRONTA" -ne 1 ]; then
  echo "FALTA: a API nao respondeu em $BASE. Ultimas linhas do log:"
  tail -20 "$LOG"
  exit 1
fi
# O smoke troca de papel pela barra lateral; com autenticacao ligada a tela pediria login.
curl -fsS "$BASE/api/v1/health" | grep -q '"auth_enabled":false' || {
  echo "FALTA: esta API esta com AUTH_ENABLED=1; o smoke abre o app sem credencial."
  exit 1
}
echo "   ok: /health respondeu e auth_enabled=false"

echo "== [4/5] 4 papeis x 8 rotas no Chromium =="
"$PY" scripts/verify/web_smoke.py --base "$BASE"

echo "== [5/5] o indice dos prints =="
test -f reports/screens/README.md
echo "   ok: reports/screens/README.md"

echo "web-smoke OK"
