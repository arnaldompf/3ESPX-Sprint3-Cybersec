"""O verificador do texto reescrito: **todo número do texto existe nas células?**

Este módulo é a razão de o LLM poder participar. Sem ele, uma reescrita "em tom consultivo"
poderia trocar 397 por 400, inventar "o dobro de torque" ou acrescentar um item de série que
ninguém verificou — e o texto sairia mais bonito e menos verdadeiro, o que é a pior troca
possível neste produto.

**A regra é assimétrica de propósito:** o texto pode dizer **menos** que as células (o LLM
resume, e resumir é o serviço), mas não pode dizer **nada que não esteja lá**. Todo número
e toda unidade do texto têm de aparecer nos valores verificados; comparativo superlativo sem
número que o sustente também reprova.

Falhou, devolve o template. Não há "corrigir o texto do LLM": um texto que inventou um
número não fica confiável depois de trocar aquele número — o que ele mais tem é o resto que
ninguém checou.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

#: Números no texto. Pega inteiro, decimal com vírgula ou ponto, e milhar pt-BR.
NUMERO = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?")

#: Números que **não** precisam estar nas células.
#:
#: Ano, mês e dia aparecem na data da fonte ("(site oficial, 01/09/2026)"), e a data é parte
#: do template — não é afirmação sobre o veículo. Sem esta exceção, toda frase com fonte
#: seria reprovada.
#:
#: Números de 0 a 12 também passam: eles aparecem em "3 pontos", "as 4 rodas", "os 2
#: primeiros", e exigir que estejam nas células reprovaria português normal. O risco é
#: baixo — um valor de ficha nessa faixa (airbags, marchas) **também** está nas células, e
#: então casa de qualquer forma.
TETO_DE_NUMERO_LIVRE = 12

#: Comparativos que **exigem** número no texto para serem sustentados.
#:
#: "Mais forte" sem número é opinião; "mais forte: 397 cv contra 204 cv" é fato. A lista é
#: curta e cobre o que um modelo escreve quando quer soar consultivo.
COMPARATIVOS_QUE_EXIGEM_NUMERO = (
    "o dobro",
    "o triplo",
    "muito mais",
    "muito menos",
    "bem mais",
    "bem menos",
    "de longe",
    "incomparavel",
    "imbativel",
    "melhor do mercado",
    "lider de mercado",
)

#: Superlativos que **nunca** passam: nenhuma célula sustenta "o melhor do Brasil".
SUPERLATIVOS_PROIBIDOS = (
    "o melhor",
    "a melhor",
    "o mais",
    "a mais",
    "unico",
    "unica",
    "sem concorrencia",
    "insuperavel",
)


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c)
    )


def _numeros_de(texto: str) -> list[str]:
    return NUMERO.findall(texto)


def _canonico(numero: str) -> float | None:
    """`"1.005"` → 1005.0, `"9,7"` → 9.7. `None` quando não dá."""
    from pipeline.units import parse_number_ptbr

    try:
        return parse_number_ptbr(numero)
    except ValueError:
        return None


@dataclass
class Resultado:
    """Aprovado ou não, e **o que** reprovou. Sem o motivo ninguém corrige a causa."""

    aprovado: bool
    numeros_do_texto: list[float] = field(default_factory=list)
    numeros_sem_respaldo: list[float] = field(default_factory=list)
    termos_proibidos: list[str] = field(default_factory=list)
    motivo: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "aprovado": self.aprovado,
            "numeros_do_texto": list(self.numeros_do_texto),
            "numeros_sem_respaldo": list(self.numeros_sem_respaldo),
            "termos_proibidos": list(self.termos_proibidos),
            "motivo": self.motivo,
        }


def numeros_das_celulas(valores: list[Any]) -> set[float]:
    """Todos os números que as células sustentam, canonicalizados.

    Inclui item de lista e booleano contado: uma lista de 7 modos sustenta o número 7, que é
    o que o texto vai citar ("os 7 modos de condução").
    """
    achados: set[float] = set()
    for valor in valores:
        if valor is None or isinstance(valor, bool):
            continue
        if isinstance(valor, int | float):
            achados.add(float(valor))
            continue
        if isinstance(valor, list | tuple):
            achados.add(float(len(valor)))
            for item in valor:
                for numero in _numeros_de(str(item)):
                    canonico = _canonico(numero)
                    if canonico is not None:
                        achados.add(canonico)
            continue
        for numero in _numeros_de(str(valor)):
            canonico = _canonico(numero)
            if canonico is not None:
                achados.add(canonico)
    return achados


def verificar(
    texto: str,
    valores: list[Any],
    *,
    datas: list[str] | None = None,
    nomes_de_campo: list[str] | None = None,
) -> Resultado:
    """Confere o texto contra os valores verificados.

    `datas` são as datas das fontes que o texto pode citar; os números delas são liberados
    porque são parte da procedência, não afirmação sobre o veículo.

    `nomes_de_campo` libera os números que fazem parte de um **nome**. O caso que obrigou
    isto: "câmera 360 de série" foi reprovado porque nenhuma célula tem o valor 360 — só
    que o 360 é o nome do item (`camera_360`), não uma medida. O mesmo vale para "4x4",
    "V6" e "2.8". Sem isto, o verificador reprovaria justamente o texto correto que citou
    o item pelo nome que a ficha usa.
    """
    suportados = numeros_das_celulas(valores)
    for data in datas or []:
        for numero in _numeros_de(str(data)):
            canonico = _canonico(numero)
            if canonico is not None:
                suportados.add(canonico)
    for nome in nomes_de_campo or []:
        for numero in _numeros_de(str(nome)):
            canonico = _canonico(numero)
            if canonico is not None:
                suportados.add(canonico)

    resultado = Resultado(aprovado=True)
    sem_respaldo: list[float] = []
    for bruto in _numeros_de(texto):
        canonico = _canonico(bruto)
        if canonico is None:
            continue
        resultado.numeros_do_texto.append(canonico)
        if canonico in suportados:
            continue
        if abs(canonico) <= TETO_DE_NUMERO_LIVRE and float(canonico).is_integer():
            continue
        # Ano de quatro dígitos: a data da fonte, quando ela não veio em `datas`.
        if 1900 <= canonico <= 2100 and float(canonico).is_integer():
            continue
        sem_respaldo.append(canonico)

    plano = _sem_acento(texto)
    proibidos = [t for t in SUPERLATIVOS_PROIBIDOS if t in plano]
    sem_numero = [
        t for t in COMPARATIVOS_QUE_EXIGEM_NUMERO if t in plano and not resultado.numeros_do_texto
    ]

    resultado.numeros_sem_respaldo = sem_respaldo
    resultado.termos_proibidos = [*proibidos, *sem_numero]

    if sem_respaldo:
        resultado.aprovado = False
        lista = ", ".join(f"{n:g}" for n in sem_respaldo)
        resultado.motivo = (
            f"o texto cita {lista}, e não há célula verificada com esse valor. "
            "Reescrita descartada; o template original foi mantido."
        )
        return resultado
    if resultado.termos_proibidos:
        resultado.aprovado = False
        resultado.motivo = (
            f"o texto usa comparativo sem número que o sustente: "
            f"{', '.join(resultado.termos_proibidos)}. Reescrita descartada."
        )
        return resultado
    return resultado
