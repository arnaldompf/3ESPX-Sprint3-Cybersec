#!/usr/bin/env bash
# WP-26 — Customer Need Engine, custo de uso e conector PBE/Inmetro.
#
# Comando da spec:
#   set -e; REPLAY_MODE=1 uv run pytest -q tests/pipeline/test_fit.py \
#       tests/pipeline/test_usage_cost.py tests/api/test_comparisons_fit.py; \
#       cd mobile && npx tsc --noEmit && npx jest --ci -t showroom
#
# `mobile/` virou `web/` (o maestro diz que a tela e a do web app), e `jest -t showroom`
# virou `vitest run -t showroom`. Os passos [4] a [7] sao acrescimo, e cada um trava uma
# regra que os comandos da spec nao alcancam:
#
#   [4] "nunca penalizar dado faltante em silencio" — a nota da spec, verificada nos tres
#       caminhos: campo sai dos DOIS lados, dimensao insuficiente sai do total, e o
#       denominador do total e o peso CONSIDERADO;
#   [5] o rotulo obrigatorio esta na resposta e na tela;
#   [6] as faixas sao versionadas e recalculadas so por comando explicito;
#   [7] o conector do PBE atribui o consumo a versao CERTA — a pagina da Hilux tem quatro
#       frases de consumo, uma por configuracao.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ=$(pwd)

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1
export REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/7] as regras do motor de aderencia =="
$UV run pytest -q tests/pipeline/test_fit.py

echo "== [2/7] o custo de uso =="
$UV run pytest -q tests/pipeline/test_usage_cost.py

echo "== [3/7] a API e a tela =="
$UV run pytest -q tests/api/test_comparisons_fit.py
cd "$RAIZ/web"
npx tsc --noEmit
npx vitest run -t showroom
cd "$RAIZ"

echo "== [4/7] dado faltante nunca e penalizado em silencio =="
$UV run python -c "
from pipeline.fit import engine, ranges
from pipeline.fit.engine import NeedsProfile

faixas = ranges.Faixas(
    versao='verify',
    por_campo={
        'potencia_cv': ranges.Faixa('potencia_cv', 200.0, 400.0, 4, 'verify'),
        'torque_nm': ranges.Faixa('torque_nm', 500.0, 600.0, 4, 'verify'),
        'aceleracao_0_100_s': ranges.Faixa('aceleracao_0_100_s', 5.0, 11.0, 3, 'verify'),
    },
)
perfil = NeedsProfile(prioridades_rank=['desempenho'])

# 1. Campo faltando de um lado sai dos DOIS. Se saisse so do lado que falta, o outro
#    ganharia a dimensao por ter sido melhor coletado — o sistema premiaria a propria
#    cobertura em vez de medir o carro.
ford = {'potencia_cv': 250, 'torque_nm': 520, 'aceleracao_0_100_s': 9.0}
conc = {'potencia_cv': None, 'torque_nm': 520, 'aceleracao_0_100_s': 9.0}
r = engine.avaliar(ford, conc, perfil, faixas=faixas)
d = next(x for x in r.dimensoes if x.id == 'desempenho')
assert 'potencia_cv' not in d.campos_usados, d.campos_usados
assert d.nota_ford == d.nota_concorrente, (d.nota_ford, d.nota_concorrente)
assert any(c['campo'] == 'potencia_cv' for c in d.campos_sem_dado)

# 2. Dimensao com cobertura abaixo do minimo sai do total, marcada e com aviso.
conc2 = {'potencia_cv': 200, 'torque_nm': None, 'aceleracao_0_100_s': None}
r2 = engine.avaliar(ford, conc2, perfil, faixas=faixas)
d2 = next(x for x in r2.dimensoes if x.id == 'desempenho')
assert d2.insuficiente is True
assert 'excluida do total' in d2.aviso.replace('í', 'i').replace('í', 'i') or 'exclu' in d2.aviso
assert r2.aderencia_ford is None, r2.aderencia_ford

# 3. O total divide pelo peso CONSIDERADO, nao por 100. Dividir por 100 diluiria a nota
#    pelo peso das dimensoes excluidas — falta de dado viraria nota baixa.
otimo = {'potencia_cv': 400, 'torque_nm': 600, 'aceleracao_0_100_s': 5.0}
pessimo = {'potencia_cv': 200, 'torque_nm': 500, 'aceleracao_0_100_s': 11.0}
r3 = engine.avaliar(otimo, pessimo, perfil, faixas=faixas)
assert r3.peso_considerado == 35, r3.peso_considerado
assert r3.aderencia_ford == 10.0, r3.aderencia_ford
assert any('35% do peso' in a for a in r3.avisos), r3.avisos
print('   ok: campo sai dos dois, dimensao insuficiente fora do total, denominador honesto')
"

echo "== [5/7] o rotulo obrigatorio, na resposta e na tela =="
$UV run python -c "
import pathlib

from pipeline.fit import dimensions, engine, ranges

esperado = 'Aderência ao perfil informado — não é um ranking de qualidade'
assert dimensions.carregar().rotulo_obrigatorio == esperado

