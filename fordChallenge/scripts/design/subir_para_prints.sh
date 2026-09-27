#!/usr/bin/env bash
# Sobe uma API só para o ciclo de autocorreção visual da interface v2.
#
# Porta e banco próprios, `REPLAY_MODE=1` e sem autenticação: nenhuma rede sai, nenhum custo
# de LLM, e a base do onboarding não é tocada. É a mesma receita do `web-smoke.sh`, com
# uma diferença: aqui a API **fica no ar** para o `playwright-cli` navegar à mão entre uma
# correção e outra, em vez de subir e cair dentro de um portão.
#
#   scripts/design/subir_para_prints.sh          # sobe (reaproveita a base se existir)
#   scripts/design/subir_para_prints.sh --limpar # remonta a base do zero
#   scripts/design/subir_para_prints.sh --parar  # derruba
#
# A base é remontada quando falta, e não a cada chamada: montá-la leva ~40 s (cinco
# extrações em replay) e o ciclo visual roda dezenas de vezes por noite.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ=$(pwd)
export PYTHONUTF8=1

PORTA=${PORTA_DO_DESIGN:-8012}
PASTA="$RAIZ/.tmp/design"
BANCO_ARQ="$PASTA/design.db"
LOG="$PASTA/api.log"
PID_ARQ="$PASTA/api.pid"
mkdir -p "$PASTA"

PY="$RAIZ/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$RAIZ/.venv/bin/python"
[ -x "$PY" ] || { echo "FALTA: nao existe .venv. Rode: uv sync"; exit 1; }

parar() {
  if [ -f "$PID_ARQ" ]; then
    kill "$(cat "$PID_ARQ")" >/dev/null 2>&1 || true
    rm -f "$PID_ARQ"
    echo "API da porta $PORTA derrubada."
  else
    echo "Nada rodando (sem $PID_ARQ)."
  fi
}

case "${1:-}" in
  --parar) parar; exit 0 ;;
  --limpar) rm -f "$BANCO_ARQ" ;;
esac

parar >/dev/null 2>&1 || true

if [ ! -f "$RAIZ/web/dist/index.html" ]; then
  echo "FALTA: web/dist. Rode: cd web && npm run build"
  exit 1
fi

BANCO_URL=$("$PY" -c "import pathlib,sys; print('sqlite:///' + pathlib.Path(sys.argv[1]).resolve().as_posix())" "$BANCO_ARQ")
export DATABASE_URL="$BANCO_URL"
export REPLAY_MODE=1
export LLM_FAKE=1
export AUTH_ENABLED=0
export RATE_LIMIT_ENABLED=0
# Mesma razão do web-smoke: o ciclo abre dezenas de telas em segundos, o que nenhuma
# pessoa faz, e com o limite de produção o print sairia de uma página de 429.

if [ ! -f "$BANCO_ARQ" ]; then
  echo "== montando a base (uma vez; ~40 s) =="
  "$PY" scripts/demo/preparar_base.py --banco "$BANCO_URL" --sem-papeis >"$PASTA/base.log" 2>&1 || {
    echo "FALTA: a base nao montou. Ultimas linhas:"; tail -20 "$PASTA/base.log"; exit 1; }
fi

"$PY" -m uvicorn api.app.main:app --host 127.0.0.1 --port "$PORTA" >"$LOG" 2>&1 &
echo $! >"$PID_ARQ"

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORTA/api/v1/health" >/dev/null 2>&1; then
    echo "no ar: http://127.0.0.1:$PORTA/app"
    exit 0
  fi
  sleep 0.5
done

echo "FALTA: a API nao respondeu. Ultimas linhas do log:"
tail -20 "$LOG"
exit 1
