#!/usr/bin/env bash
# WP-34 — Materiality Engine e Truth-to-Action Trace ("Por que?").
#
# Comando da spec:
#   set -e; REPLAY_MODE=1 uv run pytest -q tests/pipeline/test_materiality.py \
#       tests/api/test_trace.py; cd web && npx vitest run -t "radar|porque"
#
# Acrescentei os passos [4] a [7]. A nota da spec e "Regras, nao LLM. A resposta a 'e dai?'
# tem que estar na tela em 2 cliques", e sao esses passos que a tornam verificavel:
#
#   [4] a faixa NUNCA viaja sem `rules_fired`, e todo peso tem descricao. "ALTA" sozinho e
#       um oraculo; "ALTA porque price_band_entry (40)" e uma afirmacao contestavel;
#   [5] os dois BDDs numericos, medidos: |dP%| de 0,55 da RUIDO (pelo VETO, nao pela soma)
#       e a entrada na faixa de +-5% da Ford comparavel da ALTA com `price_band_entry`;
#   [6] nenhum elo da cadeia sai em branco — onde falta dado, o elo diz o motivo. Elo vazio
#       parece prova, e e por isso que ele e pior que elo ausente;
#   [7] nada de LLM no caminho da materialidade. A spec poe "LLM redigindo" FORA de escopo,
#       e uma regra que fosse ao modelo tornaria a nota irreproduzivel entre duas leituras.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ=$(pwd)

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1
export REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/7] o motor de materialidade =="
$UV run pytest -q tests/pipeline/test_materiality.py

echo "== [2/7] a fila e a cadeia pela API =="
$UV run pytest -q tests/api/test_trace.py

echo "== [3/7] a fila de prioridade e o 'Por que?' na tela =="
cd "$RAIZ/web"
npx tsc --noEmit
npx vitest run -t "radar|porque"
cd "$RAIZ"

echo "== [4/7] a faixa nunca vem sem as regras, e todo peso tem descricao =="
$UV run python -c "
from pipeline.materiality import engine

cfg = engine.carregar()

# As quatro faixas de docs/13 3, cada uma dizendo o que pede de quem le.
assert {f.nome for f in cfg.faixas} == set(engine.FAIXAS), [f.nome for f in cfg.faixas]
for faixa in cfg.faixas:
    assert len(faixa.significado) > 40, faixa.nome

# Toda regra: tipo conhecido, descricao util. Tipo desconhecido LEVANTA na carga — uma
# regra que o motor ignora em silencio e uma linha de configuracao que mente.
for regra in cfg.regras:
    assert regra.tipo in engine.TIPOS, (regra.id, regra.tipo)
    assert len(regra.descricao) > 30, regra.id

# E a saida nunca leva a nota sozinha.
saida = engine.avaliar(engine.Contexto(campo='preco_sugerido_brl', delta_pct=-8.0)).to_dict()
assert saida['rules_fired'], saida
assert all(r['descricao'] and r['id'] for r in saida['rules_fired'])
assert 'escolha declarada' in saida['nota_de_hipotese'], saida['nota_de_hipotese']
assert 'yaml' not in saida['nota_de_hipotese'].lower(), saida['nota_de_hipotese']
print(f'   ok: {len(cfg.regras)} regras nomeadas, 4 faixas com significado, nota sempre com a regua')
"

echo "== [5/7] os dois BDDs numericos, medidos =="
$UV run python -c "
from pipeline.materiality import engine

# BDD 1 — preco FIPE da Amarok variando 0,55%: RUIDO.
#
# O peso da dimensao (+20) DISPARA aqui, e sem o veto a soma levava a variacao para BAIXA.
# A conta fica visivel em rules_fired; quem decide e o veto.
ruido = engine.avaliar(engine.Contexto(
    campo='preco_fipe_brl', antes=294378, depois=296000, delta_pct=0.55,
    dimensoes_afetadas=('preco', 'revenda'),
))
ids = [r.id for r in ruido.rules_fired]
assert ruido.faixa == engine.RUIDO, (ruido.faixa, ids, ruido.pontos)
assert 'ruido_de_tabela' in ids, ids
assert ruido.pontos > 0, 'o veto tem de vencer uma soma positiva, senao nao e veto'

# BDD 2 — preco oficial da Hilux caindo para dentro da faixa de +-5% da Ranger: ALTA.
alta = engine.avaliar(engine.Contexto(
    campo='preco_sugerido_brl', antes=420000, depois=395000, delta_pct=-5.95,
    dimensoes_afetadas=('preco',), preco_ford_comparavel=390000,
))
ids_alta = [r.id for r in alta.rules_fired]
assert alta.faixa == engine.ALTA, (alta.faixa, ids_alta, alta.pontos)
assert 'price_band_entry' in ids_alta, ids_alta

