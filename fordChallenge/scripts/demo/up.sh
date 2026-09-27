#!/usr/bin/env bash
# Sobe o SpecRadar inteiro com um comando: banco, migracoes, seed, API e web app.
#
# Gemeo de `up.ps1`. As duas cascas fazem a mesma coisa e chamam o MESMO preparador
# (`scripts/demo/preparar_base.py`) — a sequencia de preparo nao existe duas vezes, so a
# parte de processo, que e o unico pedaco genuinamente diferente entre bash e PowerShell.
#
# O worker sobe junto de proposito: o documento do cliente sai por job, e sem worker a cena
# do Copiloto para em "pendente" (docs/demo/ROTEIRO_15SET.md).
#
# Banco: `data/onboarding/onboarding.db`, proprio e descartavel. NAO toca `data/dev.db`.
# Rodar o onboarding duas vezes tem de dar os mesmos numeros, e `seed --simulated-alerts N`
# soma N alertas a cada chamada — num banco reaproveitado a fila do Radar cresceria.
#
# Rede: nenhuma. `REPLAY_MODE=1` bloqueia socket; as fontes vem dos snapshots salvos.
#
# Uso:
#   bash scripts/demo/up.sh                          # sobe
#   bash scripts/demo/up.sh --refazer                # apaga a base e monta de novo
#   bash scripts/demo/up.sh --refazer-web            # reconstroi o web app
set -uo pipefail

RAIZ=$(cd "$(dirname "$0")/../.." && pwd)
cd "$RAIZ"

PASTA="$RAIZ/data/onboarding"
LOGS="$PASTA/logs"
PROCS="$PASTA/processos.txt"
BANCO="$PASTA/onboarding.db"
PORTA=8000
ANFITRIAO=127.0.0.1
URLBASE="http://${ANFITRIAO}:${PORTA}"

REFAZER=0; REFAZER_WEB=0
for arg in "$@"; do
  case "$arg" in
    --refazer)        REFAZER=1 ;;
    --refazer-web)    REFAZER_WEB=1 ;;
    -h|--help) sed -n '1,25p' "$0"; exit 0 ;;
    *) echo "opcao desconhecida: $arg"; exit 2 ;;
  esac
done

titulo() { echo ""; printf '=%.0s' {1..78}; echo ""; echo "$1"; printf '=%.0s' {1..78}; echo ""; }
passo()  { echo "-- $1"; }
ok()     { echo "   ok: $1"; }
aviso()  { echo "   aviso: $1"; }
erro()   { echo "   ERRO: $1" >&2; }

titulo 'SPECRADAR — SUBINDO TUDO'

# ------------------------------------------------------------------ 0. pre-requisitos
passo 'conferindo o que a maquina tem'

# O python do projeto: `.venv/Scripts` no Windows (Git Bash), `.venv/bin` no resto.
PY="$RAIZ/.venv/bin/python"
[ -x "$PY" ] || PY="$RAIZ/.venv/Scripts/python.exe"
if [ ! -x "$PY" ]; then
  erro "nao existe .venv. Rode primeiro:  uv sync"
  exit 1
fi
ok "python do projeto: $PY"

if command -v node >/dev/null 2>&1; then
  ok "node $(node --version)"
  TEM_NODE=1
else
  aviso 'node ausente: o web app so sobe se web/dist ja estiver construido'
  TEM_NODE=0
fi

# Disco: o projeto ja parou uma vez por ENOSPC no meio de uma escrita (MANHA.md §4).
LIVRE_KB=$(df -Pk "$RAIZ" | awk 'NR==2 {print $4}')
if [ -n "${LIVRE_KB:-}" ] && [ "$LIVRE_KB" -lt 2097152 ]; then
  aviso "menos de 2 GB livres. O build do web app e as migracoes podem falhar."
  aviso "libere espaco:  npm cache clean --force  e  uv cache clean"
else
  ok "$(( ${LIVRE_KB:-0} / 1048576 )) GB livres"
fi

