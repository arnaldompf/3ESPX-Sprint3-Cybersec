"""Exporta o OpenAPI para `reports/openapi.json`.

Serve a duas coisas de uma vez: entregar o contrato num arquivo (a disciplina cobra o
OpenAPI como artefato) e **conferir** que ele fecha. As checagens abaixo pegam as duas
falhas silenciosas mais comuns num contrato gerado:

* **rota sem `operationId` único** — gerador de cliente cria função com nome repetido e
  sobrescreve uma das duas, e ninguem descobre até a chamada errada ir para producao;
* **rota do `docs/04` ausente** — o contrato "esta pronto" com um endpoint faltando.

Uso:  python scripts/export_openapi.py [--check]
      --check nao escreve; so confere.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DESTINO = ROOT / "reports" / "openapi.json"

#: As rotas que `docs/04` promete, menos as de WP futura. `/publications` e da WP-22.
ESPERADAS = (
    "/api/v1/health",
    "/api/v1/auth/me",
    "/api/v1/brands",
    "/api/v1/brands/{brand_id}/models",
    "/api/v1/models/{model_id}/versions",
    "/api/v1/resolutions",
    "/api/v1/attributes",
    "/api/v1/attributes/resolve",
    "/api/v1/vehicles",
    "/api/v1/vehicles/{version_id}",
    "/api/v1/vehicles/{version_id}/specs",
    "/api/v1/extractions",
    "/api/v1/extractions/from-image",
    "/api/v1/jobs/{job_id}",
    "/api/v1/evidences/{evidence_id}",
    "/api/v1/snapshots/{snapshot_id}",
    "/api/v1/comparisons",
    "/api/v1/alerts",
    "/api/v1/alerts/{alert_id}",
    "/api/v1/sources",
    "/api/v1/sources/{source_id}",
    "/api/v1/users",
    "/api/v1/users/{user_id}",
)
#: Prometida em `docs/04` e fora do escopo desta onda — declarada para nao parecer esquecida.
#:
#: `/auth/login` e `/auth/refresh` entraram aqui em 12/09/2026 (D-204): elas existem, com
#: os testes delas, mas so sao montadas com `AUTH_ENABLED=1`. O contrato padrao nao as
#: promete porque o servidor padrao nao as tem — anunciar rota que responde 404 e pior do
#: que nao anunciar.
PENDENTES = {
    "/api/v1/publications": "WP-22",
    "/api/v1/auth/login": "so com AUTH_ENABLED=1 (D-204)",
    "/api/v1/auth/refresh": "so com AUTH_ENABLED=1 (D-204)",
}


#: As bandeiras que o contrato fixa, e o valor de cada uma.
#:
#: **Todas desligadas, porque o servidor padrao as tem desligadas.** O contrato descreve o
#: que um clone recem-feito responde — nao o que a maquina de quem exportou tem no `.env`.
#: Anunciar rota que responde 404 e pior do que nao anunciar.
#:
#: `RESEARCH_ENABLED` entrou aqui em 13/09/2026, e entrou por um defeito: o `.env` desta
#: maquina passou a traze-la ligada, o app sob teste montou `/research`, e
#: `test_o_arquivo_exportado_bate_com_o_app` falhou com um diff que nao era de ninguem —
#: exatamente o sintoma que a docstring abaixo ja descrevia para `AUTH_ENABLED`. A licao e
#: que fixar **uma** bandeira nao resolve: o que precisa ser fixo e o conjunto.
BANDEIRAS_DO_CONTRATO = {
    "AUTH_ENABLED": "0",
    "RESEARCH_ENABLED": "0",
    "BENCHMARK_ENABLED": "0",
}


def gerar() -> dict:
    """Monta o app e pede o esquema. Precisa de um `JWT_SECRET` valido para importar.

    **As bandeiras de `BANDEIRAS_DO_CONTRATO` saem desligadas aqui, sempre**, que e o
    padrao do produto nesta fase (D-204). O contrato exportado tem de ser o mesmo em
    qualquer maquina: com uma delas ligada no `.env` de quem exporta, o
    `reports/openapi.json` versionado anunciaria rotas que um servidor com a configuracao
    padrao nao tem — e o proximo a rodar o verify veria um diff que nao e dele.
    """
    os.environ.setdefault("JWT_SECRET", "exportacao-de-openapi-com-32-bytes-ou-mais-de-folga")
    from api.app.config import get_settings
    from api.app.main import create_app

    antes = {nome: os.environ.get(nome) for nome in BANDEIRAS_DO_CONTRATO}
    os.environ.update(BANDEIRAS_DO_CONTRATO)
    get_settings.cache_clear()
    try:
        return create_app().openapi()
    finally:
        # O ambiente volta ao que estava: quem chamou nao pediu para mudar a
        # configuracao do processo, e um teste que rode depois deste veria a variavel
        # alterada sem ninguem ter feito isso de proposito.
        for nome, valor in antes.items():
            if valor is None:
                os.environ.pop(nome, None)
            else:
                os.environ[nome] = valor
        get_settings.cache_clear()


def conferir(esquema: dict) -> list[str]:
    """Devolve a lista de problemas. Vazia significa contrato fechado."""
    problemas: list[str] = []
    caminhos = esquema.get("paths", {})

    faltando = [rota for rota in ESPERADAS if rota not in caminhos]
    if faltando:
        problemas.append(f"rotas de docs/04 ausentes: {', '.join(faltando)}")

    ids = [
        op.get("operationId", "")
        for metodos in caminhos.values()
        for chave, op in metodos.items()
        if chave in {"get", "post", "patch", "put", "delete"}
    ]
    repetidos = [oid for oid, n in Counter(ids).items() if n > 1 and oid]
    if repetidos:
        problemas.append(f"operationId repetido: {', '.join(repetidos)}")
    if any(not oid for oid in ids):
        problemas.append("ha operacao sem operationId")

    if "StandardSpec" not in esquema.get("components", {}).get("schemas", {}):
        problemas.append("StandardSpec nao aparece nos componentes: /specs perdeu o response_model")
    return problemas


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true", help="nao escreve; so confere")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    esquema = gerar()
    problemas = conferir(esquema)
    caminhos = esquema.get("paths", {})

    print(f"openapi {esquema.get('openapi')} — {len(caminhos)} rotas")
    for rota, wp in PENDENTES.items():
        if rota not in caminhos:
            print(f"  pendente por escopo: {rota} ({wp})")
    if problemas:
        print("PROBLEMAS:")
        for problema in problemas:
            print(f"  - {problema}")
        return 1

    if args.check:
        if not DESTINO.exists():
            print(f"AUSENTE: {DESTINO.relative_to(ROOT)} nao existe")
            return 1
        atual = json.loads(DESTINO.read_text(encoding="utf-8"))
        if atual != esquema:
            print(f"DIVERGENTE: {DESTINO.relative_to(ROOT)} nao bate com o app atual")
            return 1
        print(f"ok: {DESTINO.relative_to(ROOT)} confere")
        return 0

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(
        json.dumps(esquema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"escrito: {DESTINO.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
