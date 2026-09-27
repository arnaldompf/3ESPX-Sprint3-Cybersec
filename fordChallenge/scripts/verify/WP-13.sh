#!/usr/bin/env bash
# WP-13 — conector FIPE e coleta de preco oficial.
#
# Comando da spec:
#   set -e; REPLAY_MODE=1 uv run pytest -q tests/pipeline/test_fipe.py tests/pipeline/test_price.py
#
# Acrescentado: os tres criterios de aceite (BDD) conferidos direto contra as FONTES
# SALVAS e os valores do gabarito, mais duas guardas do que esta WP quase errou — o preco
# de outra versao entrando como se fosse desta, e o tier do documento inflando o tier do
# valor de mercado.
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1 REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/6] ruff =="
$UV run ruff check pipeline tests
$UV run ruff format --check pipeline tests

echo "== [2/6] testes da spec =="
$UV run pytest -q tests/pipeline/test_fipe.py tests/pipeline/test_price.py

echo "== [3/6] os tres criterios de aceite =="
$UV run python -c "
from pipeline.connectors.fipe import CONFIANCA_MAXIMA_T3, find_code, preco_oficial, price
from pathlib import Path

RAIZ = Path('tests/fixtures/snapshots')
def fonte(padrao):
    return next(RAIZ.glob(padrao)).read_text(encoding='utf-8')

# 1. Codigo 003506-8 em replay -> preco com fipe_referencia='2026-09'
c = price('003506-8')
assert c.referencia == '2026-09', c.referencia
assert c.preco_brl == 452540, c.preco_brl   # gabarito: verificado, tier 2
assert c.tier == 2, c.tier

# 2. Hilux SRX Plus -> codigo_fipe='002215-2' pelo fuzzy
MODELOS = {
    'HILUX CD SRX PLUS 4X4 2.8 TDI Die. Aut.': '002215-2',
    'HILUX CD SRX 4X4 2.8 TDI 16V Die. Aut.': '002214-4',
    'HILUX CS Chassi 4X4 3.0 TDI Die.': '002133-4',
}
r = find_code('Toyota', 'Hilux', 'SRX Plus AT', modelos_fipe=MODELOS)
assert r.codigo == '002215-2', (r.codigo, r.motivo)

# 3. Site sem preco por versao (Amarok) -> T3 com nota e confianca <= 0,6
p = preco_oficial(fonte('vw_amarok_v6_extreme_2026/*/autoesporte_amarok/page.md'),
                  versao='V6 Extreme', tier=3, fonte='autoesporte')
assert p.valor_brl == 379990, p.valor_brl   # gabarito: verificado_tier3
assert p.tier == 3 and p.confianca <= CONFIANCA_MAXIMA_T3, (p.tier, p.confianca)
assert 'imprensa' in p.nota, p.nota
print('   ok: os tres criterios de aceite passam')
"

echo "== [4/6] o preco e da VERSAO pedida, nunca da vizinha =="
$UV run python -c "
from pathlib import Path
from pipeline.connectors.fipe import preco_oficial

RAIZ = Path('tests/fixtures/snapshots')
def fonte(padrao):
    return next(RAIZ.glob(padrao)).read_text(encoding='utf-8')

# A pagina da S10 lista SETE precos. Pegar 'o preco da pagina' daria 265.690 para a
# High Country — erro grande, silencioso e plausivel.
s10 = fonte('chevrolet_s10_high_country_2027/*/chevrolet_site/page.md')
p = preco_oficial(s10, versao='S10 High Country', tier=1)
assert p.valor_brl == 348790, p.valor_brl   # gabarito: verificado, tier 1
assert '348.790' in p.quote, p.quote

# A Hilux e o caso inverso: a pagina da LINHA exibe so o preco da versao de entrada, e o
# gabarito manda pendente_coleta — 'nao inferir'. Sem valor e a resposta certa.
hilux = fonte('toyota_hilux_srx_plus_at_2026/*/toyota_site_cd/page.md')
p = preco_oficial(hilux, versao='SRX Plus AT (Cabine Dupla)', tier=1)
assert p.valor_brl is None, p.valor_brl
assert 'nao inferir' in p.nota.replace('ã','a'), p.nota
print('   ok: preco da versao certa, e sem valor quando a fonte nao associa')
"

echo "== [5/6] tier do valor vem do TIPO DE FONTE, nao do documento =="
$UV run python -c "
from pipeline.connectors.fipe import TIER_FIPE, price
from pipeline.store import snapshots_de

registro = [s for s in snapshots_de('ford_ranger_raptor_2026') if s.tipo == 'registro_de_evidencia']
assert registro, 'o registro de evidencias do Raptor tem de existir'
assert registro[0].tier == 1, registro[0].tier
c = price('003506-8')
assert 'registro_de_evidencia' in c.origem, c.origem
assert c.tier == TIER_FIPE == 2, c.tier
print(f'   ok: documento tier {registro[0].tier}, valor FIPE tier {c.tier} (nao herdou)')
"

echo "== [6/6] preco sem referencia mensal nunca esta ok =="
$UV run python -c "
from pipeline.connectors.fipe import ConsultaFipe, parse_pagina_fipe
assert not ConsultaFipe(preco_brl=452540).ok, 'preco sem referencia nao vale'
c = parse_pagina_fipe('Codigo FIPE:\t005506-9\nPreco:\tR\$ 339.270,00')
assert c.preco_brl == 339270 and not c.ok, (c.preco_brl, c.ok)
print('   ok: R\$ 452.540 sem dizer de que mes e um numero sem validade')
"

echo "WP-13 OK"