# Porta ocupada e a falha mais comum de segunda execucao: a API antiga ainda de pe, e a
# nova morre com "address already in use" num log que ninguem abre.
if "$PY" -c "
import socket,sys
s=socket.socket()
s.settimeout(1)
sys.exit(0 if s.connect_ex(('$ANFITRIAO', $PORTA))==0 else 1)
" 2>/dev/null; then
  aviso "a porta $PORTA ja esta em uso."
  aviso "derrube o que esta la antes:  bash scripts/demo/down.sh"
  exit 1
fi
ok "porta $PORTA livre"

mkdir -p "$PASTA" "$LOGS"

# -------------------------------------------------------------------------- 1. o banco
# A URL sai do PYTHON, nao do `pwd`. Defeito real e corrigido (D-148): no Git Bash do
# Windows `sqlite:///$(pwd)/...` fica com quatro barras e o SQLite cria o banco na RAIZ do
# drive — o script passava e o banco ficava no lugar errado.
BANCO_URL=$("$PY" -c "import pathlib,sys; print('sqlite:///' + pathlib.Path(sys.argv[1]).resolve().as_posix())" "$BANCO")
export DATABASE_URL="$BANCO_URL"
export PYTHONUTF8=1
export REPLAY_MODE=1
export LLM_FAKE=1
# O Pesquisador (WP-41) sobe ligado, em modo replay: as respostas de busca vem de
# `tests/fixtures/search`. A demo nao depende de buscador de pe nem de saldo em conta.
export RESEARCH_ENABLED=1
export SEARCH_PROVIDER=replay
# O Benchmark competitivo (FASE 3) sobe ligado. So le do catalogo local: nao sai para a
# internet nem gasta chamada de modelo. Para desligar sem editar este arquivo:
#   BENCHMARK_ENABLED=0 bash scripts/demo/up.sh
export BENCHMARK_ENABLED="${BENCHMARK_ENABLED:-1}"

if [ "$REFAZER" -eq 1 ] && [ -f "$BANCO" ]; then
  rm -f "$BANCO"
  ok 'base anterior do onboarding apagada (--refazer)'
fi

MODO=()
if [ -f "$BANCO" ]; then
  passo 'base do onboarding ja existe: reaproveitando (use --refazer para montar de novo)'
  MODO=(--so-usuarios)
fi

passo 'preparando a base'
if ! "$PY" scripts/demo/preparar_base.py --banco "$BANCO_URL" "${MODO[@]}" --sem-papeis; then
  erro 'o preparo da base falhou. Leia as linhas FALHOU acima; nada foi subido.'
  exit 1
fi

# ------------------------------------------------------------------------ 2. o web app
if [ "$REFAZER_WEB" -eq 1 ] || [ ! -f "$RAIZ/web/dist/index.html" ]; then
  if [ "$TEM_NODE" -eq 0 ]; then
    erro 'o web app nao esta construido e node nao existe nesta maquina.'
    erro 'a API sobe de qualquer forma; a tela em /app vai dar 404.'
  else
    passo 'construindo o web app (leva alguns minutos na primeira vez)'
    (
      cd "$RAIZ/web"
      if [ -d node_modules ]; then npm run build; else npm ci && npm run build; fi
    )
    if [ -f "$RAIZ/web/dist/index.html" ]; then ok 'web/dist construido'; else erro 'o build do web app falhou; /app vai dar 404'; fi
  fi
else
  ok 'web app ja construido (use --refazer-web para reconstruir)'
fi

# ----------------------------------------------------------- 3. API e worker, destacados
# `nohup ... &` mais `disown`: os processos sobrevivem ao fim deste script e ao fechamento
# do terminal. Eles herdam o ambiente daqui — e por isso a `DATABASE_URL` do onboarding
# vale para os dois sem editar o `.env`.
#
# `uvicorn` sem `--reload`: o recarregador sobe supervisor + filho, e o PID guardado aqui
# nao seria o que serve HTTP — o `down.sh` mataria o pai e deixaria a porta presa.
passo 'subindo a API e o worker'

LOG_API="$LOGS/api.log"
LOG_WORKER="$LOGS/worker.log"

nohup "$PY" -m uvicorn api.app.main:app --host "$ANFITRIAO" --port "$PORTA" >"$LOG_API" 2>&1 &
PID_API=$!
disown "$PID_API" 2>/dev/null || true

