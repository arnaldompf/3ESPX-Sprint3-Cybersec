#!/usr/bin/env bash
# WP-44 — Coletar onde tem ficha: fontes mapeadas, bloqueio que não gasta vaga, escalada.
#
# O que este portão responde, em ordem:
#   1. os domínios que a pesquisa conhece saem de `fontes.yaml`, validado, com data — e o
#      mais específico ganha (motor1.uol.com.br reprovado vence uol.com.br aprovado);
#   2. a busca vai restrita a esses domínios, e a restrição entra na chave do cache;
#   3. a coleta: a vaga é de quem abre a porta, 403 escala para navegador e (tier 1) para
#      o arquivo, nada escala em replay, e captura velha demais não serve;
#   4. o que a pesquisa NÃO deve ler: manual do proprietário em qualquer grafia, página
#      que compara vários carros, listagem de busca, e página de outra geração;
#   5. a gravação completa a ficha em vez de substituí-la, e a versão nova vira alerta.
set -e
cd "$(dirname "$0")/../.."
export PYTHONUTF8=1 REPLAY_MODE=1 LLM_FAKE=1 SEARCH_PROVIDER=replay

UV="uv run"
command -v uv >/dev/null 2>&1 || UV=".venv/Scripts/python.exe -m"
[ -x ".venv/Scripts/python.exe" ] && UV=".venv/Scripts/python.exe -m"

echo "== [1/5] os dominios saem do YAML, nao do codigo =="
$UV pytest -q tests/pipeline/test_research_fontes.py

echo "== [2/5] a busca restrita e o cache por dominio =="
$UV pytest -q tests/pipeline/test_research_search.py tests/pipeline/test_research_planner.py

echo "== [3/5] a coleta: a vaga, a escalada e os freios dela =="
$UV pytest -q tests/pipeline/test_research_modelo.py

echo "== [4/5] o que a pesquisa nao deve ler =="
$UV pytest -q tests/pipeline/test_research_classify.py tests/pipeline/test_normalize.py

echo "== [5/5] completar e nao substituir; a versao nova vira alerta =="
$UV pytest -q tests/pipeline/test_research_persistir.py tests/pipeline/test_research_run.py

echo ""
echo "WP-44: VERDE"
echo "A medicao ao vivo do criterio 8 nao roda aqui (gasta busca e modelo)."
echo "Os numeros medidos em 14/09/2026 estao em specs/WP-44.md e no diario."
