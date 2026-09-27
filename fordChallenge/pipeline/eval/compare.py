"""Comparação de um campo do pipeline contra o gabarito, e o grounding.

Tolerâncias e regras vêm de `docs/09_EVAL_E_GABARITO.md`:

* cv/Nm ±1 · rpm ±50 · segundos ±0,1 · preço ±0,5% (ou mesma referência FIPE)
* listas comparadas como **conjuntos** depois dos sinônimos
* objetos campo a campo; subcampo `None` no gabarito não é avaliado

O grounding é o gate anti-alucinação, e vive em `pipeline/ground.py`. Este módulo apenas
o **reexporta**: se o eval medisse um grounding diferente do que o pipeline aplica, a
métrica `grounding_rate` não mediria o produto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from pipeline.ground import LIMIAR_DIFUSO, locate, normalize_texto
from pipeline.ontology import canonicalizar_lista, normalize, resolve_value
from pipeline.schema import CAMPOS_BOOL, CAMPOS_LISTA


@dataclass(frozen=True)
class Tolerancia:
    """Como um número é comparado: em valor absoluto ou em porcentagem."""

    absoluta: float | None = None
    relativa: float | None = None

    def bate(self, esperado: float, obtido: float) -> bool:
        if self.absoluta is not None and abs(esperado - obtido) <= self.absoluta:
            return True
        if self.relativa is not None and esperado != 0:
            return abs(esperado - obtido) / abs(esperado) <= self.relativa
        return self.absoluta is None and self.relativa is None and esperado == obtido

    def descricao(self) -> str:
        partes = []
        if self.absoluta is not None:
            partes.append(f"±{self.absoluta:g}")
        if self.relativa is not None:
            partes.append(f"±{self.relativa * 100:g}%")
        return " ou ".join(partes) or "exato"


#: Tolerância por campo canônico. O que não está aqui é comparado exato.
TOLERANCIAS: dict[str, Tolerancia] = {
    "potencia_cv": Tolerancia(absoluta=1),
    "torque_nm": Tolerancia(absoluta=1),
    "potencia_rpm": Tolerancia(absoluta=50),
    "torque_rpm": Tolerancia(absoluta=50),
    "aceleracao_0_100_s": Tolerancia(absoluta=0.1),
    "velocidade_maxima_kmh": Tolerancia(absoluta=1),
    "consumo_urbano_kml": Tolerancia(absoluta=0.1),
    "consumo_rodoviario_kml": Tolerancia(absoluta=0.1),
    "deslocamento_l": Tolerancia(absoluta=0.05),
    "tanque_l": Tolerancia(absoluta=0.5),
    "preco_sugerido_brl": Tolerancia(relativa=0.005),
    "preco_fipe_brl": Tolerancia(relativa=0.005),
    "comprimento_mm": Tolerancia(absoluta=1),
    "largura_mm": Tolerancia(absoluta=1),
    "altura_mm": Tolerancia(absoluta=1),
    "entre_eixos_mm": Tolerancia(absoluta=1),
    "capacidade_carga_kg": Tolerancia(absoluta=1),
    "capacidade_reboque_kg": Tolerancia(absoluta=1),
}

_TOLERANCIA_PADRAO_NUMERICA = Tolerancia(absoluta=0.0)


def tolerancia_de(campo: str) -> Tolerancia:
    return TOLERANCIAS.get(campo, _TOLERANCIA_PADRAO_NUMERICA)


# ------------------------------------------------------------------------- grounding
#
# A implementação vive em `pipeline/ground.py`, e o eval a **reexporta** em vez de
# reimplementar. Se o eval medisse um grounding diferente do que o pipeline aplica, a
# métrica `grounding_rate` não mediria o produto — mediria uma segunda implementação.
LIMIAR_GROUNDING = LIMIAR_DIFUSO


@dataclass(frozen=True)
class ResultadoGrounding:
    """Compatibilidade com o vocabulário do eval; `modo` e `score` vêm de `ground`."""

    ok: bool
    modo: str
    score: float = 0.0

    def __bool__(self) -> bool:  # pragma: no cover - conveniência
        return self.ok


def normalize_grounding(texto: str) -> str:
    """Reexporta :func:`pipeline.ground.normalize_texto`."""
    return normalize_texto(texto)


def grounding(quote: str | None, texto: str | None) -> ResultadoGrounding:
    """O trecho citado ocorre no texto salvo da fonte?

    >>> grounding("397cv", "Motor 3.0 V6. Potencia 397cv de forca.").ok
    True
    >>> grounding("Potencia 500cv", "Motor 3.0 V6. Potencia 397cv de forca.").ok
    False
    """
    achado = locate(quote, texto)
    return ResultadoGrounding(achado.ok, achado.modo, achado.score)


def grounding_ok(quote: str | None, texto: str | None) -> bool:
    """Atalho booleano de :func:`grounding`."""
    return locate(quote, texto).ok


# -------------------------------------------------------------------- comparação
@dataclass(frozen=True)
class ResultadoValor:
    igual: bool
    modo: str  # "exato" | "tolerancia" | "conjunto" | "contido" | "diferente" | "sem_obtido"
    detalhe: str = ""


def _numero(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _tokens(texto: str) -> list[str]:
    return [t for t in re.split(r"[^0-9a-z]+", normalize(texto)) if t]


#: Campos cuja lista é de **frases livres**, não de tokens de vocabulário fechado.
#:
#: `modos_conducao` tem vocabulário fechado (`normal`, `sport`, `lama`…) e a ontologia o
#: canonicaliza; comparar como conjunto exato é certo ali. `adas_itens` é diferente: são
#: frases, e o gabarito **parafraseia** a fonte — "assistente de permanência e
#: centralização em faixa" (fonte) contra "permanência e centralização em faixa"
#: (gabarito), "sensores de estacionamento dianteiro e traseiro" contra "sensores
#: dianteiro/traseiro". Exigir igualdade nessas frases faria a métrica medir sorte de
#: paráfrase, não qualidade de extração.
CAMPOS_DE_LISTA_LIVRE: frozenset[str] = frozenset({"adas_itens"})

#: Similaridade mínima entre dois itens de lista livre para tratá-los como o mesmo item.
LIMIAR_ITEM_DE_LISTA = 72.0


def _itens_casam(esperado: str, obtido: str) -> bool:
    a, b = normalize(esperado), normalize(obtido)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return float(fuzz.token_set_ratio(a, b)) >= LIMIAR_ITEM_DE_LISTA


def comparar_lista_livre(campo: str, esperado: list, obtido: list) -> ResultadoValor:
    """Conjuntos iguais após aliases explícitos, com correspondência bijetiva.

    Itens extras e faltantes são penalizados. Similaridade textual não prova
    equivalência funcional de dois equipamentos de segurança.
    """
    # Correspondência bijetiva: um item não pode justificar duas funções distintas.
    esperados = list(
        dict.fromkeys(resolve_value(campo, str(x)) or normalize(str(x)) for x in esperado)
    )
    obtidos = list(dict.fromkeys(resolve_value(campo, str(x)) or normalize(str(x)) for x in obtido))
    if len(esperados) != len(obtidos):
        return ResultadoValor(False, "diferente", "lista incompleta ou com itens extras")
    usados: dict[int, int] = {}

    def casar(i: int, vistos: set[int]) -> bool:
        for j, o in enumerate(obtidos):
            if j in vistos or esperados[i] != o:
                continue
            vistos.add(j)
            if j not in usados or casar(usados[j], vistos):
                usados[j] = i
                return True
        return False

    ok = all(casar(i, set()) for i in range(len(esperados)))
    return ResultadoValor(
        ok,
        "lista_livre" if ok else "diferente",
        "conjunto exato após aliases explícitos; extras são penalizados",
    )


def comparar_lista(campo: str, esperado: list, obtido: list) -> ResultadoValor:
    """Conjunto após sinônimos (`docs/09`); lista de frases usa comparação por item.

    >>> comparar_lista("modos_conducao", ["normal","esportivo","lama/terra"],
    ...                ["normal","sport","lama"]).igual
    True
    """
    if campo in CAMPOS_DE_LISTA_LIVRE:
        return comparar_lista_livre(campo, esperado, obtido)
    a = set(canonicalizar_lista(campo, [str(x) for x in esperado]))
    b = set(canonicalizar_lista(campo, [str(x) for x in obtido]))
    if a == b:
        return ResultadoValor(True, "conjunto")
    faltando = sorted(a - b)
    sobrando = sorted(b - a)
    return ResultadoValor(
        False,
        "diferente",
        f"faltando={faltando} sobrando={sobrando}",
    )


def comparar_texto(campo: str, esperado: str, obtido: str) -> ResultadoValor:
    """Igualdade após sinônimos; aceita o obtido **mais específico** que o esperado.

    O gabarito às vezes é mais grosso que a fonte: `tracao.tipo` é `"4x4"` enquanto a
    ficha da Raptor detalha `"4x4 sob demanda"`. Um obtido que contém todos os tokens do
    esperado é considerado compatível — e o modo `"contido"` fica registrado no relatório,
    para que ninguém confunda compatível com idêntico.
    """
    a_canon = resolve_value(campo, esperado)
    b_canon = resolve_value(campo, obtido)
    if a_canon is not None and a_canon == b_canon:
        return ResultadoValor(True, "exato")
    a, b = normalize(esperado), normalize(obtido)
    if a == b:
        return ResultadoValor(True, "exato")
    ta, tb = _tokens(esperado), _tokens(obtido)
    if ta and set(ta) <= set(tb):
        return ResultadoValor(True, "contido", f"esperado {esperado!r} contido em {obtido!r}")
    return ResultadoValor(False, "diferente", f"esperado {esperado!r} != obtido {obtido!r}")


#: Campos em que o gabarito passou a exigir **só a contagem** — e por quê.
#:
#: `cilindros` era `"4 em linha"` na Hilux e na S10, e `"V6"` na Raptor e na Amarok.
#: Duas coisas erradas nisso, e a correção foi autorizada pelo humano em 10/09/2026:
#:
#: * **o arranjo era inferência.** Nenhuma fonte pública da Hilux diz "em linha" — as
#:   fichas trazem `"Cilindrada (cm3) 2755"` e nada mais. "4 em linha" saiu do que se
#:   sabe sobre motores 2.8 diesel, não do que a fonte afirma, e isso é exatamente o que
#:   a regra inviolável do projeto proíbe;
#: * **as duas grafias não são comparáveis entre si.** `"V6"` traz contagem **e**
#:   arranjo colados; `4` traz só contagem. Medir `"V6"` contra `6` como texto falha, e
#:   medir como texto era o que a régua fazia — a Amarok aparecia `divergente` no eval
#:   com o motivo `"exato"`, que é a régua discordando de si mesma.
#:
#: A régua agora extrai a contagem dos dois lados: `"V6"` → 6, `"4 em linha"` → 4,
#: `"6 cilindros em V"` → 6. O **arranjo continua no valor** que a ficha exibe (ninguém
#: perde a informação); ele só sai do que é **medido**.
CAMPOS_DE_CONTAGEM: frozenset[str] = frozenset({"cilindros"})

#: `V6`, `V8`, `4 em linha`, `6 cilindros`, `L4`. O número é a contagem.
_CONTAGEM = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")


def contagem_de(valor: Any) -> float | None:
    """A contagem dentro de um valor de `cilindros`, ou `None`. Ver `CAMPOS_DE_CONTAGEM`."""
    numero = _numero(valor)
    if numero is not None:
        return numero
    achado = _CONTAGEM.search(str(valor))
    return float(achado.group(1)) if achado else None


def comparar_valor(campo: str, esperado: Any, obtido: Any) -> ResultadoValor:
    """Compara um valor do pipeline contra o gabarito, com a regra certa para o tipo."""
    if obtido is None:
        return ResultadoValor(False, "sem_obtido", "pipeline não trouxe valor")

    if campo in CAMPOS_DE_CONTAGEM:
        ce, co = contagem_de(esperado), contagem_de(obtido)
        if ce is None or co is None:
            return ResultadoValor(
                False,
                "sem_contagem",
                f"sem contagem de cilindros em esperado={esperado!r} obtido={obtido!r}",
            )
        if ce == co:
            return ResultadoValor(True, "contagem", f"{ce:g} cilindros (arranjo fora da medida)")
        return ResultadoValor(False, "diferente", f"{ce:g} vs {co:g} cilindros")

    if campo in CAMPOS_LISTA or isinstance(esperado, list):
        lista_obtida = obtido if isinstance(obtido, list) else [obtido]
        lista_esperada = esperado if isinstance(esperado, list) else [esperado]
        return comparar_lista(campo, lista_esperada, lista_obtida)

    if campo in CAMPOS_BOOL or isinstance(esperado, bool):
        return (
            ResultadoValor(True, "exato")
            if bool(esperado) == bool(obtido)
            else ResultadoValor(False, "diferente", f"{esperado!r} != {obtido!r}")
        )

    ne, no = _numero(esperado), _numero(obtido)
    if ne is not None:
        if no is None:
            # o pipeline pode trazer o número como texto ("397 cv")
            from pipeline.units import parse_number_ptbr

            try:
                no = parse_number_ptbr(str(obtido))
            except ValueError:
                return ResultadoValor(False, "diferente", f"obtido não numérico: {obtido!r}")
        tol = tolerancia_de(campo)
        if ne == no:
            return ResultadoValor(True, "exato")
        if tol.bate(ne, no):
            return ResultadoValor(True, "tolerancia", f"{ne:g} vs {no:g} ({tol.descricao()})")
        return ResultadoValor(
            False, "diferente", f"{ne:g} vs {no:g} (tolerância {tol.descricao()})"
        )

    return comparar_texto(campo, str(esperado), str(obtido))


def comparar_qualquer(campo: str, esperados: tuple[Any, ...], obtido: Any) -> ResultadoValor:
    """Bate contra **qualquer** valor registrado no gabarito.

    Em campo com divergência registrada, acertar um dos valores é acertar: o gabarito
    guarda os dois de propósito e o produto expõe os dois.
    """
    melhor = ResultadoValor(False, "sem_obtido")
    for esperado in esperados:
        if esperado is None:
            continue
        resultado = comparar_valor(campo, esperado, obtido)
        if resultado.igual:
            return resultado
        melhor = resultado
    return melhor
