"""Grounding — o gate que impede valor sem evidência. É o coração do projeto.

Regra: um valor só entra na ficha se o `evidence_quote` que o acompanha for **localizado
no texto salvo da fonte**. Não localizou, o valor é **descartado** e o campo vira
`nao_verificado`. `grounding_rate` tem de ser 1,0 no eval; qualquer valor sem trecho
localizado é defeito, não arredondamento.

Três caminhos, nesta ordem, e a ordem importa:

1. **`exato`** — `normalize_texto` (NFKC, aspas e hífens unificados, minúsculas, espaços
   colapsados) e depois `in`. É o caminho preferido.
2. **`sem_acento`** — a mesma normalização, mais o dobramento de acento. É uma
   normalização **determinística**, não um limiar: ela aceita outra *grafia* do mesmo
   texto, nunca outro *valor*. Existe porque o caso é real — o gabarito cita
   `"Potencia 397cv"` e a página escreve `"Potência 397cv"` — e porque deixar isso para o
   caminho difuso é frágil: aquele par pontua 92,9, à beira do limiar de 92.
3. **`difuso`** — `partial_ratio ≥ 92` numa janela, para ruído de conversão e OCR.
   É o único caminho com limiar, e é o último.

`Localizacao.modo` viaja com a evidência: quem lê a ficha sabe por qual caminho aquele
trecho foi confirmado.

`pipeline/eval/compare.py` **reexporta** estas funções em vez de reimplementá-las. Se o
eval medisse um grounding diferente do que o pipeline aplica, a métrica não mediria o
produto.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

#: `partial_ratio` mínimo do caminho difuso (`docs/05`).
LIMIAR_DIFUSO = 92.0
#: Janela de busca do caminho difuso, em caracteres (`docs/05`).
JANELA_DIFUSA = 300

_ASPAS = re.compile(r"[‘’“”´`ʼ]")
_HIFENS = re.compile(r"[‐‑‒–—―−]")

MODO_EXATO = "exato"
MODO_SEM_ACENTO = "sem_acento"
MODO_DIFUSO = "difuso"
MODO_FALHOU = "falhou"
MODO_SEM_QUOTE = "sem_quote"
MODO_SEM_TEXTO = "sem_texto"

#: Modos que confirmam a evidência.
MODOS_OK = frozenset({MODO_EXATO, MODO_SEM_ACENTO, MODO_DIFUSO})


def normalize_texto(texto: str) -> str:
    """NFKC, aspas e hífens unificados, minúsculas, espaços colapsados (`docs/05`).

    Não remove acento: o caminho `exato` é o mais literal possível, e a diferença de
    acentuação é tratada no caminho seguinte, explicitamente.
    """
    t = unicodedata.normalize("NFKC", str(texto))
    t = _ASPAS.sub('"', t)
    t = _HIFENS.sub("-", t)
    t = t.lower()
    return re.sub(r"\s+", " ", t).strip()


def sem_acento(texto: str) -> str:
    """`normalize_texto` mais dobramento de acento."""
    base = normalize_texto(texto)
    decomposto = unicodedata.normalize("NFKD", base)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


@dataclass(frozen=True)
class Localizacao:
    """Onde e como o trecho foi encontrado."""

    ok: bool
    modo: str
    offset: int = -1
    """Posição no texto **normalizado**; -1 quando não localizado."""
    score: float = 0.0
    detalhe: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - conveniência
        return self.ok


def locate(quote: str | None, texto: str | None) -> Localizacao:
    """Localiza o trecho no texto. É a função que decide se um valor existe.

    >>> locate("Potencia 397cv", "Motor: Potência 397cv de forca").modo
    'sem_acento'
    >>> locate("Potencia 500cv", "Motor: Potência 397cv de forca").ok
    False
    """
    if not quote or not quote.strip():
        return Localizacao(False, MODO_SEM_QUOTE, detalhe="quote vazio")
    if not texto:
        return Localizacao(False, MODO_SEM_TEXTO, detalhe="nenhum texto salvo para conferir")

    q, t = normalize_texto(quote), normalize_texto(texto)
    posicao = t.find(q)
    if posicao != -1:
        return Localizacao(True, MODO_EXATO, posicao, 100.0)

    qs, ts = sem_acento(quote), sem_acento(texto)
    posicao = ts.find(qs)
    if posicao != -1:
        return Localizacao(
            True,
            MODO_SEM_ACENTO,
            posicao,
            100.0,
            "o trecho ocorre com acentuação diferente",
        )

    melhor_score, melhor_offset = _melhor_janela(qs, ts)
    if melhor_score >= LIMIAR_DIFUSO:
        faltando = _numeros_ausentes(qs, ts, melhor_offset)
        if faltando:
            # Guarda dura: o caminho difuso existe para ruído de conversão em **letras**,
            # nunca para números. Sem esta checagem, "Torque máximo de 900 Nm a 2.750 rpm
            # no eixo traseiro" casava com o texto que diz 583 Nm — 94 de similaridade,
            # acima do limiar de 92 — e um valor **errado** entrava na ficha com
            # evidência aparentemente válida. Número é exatamente o que os valores são.
            return Localizacao(
                False,
                MODO_FALHOU,
                -1,
                melhor_score,
                f"similaridade {melhor_score:.1f} passaria, mas o trecho cita "
                f"número(s) que não estão na fonte: {', '.join(sorted(faltando))}",
            )
        return Localizacao(
            True,
            MODO_DIFUSO,
            melhor_offset,
            melhor_score,
            f"similaridade {melhor_score:.1f} em janela de {JANELA_DIFUSA} caracteres",
        )
    return Localizacao(
        False,
        MODO_FALHOU,
        -1,
        melhor_score,
        f"melhor similaridade {melhor_score:.1f}, abaixo de {LIMIAR_DIFUSO:.0f}",
    )


#: Sequências numéricas do trecho (com separador pt-BR: `2.750`, `50,9`, `285/70`).
_NUMEROS = re.compile(r"\d[\d.,/]*")


def _numeros_ausentes(quote: str, texto: str, offset: int) -> set[str]:
    """Números do trecho que **não** aparecem na região casada do texto.

    A janela examinada é generosa (o dobro da janela difusa em volta do offset) para não
    rejeitar por causa de um número que ficou logo fora do recorte.
    """
    numeros = {n.rstrip(".,/") for n in _NUMEROS.findall(quote)}
    if not numeros:
        return set()
    inicio = max(0, (offset if offset >= 0 else 0) - JANELA_DIFUSA)
    janela = texto[inicio : inicio + len(quote) + 3 * JANELA_DIFUSA]
    return {n for n in numeros if n and n not in janela}


def _melhor_janela(quote: str, texto: str) -> tuple[float, int]:
    """Melhor `partial_ratio` em janelas deslizantes, e onde ele ocorreu.

    Janela em vez do texto inteiro porque `docs/05` pede janela, e porque num documento
    de 80 mil caracteres o `partial_ratio` global encontra semelhança em qualquer lugar —
    o que transformaria o caminho difuso num "sim" quase garantido.
    """
    if not quote or not texto:
        return 0.0, -1
    largura = len(quote) + JANELA_DIFUSA
    if len(texto) <= largura:
        return float(fuzz.partial_ratio(quote, texto)), 0
    passo = max(largura // 2, 1)
    melhor, onde = 0.0, -1
    for inicio in range(0, len(texto) - 1, passo):
        janela = texto[inicio : inicio + largura]
        score = float(fuzz.partial_ratio(quote, janela))
        if score > melhor:
            melhor, onde = score, inicio
            if melhor >= 100.0:
                break
    return melhor, onde


def grounding_ok(quote: str | None, texto: str | None) -> bool:
    """Atalho booleano de :func:`locate`."""
    return locate(quote, texto).ok


def localizar_em_varios(quote: str | None, textos: dict[str, str]) -> tuple[str, Localizacao]:
    """Procura o trecho em várias fontes e devolve `(source_id, localização)`.

    Prefere o caminho mais literal: uma fonte que confirma por `exato` ganha de outra que
    confirma por `difuso`, porque a evidência mais literal é a mais forte.
    """
    ordem = {MODO_EXATO: 0, MODO_SEM_ACENTO: 1, MODO_DIFUSO: 2}
    melhor_id, melhor = "", Localizacao(False, MODO_SEM_TEXTO)
    for source_id, texto in textos.items():
        achado = locate(quote, texto)
        if not achado.ok:
            if not melhor.ok and achado.score > melhor.score:
                melhor_id, melhor = source_id, achado
            continue
        if not melhor.ok or ordem[achado.modo] < ordem[melhor.modo]:
            melhor_id, melhor = source_id, achado
            if achado.modo == MODO_EXATO:
                break
    return melhor_id, melhor


# ----------------------------------------------------------------------- contador
_falhas: dict[str, int] = {"total": 0}


def registrar_falha(campo: str = "") -> None:
    """Incrementa `grounding_fail_total` (métrica de `specs/WP-11.md`)."""
    _falhas["total"] += 1
    if campo:
        _falhas[campo] = _falhas.get(campo, 0) + 1


def grounding_fail_total() -> int:
    return _falhas["total"]


def falhas_por_campo() -> dict[str, int]:
    return {k: v for k, v in _falhas.items() if k != "total"}


def zerar_falhas() -> None:
    _falhas.clear()
    _falhas["total"] = 0
