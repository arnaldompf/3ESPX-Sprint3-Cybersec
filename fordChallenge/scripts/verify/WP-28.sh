#!/usr/bin/env bash
# WP-28 — RBAC por matriz, relatorio para o cliente e compartilhamento.
#
# Comando da spec:
#   set -e; uv run pytest -q tests/api/test_rbac_matrix.py tests/api/test_pdf.py; \
#       cd mobile && npx tsc --noEmit && npx eslint . && npx jest --ci -t showroom
#
# `mobile/` virou `web/`, como o maestro manda ("o Modo Showroom para tablet NAO existe
# mais; o Copiloto e a pagina web responsiva"). Os passos [4] a [6] sao acrescimo:
#
#   [4] o documento do cliente nao vaza mecanica interna — conferido no HTML FINAL, que e
#       a unica checagem que pega o termo entrando por um valor de dado;
#   [5] o renderizador declara formato e motivo. Nesta maquina o WeasyPrint nao tem as
#       bibliotecas nativas, e um PDF de zero byte com status "concluido" seria pior que a
#       ausencia: alguem abriria o link na frente do cliente;
#   [6] o arquivo e servido por rota autenticada e o nome e validado contra travessia.
set -euo pipefail
cd "$(dirname "$0")/../.."
RAIZ=$(pwd)

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1
export REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/6] a matriz de permissoes, rota por rota =="
$UV run pytest -q tests/api/test_rbac_matrix.py

echo "== [2/6] o relatorio: job, conteudo e download =="
$UV run pytest -q tests/api/test_pdf.py

echo "== [3/6] as telas =="
cd "$RAIZ/web"
npx tsc --noEmit
npx eslint .
npx vitest run -t showroom
cd "$RAIZ"

echo "== [4/6] o documento do cliente nao vaza mecanica interna =="
$UV run python -c "
from pipeline.report import html

# Um relatorio completo, com tudo o que o gerador sabe produzir.
r = html.Relatorio(
    rotulo_ford='Ford Ranger Raptor',
    rotulo_concorrente='Toyota Hilux SRX Plus',
    gerado_em='2026-09-09T12:00:00',
    aderencia_ford='3,8 de 10',
    aderencia_concorrente='7,8 de 10',
    rotulo_da_aderencia='Aderência ao perfil informado — não é um ranking de qualidade',
    linhas=[
        html.LinhaDeComparacao('potencia_cv', 'Potência', '397 cv', '204 cv', quem_leva='ford'),
        html.LinhaDeComparacao(
            'capacidade_carga_kg', 'Capacidade de carga', '620 kg', '1.005 kg',
            quem_leva='concorrente',
        ),
    ],
    pontos=['Para quem prioriza desempenho: 397 cv contra 204 cv (site oficial, 01/09/2026).'],
    ponto_do_concorrente='Onde a Hilux leva vantagem: 1.005 kg contra 620 kg.',
    custo_ford='R\$ 1.875,00 por mês',
    custo_concorrente='R\$ 1.534,65 por mês',
    diferenca_anual='Diferença estimada de R\$ 4.084,20 por ano.',
    fontes=[
        html.Fonte('https://www.ford.com.br/ranger-raptor', '2026-09-01', ['potencia_cv']),
        html.Fonte('https://www.toyota.com.br/hilux', '2026-09-02', ['capacidade_carga_kg']),
    ],
    aviso_de_comparabilidade='Par nao comparavel: combustivel diferente.',
)
doc = html.montar(r)

# Criterio de aceite: nenhum texto contem 'confianca', 'tier' ou 'LLM'.
vazados = html.termos_internos_no_texto(doc)
assert vazados == [], vazados

# Criterio de aceite: a secao do concorrente e a lista de fontes com datas.
assert 'Onde a Toyota Hilux SRX Plus leva vantagem' in doc
assert 'Fontes consultadas' in doc
assert '01/09/2026' in doc and '02/09/2026' in doc

# O rodape de ressalvas, e o aviso de comparabilidade ANTES da tabela.
assert 'não é proposta comercial' in doc
assert doc.index('nao comparavel') < doc.index('Ficha comparada')

