"""Provedor de LLM, abstraído sobre LiteLLM — e desligável.

Três modos, e o default é o mais seguro:

* **`LLM_FAKE=1` (default no `.env`, no CI e na demo)** — nenhuma chamada de rede e
  nenhum `import litellm`. As respostas vêm de `tests/fixtures/llm/*.json`, indexadas
  pelo conteúdo do pedido. Não havendo fixture, devolve **vazio com motivo**, nunca um
  valor inventado: o pipeline então marca os campos como `nao_encontrado`, que é a
  resposta honesta.
* **Provedor real via LiteLLM** — `LLM_FAKE=0` e uma chave no ambiente. O mesmo código
  serve Anthropic, OpenAI, Gemini, DeepSeek e Kimi (Moonshot AI): troca-se `LLM_PROVIDER`,
  `LLM_MODEL` e `LLM_API_KEY`, e nada mais.
* **Sem chave, sem modelo ou com provedor desconhecido** — o provedor diz isso em
  `motivo` e **não chama nada**. O pipeline segue e os campos ficam vazios; nada de
  "completar" com conhecimento do modelo de linguagem.

Ordem de precedência das variáveis (as novas ganham; as antigas continuam servindo, para
não invalidar `.env` nem documentação já escrita):

===============  ==========================================================
o que            de onde vem, na ordem
===============  ==========================================================
provedor         `LLM_PROVIDER` → `anthropic` (default histórico)
modelo pequeno   argumento `modelo=` → `LLM_MODEL` → `LLM_MODEL_SMALL` → default do provedor
modelo grande    `LLM_MODEL` → `LLM_MODEL_LARGE` → default do provedor
chave            `LLM_API_KEY` → chave nativa do provedor (`ANTHROPIC_API_KEY`,
                 `OPENAI_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`,
                 `DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY`/`KIMI_API_KEY`)
endereço         `LLM_API_BASE` → o default do LiteLLM
intervalo        `LLM_MIN_INTERVAL_S` → o do provedor (Kimi: 21 s) → 0
===============  ==========================================================

**`LLM_API_BASE` não é luxo de configuração.** A Moonshot AI tem dois endereços,
`api.moonshot.cn` (China) e `api.moonshot.ai` (global), e a chave de um não vale no outro.
O LiteLLM aponta para um deles. Sem a variável, a chamada volta com erro de autenticação —
o sintoma mais enganoso possível, porque parece chave errada e é endereço errado.

**O portão de vazão** (`_trinco`, `intervalo_minimo`, `TENTATIVAS_EM_429`) existe porque a
conta desta máquina é Tier0 da Moonshot: **concorrência 1, 3 requisições por minuto**. Uma
chamada de cada vez no processo, 21 s entre elas, e reapresentação com espera crescente em
429. Com uma exceção que importa: a Moonshot devolve **conta sem saldo também como 429**
(`exceeded_current_quota_error`), e esperar não resolve saldo — esse caso volta na hora,
com o motivo escrito. O portão vale só para chamada de verdade; com `cliente` injetado (os
testes) ele sai do caminho.

`LLM_MODEL` é uma variável só e por isso vale para **as duas** passadas: definindo-a, o
escalonamento do `docs/05` passa a usar o mesmo modelo nas duas. Quem quer dois tamanhos
deixa `LLM_MODEL` em branco e usa `LLM_MODEL_SMALL`/`LLM_MODEL_LARGE`.

**Default de modelo só existe para a Anthropic**, que é o provedor histórico do projeto.
Para os outros quatro, `LLM_MODEL` é obrigatório: adivinhar nome de modelo é a mesma
classe de erro que adivinhar valor de especificação, e aqui não se adivinha.

Duas notas de implementação que não são detalhe:

1. **O `import litellm` é preguiçoso**, dentro da função que chama de verdade. O LiteLLM
   busca o mapa de preços na internet ao ser importado se `LITELLM_LOCAL_MODEL_COST_MAP`
   não estiver ligado — então o import preguiçoso (mais o `setdefault` dessa variável) é o
   que mantém `LLM_FAKE=1` offline **por construção**, não por sorte de configuração.
2. **O `Uso` guarda o modelo nu** (`claude-haiku-4-5-20251001`), não o identificador do
   LiteLLM (`anthropic/claude-haiku-4-5-20251001`). O nome nu é a identidade da fixture e
   a chave da tabela de preço; prefixá-lo invalidaria todas as fixtures já gravadas.

Toda chamada registra modelo, tokens, custo e duração (`Uso`), que é o que alimenta
`cost_per_vehicle_brl` no eval. Quando o LiteLLM sabe o custo real da chamada, é ele que
vale; senão fica a estimativa de `PRECO_USD_POR_MTOK`, rotulada como estimativa. Com
`LLM_FAKE=1` o custo é **zero de verdade**, não uma estimativa de zero.

Na noite de 08/09/2026 não havia chave de LLM nesta máquina (DECISOES_NOITE.md D-07),
então o caminho exercitado é o de fixture, e o fast-path por regex
(`pipeline/extract/fastpath.py`) resolve a maior parte dos campos sem LLM.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline import deadline

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_LLM = ROOT / "tests" / "fixtures" / "llm"

#: Preço por milhão de tokens, em USD, para a estimativa de custo. São **estimativas**
#: e estão aqui explicitamente para poderem ser corrigidas; o eval rotula o número. Para
#: os provedores que o LiteLLM tarifa, o número real da chamada vem dele e vence esta
#: tabela (ver `Uso.custo_usd`).
PRECO_USD_POR_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-5": (3.0, 15.0),
    # Kimi na tabela pública da Moonshot AI (USD por milhão de tokens, cache miss), lida em
    # `platform.kimi.ai/docs/pricing/chat` em 13/09/2026: 0,95 de entrada, 4,00 de saída.
    # É **estimativa**, como as de cima, e por isso está aqui à vista: quando o LiteLLM
    # souber tarifar a chamada, o número dele vence (ver `Uso.custo_usd`).
    "kimi-k2.6": (0.95, 4.00),
    "kimi-k2.7-code": (0.95, 4.00),
}
#: Câmbio usado na estimativa. Também é estimativa, e também está visível.
USD_PARA_BRL = 5.40


class SemProvedor(RuntimeError):
    """Não há como chamar o LLM: sem chave e sem fixture."""


@dataclass(frozen=True)
class Provedor:
    """Um provedor de LLM como o projeto o enxerga, e como o LiteLLM o chama."""

    slug: str
    """Como se escreve em `LLM_PROVIDER`."""
    litellm: str
    """Prefixo do LiteLLM. Não é sempre igual ao nosso: Kimi é da Moonshot AI, e o
    LiteLLM chama o provedor de `moonshot`."""
    envs: tuple[str, ...]
    """Nomes de variável de chave nativos, na ordem de preferência."""
    modelo_pequeno: str = ""
    modelo_grande: str = ""
    """Vazio = `LLM_MODEL` é obrigatório. Só a Anthropic tem default, por ser o provedor
    com que o projeto nasceu; para os outros, adivinhar nome de modelo seria inventar."""
    intervalo_minimo_s: float = 0.0
    """Segundos de espera **entre** duas chamadas ao provedor. Zero = sem espera.

    Existe por causa do plano Tier0 da Moonshot AI, que dá **3 requisições por minuto** e
    **concorrência 1**. Sem a espera, a segunda chamada de qualquer extração toma 429, e
    a terceira também: o pipeline entregaria a ficha vazia e o motivo seria "limite do
    provedor", não "a fonte não diz". `LLM_MIN_INTERVAL_S` sobrepõe."""
    sem_raciocinio: dict[str, Any] | None = None
    """O que mandar em `extra_body` para o provedor **não raciocinar** antes de responder.

    Medido em 13/09/2026 com `kimi-k2.6`, que é modelo de raciocínio: pedindo 900 tokens
    para uma lista curta de versões, gastou **899 pensando** e não escreveu nada (29 s).
    Com `thinking: disabled` a mesma pergunta voltou em 1 s, com 14 tokens. Extração de
    ficha é tarefa de leitura, não de dedução: o raciocínio só encarece e atrasa. `None`
    para provedor que não tem a opção; `LLM_RACIOCINIO=1` religa em todos."""


