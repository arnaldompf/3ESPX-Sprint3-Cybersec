#!/usr/bin/env bash
# WP-00 — bootstrap do monorepo, ferramentas e CI minimo.
#
# Original da spec:
#   set -e; uv sync; ruff check .; docker compose -f infra/docker-compose.yml up -d; sleep 5;
#   uv run pytest -q tests/test_smoke.py; test -f .env.example; test -f .github/workflows/ci.yml
#
# Adaptacao (DECISOES_NOITE.md D-05): o daemon do Docker nao esta de pe nesta maquina.
# O passo do compose fica condicional: se o daemon responder, sobe o Postgres e espera o
# healthcheck; se nao, valida que o compose existe e e sintaticamente utilizavel, e o smoke
# roda contra o SQLite de dev. Postgres continua o alvo de producao.
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"

echo "== [1/6] uv sync =="
$UV sync

echo "== [2/6] ruff =="
$UV run ruff check .
$UV run ruff format --check .

echo "== [3/6] banco =="
if docker ps >/dev/null 2>&1; then
  docker compose -f infra/docker-compose.yml up -d
  for _ in $(seq 1 24); do
    if docker compose -f infra/docker-compose.yml exec -T db pg_isready -U specradar -d specradar >/dev/null 2>&1; then
      echo "   Postgres pronto."; break
    fi
    sleep 2
  done
else
  echo "   daemon do Docker indisponivel -> smoke roda em SQLite (D-05)."
  test -f infra/docker-compose.yml
  grep -q "pgvector/pgvector:pg16" infra/docker-compose.yml
  grep -q "healthcheck" infra/docker-compose.yml
fi

echo "== [4/6] smoke =="
$UV run pytest -q tests/test_smoke.py

echo "== [5/6] artefatos obrigatorios =="
test -f .env.example
test -f .github/workflows/ci.yml
test -f .pre-commit-config.yaml
test -f .gitignore
test -f Makefile
test -f scripts/task.py
test -f pyproject.toml
for d in api pipeline web ml airflow infra scripts/verify tests; do
  test -d "$d" || { echo "falta diretorio $d"; exit 1; }
done
test -f data/snapshots/.gitkeep
test -f reports/.gitkeep

echo "== [6/6] o .env nao pode estar rastreado =="
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "ERRO: .env esta versionado"; exit 1
fi
grep -q '^\.env$' .gitignore

echo "WP-00 OK"
