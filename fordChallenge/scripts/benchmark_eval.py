"""Mede um benchmark completo: tempo, cobertura e o que a régua deixou de fora.

Não afirma que algo está certo — mede quanto custa e quanto se sabe. É o que permite
dizer no palco *"a matriz sai em 1,2 segundo e cobre 41 dos 58 campos"* com número, e não
com impressão.

    python scripts/benchmark_eval.py                        # a melhor Ford do banco
    python scripts/benchmark_eval.py --ford "Ranger Limited"
    python scripts/benchmark_eval.py --banco sqlite:///./data/dev.db

**A cobertura aqui tem dois denominadores, e os dois importam.** `campos_com_valor` conta
os campos em que **algum** veículo tem valor — é o tamanho da tabela útil. `celulas_com_valor`
conta célula a célula — é o quanto da tabela está preenchido de verdade. A primeira sozinha
esconde uma matriz onde só a Ford tem dado.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

if hasattr(sys.stdout, "reconfigure"):  # pragma: no cover - depende do console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DESTINO_MD = RAIZ / "reports" / "benchmark_eval.md"
DESTINO_JSON = RAIZ / "reports" / "benchmark_eval.json"


def _sessao():
    from api.app.db import session_scope

    return session_scope()


def _fords(sessao) -> list:
    from sqlmodel import select

    from api.app.models import Brand, SpecValue, VehicleModel, Version

    com_ficha = set(sessao.exec(select(SpecValue.version_id).distinct()).all())
    linhas = sessao.exec(
        select(Version, VehicleModel)
        .join(VehicleModel, VehicleModel.id == Version.model_id)
        .join(Brand, Brand.id == VehicleModel.brand_id)
        .where(Brand.nome == "Ford")
    ).all()
    # Só as que têm ficha: medir o benchmark de uma versão sem célula nenhuma mediria a
    # ausência de dado, não o benchmark.
    return [(v, m) for v, m in linhas if v.id in com_ficha]


def medir(sessao, ford, modelo) -> dict:
    """Um benchmark inteiro: proposta, matriz e exportação, com o relógio em cada etapa."""
    from api.app.routers import benchmark as rota
    from api.app.services import export_service

    comecou = time.monotonic()
    proposta = rota.propor(sessao, version_id=ford.id)
    t_proposta = time.monotonic() - comecou

    prontos = [c for c in proposta.candidatos if c.no_catalogo and c.version_id]
    faltando = [
        {"veiculo": c.rotulo_do_modelo, "motivo": c.motivo_da_pesquisa}
        for c in proposta.candidatos
        if c.precisa_pesquisa
    ]

    linha: dict = {
        "ford": proposta.ford.rotulo,
        "ano_modelo": proposta.ford.ano_modelo,
        "segmento": proposta.segmento.rotulo,
        "origem_do_segmento": proposta.segmento.origem,
        "candidatos": len(proposta.candidatos),
        "prontos": len(prontos),
        "a_pesquisar": len(faltando),
        "faltando": faltando,
        "segundos_proposta": round(t_proposta, 3),
        "concorrentes": [
            {
                "rotulo": c.rotulo,
                "comparabilidade": c.comparabilidade.resumo if c.comparabilidade else "",
                "comparavel": bool(c.comparabilidade and c.comparabilidade.comparavel),
                "aviso": c.comparabilidade.aviso if c.comparabilidade else "",
            }
            for c in prontos
        ],
    }

    if not prontos:
        linha["erro"] = "nenhum concorrente do segmento está no catálogo neste ano-modelo"
        return linha

    comecou = time.monotonic()
    tabela = export_service.montar_tabela(
        sessao,
        ford_version_id=ford.id,
        competitor_ids=[c.version_id for c in prontos],
    )
    linha["segundos_matriz"] = round(time.monotonic() - comecou, 3)

    celulas = [celula for item in tabela.linhas for celula in item.celulas]
    total_celulas = len(celulas)
    com_valor = sum(1 for celula in celulas if celula.tem_valor)
    com_fonte = sum(1 for celula in celulas if celula.fonte_url)
    situacoes: dict[str, int] = {}
    for celula in celulas:
        if celula.situacao:
            situacoes[celula.situacao] = situacoes.get(celula.situacao, 0) + 1

    comecou = time.monotonic()
    csv = __import__("pipeline.export", fromlist=["para_csv"]).para_csv(tabela)
    linha["segundos_csv"] = round(time.monotonic() - comecou, 3)

    linha.update(
        {
            "campos": len(tabela.linhas),
            "campos_com_valor": tabela.campos_com_valor,
            "celulas": total_celulas,
            "celulas_com_valor": com_valor,
            "celulas_com_fonte": com_fonte,
            "situacoes": situacoes,
            "ressalvas": list(tabela.ressalvas),
            "bytes_csv": len(csv.encode("utf-8")),
        }
    )
    return linha


def escrever(linhas: list[dict], destino: Path) -> None:
    agora = dt.datetime.now(dt.UTC).strftime("%d/%m/%Y %H:%M UTC")
    texto = [
        "# Benchmark — medição por versão Ford",
        "",
        f"**Rodado em:** {agora}",
        "",
        "Isto **não** é um eval de acurácia: mede tempo, cobertura e o que a régua de",
        "comparabilidade deixou de fora. A acurácia continua sendo medida pelo `make eval`,",
        "contra o gabarito.",
        "",
        "**A cobertura tem dois denominadores, e os dois importam.** *Campos com valor* é o",
        "tamanho da tabela útil; *células com valor* é o quanto dela está preenchido de",
        "verdade. O primeiro sozinho esconde uma matriz em que só a Ford tem dado.",
        "",
        "| versão Ford | concorrentes | campos com valor | células com valor | com fonte "
        "| proposta | matriz | CSV |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for linha in linhas:
        if linha.get("erro"):
            texto.append(
                f"| {linha['ford']} | {linha['prontos']}/{linha['candidatos']} | — | — | — | "
                f"{linha['segundos_proposta']:.2f} s | — | — |"
            )
            continue
        texto.append(
            f"| {linha['ford']} | {linha['prontos']}/{linha['candidatos']} | "
            f"{linha['campos_com_valor']}/{linha['campos']} | "
            f"{linha['celulas_com_valor']}/{linha['celulas']} | "
            f"{linha['celulas_com_fonte']}/{linha['celulas_com_valor']} | "
            f"{linha['segundos_proposta']:.2f} s | {linha['segundos_matriz']:.2f} s | "
            f"{linha['segundos_csv']:.2f} s |"
        )

    for linha in linhas:
        texto += ["", f"## {linha['ford']} ({linha['ano_modelo']})", ""]
        texto.append(
            f"Segmento **{linha['segmento']}**, vindo do "
            f"{'mapa escrito' if linha['origem_do_segmento'] == 'mapa' else 'Pesquisador'}."
        )
        if linha.get("erro"):
            texto += ["", f"**Não foi possível comparar:** {linha['erro']}."]
        if linha["concorrentes"]:
            texto += ["", "**Entraram na matriz:**", ""]
            for c in linha["concorrentes"]:
                marca = "" if c["comparavel"] else " — **a régua reprova este par**"
                texto.append(f"- {c['rotulo']} — {c['comparabilidade']}{marca}")
                if c["aviso"]:
                    texto.append(f"  - {c['aviso']}")
        if linha["faltando"]:
            texto += ["", "**Ficaram de fora, e por quê:**", ""]
            texto += [f"- {f['veiculo']}: {f['motivo']}" for f in linha["faltando"]]
        if linha.get("situacoes"):
            ordem = ("ganhamos", "empate", "perdemos", "não sabemos")
            conta = ", ".join(
                f"{linha['situacoes'].get(s, 0)} {s}" for s in ordem if s in linha["situacoes"]
            )
            texto += ["", f"**Nas células comparadas:** {conta}."]
        if linha.get("ressalvas"):
            texto += ["", "**Ressalvas que viajam com a exportação:**", ""]
            texto += [f"- {r}" for r in linha["ressalvas"]]

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(texto) + "\n", encoding="utf-8")
    print(f"escrito: {destino}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ford", help="parte do nome da versão Ford (ex.: 'Limited')")
    parser.add_argument("--banco", help="DATABASE_URL a usar (padrão: o do ambiente)")
    parser.add_argument("--out", default=str(DESTINO_MD))
    args = parser.parse_args()

    if args.banco:
        os.environ["DATABASE_URL"] = args.banco
    os.environ.setdefault("DATABASE_URL", "sqlite:///./data/dev.db")
    os.environ["BENCHMARK_ENABLED"] = "1"

    import task

    task.load_dotenv()

    linhas: list[dict] = []
    with _sessao() as sessao:
        fords = _fords(sessao)
        if args.ford:
            alvo = args.ford.lower()
            fords = [(v, m) for v, m in fords if alvo in f"{m.nome} {v.nome_exato}".lower()]
        if not fords:
            print("nenhuma versão Ford com ficha no banco; nada a medir")
            return 1
        for versao, modelo in fords:
            print(f"  medindo {modelo.nome} {versao.nome_exato} {versao.ano_modelo}…", flush=True)
            linha = medir(sessao, versao, modelo)
            linhas.append(linha)
            if linha.get("erro"):
                print(f"    {linha['erro']}")
            else:
                print(
                    f"    {linha['campos_com_valor']}/{linha['campos']} campos · "
                    f"{linha['celulas_com_valor']}/{linha['celulas']} células · "
                    f"{linha['segundos_matriz']:.2f} s"
                )

    escrever(linhas, Path(args.out))
    Path(args.out).with_suffix(".json").write_text(
        json.dumps(linhas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