#: Os cinco provedores previstos. Acrescentar um sexto é acrescentar uma linha — desde
#: que `litellm` seja um provedor que o LiteLLM realmente conheça (há teste para isso).
PROVEDORES: dict[str, Provedor] = {
    "anthropic": Provedor(
        "anthropic",
        "anthropic",
        ("ANTHROPIC_API_KEY",),
        modelo_pequeno="claude-haiku-4-5-20251001",
        modelo_grande="claude-sonnet-5",
    ),
    "deepseek": Provedor("deepseek", "deepseek", ("DEEPSEEK_API_KEY",)),
    # 6 s: **medido, não documentado.** O Google deixou de publicar a tabela de RPM da
    # camada gratuita — `ai.google.dev/gemini-api/docs/rate-limits` (lido em 13/09/2026)
    # remete ao painel do AI Studio, que é por projeto. O número aqui é o que esta conta
    # suportou sem 429; quem tiver outro tier ajusta por `LLM_MIN_INTERVAL_S`.
    #
    # **Sem isto, o Pesquisador ao vivo se autodestruía**: 178 chamadas em 13/09/2026,
    # 174 delas recusadas por vazão. E o prejuízo não foi só a chamada perdida — a espera
    # crescente entre as tentativas comeu o orçamento de tempo da pesquisa, e o veículo
    # parou com dois campos por "tempo". Provedor rápido sem trinco fica mais lento que
    # provedor lento com trinco.
    "gemini": Provedor(
        "gemini",
        "gemini",
        ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        intervalo_minimo_s=6.0,
    ),
    # 21 s: a conta desta máquina é Tier0 (3 req/min). 60/3 = 20, e o segundo a mais é
    # a folga para o relógio do servidor não discordar do nosso.
    "kimi": Provedor(
        "kimi",
        "moonshot",
        ("MOONSHOT_API_KEY", "KIMI_API_KEY"),
        intervalo_minimo_s=21.0,
        sem_raciocinio={"thinking": {"type": "disabled"}},
    ),
    "openai": Provedor("openai", "openai", ("OPENAI_API_KEY",)),
}

#: Apelidos aceitos em `LLM_PROVIDER`. Quem escreve `moonshot` quer Kimi; quem escreve
#: `google` quer Gemini. Errar o nome do provedor não devia custar uma sessão de debug.
APELIDOS: dict[str, str] = {
    "claude": "anthropic",
    "google": "gemini",
    "google-ai-studio": "gemini",
    "google_ai_studio": "gemini",
    "gpt": "openai",
    "moonshot": "kimi",
    "moonshotai": "kimi",
    "open-ai": "openai",
}


@dataclass
class Uso:
    """O custo de uma chamada, para o relatório do eval."""

    modelo: str
    provedor: str = ""
    """Quem atendeu de fato. Importa quando a alternativa entra: um relatório de custo que
    não diz de qual conta saiu o gasto manda conferir o extrato da conta errada."""
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_de_raciocinio: int = 0
    """Quantos dos tokens de saída o modelo gastou **pensando**, antes de escrever.

    Modelo de raciocínio cobra esses tokens como saída e não os mostra na resposta. Sem
    este número, uma extração que custou caro e voltou vazia parece defeito de prompt —
    e é orçamento curto. Zero em modelo que não raciocina, e em fixture."""
    duracao_s: float = 0.0
    de_fixture: bool = False
    custo_usd_informado: float | None = None
    """Custo que o **provedor/LiteLLM** informou para esta chamada. Quando existe, é fato
    e não estimativa; vence `PRECO_USD_POR_MTOK`."""

    @property
    def custo_usd(self) -> float:
        if self.de_fixture:
            return 0.0
        if self.custo_usd_informado is not None:
            return self.custo_usd_informado
        entrada, saida = PRECO_USD_POR_MTOK.get(self.modelo, (0.0, 0.0))
        return (self.tokens_entrada * entrada + self.tokens_saida * saida) / 1_000_000

    @property
    def custo_brl(self) -> float:
        return round(self.custo_usd * USD_PARA_BRL, 6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelo": self.modelo,
            "provedor": self.provedor,
            "tokens_entrada": self.tokens_entrada,
            "tokens_saida": self.tokens_saida,
            "tokens_de_raciocinio": self.tokens_de_raciocinio,
            "duracao_s": round(self.duracao_s, 3),
            "custo_brl": self.custo_brl,
            "de_fixture": self.de_fixture,
            "custo_e_estimativa": not self.de_fixture and self.custo_usd_informado is None,
        }


