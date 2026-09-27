#!/usr/bin/env bash
# WP-10 — extracao estruturada, provedor de LLM e fast-path por regex.
#
# Comando da spec:
#   set -e; LLM_FAKE=1 uv run pytest -q tests/pipeline/test_extract.py
#
# Acrescentado: a medida que interessa de verdade — valor certo E quote groundavel,
# contra o gabarito, nos quatro veiculos. E a prova de que nenhum candidato sai sem
# evidencia localizavel (grounding_rate = 1,0 e meta de docs/09).
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1 REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/6] ruff =="
$UV run ruff check pipeline tests/pipeline scripts
$UV run ruff format --check pipeline tests/pipeline scripts

echo "== [2/6] testes da extracao =="
$UV run pytest -q tests/pipeline/test_extract.py

echo "== [3/6] criterios de aceite da spec =="
$UV run python -c "
import pathlib
from pipeline.eval.compare import grounding
from pipeline.extract.fastpath import extrair

raw = pathlib.Path('gabarito/raw')
texto = (raw / 'ford_raptor_site_versao.md').read_text(encoding='utf-8')
texto += chr(10) + (raw / 'ford_raptor_ficha_tecnica_oficial.txt').read_text(encoding='utf-8')

r = extrair(texto, campos={'potencia_cv','tipo','numero_marchas','paddle_shifters','modos_direcao'})
v = {a.campo: a.valor for a in r.achados}
assert v['potencia_cv'] == 397, v
assert v['tipo'] == 'automatica', v
assert v['numero_marchas'] == 10, v
assert v['paddle_shifters'] is True, v
assert len(v['modos_direcao']) == 4, v
for a in r.achados:
    assert grounding(a.quote, texto).ok, (a.campo, a.quote)
print('   ok: 397 cv, automatica/10/paddle, 4 modos de direcao, todos com quote groundavel')

vazio = extrair('Uma picape bonita, sem numero nenhum.', campos={'potencia_cv','torque_nm'})
assert vazio.achados == [], vazio.achados
print('   ok: atributo ausente do texto nao vira valor')
"

echo "== [4/6] LLM_FAKE=1 nao chama rede e nao inventa =="
$UV run python -c "
from pipeline import llm
r = llm.extrair_json(prompt='pergunta que ninguem gravou', campos=['potencia_cv'])
assert not r.ok and r.dados == {}, r
assert 'nao ha fixture' in r.motivo.replace('ã','a').replace('á','a'), r.motivo
assert r.uso.custo_brl == 0.0
print(f'   ok: sem fixture -> vazio com motivo; {len(llm.fixtures_disponiveis())} fixtures no repo')
"

echo "== [5/6] field_accuracy contra o gabarito (valor + grounding) =="
$UV run pytest -q tests/pipeline/test_extract.py -k "meta_de_field_accuracy or sem_grounding" -m "slow or not slow"

echo "== [6/6] fixtures de LLM declaram a origem =="
$UV run python -c "
import json
from pathlib import Path
pasta = Path('tests/fixtures/llm')
arquivos = sorted(pasta.glob('*.json'))
assert arquivos, 'nenhuma fixture de LLM'
for a in arquivos:
    d = json.loads(a.read_text(encoding='utf-8'))
    assert d.get('meta', {}).get('origem'), f'{a.name} sem origem no meta'
    assert d.get('dados'), f'{a.name} sem dados'
print(f'   ok: {len(arquivos)} fixtures, todas com origem declarada')
"

echo "WP-10 OK"
