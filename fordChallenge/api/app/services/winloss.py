"""Win/Loss: o que as sessões de showroom dizem, **com o `n` sempre à vista**.

A regra que molda o módulo é a de `docs/12` §6.5: **percentual só com `n ≥ 20`**. Abaixo
disso, contagens. "67% de perda para a Hilux" sobre três sessões é um número que parece
estatística e é ruído — e é justamente o tipo de número que vira slide e depois vira
decisão. Com `n` pequeno o painel diz "2 de 3", que é a mesma informação sem a falsa
precisão.

**Simulado nunca se mistura com real.** As duas populações são calculadas separadamente e
devolvidas em blocos distintos, cada um com o seu `n`. Uma média ponderada das duas seria
impossível de desfazer depois, e a demo tem 60 sessões semeadas contra as poucas reais —
o real desapareceria dentro do simulado.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, select

from api.app.models import Brand, ShowroomSession, VehicleModel, Version

#: Mínimo de sessões para o painel exibir percentual. `docs/12` §6.5.
#:
#: Vinte, e o número é da spec. A razão de ele existir é a de sempre: um percentual sobre
#: cinco casos tem intervalo de confiança tão largo que a informação está no denominador,
#: não na fração.
N_MINIMO_PARA_PERCENTUAL = 20

#: O texto que acompanha todo bloco de dado simulado. `docs/13` §2.
ROTULO_SIMULACAO = "SIMULAÇÃO — dados de demonstração"

#: O texto que acompanha todo bloco com `n` abaixo do mínimo.
AVISO_N_PEQUENO = (
    "menos de {minimo} sessões: o painel mostra contagens, não percentuais. Um percentual "
    "sobre {n} caso(s) pareceria estatística e seria ruído."
)


@dataclass
class Contagem:
    """Uma contagem com o denominador, e o percentual **só** quando `n` permite."""

    valor: int
    de: int

    @property
    def percentual(self) -> float | None:
        """`None` quando `de < N_MINIMO_PARA_PERCENTUAL`. Ver o docstring do módulo."""
        if self.de < N_MINIMO_PARA_PERCENTUAL or self.de == 0:
            return None
        return round(self.valor / self.de * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {"valor": self.valor, "de": self.de, "percentual": self.percentual}


@dataclass
class PorConcorrente:
    """O que se sabe sobre um concorrente, a partir das sessões registradas."""

    version_id: str
    rotulo: str
    n: int = 0
    fechou: Contagem = field(default_factory=lambda: Contagem(0, 0))
    perdeu: Contagem = field(default_factory=lambda: Contagem(0, 0))
    em_andamento: Contagem = field(default_factory=lambda: Contagem(0, 0))
    top_motivos: list[dict[str, Any]] = field(default_factory=list)
    top_atributos_decisivos: list[dict[str, Any]] = field(default_factory=list)
    perfis: list[dict[str, Any]] = field(default_factory=list)
    mostra_percentual: bool = False
    aviso: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "rotulo": self.rotulo,
            "n": self.n,
            "fechou": self.fechou.to_dict(),
            "perdeu": self.perdeu.to_dict(),
            "em_andamento": self.em_andamento.to_dict(),
            "top_motivos": list(self.top_motivos),
            "top_atributos_decisivos": list(self.top_atributos_decisivos),
            "perfis": list(self.perfis),
            "mostra_percentual": self.mostra_percentual,
            "aviso": self.aviso,
        }


@dataclass
class Painel:
    """Os dois blocos: real e simulado, cada um com o seu `n`. Nunca somados."""

    real: list[PorConcorrente] = field(default_factory=list)
    simulado: list[PorConcorrente] = field(default_factory=list)
    n_real: int = 0
    n_simulado: int = 0
    rotulo_simulacao: str = ROTULO_SIMULACAO
    n_minimo_para_percentual: int = N_MINIMO_PARA_PERCENTUAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "real": [c.to_dict() for c in self.real],
            "simulado": [c.to_dict() for c in self.simulado],
            "n_real": self.n_real,
            "n_simulado": self.n_simulado,
            "rotulo_simulacao": self.rotulo_simulacao,
            "n_minimo_para_percentual": self.n_minimo_para_percentual,
        }


def _rotulo(sessao: Session, version_id: str) -> str:
    version = sessao.get(Version, version_id)
    if version is None:
        return version_id
    modelo = sessao.get(VehicleModel, version.model_id)
    marca = sessao.get(Brand, modelo.brand_id) if modelo else None
    partes = [p for p in (marca.nome if marca else "", modelo.nome if modelo else "") if p]
    return " ".join([*partes, version.nome_exato]).strip()


def _top(contador: Counter, *, limite: int = 3) -> list[dict[str, Any]]:
    """Os mais frequentes, **com a contagem**. Nunca só o nome.

    "Top motivo: preço" não diz se foram 12 sessões ou 2. A contagem é o que separa um
    padrão de uma coincidência.
    """
    return [{"chave": chave, "n": n} for chave, n in contador.most_common(limite)]


def _agregar(sessao: Session, sessoes: list[ShowroomSession]) -> list[PorConcorrente]:
    """Agrupa as sessões por concorrente. Uma sessão com dois concorrentes conta nos dois.

    Isso é deliberado e precisa ser dito: `n` por concorrente **não** soma o total de
    sessões. O vendedor comparou a Ranger com duas picapes na mesma conversa, e o desfecho
    daquela conversa informa as duas — o que não se pode fazer é somar os `n` e apresentar
    o resultado como número de atendimentos.
    """
    por_id: dict[str, list[ShowroomSession]] = {}
    for linha in sessoes:
        for version_id in linha.competitor_version_ids or []:
            por_id.setdefault(version_id, []).append(linha)

    saida: list[PorConcorrente] = []
    for version_id, linhas in por_id.items():
        n = len(linhas)
        desfechos = Counter(linha.outcome for linha in linhas)
        motivos: Counter = Counter()
        atributos: Counter = Counter()
        perfis: Counter = Counter()
        for linha in linhas:
            # Só a sessão perdida informa motivo de perda. Contar o motivo de uma venda
            # fechada misturaria "o que pesou contra" com "o que o cliente comentou".
            if linha.outcome == "perdeu":
                motivos.update(linha.motivos or [])
            if linha.atributo_decisivo:
                atributos.update([linha.atributo_decisivo])
            for uso in (linha.needs_profile_json or {}).get("uso", []) or []:
                perfis.update([uso])

        resultado = PorConcorrente(
            version_id=version_id,
            rotulo=_rotulo(sessao, version_id),
            n=n,
            fechou=Contagem(desfechos.get("fechou", 0), n),
            perdeu=Contagem(desfechos.get("perdeu", 0), n),
            em_andamento=Contagem(desfechos.get("em_andamento", 0), n),
            top_motivos=_top(motivos),
            top_atributos_decisivos=_top(atributos),
            perfis=_top(perfis, limite=5),
            mostra_percentual=n >= N_MINIMO_PARA_PERCENTUAL,
        )
        if not resultado.mostra_percentual:
            resultado.aviso = AVISO_N_PEQUENO.format(minimo=N_MINIMO_PARA_PERCENTUAL, n=n)
        saida.append(resultado)

    saida.sort(key=lambda c: (-c.n, c.rotulo))
    return saida


def painel(
    sessao: Session,
    *,
    ford_version: str | None = None,
    since: dt.datetime | None = None,
    vendedor_id: str | None = None,
) -> Painel:
    """O painel completo. `vendedor_id` limita ao escopo `proprios` de `docs/12` §6.6."""
    consulta = select(ShowroomSession)
    if ford_version:
        consulta = consulta.where(ShowroomSession.ford_version_id == ford_version)
    if since is not None:
        consulta = consulta.where(ShowroomSession.created_at >= since)
    if vendedor_id:
        consulta = consulta.where(ShowroomSession.vendedor_id == vendedor_id)

    todas = list(sessao.exec(consulta).all())
    reais = [s for s in todas if not s.is_simulated]
    simuladas = [s for s in todas if s.is_simulated]

    return Painel(
        real=_agregar(sessao, reais),
        simulado=_agregar(sessao, simuladas),
        n_real=len(reais),
        n_simulado=len(simuladas),
    )


def resumo(
    sessao: Session,
    *,
    since: dt.datetime | None = None,
    vendedor_id: str | None = None,
) -> dict[str, Any]:
    """O resumo geral: totais por desfecho, motivos e atributos, real e simulado à parte."""
    consulta = select(ShowroomSession)
    if since is not None:
        consulta = consulta.where(ShowroomSession.created_at >= since)
    if vendedor_id:
        consulta = consulta.where(ShowroomSession.vendedor_id == vendedor_id)
    todas = list(sessao.exec(consulta).all())

    def bloco(linhas: list[ShowroomSession]) -> dict[str, Any]:
        n = len(linhas)
        desfechos = Counter(linha.outcome for linha in linhas)
        motivos: Counter = Counter()
        atributos: Counter = Counter()
        for linha in linhas:
            if linha.outcome == "perdeu":
                motivos.update(linha.motivos or [])
            if linha.atributo_decisivo:
                atributos.update([linha.atributo_decisivo])
        return {
            "n": n,
            "fechou": Contagem(desfechos.get("fechou", 0), n).to_dict(),
            "perdeu": Contagem(desfechos.get("perdeu", 0), n).to_dict(),
            "em_andamento": Contagem(desfechos.get("em_andamento", 0), n).to_dict(),
            "top_motivos": _top(motivos, limite=5),
            "top_atributos_decisivos": _top(atributos, limite=5),
            "mostra_percentual": n >= N_MINIMO_PARA_PERCENTUAL,
            "aviso": (
                ""
                if n >= N_MINIMO_PARA_PERCENTUAL
                else AVISO_N_PEQUENO.format(minimo=N_MINIMO_PARA_PERCENTUAL, n=n)
            ),
        }

    return {
        "real": bloco([s for s in todas if not s.is_simulated]),
        "simulado": bloco([s for s in todas if s.is_simulated]),
        "rotulo_simulacao": ROTULO_SIMULACAO,
        "n_minimo_para_percentual": N_MINIMO_PARA_PERCENTUAL,
    }