@dataclass
class Medicao:
    """Quanto um trecho de trabalho gastou de LLM. Só soma o que aconteceu de verdade.

    Existe porque `pipeline/eval/run.py` afirmava `custo_brl = 0.0` **sempre** — verdade
    com `LLM_FAKE=1`, e uma estimativa de zero com modelo real, que é exatamente o tipo de
    número que este projeto não publica. Sem um acumulador, medir o custo de um eval ao
    vivo exigiria somar à mão o que nenhuma camada guardava.
    """

    chamadas: int = 0
    falhas: int = 0
    """Chamadas em que o **provedor** não entregou: cota, saldo, rede, tempo esgotado.

    **Publicar uma medição sem isto foi um erro real:** uma coluna do comparador saiu com
    34 chamadas, zero token e R$ 0,00, e a tabela a apresentou como resultado. Eram 34
    respostas 429 de cota esgotada. Uma rodada que falhou tem de aparecer como falha, e
    não como número baixo — número baixo se compara, falha não."""
    sem_fixture: int = 0
    """Chamadas que não acharam fixture gravada, com `LLM_FAKE=1`.

    **Não é falha, e a distinção importa.** É o comportamento projetado: sem fixture o
    provedor devolve vazio com motivo e os campos ficam `nao_encontrado`, que é a resposta
    honesta. Misturar as duas contas marcaria o modo determinístico — o do CI e o da demo
    — como "não confiável", que é o oposto do que ele é.

    Como número, porém, ele diz muito: medido em 13/09/2026, **31 das 34** chamadas do
    eval não têm fixture. Os 104/109 vêm quase inteiros do fast-path por regex."""
    de_fixture: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_de_raciocinio: int = 0
    sem_saldo: int = 0
    """Chamadas recusadas por **saldo ou cota da conta** — nas duas contas, quando há duas.
    É o número que manda a pesquisa parar: esperar não resolve saldo."""
    teto_atingido: int = 0
    """Chamadas que **não saíram** porque o teto de gasto desta máquina já foi batido."""
    custo_usd: float = 0.0
    segundos: float = 0.0
    motivos_de_falha: list[str] = field(default_factory=list)
    """Os motivos distintos das falhas, na ordem em que apareceram (no máximo 5).

    Saber que 34 chamadas falharam é metade da informação; a outra metade é *"429, cota
    esgotada"*, que muda o que se faz a seguir — esperar, trocar de conta ou trocar de
    provedor. Um relatório que diz só o número manda investigar do zero."""
    por_provedor: dict[str, int] = field(default_factory=dict)
    """Quantas chamadas cada provedor atendeu. Com a IA alternativa ligada, o total pode
    sair de duas contas — e o relatório tem de dizer de quais."""

    @property
    def custo_brl(self) -> float:
        return round(self.custo_usd * USD_PARA_BRL, 6)

    @property
    def confiavel(self) -> bool:
        """Nenhuma chamada falhou por culpa do provedor. Medição com falha não compara."""
        return self.falhas == 0

    def somar(
        self,
        uso: Uso,
        *,
        ok: bool = True,
        motivo: str = "",
        sem_saldo: bool = False,
        teto: bool = False,
    ) -> None:
        self.chamadas += 1
        if sem_saldo:
            self.sem_saldo += 1
        if teto:
            self.teto_atingido += 1
        if ok:
            pass
        elif uso.de_fixture:
            self.sem_fixture += 1
        else:
            self.falhas += 1
            resumo = motivo.strip().splitlines()[0][:160] if motivo.strip() else ""
            if resumo and resumo not in self.motivos_de_falha:
                self.motivos_de_falha = [*self.motivos_de_falha[:4], resumo]
        if uso.de_fixture:
            self.de_fixture += 1
        self.tokens_entrada += uso.tokens_entrada
        self.tokens_saida += uso.tokens_saida
        self.tokens_de_raciocinio += uso.tokens_de_raciocinio
        self.custo_usd += uso.custo_usd
        self.segundos += uso.duracao_s
        chave = uso.provedor or ("fixture" if uso.de_fixture else "?")
        self.por_provedor[chave] = self.por_provedor.get(chave, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "chamadas": self.chamadas,
            "falhas": self.falhas,
            "sem_fixture": self.sem_fixture,
            "de_fixture": self.de_fixture,
            "tokens_entrada": self.tokens_entrada,
            "tokens_saida": self.tokens_saida,
            "tokens_de_raciocinio": self.tokens_de_raciocinio,
            "sem_saldo": self.sem_saldo,
            "teto_atingido": self.teto_atingido,
            "custo_usd": round(self.custo_usd, 6),
            "custo_brl": self.custo_brl,
            "segundos": round(self.segundos, 2),
            "motivos_de_falha": list(self.motivos_de_falha),
            "por_provedor": dict(self.por_provedor),
        }


#: Pilha de medições ativas. Pilha e não variável única para que um bloco aninhado
#: (o eval medindo o total, e dentro dele um veículo medindo o seu) some nos dois.
_medicoes: list[Medicao] = []


@contextmanager
def medindo() -> Iterator[Medicao]:
    """Acumula o `Uso` de **toda** chamada de LLM feita dentro do bloco.

        with llm.medindo() as m:
            rodar_o_que_for()
        print(m.custo_brl, m.chamadas)

    Chamada em fixture entra com custo zero e conta em `de_fixture`: saber que foram 40
    chamadas, todas gravadas, é diferente de saber que foram 40 chamadas.
    """
    medida = Medicao()
    _medicoes.append(medida)
    try:
        yield medida
    finally:
        # Por **identidade**, não por igualdade: `Medicao` é dataclass e duas medições
        # vazias são iguais entre si. Com `remove(medida)`, o bloco de dentro tirava o de
        # fora da pilha — e o de fora quebrava ao sair (achado em 13/09/2026, quando a
        # pesquisa passou a medir o total e cada documento ao mesmo tempo).
        for i in range(len(_medicoes) - 1, -1, -1):
            if _medicoes[i] is medida:
                del _medicoes[i]
                break


def _contabilizar(
    uso: Uso | None,
    *,
    ok: bool = True,
    motivo: str = "",
    sem_saldo: bool = False,
    teto: bool = False,
) -> None:
    """Soma um `Uso` a toda medição aberta **e ao livro-razão da máquina**.

    `chamadas` conta **tentativas de extração**, não requisições HTTP: a reapresentação em
    429 dentro de `_chamar_litellm` devolve um `Uso` só. É a unidade que interessa a quem
    lê o relatório — quantas vezes o pipeline pediu alguma coisa ao modelo.

    O livro-razão só recebe o que **custou**: fixture não entra, e uma chamada recusada
    antes de sair não entra. Chamada real que falhou entra, porque um modelo de raciocínio
    cobra os tokens que gastou pensando mesmo quando não escreve a resposta.
    """
    if uso is None:
        return
    for medida in _medicoes:
        medida.somar(uso, ok=ok, motivo=motivo, sem_saldo=sem_saldo, teto=teto)
    if not uso.de_fixture and not teto and (uso.tokens_entrada or uso.tokens_saida):
        _anotar_no_livro(uso)


# ------------------------------------------------------------------ livro-razão
#: Onde fica o gasto acumulado desta máquina. `LLM_LIVRO_RAZAO` sobrepõe (os testes
#: apontam para um arquivo descartável; sem isso, um teste com `cliente` dublado somaria
#: centavos imaginários ao livro de verdade).
LIVRO_RAZAO_PADRAO = ROOT / "data" / "llm-gasto.json"
_trinco_do_livro = threading.Lock()


def caminho_do_livro() -> Path:
    """O arquivo do livro-razão. Não cria nada."""
    do_ambiente = os.environ.get("LLM_LIVRO_RAZAO", "").strip()
    return Path(do_ambiente) if do_ambiente else LIVRO_RAZAO_PADRAO


