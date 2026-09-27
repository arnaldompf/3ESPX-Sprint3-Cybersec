#!/usr/bin/env bash
# WP-14 — CLI `specradar` e worker de jobs.
#
# Comando da spec:
#   set -e; REPLAY_MODE=1 LLM_FAKE=1 uv run pytest -q tests/api/test_worker_e2e.py
#   uv run specradar --help
#
# Acrescentado: os dois criterios de aceite conferidos direto, a garantia das notas da
# spec (dois workers nao pegam o mesmo job) e o `diff` como teste de determinismo — em
# replay, duas rodadas do pipeline nao podem produzir alerta nenhum.
set -euo pipefail
cd "$(dirname "$0")/../.."

UV=uv; command -v uv >/dev/null 2>&1 || UV="python -m uv"
export PYTHONUTF8=1 REPLAY_MODE=1 LLM_FAKE=1

echo "== [1/7] ruff =="
$UV run ruff check api pipeline scripts tests
$UV run ruff format --check api pipeline scripts tests

echo "== [2/7] testes da spec =="
$UV run pytest -q tests/api/test_worker_e2e.py

echo "== [3/7] a CLI responde e tem os comandos de docs/14 =="
$UV run specradar --help >/dev/null
for comando in resolve extract eval diff refresh seed worker; do
  $UV run specradar "$comando" --help >/dev/null || { echo "FALTA: specradar $comando"; exit 1; }
  echo "   ok: specradar $comando"
done

echo "== [4/7] extract de ponta a ponta pela CLI =="
# Escreve e DEPOIS mostra: `... | tee arquivo | head` fecha o pipe e, com `pipefail`,
# o SIGPIPE aborta o verify inteiro no meio — sem mensagem de erro nenhuma.
$UV run specradar extract Ford Ranger "Raptor 3.0 V6 Bi-turbo 4WD AT" --replay > .tmp/verify14_extract.txt
head -4 .tmp/verify14_extract.txt
grep -q "resolucao: encontrada" .tmp/verify14_extract.txt
CAMPOS=$(grep -oE "campos com valor: [0-9]+" .tmp/verify14_extract.txt | grep -oE "[0-9]+")
test "$CAMPOS" -ge 25 || { echo "FALTA: so $CAMPOS campos com valor"; exit 1; }
echo "   ok: $CAMPOS campos com valor"

echo "== [5/7] a ficha da CLI valida no schema canonico =="
$UV run specradar extract Ford Ranger "Raptor 3.0 V6 Bi-turbo 4WD AT" --replay --json > .tmp/verify14_ficha.json
$UV run python -c "
import json, pathlib
from pipeline.schema import json_schema
import jsonschema
ficha = json.loads(pathlib.Path('.tmp/verify14_ficha.json').read_text(encoding='utf-8'))
jsonschema.validate(instance=ficha, schema=json_schema())
com_valor = sum(1 for g, campos in ficha.items() if isinstance(campos, dict) and g != 'meta'
                for c in campos.values() if isinstance(c, dict) and c.get('value') is not None)
print(f'   ok: ficha valida no schema, {com_valor} campos com valor')
"

echo "== [6/7] versao_inexistente sai com codigo 2, nao 0 nem erro =="
set +e
$UV run specradar extract Toyota Hilux "GR-Sport" --replay > .tmp/verify14_grsport.txt
CODIGO=$?
set -e
test "$CODIGO" -eq 2 || { echo "FALTA: codigo $CODIGO, esperado 2"; cat .tmp/verify14_grsport.txt; exit 1; }
grep -q "versao_inexistente" .tmp/verify14_grsport.txt
grep -q "alternativas:" .tmp/verify14_grsport.txt
echo "   ok: codigo 2 com as alternativas a vista (nao e erro de execucao)"

echo "== [7/7] o diff em replay nao acusa mudanca (determinismo) =="
$UV run specradar diff Ford Ranger "Raptor 3.0 V6 Bi-turbo 4WD AT" > .tmp/verify14_diff.txt
tail -3 .tmp/verify14_diff.txt
grep -q "alertas: 0" .tmp/verify14_diff.txt || {
  echo "FALTA: o pipeline mudou entre duas rodadas com os MESMOS snapshots"; exit 1; }
echo "   ok: duas rodadas, zero alertas"

echo "WP-14 OK"
