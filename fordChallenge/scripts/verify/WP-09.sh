#!/usr/bin/env bash
# WP-09 — parser de PDF com tabelas por versao e limpeza de markdown.
#
# Comando da spec:
#   set -e; uv run pytest -q tests/pipeline/test_parse_pdf.py tests/pipeline/test_version_slicer.py
#
# Acrescentado: a limpeza de markdown (tambem escopo da WP-09), a regra de casamento que
# saiu para pipeline/matching.py, e o criterio de aceite conferido contra o GABARITO em
# vez de contra numeros repetidos no script.
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1 REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/6] ruff =="
$UV run ruff check pipeline tests/pipeline scripts
$UV run ruff format --check pipeline tests/pipeline scripts

echo "== [2/6] testes do parser e do slicer =="
$UV run pytest -q tests/pipeline/test_parse_pdf.py tests/pipeline/test_version_slicer.py

echo "== [3/6] testes da limpeza de markdown e do casamento de nome =="
$UV run pytest -q tests/pipeline/test_parse_html.py tests/pipeline/test_matching.py

echo "== [4/6] fixtures de PDF conferem com o PDF de origem =="
$UV run python scripts/build_fixtures.py --check

echo "== [5/6] criterio de aceite: recorte da SRX Plus contra o gabarito =="
$UV run python -c "
import json, re
from pathlib import Path
from pipeline.eval.gabarito import carregar_gabarito
from pipeline.parse.pdf import DocumentoPdf, Tabela
from pipeline.parse.version_slicer import recortar

base = Path('tests/fixtures/pdf/toyota_hilux_my26')
dados = json.loads((base / 'tables.json').read_text(encoding='utf-8'))
md = (base / 'doc.md').read_text(encoding='utf-8')
doc = DocumentoPdf(md, md.split(chr(10)*2), [Tabela.from_dict(t) for t in dados['tabelas']], dados['motor'])

r = recortar(doc, 'SRX Plus AT (Cabine Dupla)')
assert r.encontrou_a_versao, r.avisos
assert re.search(r'204\s*/', r.texto), 'faltou a potencia'
assert re.search(r'50,9\s*/', r.texto), 'faltou o torque'

hilux = carregar_gabarito().por_id('toyota_hilux_srx_plus_at_2026')
esperado = {c.campo: c.valor for c in hilux.campos if c.valor is not None}
assert r.valor('Pneus') == esperado['pneus_medida'], (r.valor('Pneus'), esperado['pneus_medida'])
assert esperado['rodas_material'].lower() in r.valor('Rodas').lower()
assert 'barra estabilizadora' in r.valor('Traseira').lower()
print(f'   ok: {len(r.celulas)} celulas da coluna {r.coluna}, pneus/rodas/suspensao batem com o gabarito')
"

echo "== [6/6] ficha da Ford tem Paddle Shifters e Matrix no doc.md do snapshot =="
$UV run python -c "
from pipeline.snapshots import snapshot_de_url
from pipeline.store import FIXTURES
url = ('https://www.ford.com.br/content/dam/Ford/website-assets/latam/br/nameplate/'
       '2025/ranger-raptor/pdf/fbr-ranger-raptor-ficha-tecnica.pdf')
snap = snapshot_de_url(url, [FIXTURES])
assert snap.tipo == 'pdf_oficial', snap.tipo
for alvo in ('Paddle Shifters', 'Matrix'):
    assert alvo in snap.texto, alvo
print('   ok: Paddle Shifters e Matrix presentes na ficha oficial da Raptor')
"

echo "WP-09 OK"