def gasto_da_rodada() -> dict[str, Any]:
    """Quanto esta máquina já gastou de modelo, em USD, desde que o livro foi aberto.

    `{"desde": "AAAA-MM-DD", "usd": float, "chamadas": int}`. Sem livro, zeros — e nunca
    levanta: quem pergunta o gasto está no meio de uma pesquisa, e um livro corrompido não
    pode derrubá-la. Para zerar a rodada, apague o arquivo.
    """
    vazio = {"desde": "", "usd": 0.0, "chamadas": 0}
    arquivo = caminho_do_livro()
    if not arquivo.exists():
        return vazio
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        return {
            "desde": str(dados.get("desde") or ""),
            "usd": float(dados.get("usd") or 0.0),
            "chamadas": int(dados.get("chamadas") or 0),
        }
    except (OSError, ValueError, TypeError):
        return vazio


def _anotar_no_livro(uso: Uso) -> None:
    """Soma uma chamada real ao livro-razão. Falha de disco vira silêncio, nunca exceção."""
    with _trinco_do_livro:
        atual = gasto_da_rodada()
        novo = {
            "desde": atual["desde"] or time.strftime("%Y-%m-%d"),
            "usd": round(atual["usd"] + uso.custo_usd, 6),
            "chamadas": atual["chamadas"] + 1,
        }
        arquivo = caminho_do_livro()
        try:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(json.dumps(novo), encoding="utf-8", newline="\n")
        except OSError:  # pragma: no cover - disco cheio ou sem permissão
            pass


def teto_usd() -> float | None:
    """`LLM_TETO_USD`: o gasto acumulado a partir do qual **nenhuma** chamada sai.

    `None` quando não há teto ou o valor é ilegível — um teto ilegível que virasse zero
    desligaria o modelo em silêncio, e o sintoma seria "a fonte não diz".
    """
    bruto = os.environ.get("LLM_TETO_USD", "").strip()
    if not bruto:
        return None
    try:
        valor = float(bruto.replace(",", "."))
    except ValueError:
        return None
    return valor if valor > 0 else None


def raciocinio_ligado() -> bool:
    """`LLM_RACIOCINIO=1` religa o raciocínio nos provedores que permitem desligá-lo."""
    return os.environ.get("LLM_RACIOCINIO", "").strip() in {"1", "true", "True"}


@dataclass
class RespostaLLM:
    """O que o provedor devolveu, com o motivo sempre presente."""

    dados: dict[str, Any] = field(default_factory=dict)
    uso: Uso | None = None
    motivo: str = ""
    ok: bool = False
    sem_saldo: bool = False
    """A conta recusou por saldo ou cota. Quando há alternativa, só é verdade se **as duas**
    recusaram. Estruturado, e não lido do texto do motivo: o motivo da alternativa vem
    concatenado ao da principal, e procurar palavras ali confundiria os dois casos."""
    teto_atingido: bool = False
    """O teto de gasto desta máquina foi batido e a chamada **não saiu**."""

    @property
    def campos_preenchidos(self) -> list[str]:
        return [k for k, v in self.dados.items() if v is not None]


# ------------------------------------------------------------------------ ambiente
def modo_fake() -> bool:
    return os.environ.get("LLM_FAKE", "1").strip() in {"1", "true", "True"}


def _env(nome: str) -> str:
    return os.environ.get(nome, "").strip()


def provedor_atual() -> str:
    """O slug do provedor pedido, canonizado. Desconhecido volta como veio, para a mensagem."""
    bruto = _env("LLM_PROVIDER").lower()
    if not bruto:
        return "anthropic"
    return APELIDOS.get(bruto, bruto)


def provedor_config() -> Provedor | None:
    """A configuração do provedor atual, ou `None` se ninguém o conhece."""
    return PROVEDORES.get(provedor_atual())


def modelo_pequeno() -> str:
    """`LLM_MODEL` → `LLM_MODEL_SMALL` → default do provedor. Pode ser vazio."""
    config = provedor_config()
    return _env("LLM_MODEL") or _env("LLM_MODEL_SMALL") or (config.modelo_pequeno if config else "")


def modelo_grande() -> str:
    """`LLM_MODEL` → `LLM_MODEL_LARGE` → default do provedor. Pode ser vazio."""
    config = provedor_config()
    return _env("LLM_MODEL") or _env("LLM_MODEL_LARGE") or (config.modelo_grande if config else "")


def nomes_de_chave() -> tuple[str, ...]:
    """Os nomes de variável que servem de chave para o provedor atual, em ordem."""
    config = provedor_config()
    return ("LLM_API_KEY", *(config.envs if config else ()))


def chave_do_provedor() -> str:
    """O valor da chave, ou vazio. **Nunca** vai para log, mensagem ou `to_dict()`."""
    for nome in nomes_de_chave():
        if valor := _env(nome):
            return valor
    return ""


def tem_chave() -> bool:
    return bool(chave_do_provedor())


# ------------------------------------------------------------------------ vazão
#: Endereço da API do provedor, quando ele não é o default do LiteLLM.
#:
#: Existe por um caso concreto: a Moonshot AI tem **dois** endereços, `api.moonshot.cn`
#: (China) e `api.moonshot.ai` (global), e a chave de um não vale no outro. O LiteLLM
#: aponta para um deles; a conta desta máquina é do outro. Sem `LLM_API_BASE`, a chamada
#: sai e volta com erro de autenticação, que é o sintoma mais enganoso possível — parece
#: chave errada, e é endereço errado.
def api_base() -> str:
    """`LLM_API_BASE` do ambiente, ou vazio. Vazio = o default do LiteLLM."""
    return _env("LLM_API_BASE")


def intervalo_minimo() -> float:
    """Segundos entre duas chamadas ao provedor. `LLM_MIN_INTERVAL_S` sobrepõe o provedor."""
    do_ambiente = _env("LLM_MIN_INTERVAL_S")
    if do_ambiente:
        try:
            return max(0.0, float(do_ambiente))
        except ValueError:
            pass
    config = provedor_config()
    return config.intervalo_minimo_s if config else 0.0


# ------------------------------------------------------------------- IA alternativa
#: Os nomes que mudam entre a IA principal e a alternativa. Só estes cinco.
#:
#: A alternativa **não** é um segundo caminho de código: é o mesmo caminho com outra
#: configuração. Duplicar `extrair_json` para um segundo provedor criaria dois caminhos
#: que divergem — e o que diverge é justamente o que só roda quando o primeiro falhou,
#: isto é, o que ninguém testa.
PARES_ALTERNATIVOS: tuple[tuple[str, str], ...] = (
    ("LLM_PROVIDER", "LLM_PROVIDER_ALT"),
    ("LLM_MODEL", "LLM_MODEL_ALT"),
    ("LLM_API_KEY", "LLM_API_KEY_ALT"),
    ("LLM_API_BASE", "LLM_API_BASE_ALT"),
    ("LLM_MIN_INTERVAL_S", "LLM_MIN_INTERVAL_S_ALT"),
)


