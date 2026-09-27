"""Portão do eval: falha se qualquer meta de `docs/09` não for atingida.

Existe para que "o eval está verde" seja uma afirmação verificável e não uma impressão.
Lê `reports/eval.json`, compara cada métrica com a meta e sai com código != 0 na primeira
que não fecha — com o denominador à vista, porque uma métrica sem denominador não diz
nada (`docs/09`).

Também imprime a **procedência da acurácia**: quantos campos certos vieram do fast-path
(regex sobre a fonte) e quantos dependeram de uma fixture de LLM. As fixtures desta
execução foram derivadas de `gabarito_v1.json` por falta de `ANTHROPIC_API_KEY` (D-07),
então crédito de acurácia vindo delas **não é evidência independente** da qualidade da
extração. O número não fica menos verdadeiro por isso; fica menos suficiente — e quem lê
o relatório tem de poder ver a diferença sem ir procurar.

Uso:  python scripts/check_eval_gates.py [reports/eval.json] [--sem-portao]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: As metas de `docs/09`, com o comparador de cada uma.
METAS: dict[str, tuple[str, float]] = {
    "field_accuracy": (">=", 0.90),
    "status_fidelity": (">=", 0.90),
    "hallucination_rate": ("==", 0.0),
    "grounding_rate": ("==", 1.0),
    "coverage": ("==", 1.0),
    "resolver_accuracy": ("==", 1.0),
    "slide_divergences_found": ("==", 1.0),
}
#: Métricas que são **invioláveis**: são regra do produto, não alvo de qualidade. Elas
#: falham o portão mesmo em modo permissivo, porque um valor sem evidência ou uma
#: alucinação não é "meta não atingida", é o produto fazendo o que prometeu não fazer.
INVIOLAVEIS = ("hallucination_rate", "grounding_rate")


def _atinge(valor: float | None, comparador: str, meta: float) -> bool | None:
    if valor is None:
        return None
    return valor >= meta - 1e-9 if comparador == ">=" else abs(valor - meta) < 1e-9


def _fmt(valor: float | None) -> str:
    return "—" if valor is None else f"{valor:.3f}".replace(".", ",")


def campos_com_fixture_derivada() -> set[str]:
    """Campos para os quais existe fixture de LLM **derivada do gabarito**.

    Lê o `meta.origem` de cada fixture em `tests/fixtures/llm/`. As gravadas de uma
    chamada real à API dizem "chamada ao vivo"; as derivadas dizem que vieram de
    `gabarito_v1.json`, e são só essas que entram aqui.
    """
    campos: set[str] = set()
    pasta = ROOT / "tests" / "fixtures" / "llm"
    if not pasta.exists():
        return campos
    for arquivo in pasta.glob("*.json"):
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except ValueError:
            continue
        meta = dados.get("meta") or {}
        if "gabarito" not in str(meta.get("origem", "")).lower():
            continue
        campos.update(meta.get("campos_respondidos") or [])
    return campos


def procedencia_da_acuracia(dados: dict) -> tuple[int, int, list[str]]:
    """`(acertos, acertos_que_podem_depender_de_fixture, nomes)`.

    É um **limite superior**, e o rótulo importa: o relatório do eval não registra por
    qual caminho cada valor foi extraído, então o que se pode afirmar com honestidade é
    quais campos certos *têm* uma fixture derivada do gabarito capaz de responder por
    eles. Um campo que o fast-path também resolve aparece aqui sem depender da fixture —
    daí ser teto, não medida.

    Medir isso por baixo exigiria carregar a origem da extração até a ficha, o que é
    mudança no schema canônico; o teto já responde à pergunta que importa ("quanto deste
    número pode não ser independente?") sem fingir precisão que não há.
    """
    suspeitos = campos_com_fixture_derivada()
    acertos = 0
    dependentes: list[str] = []
    for veiculo in dados.get("vehicles", []):
        for campo in veiculo.get("campos", []):
            if not campo.get("valor_ok"):
                continue
            acertos += 1
            nome = str(campo.get("caminho", "")).split(".", 1)[-1]
            if nome in suspeitos:
                dependentes.append(f"{veiculo.get('id', '?')}/{nome}")
    return acertos, len(dependentes), dependentes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("relatorio", nargs="?", default=str(ROOT / "reports" / "eval.json"))
    p.add_argument(
        "--sem-portao",
        action="store_true",
        help="reporta sem falhar, exceto nas metricas inviolaveis",
    )
    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    caminho = Path(args.relatorio)
    if not caminho.exists():
        print(f"ERRO: {caminho} nao existe. Rode `python scripts/task.py eval` primeiro.")
        return 2
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    agregado = dados.get("aggregate") or dados.get("agregado") or {}

    faltando: list[str] = []
    gab = dados.get("gabarito")
    versao_gab = gab.get("versao", "?") if isinstance(gab, dict) else (gab or "?")
    print(f"portao do eval — {caminho.name} (gabarito {versao_gab})")
    for nome, (comparador, meta) in METAS.items():
        metrica = agregado.get(nome) or {}
        valor = metrica.get("valor") if isinstance(metrica, dict) else metrica
        acertos = metrica.get("acertos") if isinstance(metrica, dict) else None
        n = metrica.get("n") if isinstance(metrica, dict) else None
        atingiu = _atinge(valor, comparador, meta)
        marca = {True: "OK  ", False: "FALTA", None: "—   "}[atingiu]
        denominador = f"({acertos}/{n})" if n is not None else ""
        alvo = f"{comparador} {meta:.2f}".replace(".", ",")
        print(f"  {marca} {nome:26} {_fmt(valor):>7}  {denominador:>10}  meta {alvo}")
        if atingiu is False:
            faltando.append(nome)

    acertos, teto, dependentes = procedencia_da_acuracia(dados)
    if acertos:
        print()
        print("procedencia dos acertos (o numero e verdadeiro; leia o que o sustenta):")
        print(f"  acertos medidos                                    {acertos}")
        print(f"  TETO de acertos com fixture de LLM disponivel      {teto}")
        if teto:
            print(
                "  Sem ANTHROPIC_API_KEY, as fixtures de LLM foram derivadas de\n"
                "  gabarito_v1.json (D-07). Para estes campos o acerto pode NAO ser\n"
                "  evidencia independente da extracao. E teto, nao medida: campo que o\n"
                "  fast-path tambem resolve aparece na lista sem depender da fixture."
            )
            print(f"  campos: {', '.join(sorted({d.split('/')[-1] for d in dependentes}))}")

    inviolaveis_falhando = [m for m in faltando if m in INVIOLAVEIS]
    if inviolaveis_falhando:
        print()
        print(f"REPROVADO (regra inviolavel): {', '.join(inviolaveis_falhando)}")
        return 1
    if faltando and not args.sem_portao:
        print()
        print(f"REPROVADO: {', '.join(faltando)} abaixo da meta de docs/09")
        return 1
    if faltando:
        print()
        print(f"metas nao atingidas (portao desligado): {', '.join(faltando)}")
        return 0
    print()
    print("todas as metas de docs/09 atingidas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