r = engine.avaliar({'potencia_cv': 397}, {'potencia_cv': 204},
                   engine.NeedsProfile(prioridades_rank=['desempenho']),
                   faixas=ranges.carregar())
assert r.rotulo == esperado
assert r.to_dict()['rotulo'] == esperado

tela = pathlib.Path('web/src/pages/Showroom.tsx').read_text(encoding='utf-8')
assert 'rotulo-obrigatorio' in tela, 'a tela perdeu o rotulo'
assert '{fit.rotulo}' in tela, 'a tela deixou de ler o rotulo da resposta'
# E a tela nao pode reescrever o rotulo por conta propria.
assert 'ranking de qualidade' not in tela.split('*/')[-1], (
    'a tela tem o texto do rotulo escrito a mao; ele tem de vir da API'
)
print('   ok: rotulo literal, vindo da API para a tela')
"

echo "== [6/7] as faixas sao versionadas e o recalculo e explicito =="
$UV run python -c "
import pathlib

from pipeline.fit import ranges

arquivo = pathlib.Path('pipeline/fit/scoring_ranges.yaml')
assert arquivo.exists(), 'scoring_ranges.yaml nao existe; rode specradar fit recompute-ranges'
texto = arquivo.read_text(encoding='utf-8')
assert 'GERADO por' in texto, 'o arquivo perdeu o aviso de que e gerado'
assert 'versao:' in texto

faixas = ranges.carregar()
assert faixas.versao and faixas.por_campo
# Toda faixa com procedencia: sem 'de_onde', ninguem sabe o que formou a regua.
for campo, faixa in faixas.por_campo.items():
    assert faixa.de_onde, campo
    if faixa.amostras < ranges.MINIMO_DE_AMOSTRAS:
        assert faixa.insuficiente, campo

# Faixa insuficiente da nota NEUTRA, nao 0 nem 10.
from pipeline.fit import dimensions, engine

campo = dimensions.CampoDaDimensao(campo='tanque_l', tipo='numerico', direcao='maior')
uma_so = ranges.Faixas(
    versao='v', por_campo={'tanque_l': ranges.Faixa('tanque_l', 80.0, 80.0, 1, 'v', True)}
)
nota = engine.nota_de_campo(campo, 80, faixas=uma_so)
assert nota.nota == ranges.NOTA_NEUTRA, nota
assert 'insuficiente' in nota.motivo
print(f'   ok: faixas de {faixas.versao}, {len(faixas.por_campo)} campo(s), com procedencia')
"

echo "== [7/7] o PBE atribui o consumo a versao certa =="
$UV run python -c "
import pathlib

from pipeline.connectors import pbe

caminho = pathlib.Path(
    'tests/fixtures/snapshots/toyota_hilux_srx_plus_at_2026/'
    '2026-09-01T00-00-00Z/toyota_site_cd/page.md'
)
texto = caminho.read_text(encoding='utf-8')

# A pagina tem QUATRO frases do PBEV, uma por configuracao. Ler a primeira daria o consumo
# do vizinho com evidencia que groundeia — errado com procedencia.
registros = pbe.parse(texto)
assert len(registros) == 4, len(registros)

srx = pbe.consumo_de(texto, versao='SRX Plus AT (Cabine Dupla)', modelo='Hilux')
assert srx.tem_valor, srx.motivo
assert (srx.registro.urbano_kml, srx.registro.rodoviario_kml) == (9.7, 10.6), srx.registro
assert 'SRX Plus' in srx.registro.descricao

# Outra versao, outro numero. Se o casamento fosse frouxo, os dois dariam o mesmo.
sr = pbe.consumo_de(texto, versao='SR AT', modelo='Hilux')
assert sr.tem_valor and (sr.registro.urbano_kml, sr.registro.rodoviario_kml) == (9.3, 10.0)

# Versao que a pagina nao descreve: RECUSA, com o motivo, em vez do numero do vizinho.
nenhuma = pbe.consumo_de(texto, versao='Versao Que Nao Existe', modelo='Hilux')
assert not nenhuma.tem_valor
assert 'outras versoes' in nenhuma.motivo.replace('õ', 'o'), nenhuma.motivo

# Coleta ao vivo: declarada e NAO executada (sem Docling, e rede so o necessario).
try:
    pbe.baixar_tabela()
    raise SystemExit('ERRO: baixar_tabela deveria levantar sem autorizacao')
except pbe.ColetaNaoDisponivel as exc:
    assert 'uv sync --extra pdf' in str(exc), str(exc)

# E a pagina inteira nao pode mais oferecer as quatro frases ao extrator.
from pipeline.run import _sem_frases_ambiguas_do_pbev

limpo = _sem_frases_ambiguas_do_pbev(texto)
assert len(pbe.parse(limpo)) == 0, 'as frases ambiguas continuam na pagina'
print('   ok: 4 frases, casamento por versao, recusa com motivo, coleta ao vivo declarada')
"

echo "WP-26 OK"