def tem_alternativa() -> bool:
    """Há um segundo provedor configurado? Exige provedor **e** chave."""
    return bool(_env("LLM_PROVIDER_ALT") and _env("LLM_API_KEY_ALT"))


@contextmanager
def como_alternativa() -> Iterator[None]:
    """Roda o bloco com a IA ALTERNATIVA no lugar da principal.

    Troca as cinco variáveis, executa e devolve o ambiente ao estado anterior — inclusive
    quando o bloco levanta. As variáveis do par principal que a alternativa não define são
    **apagadas**, e não herdadas: herdar `LLM_MODEL=kimi-k2.6` numa chamada ao Gemini
    pediria um modelo que não existe lá, e o erro diria "modelo não encontrado" em vez de
    "a alternativa não está configurada".

    Não é seguro entre threads — mexe em `os.environ`. O pipeline é sequencial e o worker
    processa um job por vez; o trinco de vazão já serializa a chamada de verdade.
    """
    nomes = [n for par in PARES_ALTERNATIVOS for n in par]
    anterior = {nome: os.environ.get(nome) for nome in nomes}
    try:
        for principal, alternativo in PARES_ALTERNATIVOS:
            valor = _env(alternativo)
            if valor:
                os.environ[principal] = valor
            else:
                os.environ.pop(principal, None)
            # **Dentro do bloco não há alternativa: a alternativa é quem está atendendo.**
            # Sem apagar, `tem_alternativa()` continuaria verdadeira ali dentro e o
            # fallback chamaria a si mesmo para sempre — a alternativa caindo para a
            # alternativa. Aqui o segundo provedor é o último, e falhar é o desfecho.
            os.environ.pop(alternativo, None)
        yield
    finally:
        for nome, valor in anterior.items():
            if valor is None:
                os.environ.pop(nome, None)
            else:
                os.environ[nome] = valor


#: Motivos de falha que a IA alternativa tem chance de resolver.
#:
#: A lista é curta de propósito. Cair para a alternativa em **qualquer** falha esconderia
#: erro de configuração: uma chave principal errada passaria despercebida enquanto a conta
#: alternativa paga a conta, e o defeito só apareceria quando as duas acabassem.
#:
#: O que está aqui é falha **do provedor**, não da nossa configuração: saldo, cota, vazão,
#: tempo esgotado, queda de conexão e indisponibilidade. Tudo o mais falha e diz por quê.
MARCAS_QUE_A_ALTERNATIVA_RESOLVE = (
    "timeout",
    "timed out",
    "connection",
    "service unavailable",
    "internal server error",
    "502",
    "503",
    "504",
    "overloaded",
)


def _vale_a_alternativa(motivo: str) -> bool:
    """Este fracasso é do tipo que um segundo provedor resolveria?"""
    baixo = motivo.lower()
    if _e_conta_sem_saldo(motivo) or _e_limite_de_vazao(motivo):
        return True
    return any(marca in baixo for marca in MARCAS_QUE_A_ALTERNATIVA_RESOLVE)


#: Quantas vezes reapresentar uma chamada barrada por limite de vazão.
TENTATIVAS_EM_429 = 4

#: Marcas de "sua conta acabou", que **não** melhoram com espera.
#:
#: A Moonshot devolve conta suspensa como **429** (`exceeded_current_quota_error`), o
#: mesmo código de "rápido demais". Tratar os dois igual faria o pipeline dormir minutos
#: por campo para receber o mesmo erro no fim — e foi exatamente o que a conta desta
#: máquina respondeu em 12/09/2026. Saldo não se resolve esperando.
MARCAS_DE_CONTA_SEM_SALDO = (
    "insufficient balance",
    "exceeded_current_quota",
    "insufficient_quota",
    "suspended",
    "billing",
)


def _e_conta_sem_saldo(mensagem: str) -> bool:
    baixo = mensagem.lower()
    return any(marca in baixo for marca in MARCAS_DE_CONTA_SEM_SALDO)


def _e_limite_de_vazao(mensagem: str) -> bool:
    baixo = mensagem.lower()
    return "429" in baixo or "rate limit" in baixo or "ratelimit" in baixo


#: O mesmo teste, com nome público: o Pesquisador precisa dele para decidir parar.
e_conta_sem_saldo = _e_conta_sem_saldo


#: **Uma chamada de cada vez, no processo inteiro.**
#:
#: O plano Tier0 da Moonshot AI dá concorrência 1: duas chamadas ao mesmo tempo fazem a
#: segunda voltar 429 mesmo respeitando o intervalo. O trinco é de módulo porque a conta
#: é do processo, não do objeto — dois extratores rodando no mesmo worker disputariam a
#: mesma cota.
_trinco = threading.Lock()
#: Instante da última chamada ao provedor, para o intervalo mínimo. Protegido por `_trinco`.
_ultima_chamada = 0.0


#: Quem quer saber quando o trinco dorme: a trilha da pesquisa, para a tela dizer
#: "aguardando 21 s pela cota do modelo" em vez de parecer travada. Pilha, como as
#: medições: um bloco aninhado avisa os dois.
_ouvintes_de_espera: list[Callable[[float, str], None]] = []


@contextmanager
def avisando_espera(ouvinte: Callable[[float, str], None]) -> Iterator[None]:
    """Chama `ouvinte(segundos, motivo)` **antes** de cada espera do trinco dentro do bloco.

    `motivo` é `"intervalo mínimo"` ou `"429"`. O ouvinte que levantar é engolido:
    avisar é cortesia, e a chamada ao modelo não pode morrer por causa dela.
    """
    _ouvintes_de_espera.append(ouvinte)
    try:
        yield
    finally:
        _ouvintes_de_espera.remove(ouvinte)


def _avisar_espera(segundos: float, motivo: str) -> None:
    for ouvinte in list(_ouvintes_de_espera):
        # Cortesia não derruba a chamada: um ouvinte quebrado é problema de quem escuta.
        with contextlib.suppress(Exception):
            ouvinte(segundos, motivo)


def _esperar_a_vez(intervalo: float) -> float:
    """Dorme o que falta do intervalo mínimo. Devolve quanto dormiu, para o log."""
    global _ultima_chamada
    if intervalo <= 0:
        _ultima_chamada = time.monotonic()
        return 0.0
    falta = intervalo - (time.monotonic() - _ultima_chamada)
    if falta > 0:
        _avisar_espera(falta, "intervalo mínimo")
        deadline.sleep(falta)
    _ultima_chamada = time.monotonic()
    return max(0.0, falta)


def identificador_litellm(modelo: str, provedor: str | None = None) -> str:
    """O identificador que o LiteLLM espera: `<provedor>/<modelo>`.

    Modelo que já traz barra passa intacto — quem escreveu
    `LLM_MODEL=openrouter/moonshotai/kimi-k2` sabe o que quer, e prefixar de novo
    quebraria o roteamento.
    """
    nu = modelo.strip()
    if not nu or "/" in nu:
        return nu
    config = PROVEDORES.get(provedor or provedor_atual())
    return f"{config.litellm}/{nu}" if config else nu


