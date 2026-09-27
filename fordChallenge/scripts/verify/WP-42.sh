#!/usr/bin/env bash
# WP-42 — Pesquisa: a conversa que identifica o carro, pesquisa com fontes e grava no catálogo.
#
# O que este portão responde, em ordem:
#   1. o modelo sob orçamento: teto de gasto recusa ANTES de chamar, a cota de chamadas
#      desliga o modelo (não a pesquisa), a Kimi vai sem raciocínio, quem espera avisa;
#   2. a trilha chega à tabela ENQUANTO a pesquisa acontece — e o `fim` só quando o run
#      já está concluído, no mesmo commit do `version_id`;
#   3. a ficha pesquisada entra no catálogo: `versions`, `spec_values`, `evidences`,
#      `snapshots`; re-pesquisa substitui; pesquisa vazia não grava ficha vazia;
#   4. a identificação pergunta quando há dúvida, e opção sem fonte não chega à tela;
#   5. a tela: reducer da conversa, trilha, cartão da ficha e a página inteira, dubladas.
set -e
cd "$(dirname "$0")/../.."
export PYTHONUTF8=1 REPLAY_MODE=1 LLM_FAKE=1 SEARCH_PROVIDER=replay

UV="uv run"
command -v uv >/dev/null 2>&1 || UV=".venv/Scripts/python.exe -m"
[ -x ".venv/Scripts/python.exe" ] && UV=".venv/Scripts/python.exe -m"

echo "== [1/5] o modelo sob orcamento =="
$UV pytest -q \
  tests/pipeline/test_llm_teto.py \
  tests/pipeline/test_extract_blocos.py \
  tests/pipeline/test_research_gaps.py \
  tests/pipeline/test_research_modelo.py

echo "== [2/5] a trilha ao vivo, sem duplicata =="
$UV pytest -q tests/api/test_worker_research_incremental.py

echo "== [3/5] a ficha pesquisada no catalogo =="
$UV pytest -q tests/pipeline/test_research_persistir.py tests/pipeline/test_persist_evidencia_snapshot.py

echo "== [4/5] a identificacao e a API =="
$UV pytest -q tests/pipeline/test_research_identificar.py tests/api/test_research_api.py tests/pipeline/test_research_run.py

echo "== [5/5] a tela Pesquisa =="
(cd web && npm run test -- --run conversa Pesquisa Trilha CartaoDaFicha Pesquisador)

echo ""
echo "WP-42: VERDE"
