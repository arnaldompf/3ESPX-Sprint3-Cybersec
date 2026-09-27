#!/usr/bin/env bash
# WP-32 — Comparable Set, Parity Matrix (4 estados) e regra dos 1.000 kg.
#
# Comando da spec:
#   set -e; REPLAY_MODE=1 uv run pytest -q tests/pipeline/test_comparables.py \
#       tests/pipeline/test_parity.py tests/api/test_parity.py; \
#       cd web && npx vitest run -t matriz
#
# Acrescentei os passos [4] a [7]. Todos verificam regra de produto que os dois comandos
# da spec nao alcancam, e todos ja pegaram algo:
#
#   [4] "k/n, nunca porcentagem" (docs/13 §3) conferido no codigo e na resposta da API;
#   [5] o quarto estado nao pode ser filtrado nem colapsado — e a legenda tem de dizer
#       que `desconhecido` nunca aparece como empate;
#   [6] o texto da flag de 1.000 kg e LITERAL e nao fala de imposto. Este e o passo que
#       protege contra o "melhoramento" mais provavel do texto ("logo, isento de IPI"),
#       que seria orientacao tributaria dada por um extrator de ficha tecnica;
#   [7] a regua de paridade e a MESMA do eval. Se divergirem, a tela exibe vantagem sobre
#       o que o eval trata como o mesmo numero.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ=$(pwd)

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1
export REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/7] as regras: comparaveis e paridade =="
$UV run pytest -q tests/pipeline/test_comparables.py tests/pipeline/test_parity.py

echo "== [2/7] a API: /comparables e /parity =="
$UV run pytest -q tests/api/test_parity.py

echo "== [3/7] a tela da matriz =="
cd "$RAIZ/web"
npx tsc --noEmit
npx vitest run -t matriz
cd "$RAIZ"

echo "== [4/7] k/n, nunca porcentagem =="
$UV run python -c "
import pathlib, re

from pipeline import comparables

# O resumo e a unica frase que resume a comparabilidade, e ela nao pode virar porcentagem.
r = comparables.avaliar(
    {'segmento': 'picape media', 'combustivel': 'gasolina', 'finalidade': ['desempenho']},
    {'segmento': 'picape media', 'combustivel': 'diesel', 'finalidade': ['trabalho']},
)
assert '/' in r.resumo and '%' not in r.resumo, r.resumo
assert r.criterios_avaliaveis <= r.total_de_criterios

# E o denominador nao pode incluir o que ninguem mediu.
assert r.criterios_atendidos + len(r.nao_atendidos) == r.criterios_avaliaveis

# Nenhuma das telas deste WP pode calcular porcentagem de comparabilidade.
tela = pathlib.Path('web/src/pages/Matriz.tsx').read_text(encoding='utf-8')
assert 'criterios_atendidos /' not in tela, 'a tela esta dividindo criterios para virar %'
assert not re.search(r'criterios_a\w+\s*\*\s*100', tela), 'a tela esta calculando porcentagem'
print(f'   ok: resumo = {r.resumo!r}, sem porcentagem em lugar nenhum')
"

echo "== [5/7] o quarto estado: nem filtrado, nem colapsado em empate =="
$UV run python -c "
import pathlib

from pipeline import parity
from pipeline.schema import Status

# Ausencia de um lado -> desconhecido. Este e o criterio de aceite da Amarok.
c = parity.comparar_campo(
    'potencia_rpm', valor_ford=5650, valor_concorrente=None,
    status_concorrente=Status.NAO_ENCONTRADO,
)
assert c.estado == parity.DESCONHECIDO, c.estado
assert c.motivo_tipo == parity.SEM_DADO_CONCORRENTE

# Os dois desconhecidos sao distinguiveis: falta de dado e falta de ordem de merito.
cruzado = parity.comparar_campo(
    'modos_conducao', valor_ford=['baja'], valor_concorrente=['lama'],
)
assert cruzado.estado == parity.DESCONHECIDO
assert cruzado.motivo_tipo != c.motivo_tipo

# A legenda tem de dizer, em palavras, que desconhecido nao e empate.
legenda = parity.LEGENDA[parity.DESCONHECIDO].lower()
assert 'nunca' in legenda and 'empate' in legenda, legenda
assert 'sempre' in parity.LEGENDA[parity.GAP].lower()

# A tela conta o desconhecido em vez de descartar as celulas.
tela = pathlib.Path('web/src/pages/Matriz.tsx').read_text(encoding='utf-8')
assert 'estado-desconhecido' in tela or 'desconhecido' in tela
assert \"filter((c) => c.estado !== 'desconhecido')\" not in tela, (
    'a tela esta filtrando as celulas desconhecidas'
)
print('   ok: desconhecido de primeira classe, com dois motivos distinguiveis')
"

echo "== [6/7] o texto da flag de 1.000 kg e literal e nao fala de imposto =="
$UV run python -c "
from pipeline import comparables

texto = comparables.TEXTO_DA_FLAG_DE_CARGA
# LITERAL: a frase da spec, palavra por palavra.
esperado = (
    'Capacidade de carga ≥ 1.000 kg ({fonte}). Critério comumente associado à '
    'classificação como veículo de carga; confirmar enquadramento fiscal com a Ford.'
)
assert texto == esperado, f'o texto fixo mudou:\n{texto!r}'
for proibido in ('ipi', 'icms', 'imposto', 'isento', 'aliquota', 'alíquota', '%'):
    assert proibido not in texto.lower(), f'o texto passou a falar de {proibido}'
assert comparables.ETIQUETA_DA_FLAG_DE_CARGA == 'INFERENCIA'

# Sem valor de carga a flag e INDETERMINADA. 'Nao atinge 1.000 kg' sobre uma picape cuja
# carga ninguem encontrou seria afirmar um fato a partir de uma ausencia.
sem = comparables.flag_de_carga(None)
assert sem.aplicavel is False and sem.valor is None, sem
assert comparables.flag_de_carga(1000).valor is True
assert comparables.flag_de_carga(999).valor is False
print('   ok: texto literal, etiqueta INFERENCIA, ausencia != negativa')
"

echo "== [7/7] a regua de paridade e a MESMA do eval =="
$UV run python -c "
import inspect

from pipeline import parity
from pipeline.eval import compare

# Nao ha limiar proprio: o modulo importa a tolerancia do eval.
fonte = inspect.getsource(parity)
assert 'from pipeline.eval.compare import tolerancia_de' in fonte, (
    'parity.py parou de usar a tolerancia do eval'
)
for campo in ('potencia_cv', 'torque_nm', 'preco_sugerido_brl', 'aceleracao_0_100_s'):
    tol = compare.tolerancia_de(campo)
    quase = parity.comparar_campo(
        campo, valor_ford=100.0, valor_concorrente=100.0,
    )
    assert quase.estado == parity.PARIDADE, campo
    assert tol.descricao(), campo

# 397 contra 398 cv e o mesmo motor para qualquer efeito comercial.
assert parity.comparar_campo('potencia_cv', valor_ford=397, valor_concorrente=398).estado == (
    parity.PARIDADE
)
# E preco: menos e melhor para quem compra, mais e gap.
assert parity.comparar_campo(
    'preco_sugerido_brl', valor_ford=380000, valor_concorrente=348790
).estado == parity.GAP
print('   ok: paridade pela tolerancia do eval, direcao de merito por campo')
"

echo "WP-32 OK"
