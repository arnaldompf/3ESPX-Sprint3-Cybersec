"""Normalização: valor bruto da fonte → valor canônico da ficha.

Duas garantias, e a segunda é a que faz a auditoria funcionar:

1. **Unidade canônica sempre.** `50,9 kgf.m` vira `499 Nm`; `258 hp` vira `262 cv`;
   `2755 cm³` vira `2,8 l`. A tabela de fatores é `docs/03`, implementada em
   `pipeline/units.py`.
2. **`raw_value` nunca se perde.** O que a fonte escreveu vai para a evidência, junto com
   a conversão aplicada. Sem isso, "583 Nm" na tela seria indistinguível de um número que
   alguém digitou — e a promessa do produto é justamente essa distinção.

Listas de modos passam pela ontologia (`resolve_value`), então `Esportivo` e `Sport` viram
o mesmo token e `Lama/Terra` vira `lama`. Atributo livre que não casa com campo canônico
vai para `extras[slug]`, com as mesmas regras de status — nunca é descartado em silêncio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pipeline import units
from pipeline.ontology import canonicalizar_lista, resolve_attribute, resolve_value, slugify
from pipeline.schema import (
    CAMPOS_BOOL,
    CAMPOS_LISTA,
    UNIDADE_CANONICA,
    caminho_canonico,
    grupo_de,
)

#: Dimensão de unidade por campo, para escolher o conversor.
DIMENSAO_POR_CAMPO: dict[str, str] = {
    "potencia_cv": "potencia",
    "torque_nm": "torque",
    "deslocamento_l": "volume",
    "tanque_l": "volume",
    "comprimento_mm": "comprimento",
    "largura_mm": "comprimento",
    "altura_mm": "comprimento",
    "entre_eixos_mm": "comprimento",
    "preco_sugerido_brl": "preco",
    "preco_fipe_brl": "preco",
    "potencia_rpm": "rpm",
    "torque_rpm": "rpm",
    "pneus_medida": "pneu",
}

#: Campos cujo valor canônico é inteiro.
CAMPOS_INTEIROS: frozenset[str] = frozenset(
    {
        "potencia_cv",
        "torque_nm",
        "potencia_rpm",
        "torque_rpm",
        "numero_marchas",
        "airbags_qtd",
        "rodas_aro_pol",
        "comprimento_mm",
        "largura_mm",
        "altura_mm",
        "entre_eixos_mm",
        "capacidade_carga_kg",
        "capacidade_reboque_kg",
        "velocidade_maxima_kmh",
        "preco_sugerido_brl",
        "preco_fipe_brl",
        "garantia_meses",
        "ano_modelo",
        "cilindros",
    }
)

#: Valores textuais que significam "sim" e "não" em ficha de equipamento.
SIM = frozenset({"sim", "si", "s", "•", "x", "✓", "true", "1", "de serie", "de série", "serie"})
NAO = frozenset({"nao", "não", "n", "-", "–", "—", "false", "0", "opcional", "nd"})

#: Como a fonte oficial escreve "este item não existe nesta versão" (`docs/05`).
MARCAS_DE_AUSENCIA = frozenset(
    {"-", "–", "—", "n/d", "nd", "n.d.", "não disponível", "nao disponivel", "não oferecido"}
)

#: Datas em pt-BR e ISO.
_DATA_ISO = re.compile(r"\b(?P<a>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b")
_DATA_BR = re.compile(r"\b(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<a>\d{4})\b")
_MES_ANO = re.compile(r"\b(?P<a>\d{4})-(?P<m>\d{2})\b|\b(?P<m2>\d{1,2})/(?P<a2>\d{4})\b")


class NaoNormalizavel(ValueError):
    """O valor bruto não virou o tipo canônico do campo.

    **É o único tipo que atravessa a fronteira desta função.** `pipeline/units.py` levanta
    `UnidadeDesconhecida`, que é *irmã* desta (as duas herdam de `ValueError`) e não filha
    — e `pipeline/reconcile.py` só captura esta. Em 13/09/2026 uma página escreveu o
    comprimento em `"metros"`, a irmã passou reto pelo `except`, e a pesquisa inteira
    morreu levando junto 54 campos já lidos e pagos.

    A conversão está em :func:`normalizar_campo`, e não no `except` do chamador, porque
    chamador é plural: `reconcile`, `radar/internal` e o que vier. Consertar no lugar onde
    o erro nasce vale para todos eles.
    """


@dataclass
class Normalizado:
    """O valor canônico, com o bruto e a conversão preservados."""

    campo: str
    valor: Any
    raw_value: str
    unidade: str | None = None
    conversao: str = ""
    """Descrição da conversão aplicada, para a evidência (ex.: `kgf.m→Nm ×9,80665`)."""
    ausencia_declarada: bool = False
    """A fonte disse explicitamente que o item não existe (`nao_disponivel`)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "campo": self.campo,
            "valor": self.valor,
            "raw_value": self.raw_value,
            "unidade": self.unidade,
            "conversao": self.conversao,
            "ausencia_declarada": self.ausencia_declarada,
        }