# A fila: ALTA na frente de MEDIA sempre, com a pontuacao desempatando DENTRO da faixa.
limiar = next(f.minimo for f in engine.carregar().faixas if f.nome == engine.ALTA)
assert engine.rank_de(engine.ALTA, limiar) < engine.rank_de(engine.MEDIA, limiar - 1)
assert engine.rank_de(engine.ALTA, 125) < engine.rank_de(engine.ALTA, 70)
assert engine.rank_de(engine.RUIDO, 20) > engine.rank_de(engine.BAIXA, 20)
print(f'   ok: RUIDO {ruido.pontos:g} {ids} | ALTA {alta.pontos:g} {ids_alta}')
print(f'   ok: rank alta {alta.priority_rank} < ruido {ruido.priority_rank}')
"

echo "== [6/7] nenhum elo da cadeia sai em branco =="
$UV run python -c "
import datetime as dt
import os, pathlib, tempfile

tmp = pathlib.Path(tempfile.mkdtemp()) / 'verify34.db'
os.environ['DATABASE_URL'] = f'sqlite:///{tmp.as_posix()}'

from sqlmodel import Session, SQLModel, create_engine

import api.app.models as m
from api.app.services import materiality_service

engine = create_engine(f'sqlite:///{tmp.as_posix()}')
SQLModel.metadata.create_all(engine)

with Session(engine) as s:
    # Um alerta SEM evidencia nenhuma: o caso em que o elo poderia sair em branco.
    alerta = m.Alert(
        type='preco_fipe', field='preco_fipe_brl', old=294378, new=296000,
        impact_json={'delta_pct': 0.55, 'dimensoes_afetadas': ['preco']},
        is_simulated=False, created_at=dt.datetime(2026, 9, 6),
    )
    s.add(alerta)
    s.commit()
    cadeia = materiality_service.trace(s, alerta)

# Cada elo da cadeia: ou tem conteudo, ou tem um motivo escrito ao lado.
assert cadeia['acao_sugerida'], cadeia
assert cadeia['regras'], 'a faixa sem as regras e um oraculo'
assert cadeia['mudanca']['campo_canonico'] and cadeia['mudanca']['before'] is not None
assert cadeia['evidencias'] == [] and cadeia['motivo_sem_evidencia'], cadeia['motivo_sem_evidencia']
assert cadeia['snapshots'] == [] and cadeia['motivo_sem_snapshot'], cadeia['motivo_sem_snapshot']
assert cadeia['comparavel']['version_id'] or cadeia['comparavel']['motivo'], cadeia['comparavel']
assert cadeia['significado'] and cadeia['nota_dos_pesos']

# E o motivo NAO sugere contornar nada nem inventar o dado que falta.
for chave in ('motivo_sem_evidencia', 'motivo_sem_snapshot'):
    texto = cadeia[chave].lower()
    for proibido in ('estimado', 'provavelmente', 'assumimos'):
        assert proibido not in texto, (chave, texto)

# A cadeia do alerta SIMULADO diz 'hipotese' na acao, nao so numa etiqueta de canto.
with Session(engine) as s:
    simulado = m.Alert(
        type='preco_oficial', field='preco_sugerido_brl', old=430000, new=395600,
        impact_json={'delta_pct': -8.0}, is_simulated=True,
        created_at=dt.datetime(2026, 9, 7),
    )
    s.add(simulado)
    s.commit()
    hipotese = materiality_service.trace(s, simulado)
assert hipotese['is_simulated'] is True
assert 'SIMULA' in hipotese['acao_sugerida']
assert 'hipótese' in hipotese['acao_sugerida'], hipotese['acao_sugerida']
print('   ok: 5 elos preenchidos ou com motivo; alerta simulado diz hipotese na acao')
"

echo "== [7/7] regras, nao LLM: nada de modelo no caminho da materialidade =="
$UV run python -c "
import pathlib

# 'LLM redigindo' esta FORA de escopo na spec. O motivo nao e purismo: a nota tem de sair
# igual nas duas leituras do mesmo alerta, e uma chamada de modelo no meio quebraria isso
# sem quebrar nenhum teste — a nota apenas mudaria de vez em quando.
for caminho in (
    'pipeline/materiality/engine.py',
    'pipeline/materiality/rules.yaml',
    'api/app/services/materiality_service.py',
):
    texto = pathlib.Path(caminho).read_text(encoding='utf-8')
    corpo = '\n'.join(
        linha for linha in texto.splitlines()
        if not linha.lstrip().startswith(('#', '*', '\"\"\"'))
    )
    for proibido in ('anthropic', 'llm_client', 'llm_rewrite', 'completions'):
        assert proibido not in corpo.lower(), f'{caminho} chama {proibido}'

# A tela tambem nao escreve uma segunda definicao do que e 'ALTA': o significado vem da
# API, que o le do rules.yaml. Duas copias da mesma frase divergem na primeira revisao.
tela = pathlib.Path('web/src/lib/materialidade.ts').read_text(encoding='utf-8')
for frase in ('altera a posi', 'revisão da semana', 'arredondamento de tabela'):
    assert frase not in tela, f'a tela copiou a definicao da faixa: {frase!r}'
print('   ok: materialidade por regra, sem LLM, e a definicao da faixa mora no YAML')
"

echo "WP-34 OK"
