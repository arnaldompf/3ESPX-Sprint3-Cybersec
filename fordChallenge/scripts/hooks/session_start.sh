#!/usr/bin/env bash
# Contexto mínimo no início de cada sessão: estado do repo + últimas linhas do STATUS.
cd "$CLAUDE_PROJECT_DIR" || exit 0
echo "== SpecRadar :: sessão iniciada $(date -Iseconds) =="
git status --short | head -20
echo "-- specs/STATUS.md (últimas 12 linhas) --"
tail -n 12 specs/STATUS.md 2>/dev/null
echo "Lembrete: uma spec por sessão; pronto = 'make verify WP=XX' verde + commit + STATUS.md."
