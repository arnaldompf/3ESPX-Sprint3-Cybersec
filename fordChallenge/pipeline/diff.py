"""Diff entre duas fichas da mesma versão, e os alertas que ele gera.

O que este módulo existe para responder: *"o que mudou desde a última coleta?"* — e a
resposta tem de ser útil sem ser barulhenta. Duas regras seguram o barulho:

* **campo que não tinha valor e continua sem valor não é mudança.** Um alerta por
  `nao_encontrado` → `nao_encontrado` treinaria o usuário a ignorar alertas;
* **`desconhecido` nunca vira lacuna, e mudança de status sem mudança de valor é um
  alerta de outra natureza** (`status`), separada de `valor`. Um preço que trocou de
  `verificado` para `divergente` mantendo o número é notícia — mas não é "o preço subiu".

`alert.type` sai da natureza do campo (`preco` para os campos comerciais, `spec` para o
resto), porque é assim que a watchlist da WP-25 vai filtrar. O `alerta.quote` traz a citação
da evidência do valor **novo**: um alerta nasce provável, não como boato.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.eval.compare import comparar_valor
from pipeline.schema import STATUS_SEM_VALOR, StandardSpec

#: Campos cuja mudança é notícia comercial, não técnica. A watchlist filtra por isto.
CAMPOS_DE_PRECO = frozenset(
    {"preco_sugerido_brl", "preco_fipe_brl", "fipe_referencia", "preco_data"}
)


@dataclass
class Alerta:
    """Uma mudança digna de aviso, com o antes e o depois à vista."""

    type: str
    field: str
    old: Any = None
    new: Any = None
    old_status: str = ""
    new_status: str = ""
    quote: str = ""
    motivo: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "field": self.field,
            "old": self.old,
            "new": self.new,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "quote": self.quote,
            "motivo": self.motivo,
        }


@dataclass
class Diff:
    """O resultado da comparação, separado por natureza da mudança."""

    alertas: list[Alerta] = field(default_factory=list)
    inalterados: int = 0

    @property
    def de_preco(self) -> list[Alerta]:
        return [a for a in self.alertas if a.type == "preco"]

    def por_campo(self, campo: str) -> list[Alerta]:
        return [a for a in self.alertas if a.field == campo]


def _tipo_de(campo: str) -> str:
    return "preco" if campo in CAMPOS_DE_PRECO else "spec"


def _primeira_citacao(campo) -> str:
    """O trecho que sustenta o valor **novo**. Vazio quando o campo perdeu o valor."""
    return campo.evidences[0].quote if campo.evidences else ""


def comparar(anterior: StandardSpec, atual: StandardSpec) -> Diff:
    """Compara duas fichas da mesma versão e devolve os alertas.

    A comparação de valor usa a **mesma** função do eval (`comparar_valor`), e não um
    `!=`. Sem isso, `397` e `397.0` viravam alerta de mudança de potência, e a tolerância
    numérica que o eval aplica para *não* reprovar um acerto teria de ser reimplementada
    aqui — com a chance de divergir dela.
    """
    diff = Diff()
    for caminho, campo_atual in atual.itens():
        nome = caminho.split(".", 1)[-1]
        campo_antes = anterior.get(caminho)
        if campo_antes is None:
            continue

        status_antes, status_agora = str(campo_antes.status), str(campo_atual.status)
        sem_valor_antes = status_antes in STATUS_SEM_VALOR and campo_antes.value is None
        sem_valor_agora = status_agora in STATUS_SEM_VALOR and campo_atual.value is None

        # Vazio → vazio, do mesmo tipo: nada a anunciar. Se o *tipo* de vazio mudou
        # (`nao_encontrado` → `nao_disponivel`), a notícia entra como alerta de status.
        if sem_valor_antes and sem_valor_agora and status_antes == status_agora:
            diff.inalterados += 1
            continue

        # Dois vazios não são "valores diferentes": um alerta com `old=None, new=None`
        # não diz nada a quem o recebe. O que mudou aí é o **tipo** de vazio, e isso sai
        # como alerta de status logo abaixo. `comparar_valor` não responde isso por nós:
        # ela compara valores, e para ela `None` não é igual a `None`.
        if campo_antes.value is None and campo_atual.value is None:
            mudou_valor = False
        else:
            mudou_valor = not comparar_valor(nome, campo_antes.value, campo_atual.value).igual
        if mudou_valor:
            diff.alertas.append(
                Alerta(
                    type=_tipo_de(nome),
                    field=nome,
                    old=campo_antes.value,
                    new=campo_atual.value,
                    old_status=status_antes,
                    new_status=status_agora,
                    quote=_primeira_citacao(campo_atual),
                    motivo="valor mudou entre duas coletas",
                )
            )
            continue

        if status_antes != status_agora:
            diff.alertas.append(
                Alerta(
                    type="status",
                    field=nome,
                    old=campo_antes.value,
                    new=campo_atual.value,
                    old_status=status_antes,
                    new_status=status_agora,
                    quote=_primeira_citacao(campo_atual),
                    motivo=(
                        f"o valor é o mesmo, mas o status foi de {status_antes} para {status_agora}"
                    ),
                )
            )
            continue

        diff.inalterados += 1
    return diff


def persistir_alertas(version_id: str, diff: Diff) -> int:
    """Grava os alertas. Sem banco, devolve 0 — alerta não gravado não derruba o job."""
    from pipeline.persist import _sessao

    sessao = _sessao()
    if sessao is None:
        return 0
    from api.app.models import Alert

    gravados = 0
    with sessao as s:
        for alerta in diff.alertas:
            s.add(
                Alert(
                    type=alerta.type,
                    version_id=version_id or None,
                    field=alerta.field,
                    old=alerta.old,
                    new=alerta.new,
                )
            )
            gravados += 1
        s.commit()
    return gravados
