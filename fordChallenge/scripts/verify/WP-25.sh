#!/usr/bin/env bash
# WP-25 — Change Radar: tipos de alerta, referencia interna (T0), impacto, reacao, tela.
#
# Comando da spec:
#   set -e; REPLAY_MODE=1 LLM_FAKE=1 uv run pytest -q tests/pipeline/test_radar.py \
#       tests/api/test_alerts.py; cd mobile && npx tsc --noEmit && npx jest --ci -t radar
#
# DUAS ADAPTACOES, e as duas estao registradas em DECISOES_NOITE.md:
#
# 1. `mobile/` virou `web/`. O maestro (doc 05) diz explicitamente "a tela e a do web app
#    (WP-31), nao Expo", e nao existe pasta `mobile/` neste repo. `npx jest -t radar` virou
#    `npx vitest run src/pages/Radar.test.tsx src/components/Layout.test.tsx`, que sao os
#    arquivos com "radar" no escopo (a tela e o selo da aba).
# 2. Acrescentei os passos [5] a [8]: os criterios de aceite que nenhum dos dois comandos
#    da spec cobre — o 403 do vendedor conferido na resposta HTTP, a faixa SIMULACAO
#    obrigatoria, o determinismo do refresh em replay, e a regra que impede a referencia
#    interna de virar valor de ficha.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ=$(pwd)

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1
export REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/8] regras do radar: impacto, reacao, referencia interna, tipos =="
$UV run pytest -q tests/pipeline/test_radar.py

echo "== [2/8] a API: /alerts, /internal-references, /equivalents =="
$UV run pytest -q tests/api/test_alerts.py tests/api/test_seed_equivalencias.py

echo "== [3/8] tipos e testes do web app =="
cd "$RAIZ/web"
npx tsc --noEmit
npx vitest run src/pages/Radar.test.tsx src/components/Layout.test.tsx
cd "$RAIZ"

echo "== [4/8] a migracao sobe e desce =="
$UV run alembic -c api/alembic.ini upgrade head >/dev/null
$UV run alembic -c api/alembic.ini current 2>/dev/null | tail -1
echo "   ok: head aplicado (0003_change_radar)"

echo "== [5/8] criterio: vendedor recebe 403 em /alerts =="
$UV run pytest -q tests/api/test_alerts.py -k "vendedor" -v 2>&1 | grep -E "PASSED|passed"

echo "== [6/8] criterio: is_simulated=true nunca aparece sem a faixa SIMULACAO =="
$UV run python -c "
import pathlib, re, sys

radar = pathlib.Path('web/src/pages/Radar.tsx').read_text(encoding='utf-8')
# A faixa e a etiqueta tem de estar amarradas ao PROPRIO campo is_simulated. Um literal
# solto (\`<FaixaDeSimulacao />\` sem condicao ligada ao dado) passaria a existir sempre —
# ou nunca — e o rotulo deixaria de dizer a verdade sobre aquele alerta.
assert 'alerta.is_simulated ?' in radar, 'a faixa do cartao nao depende de is_simulated'
assert \"etiqueta={alerta.is_simulated ? 'SIMULACAO' : 'FATO'}\" in radar, (
    'a etiqueta do alerta nao muda com is_simulated'
)
# O seed de demonstracao NAO pode ter caminho que grave alerta sem a marca.
refresh = pathlib.Path('pipeline/refresh.py').read_text(encoding='utf-8')
semear = refresh[refresh.index('def semear_alertas_simulados'):]
assert 'is_simulated=True' in semear, 'o seed simulado perdeu a marca'
assert 'is_simulated=False' not in semear, 'o seed simulado tem caminho sem a marca'
print('   ok: faixa e etiqueta ligadas a is_simulated; seed simulado sempre marcado')
"

echo "== [7/8] o refresh e determinista em replay (alerta so quando o valor muda) =="
$UV run python -c "
import pathlib, sqlite3, tempfile, os, subprocess, sys

# Banco descartavel: a segunda passada sobre os MESMOS snapshots tem de produzir zero
# alerta de mudanca. Alerta aparecendo aqui significa extracao nao reproduzivel.
tmp = pathlib.Path(tempfile.mkdtemp()) / 'verify25.db'
env = dict(os.environ, DATABASE_URL=f'sqlite:///{tmp.as_posix()}')
def rodar(*args):
    return subprocess.run([sys.executable, '-m', 'pipeline.cli', *args], env=env,
                          capture_output=True, text=True, encoding='utf-8')
# O schema vem da migracao, nao de create_all: e a mesma ordem de producao, e e o que
# prova que o 0003 sozinho basta para o Radar funcionar num banco novo.
migrar = subprocess.run([sys.executable, '-m', 'alembic', '-c', 'api/alembic.ini',
                         'upgrade', 'head'], env=env, capture_output=True, text=True,
                        encoding='utf-8')
assert migrar.returncode == 0, migrar.stdout + migrar.stderr
for passo in (('seed',),
              ('extract', 'Ford', 'Ranger', 'Raptor 3.0 V6 Bi-turbo 4WD AT',
               '--replay', '--persistir')):
    r = rodar(*passo)
    assert r.returncode == 0, r.stdout + r.stderr
primeira = rodar('refresh', '--watchlist')
segunda = rodar('refresh', '--watchlist')
assert primeira.returncode == 0 and segunda.returncode == 0, primeira.stderr + segunda.stderr
assert '0 alerta(s) de mudanca' in primeira.stdout, primeira.stdout
assert '0 alerta(s) de mudanca' in segunda.stdout, segunda.stdout
# E a divergencia com o material interno nao se repete a cada passada.
assert '0 de divergencia interna' in segunda.stdout, segunda.stdout
print('   ok: replay nao inventa mudanca, e a divergencia interna nao duplica')
print('   ' + primeira.stdout.strip().splitlines()[-1])
"

echo "== [8/8] a referencia interna nao vira valor de ficha =="
$UV run python -c "
import pathlib

# O 'T0' de docs/12 nomeia a origem; ele NAO e posicao na ordenacao (onde 1 e a mais
# forte). Uma linha interna em spec_values com tier=0 venceria o site oficial, e o Fogo
# Amigo se inverteria: o produto confirmaria o erro do deck com ar de autoridade.
router = pathlib.Path('api/app/routers/radar.py').read_text(encoding='utf-8')
alvo = router[router.index('async def importar_referencias'):router.index('/internal-references/modelo.csv')]
assert 'SpecValue(' not in alvo, 'o import de referencia interna esta gravando em spec_values'
assert 'InternalReference(' in alvo, 'o import parou de gravar internal_references'
interno = pathlib.Path('pipeline/radar/internal.py').read_text(encoding='utf-8')
assert 'TIER_INTERNO = 0' in interno
# O aviso e a unica coisa que impede a proxima pessoa de comparar este 0 com um tier.
# Colapsa o espaco antes de procurar: o texto do docstring e quebrado em linhas, e um
# portao que quebra quando alguem reflui um paragrafo e portao que alguem desliga.
corrido = ' '.join(interno.lower().replace('#:', ' ').split())
assert corrido.count('posição na ordenação') >= 2, 'o aviso sobre o tier 0 saiu do modulo'
print('   ok: internal_references em tabela propria; o 0 e rotulo, nao ordenacao')
"

echo "WP-25 OK"
