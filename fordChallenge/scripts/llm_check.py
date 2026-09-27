"""Testa os provedores de IA configurados com **uma chamada mínima**, e mede o que custa.

Responde três perguntas que só a rede responde, e que nenhum teste em fixture alcança:

1. **a chave funciona?** — chave certa no endereço errado volta como erro de autenticação,
   que é o sintoma mais enganoso que existe (parece chave inválida, e é `LLM_API_BASE`);
2. **o nome do modelo existe?** — se não, o script **lista os modelos pela API do próprio
   provedor** e mostra os candidatos. Adivinhar nome de modelo é a mesma classe de erro que
   adivinhar valor de especificação, e aqui não se adivinha;
3. **ele devolve JSON estruturado?** — é a única coisa que o pipeline pede dele. Um modelo
   que escreve prosa em volta do JSON serve para conversar e não serve para extrair.

O que ele **não** faz: inventar limite de cota ou preço. Esses números vêm da documentação
do provedor e estão em `LIMITES_PUBLICADOS`, com a data em que foram lidos — quando o
provedor informa cota nos cabeçalhos da resposta, o medido vence o publicado e o relatório
diz qual é qual.

    python scripts/llm_check.py                  # principal e alternativa
    python scripts/llm_check.py --so principal
    python scripts/llm_check.py --listar-modelos # só lista, sem gastar chamada de geração

**Nenhum valor de chave sai daqui**, nem em erro: as mensagens do provedor passam por
`pipeline.llm._sem_segredo` antes de serem impressas.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

if hasattr(sys.stdout, "reconfigure"):  # pragma: no cover - depende do console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DESTINO = RAIZ / "reports" / "llm_check.json"

#: O pedido mínimo. Curto de propósito: a pergunta é se o caminho funciona, não se o
#: modelo é bom. Cinco tokens de resposta custam frações de centavo e medem a latência
#: real da conta — que é o número que decide se o Pesquisador cabe em três minutos.
PROMPT = (
    "Devolva apenas este JSON, sem texto em volta: "
    '{"ok": true, "motor": "<o nome do modelo que está respondendo>"}'
)
CAMPOS = ["ok", "motor"]

#: Orçamento de saída da sonda. **Não é 64, e a diferença foi medida.**
#:
#: `kimi-k2.6` é modelo de raciocínio: pedindo `{"ok": true}` com 64 tokens, ele gastou
#: 63 **pensando**, terminou em `finish_reason="length"` e devolveu conteúdo vazio. A
#: resposta certa nunca começou a ser escrita, e o sintoma — "não é JSON válido" — mandava
#: depurar o prompt. Mil tokens é folga suficiente para o raciocínio de uma pergunta trivial
#: e continua custando frações de centavo.
ORCAMENTO_DA_SONDA = 1024

#: Limites e preços **da documentação do provedor**, com a data da leitura.
#:
#: Não são medidos por este script, e por isso não se disfarçam de medidos. Cota e preço
#: mudam sem aviso; um número aqui com seis meses é um número errado, e a data é o que
#: permite saber disso sem ter de descobrir na hora da demonstração.
LIMITES_PUBLICADOS: dict[str, dict[str, str]] = {
    "kimi": {
        "fonte": "platform.moonshot.ai — página de limites de vazão (tier por saldo)",
        "lido_em": "13/09/2026",
        "observacao": (
            "a vazão da Moonshot AI é por **tier**, e o tier sobe com o saldo/histórico da "
            "conta. O Tier0 desta máquina dá 3 RPM e concorrência 1 — é o número que o "
            "`intervalo_minimo_s=21.0` de `pipeline/llm.py` assume. Confirme em "
            "platform.moonshot.ai → Limits antes de contar com mais."
        ),
    },
    "gemini": {
        "fonte": "ai.google.dev/gemini-api/docs/rate-limits",
        "lido_em": "13/09/2026",
        "observacao": (
            "o Gemini publica RPM, TPM e RPD por modelo **e por nível** (free / tier 1+). "
            "O nível da conta não é visível pela chave, então o número que vale é o do "
            "painel do Google AI Studio desta conta."
        ),
    },
    "anthropic": {
        "fonte": "docs.claude.com — Rate limits",
        "lido_em": "13/09/2026",
        "observacao": "RPM/ITPM/OTPM por tier de uso; o tier sobe com o histórico de gasto.",
    },
}


@dataclass
class Medida:
    """O resultado de testar um provedor. Tudo o que está aqui é medido ou declarado."""

    papel: str  # "principal" | "alternativa"
    provedor: str = ""
    modelo: str = ""
    endereco: str = ""
    chave_presente: bool = False
    chave_final: str = ""  # os 4 últimos caracteres, nunca mais
    ok: bool = False
    motivo: str = ""
    json_valido: bool = False
    segundos: float = 0.0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_de_raciocinio: int = 0
    custo_usd: float = 0.0
    custo_e_estimativa: bool = True
    modelos_disponiveis: list[str] = field(default_factory=list)
    limites: dict[str, str] = field(default_factory=dict)


def _final(valor: str) -> str:
    return f"····{valor[-4:]}" if len(valor) >= 8 else "(curta)"


def carregar_env() -> None:
    """Põe o `.env` no ambiente, sem sobrescrever o que já estiver definido.

    Usa o leitor de `scripts/env_check.py` — o mesmo que entende `export`, aspas e
    comentários. Um segundo leitor de `.env` neste repositório seria o terceiro, e a
    diferença entre eles só apareceria no dia em que alguém usasse aspas.
    """
    sys.path.insert(0, str(RAIZ / "scripts"))
    import env_check

    for nome, valor in env_check.ler(RAIZ / ".env").items():
        os.environ.setdefault(nome, valor)


def listar_modelos(provedor: str, chave: str, endereco: str) -> tuple[list[str], str]:
    """Pergunta ao provedor **quais modelos a conta pode usar**.

    É o passo que transforma "modelo não encontrado" de beco sem saída em lista de
    escolhas. Cada provedor tem seu jeito, e são só dois jeitos no fim: o do Google, com
    a chave na query, e o resto, compatível com a OpenAI.
    """
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return [], "httpx ausente"

    try:
        if provedor == "gemini":
            # O Google não aceita Bearer aqui: a chave vai na query, e é por isso que um
            # token OAuth (`AQ.…`) falha neste endpoint mesmo sendo credencial válida —
            # ele é de outro mecanismo de autenticação.
            url = "https://generativelanguage.googleapis.com/v1beta/models"
            resposta = httpx.get(url, params={"key": chave}, timeout=20.0)
            resposta.raise_for_status()
            nomes = [m["name"].removeprefix("models/") for m in resposta.json().get("models", [])]
        else:
            base = (endereco or _base_padrao(provedor)).rstrip("/")
            resposta = httpx.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {chave}"},
                timeout=20.0,
            )
            resposta.raise_for_status()
            nomes = [m.get("id", "") for m in resposta.json().get("data", [])]
        return sorted(n for n in nomes if n), ""
    except Exception as exc:  # rede, auth, formato — todos interessam, nenhum derruba
        from pipeline.llm import _sem_segredo

        return [], _sem_segredo(f"{type(exc).__name__}: {exc}"[:300], chave)


def _base_padrao(provedor: str) -> str:
    return {
        "kimi": "https://api.moonshot.ai/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
    }.get(provedor, "")


def medir(papel: str, *, listar: bool) -> Medida:
    """Testa o provedor que estiver ativo no ambiente **agora**."""
    from pipeline import llm

    m = Medida(papel=papel)
    m.provedor = llm.provedor_atual()
    m.modelo = llm.modelo_pequeno()
    m.endereco = llm.api_base() or _base_padrao(m.provedor) or "(default do LiteLLM)"
    chave = llm.chave_do_provedor()
    m.chave_presente = bool(chave)
    m.chave_final = _final(chave)
    m.limites = LIMITES_PUBLICADOS.get(m.provedor, {})

    if not m.chave_presente:
        m.motivo = f"sem chave para {m.provedor}: {' / '.join(llm.nomes_de_chave())}"
        return m
    if not m.modelo:
        m.motivo = f"{m.provedor} não tem modelo padrão; defina LLM_MODEL"
        if listar:
            m.modelos_disponiveis, erro = listar_modelos(m.provedor, chave, llm.api_base())
            if erro:
                m.motivo += f" · a lista de modelos também falhou: {erro}"
        return m

    comecou = time.monotonic()
    resposta = llm.extrair_json(prompt=PROMPT, campos=CAMPOS, max_tokens=ORCAMENTO_DA_SONDA)
    m.segundos = round(time.monotonic() - comecou, 2)
    m.ok = resposta.ok
    m.motivo = resposta.motivo
    m.json_valido = bool(resposta.dados) and "ok" in resposta.dados

    if resposta.uso is not None:
        m.tokens_entrada = resposta.uso.tokens_entrada
        m.tokens_saida = resposta.uso.tokens_saida
        m.tokens_de_raciocinio = resposta.uso.tokens_de_raciocinio
        m.custo_usd = round(resposta.uso.custo_usd, 6)
        m.custo_e_estimativa = resposta.uso.custo_usd_informado is None

    # A lista de modelos só é pedida quando ela **resolve alguma coisa**: o modelo pedido
    # não existe, ou a conta não pode usá-lo. Pedi-la sempre gastaria uma chamada por
    # execução para imprimir o que ninguém ia ler.
    if listar or (not m.ok and _parece_modelo_errado(m.motivo)):
        m.modelos_disponiveis, erro = listar_modelos(m.provedor, chave, llm.api_base())
        if erro and not m.motivo:
            m.motivo = erro
    return m


def _parece_modelo_errado(motivo: str) -> bool:
    baixo = motivo.lower()
    return any(
        marca in baixo
        for marca in ("model", "not found", "404", "does not exist", "invalid_request")
    )


def custo_por_mil(m: Medida) -> str:
    """Custo por **mil** tokens, que é a unidade que o pedido usa — a tabela é por milhão."""
    from pipeline.llm import PRECO_USD_POR_MTOK

    preco = PRECO_USD_POR_MTOK.get(m.modelo)
    if not preco:
        return "não tabelado neste projeto"
    entrada, saida = preco
    return f"US$ {entrada / 1000:.5f} entrada / US$ {saida / 1000:.5f} saída (por 1 mil)"


def imprimir(m: Medida) -> None:
    marca = "ok " if m.ok else "FALHOU"
    print(f"\n  [{marca}] IA {m.papel}: {m.provedor} · {m.modelo or '(sem modelo)'}")
    print(f"         endereço: {m.endereco}")
    print(f"         chave:    {m.chave_final if m.chave_presente else '(ausente)'}")
    if m.ok:
        raciocinio = f" ({m.tokens_de_raciocinio} de raciocínio)" if m.tokens_de_raciocinio else ""
        print(
            f"         resposta: {m.segundos:.2f} s · "
            f"{m.tokens_entrada}→{m.tokens_saida} tokens{raciocinio}"
        )
        rotulo = "estimado" if m.custo_e_estimativa else "informado pelo provedor"
        print(f"         custo:    US$ {m.custo_usd:.6f} nesta chamada ({rotulo})")
        print(f"         tabela:   {custo_por_mil(m)}")
        print(f"         JSON:     {'válido' if m.json_valido else 'NÃO veio estruturado'}")
    else:
        print(f"         motivo:   {m.motivo[:300]}")
    if m.modelos_disponiveis:
        print(f"         modelos que esta conta lista ({len(m.modelos_disponiveis)}):")
        for nome in m.modelos_disponiveis[:25]:
            print(f"           · {nome}")
        if len(m.modelos_disponiveis) > 25:
            print(f"           … e mais {len(m.modelos_disponiveis) - 25}")
    if m.limites:
        print(f"         limites:  {m.limites['fonte']} (lido em {m.limites['lido_em']})")
        print(f"                   {m.limites['observacao']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--so", choices=("principal", "alternativa"), help="testa só um")
    parser.add_argument(
        "--listar-modelos",
        action="store_true",
        help="lista os modelos da conta mesmo quando a chamada funciona",
    )
    args = parser.parse_args()

    carregar_env()
    # Este script **existe** para sair para a rede: `LLM_FAKE=0` aqui e só aqui, e
    # **depois** de carregar o `.env` — que traz `LLM_FAKE=1` e venceria a ordem inversa.
    os.environ["LLM_FAKE"] = "0"
    from pipeline import llm

    medidas: list[Medida] = []
    if args.so != "alternativa":
        medidas.append(medir("principal", listar=args.listar_modelos))
    if args.so != "principal":
        if llm.tem_alternativa():
            with llm.como_alternativa():
                medidas.append(medir("alternativa", listar=args.listar_modelos))
        else:
            medidas.append(
                Medida(papel="alternativa", motivo="não configurada (LLM_PROVIDER_ALT/_KEY_ALT)")
            )

    for m in medidas:
        imprimir(m)

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(
        json.dumps(
            {
                "rodado_em": datetime.now(UTC).isoformat(timespec="seconds"),
                "medidas": [asdict(m) for m in medidas],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n  escrito: {DESTINO.relative_to(RAIZ)}\n")
    return 0 if any(m.ok for m in medidas) else 1


if __name__ == "__main__":
    raise SystemExit(main())
