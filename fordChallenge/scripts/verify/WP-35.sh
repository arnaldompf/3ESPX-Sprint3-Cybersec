#!/usr/bin/env bash
# WP-35 — What-if / Counterfactual rotulado SIMULACAO.
#
# Comando da spec:
#   set -e; REPLAY_MODE=1 uv run pytest -q tests/pipeline/test_scenarios.py \
#       tests/api/test_scenarios.py; cd web && npx vitest run -t simulador
#
# Acrescentei os passos [4] a [7]. A nota da spec e "Observacao != inferencia != simulacao.
# Se perguntarem 'de onde veio o -5%': 'do usuario'", e sao esses passos que a tornam
# verificavel:
#
#   [4] o motor NAO PODE escrever: nao importa `sqlmodel` nem `api.app`, e a rota nao tem
#       `add`/`commit`/`merge`. O criterio de aceite "nenhum registro novo em spec_values"
#       passa a ser propriedade da arquitetura, e nao disciplina de quem edita;
#   [5] o valor hipotetico NAO ganha evidencia (citacao ao lado de numero que ninguem
#       observou seria prova de nada) e NAO desaparece da comparacao (o outro jeito de
#       errar: o simulador ficaria inerte, dizendo "nada mudou" para um corte de 5%);
#   [6] o rotulo SIMULACAO esta em CADA painel de cenario, com o texto literal — e nao no
#       painel de realidade, que e FATO;
#   [7] a flag dos 1.000 kg e recalculada por painel: cenario que remove a carga deixa a
#       regra INDETERMINADA, nunca "nao atinge". A frase fala de enquadramento fiscal.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ=$(pwd)

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1
export REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/7] o motor do simulador =="
$UV run pytest -q tests/pipeline/test_scenarios.py

echo "== [2/7] POST /scenarios =="
$UV run pytest -q tests/api/test_scenarios.py

echo "== [3/7] a tela do Simulador =="
cd "$RAIZ/web"
npx tsc --noEmit
npx vitest run -t simulador
cd "$RAIZ"

echo "== [4/7] o simulador nao tem como escrever =="
$UV run python -c "
import ast
import pathlib

# O motor: nenhum import de banco. Checagem na arvore sintatica, e nao no texto do
# arquivo — o proprio docstring cita 'commit' e 'api.app' para explicar que nao os usa, e
# uma regra que reprova codigo certo e regra ruim.
arvore = ast.parse(pathlib.Path('pipeline/scenarios.py').read_text(encoding='utf-8'))
importados = []
for no in ast.walk(arvore):
    if isinstance(no, ast.Import):
        importados += [a.name for a in no.names]
    elif isinstance(no, ast.ImportFrom):
        importados.append(no.module or '')
for proibido in ('sqlmodel', 'sqlalchemy', 'api', 'api.app'):
    ruins = [m for m in importados if m == proibido or m.startswith(proibido + '.')]
    assert not ruins, f'pipeline/scenarios.py importa {ruins}: passou a poder escrever'

# A rota e o servico: nenhuma chamada de escrita.
for caminho in ('api/app/routers/scenarios.py', 'api/app/services/scenario_service.py'):
    arvore = ast.parse(pathlib.Path(caminho).read_text(encoding='utf-8'))
    chamadas = [
        no.func.attr
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
    ]
    for proibida in ('commit', 'add', 'merge', 'flush', 'delete'):
        assert proibida not in chamadas, f'{caminho} chama {proibida}()'
print('   ok: o motor nao importa banco; rota e servico nao tem add/commit/merge/flush')
"

echo "== [5/7] a hipotese nao ganha evidencia, e nao sai da comparacao =="
$UV run python -c "
from pipeline import scenarios

def valores(mapa):
    return {
        campo: {'valor': v, 'status': 'verificado', 'unidade': None, 'evidence_id': 'ev-' + campo}
        for campo, v in mapa.items()
    }

ford = scenarios.Lado('v-ford', 'Ford Ranger', valores({'preco_sugerido_brl': 410000}))
conc = scenarios.Lado('v-conc', 'Toyota Hilux', valores({'preco_sugerido_brl': 420000}))
r = scenarios.simular(
    ford=ford,
    concorrentes=[conc],
    overrides=[scenarios.Override('v-conc', 'preco_sugerido_brl', delta_pct=-5)],
)

celula = next(c for c in r.cenario[0].coluna.celulas if c.campo == 'preco_sugerido_brl')
# 1) sem evidencia do lado simulado...
assert celula.evidence_id_concorrente is None, celula.evidence_id_concorrente
# 2) ...com evidencia do lado que ninguem mexeu...
assert celula.evidence_id_ford == 'ev-preco_sugerido_brl'
# 3) ...e o campo CONTINUA comparavel (a inercia silenciosa e o outro jeito de errar).
assert celula.estado == 'gap', celula.estado
assert celula.valor_concorrente == 399000

