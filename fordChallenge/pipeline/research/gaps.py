"""As lacunas, e o orçamento — as duas coisas que decidem quando parar.

**A parada é aritmética, e não opinião.** Nos quatro motores de busca estudados em
12/09/2026, a rodada termina quando o modelo diz "acho que já tenho o bastante". Aqui a
pergunta tem resposta exata: *quantos dos 58 campos ainda não têm valor com evidência?*
Um número, calculado sobre o schema, sem chamar ninguém.

Isso muda o que a segunda rodada pergunta. Lá ela repete a busca com outro ângulo; aqui ela
pergunta **pelo que ficou faltando**, e o planejador transforma esses campos em consultas
dirigidas.

**O orçamento é constante de módulo, conferido antes e depois de cada rodada** — o desenho
é do Simplicity, e vale o elogio: a parada macia (o modelo dizendo "suficiente") nunca é a
única parada. Um laço que só termina quando o modelo concorda é um laço que não termina
numa terça-feira ruim.

**E o run diz qual limite o parou.** "Acabou" não é resposta: com três minutos de
orçamento, saber se a pesquisa parou por ter fechado tudo, por ter gastado as doze páginas
ou por ter estourado o relógio é a diferença entre "a fonte não tem" e "não deu tempo".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

from pipeline.schema import GRUPOS, STATUS_SEM_VALOR, StandardSpec, Status

#: Os campos que a pesquisa **não** procura: eles são a entrada dela.
#:
#: Marca, modelo, versão **e ano-modelo** vêm do que a pessoa digitou (ou confirmou na
#: conversa); procurá-los seria perguntar ao buscador algo que já sabemos, e contá-los como
#: lacuna faria a cobertura nunca fechar.
#:
#: O ano entrou na lista em 13/09/2026, por um caso medido: a pesquisa da Triton HPE-S 2026
#: gravou `ano_modelo = 2020` lido de um edital sobre a L200 Triton Sport. A identidade da
#: versão vem da linha do catálogo (`spec_assembler` a rotula CATÁLOGO), não de uma página.
NAO_SE_PROCURA: frozenset[str] = frozenset({"marca", "modelo", "versao", "ano_modelo"})


class Motivo(StrEnum):
    """Por que o run parou. **Sempre** um destes, e sempre dito na tela."""

    COBERTURA = "cobertura"
    """Não sobrou lacuna que uma consulta nova pudesse fechar."""

    SEM_PROGRESSO = "sem_progresso"
    """A rodada não preencheu nenhum campo novo. Insistir custaria e não renderia."""

    RODADAS = "rodadas"
    PAGINAS = "paginas"
    TEMPO = "tempo"

    MODELO_SEM_SALDO = "modelo_sem_saldo"
    """O modelo recusou por saldo ou cota — nas duas contas, quando há duas. Esperar não
    resolve saldo, e insistir só repetiria o erro; a ficha sai com o que a regra leu."""

    TETO_DE_GASTO = "teto_de_gasto"
    """O teto de gasto desta máquina (`LLM_TETO_USD`) foi batido. Nenhuma chamada saiu."""

    TETO_SERVICOS = "teto_servicos"
    """A próxima busca excederia o teto de chamadas ou custo desta execução."""


@dataclass
class Orcamento:
    """Os limites da pesquisa. Os padrões são os da demonstração de 15/09.

    **Três minutos** porque é quanto tempo alguém olha uma tela de progresso antes de achar
    que travou; **doze páginas** porque é o que cabe em três minutos a 1 req/s por domínio
    com a coleta educada; **duas rodadas** porque a terceira, medida nos ensaios, fecha
    menos campos do que a segunda e gasta o mesmo.
    """

    rodadas: int = 2
    paginas: int = 12
    segundos: float = 180.0
    chamadas_llm: int = 4
    """Quantas vezes a pesquisa pode chamar o modelo. **Quatro**, medido em 13/09/2026:
    com o raciocínio desligado uma extração leva ~30 s, e quatro cabem nos três minutos
    junto com a coleta. A regra por regex lê **todas** as páginas; o modelo só entra nas
    de maior tier. Gastar a cota não para a pesquisa — só desliga o modelo para as
    páginas seguintes, e a trilha diz isso."""

    _inicio: float = field(default_factory=time.monotonic, repr=False)
    rodadas_gastas: int = 0
    paginas_gastas: int = 0
    chamadas_llm_gastas: int = 0

    @property
    def decorrido(self) -> float:
        return round(time.monotonic() - self._inicio, 2)

    @property
    def paginas_restantes(self) -> int:
        return max(0, self.paginas - self.paginas_gastas)

    @property
    def chamadas_llm_restantes(self) -> int:
        return max(0, self.chamadas_llm - self.chamadas_llm_gastas)

    def estourou(self) -> Motivo | None:
        """O limite atingido, ou `None`. Conferido **antes e depois** de cada rodada."""
        if self.decorrido >= self.segundos:
            return Motivo.TEMPO
        if self.rodadas_gastas >= self.rodadas:
            return Motivo.RODADAS
        if self.paginas_gastas >= self.paginas:
            return Motivo.PAGINAS
        return None

    def estourou_na_coleta(self) -> Motivo | None:
        """O limite que vale **no meio da coleta**: páginas e tempo. Rodadas, não.

        Defeito medido em 13/09/2026: `estourou()` era conferido antes de cada página e
        inclui o limite de rodadas — e a rodada em curso já conta como gasta. Na última
        rodada permitida (a segunda, no padrão da demo), a coleta era abortada antes de
        baixar a primeira página: **a segunda rodada nunca coletou nada**, e as consultas
        de lacuna que ela planejava eram desperdiçadas em silêncio.
        """
        if self.paginas_gastas >= self.paginas:
            return Motivo.PAGINAS
        if self.decorrido >= self.segundos:
            return Motivo.TEMPO
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "rodadas": self.rodadas,
            "paginas": self.paginas,
            "segundos": self.segundos,
            "rodadas_gastas": self.rodadas_gastas,
            "paginas_gastas": self.paginas_gastas,
            "decorrido": self.decorrido,
            "chamadas_llm": self.chamadas_llm,
            "chamadas_llm_gastas": self.chamadas_llm_gastas,
        }


@dataclass(frozen=True)
class Cobertura:
    """Quantos campos a ficha respondeu, e quais ainda não.

    `verificados` conta só campo **com valor**. `nao_disponivel` não entra: a montadora
    afirmar que a versão não tem reboque é uma resposta boa — e continuar procurando por
    ela seria gastar página para confirmar uma ausência que a fonte já declarou.
    """

    total: int
    com_valor: int
    declarados_ausentes: int
    faltando: tuple[str, ...]
    conflitos: int = 0

    @property
    def fracao(self) -> float:
        return round(self.com_valor / self.total, 4) if self.total else 0.0

    @property
    def respondidos(self) -> int:
        """Com valor **mais** os que a fonte declarou não existir. Os dois são resposta."""
        return self.com_valor + self.declarados_ausentes

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "com_valor": self.com_valor,
            "declarados_ausentes": self.declarados_ausentes,
            "respondidos": self.respondidos,
            "fracao": self.fracao,
            "faltando": list(self.faltando),
            "conflitos": self.conflitos,
            "resolucao": round(self.respondidos / self.total, 4) if self.total else 0,
            "precisao_auditada": None,
        }


def campos_procuraveis(alvo: list[str] | None = None) -> list[str]:
    """Os campos que a pesquisa persegue: os canônicos, menos a identidade do pedido."""
    todos = [c for campos in GRUPOS.values() for c in campos if c not in NAO_SE_PROCURA]
    if alvo:
        pedidos = set(alvo)
        return [c for c in todos if c in pedidos]
    return todos


def medir(spec: StandardSpec, alvo: list[str] | None = None) -> Cobertura:
    """A cobertura da ficha, campo a campo. **Sem chamar ninguém.**"""
    procuraveis = campos_procuraveis(alvo)
    dados = spec.model_dump()

    com_valor = 0
    ausentes = 0
    conflitos = 0
    faltando: list[str] = []
    for campo in procuraveis:
        celula = _celula(dados, campo)
        if celula is None:
            faltando.append(campo)
            continue
        if celula.get("value") is not None and celula.get("status") == Status.VERIFICADO.value:
            com_valor += 1
        elif celula.get("status") == Status.NAO_DISPONIVEL.value:
            # A fonte disse que não tem. É resposta, e procurar mais seria gastar página
            # para confirmar uma ausência já declarada.
            ausentes += 1
        else:
            faltando.append(campo)
            conflitos += int(celula.get("status") == Status.DIVERGENTE.value)

    return Cobertura(
        total=len(procuraveis),
        com_valor=com_valor,
        declarados_ausentes=ausentes,
        faltando=tuple(faltando),
        conflitos=conflitos,
    )


def _celula(dados: dict, campo: str) -> dict | None:
    for grupo, campos in GRUPOS.items():
        if campo in campos:
            valor = dados.get(grupo, {}).get(campo)
            return valor if isinstance(valor, dict) else None
    return None


def vale_outra_rodada(
    antes: Cobertura, depois: Cobertura, orcamento: Orcamento
) -> tuple[bool, Motivo | None]:
    """Vale gastar mais uma rodada? E, se não vale, **por quê**.

    A ordem das perguntas importa e é deliberada:

    1. **o orçamento estourou?** — o limite duro vem antes de qualquer julgamento;
    2. **sobrou lacuna?** — se não, a pesquisa terminou por cobertura, que é o bom final;
    3. **a rodada rendeu?** — uma rodada que não preencheu **nenhum** campo novo é o sinal
       mais honesto de que a fonte não tem o que falta. Insistir custa e não rende, e o
       custo sai do orçamento da próxima pesquisa.
    """
    estouro = orcamento.estourou()
    if estouro is not None:
        return False, estouro
    if not depois.faltando:
        return False, Motivo.COBERTURA
    if depois.com_valor <= antes.com_valor:
        return False, Motivo.SEM_PROGRESSO
    return True, None


def explicar(motivo: Motivo, cobertura: Cobertura, orcamento: Orcamento) -> str:
    """A frase que a tela mostra. Em português de quem vende, não de quem opera."""
    if motivo is Motivo.COBERTURA:
        return (
            f"pesquisa concluída: {cobertura.respondidos} de {cobertura.total} campos "
            "respondidos, e não sobrou nenhum que uma busca nova pudesse fechar"
        )
    if motivo is Motivo.SEM_PROGRESSO:
        return (
            f"a última rodada não preencheu nenhum campo novo; {len(cobertura.faltando)} "
            "campo(s) seguem sem valor nas fontes consultadas"
        )
    if motivo is Motivo.RODADAS:
        return f"limite de {orcamento.rodadas} rodada(s) de busca atingido"
    if motivo is Motivo.PAGINAS:
        return f"limite de {orcamento.paginas} página(s) coletadas atingido"
    if motivo is Motivo.MODELO_SEM_SALDO:
        return (
            "o modelo de linguagem recusou a chamada por falta de saldo ou cota na(s) "
            "conta(s) configurada(s); a pesquisa parou para não repetir o erro — "
            f"{cobertura.com_valor} campo(s) vieram só da leitura por regra"
        )
    if motivo is Motivo.TETO_DE_GASTO:
        return (
            "o teto de gasto com modelo desta máquina foi atingido e nenhuma chamada saiu; "
            f"{cobertura.com_valor} campo(s) vieram só da leitura por regra"
        )
    if motivo is Motivo.TETO_SERVICOS:
        return (
            "o limite de consultas ou custo da busca foi atingido; "
            f"{cobertura.com_valor} campo(s) têm valor nas fontes já consultadas"
        )
    return f"limite de {orcamento.segundos:.0f} segundos atingido"


__all__ = [
    "NAO_SE_PROCURA",
    "STATUS_SEM_VALOR",
    "Cobertura",
    "Motivo",
    "Orcamento",
    "campos_procuraveis",
    "explicar",
    "medir",
    "vale_outra_rodada",
]
