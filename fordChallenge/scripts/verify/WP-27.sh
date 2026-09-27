#!/usr/bin/env bash
# WP-27 — argumentario verificado, win/loss e insights.
#
# Comando da spec:
#   set -e; REPLAY_MODE=1 LLM_FAKE=1 uv run pytest -q tests/pipeline/test_arguments.py \
#       tests/api/test_showroom_sessions.py tests/api/test_insights.py; \
#       cd mobile && npx tsc --noEmit && npx jest --ci -t "argumentos|resultado|insights"
#
# `mobile/` virou `web/` e `jest` virou `vitest`, como nas WPs anteriores. Os passos [4] a
# [7] sao acrescimo, e cada um trava uma regra que os comandos da spec nao alcancam:
#
#   [4] o argumentario funciona SEM LLM e SEM rede — e o caminho padrao da demo;
#   [5] o verificador rejeita numero que nao esta nas celulas;
#   [6] a sessao de showroom nao tem onde guardar PII, nem no schema nem na tabela;
#   [7] a regra do n >= 20 e a separacao entre real e simulado.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ=$(pwd)

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1
export REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/7] o argumentario: template, verificador, reescrita =="
$UV run pytest -q tests/pipeline/test_arguments.py

echo "== [2/7] a API: sessoes de showroom e governanca do argumentario =="
$UV run pytest -q tests/api/test_showroom_sessions.py

echo "== [3/7] a API: win/loss e insights =="
$UV run pytest -q tests/api/test_insights.py

echo "== [4/7] as telas =="
cd "$RAIZ/web"
npx tsc --noEmit
npx vitest run -t "argumentos|resultado|insights"
cd "$RAIZ"

echo "== [5/7] o argumentario funciona sem LLM e sem rede =="
$UV run python -c "
from pipeline.arguments import llm_rewrite, template

celulas = {
    'potencia_cv': template.CampoDaCelula(
        campo='potencia_cv', valor_ford=397, valor_concorrente=204, unidade='cv',
        evidence_id_ford='a', evidence_id_concorrente='b',
        fonte_ford='https://www.ford.com.br/x', fonte_concorrente='https://www.toyota.com.br/y',
        data_ford='2026-09-01T00:00:00', data_concorrente='2026-09-01T00:00:00',
    ),
    'capacidade_carga_kg': template.CampoDaCelula(
        campo='capacidade_carga_kg', valor_ford=620, valor_concorrente=1005, unidade='kg',
        evidence_id_ford='c', evidence_id_concorrente='d',
        fonte_ford='https://www.ford.com.br/x', fonte_concorrente='https://www.toyota.com.br/y',
        data_ford='2026-09-01T00:00:00', data_concorrente='2026-09-01T00:00:00',
    ),
}
aderencia = {
    'dimensoes': [
        {
            'dimensao': 'desempenho', 'rotulo': 'desempenho', 'peso': 35,
            'campos_usados': ['potencia_cv'], 'campos_sem_dado': [], 'cobertura': 1.0,
            'insuficiente': False, 'aviso': '',
            'detalhe_ford': [{'campo': 'potencia_cv', 'nota': 10.0}],
            'detalhe_concorrente': [{'campo': 'potencia_cv', 'nota': 2.0}],
        },
        {
            'dimensao': 'capacidade', 'rotulo': 'capacidade', 'peso': 25,
            'campos_usados': ['capacidade_carga_kg'], 'campos_sem_dado': [], 'cobertura': 1.0,
            'insuficiente': False, 'aviso': '',
            'detalhe_ford': [{'campo': 'capacidade_carga_kg', 'nota': 2.0}],
            'detalhe_concorrente': [{'campo': 'capacidade_carga_kg', 'nota': 9.0}],
        },
    ],
    'vence_em': {'ford': ['desempenho'], 'concorrente': ['capacidade']},
}

