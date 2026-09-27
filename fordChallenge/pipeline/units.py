"""Conversão de unidades e parsing de números pt-BR.

Fatores em `docs/03` (Grupos e campos). Regra do projeto: o valor canônico vai para o
campo, o `raw_value` fica **sempre** preservado na evidência — a conversão nunca apaga
o que a fonte disse.

Os sinônimos de unidade vieram de erro real de extração ingênua: `kgfm`, `kgf.m` e
`mkgf` são a mesma coisa, e `hp` não é `cv`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ---------------------------------------------------------------------------- fatores
#: Multiplicadores para chegar a **cv** (docs/03).
FATOR_POTENCIA: dict[str, float] = {
    "cv": 1.0,
    "ps": 1.0,  # Pferdestärke == cv métrico
    "hp": 1.0139,  # hp (mecânico) -> cv métrico
    "bhp": 1.0139,
    "kw": 1.3596,
}

#: Multiplicadores para chegar a **Nm** (docs/03).
FATOR_TORQUE: dict[str, float] = {
    "nm": 1.0,
    "n.m": 1.0,
    "n·m": 1.0,
    "kgfm": 9.80665,
    "kgf.m": 9.80665,
    "kgf·m": 9.80665,
    "kgm": 9.80665,
    "mkgf": 9.80665,
    "m.kgf": 9.80665,
    "lb-ft": 1.3558,
    "lbft": 1.3558,
    "lb.ft": 1.3558,
    "lbf.ft": 1.3558,
}

#: 1 polegada em mm, para dimensões declaradas em pol.
MM_POR_POLEGADA = 25.4


class UnidadeDesconhecida(ValueError):
    """A unidade recebida não está na tabela de conversão."""


def _slug_unidade(unidade: str) -> str:
    """`"KGF.m "` -> `"kgf.m"`; remove acento e espaço, mantém `.` `·` `-`.

    O docstring dizia "remove acento" desde sempre, e a função não removia: fazia `NFKC`,
    que **compõe** o acento em vez de separá-lo. Passava despercebido porque nenhuma
    unidade da tabela tinha acento — até a página escrever `"centímetros"` por extenso.
    A correção é `NFKD` e descartar as marcas, que é o que a frase já prometia.
    """
    texto = unicodedata.normalize("NFKD", unidade).strip().lower()
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.replace(" ", "").replace("_", "")
    return texto


# ------------------------------------------------------------------- números pt-BR
#: A ordem das alternativas **é a regra**, não estilo: alternância em regex é preguiçosa
#: da esquerda para a direita, então a primeira que casa vence. Numa versão anterior o
#: decimal com ponto vinha por último, depois de `-?\d+(?:,\d+)?` — e como aquela
#: alternativa casa "5" sozinho em "5.8", o ramo do ponto **nunca executava**: "5.8
#: segundos" virava `5.0`, calado e com confiança total. Por isso o decimal com vírgula
#: agora exige a vírgula (`(?:,\d+)`, sem o `?`) e o inteiro puro é o último recurso.
_NUM_PTBR = re.compile(
    # O `(?!\d)` fecha a mesma armadilha pelo outro lado: sem ele, "12.3456" casaria como
    # milhar "12.345" e o `6` sumiria — 12345 em vez de 12,3456.
    r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?!\d)"  # 1.234 · 1.234.567 · 1.234,5 (milhar pt-BR)
    r"|-?\d+,\d+"  # 5,8 (decimal pt-BR)
    r"|-?\d+\.\d+"  # 5.8 (decimal em estilo inglês, comum em texto de marketing)
    r"|-?\d+"  # 397
)


def parse_number_ptbr(texto: str | float | int) -> float:
    """Lê número no formato brasileiro: `"1.234,5"` -> `1234.5`.

    Aceita também o formato inglês quando não houver ambiguidade (`"1234.5"` -> `1234.5`)
    e sufixos/prefixos de unidade (`"397 cv"` -> `397.0`).

    **Ponto com uma ou duas casas é decimal, não milhar.** "5.8" como milhar não seria
    nenhum número que uma fonte queira dizer (58? 5800?), enquanto como decimal é
    exatamente o que "5.8 segundos" significa. Truncar para `5.0` seria pior que recusar:
    devolve um número errado com a mesma confiança de um certo.
    """
    if isinstance(texto, (int, float)):
        return float(texto)
    bruto = unicodedata.normalize("NFKC", str(texto)).strip()
    achado = _NUM_PTBR.search(bruto.replace(" ", ""))
    if not achado:
        raise ValueError(f"nenhum número em {texto!r}")
    num = achado.group(0)
    if "," in num:
        # pt-BR: ponto é milhar, vírgula é decimal
        num = num.replace(".", "").replace(",", ".")
    elif num.count(".") > 1:
        # 1.234.567 -> milhares
        num = num.replace(".", "")
    elif "." in num:
        inteiro, _, decimal = num.partition(".")
        # "1.234" com exatamente 3 casas e parte inteira curta é milhar em pt-BR
        if len(decimal) == 3 and len(inteiro) <= 3:
            num = inteiro + decimal
    return float(num)


def to_cv(value: str | float | int, unit: str = "cv") -> int:
    """Potência em **cv**, arredondada (tolerância do eval é ±1 cv).

    `to_cv(258, "hp")` -> 262 · `to_cv("190 kW", "kw")` -> 258
    """
    return round(to_cv_exact(value, unit))


def to_cv_exact(value: str | float | int, unit: str = "cv") -> float:
    """Igual a :func:`to_cv`, sem arredondar (para auditoria)."""
    u = _slug_unidade(unit)
    if u not in FATOR_POTENCIA:
        raise UnidadeDesconhecida(f"unidade de potência desconhecida: {unit!r}")
    return parse_number_ptbr(value) * FATOR_POTENCIA[u]


def to_nm(value: str | float | int, unit: str = "Nm") -> int:
    """Torque em **Nm**, arredondado (tolerância do eval é ±1 Nm).

    `to_nm(50.9, "kgfm")` -> 499 · `to_nm("583 N.m")` -> 583
    """
    return round(to_nm_exact(value, unit))


def to_nm_exact(value: str | float | int, unit: str = "Nm") -> float:
    """Igual a :func:`to_nm`, sem arredondar (para auditoria)."""
    u = _slug_unidade(unit)
    if u not in FATOR_TORQUE:
        raise UnidadeDesconhecida(f"unidade de torque desconhecida: {unit!r}")
    return parse_number_ptbr(value) * FATOR_TORQUE[u]


# ------------------------------------------------------------------------- preço
_MOEDA = re.compile(r"r\$|\breais?\b|\bbrl\b", re.IGNORECASE)


def parse_price(texto: str | float | int) -> int:
    """Preço em **centavos-inteiros de real, arredondado para real**.

    `parse_price("R$ 499.000")` -> 499000 · `parse_price("R$ 452.540,00")` -> 452540
    Levanta se não houver número. Nunca "completa" um preço parcial.
    """
    if isinstance(texto, (int, float)):
        return round(float(texto))
    bruto = _MOEDA.sub(" ", unicodedata.normalize("NFKC", str(texto)))
    return round(parse_number_ptbr(bruto))


def parse_rpm(texto: str | float | int) -> int:
    """`"5.650 rpm"` -> 5650 · `"3.500 a 4.500 rpm"` -> 3500 (o primeiro valor)."""
    return round(parse_number_ptbr(texto))


# -------------------------------------------------------------------------- pneus
@dataclass(frozen=True)
class Pneu:
    """Medida de pneu decomposta. `medida` mantém a forma canônica `285/70 R17`."""

    largura_mm: int
    perfil: int
    aro_pol: int
    medida: str

    def __str__(self) -> str:  # pragma: no cover - conveniência
        return self.medida


_PNEU = re.compile(
    r"(?P<largura>\d{3})\s*[/x]\s*(?P<perfil>\d{2})\s*[rzd]?\s*(?P<aro>\d{2})",
    re.IGNORECASE,
)


def parse_tire(texto: str) -> Pneu:
    """`"285/70 R17"`, `"285/70R17"`, `"pneus 285/70 r 17 AT"` -> :class:`Pneu`."""
    achado = _PNEU.search(unicodedata.normalize("NFKC", texto))
    if not achado:
        raise ValueError(f"medida de pneu não reconhecida: {texto!r}")
    largura = int(achado.group("largura"))
    perfil = int(achado.group("perfil"))
    aro = int(achado.group("aro"))
    return Pneu(largura, perfil, aro, f"{largura}/{perfil} R{aro}")


# ------------------------------------------------------------------- comprimentos
def to_mm(value: str | float | int, unit: str = "mm") -> int:
    """Comprimento em **mm**. Aceita `mm`, `cm`, `m`, `pol`/`in`/`"`."""
    u = _slug_unidade(unit).replace('"', "pol")
    numero = parse_number_ptbr(value)
    # Por extenso porque **é assim que a página escreve**, e a regra do projeto manda o
    # modelo copiar a unidade do texto em vez de traduzi-la. `to_litros` já aceitava
    # `"litros"`; esta tabela não aceitava `"metros"`, e foi por isso que a pesquisa da
    # Triton morreu em 13/09/2026, depois de 456 s e 29 chamadas pagas.
    fatores = {
        "mm": 1.0,
        "milimetro": 1.0,
        "milimetros": 1.0,
        "cm": 10.0,
        "centimetro": 10.0,
        "centimetros": 10.0,
        "m": 1000.0,
        "metro": 1000.0,
        "metros": 1000.0,
        "pol": MM_POR_POLEGADA,
        "polegada": MM_POR_POLEGADA,
        "polegadas": MM_POR_POLEGADA,
        "in": MM_POR_POLEGADA,
    }
    if u not in fatores:
        raise UnidadeDesconhecida(f"unidade de comprimento desconhecida: {unit!r}")
    # **Um carro não tem 5.285 metros.** Medido em 13/09/2026: o modelo devolveu
    # `value=5285` com `unit="m"` para o trecho "Comprimento: 5,285 m" — converteu o número
    # e copiou a unidade do texto, que é o que o prompt manda fazer com a unidade. Multiplicar
    # de novo dava 5.285.000 mm gravados como FATO. Acima de 100 "metros" o número só pode
    # estar em milímetros já; a unidade é a que sobrou do texto.
    if u in ("m", "metro", "metros") and numero >= 100:
        return round(numero)
    return round(numero * fatores[u])


def to_litros(value: str | float | int, unit: str = "l") -> float:
    """Volume em **litros**. Aceita `l`, `ml`, `cc`/`cm3`, `gal` (US)."""
    u = _slug_unidade(unit)
    numero = parse_number_ptbr(value)
    fatores = {
        "l": 1.0,
        "lt": 1.0,
        "litro": 1.0,
        "litros": 1.0,
        "ml": 0.001,
        "mililitro": 0.001,
        "mililitros": 0.001,
        "cc": 0.001,
        "cm3": 0.001,
    }
    fatores["gal"] = 3.785411784
    if u not in fatores:
        raise UnidadeDesconhecida(f"unidade de volume desconhecida: {unit!r}")
    return round(numero * fatores[u], 3)
