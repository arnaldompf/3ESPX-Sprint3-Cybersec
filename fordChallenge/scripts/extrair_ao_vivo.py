#!/usr/bin/env python
"""Extração **com o provedor de LLM de verdade**, um veículo por vez, com a conta na mão.

    python scripts/extrair_ao_vivo.py                      # os cinco veículos
    python scripts/extrair_ao_vivo.py --veiculo ford_ranger_raptor_2026
    python scripts/extrair_ao_vivo.py --teto-de-tokens 300000

Por que este arquivo existe, e por que ele não é uma opção da CLI:

* **`LLM_FAKE=0` vale só aqui dentro.** O padrão do projeto é `LLM_FAKE=1` — em teste, no
  `seed`, na demonstração e no eval de replay —, e ele tem de continuar sendo. Trocar a
  variável no `.env` faria a demonstração inteira passar a gastar token sem ninguém pedir.
  Este script lê o `.env` para saber **qual** provedor usar e liga o modo real no próprio
  processo, sem tocar no arquivo;
* **`REPLAY_MODE=1` continua ligado.** "Ao vivo" aqui é o *modelo*, não a *coleta*: as
  fontes continuam vindo dos snapshots salvos, que é o que torna a medição comparável com
  a do replay. Coletar ao vivo é outro comando, e outra noite;
* **a conta fica registrada.** Tokens de entrada e de saída, custo estimado, tempo e o
  motivo de cada chamada que não deu certo vão para `reports/extracao_ao_vivo.json`. Sem
  isso, "rodamos com o modelo real" é uma frase, não um número.

O portão de vazão de `pipeline/llm.py` (concorrência 1, intervalo mínimo, retentativa em
429) vale aqui como em qualquer chamada real. Na conta Tier0 da Moonshot AI isso significa
**21 s entre chamadas**: uma extração de cinco veículos leva dezenas de minutos, e é assim
mesmo — o limite é do plano, não do código.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

DESTINO = RAIZ / "reports" / "extracao_ao_vivo.json"

#: Os cinco veículos com snapshot salvo, na ordem do gabarito. O primeiro é o da spec.
VEICULOS: tuple[tuple[str, str, str, str], ...] = (
    ("ford_ranger_raptor_2026", "Ford", "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT"),
    ("ford_ranger_limited_2027", "Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT"),
    ("toyota_hilux_srx_plus_at_2026", "Toyota", "Hilux", "SRX Plus AT"),
    ("vw_amarok_v6_extreme_2026", "Volkswagen", "Amarok", "V6 Extreme"),
    ("chevrolet_s10_high_country_2027", "Chevrolet", "S10", "High Country"),
)


def carregar_env() -> None:
    """Lê o `.env` sem sobrescrever o que já está no ambiente.

    Só o provedor interessa aqui (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`,
    `LLM_API_BASE`); o resto vem junto porque o arquivo é um só.
    """
    arquivo = RAIZ / ".env"
    if not arquivo.exists():
        return
    for bruta in arquivo.read_text(encoding="utf-8").splitlines():
        linha = bruta.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def somar(usos) -> dict[str, float]:
    """Tokens, custo e tempo de uma lista de `llm.Uso`. Fixture conta como zero.

    `tentativas` e `respondidas` são coisas diferentes, e separá-las é o ponto: uma conta
    sem saldo produz oito tentativas e zero resposta, e um relatório que só dissesse
    "8 chamadas" pareceria sucesso.
    """
    reais = [u for u in usos if not u.de_fixture]
    respondidas = [u for u in reais if u.tokens_entrada or u.tokens_saida]
    return {
        "tentativas": len(reais),
        "respondidas": len(respondidas),
        "tokens_entrada": sum(u.tokens_entrada for u in reais),
        "tokens_saida": sum(u.tokens_saida for u in reais),
        "custo_brl": round(sum(u.custo_brl for u in reais), 4),
        # `None` e nao `False` quando nada foi respondido: dizer "o custo nao e
        # estimativa" sobre zero chamada seria afirmar algo sobre nada.
        "custo_e_estimativa": (
            any(u.custo_usd_informado is None for u in respondidas) if respondidas else None
        ),
    }


#: O que marca um aviso como vindo do passo de LLM. Escrito pelas formas que
#: `pipeline/extract/run.py` produz, e não por uma palavra solta: o motivo do provedor
#: (`RateLimitError: ... insufficient balance`) não contém "LLM" em lugar nenhum, e um
#: filtro ingênuo devolve lista vazia justamente quando há o que contar.
MARCAS_DE_AVISO_DE_LLM = (
    "bloco ",
    "passada (modelo grande)",
    "LLM",
    "429",
    "Error",
    "erro",
)

#: Identificadores de credencial que o provedor devolve **dentro da mensagem de erro**.
#:
#: `pipeline/llm.py` já mascara o **valor** da chave; a Moonshot devolve, além dele, o id
#: da organização e o id da chave (`ak-...`). Nenhum dos dois é o segredo, e nenhum dos
#: dois tem por que ser copiado adiante: o relatório é colado em `MANHA.md`, em relatório
#: de QA e em conversa, e quem lê precisa do motivo ("conta sem saldo"), não da identidade
#: da conta.
IDENTIFICADORES = re.compile("(ak|sk|org)-[A-Za-z0-9_-]{6,}", re.IGNORECASE)


def sem_identificadores(texto: str) -> str:
    """Troca `org-...` e `ak-...` por `***`. O motivo continua legível."""
    return IDENTIFICADORES.sub(lambda m: f"{m.group(1)}-***", texto)


def listar_modelos(base: str, chave: str) -> int:
    """`GET /models` do provedor: o que a conta enxerga, sem gastar token.

    Existe como comando porque a pergunta "o `LLM_MODEL` do `.env` existe mesmo?" é a
    primeira a fazer antes de qualquer extração, e adivinhar nome de modelo é a mesma
    classe de erro que adivinhar valor de especificação. A listagem é gratuita e não
    consome cota; ela também responde se a chave e o endereço combinam.
    """
    import httpx

    if not base:
        print("ABORTADO: --listar-modelos precisa de LLM_API_BASE no .env.")
        return 2
    try:
        resposta = httpx.get(
            f"{base.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {chave}"},
            timeout=45.0,
        )
    except Exception as erro:  # rede caida vira mensagem, nao traceback
        print(f"FALHOU: {type(erro).__name__}: {sem_identificadores(str(erro))[:300]}")
        return 1
    if resposta.status_code != 200:
        corpo = sem_identificadores(resposta.text.replace(chave, "***"))
        print(f"HTTP {resposta.status_code}: {corpo[:500]}")
        return 1
    ids = sorted(m.get("id", "?") for m in resposta.json().get("data", []))
    print(f"{len(ids)} modelo(s) em {base}:")
    for identificador in ids:
        print(f"   {identificador}")
    return 0


def main(argv: list[str] | None = None) -> int:
    analise = argparse.ArgumentParser(description=__doc__)
    analise.add_argument("--veiculo", action="append", default=[], help="id (repetível)")
    analise.add_argument(
        "--teto-de-tokens",
        type=int,
        default=300_000,
        help="para depois do veículo que cruzar este total (0 = sem teto)",
    )
    analise.add_argument(
        "--listar-modelos",
        action="store_true",
        help="só pergunta ao provedor quais modelos a conta enxerga, e sai",
    )
    argumentos = analise.parse_args(argv)

    carregar_env()
    # **Aqui, e só aqui.** O `.env` continua com o padrão do projeto.
    os.environ["LLM_FAKE"] = "0"
    os.environ.setdefault("REPLAY_MODE", "1")
    os.environ.setdefault("PYTHONUTF8", "1")

    from pipeline import llm
    from pipeline.run import run as pipeline_run

    if llm.modo_fake():  # pragma: no cover - defesa contra ambiente esquisito
        print("ABORTADO: LLM_FAKE continua ligado. Nada foi chamado.")
        return 2
    if not llm.tem_chave():
        print(
            "ABORTADO: nenhuma chave de provedor no ambiente "
            f"({' / '.join(llm.nomes_de_chave())}). Nada foi chamado, nada foi inventado."
        )
        return 2

    if argumentos.listar_modelos:
        return listar_modelos(llm.api_base(), llm.chave_do_provedor())

    escolhidos = [v for v in VEICULOS if not argumentos.veiculo or v[0] in argumentos.veiculo]
    if not escolhidos:
        print(f"ABORTADO: nenhum veiculo casa com {argumentos.veiculo}.")
        return 2

    cabecalho = {
        "provedor": llm.provedor_atual(),
        "modelo": llm.modelo_pequeno(),
        "modelo_grande": llm.modelo_grande(),
        "api_base": llm.api_base() or "(default do litellm)",
        "intervalo_minimo_s": llm.intervalo_minimo(),
        "replay_de_coleta": os.environ.get("REPLAY_MODE") == "1",
    }
    print("=" * 78)
    print("EXTRACAO AO VIVO — provedor de LLM real")
    print("=" * 78)
    for chave, valor in cabecalho.items():
        print(f"  {chave:20s} {valor}")
    print(f"  {'teto de tokens':20s} {argumentos.teto_de_tokens or 'sem teto'}")
    print("")

    linhas: list[dict] = []
    total_tokens = 0
    parou_no_teto = ""

    for version_id, marca, modelo, versao in escolhidos:
        print(f"-- {marca} {modelo} {versao}")
        inicio = time.perf_counter()
        contexto: list = []
        try:
            spec = pipeline_run(
                marca=marca,
                modelo=modelo,
                versao=versao,
                replay=True,
                version_id=version_id,
                contexto=contexto,
            )
        except Exception as erro:  # o motivo vai para o relatorio, nao para um traceback
            print(f"   FALHOU: {type(erro).__name__}: {erro}")
            linhas.append({"id": version_id, "erro": f"{type(erro).__name__}: {erro}"})
            continue
        decorrido = time.perf_counter() - inicio

        ctx = contexto[0] if contexto else None
        usos = list(ctx.extracao.usos) if ctx and ctx.extracao else []
        conta = somar(usos)
        com_valor = sum(1 for _, campo in spec.itens() if campo.value is not None)
        avisos = list(ctx.avisos) if ctx else []
        motivos = sorted(
            {
                sem_identificadores(a)
                for a in avisos
                if any(marca in a for marca in MARCAS_DE_AVISO_DE_LLM)
            }
        )

        linha = {
            "id": version_id,
            "rotulo": f"{marca} {modelo} {versao}",
            "campos_com_valor": com_valor,
            "tempo_s": round(decorrido, 2),
            **conta,
            "motivos_do_llm": motivos[:4],
        }
        linhas.append(linha)
        total_tokens += conta["tokens_entrada"] + conta["tokens_saida"]
        print(
            f"   {com_valor} campo(s) com valor · {conta['respondidas']}/"
            f"{conta['tentativas']} chamada(s) respondida(s) · "
            f"{conta['tokens_entrada']}+{conta['tokens_saida']} tokens · "
            f"R$ {conta['custo_brl']:.4f} · {decorrido:.1f}s"
        )
        for motivo in motivos[:2]:
            print(f"   motivo: {motivo[:160]}")

        if argumentos.teto_de_tokens and total_tokens >= argumentos.teto_de_tokens:
            parou_no_teto = (
                f"parou depois de {version_id}: {total_tokens} tokens "
                f">= teto de {argumentos.teto_de_tokens}"
            )
            print(f"   {parou_no_teto}")
            break

    relatorio = {
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **cabecalho,
        "veiculos": linhas,
        "total_tokens": total_tokens,
        "total_custo_brl": round(sum(linha.get("custo_brl", 0.0) for linha in linhas), 4),
        "parou_no_teto": parou_no_teto,
        "pedidos": [v[0] for v in escolhidos],
    }
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("")
    print(
        f"total: {total_tokens} token(s), R$ {relatorio['total_custo_brl']:.4f} "
        f"em {len(linhas)} veiculo(s)"
    )
    print(f"escrito: {DESTINO.relative_to(RAIZ)}")
    # Zero chamada real com chave presente significa que **nenhuma** foi aceita: é
    # resultado ruim e tem de sair no codigo de saida, nao so no texto.
    if total_tokens == 0:
        print("ATENCAO: nenhuma chamada ao provedor foi aceita. Leia os motivos acima.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
