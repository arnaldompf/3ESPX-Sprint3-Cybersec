"""Saúde do Conhecimento: **quão confiável está a informação usada para decidir**.

O conhecimento competitivo é ativo que degrada. Um preço coletado em julho não fica errado
— fica **velho**, e a diferença entre as duas coisas é o que este módulo mede. A pergunta
que ele responde é operacional: "posso entrar numa reunião com esta ficha, ou preciso
reconferir alguma coisa antes?".

**O que este número NÃO é.** Ele não é probabilidade de a ficha estar certa. `docs/13` §3
pede o texto fixo, e ele está em :data:`TEXTO_FIXO` sem paráfrase possível: "indicador
operacional do MVP, não probabilidade de verdade". A distinção é a diferença entre um
painel útil e um número inventado — "89% verdadeiro" seria estatística sem estudo por
trás, e o projeto proíbe estatística inventada.

Três decisões:

* **cada indicador vem com o denominador e com a lista dos campos que o compõem.** "12
  campos desatualizados" manda alguém procurar; "12 de 58, e são estes" manda alguém
  resolver. É a mesma regra dos denominadores visíveis do eval;
* **as regras do status são dados**, não `if` espalhado: :data:`REGRAS_DO_STATUS` é uma
  tupla de regras com nome, condição e explicação, e a API devolve **qual regra decidiu**.
  Um status sem regra à vista é um oráculo, e ninguém audita oráculo;
* **`nao_confirmado` conta só T3/T4.** Um campo cuja única fonte é imprensa (tier 3) ou
  material interno (tier 4) está num estado diferente de um campo com a página oficial
  atrás: os dois têm valor e evidência, mas só um foi dito pela montadora.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

#: O texto que acompanha **todo** indicador de saúde exibido. `docs/13` §3, literal.
TEXTO_FIXO = "indicador operacional do MVP, não probabilidade de verdade"

#: Os três estados. Vocabulário fechado: a tela pinta por eles.
OK = "OK"
REVISAR = "REVISAR"
INSUFICIENTE = "INSUFICIENTE"
STATUS = (OK, REVISAR, INSUFICIENTE)

#: Tiers que **não** confirmam por si: imprensa (3) e referência interna (4).
TIERS_NAO_CONFIRMATORIOS = frozenset({3, 4, 5})

#: Abaixo desta fração de campos verificados a ficha é INSUFICIENTE para decidir.
#:
#: Metade, e o número é uma escolha declarada, não medida — não há amostra que a
#: justifique. O que a sustenta é o uso: com menos da metade dos campos verificados, a
#: comparação lado a lado fica mais cheia de "não sabemos" do que de valores, e o problema
#: deixa de ser confiança e passa a ser cobertura.
FRACAO_MINIMA_PARA_DECIDIR = 0.5


@dataclass
class CampoComProblema:
    """Um campo que puxa a saúde para baixo, **com o motivo**.

    Existe para o painel poder responder "por que este campo falta?", que é a nota da spec.
    Um contador sozinho mandaria alguém abrir 58 campos para descobrir quais são.
    """

    campo: str
    motivo: str
    detalhe: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"campo": self.campo, "motivo": self.motivo, "detalhe": self.detalhe}


@dataclass
class Indicador:
    """Um número com o denominador ao lado. Nunca só o número."""

    valor: int
    de: int
    campos: list[CampoComProblema] = field(default_factory=list)

    @property
    def fracao(self) -> float | None:
        """`None` quando o denominador é zero — e `None` não é `0.0`."""
        return (self.valor / self.de) if self.de else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valor": self.valor,
            "de": self.de,
            "fracao": self.fracao,
            "campos": [c.to_dict() for c in self.campos],
        }


@dataclass
class SaudeDaVersao:
    """A saúde de uma versão, indicador por indicador, com a regra que decidiu o status."""

    version_id: str
    rotulo: str = ""
    verificados: Indicador = field(default_factory=lambda: Indicador(0, 0))
    desatualizados: Indicador = field(default_factory=lambda: Indicador(0, 0))
    conflitos: Indicador = field(default_factory=lambda: Indicador(0, 0))
    nao_confirmados: Indicador = field(default_factory=lambda: Indicador(0, 0))
    fontes_bloqueadas: Indicador = field(default_factory=lambda: Indicador(0, 0))
    ultima_atualizacao: str | None = None
    status: str = INSUFICIENTE
    regra_do_status: str = ""
    explicacao_do_status: str = ""
    limiar_de_dias: int = 30
    texto_fixo: str = TEXTO_FIXO

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "rotulo": self.rotulo,
            "verificados": self.verificados.to_dict(),
            "desatualizados": self.desatualizados.to_dict(),
            "conflitos": self.conflitos.to_dict(),
            "nao_confirmados": self.nao_confirmados.to_dict(),
            "fontes_bloqueadas": self.fontes_bloqueadas.to_dict(),
            "ultima_atualizacao": self.ultima_atualizacao,
            "status": self.status,
            "regra_do_status": self.regra_do_status,
            "explicacao_do_status": self.explicacao_do_status,
            "limiar_de_dias": self.limiar_de_dias,
            "texto_fixo": self.texto_fixo,
        }


@dataclass(frozen=True)
class RegraDeStatus:
    """Uma regra do status: nome, condição e a explicação que vai para a tela."""

    nome: str
    status: str
    condicao: Callable[[SaudeDaVersao], bool]
    explicacao: str


#: As regras, **na ordem em que são testadas**. A primeira que casa decide, e o nome dela
#: viaja na resposta.
#:
#: A ordem é a regra: "sem campo nenhum" tem de vencer "tem conflito", senão uma ficha
#: vazia sairia como OK por não ter conflito — o pior dos resultados possíveis, porque
#: nada acusa.
REGRAS_DO_STATUS: tuple[RegraDeStatus, ...] = (
    RegraDeStatus(
        nome="sem_campos",
        status=INSUFICIENTE,
        condicao=lambda s: s.verificados.de == 0,
        explicacao=(
            "Nenhum campo foi coletado para esta versão. Rode a extração antes de usar "
            "esta ficha para decidir."
        ),
    ),
    RegraDeStatus(
        nome="poucos_verificados",
        status=INSUFICIENTE,
        condicao=lambda s: (s.verificados.fracao or 0) < FRACAO_MINIMA_PARA_DECIDIR,
        explicacao=(
            "Menos da metade dos campos tem valor verificado. O problema aqui é de "
            "cobertura, não de confiança: falta coletar."
        ),
    ),
    RegraDeStatus(
        nome="tem_conflito",
        status=REVISAR,
        condicao=lambda s: s.conflitos.valor > 0,
        explicacao=(
            "Fontes discordam em pelo menos um campo. Os dois valores estão na ficha, com "
            "evidência; alguém precisa decidir qual vale antes de levar o número a uma "
            "reunião."
        ),
    ),
    RegraDeStatus(
        nome="tem_desatualizado",
        status=REVISAR,
        condicao=lambda s: s.desatualizados.valor > 0,
        explicacao=(
            "Há campo cuja evidência passou do limiar de dias. Não está errado — está "
            "velho, e preço de tabela é o que envelhece mais rápido."
        ),
    ),
    RegraDeStatus(
        nome="tem_fonte_bloqueada",
        status=REVISAR,
        condicao=lambda s: s.fontes_bloqueadas.valor > 0,
        explicacao=(
            "Uma fonte fechou a porta (403, CAPTCHA ou paywall) e ficou registrada como "
            "bloqueada. O campo que dependia dela é `nao_encontrado` por causa disso, e "
            "não por a informação não existir."
        ),
    ),
    RegraDeStatus(
        nome="tem_nao_confirmado",
        status=REVISAR,
        condicao=lambda s: s.nao_confirmados.valor > 0,
        explicacao=(
            "Há campo cuja única fonte é imprensa ou material interno. Tem valor e tem "
            "evidência, mas não foi a montadora que disse."
        ),
    ),
    RegraDeStatus(
        nome="sem_pendencia",
        status=OK,
        condicao=lambda _: True,
        explicacao=(
            "Nenhuma pendência nos indicadores acima. Continua sendo indicador "
            "operacional: ele diz que não há sinal de degradação, não que a ficha está "
            "certa."
        ),
    ),
)


@dataclass
class LinhaDeCampo:
    """O que a saúde precisa saber de um campo. Independente de ORM de propósito.

    Assim a regra é testável com dicionários e o mesmo cálculo serve para o banco, para um
    `StandardSpec` em memória e para o relatório do eval.
    """

    campo: str
    status: str
    tier: int | None = None
    captured_at: dt.datetime | None = None
    source_url: str = ""


def _idade_em_dias(quando: dt.datetime | None, *, agora: dt.datetime) -> int | None:
    if quando is None:
        return None
    referencia = quando if quando.tzinfo is None else quando.astimezone(dt.UTC).replace(tzinfo=None)
    return max(0, (agora - referencia).days)


def avaliar(
    linhas: Sequence[LinhaDeCampo],
    *,
    version_id: str = "",
    rotulo: str = "",
    bloqueadas: Iterable[str] = (),
    limiar_de_dias: int = 30,
    agora: dt.datetime | None = None,
) -> SaudeDaVersao:
    """Calcula a saúde a partir das linhas de campo. Função pura.

    `linhas` traz **uma linha por campo** (não por valor): um campo `divergente` com três
    valores concorrentes é **um** conflito, não três. Contar por valor faria o painel
    parecer três vezes pior a cada fonte nova consultada, o que puniria justamente o
    comportamento que se quer.
    """
    momento = agora or dt.datetime.now(dt.UTC).replace(tzinfo=None)
    saude = SaudeDaVersao(version_id=version_id, rotulo=rotulo, limiar_de_dias=limiar_de_dias)

    total = len(linhas)
    com_valor = [linha for linha in linhas if linha.status in {"verificado", "divergente"}]

    saude.verificados = Indicador(
        valor=sum(linha.status == "verificado" for linha in linhas), de=total
    )

    desatualizados: list[CampoComProblema] = []
    nao_confirmados: list[CampoComProblema] = []
    conflitos: list[CampoComProblema] = []

    for linha in com_valor:
        idade = _idade_em_dias(linha.captured_at, agora=momento)
        if idade is None:
            # Sem data de coleta não se afirma "atualizado" nem "velho": o campo entra
            # como desatualizado com o motivo dito. Chamá-lo de atual seria assumir que a
            # coleta é de hoje sem nenhuma evidência disso.
            desatualizados.append(
                CampoComProblema(
                    linha.campo,
                    "sem data de coleta",
                    "a evidência não registra `captured_at`; não é possível dizer se está atual",
                )
            )
        elif idade > limiar_de_dias:
            desatualizados.append(
                CampoComProblema(
                    linha.campo,
                    f"coletado há {idade} dias",
                    f"acima do limiar de {limiar_de_dias} dias ({linha.source_url})",
                )
            )

        if linha.tier is not None and linha.tier in TIERS_NAO_CONFIRMATORIOS:
            nao_confirmados.append(
                CampoComProblema(
                    linha.campo,
                    f"única fonte é tier {linha.tier}",
                    "imprensa ou material interno: tem evidência, mas não é a montadora",
                )
            )

        if linha.status == "divergente":
            conflitos.append(
                CampoComProblema(
                    linha.campo,
                    "fontes discordam",
                    "os valores concorrentes estão na ficha, cada um com a sua evidência",
                )
            )

    saude.desatualizados = Indicador(len(desatualizados), len(com_valor), desatualizados)
    saude.nao_confirmados = Indicador(len(nao_confirmados), len(com_valor), nao_confirmados)
    saude.conflitos = Indicador(len(conflitos), len(com_valor), conflitos)

    urls = list(dict.fromkeys(bloqueadas))
    saude.fontes_bloqueadas = Indicador(
        len(urls),
        len(urls),
        [
            CampoComProblema(
                url,
                "fonte bloqueada",
                "403, CAPTCHA ou paywall: registrada como bloqueada, nunca contornada",
            )
            for url in urls
        ],
    )

    datas = [linha.captured_at for linha in com_valor if linha.captured_at is not None]
    saude.ultima_atualizacao = max(datas).isoformat() if datas else None

    for regra in REGRAS_DO_STATUS:
        if regra.condicao(saude):
            saude.status = regra.status
            saude.regra_do_status = regra.nome
            saude.explicacao_do_status = regra.explicacao
            break

    return saude


# --------------------------------------------------------------------------- cobertura
@dataclass
class CoberturaDaMarca:
    """Cobertura por montadora. Todos os indicadores com `de` ao lado."""

    marca: str
    versoes_mapeadas: int = 0
    versoes_com_ficha: int = 0
    campos_com_fonte_oficial: Indicador = field(default_factory=lambda: Indicador(0, 0))
    nao_encontrados: Indicador = field(default_factory=lambda: Indicador(0, 0))
    divergencias: Indicador = field(default_factory=lambda: Indicador(0, 0))
    por_campo: dict[str, Indicador] = field(default_factory=dict)
    """Cobertura de campos específicos (ex.: `potencia_rpm`), para a pergunta "quem publica
    rotação?" ter resposta sem abrir 58 fichas."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "marca": self.marca,
            "versoes_mapeadas": self.versoes_mapeadas,
            "versoes_com_ficha": self.versoes_com_ficha,
            "campos_com_fonte_oficial": self.campos_com_fonte_oficial.to_dict(),
            "nao_encontrados": self.nao_encontrados.to_dict(),
            "divergencias": self.divergencias.to_dict(),
            "por_campo": {k: v.to_dict() for k, v in self.por_campo.items()},
        }


#: Tier de fonte **oficial da montadora**. `docs/03`: 1 é a montadora.
TIER_OFICIAL = 1

#: Campos que a cobertura reporta um a um, porque a pergunta aparece sozinha.
#:
#: `potencia_rpm` e `torque_rpm` estão aqui por um motivo concreto medido nesta base: a
#: Toyota publica rotação na ficha, e Ford, VW e GM não. É informação sobre **a fonte**,
#: não sobre o carro — e é ela que explica por que a matriz de paridade mostra
#: `desconhecido` em rpm para três das quatro marcas.
CAMPOS_DESTACADOS = ("potencia_rpm", "torque_rpm", "capacidade_carga_kg", "preco_sugerido_brl")
