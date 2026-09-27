#!/usr/bin/env bash
# WP-33 — Saude do Conhecimento, cobertura por montadora e radar de divergencias.
#
# Comando da spec:
#   set -e; REPLAY_MODE=1 uv run pytest -q tests/pipeline/test_health.py \
#       tests/api/test_insights_health.py; cd web && npx vitest run -t saude
#
# Acrescentei os passos [4] a [6]. A nota da spec e "sempre explicar por que um campo
# falta. Nunca '89% verdadeiro'", e sao esses passos que a tornam verificavel:
#
#   [4] o texto fixo e literal, e nenhum indicador vira porcentagem de verdade;
#   [5] todo status sai de uma REGRA NOMEADA, e a ordem das regras esta certa — se
#       "sem campo nenhum" nao vencer "sem conflito", uma ficha vazia sai como OK;
#   [6] a fonte bloqueada e persistida como estado. Antes da WP-33 ela vivia so na
#       memoria do job: o painel diria "0 fontes bloqueadas", que e pior que nao ter o
#       indicador, porque afirma o contrario do que aconteceu.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ=$(pwd)

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1
export REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/6] as regras da saude =="
$UV run pytest -q tests/pipeline/test_health.py

echo "== [2/6] a API: saude, cobertura e divergencias =="
$UV run pytest -q tests/api/test_insights_health.py

echo "== [3/6] a tela de Saude =="
cd "$RAIZ/web"
npx tsc --noEmit
npx vitest run -t saude
cd "$RAIZ"

echo "== [4/6] o texto fixo, e nenhuma porcentagem de verdade =="
$UV run python -c "
import pathlib

from pipeline import health

assert health.TEXTO_FIXO == (
    'indicador operacional do MVP, não probabilidade de verdade'
), health.TEXTO_FIXO

# Todo indicador tem denominador, e denominador zero da fracao None — nao 0.0. Zero
# afirmaria 'nenhum de muitos'; None diz 'nao medimos'.
assert health.Indicador(0, 0).fracao is None
assert health.Indicador(0, 10).fracao == 0.0

# A tela nao pode transformar a fracao em '% de confianca' nem em '% verdadeiro'.
#
# A checagem olha o JSX, nao o arquivo inteiro: o docstring do modulo CITA o texto fixo
# ('nao probabilidade de verdade'), e a primeira versao deste passo reprovou por causa da
# propria frase que a spec manda exibir. Regra que acusa codigo certo e regra ruim.
tela = pathlib.Path('web/src/pages/Saude.tsx').read_text(encoding='utf-8')
jsx = tela[tela.index('const APARENCIA'):]
for proibido in ('de confiança', 'confiabilidade', '% verdade', 'saúde:'):
    assert proibido not in jsx, f'a tela passou a falar de {proibido!r}'
assert 'texto-fixo' in jsx, 'o texto fixo saiu do cartao'
# A barra de proporcao e legitima (cobertura de campo com fonte oficial), e por isso ela
# tem de mostrar o valor/de ao lado: proporcao sem denominador vira um numero solto.
#
# SEM BACKTICK NESTE BLOCO. O codigo vai dentro de python -c \" ... \", e dentro de aspas
# duplas o backtick e substituicao de comando do shell: a primeira versao desta linha
# escrevia valor/de entre backticks e o bash tentou EXECUTAR 'valor/de'.
assert '{indicador.valor}/{indicador.de}' in jsx, 'a barra perdeu o denominador ao lado'
print('   ok: texto fixo literal, denominadores presentes, sem porcentagem de verdade')
"

echo "== [5/6] todo status vem de uma regra nomeada, e a ordem esta certa =="
$UV run python -c "
import datetime as dt

from pipeline import health
from pipeline.health import LinhaDeCampo

# A ordem e a regra: ficha VAZIA tem de sair INSUFICIENTE por 'sem_campos', e nao OK por
# nao ter conflito. Um painel que aprova a ficha vazia e o pior resultado possivel,
# porque nada acusa.
vazia = health.avaliar([])
assert vazia.status == health.INSUFICIENTE, vazia.status
assert vazia.regra_do_status == 'sem_campos', vazia.regra_do_status

