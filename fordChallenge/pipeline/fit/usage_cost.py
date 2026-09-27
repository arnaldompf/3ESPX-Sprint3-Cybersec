"""Custo mensal de combustível: `km_mes / consumo × preço`, com o combustível certo.

Três coisas que este módulo faz e que uma calculadora de duas linhas não faria:

* **usa o preço do combustível do veículo**, não um preço médio. A Raptor é gasolina e as
  concorrentes são diesel; um preço só faria a comparação de custo dizer o contrário do que
  o cliente vai pagar no posto. Sem o preço daquele combustível, o custo **não é calculado**
  e a resposta diz qual preço falta;
* **declara de onde vem o consumo** (`pbe`, `oficial` ou `informado`), e a frase fixa
  carrega essa origem. "9,5 km/l" medido pelo PBE/Inmetro e "9,5 km/l" que o vendedor
  digitou têm o mesmo formato e valores muito diferentes de confiança;
* **diz o que não está incluído**, na frase fixa de `docs/12` §6.3. Um número de "custo
  mensal" sem essa ressalva será lido como custo de posse, e aí o cliente descobre a
  diferença sozinho — do pior jeito.

O que este módulo **não** faz: estimar seguro, manutenção ou depreciação (fora de escopo
por `specs/WP-26.md`), e recomendar preço.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

#: As origens possíveis do consumo, **da mais forte para a mais fraca**.
#:
#: `pbe` é a medição oficial do programa brasileiro de etiquetagem (tier 2); `oficial` é o
#: consumo declarado pela montadora na própria ficha (tier 1 como fonte, mas número de
#: marketing); `informado` é o que o vendedor digitou. A ordem está aqui em vez de num `if`
#: para a resposta poder dizer "usei a segunda melhor origem, e a melhor não existia".
ORIGENS = ("pbe", "oficial", "informado")

ROTULO_DA_ORIGEM = {
    "pbe": "medido pelo PBE/Inmetro",
    "oficial": "declarado pela montadora",
    "informado": "informado pelo vendedor",
}

#: A frase fixa de `docs/12` §6.3. **Literal**, com dois espaços para preencher.
FRASE_FIXA = (
    "Estimativa de combustível baseada em consumo {fonte} e preços informados em {data}. "
    "Não inclui seguro, manutenção ou depreciação."
)

#: Combustíveis que o cálculo conhece. Fora daqui, o custo não é calculado — e o motivo
#: aparece, em vez de o sistema escolher um preço qualquer.
COMBUSTIVEIS = ("diesel", "gasolina", "flex")

#: Para o flex, qual preço usar. Gasolina, e declarado: um veículo flex rodando com etanol
#: tem consumo diferente do medido a gasolina, e misturar as duas coisas produziria um
#: número que não corresponde a nenhum uso real.
COMBUSTIVEL_DO_FLEX = "gasolina"


@dataclass
class Consumo:
    """O consumo usado no cálculo, com a origem à vista."""

    valor_kml: float | None
    origem: str = ""
    campo: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "valor_kml": self.valor_kml,
            "origem": self.origem,
            "rotulo_da_origem": ROTULO_DA_ORIGEM.get(self.origem, self.origem),
            "campo": self.campo,
        }


@dataclass
class CustoDeUso:
    """O custo mensal de um veículo, ou o motivo de não haver número."""

    version_id: str = ""
    rotulo: str = ""
    combustivel: str = ""
    consumo: Consumo = field(default_factory=lambda: Consumo(None))
    preco_por_litro: float | None = None
    km_mes: float | None = None
    litros_mes: float | None = None
    custo_mes: float | None = None
    custo_ano: float | None = None
    frase: str = ""
    motivo_sem_custo: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "rotulo": self.rotulo,
            "combustivel": self.combustivel,
            "consumo": self.consumo.to_dict(),
            "preco_por_litro": self.preco_por_litro,
            "km_mes": self.km_mes,
            "litros_mes": self.litros_mes,
            "custo_mes": self.custo_mes,
            "custo_ano": self.custo_ano,
            "frase": self.frase,
            "motivo_sem_custo": self.motivo_sem_custo,
        }


def _numero(valor: Any) -> float | None:
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int | float):
        return float(valor)
    if isinstance(valor, str):
        from pipeline.units import parse_number_ptbr

        try:
            return parse_number_ptbr(valor)
        except ValueError:
            return None
    return None


#: Peso de cada ciclo na média ponderada, quando os dois consumos existem.
#:
#: A ponderação urbano/rodoviário é do próprio PBE/Inmetro para o consumo combinado. Está
#: declarada aqui porque uma média simples (50/50) produziria um número que não é o
#: combinado de ninguém e ainda assim pareceria oficial.
PESO_URBANO = 0.55
PESO_RODOVIARIO = 0.45


def consumo_de(
    atributos: dict[str, Any],
    *,
    origem_por_campo: dict[str, str] | None = None,
    informado_kml: float | None = None,
) -> Consumo:
    """Escolhe o consumo a usar, na ordem de `ORIGENS`.

    A média é a **ponderada do PBE** (55% urbano, 45% rodoviário) quando os dois ciclos
    existem; com um só, usa o que existe e diz qual. Uma média 50/50 daria um número que
    não é o combinado de ninguém.
    """
    origens = origem_por_campo or {}
    urbano = _numero(atributos.get("consumo_urbano_kml"))
    rodoviario = _numero(atributos.get("consumo_rodoviario_kml"))

    if urbano is not None and rodoviario is not None:
        origem = (
            origens.get("consumo_urbano_kml") or origens.get("consumo_rodoviario_kml") or "oficial"
        )
        return Consumo(
            round(urbano * PESO_URBANO + rodoviario * PESO_RODOVIARIO, 2),
            origem,
            "consumo_urbano_kml + consumo_rodoviario_kml (55/45, ponderação do PBE)",
        )
    if urbano is not None:
        return Consumo(urbano, origens.get("consumo_urbano_kml", "oficial"), "consumo_urbano_kml")
    if rodoviario is not None:
        return Consumo(
            rodoviario, origens.get("consumo_rodoviario_kml", "oficial"), "consumo_rodoviario_kml"
        )
    if informado_kml is not None:
        return Consumo(float(informado_kml), "informado", "informado pelo vendedor")
    return Consumo(None)


def calcular(
    *,
    atributos: dict[str, Any],
    km_mes: float | None,
    precos: dict[str, float | None],
    version_id: str = "",
    rotulo: str = "",
    informado_kml: float | None = None,
    origem_por_campo: dict[str, str] | None = None,
    data: dt.date | None = None,
) -> CustoDeUso:
    """O custo mensal, ou o motivo de não haver número.

    Falta de qualquer uma das três entradas (km/mês, consumo, preço do combustível **do
    veículo**) deixa `custo_mes = None` com o motivo. Um zero ali seria pior que a
    ausência: apareceria na tela como "custo zero".
    """
    quando = data or dt.date.today()
    combustivel = str(atributos.get("combustivel") or "").strip().lower()
    resultado = CustoDeUso(
        version_id=version_id, rotulo=rotulo, combustivel=combustivel, km_mes=km_mes
    )

    resultado.consumo = consumo_de(
        atributos, origem_por_campo=origem_por_campo, informado_kml=informado_kml
    )

    faltando: list[str] = []
    if km_mes is None or km_mes <= 0:
        faltando.append("km por mês")
    if resultado.consumo.valor_kml is None or resultado.consumo.valor_kml <= 0:
        faltando.append("consumo (nenhuma fonte, e nada informado)")

    chave = COMBUSTIVEL_DO_FLEX if combustivel == "flex" else combustivel
    if combustivel not in COMBUSTIVEIS:
        faltando.append(
            f"combustível do veículo (valor {combustivel or 'ausente'!r} não está em "
            f"{', '.join(COMBUSTIVEIS)})"
        )
    else:
        preco = _numero(precos.get(chave))
        if preco is None or preco <= 0:
            faltando.append(f"preço do {chave} por litro")
        else:
            resultado.preco_por_litro = preco

    if faltando:
        resultado.motivo_sem_custo = "sem custo estimado: falta " + "; falta ".join(faltando)
        return resultado

    litros = (km_mes or 0) / (resultado.consumo.valor_kml or 1)
    resultado.litros_mes = round(litros, 2)
    resultado.custo_mes = round(litros * (resultado.preco_por_litro or 0), 2)
    resultado.custo_ano = round(resultado.custo_mes * 12, 2)
    resultado.frase = FRASE_FIXA.format(
        fonte=ROTULO_DA_ORIGEM.get(resultado.consumo.origem, resultado.consumo.origem),
        data=quando.strftime("%d/%m/%Y"),
    )
    return resultado


@dataclass
class ComparacaoDeCusto:
    """Os dois custos e a diferença anual, que é o número que fecha a conversa."""

    ford: CustoDeUso
    concorrente: CustoDeUso
    diferenca_mes: float | None = None
    diferenca_ano: float | None = None
    quem_gasta_menos: str = ""
    motivo_sem_diferenca: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ford": self.ford.to_dict(),
            "concorrente": self.concorrente.to_dict(),
            "diferenca_mes": self.diferenca_mes,
            "diferenca_ano": self.diferenca_ano,
            "quem_gasta_menos": self.quem_gasta_menos,
            "motivo_sem_diferenca": self.motivo_sem_diferenca,
        }


def comparar(ford: CustoDeUso, concorrente: CustoDeUso) -> ComparacaoDeCusto:
    """A diferença entre os dois custos. Sem os dois números, não há diferença.

    `None` e não zero: zero diria "custam o mesmo", que é uma afirmação — e faltando um dos
    lados não há afirmação a fazer.
    """
    comparacao = ComparacaoDeCusto(ford=ford, concorrente=concorrente)
    if ford.custo_mes is None or concorrente.custo_mes is None:
        faltando = [
            lado
            for lado, custo in (("Ford", ford), ("concorrente", concorrente))
            if custo.custo_mes is None
        ]
        comparacao.motivo_sem_diferenca = (
            f"sem custo estimado para {' e '.join(faltando)}: não há diferença a calcular"
        )
        return comparacao

    comparacao.diferenca_mes = round(ford.custo_mes - concorrente.custo_mes, 2)
    comparacao.diferenca_ano = round(comparacao.diferenca_mes * 12, 2)
    if comparacao.diferenca_mes < 0:
        comparacao.quem_gasta_menos = "ford"
    elif comparacao.diferenca_mes > 0:
        comparacao.quem_gasta_menos = "concorrente"
    else:
        comparacao.quem_gasta_menos = "empate"
    return comparacao
