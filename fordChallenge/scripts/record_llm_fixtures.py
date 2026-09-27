#!/usr/bin/env python
"""Grava as fixtures de `LLM_FAKE=1` em `tests/fixtures/llm/`.

Dois modos, e o segundo é o que roda quando não há chave:

* **`--live`** — precisa de `ANTHROPIC_API_KEY`. Faz as chamadas de verdade e grava a
  resposta. É o modo que `specs/WP-10.md` prevê ("gere as fixtures uma vez ao vivo e faça
  commit; o CI nunca chama a API").
* **`--from-gabarito`** (default sem chave) — monta a resposta a partir da **verdade-terra
  humana**: valor de `gabarito_v1.json` e `evidence_quote` do `trecho` que o próprio
  gabarito registra. É o caminho que a noite de 08/09 usou, porque não havia chave nesta
  máquina (DECISOES_NOITE.md D-07).

Duas salvaguardas no modo `--from-gabarito`, e as duas importam:

1. **Só entra campo cujo `trecho` realmente ocorre no texto salvo.** Trecho que não
   grounda geraria uma fixture que o WP-11 descartaria depois — fixture que finge ter
   resposta é pior que fixture ausente.
2. **Só entra campo que o fast-path não resolve.** O que o regex resolve não vai ao LLM
   (`docs/12` §6.8), então gravar fixture para ele seria gravar resposta para uma pergunta
   que nunca é feita.

A fixture registra `origem` no `meta`: quem ler o arquivo sabe se aquela resposta veio do
modelo ou da verdade-terra.

Uso:
    python scripts/record_llm_fixtures.py              # deriva do gabarito
    python scripts/record_llm_fixtures.py --live       # chama a API (precisa de chave)
    python scripts/record_llm_fixtures.py --listar     # só mostra o que faria
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import llm  # noqa: E402
from pipeline.eval.compare import grounding  # noqa: E402
from pipeline.eval.gabarito import carregar_gabarito  # noqa: E402
from pipeline.extract.run import Documento, planejar_chamadas  # noqa: E402
from pipeline.run import CAMPOS_DE_SERVICO, campos_canonicos, documentos_de  # noqa: E402
from pipeline.store import FIXTURES  # noqa: E402


def campos_do_pipeline() -> list[str]:
    """Os campos que `pipeline.run` pede, na forma curta que a extracao usa."""
    curtos = [c.split(".", 1)[-1] for c in campos_canonicos()]
    return [c for c in curtos if c not in CAMPOS_DE_SERVICO]


def documentos_do_veiculo(version_id: str, versao: str) -> list[Documento]:
    """Monta os documentos **pela mesma funcao que o pipeline usa**.

    Antes esta funcao montava por conta propria, sem as celulas recortadas por versao. O
    resultado: o prompt do gravador e o prompt do pipeline eram diferentes, a chave
    sha256 da fixture era diferente, e a resposta gravada nunca era encontrada no replay.
    Deriva silenciosa entre o que se grava e o que se replaya — o replay parecia
    funcionar, so nao respondia nada.
    """
    documentos, _, _ = documentos_de(version_id, versao, raiz=FIXTURES)
    return documentos


def resposta_do_gabarito(veiculo, campos: tuple[str, ...], texto: str) -> dict:
    """Monta a resposta a partir do gabarito, só com o que grounda no texto salvo."""
    dados: dict[str, dict] = {}
    for campo in veiculo.campos:
        if campo.campo not in campos or campo.valor is None or not campo.trecho:
            continue
        if not grounding(campo.trecho, texto).ok:
            continue
        dados[campo.campo] = {
            "raw_value": campo.valor_bruto or str(campo.valor),
            "value": campo.valor,
            "unit": None,
            "evidence_quote": campo.trecho,
        }
    return dados


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--live", action="store_true", help="chama a API de verdade")
    p.add_argument("--listar", action="store_true", help="mostra o plano e sai")
    p.add_argument("--veiculo", default=None, help="restringe a um id do gabarito")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    if args.live and not llm.tem_chave():
        print("ANTHROPIC_API_KEY ausente: --live impossivel. Rode sem --live.")
        return 1

    gab = carregar_gabarito()
    veiculos = [gab.por_id(args.veiculo)] if args.veiculo else list(gab.veiculos_com_atributos)

    total_planos = gravadas = vazias = 0
    for veiculo in veiculos:
        # O alvo e o do PIPELINE (a ficha inteira, menos os campos de servico), nao o do
        # gabarito: o conjunto de campos entra no prompt, e portanto na chave da fixture.
        # Gravar com o conjunto do gabarito produzia chaves que o pipeline nunca consulta.
        alvo = set(campos_do_pipeline())
        if not alvo:
            continue
        for documento in documentos_do_veiculo(veiculo.id, veiculo.versao):
            planos = planejar_chamadas(
                documento,
                alvo,
                marca=veiculo.marca,
                modelo_veiculo=veiculo.modelo,
                versao=veiculo.versao,
            )
            for plano in planos:
                total_planos += 1
                if args.listar:
                    print(
                        f"{veiculo.id[:26]:28} {plano.source_id[:24]:26} "
                        f"{plano.modelo[:22]:24} {len(plano.campos):2} campos  {plano.chave}"
                    )
                    continue

                if args.live:  # pragma: no cover - exige chave
                    resposta = llm.extrair_json(
                        prompt=plano.prompt, campos=list(plano.campos), modelo=plano.modelo
                    )
                    dados = resposta.dados
                    origem = f"chamada ao vivo em {plano.modelo}"
                else:
                    dados = resposta_do_gabarito(veiculo, plano.campos, documento.texto)
                    origem = (
                        "derivada de gabarito_v1.json (valor e trecho verbatim da "
                        "verdade-terra humana), porque nao havia ANTHROPIC_API_KEY"
                    )

                if not dados:
                    vazias += 1
                    continue
                llm.gravar_fixture(
                    plano.chave,
                    dados,
                    meta={
                        "origem": origem,
                        "version_id": veiculo.id,
                        "source_id": plano.source_id,
                        "modelo": plano.modelo,
                        "campos_pedidos": list(plano.campos),
                        "campos_respondidos": sorted(dados),
                        "gerado_por": "scripts/record_llm_fixtures.py",
                    },
                )
                gravadas += 1

    if args.listar:
        print(f"\n{total_planos} chamada(s) planejada(s)")
        return 0
    print(f"{gravadas} fixture(s) gravada(s) de {total_planos} chamada(s) planejada(s)")
    if vazias:
        print(
            f"{vazias} chamada(s) sem resposta a gravar: o gabarito nao tem valor com "
            "trecho groundavel para nenhum dos campos pedidos. Ausencia de fixture faz o "
            "pipeline devolver nao_encontrado, que e a resposta honesta."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
