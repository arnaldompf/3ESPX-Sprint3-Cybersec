"""Roda o eval **uma vez por configuração de IA** e põe os números lado a lado.

A pergunta que ele responde é a única que decide a configuração da apresentação:

> **o modelo de verdade acha mais campos que a fixture gravada — e a que custo de tempo?**

Três configurações, e cada uma isola uma variável:

* **`fixture`** (`LLM_FAKE=1`) — o modo determinístico do CI e da demo. É o piso: mede o
  que o fast-path por regex e as fixtures já resolvem, com custo **zero de verdade**;
* **`principal`** (`LLM_FAKE=0`) — o provedor do `.env`;
* **`alternativa`** — o segundo provedor, pelo mesmo caminho de código.

A coleta fica em **replay** nas três (`REPLAY_MODE=1`): as páginas são as mesmas cópias
salvas. Sem isso, a diferença entre duas colunas misturaria "o modelo leu melhor" com "a
internet respondeu diferente", e nenhuma das duas ficaria sabida.

    python scripts/eval_modelos.py                      # as três
    python scripts/eval_modelos.py --so fixture principal
    python scripts/eval_modelos.py --veiculo ford_ranger_raptor

**Ao vivo custa dinheiro e tempo.** Com o Kimi Tier0 (3 requisições por minuto) o eval
inteiro leva dezenas de minutos — o script imprime o andamento veículo a veículo para que
dê para acompanhar, e escreve o relatório mesmo se uma configuração falhar.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

if hasattr(sys.stdout, "reconfigure"):  # pragma: no cover - depende do console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DESTINO_MD = RAIZ / "reports" / "eval_modelos.md"
DESTINO_JSON = RAIZ / "reports" / "eval_modelos.json"

#: As métricas que entram na comparação, na ordem em que importam.
#:
#: `grounding_rate` e `hallucination_rate` vêm primeiro de propósito: um modelo que acha
#: mais campos **e** inventa um deles não é melhor, é pior. A ordem da tabela é a ordem
#: em que se deve olhar.
METRICAS = (
    "grounding_rate",
    "hallucination_rate",
    "field_accuracy",
    "status_fidelity",
    "coverage",
)


def configurar(modo: str):
    """Devolve o contexto que põe o ambiente na configuração pedida.

    A coleta fica em replay nos três modos — a variável sob teste é o modelo, e só ele.
    """
    from pipeline import llm

    os.environ["REPLAY_MODE"] = "1"
    if modo == "fixture":
        # **`replay_env()` do `task.py`, e não um `LLM_FAKE=1` escrito aqui.**
        #
        # A fixture de LLM é indexada por `hash(modelo, campos, prompt)`, e as gravadas
        # trazem o modelo histórico do projeto (a Anthropic). Com `LLM_MODEL=kimi-k2.6`
        # vindo do `.env`, a chave muda, **nenhuma fixture casa**, e o pipeline segue com
        # os campos vazios sem um erro sequer: a coluna media 102/109 em vez de 104/109.
        #
        # A primeira versão deste script escreveu `LLM_FAKE=1` à mão e caiu exatamente
        # nesse buraco — o mesmo que `scripts/task.py::replay_env` documenta desde
        # 12/09/2026. Chamar a função de lá é o que garante que a coluna de referência
        # seja a **mesma** que `make eval` publica.
        # **Dentro de `ambiente_protegido()`, e isso não é zelo.** `replay_env()` desarma
        # *todas* as credenciais, inclusive `LLM_API_KEY_ALT`. Sem restaurar ao sair, a
        # coluna "fixture" apagaria a configuração da coluna "alternativa", e
        # `--so fixture alternativa` falharia na segunda — com a mensagem "não há IA
        # alternativa configurada", que aponta para o `.env` e não para a ordem das
        # colunas. Um teste pegou isto antes de a rodada longa pagar por ele.
        import task

        @contextmanager
        def _como_fixture():
            with llm.ambiente_protegido():
                task.replay_env()
                yield

        return _como_fixture()
    os.environ["LLM_FAKE"] = "0"
    if modo == "principal":
        return nullcontext()
    if modo == "alternativa":
        if not llm.tem_alternativa():
            raise RuntimeError("não há IA alternativa configurada (LLM_PROVIDER_ALT/_KEY_ALT)")
        return llm.como_alternativa()
    raise ValueError(f"modo desconhecido: {modo}")


def rodar(modo: str, *, gabarito: Path, so_veiculo: str) -> dict:
    """Roda o eval numa configuração e devolve o agregado + o detalhe por veículo."""
    from pipeline import llm
    from pipeline.eval.gabarito import carregar_gabarito
    from pipeline.eval.run import agregar, avaliar_veiculo

    with configurar(modo):
        provedor = llm.provedor_atual() if not llm.modo_fake() else "fixture"
        modelo = llm.modelo_pequeno() if not llm.modo_fake() else "—"
        print(f"\n  [{modo}] {provedor} · {modelo}")

        g = carregar_gabarito(gabarito)
        veiculos = [v for v in g.veiculos if not so_veiculo or v.id == so_veiculo]
        if not veiculos:
            raise RuntimeError(f"nenhum veículo casa com {so_veiculo!r}")

        linhas: list[dict] = []
        comecou = time.monotonic()
        for veiculo in veiculos:
            t0 = time.monotonic()
            r = avaliar_veiculo(veiculo, replay=True)
            uso = r.uso or {}
            linhas.append(
                {
                    "id": r.id,
                    "descricao": r.descricao,
                    "segundos": round(time.monotonic() - t0, 1),
                    "custo_brl": r.custo_brl,
                    "llm": uso,
                    "metricas": {k: v.to_dict() for k, v in r.metricas.items()},
                }
            )
            falhas = uso.get("falhas", 0)
            alerta = f"  ** {falhas} FALHA(S) **" if falhas else ""
            print(
                f"      {r.descricao[:44]:<46} {time.monotonic() - t0:6.1f}s  "
                f"{uso.get('chamadas', 0):>2} chamada(s)  R$ {r.custo_brl:.4f}{alerta}"
            )

        total = agregar([_falso_resultado(linha) for linha in linhas])
        return {
            "modo": modo,
            "provedor": provedor,
            "modelo": modelo,
            "segundos": round(time.monotonic() - comecou, 1),
            "custo_brl": round(sum(linha["custo_brl"] for linha in linhas), 4),
            "chamadas": sum(linha["llm"].get("chamadas", 0) for linha in linhas),
            "tokens_entrada": sum(linha["llm"].get("tokens_entrada", 0) for linha in linhas),
            "tokens_saida": sum(linha["llm"].get("tokens_saida", 0) for linha in linhas),
            "tokens_de_raciocinio": sum(
                linha["llm"].get("tokens_de_raciocinio", 0) for linha in linhas
            ),
            "falhas": sum(linha["llm"].get("falhas", 0) for linha in linhas),
            "sem_fixture": sum(linha["llm"].get("sem_fixture", 0) for linha in linhas),
            "motivos_de_falha": sorted(
                {m for linha in linhas for m in linha["llm"].get("motivos_de_falha", [])}
            )[:5],
            "agregado": {k: v.to_dict() for k, v in total.items()},
            "veiculos": linhas,
        }


def _falso_resultado(linha: dict):
    """Recria o mínimo que `agregar` precisa a partir do dicionário já serializado."""
    from pipeline.eval.run import Metrica, ResultadoVeiculo

    metricas = {}
    for nome, bruto in linha["metricas"].items():
        m = Metrica(nome=nome)
        m.acertos = bruto.get("acertos", 0)
        m.n = bruto.get("n", 0)
        metricas[nome] = m
    return ResultadoVeiculo(
        id=linha["id"], descricao=linha["descricao"], papel="", metricas=metricas
    )


def _pct(bruto: dict) -> str:
    if not bruto.get("n"):
        return "—"
    return f"{bruto['acertos']}/{bruto['n']} ({bruto['acertos'] / bruto['n']:.1%})"


def escrever(rodadas: list[dict], *, so_veiculo: str) -> None:
    agora = datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC")
    alvo = f" · **apenas** `{so_veiculo}`" if so_veiculo else ""
    texto = [
        "# Eval por configuração de IA",
        "",
        f"**Rodado em:** {agora}{alvo}",
        "",
        "A coleta está em **replay** nas três colunas: as páginas são as mesmas cópias",
        "salvas. A única variável é quem lê o documento. Sem isso, a diferença entre duas",
        'colunas misturaria *"o modelo leu melhor"* com *"a internet respondeu diferente"*.',
        "",
        "**Olhe nesta ordem:** grounding e alucinação primeiro. Um modelo que acha mais",
        "campos e inventa um deles não é melhor — é pior, e de um jeito que a acurácia",
        "média esconde.",
        "",
        "| | "
        + " | ".join(f"**{r['modo']}**" + (" ⚠︎" if r.get("falhas") else "") for r in rodadas)
        + " |",
        "|---|" + "---|" * len(rodadas),
        "| provedor · modelo | "
        + " | ".join(f"`{r['provedor']}` · `{r['modelo']}`" for r in rodadas)
        + " |",
    ]
    for metrica in METRICAS:
        celulas = " | ".join(_pct(r["agregado"].get(metrica, {})) for r in rodadas)
        texto.append(f"| {metrica} | {celulas} |")

    texto += [
        "| **tempo total** | " + " | ".join(f"{r['segundos']:.0f} s" for r in rodadas) + " |",
        "| **chamadas** | " + " | ".join(str(r["chamadas"]) for r in rodadas) + " |",
        "| **tokens (entrada→saída)** | "
        + " | ".join(f"{r['tokens_entrada']}→{r['tokens_saida']}" for r in rodadas)
        + " |",
        "| **dos quais raciocínio** | "
        + " | ".join(str(r["tokens_de_raciocinio"]) for r in rodadas)
        + " |",
        "| **custo** | " + " | ".join(f"R$ {r['custo_brl']:.4f}" for r in rodadas) + " |",
        "| **chamadas que falharam** | "
        + " | ".join(str(r.get("falhas", 0)) for r in rodadas)
        + " |",
        "| **chamadas sem fixture gravada** | "
        + " | ".join(str(r.get("sem_fixture", 0)) or "—" for r in rodadas)
        + " |",
        "",
        "## Por veículo",
        "",
    ]
    quebradas = [r for r in rodadas if r.get("falhas")]
    if quebradas:
        texto += [
            "> ### ⚠︎ Colunas com chamada que falhou — **não compare estes números**",
            ">",
            "> Uma rodada em que o provedor recusou chamadas mede o provedor recusando,",
            "> não o modelo lendo. Os campos que faltaram ficaram vazios pelo motivo",
            "> errado, e a acurácia daí sai **baixa por acidente**.",
            ">",
        ]
        for r in quebradas:
            motivos = r.get("motivos_de_falha") or ["(sem motivo registrado)"]
            texto.append(
                f"> - **{r['modo']}**: {r['falhas']} de {r['chamadas']} chamada(s) "
                f"falharam. Primeiro motivo: `{motivos[0]}`"
            )
        texto.append("")

    for r in rodadas:
        aviso = "  ⚠︎ **não confiável**" if r.get("falhas") else ""
        texto.append(f"### {r['modo']} — `{r['provedor']}` · `{r['modelo']}`{aviso}")
        texto.append("")
        texto.append("| veículo | tempo | chamadas | tokens saída | raciocínio | custo |")
        texto.append("|---|---:|---:|---:|---:|---:|")
        for linha in r["veiculos"]:
            uso = linha["llm"]
            texto.append(
                f"| {linha['descricao']} | {linha['segundos']:.1f} s "
                f"| {uso.get('chamadas', 0)} | {uso.get('tokens_saida', 0)} "
                f"| {uso.get('tokens_de_raciocinio', 0)} | R$ {linha['custo_brl']:.4f} |"
            )
        texto.append("")

    DESTINO_MD.parent.mkdir(parents=True, exist_ok=True)
    DESTINO_MD.write_text("\n".join(texto) + "\n", encoding="utf-8")
    DESTINO_JSON.write_text(json.dumps(rodadas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  escrito: {DESTINO_MD.relative_to(RAIZ)} e {DESTINO_JSON.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--so",
        nargs="+",
        choices=("fixture", "principal", "alternativa"),
        default=["fixture", "principal", "alternativa"],
    )
    parser.add_argument("--veiculo", default="", help="id do gabarito, para medir um só")
    parser.add_argument("--gabarito", default="gabarito/gabarito_v1.json")
    args = parser.parse_args()

    import env_check

    for nome, valor in env_check.ler(RAIZ / ".env").items():
        os.environ.setdefault(nome, valor)

    rodadas: list[dict] = []
    for modo in args.so:
        try:
            rodadas.append(rodar(modo, gabarito=RAIZ / args.gabarito, so_veiculo=args.veiculo))
        except Exception as exc:  # uma configuração fora do ar não derruba as outras
            print(f"  [{modo}] FALHOU: {type(exc).__name__}: {str(exc)[:200]}")

    if not rodadas:
        print("nenhuma configuração rodou")
        return 1
    escrever(rodadas, so_veiculo=args.veiculo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
