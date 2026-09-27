"""Os provedores de busca — e a regra de evidência virando **assinatura de função**.

A lição mais cara dos quatro projetos estudados em 12/09/2026 veio de uma cicatriz do
gpt-researcher: eles decidiam se uma página tinha sido baixada com um heurístico
(`len(raw_content) > 100`), e **snippet longo era confundido com página baixada** — o
relatório saía com citação que não existia em lugar nenhum. Trocaram por uma flag
explícita; e um dos provedores esqueceu de declará-la, e só não quebrou por acaso.

**Aqui a regra não é uma flag: é o tipo.**

* `Achado.snippet` é o trecho que o buscador devolve. É **metadado de roteamento** — serve
  para decidir se vale gastar uma das doze páginas naquela URL, e para mais nada;
* o texto de evidência vem do `fetch`, que salva a página em disco e devolve o texto
  contra o qual o grounding confere.

Não há caminho no código em que um `Achado` vire evidência, porque ele não tem o campo que
o grounding lê. É a diferença entre pedir disciplina e não deixar a coisa acontecer.

**Sem fallback mudo.** No gpt-researcher, um nome de provedor inválido cai em Tavily **sem
avisar**. Aqui isso levanta exceção: uma rodada em que ninguém sabe qual buscador respondeu
é uma rodada que não se pode auditar, e o produto inteiro é auditoria.

**Brasil e português priorizados quando a API permite.** Tavily recebe idioma `pt` e
país `brazil`; Exa oferece `userLocation=BR`, sem filtro de idioma equivalente. Essas
preferências não substituem a conferência do mercado e da identidade no documento.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline import deadline
from pipeline.fetch.http import modo_replay
from pipeline.research import service_budget

#: Onde a busca guarda o que já perguntou, por `(consulta, dia)`.
#:
#: Mesmo molde de `fetch/http.py`: a demo roda o mesmo run várias vezes no ensaio, e pagar
#: a mesma busca cinco vezes seria desperdício — e ruído na conta de custo.
# `or`, e não o segundo argumento do `get`: uma variável que **existe vazia** devolve
# `""`, e `Path("")` é o diretório atual. Foi assim que o cache de busca gravou 37 arquivos
# na raiz do repositório em 13/09/2026, depois que o `.env` passou a declarar a variável.
CACHE = Path(os.environ.get("SEARCH_CACHE_DIR") or "data/search-cache")

#: Quantos resultados pedir por consulta.
#:
#: Dez. O funil do Perplexica pede muitos e corta para três depois do rerank; aqui o corte
#: quem faz é o classificador por tier, que é mais barato e mais explicável — e com doze
#: páginas de orçamento, pedir cinquenta seria comprar o que não cabe.
RESULTADOS_POR_CONSULTA = 10


class BuscaIndisponivel(RuntimeError):
    """O provedor não respondeu, ou não está configurado.

    Vira estado do run (`busca_falhou`, com o motivo), e os campos daquela família terminam
    `nao_encontrado`. **Nunca** um valor — é o antipadrão do "fallback silencioso" que os
    quatro projetos estudados praticam e que aqui é proibido.
    """


class RedeProibidaEmReplay(RuntimeError):
    """Tentativa de busca ao vivo com `REPLAY_MODE=1`.

    Espelha `fetch.http.RedeProibidaEmReplay` de propósito: em replay, **nada** sai para a
    rede — nem a coleta, nem a busca. Um teste que passasse porque foi à internet não
    prova o que diz provar.
    """


@dataclass(frozen=True)
class Achado:
    """Um resultado de busca. **Não** é evidência, e não tem como virar.

    `snippet` é o resumo que o buscador escreveu. Ele pode conter o número certo, e ainda
    assim não serve: não sabemos de que trecho da página ele saiu, se a página ainda diz
    aquilo, nem se é da versão pedida. Serve para **decidir o que baixar**.
    """

    url: str
    titulo: str
    snippet: str
    posicao: int
    provedor: str
    consulta: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "titulo": self.titulo,
            "snippet": self.snippet,
            "posicao": self.posicao,
            "provedor": self.provedor,
            "consulta": self.consulta,
        }


@dataclass
class Resposta:
    """O que uma consulta devolveu, com de onde veio e quanto custou."""

    consulta: str
    provedor: str
    achados: list[Achado] = field(default_factory=list)
    do_cache: bool = False
    erro: str = ""
    custo_previsto_usd: float = 0.0
    custo_real_usd: float | None = None
    provider_estimate_usd: float | None = None
    actual_basis: str = ""
    usage: dict[str, float] = field(default_factory=dict)
    orcamento_excedido: bool = False

    @property
    def ok(self) -> bool:
        return not self.erro


class SearchProvider:
    """A interface. Minúscula de propósito — é a do gpt-researcher, em Pydantic e async.

    Uma implementação precisa de um método só: `buscar`. O cache fica no wrapper;
    provedores também barram replay na chamada direta e reservam antes da rede.
    """

    nome: str = "abstrato"
    last_reservation: service_budget.Reservation | None = None

    def buscar(
        self,
        consulta: str,
        *,
        quantos: int = RESULTADOS_POR_CONSULTA,
        dominios: tuple[str, ...] = (),
    ) -> list[Achado]:
        """Os resultados da consulta. `dominios` restringe a varredura, quando o provedor
        souber fazer isso — quem não souber **ignora**, e a classificação filtra depois."""
        raise NotImplementedError


# --------------------------------------------------------------------- o registro
#: Os provedores conhecidos, por nome.
PROVEDORES: dict[str, type[SearchProvider]] = {}


def registrar(nome: str) -> Callable[[type[SearchProvider]], type[SearchProvider]]:
    """Registra um provedor pelo nome, **num lugar só**.

    No gpt-researcher, acrescentar um provedor custa três edições manuais em três arquivos
    — e é o tipo de coisa que se esquece pela metade.
    """

    def decorador(classe: type[SearchProvider]) -> type[SearchProvider]:
        PROVEDORES[nome] = classe
        classe.nome = nome
        return classe

    return decorador


def _chave(consulta: str, provedor: str, dia: str, dominios: tuple[str, ...] = ()) -> str:
    """A identidade de uma busca. **Os domínios entram**, e é obrigatório que entrem.

    A mesma frase restrita a `icarros.com.br` e sem restrição são duas buscas diferentes,
    com resultados diferentes. Compartilhar a chave faria a segunda ler do cache a
    resposta da primeira — e o replay gravaria uma só, achando que gravou as duas.
    """
    normalizada = re.sub(r"\s+", " ", consulta).strip().lower()
    restricao = ",".join(sorted(d.strip().lower() for d in dominios if d.strip()))
    bruto = f"{provedor}|{dia}|{normalizada}|{restricao}"
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:24]


def _chave_legada(consulta: str, provedor: str, dia: str) -> str:
    """Chave anterior a domínios fazerem parte da identidade da busca.

    As respostas reais em `tests/fixtures/search` foram gravadas com essa forma. O
    fallback precisa calculá-la de verdade; chamar `_chave(..., dominios=())` acrescenta
    um `|` final e aponta para outro arquivo — foi o bug que zerou toda a demo replay.
    """
    normalizada = re.sub(r"\s+", " ", consulta).strip().lower()
    bruto = f"{provedor}|{dia}|{normalizada}"
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:24]


def caminho_de_cache(
    consulta: str, provedor: str, dia: str | None = None, dominios: tuple[str, ...] = ()
) -> Path:
    dia = dia or datetime.now(UTC).strftime("%Y-%m-%d")
    perfil = provedor
    if provedor == "tavily" and _tavily_depth() != "basic":
        perfil += ":" + _tavily_depth()
    return CACHE / dia / f"{_chave(consulta, perfil, dia, dominios)}.json"


def persistent_cache_allowed(provedor: str) -> bool:
    """Brave exige direito contratual explícito para armazenamento dos resultados."""
    return provedor != "brave" or os.environ.get("SEARCH_BRAVE_STORAGE_RIGHTS") == "1"


def _le_cache(consulta: str, provedor: str, dominios: tuple[str, ...] = ()) -> list[Achado] | None:
    if not persistent_cache_allowed(provedor):
        return None
    caminho = caminho_de_cache(consulta, provedor, dominios=dominios)
    if not caminho.exists():
        return None
    try:
        cru = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return [
        Achado(
            url=a.get("url", ""),
            titulo=a.get("titulo", ""),
            snippet=a.get("snippet", ""),
            posicao=int(a.get("posicao", 0)),
            provedor=provedor,
            consulta=consulta,
        )
        for a in cru.get("achados", [])
    ]


def _grava_cache(
    consulta: str, provedor: str, achados: list[Achado], dominios: tuple[str, ...] = ()
) -> None:
    if not persistent_cache_allowed(provedor):
        return
    caminho = caminho_de_cache(consulta, provedor, dominios=dominios)
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(
            json.dumps(
                {
                    "consulta": consulta,
                    "provedor": provedor,
                    "dominios": list(dominios),
                    "gravado_em": datetime.now(UTC).isoformat(timespec="seconds"),
                    "achados": [a.to_dict() for a in achados],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        # Cache é conveniência. Não poder gravar não pode derrubar a pesquisa.
        pass


def provedor_configurado() -> str:
    """O nome do provedor pedido no ambiente. Vazio quando não há nenhum."""
    return (os.environ.get("SEARCH_PROVIDER") or "").strip().lower()


def montar(nome: str = "") -> SearchProvider:
    """O provedor pelo nome. Nome desconhecido **levanta** — nunca cai em outro.

    É o oposto do que o gpt-researcher faz, e de propósito: lá, um nome inválido cai em
    Tavily em silêncio. Uma rodada em que ninguém sabe qual buscador respondeu é uma rodada
    que não se pode auditar.
    """
    nome = (nome or provedor_configurado()).strip().lower()
    if not nome:
        raise BuscaIndisponivel(
            "nenhum provedor de busca configurado: defina SEARCH_PROVIDER no .env "
            f"(conhecidos: {', '.join(sorted(PROVEDORES))})"
        )
    if nome not in PROVEDORES:
        raise BuscaIndisponivel(
            f"provedor de busca desconhecido: {nome!r} "
            f"(conhecidos: {', '.join(sorted(PROVEDORES))})"
        )
    return PROVEDORES[nome]()


def buscar(
    consulta: str,
    *,
    provedor: str = "",
    quantos: int = RESULTADOS_POR_CONSULTA,
    dominios: tuple[str, ...] = (),
) -> Resposta:
    """Uma consulta, com cache por `(consulta, domínios, dia)` e replay respeitado.

    Em `REPLAY_MODE=1` só o cache responde: se a consulta não está gravada, **levanta**.
    Cair para a rede num teste faria o teste passar por motivo errado — e o projeto inteiro
    roda em replay.

    `dominios` restringe a busca aos sites que a sondagem aprovou (`fontes.yaml`). É o que
    faz a pesquisa procurar **onde tem ficha** em vez de varrer a web inteira: na S10, 15
    dos 20 resultados da primeira rodada saíram como "domínio não reconhecido".
    """
    nome = (provedor or provedor_configurado()).strip().lower()
    guardados = _le_cache(consulta, nome, dominios) if nome else None
    if guardados is not None:
        return Resposta(consulta=consulta, provedor=nome, achados=guardados, do_cache=True)

    if nome == "replay":
        # O provedor de fixtures **é** o caminho de replay: ele lê de disco e não tem
        # como ir à rede. Barrá-lo aqui tornaria o modo replay impossível de usar.
        achados = montar(nome).buscar(consulta, quantos=quantos, dominios=dominios)
        return Resposta(consulta=consulta, provedor=nome, achados=achados, do_cache=True)

    if modo_replay():
        raise RedeProibidaEmReplay(
            f"REPLAY_MODE=1 e a consulta não está no cache: {consulta!r} (provedor {nome!r}). "
            "Grave a fixture de busca antes, ou rode ao vivo."
        )

    backend = None
    try:
        backend = montar(nome)
        achados = backend.buscar(consulta, quantos=quantos, dominios=dominios)
    except service_budget.BudgetExceeded as exc:
        return Resposta(consulta=consulta, provedor=nome, erro=str(exc), orcamento_excedido=True)
    except BuscaIndisponivel as exc:
        return Resposta(consulta=consulta, provedor=nome, erro=str(exc))
    except Exception as exc:  # provedor fora do ar, timeout, resposta estranha
        # Exceções HTTP podem conter URL, consulta, corpo ou credenciais. Só registrar tipo.
        return Resposta(
            consulta=consulta,
            provedor=nome,
            erro=f"provedor indisponível ({type(exc).__name__})",
            **_cost_fields(backend),
        )

    _grava_cache(consulta, nome, achados, dominios)
    return Resposta(consulta=consulta, provedor=nome, achados=achados, **_cost_fields(backend))


def _cost_fields(backend: SearchProvider | None) -> dict:
    receipt = getattr(backend, "last_reservation", None)
    if receipt is None:
        return {}
    record = receipt.to_dict()
    return {
        "custo_previsto_usd": record["estimated_usd"],
        "custo_real_usd": record["actual_usd"],
        "provider_estimate_usd": record["provider_estimate_usd"],
        "actual_basis": record["actual_basis"],
        "usage": record["usage"],
    }


def _require_live() -> None:
    if modo_replay():
        raise RedeProibidaEmReplay("REPLAY_MODE=1 proíbe chamada direta ao provedor de busca")


def _tavily_depth() -> str:
    return (os.environ.get("SEARCH_TAVILY_DEPTH") or "basic").strip().lower()


# ----------------------------------------------------------------- implementações
#: Teto de domínios numa busca restrita. A Tavily aceita 300; a lista de `fontes.yaml` tem
#: uma dezena, e o teto existe para o dia em que ela crescer sem ninguém olhar.
MAXIMO_DE_DOMINIOS = 300

#: Onde ficam as respostas de busca gravadas para o replay.
FIXTURES = Path("tests/fixtures/search")


@registrar("replay")
class Replay(SearchProvider):
    """Lê respostas **gravadas** em `tests/fixtures/search`. Nunca toca a rede.

    É o provedor da demonstração e do `verify`: a apresentação de 15/09 não pode depender
    de o buscador estar de pé, de haver saldo na conta, nem de a internet do auditório
    funcionar. As fixtures foram gravadas com as URLs reais que os snapshots do
    repositório já contêm — então a pesquisa em replay percorre o mesmo caminho da
    pesquisa ao vivo, e lê as mesmas páginas.

    Consulta sem fixture devolve **lista vazia**, e não exceção: o run trata isso como
    "esta consulta não rendeu" e segue com as outras, que é o comportamento honesto com
    uma gravação parcial.
    """

    def buscar(
        self,
        consulta: str,
        *,
        quantos: int = RESULTADOS_POR_CONSULTA,
        dominios: tuple[str, ...] = (),
    ) -> list[Achado]:
        # A restrição entra na chave: a mesma frase com e sem `include_domains` são duas
        # buscas, e a gravação de uma não responde pela outra.
        caminho = FIXTURES / f"{_chave(consulta, 'replay', 'fixture', dominios)}.json"
        if not caminho.exists():
            # Gravação antiga, feita antes de a restrição existir: vale como resposta da
            # mesma consulta. Melhor reaproveitar do que devolver vazio e sumir com a
            # fonte que o replay já tem em disco.
            caminho = FIXTURES / f"{_chave_legada(consulta, 'replay', 'fixture')}.json"
        if not caminho.exists():
            return []
        try:
            cru = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [
            Achado(
                url=item.get("url", ""),
                titulo=item.get("titulo", ""),
                snippet=item.get("snippet", ""),
                posicao=int(item.get("posicao", i)),
                provedor="replay",
                consulta=consulta,
            )
            for i, item in enumerate(cru.get("achados", [])[:quantos])
        ]


@registrar("tavily")
class Tavily(SearchProvider):
    """Busca da Tavily. API de uma chamada, feita para agente — é a configurada no `.env`."""

    def buscar(
        self,
        consulta: str,
        *,
        quantos: int = RESULTADOS_POR_CONSULTA,
        dominios: tuple[str, ...] = (),
    ) -> list[Achado]:
        import httpx

        self.last_reservation = None
        _require_live()
        chave = os.environ.get("SEARCH_API_KEY", "").strip()
        if not chave:
            raise BuscaIndisponivel("SEARCH_API_KEY vazia para o provedor tavily")
        depth = _tavily_depth()
        if depth not in {"basic", "advanced"}:
            raise BuscaIndisponivel("SEARCH_TAVILY_DEPTH deve ser basic ou advanced")
        corpo: dict[str, object] = {
            "api_key": chave,
            "query": consulta,
            "max_results": quantos,
            "search_depth": depth,
            "auto_parameters": False,
            "include_usage": True,
            # Este conector descobre URLs. Quem baixa a página original é o fetch,
            # que preserva o documento; snippets não são prova de fatos.
            "include_answer": False,
            "country": "brazil",
            "language": "pt",
        }
        if dominios:
            # A API aceita até 300 domínios e **não cobra a mais** por isso (`basic` custa
            # 1 crédito com ou sem restrição). É o jeito barato de procurar só onde a
            # sondagem provou que tem ficha.
            corpo["include_domains"] = list(dominios[:MAXIMO_DE_DOMINIOS])
        timeout = deadline.timeout(15.0)
        self.last_reservation = service_budget.reserve(
            "tavily",
            "search",
            service_budget.TAVILY_SEARCH_ADVANCED_USD
            if depth == "advanced"
            else service_budget.TAVILY_SEARCH_BASIC_USD,
        )
        resposta = httpx.post(
            "https://api.tavily.com/search",
            json=corpo,
            timeout=timeout,
            headers={"User-Agent": os.environ.get("SPECRADAR_USER_AGENT", "SpecRadar/0.1")},
        )
        resposta.raise_for_status()
        dados = resposta.json()
        service_budget.settle_tavily(self.last_reservation, dados)
        return [
            Achado(
                url=item.get("url", ""),
                titulo=item.get("title", ""),
                snippet=item.get("content", "")[:500],
                posicao=i,
                provedor="tavily",
                consulta=consulta,
            )
            for i, item in enumerate(dados.get("results", []))
        ]


def com_site(consulta: str, dominios: tuple[str, ...]) -> str:
    """A consulta com `site:` — para os backends que não têm parâmetro de domínio.

    Brave, DuckDuckGo e SearXNG não aceitam uma lista como a Tavily; o que eles entendem é
    o operador na frase. **Um domínio só**, e não uma cadeia de `OR`: medido nos quatro
    motores estudados em 12/09/2026, `site:a OR site:b` devolve vazio com frequência — e
    uma consulta vazia é pior que uma consulta estreita. Os outros domínios continuam
    alcançáveis pelas outras consultas do plano.
    """
    if not dominios:
        return consulta
    return f"site:{dominios[0]} {consulta}".strip()


@registrar("brave")
class Brave(SearchProvider):
    def buscar(
        self,
        consulta: str,
        *,
        quantos: int = RESULTADOS_POR_CONSULTA,
        dominios: tuple[str, ...] = (),
    ) -> list[Achado]:
        import httpx

        self.last_reservation = None
        _require_live()
        chave = os.environ.get("SEARCH_API_KEY", "").strip()
        if not chave:
            raise BuscaIndisponivel("SEARCH_API_KEY vazia para o provedor brave")
        timeout = deadline.timeout(15.0)
        self.last_reservation = service_budget.reserve(
            "brave", "search", service_budget.BRAVE_SEARCH_USD
        )
        resposta = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={
                "q": com_site(consulta, dominios),
                "count": quantos,
                "country": "BR",
                "search_lang": "pt",
            },
            headers={"X-Subscription-Token": chave, "Accept": "application/json"},
            timeout=timeout,
        )
        resposta.raise_for_status()
        itens = resposta.json().get("web", {}).get("results", [])
        return [
            Achado(
                url=item.get("url", ""),
                titulo=item.get("title", ""),
                snippet=(item.get("description") or "")[:500],
                posicao=i,
                provedor="brave",
                consulta=consulta,
            )
            for i, item in enumerate(itens)
        ]


@registrar("exa")
class Exa(SearchProvider):
    """Descoberta opcional com até dez URLs; conteúdo original é coletado separadamente."""

    def buscar(
        self,
        consulta: str,
        *,
        quantos: int = RESULTADOS_POR_CONSULTA,
        dominios: tuple[str, ...] = (),
    ) -> list[Achado]:
        import httpx

        self.last_reservation = None
        _require_live()
        chave = os.environ.get("EXA_API_KEY", "").strip()
        if not chave and provedor_configurado() == "exa":
            chave = os.environ.get("SEARCH_API_KEY", "").strip()
        if not chave:
            raise BuscaIndisponivel(
                "EXA_API_KEY vazia; SEARCH_API_KEY só vale com SEARCH_PROVIDER=exa"
            )
        corpo = {
            "query": consulta,
            "type": "auto",
            "numResults": min(max(quantos, 1), 10),
            "userLocation": "BR",
        }
        if dominios:
            corpo["includeDomains"] = list(dominios[:MAXIMO_DE_DOMINIOS])
        timeout = deadline.timeout(15.0)
        self.last_reservation = service_budget.reserve(
            "exa", "search", service_budget.EXA_SEARCH_USD
        )
        resposta = httpx.post(
            "https://api.exa.ai/search",
            json=corpo,
            timeout=timeout,
            headers={"x-api-key": chave, "Content-Type": "application/json"},
        )
        resposta.raise_for_status()
        dados = resposta.json()
        costs = dados.get("costDollars")
        total = costs.get("total") if isinstance(costs, dict) else None
        if (
            isinstance(total, (int, float))
            and not isinstance(total, bool)
            and math.isfinite(total)
            and total >= 0
        ):
            self.last_reservation.note_estimate(total)
        return [
            Achado(
                url=item.get("url", ""),
                titulo=item.get("title", ""),
                snippet="",
                posicao=i,
                provedor="exa",
                consulta=consulta,
            )
            for i, item in enumerate(dados.get("results", [])[: corpo["numResults"]])
        ]


@registrar("duckduckgo")
class DuckDuckGo(SearchProvider):
    """Sem chave. É o provedor que faz a demo rodar na máquina de quem clonou o repositório."""

    def buscar(
        self,
        consulta: str,
        *,
        quantos: int = RESULTADOS_POR_CONSULTA,
        dominios: tuple[str, ...] = (),
    ) -> list[Achado]:
        _require_live()
        try:
            from ddgs import DDGS
        except ImportError as exc:  # pragma: no cover - depende de extra opcional
            raise BuscaIndisponivel("pacote `ddgs` não instalado (extra `research`)") from exc

        with DDGS() as ddgs:
            itens = list(
                ddgs.text(com_site(consulta, dominios), region="br-pt", max_results=quantos)
            )
        return [
            Achado(
                url=item.get("href", ""),
                titulo=item.get("title", ""),
                snippet=(item.get("body") or "")[:500],
                posicao=i,
                provedor="duckduckgo",
                consulta=consulta,
            )
            for i, item in enumerate(itens)
        ]


@registrar("searxng")
class SearxNG(SearchProvider):
    """Instância própria. `SEARXNG_URL` no ambiente.

    A interface é a mínima do Perplexica (`categories`, `engines`, `language`, `pageno`),
    com uma correção: **`language` é sempre passado**. Eles nunca passam, e para ficha
    técnica brasileira isso arrisca trazer o mercado errado.
    """

    def buscar(
        self,
        consulta: str,
        *,
        quantos: int = RESULTADOS_POR_CONSULTA,
        dominios: tuple[str, ...] = (),
    ) -> list[Achado]:
        import httpx

        _require_live()
        base = os.environ.get("SEARXNG_URL", "").strip().rstrip("/")
        if not base:
            raise BuscaIndisponivel("SEARXNG_URL vazia para o provedor searxng")
        resposta = httpx.get(
            f"{base}/search",
            params={
                "q": com_site(consulta, dominios),
                "format": "json",
                "language": "pt-BR",
                "pageno": 1,
            },
            timeout=deadline.timeout(15.0),
            headers={"User-Agent": os.environ.get("SPECRADAR_USER_AGENT", "SpecRadar/0.1")},
        )
        resposta.raise_for_status()
        itens = resposta.json().get("results", [])[:quantos]
        return [
            Achado(
                url=item.get("url", ""),
                titulo=item.get("title", ""),
                snippet=(item.get("content") or "")[:500],
                posicao=i,
                provedor="searxng",
                consulta=consulta,
            )
            for i, item in enumerate(itens)
        ]
