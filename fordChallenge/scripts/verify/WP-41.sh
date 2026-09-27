#!/usr/bin/env bash
# WP-41 — o Pesquisador: completar a ficha de um veículo que não está no catálogo.
#
# O que este portão responde, em ordem:
#   1. as peças determinísticas fazem o que dizem (planejador, classificador, busca);
#   2. **a regra é arquitetura, e não pedido**: com o LLM quebrado, nada é inventado;
#   3. o snippet do buscador nunca vira evidência;
#   4. o orçamento para, e **diz qual limite** o parou;
#   5. a pesquisa roda ponta a ponta em replay, sem tocar a rede.
set -e
cd "$(dirname "$0")/../.."
export PYTHONUTF8=1 REPLAY_MODE=1 LLM_FAKE=1 SEARCH_PROVIDER=replay

UV="uv run"
command -v uv >/dev/null 2>&1 || UV=".venv/Scripts/python.exe -m"
[ -x ".venv/Scripts/python.exe" ] && UV=".venv/Scripts/python.exe -m"

echo "== [1/5] as pecas: planejador, classificador, busca, lacunas =="
$UV pytest -q \
  tests/pipeline/test_research_planner.py \
  tests/pipeline/test_research_classify.py \
  tests/pipeline/test_research_search.py \
  tests/pipeline/test_research_gaps.py

echo "== [2/5] a garantia: com o LLM quebrado, nada e inventado =="
$UV pytest -q tests/pipeline/test_research_run.py -k "LLM_quebrado or snippet"

echo "== [3/5] o orcamento para, e diz qual limite =="
$UV pytest -q tests/pipeline/test_research_run.py -k "Orcamento or trilha or Trilha"

echo "== [4/5] a API: 202, a trilha e o SSE =="
$UV pytest -q tests/api/test_research_api.py

echo "== [5/5] ponta a ponta pela CLI, em replay =="
mkdir -p .tmp
.venv/Scripts/python.exe -m pipeline.cli research Ford Ranger "Raptor 3.0 V6 Bi-turbo 4WD AT" --json > .tmp/wp41.json
.venv/Scripts/python.exe - <<'PY'
import json, pathlib
d = json.loads(pathlib.Path(".tmp/wp41.json").read_text(encoding="utf-8"))
cobertura = d["cobertura"]
eventos = d["eventos"]

assert cobertura["com_valor"] >= 20, f"cobertura baixa demais: {cobertura}"
assert d["motivo_da_parada"], "o run tem de dizer POR QUE parou"
assert d["explicacao"], "e a explicacao tem de estar em portugues de quem le"

# A trilha tem de mostrar a consulta VERBATIM, e nao uma parafrase.
consultas = [e for e in eventos if e["tipo"] == "consulta"]
assert consultas, "nenhuma consulta na trilha"
assert any("ficha" in e["texto"] for e in consultas)

# Toda etiqueta, como manda docs/13 secao 2.
for e in eventos:
    assert e["etiqueta"] in {"FATO", "INFERENCIA", "SIMULACAO"}, e

# Nenhuma pagina baixada sem tier aceitavel.
for f in d["fontes"]:
    assert f["tier"] <= 3, f

print(f"   ok: {cobertura['com_valor']}/{cobertura['total']} campos, "
      f"{len(d['fontes'])} fonte(s), {len(eventos)} evento(s), parou por {d['motivo_da_parada']}")
PY

echo ""
echo "WP-41: VERDE"