def parece_ausencia(bruto: Any) -> bool:
    """A fonte oficial está declarando ausência? (`nao_disponivel`, não `nao_encontrado`)"""
    if bruto is None:
        return False
    texto = str(bruto).strip().lower()
    return texto in MARCAS_DE_AUSENCIA


def _para_bool(bruto: Any) -> bool:
    if isinstance(bruto, bool):
        return bruto
    texto = str(bruto).strip().lower()
    if texto in SIM:
        return True
    if texto in NAO:
        return False
    # texto descritivo presente é presença: "Paddle Shifters" numa lista de itens
    return bool(texto)


def _para_data(bruto: Any) -> str:
    """Data em ISO (`AAAA-MM-DD`) ou referência mensal (`AAAA-MM`)."""
    texto = str(bruto).strip()
    achado = _DATA_ISO.search(texto)
    if achado:
        return f"{achado['a']}-{achado['m']}-{achado['d']}"
    achado = _DATA_BR.search(texto)
    if achado:
        return f"{achado['a']}-{int(achado['m']):02d}-{int(achado['d']):02d}"
    achado = _MES_ANO.search(texto)
    if achado:
        if achado["a"]:
            return f"{achado['a']}-{achado['m']}"
        return f"{achado['a2']}-{int(achado['m2']):02d}"
    raise NaoNormalizavel(f"data não reconhecida: {bruto!r}")


def normalizar_campo(campo: str, bruto: Any, *, unidade: str | None = None) -> Normalizado:
    """Normaliza um valor bruto para o tipo e a unidade canônicos do campo.

    Levanta :class:`NaoNormalizavel` quando não dá — e não dar é um resultado legítimo:
    o campo então fica `nao_verificado`, nunca com um valor forçado.

    **E levanta só isso.** O invólucro existe para que a promessa da frase acima valha:
    `pipeline/units.py` tem quatro `raise UnidadeDesconhecida` espalhados por quatro
    dimensões, e um chamador que precise listar exceções de outro módulo para não morrer
    vai esquecer a quinta. Ver :class:`NaoNormalizavel` para o defeito que isto fecha.

    **Qualquer `ValueError` vira o tipo da fronteira, e não só a irmã conhecida.** A
    primeira versão capturava `UnidadeDesconhecida` nominalmente — e em 13/09/2026, na
    pesquisa ao vivo da Frontier, uma fonte escreveu *"seis"* airbags por extenso:
    `parse_number_ptbr` levantou um `ValueError` simples, que não era nenhuma das duas, e
    **a pesquisa inteira morreu** depois de 10 páginas e 4 chamadas de modelo pagas. É o
    mesmo defeito da unidade em `"metros"`, uma exceção adiante. Listar tipos irmãos é uma
    lista que envelhece; a família inteira, não.
    """
    try:
        return _normalizar_campo(campo, bruto, unidade=unidade)
    except NaoNormalizavel:
        raise
    except ValueError as exc:
        raise NaoNormalizavel(f"{campo}: {exc}") from exc


def _normalizar_campo(campo: str, bruto: Any, *, unidade: str | None = None) -> Normalizado:
    raw = "" if bruto is None else str(bruto).strip()

    if parece_ausencia(raw):
        return Normalizado(campo, None, raw, UNIDADE_CANONICA.get(campo), ausencia_declarada=True)
    if raw == "":
        raise NaoNormalizavel(f"{campo}: valor bruto vazio")

    if campo in CAMPOS_LISTA:
        tokens = bruto if isinstance(bruto, list) else _dividir_lista(raw)
        lista = canonicalizar_lista(campo, [str(t) for t in tokens])
        if not lista:
            raise NaoNormalizavel(f"{campo}: nenhuma opção reconhecida em {raw!r}")
        return Normalizado(campo, lista, raw, None, "tokens canonicalizados por sinônimos")

    if campo in CAMPOS_BOOL:
        return Normalizado(campo, _para_bool(bruto), raw, None)

    if campo in {"preco_data"}:
        return Normalizado(campo, _para_data(raw), raw, None, "data em ISO")
    if campo in {"fipe_referencia"}:
        return Normalizado(campo, _para_data(raw), raw, None, "referência mensal AAAA-MM")

    dimensao = DIMENSAO_POR_CAMPO.get(campo)
    canonica = UNIDADE_CANONICA.get(campo)

    if dimensao == "potencia":
        origem = (unidade or "cv").lower()
        valor = units.to_cv(bruto, origem)
        conversao = "" if origem in {"cv", "ps"} else f"{origem}→cv"
        return Normalizado(campo, valor, raw, canonica, conversao)

    if dimensao == "torque":
        origem = (unidade or "Nm").lower()
        valor = units.to_nm(bruto, origem)
        conversao = "" if origem.startswith("n") else f"{origem}→Nm ×9,80665"
        return Normalizado(campo, valor, raw, canonica, conversao)

    if dimensao == "preco":
        return Normalizado(campo, units.parse_price(bruto), raw, canonica)

    if dimensao == "rpm":
        return Normalizado(campo, units.parse_rpm(bruto), raw, canonica)

    if dimensao == "pneu":
        return Normalizado(campo, units.parse_tire(raw).medida, raw, None, "medida canônica")

    if dimensao == "volume":
        origem = (unidade or "l").lower()
        # cm³ é o que a Toyota usa para cilindrada; a ficha diz "2755"
        if origem in {"cm3", "cc", "cm³"}:
            valor = round(units.parse_number_ptbr(bruto) / 1000, 2)
            return Normalizado(
                campo, _cilindrada_plausivel(campo, valor, raw), raw, canonica, "cm³→l"
            )
        valor = units.to_litros(bruto, origem)
        return Normalizado(
            campo,
            _cilindrada_plausivel(campo, valor, raw),
            raw,
            canonica,
            "" if origem == "l" else f"{origem}→l",
        )

    if dimensao == "comprimento":
        origem = (unidade or "mm").lower()
        valor = units.to_mm(bruto, origem)
        return Normalizado(campo, valor, raw, canonica, "" if origem == "mm" else f"{origem}→mm")

    if campo in CAMPOS_INTEIROS:
        if campo == "cilindros":
            # "V6" não é número; é arranjo. Fica como texto.
            return Normalizado(campo, _texto_canonico(campo, raw), raw, None)
        return Normalizado(campo, round(units.parse_number_ptbr(bruto)), raw, canonica)

    if canonica in {"s", "km/l", "km/h"} or campo in {
        "aceleracao_0_100_s",
        "consumo_urbano_kml",
        "consumo_rodoviario_kml",
    }:
        return Normalizado(campo, units.parse_number_ptbr(bruto), raw, canonica)

    return Normalizado(campo, _texto_canonico(campo, raw), raw, None)