# 4) a realidade nao foi contaminada.
assert conc.valores['preco_sugerido_brl']['valor'] == 420000
assert conc.valores['preco_sugerido_brl']['evidence_id'] == 'ev-preco_sugerido_brl'

# 5) e a origem do numero e dita, com estas palavras.
aplicado = r.overrides_aplicados[0]
assert aplicado.origem == scenarios.ORIGEM
assert 'usuário' in aplicado.origem, aplicado.origem
print(f'   ok: {aplicado.antes} -> {aplicado.depois}, sem evidencia, estado {celula.estado}, origem dita')
"

echo "== [6/7] o rotulo SIMULACAO em cada painel de cenario, e so neles =="
$UV run python -c "
import pathlib

from pipeline import scenarios

def valores(mapa):
    return {
        campo: {'valor': v, 'status': 'verificado', 'unidade': None, 'evidence_id': 'ev'}
        for campo, v in mapa.items()
    }

r = scenarios.simular(
    ford=scenarios.Lado('v-ford', 'Ford', valores({'preco_sugerido_brl': 410000})),
    concorrentes=[scenarios.Lado('v-conc', 'Hilux', valores({'preco_sugerido_brl': 420000}))],
    overrides=[scenarios.Override('v-conc', 'preco_sugerido_brl', delta_pct=-5)],
)
dados = r.to_dict()

assert scenarios.ROTULO == 'SIMULAÇÃO — não é dado observado', scenarios.ROTULO
assert dados['is_simulation'] is True and dados['rotulo'] == scenarios.ROTULO
for painel in dados['cenario']:
    assert painel['is_simulation'] is True
    assert painel['rotulo_simulacao'] == scenarios.ROTULO, painel['rotulo_simulacao']
for painel in dados['atual']:
    assert painel['is_simulation'] is False
    assert painel['rotulo_simulacao'] == '', painel['rotulo_simulacao']

# A tela mostra o texto da API, e nao o texto de dado semeado: no simulador a hipotese e
# de quem esta olhando, e chamar isso de 'dado de demonstracao' seria impreciso.
tela = pathlib.Path('web/src/pages/Simulador.tsx').read_text(encoding='utf-8')
assert 'texto={painel.rotulo_simulacao}' in tela, 'a faixa do painel deixou de usar o texto da API'
assert 'data-testid=\"painel-cenario\"' in tela or 'painel-' in tela
print('   ok: rotulo literal em todo painel de cenario, ausente no de realidade')
"

echo "== [7/7] a flag dos 1.000 kg e por painel: remover a carga NAO vira 'nao atinge' =="
$UV run python -c "
from pipeline import scenarios

def valores(mapa):
    return {
        campo: {'valor': v, 'status': 'verificado', 'unidade': None, 'evidence_id': 'ev'}
        for campo, v in mapa.items()
    }

base = {'preco_sugerido_brl': 420000, 'capacidade_carga_kg': 1000}
ford = scenarios.Lado('v-ford', 'Ford', valores({'preco_sugerido_brl': 410000, 'capacidade_carga_kg': 1080}))

# Realidade: 1.000 kg atinge o limiar, com a fonte da ficha.
r = scenarios.simular(
    ford=ford,
    concorrentes=[scenarios.Lado('v-conc', 'Hilux', valores(base))],
    overrides=[scenarios.Override('v-conc', 'preco_sugerido_brl', delta_pct=-5)],
)
real = r.atual[0].to_dict()['coluna']['flag_de_carga']
assert real['aplicavel'] is True and real['valor'] is True, real

# Cenario que REMOVE a carga: indeterminada, nunca 'nao atinge'.
r = scenarios.simular(
    ford=ford,
    concorrentes=[scenarios.Lado('v-conc', 'Hilux', valores(base))],
    overrides=[scenarios.Override('v-conc', 'capacidade_carga_kg', remover=True)],
)
sem = r.cenario[0].to_dict()['coluna']['flag_de_carga']
assert sem['aplicavel'] is False, sem
assert sem['valor'] is None, sem
assert 'não avaliada é diferente de não atingida' in sem['motivo'], sem['motivo']
assert sem['texto'] == '', sem['texto']

# Cenario com carga HIPOTETICA acima do limiar: a frase cita o usuario como fonte.
r = scenarios.simular(
    ford=ford,
    concorrentes=[scenarios.Lado('v-conc', 'Hilux', valores(base))],
    overrides=[scenarios.Override('v-conc', 'capacidade_carga_kg', novo_valor=1200)],
)
hipotese = r.cenario[0].to_dict()['coluna']['flag_de_carga']
assert hipotese['valor'] is True
assert scenarios.FONTE_DA_HIPOTESE in hipotese['texto'], hipotese['texto']
# E a frase NAO promete enquadramento fiscal.
for proibido in ('isento', 'IPI', 'nao paga'):
    assert proibido not in hipotese['texto'], hipotese['texto']
print('   ok: flag real ok, removida indeterminada, hipotetica com a fonte do usuario')
"

echo "WP-35 OK"