# ------------------------------------------------------------------------ fixtures
def chave_de_fixture(*, modelo: str, prompt: str, campos: list[str]) -> str:
    """Identidade determinística do pedido: modelo + campos + conteúdo do prompt.

    O prompt entra por **hash do conteúdo**, não por trecho: assim a fixture só é
    reutilizada quando o pedido é de fato o mesmo, e uma mudança no prompt não faz o CI
    passar com resposta de outro pedido.
    """
    material = json.dumps(
        {"modelo": modelo, "campos": sorted(campos), "prompt": prompt},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def caminho_de_fixture(chave: str) -> Path:
    return FIXTURES_LLM / f"{chave}.json"


def gravar_fixture(chave: str, dados: dict[str, Any], *, meta: dict | None = None) -> Path:
    """Grava uma fixture de resposta. Usado por `scripts/record_llm_fixtures.py`."""
    FIXTURES_LLM.mkdir(parents=True, exist_ok=True)
    alvo = caminho_de_fixture(chave)
    alvo.write_text(
        json.dumps(
            {"chave": chave, "meta": meta or {}, "dados": dados},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return alvo


def _ler_fixture(chave: str) -> dict[str, Any] | None:
    alvo = caminho_de_fixture(chave)
    if not alvo.exists():
        return None
    try:
        return json.loads(alvo.read_text(encoding="utf-8")).get("dados", {})
    except (OSError, json.JSONDecodeError):
        return None


def fixtures_disponiveis() -> list[str]:
    if not FIXTURES_LLM.is_dir():
        return []
    return sorted(p.stem for p in FIXTURES_LLM.glob("*.json"))


# ------------------------------------------------------------------------- chamada
def extrair_json(
    *,
    prompt: str,
    campos: list[str],
    modelo: str | None = None,
    sistema: str = "",
    max_tokens: int = 4096,
    cliente: Callable[..., Any] | None = None,
) -> RespostaLLM:
    """Pede ao modelo um JSON com os campos, ou devolve o motivo de não ter pedido.

    `cliente` é a costura de teste: qualquer chamável com a assinatura de
    `litellm.completion`. Passando um, nada do LiteLLM é importado — que é como os testes
    conferem provedor, modelo e parâmetros sem chave e sem rede.
    """
    escolhido = modelo or modelo_pequeno()
    chave = chave_de_fixture(modelo=escolhido, prompt=prompt, campos=campos)

    if modo_fake():
        dados = _ler_fixture(chave)
        if dados is None:
            vazio = Uso(escolhido, de_fixture=True)
            # Fixture ausente é **falha**, não custo zero: o pipeline segue com os campos
            # vazios, e sem isto a rodada pareceria uma medição barata.
            _contabilizar(vazio, ok=False, motivo=f"fixture {chave}.json ausente")
            return RespostaLLM(
                dados={},
                uso=vazio,
                motivo=(
                    f"LLM_FAKE=1 e não há fixture {chave}.json. Nenhum valor é inventado: "
                    "os campos ficam vazios. Para gravar, rode "
                    "`python scripts/record_llm_fixtures.py` com uma chave de LLM."
                ),
            )
        da_fixture = Uso(escolhido, de_fixture=True)
        _contabilizar(da_fixture)
        return RespostaLLM(
            dados=dados,
            uso=da_fixture,
            motivo=f"fixture {chave}.json",
            ok=True,
        )

    config = provedor_config()
    if config is None:
        return RespostaLLM(
            motivo=(
                f"LLM_PROVIDER={provedor_atual()!r} não é um provedor conhecido. "
                f"Aceitos: {', '.join(sorted(PROVEDORES))} "
                f"(apelidos: {', '.join(sorted(APELIDOS))}). Nenhuma chamada feita."
            ),
            uso=Uso(escolhido),
        )

    if not escolhido:
        return RespostaLLM(
            motivo=(
                f"o provedor {config.slug} não tem modelo padrão neste projeto: defina "
                "LLM_MODEL (ou LLM_MODEL_SMALL/LLM_MODEL_LARGE). Nome de modelo não se "
                "adivinha, do mesmo jeito que valor de especificação não se adivinha."
            ),
            uso=Uso(escolhido),
        )

    segredo = chave_do_provedor()
    if not segredo:
        return RespostaLLM(
            motivo=(
                f"{' / '.join(nomes_de_chave())} ausente e LLM_FAKE=0. Nenhuma chamada "
                f"feita e nenhum valor inventado. Defina a chave no .env (provedor "
                f"{config.slug}) ou volte para LLM_FAKE=1."
            ),
            uso=Uso(escolhido),
        )

    # **O teto de gasto é conferido antes de a chamada sair, e vale para as duas contas.**
    # Cair para a alternativa aqui gastaria de outra conta exatamente o que a regra existe
    # para impedir; por isso o retorno é direto, sem passar pelo fallback.
    teto = teto_usd()
    if teto is not None:
        gasto = gasto_da_rodada()
        if gasto["usd"] >= teto:
            recusada = RespostaLLM(
                uso=Uso(escolhido, provedor=config.slug),
                teto_atingido=True,
                motivo=(
                    f"teto de gasto de US$ {teto:.2f} atingido (gasto acumulado: "
                    f"US$ {gasto['usd']:.2f} em {gasto['chamadas']} chamada(s) desde "
                    f"{gasto['desde'] or 'o início'}). Nenhuma chamada saiu, nem para a "
                    f"IA alternativa. Para continuar, suba LLM_TETO_USD ou apague "
                    f"{caminho_do_livro().name}."
                ),
            )
            _contabilizar(recusada.uso, ok=False, motivo=recusada.motivo, teto=True)
            return recusada

    extra_body = config.sem_raciocinio if not raciocinio_ligado() else None
    resposta = _chamar_litellm(
        prompt=prompt,
        modelo=escolhido,
        identificador=identificador_litellm(escolhido, config.slug),
        segredo=segredo,
        sistema=sistema,
        max_tokens=max_tokens,
        cliente=cliente,
        extra_body=extra_body,
    )
    if resposta.uso is not None and not resposta.uso.provedor:
        resposta.uso.provedor = config.slug
    # Contabilizada **aqui**, antes da queda para a alternativa. A chamada alternativa é
    # uma chamada a `extrair_json` e se contabiliza sozinha; somar de novo no retorno
    # contaria o gasto dela duas vezes e o da principal, nenhuma.
    _contabilizar(
        resposta.uso, ok=resposta.ok, motivo=resposta.motivo, sem_saldo=resposta.sem_saldo
    )
    if resposta.ok or not tem_alternativa() or not _vale_a_alternativa(resposta.motivo):
        return resposta

    # **A segunda conta, e só nos casos em que ela resolve.** O motivo do primeiro
    # fracasso viaja junto: sem ele, um relatório diria "respondido pelo Gemini" sem
    # dizer que o Kimi ficou sem saldo — e a conta a recarregar seria a errada.
    primeiro = resposta.motivo
    with como_alternativa():
        alternativa = extrair_json(
            prompt=prompt,
            campos=campos,
            modelo=None,  # o modelo é o da alternativa, nunca o nome herdado do principal
            sistema=sistema,
            max_tokens=max_tokens,
            cliente=cliente,
        )
    alternativa.motivo = f"{alternativa.motivo} [IA alternativa; a principal falhou: {primeiro}]"
    # `sem_saldo` da alternativa já diz se **ela** recusou por saldo; a principal já tinha
    # recusado, ou não estaríamos aqui. Verdadeiro aqui = as duas contas acabaram.
    return alternativa


#: O que `import litellm` não pode mexer: a configuração que é nossa.
#:
#: Prefixos, não nomes: cobre `LLM_API_BASE`, `LLM_MODEL_ALT`, `SEARCH_PROVIDER` e o que
#: vier depois, sem precisar lembrar de acrescentar cada um aqui.
PREFIXOS_NOSSOS = ("LLM_", "SEARCH_", "RESEARCH_", "BENCHMARK_", "REPLAY_")


@contextmanager
def ambiente_protegido() -> Iterator[None]:
    """Roda o bloco garantindo que ele **não** altere a configuração do projeto.

    O que é nosso (`PREFIXOS_NOSSOS`) volta exatamente como estava: o que o bloco criou é
    apagado, o que ele mudou é restaurado. O que **não** é nosso fica — uma biblioteca tem
    direito de configurar a si mesma, e `LITELLM_*` é dela.
    """
    antes = {n: v for n, v in os.environ.items() if n.startswith(PREFIXOS_NOSSOS)}
    try:
        yield
    finally:
        for nome in [n for n in os.environ if n.startswith(PREFIXOS_NOSSOS)]:
            if nome not in antes:
                del os.environ[nome]
        for nome, valor in antes.items():
            if os.environ.get(nome) != valor:
                os.environ[nome] = valor


def _completion_padrao() -> Callable[..., Any]:
    """`litellm.completion`, importado só agora, sem rede e **sem mexer no ambiente**.

    Duas coisas acontecem no `import litellm`, e as duas são efeito colateral dele:

    1. ele **busca o mapa de preços no GitHub** se `LITELLM_LOCAL_MODEL_COST_MAP` não
       estiver ligado — daí o `setdefault`, que é o que mantém `LLM_FAKE=1` offline por
       construção e não por sorte;
    2. ele **chama `load_dotenv()`**, lendo o `.env` do diretório e injetando tudo em
       `os.environ`. Isso reconfigura o processo a partir de um arquivo em disco, no meio
       de uma chamada, sem ninguém pedir.

    O item 2 causou um defeito real, medido em 13/09/2026, e ele é do tipo pior: só
    aparece no dia em que o plano B é acionado. `como_alternativa()` apaga `LLM_API_BASE`
    ao entrar, justamente para a chamada ao Gemini não herdar o endereço da Moonshot. O
    `import litellm`, logo em seguida, **trazia o valor de volta do `.env`** — e a chamada
    ao Gemini saía para `https://api.moonshot.ai/v1/models/gemini-3.6-flash:generateContent`.
    A URL foi capturada; o erro que voltava era `url.not_found`, em chinês, e parecia
    modelo inexistente.

    A correção é restaurar o que é nosso. Importar uma biblioteca não pode reconfigurar o
    processo — e o que o LiteLLM define para si (`LITELLM_*`) fica, porque é dele.
    """
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    with ambiente_protegido():
        import litellm
    return litellm.completion


def _atributo(obj: Any, nome: str, default: Any = None) -> Any:
    """Lê `nome` de um objeto ou de um dict — o LiteLLM devolve objeto, o dublê devolve dict."""
    if isinstance(obj, dict):
        return obj.get(nome, default)
    return getattr(obj, nome, default)


def _suporta_json_object(identificador: str) -> bool:
    """O provedor aceita `response_format={"type": "json_object"}`?

    Quem responde é o LiteLLM, não nós — a lista de parâmetros por provedor muda, e
    chutar aqui viraria bug de um provedor só. Se o LiteLLM não estiver carregado (caso
    do cliente dublado), a resposta é "não": nunca vale importar o LiteLLM só para isto.
    """
    litellm = sys.modules.get("litellm")
    if litellm is None:
        return False
    try:
        suportados = litellm.get_supported_openai_params(model=identificador) or []
    except Exception:  # metadado ausente não é motivo para derrubar a chamada
        return False
    return "response_format" in suportados


def _tokens_de_raciocinio(consumo: Any) -> int:
    """Lê `usage.completion_tokens_details.reasoning_tokens`, quando o provedor manda.

    Cada provedor embrulha isso de um jeito e nem todos mandam; ausente vira zero, que é
    a verdade para um modelo que não raciocina.
    """
    detalhes = _atributo(consumo, "completion_tokens_details")
    if detalhes is None:
        return 0
    try:
        return int(_atributo(detalhes, "reasoning_tokens", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _custo_informado(resposta: Any) -> float | None:
    """O custo em USD que o LiteLLM calcula para esta resposta, se ele souber."""
    litellm = sys.modules.get("litellm")
    if litellm is None:
        return None
    try:
        valor = litellm.completion_cost(completion_response=resposta)
    except Exception:  # modelo sem tarifa conhecida cai na estimativa
        return None
    return float(valor) if valor is not None else None


def _sem_segredo(texto: str, segredo: str) -> str:
    """Nenhuma mensagem de erro carrega o valor da chave, nem quando o provedor a devolve."""
    return texto.replace(segredo, "***") if segredo else texto


def _chamar_litellm(
    *,
    prompt: str,
    modelo: str,
    identificador: str,
    segredo: str,
    sistema: str,
    max_tokens: int,
    cliente: Callable[..., Any] | None,
    extra_body: dict[str, Any] | None = None,
) -> RespostaLLM:
    inicio = time.perf_counter()
    if cliente is None:
        try:
            completion = _completion_padrao()
        except ImportError as exc:
            return RespostaLLM(
                motivo=(
                    f"pacote litellm ausente: {exc}. Instale com "
                    "`uv sync` (dependência declarada no pyproject.toml)."
                ),
                uso=Uso(modelo),
            )
    else:
        completion = cliente

    argumentos: dict[str, Any] = {
        "model": identificador,
        "messages": [
            {"role": "system", "content": sistema or "Responda apenas com JSON válido."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "api_key": segredo,
    }
    if endereco := api_base():
        argumentos["api_base"] = endereco
    if extra_body:
        # Parâmetro próprio do provedor (ex.: `thinking: disabled` da Moonshot). O LiteLLM
        # repassa `extra_body` intacto aos provedores compatíveis com a API da OpenAI.
        argumentos["extra_body"] = dict(extra_body)
    if _suporta_json_object(identificador):
        argumentos["response_format"] = {"type": "json_object"}

    # **O portão de vazão vale só para chamada de verdade.** Com `cliente` injetado a
    # chamada é um dublê de teste, e dormir 21 s ali transformaria a suíte em espera.
    if cliente is not None:
        return _interpretar(completion, argumentos, modelo, identificador, segredo, inicio)

    try:
        with deadline.locked(_trinco):
            intervalo = intervalo_minimo()
            for tentativa in range(1, TENTATIVAS_EM_429 + 1):
                _esperar_a_vez(intervalo)
                resultado = _interpretar(
                    completion, argumentos, modelo, identificador, segredo, inicio
                )
                if resultado.ok or not _e_limite_de_vazao(resultado.motivo):
                    return resultado
                if _e_conta_sem_saldo(resultado.motivo):
                    # 429 de saldo, não de pressa. Esperar não resolve, e insistir gastaria
                    # minutos por campo para receber a mesma resposta.
                    return resultado
                if tentativa == TENTATIVAS_EM_429:
                    return resultado
                # Espera crescente **além** do intervalo: se o provedor disse que estamos
                # rápidos demais, o intervalo configurado está curto para esta conta.
                espera = max(intervalo, 1.0) * tentativa
                _avisar_espera(espera, "429")
                deadline.sleep(espera)
            return resultado  # pragma: no cover - o laço sempre retorna antes
    except TimeoutError as exc:
        return RespostaLLM(motivo=str(exc), ok=False)


def _interpretar(
    completion: Callable[..., Any],
    argumentos: dict[str, Any],
    modelo: str,
    identificador: str,
    segredo: str,
    inicio: float,
) -> RespostaLLM:
    """Uma chamada e a leitura da resposta. Toda falha vira `motivo`, nunca exceção."""
    try:
        if deadline.remaining() is not None:
            argumentos["timeout"] = deadline.timeout(60.0)
            argumentos["num_retries"] = 0
        resposta = completion(**argumentos)
    except Exception as exc:  # a falha de rede vira motivo, não exceção que sobe
        motivo = _sem_segredo(f"{type(exc).__name__}: {exc}", segredo)
        return RespostaLLM(
            motivo=motivo,
            uso=Uso(modelo, duracao_s=time.perf_counter() - inicio),
            sem_saldo=_e_conta_sem_saldo(motivo),
        )

    escolhas = _atributo(resposta, "choices") or []
    mensagem = _atributo(escolhas[0], "message", {}) if escolhas else {}
    texto = str(_atributo(mensagem, "content") or "")
    consumo = _atributo(resposta, "usage") or {}
    uso = Uso(
        modelo=modelo,
        tokens_entrada=int(_atributo(consumo, "prompt_tokens", 0) or 0),
        tokens_saida=int(_atributo(consumo, "completion_tokens", 0) or 0),
        tokens_de_raciocinio=_tokens_de_raciocinio(consumo),
        duracao_s=time.perf_counter() - inicio,
        custo_usd_informado=_custo_informado(resposta),
    )

    # **O orçamento acabou antes da resposta.** Sem esta verificação, o caso volta como
    # "resposta não é JSON válido", que é o sintoma e manda depurar o prompt — quando o
    # problema é aritmética de orçamento.
    #
    # Medido em 13/09/2026 com `kimi-k2.6`, que é modelo de **raciocínio**: pedindo
    # `{"ok": true}` com `max_tokens=64`, ele gastou **63 tokens pensando**, terminou com
    # `finish_reason="length"` e devolveu `content` vazio. A resposta certa nunca começou
    # a ser escrita. Um modelo de raciocínio precisa de orçamento para pensar **e** para
    # responder, e quem paga a conta tem de saber qual dos dois faltou.
    parou_por = _atributo(escolhas[0], "finish_reason", "") if escolhas else ""

    def _sem_orcamento() -> RespostaLLM:
        gasto = uso.tokens_de_raciocinio
        detalhe = f" — {gasto} deles em raciocínio" if gasto else ""
        escreveu = " Escreveu parte da resposta e foi cortado." if texto.strip() else ""
        return RespostaLLM(
            uso=uso,
            motivo=(
                f"o modelo esgotou os {argumentos.get('max_tokens', '?')} tokens de saída "
                f"antes de terminar a resposta{detalhe}.{escreveu} Não é prompt ruim nem "
                f"modelo errado: é orçamento curto. Aumente `max_tokens`."
            ),
        )

    if not texto.strip() and parou_por == "length":
        return _sem_orcamento()

    try:
        dados = json.loads(_so_o_json(texto))
    except json.JSONDecodeError as exc:
        # **Cortado no meio conta como orçamento, não como JSON ruim.**
        #
        # A primeira versão desta guarda só olhava conteúdo **vazio**, e por isso pegava o
        # Kimi (que gasta tudo pensando e não chega a escrever) e deixava passar o Gemini,
        # que escreve algumas centenas de tokens de JSON e é cortado no meio. Os dois
        # ficaram sem resposta pelo mesmo motivo, e um deles recebia a mensagem errada —
        # "resposta não é JSON válido" manda depurar o prompt.
        if parou_por == "length":
            return _sem_orcamento()
        return RespostaLLM(uso=uso, motivo=f"resposta não é JSON válido: {exc}")
    if not isinstance(dados, dict):
        return RespostaLLM(uso=uso, motivo="resposta não é um objeto JSON")
    return RespostaLLM(dados=dados, uso=uso, motivo=f"modelo {identificador}", ok=True)


def _so_o_json(texto: str) -> str:
    """Extrai o objeto JSON de uma resposta que pode vir cercada de texto ou de ```json."""
    limpo = texto.strip()
    if limpo.startswith("```"):
        limpo = limpo.split("```")[1]
        limpo = limpo.removeprefix("json").strip()
    inicio, fim = limpo.find("{"), limpo.rfind("}")
    return limpo[inicio : fim + 1] if inicio != -1 and fim != -1 else limpo


# ------------------------------------------------------------------- registro no banco
def registrar_extracao(
    uso: Uso,
    *,
    job_id: str = "",
    version_id: str = "",
    prompt_versao: str = "",
) -> str | None:
    """Grava a chamada em `extractions`, se a camada de dados existir.

    Import tardio e falha silenciosa: o provedor tem de funcionar em teste de unidade
    sem banco. Quem precisa de garantia confere o retorno.
    """
    try:
        from api.app.db import session_scope
        from api.app.models import Extraction
    except ImportError:  # pragma: no cover - ambiente sem a WP-03
        return None
    with session_scope() as sessao:
        linha = Extraction(
            job_id=job_id or None,
            version_id=version_id or None,
            modelo_llm=uso.modelo,
            prompt_versao=prompt_versao or None,
            tokens_entrada=uso.tokens_entrada,
            tokens_saida=uso.tokens_saida,
            custo_usd=uso.custo_usd,
            latencia_ms=int(uso.duracao_s * 1000),
        )
        sessao.add(linha)
        sessao.flush()
        return linha.id
