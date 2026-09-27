#!/usr/bin/env bash
# WP-11 — grounding, normalizacao e status. O coracao do projeto.
#
# Comando da spec:
#   set -e; uv run pytest -q tests/pipeline/test_ground.py tests/pipeline/test_normalize.py \
#       tests/pipeline/test_status.py tests/eval/test_grounding.py \
#       tests/eval/test_two_kinds_of_empty.py tests/eval/test_synonyms.py
#
# Acrescentado: os cinco criterios de aceite conferidos direto, a garantia de que o eval
# usa a MESMA funcao de grounding que o pipeline, e a guarda numerica do caminho difuso —
# que foi o defeito mais perigoso encontrado nesta WP.
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1 REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/6] ruff =="
$UV run ruff check pipeline tests
$UV run ruff format --check pipeline tests

echo "== [2/6] testes da spec =="
$UV run pytest -q tests/pipeline/test_ground.py tests/pipeline/test_normalize.py \
  tests/pipeline/test_status.py tests/eval/test_grounding.py \
  tests/eval/test_two_kinds_of_empty.py tests/eval/test_synonyms.py

echo "== [3/6] os cinco criterios de aceite =="
$UV run python -c "
from pipeline.ground import locate
from pipeline.normalize import normalizar_campo
from pipeline.schema import Status
from pipeline.status import Observacao, decidir

def o(campo, valor, quote, tier=1, sid='s', **kw):
    return Observacao(campo=campo, valor=valor, quote=quote, tier=tier, source_id=sid,
                      url='https://oficial', **kw)

# 1. quote sem acento localiza no texto com acento
r = locate('Potencia 397cv', 'Ficha: Potência 397cv')
assert r.ok and r.modo == 'sem_acento', r
# 2. quote inventado -> nao_verificado, valor nulo
d = decidir('potencia_cv', [o('potencia_cv', 500, 'Potencia 500cv')], textos={'s': 'Potencia 397cv'})
assert d.status is Status.NAO_VERIFICADO and d.spec.value is None, d.status
# 3. T1 583 Nm + T3 59,4 kgfm -> verificado com 0,95
d = decidir('torque_nm', [o('torque_nm', 583, 'Torque 583Nm', 1, 'a'),
                         o('torque_nm', 583, '59,4 kgfm', 3, 'b')],
            textos={'a': 'Torque 583Nm', 'b': 'torque de 59,4 kgfm'})
assert d.status is Status.VERIFICADO and d.spec.confidence == 0.95, (d.status, d.spec.confidence)
# 4. T1 Off-Road x slide Baja -> divergente com os dois
d = decidir('modos_amortecedor',
            [o('modos_amortecedor', ['normal','sport','off_road'], 'Normal, Sport, Off-Road', 1, 'a'),
             o('modos_amortecedor', ['normal','sport','baja'], 'Normal, Sport, Baja', 1, 'b')],
            textos={'a': 'modos: Normal, Sport, Off-Road', 'b': 'modos: Normal, Sport, Baja'})
assert d.status is Status.DIVERGENTE, d.status
assert d.spec.conflicts, 'divergente tem de trazer os valores concorrentes'
# 5. travessao na coluna da versao -> nao_disponivel
n = normalizar_campo('camera_360', '—')
assert n.ausencia_declarada and n.valor is None
d = decidir('camera_360', [o('camera_360', None, '—', 1, 'pdf', ausencia_declarada=True)],
            textos={'pdf': 'Camera 360   —'})
assert d.status is Status.NAO_DISPONIVEL, d.status
print('   ok: os cinco criterios de aceite passam')
"

echo "== [4/6] o eval usa a MESMA funcao de grounding do pipeline =="
$UV run python -c "
from pipeline.eval import compare
from pipeline import ground
assert compare.LIMIAR_GROUNDING == ground.LIMIAR_DIFUSO
for q, t in (('397cv','Potencia 397cv'), ('Potencia 397cv','Potência 397cv'),
             ('Potencia 900cv','Potencia 397cv')):
    a, b = compare.grounding(q, t), ground.locate(q, t)
    assert (a.ok, a.modo) == (b.ok, b.modo), (q, a, b)
print('   ok: uma implementacao, dois nomes')
"

echo "== [5/6] guarda numerica: numero errado nao passa pelo difuso =="
$UV run python -c "
from pipeline.ground import LIMIAR_DIFUSO, locate
texto = 'Torque máximo de 583 Nm a 2.750 rpm no eixo traseiro'
r = locate('Torque máximo de 900 Nm a 2.750 rpm no eixo traseiro', texto)
assert not r.ok, 'numero errado nao pode groundar'
assert r.score >= LIMIAR_DIFUSO, 'a similaridade passaria; foi a guarda que reprovou'
assert 'nao estao na fonte' in r.detalhe.replace('ã','a').replace('á','a'), r.detalhe
r2 = locate('Torque máximo de 583 Nm a 2.750 rpm no eixo trasero', texto)
assert r2.ok, 'ruido em letras continua aceito'
print(f'   ok: reprovado com similaridade {r.score:.1f} (limiar {LIMIAR_DIFUSO:.0f})')
"

echo "== [6/6] grounding_rate = 1,0 sobre as fontes reais =="
$UV run pytest -q tests/eval/test_grounding.py -k "trecho_localizado or modos_de_grounding"

echo "WP-11 OK"
