#!/usr/bin/env bash
# Derruba o que o `up.sh` subiu: a API e o worker. Gemeo de `down.ps1`.
#
# Le os PIDs de `data/onboarding/processos.txt` e para os dois. Se o arquivo nao existir
# (ou os PIDs ja tiverem morrido), procura pela porta — porque o sintoma que importa e "a
# porta 8000 esta presa", e ele tem de ser resolvido mesmo quando o registro se perdeu.
#
# O banco do onboarding NAO e apagado: derrubar nao e desfazer. Para montar tudo de novo,
# `up.sh --refazer`.
#
# Uso:
#   bash scripts/demo/down.sh
#   bash scripts/demo/down.sh --apagar-banco
set -uo pipefail

RAIZ=$(cd "$(dirname "$0")/../.." && pwd)
PASTA="$RAIZ/data/onboarding"
PROCS="$PASTA/processos.txt"
BANCO="$PASTA/onboarding.db"

APAGAR=0
for arg in "$@"; do
  case "$arg" in
    --apagar-banco) APAGAR=1 ;;
    -h|--help) sed -n '1,15p' "$0"; exit 0 ;;
    *) echo "opcao desconhecida: $arg"; exit 2 ;;
  esac
done

ok()    { echo "   ok: $1"; }
aviso() { echo "   aviso: $1"; }

echo ""
echo 'SPECRADAR — DERRUBANDO'
printf '=%.0s' {1..78}; echo ""

PORTA=8000
PARADOS=0

# O pedido de parada vem ANTES de qualquer kill: o worker sobe dentro de um laco de
# supervisao (`up.sh`), e matar o processo sem avisar faria o laco levanta-lo de volta.
mkdir -p "$PASTA/logs" 2>/dev/null || true
: > "$PASTA/logs/parar.flag"

if [ -f "$PROCS" ]; then
  # shellcheck disable=SC1090
  . "$PROCS"
  PORTA="${porta:-8000}"
  for par in "API:${api:-}" "worker:${worker:-}"; do
    NOME="${par%%:*}"; ALVO="${par##*:}"
    [ -n "$ALVO" ] || continue
    if kill -0 "$ALVO" 2>/dev/null; then
      kill "$ALVO" 2>/dev/null || true
      sleep 0.3
      kill -9 "$ALVO" 2>/dev/null || true
      ok "$NOME parado (PID $ALVO)"
      PARADOS=$((PARADOS + 1))
    else
      aviso "$NOME (PID $ALVO) ja nao estava rodando"
    fi
  done
  rm -f "$PROCS"
else
  aviso "nao ha registro em $PROCS — procurando pela porta"
fi

# Rede de seguranca: qualquer coisa ainda escutando na porta. Sem isto, um `up` anterior
# que perdeu o registro deixa a porta presa e o proximo `up` sai com "porta em uso" sem
# nenhum caminho de saida. No Windows o `lsof` nao existe; `netstat -ano` responde nos dois.
PIDS_NA_PORTA=$(
  { netstat -ano 2>/dev/null || netstat -anp 2>/dev/null; } \
    | awk -v p=":$PORTA" '$0 ~ p && (/LISTEN/ || /LISTENING/) {print $NF}' \
    | grep -E '^[0-9]+$' | sort -u
)
for ALVO in $PIDS_NA_PORTA; do
  if kill -0 "$ALVO" 2>/dev/null; then
    kill -9 "$ALVO" 2>/dev/null || true
    ok "processo na porta $PORTA parado (PID $ALVO)"
    PARADOS=$((PARADOS + 1))
  fi
done

# Segunda rede: um worker orfao nao escuta porta nenhuma, entao a varredura acima nao o
# alcanca. Sem registro ele ficaria rodando para sempre, consumindo a fila de um banco que
# ninguem mais olha. Sem psutil (que nao esta instalado): `wmic` no Windows, `ps` no resto.
PY_ORFAOS="$RAIZ/.venv/bin/python"
[ -x "$PY_ORFAOS" ] || PY_ORFAOS="$RAIZ/.venv/Scripts/python.exe"
if [ -x "$PY_ORFAOS" ]; then
  ORFAOS=$("$PY_ORFAOS" - <<'FIMPY'
import os, re, subprocess, sys

PADROES = ("pipeline.cli worker", "uvicorn api.app.main:app")

def linhas():
    if os.name == "nt":
        try:
            bruto = subprocess.run(
                ["wmic", "process", "get", "ProcessId,CommandLine", "/format:csv"],
                capture_output=True, text=True, errors="replace", timeout=30,
            ).stdout
        except Exception:
            return
        for linha in bruto.splitlines():
            partes = linha.rsplit(",", 1)
            if len(partes) == 2 and partes[1].strip().isdigit():
                yield int(partes[1].strip()), partes[0]
        return
    try:
        bruto = subprocess.run(
            ["ps", "-eo", "pid=,args="], capture_output=True, text=True, errors="replace", timeout=30
        ).stdout
    except Exception:
        return
    for linha in bruto.splitlines():
        achado = re.match(r"\s*(\d+)\s+(.*)", linha)
        if achado:
            yield int(achado.group(1)), achado.group(2)

meu = os.getpid()
for pid, comando in linhas():
    if pid == meu:
        continue
    if any(p in comando for p in PADROES):
        print(pid)
FIMPY
  )
  for ALVO in ${ORFAOS:-}; do
    if kill -0 "$ALVO" 2>/dev/null; then
      kill -9 "$ALVO" 2>/dev/null || true
      ok "processo orfao do SpecRadar parado (PID $ALVO)"
      PARADOS=$((PARADOS + 1))
    fi
  done
fi

[ "$PARADOS" -eq 0 ] && aviso 'nada estava rodando'

if [ "$APAGAR" -eq 1 ] && [ -f "$BANCO" ]; then
  rm -f "$BANCO"
  ok 'banco do onboarding apagado'
elif [ -f "$BANCO" ]; then
  echo "   o banco continua em $BANCO (derrubar nao e desfazer)"
fi

echo ""
echo '   Para subir de novo:  bash scripts/demo/up.sh'
echo ""
