#!/usr/bin/env bash
# Ensaio da demo de 15/09: monta a base em replay e percorre as 12 cenas de `docs/13` §7.
#
# O que este script e: o ensaio TECNICO. Ele monta o banco com os mesmos comandos que a
# pessoa vai rodar antes da apresentacao, exerce cada cena pela API de verdade e imprime a
# URL de cada uma, com os numeros que vao aparecer na tela. Se uma cena nao tiver dado, ele
# diz aqui — e nao no telao.
#
# O que este script NAO e: o ensaio de palco. Quem fala o que, em que ordem e em quanto
# tempo esta em `docs/demo/ROTEIRO_15SET.md`, e o cronometro de palco e do item (HUMANO) do
# maestro. O teto de 8 minutos que este script cobra e de MAQUINA: ele garante que a demo
# nao vai esperar o software.
#
# Rede: ZERO. `REPLAY_MODE=1` bloqueia qualquer chamada; as fontes vem dos snapshots
# salvos em `tests/fixtures/snapshots/`. `LLM_FAKE=1` garante custo real zero.
#
# Banco: `data/demo/demo.db`, descartavel e RECRIADO a cada execucao. O banco de dev
# (`data/dev.db`) nao e tocado.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ=$(pwd)

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"

export PYTHONUTF8=1
export REPLAY_MODE=1
export LLM_FAKE=1
export LOG_LEVEL="${LOG_LEVEL:-WARNING}"

mkdir -p "$RAIZ/data/demo"

# O caminho do banco sai do PYTHON, e nao do `pwd`.
#
# DEFEITO CORRIGIDO, e e do ambiente: no Git Bash do Windows o `pwd` devolve um caminho
# estilo POSIX que comeca com a letra do drive como primeiro diretorio, e
# `sqlite:///$(pwd)/...` acabava com QUATRO barras. O SQLAlchemy leu aquilo como caminho
# POSIX absoluto e o SQLite criou uma arvore de diretorios inteira na RAIZ do drive, fora
# do projeto: o ensaio passava (o banco existia, so no lugar errado), o `data/demo/` ficava
# vazio, e a URL impressa para a pessoa nao funcionava em PowerShell.
#
# `Path.resolve().as_posix()` devolve a forma com a letra do drive e barras normais no
# Windows, e o caminho POSIX de sempre no Linux — a mesma URL serve nos dois shells.
BANCO=$($UV run python -c "import pathlib; print(pathlib.Path('data/demo/demo.db').resolve().as_posix())")
rm -f "$BANCO"
export DATABASE_URL="sqlite:///${BANCO}"

# O `JWT_SECRET` do ensaio: aleatorio por execucao, nunca impresso, banco descartavel.
# Nao ha credencial padrao em lugar nenhum do projeto, e o ensaio nao abre excecao.
if [ -z "${JWT_SECRET:-}" ]; then
  JWT_SECRET=$($UV run python -c "import secrets; print(secrets.token_urlsafe(48))")
  export JWT_SECRET
fi

COMECO=$(date +%s)

echo "=============================================================================="
echo "PREPARO — o mesmo que a pessoa roda antes da apresentacao"
echo "=============================================================================="

echo "-- [1/5] migracoes"
$UV run alembic -c api/alembic.ini upgrade head >/dev/null
echo "   ok: schema em head, em $BANCO"

echo "-- [2/5] catalogo, watchlist, equivalencias e o deck interno da Raptor"
$UV run python -m pipeline.cli seed 2>&1 | grep -E "^seed:" || true

echo "-- [3/5] extracao das CINCO versoes (replay, com persistencia)"
extrair() {
  printf "   %-46s" "$1 $2 $3"
  $UV run python -m pipeline.cli extract "$1" "$2" "$3" --replay --persistir 2>&1 \
    | grep -E "campos com valor" | head -1
}
extrair Ford Ranger "Raptor 3.0 V6 Bi-turbo 4WD AT"
# A Ford diesel de topo, coletada em 10/09/2026. E ela que a cena 8 compara com a
# Hilux SRX Plus — o par que `docs/13` §7 pede e que ate 09/09 nao existia na base.
extrair Ford Ranger "Limited 3.0 V6 Diesel 4WD AT"
extrair Toyota Hilux "SRX Plus AT (Cabine Dupla)"
extrair Volkswagen Amarok "V6 Extreme"
extrair Chevrolet S10 "High Country"

echo "-- [4/5] refresh da watchlist (e o Fogo Amigo contra o deck)"
$UV run python -m pipeline.cli refresh --watchlist 2>&1 | grep -E "^refresh:" || true

echo "-- [5/5] dado de demonstracao, todo marcado is_simulated=true"
$UV run python -m pipeline.cli seed --simulated-alerts 3 --simulated-sessions 40 2>&1 \
  | grep -E "SIMULAD" || true

PREPARO=$(( $(date +%s) - COMECO ))
echo ""
echo "preparo: ${PREPARO}s"
echo ""

# O passeio pelas cenas, e o teto de tempo, ficam em Python: cada cena e uma chamada de
# API de verdade, com o resultado impresso. Ver `scripts/demo/cenas.py`.
$UV run python scripts/demo/cenas.py
SAIDA=$?

# O roteiro passa a trazer os numeros deste ensaio, no bloco entre ENSAIO:INICIO e
# ENSAIO:FIM. Era aqui que o roteiro e a tela divergiam: o roteiro dizia "10 ALTA" na
# cena 10 e o medido era "4 ALTA, 1 MEDIA, 2 RUIDO". Agora os dois leem a mesma fonte.
$UV run python scripts/demo/atualizar_roteiro.py || true

TOTAL=$(( $(date +%s) - COMECO ))
echo ""
echo "TEMPO TOTAL (preparo + passeio): ${TOTAL}s"
echo ""
echo "Para a demo de verdade, com a tela:"
echo "  1. cd web && npm ci && npm run build && cd .."
echo "  2. DATABASE_URL=\"sqlite:///$BANCO\" python scripts/task.py api"
echo "  3. abra http://127.0.0.1:8000/app  (o roteiro esta em docs/demo/ROTEIRO_15SET.md)"
echo "  nao ha login: o app abre na Consulta e o papel fica na barra lateral (D-204)"

exit $SAIDA
