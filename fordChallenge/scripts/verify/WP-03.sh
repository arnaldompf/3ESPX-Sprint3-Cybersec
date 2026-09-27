#!/usr/bin/env bash
# WP-03 -- modelo de dados, migracoes Alembic e seed.
#
# Comando da spec:
#   set -e; make migrate; uv run specradar seed; uv run pytest -q tests/api/test_models.py
#
# Adaptacoes, todas por motivo:
#   (a) sem `make` nesta maquina (D-06): `python scripts/task.py migrate`.
#   (b) o criterio de aceite comeca em "dado banco vazio", entao o script cria um SQLite
#       proprio (data/verify_wp03.db) e o apaga no fim, em vez de mexer no banco de dev.
#   (c) o ciclo `downgrade base` -> `upgrade head` do segundo criterio de aceite entra
#       aqui explicitamente, incluindo a checagem de que o downgrade nao deixou tabela.
#   (d) ADMIN_EMAIL/ADMIN_PASSWORD ausentes do ambiente ganham valor efemero e aleatorio
#       gerado na hora -- senha nunca fica escrita em arquivo (regra inviolavel).
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"

BANCO="data/verify_wp03.db"
export DATABASE_URL="sqlite:///./${BANCO}"
export REPLAY_MODE=1
export LLM_FAKE=1

mkdir -p data
limpar() { rm -f "$BANCO"; }
trap limpar EXIT

: "${ADMIN_EMAIL:=admin.verify@specradar.local}"
export ADMIN_EMAIL
if [ -z "${ADMIN_PASSWORD:-}" ]; then
  ADMIN_PASSWORD="$($UV run python -c 'import secrets;print(secrets.token_urlsafe(24))')"
fi
export ADMIN_PASSWORD

# Escopado em api/ e tests/api/, como o WP-01 escopa em pipeline/: o verify de uma WP
# nao deve quebrar por causa de arquivo em voo de outra. `ruff check .` roda no lint geral.
echo "== [1/6] ruff em api =="
$UV run ruff check api tests/api
$UV run ruff format --check api tests/api

echo "== [2/6] migrate em banco vazio =="
limpar
python scripts/task.py migrate
$UV run python -c "
from sqlalchemy import create_engine, inspect
esperadas = {'brands','models','versions','sources','snapshots','extractions','spec_values',
             'evidences','synonyms','jobs','users','alerts','audit_log'}
motor = create_engine('${DATABASE_URL}')
tabelas = set(inspect(motor).get_table_names())
motor.dispose()
faltando = sorted(esperadas - tabelas)
assert not faltando, 'a migracao nao criou: ' + str(faltando)
print('   ok: ' + str(len(esperadas)) + ' tabelas criadas')
"

echo "== [3/6] seed (duas vezes: a segunda tem de ser idempotente) =="
$UV run python -m pipeline.cli seed
$UV run python -c "
from sqlmodel import Session, select
from api.app.db import criar_engine
from api.app.models import Brand, Synonym, User, Version

motor = criar_engine('${DATABASE_URL}')
with Session(motor) as s:
    marcas = sorted(b.nome for b in s.exec(select(Brand)))
    sinonimos = len(list(s.exec(select(Synonym))))
    admins = len(list(s.exec(select(User).where(User.role == 'admin'))))
    versoes = len(list(s.exec(select(Version))))
motor.dispose()
assert marcas == ['Chevrolet','Ford','Toyota','Volkswagen'], marcas
assert sinonimos > 20, sinonimos
assert admins == 1, admins
print('   ok: ' + str(len(marcas)) + ' marcas, ' + str(versoes) + ' versoes, '
      + str(sinonimos) + ' sinonimos, ' + str(admins) + ' admin')
import json, pathlib
pathlib.Path('data/.wp03_contagens.json').write_text(
    json.dumps({'marcas': len(marcas), 'sinonimos': sinonimos, 'admins': admins,
                'versoes': versoes}), encoding='utf-8')
"
$UV run python -m pipeline.cli seed
$UV run python -c "
import json, pathlib
from sqlmodel import Session, select
from api.app.db import criar_engine
from api.app.models import Brand, Synonym, User, Version

antes = json.loads(pathlib.Path('data/.wp03_contagens.json').read_text(encoding='utf-8'))
motor = criar_engine('${DATABASE_URL}')
with Session(motor) as s:
    depois = {
        'marcas': len(list(s.exec(select(Brand)))),
        'sinonimos': len(list(s.exec(select(Synonym)))),
        'admins': len(list(s.exec(select(User).where(User.role == 'admin')))),
        'versoes': len(list(s.exec(select(Version)))),
    }
motor.dispose()
pathlib.Path('data/.wp03_contagens.json').unlink()
assert antes == depois, ('seed nao e idempotente', antes, depois)
print('   ok: contagens identicas apos o segundo seed')
"

echo "== [4/6] senha do admin nunca em texto puro =="
$UV run python -c "
import os
from sqlmodel import Session, select
from api.app.db import criar_engine
from api.app.models import User

motor = criar_engine('${DATABASE_URL}')
with Session(motor) as s:
    admin = s.exec(select(User).where(User.email == os.environ['ADMIN_EMAIL'])).one()
    h = admin.password_hash
motor.dispose()
assert h.startswith('\$argon2'), h[:12]
assert os.environ['ADMIN_PASSWORD'] not in h
print('   ok: hash argon2, senha ausente do banco')
"

echo "== [5/6] testes do WP-03 =="
$UV run pytest -q tests/api/test_models.py

echo "== [6/6] downgrade base -> upgrade head =="
$UV run alembic -c api/alembic.ini downgrade base
$UV run python -c "
from sqlalchemy import create_engine, inspect
esperadas = {'brands','models','versions','sources','snapshots','extractions','spec_values',
             'evidences','synonyms','jobs','users','alerts','audit_log'}
motor = create_engine('${DATABASE_URL}')
restantes = sorted(set(inspect(motor).get_table_names()) & esperadas)
motor.dispose()
assert not restantes, 'downgrade deixou tabelas: ' + str(restantes)
print('   ok: downgrade limpou as 13 tabelas')
"
$UV run alembic -c api/alembic.ini upgrade head
$UV run python -c "
from sqlalchemy import create_engine, inspect
esperadas = {'brands','models','versions','sources','snapshots','extractions','spec_values',
             'evidences','synonyms','jobs','users','alerts','audit_log'}
motor = create_engine('${DATABASE_URL}')
tabelas = set(inspect(motor).get_table_names())
motor.dispose()
assert esperadas <= tabelas, sorted(esperadas - tabelas)
print('   ok: upgrade head reconstruiu tudo')
"

echo "WP-03 OK"