# Nada de PII: o gerador nao tem campo para isso.
campos = set(html.Relatorio.__dataclass_fields__)
for proibido in ('nome', 'telefone', 'email', 'cpf', 'cliente', 'contato'):
    assert not any(proibido in c for c in campos), campos

# E o HTML escapa o que vem de pagina de terceiro.
perigoso = html.montar(html.Relatorio(rotulo_ford='<script>x</script>', rotulo_concorrente='y'))
assert '<script>x</script>' not in perigoso
print(f'   ok: {len(doc)} bytes, sem termo interno, com secao do concorrente e fontes datadas')
"

echo "== [5/6] o renderizador declara a ordem dos motores, o formato e o motivo =="
$UV run python -c "
import tempfile, pathlib

from pipeline.report import html, render

disponivel, motivo = render.weasyprint_disponivel()

# A ordem e declarada (WeasyPrint, xhtml2pdf, e o HTML por ultimo) e nenhum 'nao da'
# aparece sem o motivo escrito ao lado.
print('   motores, em ordem de preferencia:')
for m in render.motores_de_pdf():
    assert m.disponivel or m.motivo, m
    print(f'     - {m.nome}: ' + (f'ok {m.versao}' if m.disponivel else m.motivo[:90]))

doc = html.montar(html.Relatorio(rotulo_ford='Ford', rotulo_concorrente='Concorrente'))
res = render.renderizar(doc, 'verify28', diretorio=pathlib.Path(tempfile.mkdtemp()))

assert res.formato in {'pdf', 'html'}, res.formato
assert res.bytes_gerados > 200, res.bytes_gerados
assert res.caminho.exists()
# Quem gerou fica registrado: proveniencia de arquivo nao e adivinhacao.
assert res.motor in (*render.MOTORES, 'html'), res.motor
assert res.renderizador.startswith(res.motor), (res.motor, res.renderizador)

if res.formato == 'pdf':
    assert res.caminho.read_bytes()[:5] == b'%PDF-', 'arquivo .pdf que nao comeca com %PDF-'
    print(f'   ok: PDF gerado por {res.renderizador} ({res.bytes_gerados} bytes)')
    if res.motor != render.MOTORES[0]:
        # Motor de reserva: o resultado diz que e reserva, e por que.
        assert 'reserva' in res.motivo, res.motivo
        assert 'WeasyPrint' in res.motivo, res.motivo
        print(f'   ok: motor de reserva declarado — {res.motivo[:100]}')
else:
    # Fallback: o motivo tem de dizer o QUE falta e COMO habilitar.
    assert 'WeasyPrint' in res.motivo, res.motivo
    assert 'GTK' in res.motivo, res.motivo
    assert res.caminho.suffix == '.html'
    print(f'   ok: fallback HTML declarado ({res.bytes_gerados} bytes); {motivo[:60]}')
"

echo "== [6/6] o arquivo e servido autenticado, e o nome e validado =="
$UV run python -c "
from api.app.routers.reports import NOME_DE_ARQUIVO

# Aceita o que o gerador produz.
for bom in ('relatorio-abc123.pdf', 'relatorio-abc123.html'):
    assert NOME_DE_ARQUIVO.match(bom), bom

# Recusa travessia e extensao errada. A rota le caminho vindo da URL, e '../../.env' e o
# primeiro teste que alguem faz.
for ruim in ('../../.env', '../.env', 'x/../y.pdf', 'relatorio.txt', 'relatorio', 'a.pdf.exe'):
    assert not NOME_DE_ARQUIVO.match(ruim), ruim

# A rota do arquivo exige permissao: o link vive no WhatsApp de quem recebeu.
import inspect

from api.app.routers import reports

fonte = inspect.getsource(reports)
assert 'dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))]' in fonte
assert 'is_relative_to' in fonte, 'faltou a segunda linha de defesa do caminho'
print('   ok: nome validado, travessia barrada, rota autenticada')
"

echo "WP-28 OK"
