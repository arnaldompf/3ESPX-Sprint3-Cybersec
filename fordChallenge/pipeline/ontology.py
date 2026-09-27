"""Ontologia: do jeito que a fonte (ou o usuário) escreve para o campo canônico.

Existe porque sinônimo mata extração ingênua — lição registrada em `gabarito/README.md`:
o slide da Ford diz "3 modos de **volante**", a ficha pública diz "4 modos de **direção**",
e um agente genérico marcou `nao_encontrado` por procurar a palavra errada.

Duas resoluções distintas:

* :func:`resolve_attribute` — texto livre → **campo** canônico (`"modos de volante"` →
  `modos_direcao`), com rapidfuzz `token_set_ratio ≥ 85`.
* :func:`resolve_value` — token de valor → forma canônica dentro de um campo
  (`("modos_conducao", "esportivo")` → `"sport"`).

Sem match, devolve `None`: o atributo livre vira `extras[<slug>]` e é extraído com as
mesmas regras de status. Nunca se inventa um campo.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from pipeline import matching
from pipeline.schema import caminho_canonico, grupo_de

SEED_PATH = Path(__file__).resolve().parent / "synonyms_seed.json"

#: Limiar de aceitação do match difuso (docs/05: `token_set_ratio >= 85`).
LIMIAR_MATCH = 85.0


def normalize(texto: str) -> str:
    """NFKC, minúsculas, sem acento, espaços colapsados, pontuação de ligação suavizada.

    É a mesma normalização usada no grounding (docs/05) para que "o que casa aqui casa lá".
    """
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = t.replace("·", " ").replace("–", "-").replace("—", "-")
    t = re.sub(r"[“”\"'`´]", "", t)
    t = re.sub(r"[_/]+", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def normalizar_rotulo(texto: str) -> str:
    """Rótulo de linha de tabela, normalizado e **sem a unidade entre parênteses**.

    `"Potência (cv/rpm)"` -> `"potencia"`. A unidade é informação da regra de extração,
    não do nome do campo: separar as duas coisas é o que permite o mesmo rótulo casar em
    fichas que escrevem a unidade de formas diferentes.
    """
    return normalize(re.sub(r"\([^)]*\)", " ", str(texto)))


def slugify(texto: str) -> str:
    """`"Modos de Volante"` -> `"modos_de_volante"` (chave de `extras`)."""
    base = normalize(texto)
    base = re.sub(r"[^a-z0-9]+", "_", base)
    return base.strip("_") or "atributo"


@dataclass(frozen=True)
class EntradaCampo:
    campo_canonico: str
    grupo: str
    termos: tuple[str, ...]
    marca: str | None = None


@dataclass
class Ontologia:
    campos: list[EntradaCampo] = field(default_factory=list)
    valores: dict[str, dict[str, str]] = field(default_factory=dict)
    unidades: dict[str, dict[str, str]] = field(default_factory=dict)

    #: termo normalizado -> campo canônico (construído no carregamento)
    _indice: dict[str, str] = field(default_factory=dict, repr=False)

    def total_sinonimos(self) -> int:
        de_campo = sum(len(e.termos) for e in self.campos)
        de_valor = sum(len(m) for m in self.valores.values())
        return de_campo + de_valor


@lru_cache(maxsize=1)
def carregar(caminho: str | None = None) -> Ontologia:
    """Carrega e indexa `pipeline/synonyms_seed.json` (cacheado)."""
    dados = json.loads(Path(caminho or SEED_PATH).read_text(encoding="utf-8"))
    onto = Ontologia(
        valores={
            campo: {normalize(k): v for k, v in mapa.items()}
            for campo, mapa in dados.get("valores", {}).items()
        },
        unidades={
            dim: {normalize(k): v for k, v in mapa.items()}
            for dim, mapa in dados.get("unidades", {}).items()
        },
    )
    for bruto in dados.get("campos", []):
        entrada = EntradaCampo(
            campo_canonico=bruto["campo_canonico"],
            grupo=bruto.get("grupo") or (grupo_de(bruto["campo_canonico"]) or ""),
            termos=tuple(bruto.get("termos", ())),
            marca=bruto.get("marca"),
        )
        onto.campos.append(entrada)
        for termo in entrada.termos:
            onto._indice.setdefault(normalize(termo), entrada.campo_canonico)
        # o próprio nome canônico sempre resolve para si
        onto._indice.setdefault(normalize(entrada.campo_canonico), entrada.campo_canonico)
    return onto


#: Palavras que não carregam informação de campo em pt-BR. Sem removê-las, uma pergunta
#: longa ("quantos modos de direção tem?") passa a casar com qualquer termo curto.
#:
#: **Não** entram aqui os substantivos de veículo ("carro", "veículo", "picape",
#: "modelo"), e o motivo é concreto: "modos de direção **do veículo**" é sinônimo de
#: `modos_conducao`, enquanto "modos de direção" é `modos_direcao`. Removendo "veículo",
#: as duas formas colapsavam na mesma string, o termo passava a apontar para **dois**
#: campos, e o casamento devolvia `None` por ambiguidade — fazendo a pergunta mais óbvia
#: do domínio deixar de resolver. "modelo" é, além disso, nome de campo canônico.
STOPWORDS: frozenset[str] = frozenset(
    [
        "a",
        "as",
        "o",
        "os",
        "um",
        "uma",
        "uns",
        "umas",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "por",
        "para",
        "com",
        "e",
        "ou",
        "qual",
        "quais",
        "quanto",
        "quantos",
        "quanta",
        "quantas",
        "tem",
        "ter",
        "possui",
        "eh",
        "que",
        "se",
        "ao",
        "aos",
        "graus",
        "qtd",
        "quantidade",
        "valor",
        "sobre",
    ]
)

#: Um token da consulta conta como coberto quando algum token do candidato chega aqui.
#: Tolera erro de digitação ("volnte" x "volante" = 92).
LIMIAR_TOKEN = 85.0


def _tokens_significativos(texto: str) -> list[str]:
    tokens = [t for t in texto.split() if t not in STOPWORDS and len(t) > 1]
    return tokens or texto.split()


def _cobertura(alvo: list[str], referencia: list[str]) -> float:
    """Fração de `alvo` cujos tokens aparecem em `referencia` (com tolerância a typo)."""
    if not alvo:
        return 0.0
    cobertos = sum(
        1 for t in alvo if any(t == r or fuzz.ratio(t, r) >= LIMIAR_TOKEN for r in referencia)
    )
    return cobertos / len(alvo)


#: Cobertura mínima para **atributo livre do usuário**, mais alta que a do resolvedor de
#: versão (0,5). Motivo concreto: "ganchos de reboque" cobre 1 dos 2 tokens de
#: "capacidade de reboque" e, com 0,5, virava `capacidade_reboque_kg` — o usuário pergunta
#: pelo gancho e recebe a capacidade de tração. Aqui o custo do falso positivo é alto (o
#: atributo pedido vai para o campo errado) e o do falso negativo é baixo (vai para
#: `extras`, e é extraído com as mesmas regras). Então o limiar sobe.
COBERTURA_MINIMA_ATRIBUTO = 0.6


def resolve_attribute(
    texto: str,
    *,
    marca: str | None = None,
    limiar: float = LIMIAR_MATCH,
    cobertura_minima: float = COBERTURA_MINIMA_ATRIBUTO,
) -> tuple[str | None, float]:
    """Texto livre → `(campo_canonico | None, score 0–100)`.

    Match exato de termo devolve 100. Sem match aceitável, devolve `(None, score)` — o
    chamador manda o atributo para `extras[slug]`, sem inventar um campo canônico.

    A regra de escolha vive em :mod:`pipeline.matching`, compartilhada com o resolvedor de
    versão e com o recorte de coluna de tabela: ranqueia por **cobertura da consulta** e
    exige máximo único. `token_set_ratio` puro devolvia 100 para subconjunto de tokens, e
    por isso "quantos modos de direção tem" casava com `direcao` (chassi) em vez de
    `modos_direcao`.

    >>> resolve_attribute("modos de volante")[0]
    'modos_direcao'
    >>> resolve_attribute("aletas no volante")[0]
    'paddle_shifters'
    >>> resolve_attribute("quantos modos de direcao tem")[0]
    'modos_direcao'
    """
    onto = carregar()
    consulta = normalize(texto)
    if not consulta:
        return None, 0.0
    if consulta in onto._indice:
        return onto._indice[consulta], 100.0

    # A comparação é feita sobre os **tokens significativos**: sem remover
    # "de/do/quantos", uma pergunta longa casa com qualquer termo curto.
    #
    # E os candidatos são **deduplicados por forma**: a semente traz "modos de direcao" e
    # "modos de direção", que colapsam na mesma string de tokens significativos. Sem
    # deduplicar, `avaliar` via dois candidatos idênticos e devolvia **empate** — o que
    # transformava um acerto perfeito em "ambíguo". Duas formas do mesmo termo apontando
    # para o mesmo campo não são ambiguidade; duas apontando para campos diferentes são,
    # e essas continuam devolvendo `None`.
    alvo = " ".join(_tokens_significativos(consulta))
    por_forma: dict[str, set[str]] = {}
    for termo, campo_do_termo in onto._indice.items():
        forma = " ".join(_tokens_significativos(termo))
        if forma:
            por_forma.setdefault(forma, set()).add(campo_do_termo)

    formas = list(por_forma)
    resultado = matching.avaliar(alvo, formas, cobertura_minima=cobertura_minima, limiar=limiar)
    if resultado.vencedor is None:
        campos_empatados = {c for m in resultado.empatados for c in por_forma[formas[m.indice]]}
        if len(campos_empatados) != 1:
            return None, resultado.score
        return next(iter(campos_empatados)), resultado.score

    campos_do_vencedor = por_forma[formas[resultado.vencedor.indice]]
    if len(campos_do_vencedor) != 1:
        return None, resultado.vencedor.score
    campo = next(iter(campos_do_vencedor))
    if marca:
        for entrada in onto.campos:
            if entrada.campo_canonico == campo and entrada.marca and entrada.marca != marca:
                return None, resultado.score
    return campo, resultado.vencedor.score


def resolve_attribute_path(texto: str, **kw) -> tuple[str | None, float]:
    """Igual a :func:`resolve_attribute`, devolvendo o caminho `grupo.campo`."""
    campo, score = resolve_attribute(texto, **kw)
    return (caminho_canonico(campo) if campo else None), score


def resolve_value(campo: str, token: str) -> str | None:
    """Token de valor → forma canônica dentro do campo.

    `resolve_value("modos_conducao", "Esportivo")` -> `"sport"`.
    Sem mapeamento conhecido, devolve o token normalizado (não descarta informação).
    """
    onto = carregar()
    mapa = onto.valores.get(campo)
    alvo = normalize(token)
    if not alvo:
        return None
    if mapa and alvo in mapa:
        return mapa[alvo]
    # O hífen é separador tanto quanto o espaço na escrita das montadoras: "Rock Crawl",
    # "rock-crawl" e "rock_crawl" são o mesmo modo. `normalize` preserva o hífen de
    # propósito (o grounding precisa dele em faixas como "0-100"), então a equivalência é
    # resolvida **aqui**, onde o token já está sendo reduzido a uma forma canônica.
    sem_hifen = alvo.replace("-", " ").strip()
    if mapa and sem_hifen in mapa:
        return mapa[sem_hifen]
    if mapa:
        achado = process.extractOne(alvo, list(mapa.keys()), scorer=fuzz.token_set_ratio)
        if achado and achado[1] >= 92:
            return mapa[achado[0]]
    # O slug do token não mapeado sai com o **mesmo** separador em todos os casos. Sem
    # isto, "rock-crawl" (do deck interno) e "rock crawl" (do site) viravam dois tokens
    # distintos, e o Radar abria uma divergência que não existe — alerta falso é o jeito
    # mais rápido de fazer alguém parar de ler alertas.
    return sem_hifen.replace(" ", "_")


def valor_conhecido(campo: str, token: str) -> bool:
    """O token está no vocabulário deste campo, ou é slug de coisa que não conhecemos?

    `resolve_value` **nunca** descarta: token não mapeado sai como slug, de propósito
    (uma fonte pode nomear um modo novo antes de a ontologia saber dele). Mas quem
    precisa distinguir "isto é uma enumeração de modos" de "isto é uma frase sobre
    modos" precisa da pergunta separada — e é ela.
    """
    onto = carregar()
    mapa = onto.valores.get(campo)
    if not mapa:
        return False
    alvo = normalize(token)
    if not alvo:
        return False
    if alvo in mapa or alvo.replace("-", " ").strip() in mapa:
        return True
    achado = process.extractOne(alvo, list(mapa.keys()), scorer=fuzz.token_set_ratio)
    return bool(achado and achado[1] >= 92)


def canonicalizar_lista(campo: str, tokens: list[str]) -> list[str]:
    """Lista de modos/itens → tokens canônicos, sem duplicata, ordem preservada."""
    saida: list[str] = []
    for token in tokens:
        canon = resolve_value(campo, token)
        if canon and canon not in saida:
            saida.append(canon)
    return saida


def resolve_unit(dimensao: str, unidade: str) -> str | None:
    """`("torque", "kgf.m")` -> `"Nm"` (unidade canônica da dimensão)."""
    onto = carregar()
    return onto.unidades.get(dimensao, {}).get(normalize(unidade))


def total_sinonimos() -> int:
    """Quantos sinônimos a semente carrega (usado pelo seed do WP-03)."""
    return carregar().total_sinonimos()
