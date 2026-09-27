#!/usr/bin/env bash
# Portão de saída: se houver uma WP marcada como 'em_andamento' em specs/STATUS.md, roda o verify dela.
# Falhou -> exit 2 (bloqueia o encerramento e devolve o erro ao agente), no máximo 3 vezes por sessão.
#
# Windows: 'make' pode não existir; nesse caso usa o executor canônico
# 'python scripts/task.py verify WP=XX' (DECISOES_NOITE.md D-06).
cd "$CLAUDE_PROJECT_DIR" || exit 0
WP=$(grep -E '^\| *WP-[0-9]+ *\| *em_andamento' specs/STATUS.md 2>/dev/null | head -1 | sed -E 's/^\| *WP-([0-9]+).*/\1/')
[ -z "$WP" ] && exit 0
COUNTER=".claude/.stop_gate_count"
N=$(cat "$COUNTER" 2>/dev/null || echo 0)
if [ "$N" -ge 3 ]; then echo "stop_gate: limite de 3 bloqueios atingido; registre o ponto em STATUS.md" >&2; rm -f "$COUNTER"; exit 0; fi

LOG="${TMPDIR:-/tmp}/stop_gate.log"
if command -v make >/dev/null 2>&1; then
  RUN=(make -s verify "WP=$WP")
else
  PYBIN=python; command -v python >/dev/null 2>&1 || PYBIN=py
  RUN=("$PYBIN" scripts/task.py verify "WP=$WP")
fi

if "${RUN[@]}" > "$LOG" 2>&1; then
  rm -f "$COUNTER"; exit 0
else
  echo $((N+1)) > "$COUNTER"
  echo "stop_gate: verify da WP-$WP FALHOU (${RUN[*]}). Corrija antes de encerrar. Últimas linhas:" >&2
  tail -n 40 "$LOG" >&2
  exit 2
fi
