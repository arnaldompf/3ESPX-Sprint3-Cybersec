"""Mede o Pesquisador em N veículos e escreve `reports/research_eval.md`.

**Por que um script e não um teste.** Isto não afirma que algo está certo — mede quanto
custa. Tempo, cobertura, fontes T1, bloqueios e o motivo da parada, veículo a veículo. É o
que permite escolher, com número e não com impressão, quais dois veículos vão para a
demonstração de 15/09.

Roda ao vivo (`--ao-vivo`) ou em replay. Ao vivo ele **sai para a internet**: respeita
robots.txt e 1 req/s por domínio, como todo o resto do projeto, mas consome cota do provedor
de busca. Por isso o padrão é replay.

    python scripts/research_eval.py                 # os 5 do gabarito, em replay
    python scripts/research_eval.py --ao-vivo       # os 5 novos, ao vivo
    python scripts/research_eval.py --veiculo "RAM|Rampage|Laramie"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from contextlib import nullcontext
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

#: Os cinco que a FASE D manda medir ao vivo: picapes **fora** do catálogo do projeto.
#:
#: São o caso de uso do Pesquisador — veículos que ninguém coletou — e por isso são a
#: medida honesta. Rodar os cinco do gabarito ao vivo mediria o quanto os snapshots ajudam,
#: que é outra pergunta.
NOVOS: list[tuple[str, str, str]] = [
    ("Volkswagen", "Amarok", "V6 Highline"),
    ("Fiat", "Toro", "Ranch 2.0 Turbodiesel AT9 4x4"),
    ("RAM", "Rampage", "Laramie 2.0 Turbodiesel AT9 4x4"),
    ("Mitsubishi", "Triton", "HPE-S 2.4 Turbodiesel AT6 4x4"),
    ("Nissan", "Frontier", "Pro-4X 2.3 Bi-Turbodiesel AT7 4x4"),
]

#: Os cinco do gabarito, para comparar o Pesquisador com o que já sabemos.
#:
#: Aqui existe verdade-terra: dá para dizer se o que ele achou **bate** com o gabarito, e
#: não só quantos campos ele preencheu.
DO_GABARITO: list[tuple[str, str, str]] = [
    ("Ford", "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT"),
    ("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT"),
    ("Toyota", "Hilux", "SRX Plus AT"),
    ("Chevrolet", "S10", "High Country"),
    ("Volkswagen", "Amarok", "V6 Extreme"),
]


def medir(marca: str, modelo: str, versao: str, *, orcamento, alternativa: bool = False) -> dict:
    """Pesquisa um veículo e devolve a linha da tabela — **inclusive o que custou**.

    O bloco `llm.medindo()` é o que separa esta medição da anterior (13/09, 01:56 UTC), que
    saiu com cobertura de 4% a 31% e **nenhuma linha de custo**: ela rodou com `LLM_FAKE=1`,
    porque era o padrão do script, e mediu o fast-path por regex sozinho contra páginas que
    nunca foram vistas — o regime em que ele cobre menos. Sem o `Uso` acumulado não havia
    como saber que o modelo não tinha lido nada; a tabela só mostrava um número baixo.
    """
    from pipeline import llm
    from pipeline.research.run import pesquisar

    comecou = time.monotonic()
    erro = ""
    trocar = llm.como_alternativa() if alternativa else nullcontext()
    medida = llm.Medicao()  # ligado antes do `try` para que o `except` sempre tenha o quê ler
    try:
        with llm.medindo() as medida, trocar:
            resultado = pesquisar(marca, modelo, versao, orcamento=orcamento)
    except Exception as exc:  # provedor fora do ar, rede caída, fixture faltando
        return {
            "veiculo": f"{marca} {modelo} {versao}",
            "erro": f"{type(exc).__name__}: {exc}"[:200],
            "segundos": round(time.monotonic() - comecou, 1),
            "llm": medida.to_dict(),
        }

    fontes = resultado.fontes
    return {
        "veiculo": f"{marca} {modelo} {versao}",
        "erro": erro,
        "llm": medida.to_dict(),
        "campos": resultado.cobertura.com_valor,
        "total": resultado.cobertura.total,
        "fracao": resultado.cobertura.fracao,
        "t1": sum(1 for f in fontes if f.tier == 1 and f.baixada),
        "t2": sum(1 for f in fontes if f.tier == 2 and f.baixada),
        "t3": sum(1 for f in fontes if f.tier == 3 and f.baixada),
        "baixadas": sum(1 for f in fontes if f.baixada),
        "bloqueadas": sum(1 for f in fontes if f.bloqueada),
        "consultas": len(resultado.trilha.consultas),
        "paginas": resultado.orcamento.paginas_gastas,
        "rodadas": resultado.orcamento.rodadas_gastas,
        "segundos": resultado.orcamento.decorrido,
        "motivo": resultado.motivo_da_parada.value,
        "faltando": list(resultado.cobertura.faltando),
    }


def _leitor(*, alternativa: bool) -> str:
    """Quem leu as páginas, em uma frase — para o cabeçalho do relatório.

    Existe porque a medição de 13/09 01:56 UTC **não dizia isto**, e por isso a tabela
    dela era ambígua: 4% de cobertura com modelo real e 4% sem modelo são o mesmo número
    e conclusões opostas. O nome do modelo no cabeçalho é o que torna a tabela lível
    daqui a um mês. Nunca a chave — só provedor e modelo, que são públicos.
    """
    if os.environ.get("LLM_FAKE", "1") not in {"0", "false", "nao"}:
        return "`LLM_FAKE=1` — **sem modelo**: só o fast-path por regex e fixtures gravadas"
    sufixo = "_ALT" if alternativa else ""
    provedor = os.environ.get(f"LLM_PROVIDER{sufixo}") or "(padrão)"
    modelo = os.environ.get(f"LLM_MODEL{sufixo}") or "(padrão do provedor)"
    papel = "IA alternativa" if alternativa else "IA principal"
    return f"**modelo real** — {papel}: `{provedor}` · `{modelo}`"


def escrever(
    linhas: list[dict], destino: Path, *, ao_vivo: bool, provedor: str, leitor: str
) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    agora = dt.datetime.now(dt.UTC).strftime("%d/%m/%Y %H:%M UTC")
    modo = "**ao vivo**" if ao_vivo else "**replay** (sem rede)"

    ok = [linha for linha in linhas if not linha.get("erro")]
    candidatos = sorted(
        (linha for linha in ok if linha["segundos"] < 180 and linha["bloqueadas"] == 0),
        key=lambda linha: (-linha["campos"], linha["segundos"]),
    )

    texto = [
        "# Pesquisador — medição por veículo",
        "",
        f"**Rodado em:** {agora} · **Modo:** {modo} · **Provedor de busca:** `{provedor}`",
        f"· **Quem leu as páginas:** {leitor}",
        "",
        "Isto **não** é um eval de acurácia: é uma medição de custo e cobertura. O que ele",
        "responde é quanto tempo cada veículo leva, quantos campos fecham, de que tier vêm",
        "as fontes e quantas portas se fecharam. A acurácia continua sendo medida pelo",
        "`make eval`, contra o gabarito.",
        "",
        "**Quem leu importa mais aqui do que no eval.** Contra o gabarito, o fast-path por",
        "regex resolve quase tudo, e o modelo é auxiliar (D-263). Aqui as páginas são novas:",
        "não há fixture, e os padrões do fast-path foram escritos olhando outras marcas. É o",
        "regime em que o modelo de verdade é o que existe — e por isso a linha de custo.",
        "",
        "| veículo | campos | T1 | T2 | T3 | baixadas | bloqueadas | consultas | tempo "
        "| LLM | custo | parou por |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for linha in linhas:
        uso = linha.get("llm") or {}
        chamadas = uso.get("chamadas", 0)
        falhas = uso.get("falhas", 0)
        gasto = uso.get("custo_brl", 0.0)
        selo = f"{chamadas}" + (f" (**{falhas} falhou**)" if falhas else "")
        if linha.get("erro"):
            texto.append(
                f"| {linha['veiculo']} | — | — | — | — | — | — | — | "
                f"{linha['segundos']:.0f}s | {selo} | R$ {gasto:.4f} | "
                f"**erro:** {linha['erro']} |"
            )
            continue
        texto.append(
            f"| {linha['veiculo']} | {linha['campos']}/{linha['total']} "
            f"({linha['fracao']:.0%}) | {linha['t1']} | {linha['t2']} | {linha['t3']} | "
            f"{linha['baixadas']} | {linha['bloqueadas']} | {linha['consultas']} | "
            f"{linha['segundos']:.0f}s | {selo} | R$ {gasto:.4f} | {linha['motivo']} |"
        )

    total_brl = sum((linha.get("llm") or {}).get("custo_brl", 0.0) for linha in linhas)
    total_falhas = sum((linha.get("llm") or {}).get("falhas", 0) for linha in linhas)
    total_chamadas = sum((linha.get("llm") or {}).get("chamadas", 0) for linha in linhas)
    texto += [
        "",
        f"**Total:** {total_chamadas} chamada(s) de LLM, {total_falhas} falha(s), "
        f"**R$ {total_brl:.4f}**.",
    ]
    if total_falhas:
        motivos: list[str] = []
        for linha in linhas:
            for motivo in (linha.get("llm") or {}).get("motivos_de_falha", []):
                if motivo not in motivos:
                    motivos.append(motivo)
        texto += [
            "",
            "**Houve falha de provedor nesta rodada, e por isso os números acima não",
            "comparam.** Cobertura baixa por cota esgotada é indistinguível de cobertura",
            "baixa por página pobre — a não ser que a falha apareça. Motivos:",
            "",
        ]
        texto += [f"- `{motivo}`" for motivo in motivos[:5]]

    texto += ["", "## Os candidatos da demonstração", ""]
    if candidatos:
        texto.append(
            "Critério: **mais cobertura, nenhum bloqueio, abaixo de três minutos.** Em ordem:"
        )
        texto.append("")
        for i, linha in enumerate(candidatos[:3], 1):
            texto.append(
                f"{i}. **{linha['veiculo']}** — {linha['campos']}/{linha['total']} campos "
                f"({linha['fracao']:.0%}), {linha['t1']} fonte(s) T1, {linha['segundos']:.0f}s"
            )
    else:
        texto.append(
            "Nenhum veículo passou nos três critérios. **Isto é informação, não falha:** o "
            "que ela diz é que a cena 13 precisa rodar em replay, ou com outro veículo."
        )

    texto += ["", "## O que faltou, por veículo", ""]
    for linha in linhas:
        if linha.get("erro") or not linha.get("faltando"):
            continue
        faltando = ", ".join(linha["faltando"][:12])
        resto = len(linha["faltando"]) - 12
        texto.append(
            f"- **{linha['veiculo']}**: {faltando}" + (f" *(+{resto})*" if resto > 0 else "")
        )

    texto.append("")
    destino.write_text("\n".join(texto), encoding="utf-8")
    print(f"escrito: {destino}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ao-vivo", action="store_true", help="sai para a internet")
    parser.add_argument("--gabarito", action="store_true", help="mede os 5 do gabarito")
    parser.add_argument("--veiculo", action="append", help='"Marca|Modelo|Versão" (repetível)')
    parser.add_argument("--paginas", type=int, default=12)
    parser.add_argument("--rodadas", type=int, default=2)
    parser.add_argument("--segundos", type=float, default=180.0)
    parser.add_argument("--out", default="reports/research_eval.md")
    parser.add_argument(
        "--modelo-real",
        action="store_true",
        help="liga o LLM de verdade (LLM_FAKE=0) — custa dinheiro e tempo",
    )
    parser.add_argument(
        "--alternativa",
        action="store_true",
        help="usa a IA ALTERNATIVA (LLM_*_ALT) no lugar da principal; implica --modelo-real",
    )
    args = parser.parse_args()

    if args.ao_vivo:
        os.environ["REPLAY_MODE"] = "0"
    else:
        os.environ.setdefault("REPLAY_MODE", "1")
        os.environ.setdefault("SEARCH_PROVIDER", "replay")
    if args.modelo_real or args.alternativa:
        # **Explícito, e não pelo `load_dotenv()` que o `import crawl4ai` faz por dentro.**
        # O `.env` já chegava aqui por aquele caminho — mas só quando o navegador era
        # importado, e depois do primeiro uso das variáveis. Configuração que aparece no
        # meio da execução é a mesma classe de defeito que o eval sofreu em 12/09.
        sys.path.insert(0, str(RAIZ / "scripts"))
        import task

        task.load_dotenv()
        os.environ["LLM_FAKE"] = "0"
    else:
        os.environ.setdefault("LLM_FAKE", "1")

    from pipeline.research import gaps
    from pipeline.research.search import provedor_configurado

    if args.veiculo:
        veiculos = [tuple(v.split("|", 2)) for v in args.veiculo]
    elif args.gabarito:
        veiculos = DO_GABARITO
    else:
        veiculos = NOVOS if args.ao_vivo else DO_GABARITO

    linhas: list[dict] = []
    for marca, modelo, versao in veiculos:
        print(f"  medindo {marca} {modelo} {versao}…", flush=True)
        linha = medir(
            marca,
            modelo,
            versao,
            orcamento=gaps.Orcamento(
                rodadas=args.rodadas, paginas=args.paginas, segundos=args.segundos
            ),
            alternativa=args.alternativa,
        )
        linhas.append(linha)
        if linha.get("erro"):
            print(f"    erro: {linha['erro']}")
        else:
            print(
                f"    {linha['campos']}/{linha['total']} campos · {linha['baixadas']} página(s) "
                f"· {linha['bloqueadas']} bloqueada(s) · {linha['segundos']:.0f}s"
            )

    escrever(
        linhas,
        RAIZ / args.out,
        ao_vivo=args.ao_vivo,
        provedor=provedor_configurado(),
        leitor=_leitor(alternativa=args.alternativa),
    )
    (RAIZ / args.out).with_suffix(".json").write_text(
        json.dumps(linhas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