r = template.montar(aderencia, celulas, rotulo_ford='Ford', rotulo_concorrente='Concorrente')
assert r.pontos, 'o template nao gerou ponto nenhum'
assert r.ponto_forte_concorrente is not None, 'faltou o ponto de atencao'
# Cada frase carrega os evidence_id das duas pontas.
for p in [*r.pontos, r.ponto_forte_concorrente]:
    assert len(p.fonte_por_ponto) == 2, p.fonte_por_ponto
# O ponto de atencao nao ameniza.
for amenizador in ('porem', 'apesar'):
    assert amenizador not in r.ponto_forte_concorrente.texto.lower()

# Sem LLM: o texto e o do template, e a resposta diz isso.
sem = llm_rewrite.reescrever(r, celulas, permitir_llm=False)
assert sem.gerado_por == 'template', sem.gerado_por
print(f'   ok: {len(r.pontos)} ponto(s) + atencao, todos com evidencia, sem LLM')
"

echo "== [6/7] o verificador rejeita numero que nao esta nas celulas =="
$UV run python -c "
from pipeline.arguments import verify

# Numero que existe: passa.
assert verify.verificar('A Ford tem 397 cv contra 204 cv.', [397, 204]).aprovado

# Numero inventado: reprova, e o motivo diz QUAL.
r = verify.verificar('A Ford tem 400 cv contra 204 cv.', [397, 204])
assert not r.aprovado
assert 400.0 in r.numeros_sem_respaldo, r.numeros_sem_respaldo
assert '400' in r.motivo

# Superlativo reprova sempre: nenhuma celula sustenta 'a melhor do mercado'.
assert not verify.verificar('A melhor picape do mercado, com 397 cv.', [397]).aprovado
# Comparativo sem numero tambem.
assert not verify.verificar('Tem o dobro de forca.', [397, 204]).aprovado

# Numero que e parte do NOME do campo passa quando o nome e informado — 'camera 360'
# cita o item, nao uma medida.
assert not verify.verificar('Tem camera 360.', [True]).aprovado
assert verify.verificar('Tem camera 360.', [True], nomes_de_campo=['camera_360']).aprovado
print('   ok: numero inventado, superlativo e comparativo sem numero sao rejeitados')
"

echo "== [7/7] sessao sem PII, e a regra do n =="
$UV run python -c "
from api.app.models import ShowroomSession
from api.app.routers.showroom import SessaoIn
from api.app.services import winloss

# 1. Nao ha onde guardar PII: nem no schema de entrada, nem na tabela.
assert SessaoIn.model_config.get('extra') == 'forbid'
try:
    SessaoIn(ford_version_id='x', nome_do_cliente='Joao')
    raise SystemExit('ERRO: o schema aceitou um campo de PII')
except Exception as exc:
    assert 'extra' in str(exc).lower() or 'forbidden' in str(exc).lower(), str(exc)

colunas = set(ShowroomSession.model_fields)
for proibida in ('nome', 'telefone', 'email', 'cpf', 'cliente', 'observacoes'):
    assert not any(proibida in c for c in colunas), colunas

# 2. A regra do n: percentual so com n >= 20, e o limiar vem da spec.
assert winloss.N_MINIMO_PARA_PERCENTUAL == 20
assert winloss.Contagem(10, 15).percentual is None
assert winloss.Contagem(10, 20).percentual == 50.0
# Denominador zero nao vira 0%: nao ha proporcao a mostrar.
assert winloss.Contagem(0, 0).percentual is None

# 3. O rotulo de simulacao e literal.
assert winloss.ROTULO_SIMULACAO == 'SIMULAÇÃO — dados de demonstração'

# 4. A distribuicao da semente e declarada no script, com soma 1.
from api.app.seed import DISTRIBUICAO_DE_SESSOES

for chave in ('desfecho', 'motivos', 'atributo_decisivo', 'uso'):
    soma = sum(DISTRIBUICAO_DE_SESSOES[chave].values())
    assert abs(soma - 1.0) < 1e-9, (chave, soma)
print('   ok: sem PII no schema e na tabela, n >= 20 para percentual, semente declarada')
"

echo "WP-27 OK"