# O worker sobe dentro de um laco de supervisao, e nao solto.
#
# Por que (12/09/2026): um avaliador pediu o documento do cliente e a tela girou ate
# desistir. O worker tinha morrido depois da subida, e nada o levantava — `nohup ... &` e
# chamada unica, e a unica conferencia de vida acontecia no segundo em que o `up` terminava.
#
# O pedido de parada e um arquivo, lido a cada volta: o `down.sh` o cria ANTES de matar,
# senao o laco levantaria o worker de volta e o `down` nunca terminaria.
FLAG_PARAR="$LOGS/parar.flag"
rm -f "$FLAG_PARAR"

vigiar_worker() {
  while [ ! -f "$FLAG_PARAR" ]; do
    "$PY" -m pipeline.cli worker >>"$LOG_WORKER" 2>&1
    [ -f "$FLAG_PARAR" ] && break
    echo "[$(date -Iseconds)] worker caiu; subindo de novo em 2 s" >>"$LOG_WORKER"
    sleep 2
  done
}

vigiar_worker &
PID_WORKER=$!
disown "$PID_WORKER" 2>/dev/null || true

cat >"$PROCS" <<FIM
api=$PID_API
worker=$PID_WORKER
porta=$PORTA
banco=$BANCO_URL
log_api=$LOG_API
log_worker=$LOG_WORKER
FIM

ok "API no PID $PID_API · worker no PID $PID_WORKER"

# ---------------------------------------------------------------------- 4. conferencia
passo 'conferindo /health e a pagina inicial do web app'

SAUDE=""
for _ in $(seq 1 40); do
  SAUDE=$(curl -fsS --max-time 3 "$URLBASE/api/v1/health" 2>/dev/null) && break
  SAUDE=""
  sleep 0.5
done

if [ -z "$SAUDE" ]; then
  erro "a API nao respondeu em $URLBASE/api/v1/health depois de 20 s."
  erro "o log esta em $LOG_API"
  tail -n 15 "$LOG_API" 2>/dev/null | sed 's/^/   | /'
  exit 1
fi
ok "/health respondeu 200 -> $SAUDE"

CODIGO_APP=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$URLBASE/app" 2>/dev/null)
# 307 e o redirecionamento do StaticFiles de `/app` para `/app/`: tambem e sucesso.
if [ "$CODIGO_APP" = "200" ] || [ "$CODIGO_APP" = "307" ]; then
  ok "/app respondeu $CODIGO_APP"
else
  erro "/app respondeu $CODIGO_APP. O web app pode nao estar construido."
fi

if kill -0 "$PID_WORKER" 2>/dev/null; then
  ok "worker de pe (PID $PID_WORKER) — o documento do cliente sai por job e precisa dele"
else
  erro "o worker morreu. Log em $LOG_WORKER"
  tail -n 10 "$LOG_WORKER" 2>/dev/null | sed 's/^/   | /'
fi

# ------------------------------------------------------------------------- 5. as URLs
titulo 'ESTA DE PE — AS URLS'
echo ""
echo "   Entrada (abre direto na Consulta; nao ha login):"
echo "     $URLBASE/app"
echo ""
echo "   As telas, na ordem do passeio guiado:"
echo "     $URLBASE/app/consulta     pedir um veiculo pelo nome"
echo "     $URLBASE/app/radar        a fila de prioridade e o Fogo Amigo"
echo "     $URLBASE/app/matriz       onde ganhamos, empatamos, perdemos e nao sabemos"
echo "     $URLBASE/app/saude        cobertura por montadora e as divergencias"
echo "     $URLBASE/app/showroom     o perfil do cliente e o argumentario"
echo "     $URLBASE/app/insights     win/loss das conversas de showroom"
echo "     $URLBASE/app/simulador    e se o concorrente baixar 5%?"
echo ""
echo "   Aba de seguranca (a mesma resposta pela API, se uma tela travar):"
echo "     $URLBASE/docs"
echo ""

"$PY" scripts/demo/preparar_base.py --banco "$BANCO_URL" --so-papeis

echo "   Para derrubar tudo:"
echo "     bash scripts/demo/down.sh"
echo ""
echo "   Logs: $LOG_API  e  $LOG_WORKER"
echo "   Banco desta sessao: $BANCO_URL"
echo ""
