#!/usr/bin/env bash
# WP-05 — autenticacao JWT, RBAC pela matriz, rate limit, CORS e seguranca.
#
# Comando da spec:
#   set -e; uv run pytest -q tests/api/test_auth.py tests/api/test_rbac.py \
#       tests/api/test_ratelimit.py
#   uv run semgrep --config p/python --config p/secrets --error api pipeline
#
# SEMGREP SUBSTITUIDO por `ruff check` (regras `S`, flake8-bandit) + varredura propria de
# segredo. Tres motivos, e estao em DECISOES_NOITE.md D-64:
#   1. `p/python` e `p/secrets` sao rulesets do REGISTRO do semgrep, buscados na rede. A
#      regra da noite e "rede so o necessario", e um verify que depende de download
#      externo quebra offline e no CI sem egress;
#   2. o semgrep nao esta no `pyproject`; instalado a mao, o proximo `uv sync` o remove, e
#      um portao que desaparece nao e portao;
#   3. o `ruff` do projeto ja seleciona `S` (flake8-bandit), que sao as mesmas regras de
#      seguranca para Python do `p/python`, e roda offline em 0,2 s.
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1

echo "== [1/7] ruff (inclui as regras S de seguranca) =="
$UV run ruff check api pipeline scripts tests
$UV run ruff format --check api pipeline scripts tests

echo "== [2/7] testes da spec =="
$UV run pytest -q tests/api/test_auth.py tests/api/test_rbac.py tests/api/test_ratelimit.py

echo "== [3/7] os tres criterios de aceite =="
$UV run pytest -q tests/api -k "CriteriosDeAceite" -v 2>&1 | tail -8

echo "== [4/7] nenhum segredo no codigo (o que p/secrets procuraria) =="
$UV run python -c "
import re, sys
from pathlib import Path

# Padroes de credencial literal. O que se procura e ATRIBUICAO de valor literal, nao a
# palavra: 'JWT_SECRET' aparece legitimamente em mensagem de erro e em docstring.
PADROES = [
    (re.compile(r'''(?i)(secret|password|senha|token|api_key)\s*=\s*[\"'][^\"'{}\$]{8,}[\"']'''), 'credencial literal'),
    (re.compile(r'sk-ant-[A-Za-z0-9]{10,}'), 'chave da Anthropic'),
    (re.compile(r'(?i)postgres(ql)?://[^:]+:[^@]+@'), 'senha em URL de banco'),
]
# O que e legitimo: default de config vazio, placeholder, e os arquivos de teste (que
# declaram senha de teste de proposito e estao isentos de S105/S106 no pyproject).
ISENTOS = ('tests/', '.venv/', '_kits/')
achados = []
for caminho in list(Path('api').rglob('*.py')) + list(Path('pipeline').rglob('*.py')) + list(Path('scripts').rglob('*.py')):
    texto = str(caminho).replace('\\\\', '/')
    if any(i in texto for i in ISENTOS):
        continue
    for n, linha in enumerate(caminho.read_text(encoding='utf-8').splitlines(), 1):
        if 'noqa' in linha or linha.lstrip().startswith('#'):
            continue
        for padrao, nome in PADROES:
            if padrao.search(linha):
                achados.append(f'{caminho}:{n}: {nome}: {linha.strip()[:80]}')
if achados:
    print('SEGREDO NO CODIGO:'); [print(' ', a) for a in achados]; sys.exit(1)
print('   ok: nenhuma credencial literal em api/, pipeline/ e scripts/')
"

echo "== [5/7] a matriz de docs/12 6.6 nao e hierarquia =="
$UV run python -c "
import itertools
from api.app.models import Role
from api.app.permissions import Acao, pode

# O cruzamento: vendedor abre showroom e analista NAO; analista extrai e vendedor NAO.
assert pode(Role.VENDEDOR, Acao.CRIAR_SESSAO_SHOWROOM)
assert not pode(Role.ANALISTA, Acao.CRIAR_SESSAO_SHOWROOM)
assert pode(Role.ANALISTA, Acao.CRIAR_EXTRACOES)
assert not pode(Role.VENDEDOR, Acao.CRIAR_EXTRACOES)

papeis = list(Role)
def linear(ordem):
    for acao in (Acao.CRIAR_SESSAO_SHOWROOM, Acao.CRIAR_EXTRACOES):
        idx = sorted(ordem.index(p) for p in papeis if pode(p, acao))
        if idx != list(range(idx[0], len(ordem))):
            return False
    return True
assert not any(linear(list(o)) for o in itertools.permutations(papeis)), \
    'existe ordem linear que explica a matriz — a premissa da WP-05 mudou'
print(f'   ok: nenhuma das {len(list(itertools.permutations(papeis)))} ordens de papel explica a matriz')
"

echo "== [6/7] JWT: segredo curto recusado, e refresh nao vale como access =="
$UV run python -c "
import os
os.environ['JWT_SECRET'] = 'segredo-de-verify-com-mais-de-32-bytes-de-folga'
from api.app.config import get_settings
get_settings.cache_clear()
from api.app.security import (
    SegredoInvalido, TokenExpirado, TokenInvalido, criar_token, ler_token, segredo,
)
import datetime as dt

# 1. tipo de token e verificado
refresh, _ = criar_token(sub='u1', role='admin', tipo='refresh')
try:
    ler_token(refresh, tipo_esperado='access')
    raise SystemExit('FALHOU: refresh passou como access')
except TokenInvalido as e:
    assert 'tipo' in e.detalhe.lower(), e.detalhe

# 2. expirado tem titulo proprio
expirado, _ = criar_token(sub='u1', role='admin', ttl=dt.timedelta(minutes=-1))
try:
    ler_token(expirado)
    raise SystemExit('FALHOU: token expirado passou')
except TokenExpirado as e:
    assert e.titulo == 'Token expirado', e.titulo

# 3. segredo curto e recusado
os.environ['JWT_SECRET'] = 'curto'
get_settings.cache_clear()
try:
    segredo()
    raise SystemExit('FALHOU: segredo curto aceito')
except SegredoInvalido:
    pass
print('   ok: tipo verificado, expiracao com titulo proprio, segredo curto recusado')
"

echo "== [7/7] CORS restrito e sem curinga =="
$UV run python -c "
import os
os.environ['CORS_ORIGINS'] = 'http://localhost:5173,*'
from api.app.config import get_settings
get_settings.cache_clear()
origens = list(get_settings().origens_cors)
assert '*' not in origens, f'curinga passou para o CORS: {origens}'
assert 'http://localhost:5173' in origens, origens
print(f'   ok: curinga descartado; origens = {origens}')
"

echo "WP-05 OK"
