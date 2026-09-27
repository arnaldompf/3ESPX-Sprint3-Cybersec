"""O **tipo da afirmação**: a fonte declarou, mediu, ou apenas listou?

Nasceu de um defeito de tela achado em 12/09/2026. A ficha da Ranger Raptor mostra dois
valores para a aceleração 0–100 — 5,8 s e 6,5 s — e escrevia, ao lado, *"As fontes
divergem"*. Só que **a fonte é uma só**: a mesma matéria da Autoesporte traz o número que
a Ford declara e o que a revista cronometrou. Não são duas fontes discordando; é uma fonte
registrando duas coisas diferentes, e a diferença entre elas é justamente o assunto.

Chamar isso de "as fontes divergem" erra o fato e desperdiça o melhor argumento que a
página oferece a quem vende.

**A regra deste módulo, e o limite dela.** O tipo é derivado do **trecho verbatim já
localizado no texto salvo** — nunca de conhecimento do modelo, nunca de suposição sobre o
domínio. Se nenhum termo casar, o resultado é `None`, e `None` aqui é `desconhecido`:
estado de primeira classe, como em todo o resto do projeto. Rotular por padrão seria
inventar exatamente onde o produto promete não inventar.

Os termos não são hipótese: saíram dos quotes que o próprio pipeline extrai hoje —
`"A Ford declara que a Ranger Raptor vai de 0 a 100 km/h em 5,8 segundos"` e
`"6,5 s (teste Autoesporte)"`.
"""

from __future__ import annotations

import re
from typing import Literal

TipoDeAfirmacao = Literal["declarado", "medido", "listado"]

#: **A ordem importa.** "a Ford declara 5,8 s; medimos 6,5 s" numa frase só tem os dois
#: termos, e o que vale é o que qualifica o número daquela evidência. `medido` vem
#: primeiro porque é o mais específico: quem mede, publica a medição; quem repete o
#: declarado raramente diz "medimos".
REGRAS: tuple[tuple[TipoDeAfirmacao, re.Pattern[str]], ...] = (
    (
        "medido",
        re.compile(
            # `\btestes?\b` solto, e não `teste d[ao]`: a forma que a fonte usa ao lado
            # do número é "(teste Autoesporte)", sem preposição nenhuma.
            r"\bmedi(?:mos|do|da|u|ção|cao)\b|\btestes?\b|\bcronometr\w*|\bapurou\b"
            r"|\bregistrou\b|\baferi\w*",
            re.IGNORECASE,
        ),
    ),
    (
        "declarado",
        re.compile(
            r"\bdeclara(?:do|da|m|ção|cao)?\b|\bsegundo (?:a|o) (?:fabricante|montadora|marca)\b"
            r"|\binforma(?:do|da|ções|coes)?\b|\bpromete\b|\bde fábrica\b|\bde fabrica\b"
            r"|\bdados? oficia(?:l|is)\b|\bficha técnica\b|\bficha tecnica\b",
            re.IGNORECASE,
        ),
    ),
)


def classificar(quote: str, *, raw_value: str = "") -> tuple[TipoDeAfirmacao | None, str]:
    """`(tipo, termo_que_disparou)`. `(None, "")` quando nada casa — e isso é legítimo.

    Olha o `raw_value` **antes** do `quote`: ele costuma ser a forma curta que a fonte usou
    ao lado do número ("6,5 s (teste Autoesporte)"), e por isso é o sinal mais próximo do
    valor. O `quote` é a frase inteira, onde os dois termos podem conviver.

    >>> classificar("A Ford declara que vai de 0 a 100 em 5,8 segundos")
    ('declarado', 'declara')
    >>> classificar("", raw_value="6,5 s (teste Autoesporte)")
    ('medido', 'teste Autoesporte')
    >>> classificar("0-100 km/h: 5,8 s")
    (None, '')
    """
    for texto in (raw_value or "", quote or ""):
        if not texto.strip():
            continue
        for tipo, padrao in REGRAS:
            achado = padrao.search(texto)
            if achado:
                # O termo literal viaja junto: uma etiqueta sem o que a disparou é opinião
                # do sistema, e a regra do projeto é que toda inferência seja conferível.
                return tipo, _termo(texto, achado)
    return None, ""


def _termo(texto: str, achado: re.Match[str]) -> str:
    """O termo casado mais o que vem logo depois, até o fim da expressão entre parênteses.

    "teste" sozinho não diz nada a quem lê a nota; "teste Autoesporte" diz. O recorte para
    no primeiro delimitador para não arrastar a frase inteira para dentro do rótulo.
    """
    inicio = achado.start()
    resto = texto[inicio : inicio + 40]
    corte = re.split(r"[).,;\n]", resto, maxsplit=1)[0]
    return corte.strip() or achado.group(0)


#: Como cada tipo se lê na tela. É o texto que o vendedor mostra ao cliente.
ROTULO: dict[str, str] = {
    "declarado": "declarado",
    "medido": "medido",
    "listado": "listado",
}
