#!/usr/bin/env python
"""Injeta no roteiro os números que o **último ensaio** mediu.

O problema que isto resolve é o risco nº 4 do `ONBOARDING.md`, e ele estava classificado
como **alta**: *"um número na tela é diferente do roteiro"*. A causa era estrutural — o
roteiro trazia números escritos à mão e o ensaio media outros, e ninguém garantia que os
dois andassem juntos. O caso confirmado: o roteiro dizia "10 ALTA" na cena 10 e o medido
era "4 ALTA, 1 MÉDIA, 2 RUÍDO".

A partir de 10/09/2026 o roteiro tem um **bloco gerado**, entre os marcadores

    <!-- ENSAIO:INICIO -->  …  <!-- ENSAIO:FIM -->

e é este script que o escreve, lendo `reports/ensaio.json` (gravado por
`scripts/demo/cenas.py` a cada rodada de `replay_demo.sh`). O texto de palco continua
sendo escrito por uma pessoa; o que sai da máquina são os **números**, e eles passam a
vir de uma fonte só.

Uso:

    bash scripts/demo/replay_demo.sh          # mede e grava reports/ensaio.json
    python scripts/demo/atualizar_roteiro.py  # injeta no roteiro
    python scripts/demo/atualizar_roteiro.py --check   # falha se estiver desatualizado
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
ENSAIO = RAIZ / "reports" / "ensaio.json"
ROTEIRO = RAIZ / "docs" / "demo" / "ROTEIRO_15SET.md"

INICIO = "<!-- ENSAIO:INICIO -->"
FIM = "<!-- ENSAIO:FIM -->"

#: Linhas do ensaio que valem para o palco: as que trazem número ou decisão. As demais
#: são explicação de mecanismo, que o roteiro já dá em prosa.
PREFIXOS_UTEIS = (
    "MEDIDO",
    "par:",
    "PAR DA SPEC",
    "aderência",
    "fila:",
    "topo da fila",
    "elo 5",
    "cadeia",
    "real:",
    "ACELERAÇÃO",
    "resolução:",
    "campo(s)",
    "divergência(s)",
    "documento do cliente",
    "argumentário",
    "hipótese:",
    "materialidade do cenário",
)


def _sem_id(url: str) -> str:
    """`/app/ficha/f43a02eb…` → `/app/ficha/{id}`.

    Os identificadores são **sorteados a cada montagem** da base. Gravá-los no roteiro
    daria à pessoa uma URL que funciona hoje e falha amanhã, com a ficha aparecendo vazia
    — que é o risco nº 3 do `ONBOARDING.md` ("você abriu um endereço de ficha antigo").
    O caminho certo é sempre chegar à ficha pela tela de Consulta.
    """
    if not url:
        return "slide"
    partes = url.rstrip("/").split("/")
    if len(partes) > 2 and len(partes[-1]) >= 24:
        return "/".join([*partes[:-1], "{id}"])
    return url


def _e_util(linha: str) -> bool:
    limpo = linha.strip()
    return any(limpo.startswith(p) for p in PREFIXOS_UTEIS)


def bloco(dados: dict) -> str:
    """O bloco markdown com o placar e os números por cena."""
    placar = dados["placar"]
    linhas = [
        INICIO,
        "",
        "> **Bloco gerado — não edite à mão.**",
        f"> Medido pelo ensaio de `{dados['gerado_em']}`, em"
        f" {dados['segundos_de_maquina']:g} s de máquina"
        f" (teto {dados['teto_s']} s). Regerar:"
        " `bash scripts/demo/replay_demo.sh && python scripts/demo/atualizar_roteiro.py`.",
        "",
        f"**Placar do último ensaio: {placar['prontas']} pronta(s) ·"
        f" {placar['parciais']} parcial(is) · {placar['slides']} slide(s).**",
        "",
        "Identificadores de versão são sorteados a cada montagem da base — por isso"
        " `{id}`. **Chegue à ficha pela tela de Consulta**, sempre.",
        "",
        "| # | Cena | Estado | Onde |",
        "|---|---|---|---|",
    ]
    for cena in dados["cenas"]:
        linhas.append(
            f"| {cena['numero']} | {cena['titulo']} | **{cena['estado'].lower()}** "
            f"| `{_sem_id(cena['url'])}` |"
        )
    linhas += ["", "### Os números que a tela vai mostrar", ""]
    for cena in dados["cenas"]:
        uteis = [linha for linha in cena["linhas"] if _e_util(linha)]
        if not uteis:
            continue
        linhas.append(f"**Cena {cena['numero']} — {cena['titulo']}**")
        linhas.append("")
        for linha in uteis:
            linhas.append(f"- {linha.strip()}")
        linhas.append("")
    linhas += [
        "> Se um número na tela divergir deste bloco, **o da tela vale** — e o bloco está",
        "> velho: rode o ensaio de novo. Se divergir do texto de palco abaixo, o bloco vale,",
        "> porque ele é medido.",
        "",
        FIM,
    ]
    return "\n".join(linhas)


def aplicar(*, checar: bool = False) -> int:
    if not ENSAIO.exists():
        print(f"FALTA: {ENSAIO.relative_to(RAIZ)} não existe. Rode `replay_demo.sh` primeiro.")
        return 1
    dados = json.loads(ENSAIO.read_text(encoding="utf-8"))
    texto = ROTEIRO.read_text(encoding="utf-8")

    novo_bloco = bloco(dados)
    if INICIO in texto and FIM in texto:
        antes = texto[: texto.index(INICIO)]
        depois = texto[texto.index(FIM) + len(FIM) :]
        novo = antes + novo_bloco + depois
    else:
        print(
            f"FALTA: o roteiro não tem os marcadores {INICIO} / {FIM}. "
            "Acrescente-os no lugar onde o bloco deve aparecer."
        )
        return 1

    if checar:
        if novo != texto:
            print(
                "FALTA: o roteiro está desatualizado em relação ao último ensaio. "
                "Rode `python scripts/demo/atualizar_roteiro.py`."
            )
            return 1
        print("ok: o roteiro bate com o último ensaio")
        return 0

    if novo == texto:
        print("ok: o roteiro já estava atualizado")
        return 0
    ROTEIRO.write_text(novo, encoding="utf-8", newline="\n")
    idade = dt.datetime.fromisoformat(dados["gerado_em"])
    print(
        f"ok: {ROTEIRO.relative_to(RAIZ)} atualizado com o ensaio de "
        f"{idade.strftime('%d/%m/%Y %H:%M')} UTC "
        f"({dados['placar']['prontas']} pronta(s), {dados['placar']['parciais']} parcial(is))"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument(
        "--check",
        action="store_true",
        help="não escreve; falha se o roteiro estiver desatualizado",
    )
    args = analisador.parse_args(argv)
    return aplicar(checar=args.check)


if __name__ == "__main__":
    sys.exit(main())