#: Cilindrada de motor de automóvel, em litros. Fora disto é erro de leitura, não motor.
FAIXA_DE_CILINDRADA_L = (0.5, 10.0)


def _cilindrada_plausivel(campo: str, valor: float, raw: str) -> float:
    """Recusa uma cilindrada que nenhum automóvel tem, em vez de gravá-la.

    Medido na S10 em 14/09/2026: a página dizia `Cilindrada: 2.776 cm³`, e o modelo
    devolveu o número **já convertido a float** — `2.776`, com o ponto lido à inglesa.
    Dividir por mil deu `0,003`, que arredondou para **0**, e a ficha ganhou um motor de
    zero litro com `status=verificado` e uma citação verdadeira ao lado.

    A guarda é a mesma de `units.to_mm` para "5,285 m": o número que sai da conversão tem
    de caber no mundo. Quando não cabe, o campo volta a ser lacuna — que se vê — em vez de
    virar zero, que passa.
    """
    if campo != "deslocamento_l":
        return valor
    minimo, maximo = FAIXA_DE_CILINDRADA_L
    if minimo <= valor <= maximo:
        return valor
    raise NaoNormalizavel(
        f"{campo}: {valor} l está fora de {minimo}–{maximo} l (lido de {raw!r}); "
        "nenhum automóvel tem esse motor, então é erro de leitura, não medida"
    )


def _texto_canonico(campo: str, raw: str) -> str:
    """Texto passado pela ontologia quando o campo tem vocabulário; senão, como veio."""
    canonico = resolve_value(campo, raw)
    if canonico and canonico != slugify(raw):
        return canonico
    return re.sub(r"\s+", " ", raw).strip()


_SEPARADOR_DE_LISTA = re.compile(r"\s*(?:,|;|\be\b|\+)\s*", re.IGNORECASE)


def _dividir_lista(raw: str) -> list[str]:
    return [t for t in _SEPARADOR_DE_LISTA.split(raw) if t and len(t.strip()) > 1]


# ------------------------------------------------------------------ atributo livre
@dataclass(frozen=True)
class AtributoResolvido:
    """Para onde vai um atributo pedido em texto livre pelo usuário."""

    pedido: str
    campo: str | None
    caminho: str
    score: float
    e_extra: bool

    @property
    def chave(self) -> str:
        """Nome sob o qual o atributo aparece na ficha."""
        return self.campo or self.caminho.split(".", 1)[1]


def resolver_atributo(pedido: str) -> AtributoResolvido:
    """Atributo livre → campo canônico, ou `extras[slug]`.

    `docs/03`: match em `synonyms`/rapidfuzz ≥ 0,85 vira campo canônico; senão vira
    `extras[<slug>]`, **extraído com o mesmo pipeline e as mesmas regras de status**.
    Nunca é descartado: um atributo que o usuário pediu e o sistema ignorou em silêncio
    é pior que um `nao_encontrado`.
    """
    campo, score = resolve_attribute(pedido)
    if campo and grupo_de(campo):
        return AtributoResolvido(pedido, campo, caminho_canonico(campo) or "", score, False)
    slug = slugify(pedido)
    return AtributoResolvido(pedido, None, f"extras.{slug}", score, True)


def resolver_atributos(pedidos: list[str]) -> list[AtributoResolvido]:
    return [resolver_atributo(p) for p in pedidos]