# Toda regra com nome, status valido e explicacao util.
for regra in health.REGRAS_DO_STATUS:
    assert regra.nome and regra.status in health.STATUS
    assert len(regra.explicacao) > 40, regra.nome

# A ultima e pega-tudo: sem ela, um estado nao previsto sairia com o status default.
assert health.REGRAS_DO_STATUS[-1].condicao(vazia) is True
assert health.REGRAS_DO_STATUS[-1].status == health.OK

# E cada campo problematico carrega o MOTIVO — 'sempre explicar por que um campo falta'.
agora = dt.datetime(2026, 9, 9)
velho = LinhaDeCampo(
    campo='preco_sugerido_brl',
    status='verificado',
    tier=1,
    captured_at=agora - dt.timedelta(days=45),
)
saude = health.avaliar([velho], limiar_de_dias=30, agora=agora)
problema = saude.desatualizados.campos[0]
assert '45 dias' in problema.motivo and '30 dias' in problema.detalhe, problema
print(f'   ok: {len(health.REGRAS_DO_STATUS)} regras nomeadas, ordem correta, motivo por campo')
"

echo "== [6/6] fonte bloqueada e PERSISTIDA como estado, nao so registrada em log =="
$UV run python -c "
import os, pathlib, subprocess, sys, tempfile

tmp = pathlib.Path(tempfile.mkdtemp()) / 'verify33.db'
env = dict(os.environ, DATABASE_URL=f'sqlite:///{tmp.as_posix()}')

def rodar(modulo, *args):
    return subprocess.run([sys.executable, '-m', modulo, *args], env=env,
                          capture_output=True, text=True, encoding='utf-8')

r = rodar('alembic', '-c', 'api/alembic.ini', 'upgrade', 'head')
assert r.returncode == 0, r.stdout + r.stderr
for passo in (('seed',),
              ('extract', 'Chevrolet', 'S10', 'High Country', '--replay', '--persistir')):
    r = rodar('pipeline.cli', *passo)
    assert r.returncode == 0, r.stdout + r.stderr

# A sala de imprensa da GM esta atras de CAPTCHA e o conector NUNCA a requisita: ela
# entra na lista de bloqueadas sem pedido nenhum (scraping educado, ADR-7). O que este
# passo prova e que aquele fato chega ao banco.
from sqlmodel import Session, create_engine, select

from api.app.models import Alert, Source, SourceStatus

engine = create_engine(f'sqlite:///{tmp.as_posix()}')
with Session(engine) as s:
    fontes = s.exec(select(Source).where(Source.status == SourceStatus.BLOQUEADA.value)).all()
    assert fontes, 'nenhuma fonte bloqueada persistida'
    assert any('media.gm.com' in f.dominio for f in fontes), [f.dominio for f in fontes]
    assert all(f.motivo for f in fontes), 'fonte bloqueada sem motivo'

    alertas = s.exec(select(Alert).where(Alert.type == 'fonte_bloqueada')).all()
    assert alertas, 'nenhum alerta fonte_bloqueada'
    assert all(a.version_id for a in alertas), 'alerta de fonte bloqueada sem versao'

    # E a saude da versao conta a fonte bloqueada, com a URL nomeada.
    from api.app.services import knowledge_health

    saude = knowledge_health.saude_da_versao(s, alertas[0].version_id)
    assert saude.fontes_bloqueadas.valor >= 1, saude.fontes_bloqueadas
    nomeadas = [c.campo for c in saude.fontes_bloqueadas.campos]
    assert any('media.gm.com' in n for n in nomeadas), nomeadas
    # E o detalhe NAO sugere contornar o bloqueio.
    for campo in saude.fontes_bloqueadas.campos:
        texto = campo.detalhe.lower()
        for proibido in ('proxy', 'user-agent', 'burlar'):
            assert proibido not in texto, texto
print('   ok: fonte bloqueada em sources + alerta por versao + contada na saude')
"

echo "WP-33 OK"
