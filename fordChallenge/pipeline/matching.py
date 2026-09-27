"""Casamento de nome de versão — a regra, num lugar só.

Este módulo existe porque o mesmo defeito apareceu **três vezes** em lugares diferentes:
na ontologia (WP-01), no resolvedor de versão (WP-07) e no recorte de coluna de tabela
(WP-09). A causa é sempre a mesma: `rapidfuzz.token_set_ratio` devolve **100** quando um
conjunto de tokens é subconjunto do outro, em qualquer direção. Consequências reais:

* `"quantos modos de direção tem"` casava com `direcao` (chassi) em vez de `modos_direcao`;
* `"SRX Plus AT"` empatava com `"SRX AT"` e virava `ambigua`;
* `"SRX Plus AT (Cabine Dupla)"` — o nome que o **gabarito** usa — não casava com a coluna
  `"SRX Plus AT"` da tabela, porque a página `hilux-cabine-dupla` não repete a carroceria
  no nome de cada versão.

A regra que resolve os três:

1. Nome idêntico após normalização ganha sozinho.
2. Senão, mede-se a **cobertura** — que fração dos tokens do pedido aparece no candidato,
   tolerando erro de digitação por token.
3. Vence quem tem a **maior** cobertura, e só se for **único** nesse máximo. Empate é
   ambiguidade, e ambiguidade se devolve como tal: o sistema não escolhe em silêncio.

`token_set_ratio` continua sendo usado, mas como **portão** e como critério de desempate
secundário — nunca como o ranqueador principal.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

#: Similaridade mínima entre dois tokens para tratá-los como o mesmo ("volnte" ≈ "volante").
LIMIAR_TOKEN = 85.0
#: Fração mínima dos tokens do pedido que o candidato precisa cobrir.
COBERTURA_MINIMA = 0.5
#: `token_set_ratio` mínimo (o portão de `docs/05`).
LIMIAR_MATCH = 85.0


def cobertura(tokens_consulta: list[str], tokens_candidato: list[str]) -> float:
    """Fração dos tokens do pedido presentes no candidato, com tolerância a typo."""
    if not tokens_consulta:
        return 0.0
    cobertos = sum(
        1
        for t in tokens_consulta
        if any(t == c or fuzz.ratio(t, c) >= LIMIAR_TOKEN for c in tokens_candidato)
    )
    return cobertos / len(tokens_consulta)


@dataclass(frozen=True)
class Match:
    """Um candidato avaliado."""

    indice: int
    """Posição do candidato na lista recebida."""
    valor: str
    cobertura: float
    score: float
    """`token_set_ratio` entre pedido e candidato, 0–100."""
    exato: bool = False


@dataclass(frozen=True)
class Resultado:
    """Resultado do casamento: um vencedor, vários empatados, ou nenhum."""

    vencedor: Match | None
    empatados: tuple[Match, ...] = ()
    todos: tuple[Match, ...] = ()

    @property
    def ambiguo(self) -> bool:
        return self.vencedor is None and len(self.empatados) > 1

    @property
    def score(self) -> float:
        if self.vencedor:
            return self.vencedor.score
        return self.empatados[0].score if self.empatados else 0.0


def avaliar(
    alvo_normalizado: str,
    candidatos_normalizados: list[str],
    *,
    cobertura_minima: float = COBERTURA_MINIMA,
    limiar: float = LIMIAR_MATCH,
) -> Resultado:
    """Aplica a regra de casamento sobre nomes **já normalizados**.

    A normalização fica com o chamador de propósito: `pipeline.connectors.base` remove
    `at/mt/4x4` (que não distinguem versão) e `pipeline.ontology` remove acento e
    pontuação. Cada domínio sabe o que é ruído no seu vocabulário; a **regra de escolha**
    é a mesma, e é esta.
    """
    if not alvo_normalizado:
        return Resultado(None)

    tokens_alvo = alvo_normalizado.split()
    avaliados: list[Match] = []
    for i, candidato in enumerate(candidatos_normalizados):
        if not candidato:
            continue
        avaliados.append(
            Match(
                indice=i,
                valor=candidato,
                cobertura=cobertura(tokens_alvo, candidato.split()),
                score=float(fuzz.token_set_ratio(alvo_normalizado, candidato)),
                exato=candidato == alvo_normalizado,
            )
        )
    if not avaliados:
        return Resultado(None)

    exatos = [m for m in avaliados if m.exato]
    if len(exatos) == 1:
        return Resultado(exatos[0], (), tuple(avaliados))
    if len(exatos) > 1:
        return Resultado(None, tuple(exatos), tuple(avaliados))

    melhor_cobertura = max(m.cobertura for m in avaliados)
    if melhor_cobertura < cobertura_minima:
        return Resultado(None, (), tuple(avaliados))

    no_topo = [m for m in avaliados if m.cobertura >= melhor_cobertura - 1e-9]
    no_topo.sort(key=lambda m: (-m.score, m.valor))
    if no_topo[0].score < limiar:
        return Resultado(None, (), tuple(avaliados))

    melhor_score = no_topo[0].score
    empatados = [m for m in no_topo if m.score >= melhor_score - 1e-9]
    if len(empatados) > 1:
        return Resultado(None, tuple(empatados), tuple(avaliados))
    return Resultado(empatados[0], (), tuple(avaliados))
