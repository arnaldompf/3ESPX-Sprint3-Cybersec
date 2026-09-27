"""Classifica a mudança nos sete tipos de `docs/12` §6.1 e monta o alerta completo.

O `pipeline/diff.py` da WP-12 responde *"mudou?"*. Este módulo responde *"mudou o quê, e
o que isso significa"* — e é a diferença entre um log de alterações e o Change Radar.

A classificação não é cosmética: a tela desenha ícone por tipo, o filtro da API é por
tipo, e a tabela de reações é indexada por tipo. Um `campo_alterado` genérico onde cabia
`preco_fipe` faria o alerta chegar sem a reação certa.

**Nenhum alerta sem evidência.** É a nota final da spec, e vale como a regra da ficha:
um alerta é uma afirmação sobre dois valores, e afirmação sem procedência não existe. O
alerta de `versao_nova`/`versao_removida` é a exceção declarada — a evidência dele é a
**própria linha vigente** do resolvedor, que não é um trecho de campo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.diff import Alerta as AlertaDeDiff
from pipeline.radar import impact, reactions
from pipeline.schema import Evidence, SpecField, StandardSpec

#: Campos comerciais que ganham tipo próprio, em vez de cair em `campo_alterado`.
TIPO_POR_CAMPO = {
    "preco_sugerido_brl": "preco_oficial",
    "preco_fipe_brl": "preco_fipe",
    "fipe_referencia": "preco_fipe",
}


def classificar(campo: str | None, *, status_novo: str = "") -> str:
    """O tipo do alerta a partir do campo e do status novo.

    A ordem das checagens é a da especificidade: preço primeiro, porque é o que tem
    leitura comercial direta; `fonte_bloqueada` depois, porque é sobre a **coleta** e não
    sobre o veículo; `campo_alterado` no fim, como o genérico honesto.
    """
    if campo and campo in TIPO_POR_CAMPO:
        return TIPO_POR_CAMPO[campo]
    if status_novo == "bloqueada":
        return "fonte_bloqueada"
    return "campo_alterado"


@dataclass
class AlertaDetectado:
    """Um alerta pronto para gravar: tipo, os dois valores, as duas evidências, impacto."""

    type: str
    field: str | None
    old: Any
    new: Any
    evidencia_antes: Evidence | None = None
    evidencia_depois: Evidence | None = None
    impacto: impact.Impacto = field(default_factory=impact.Impacto)
    reacoes: reactions.Reacoes | None = None
    is_simulated: bool = False
    motivo: str = ""

    @property
    def tem_evidencia(self) -> bool:
        """Ao menos uma das duas pontas provada.

        Uma ponta basta para o alerta existir: quando um campo **ganha** valor, não havia
        evidência antes — e "de nada para 397 cv, com este trecho" é informação legítima.
        Zero evidências, não: aí o alerta seria boato.
        """
        return self.evidencia_antes is not None or self.evidencia_depois is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "field": self.field,
            "old": self.old,
            "new": self.new,
            "impact": self.impacto.to_dict(),
            "reactions": self.reacoes.to_dict() if self.reacoes else None,
            "is_simulated": self.is_simulated,
            "motivo": self.motivo,
        }


def _primeira_evidencia(campo: SpecField | None) -> Evidence | None:
    if campo is None or not campo.evidences:
        return None
    return campo.evidences[0]


def enriquecer(
    alerta: AlertaDeDiff,
    *,
    antes: StandardSpec | None = None,
    depois: StandardSpec | None = None,
    preco_ford: float | None = None,
    preco_ford_equivalente_id: str | None = None,
    e_do_concorrente: bool = True,
    is_simulated: bool = False,
) -> AlertaDetectado:
    """Transforma um alerta do `diff` num alerta do Radar.

    `preco_ford` é o preço da versão Ford equivalente **hoje**. Sem ele o impacto sai sem
    gap e com o motivo — ver `pipeline/radar/impact.py`.
    """
    tipo = classificar(alerta.field, status_novo=alerta.new_status)
    impacto = impact.calcular(
        campo=alerta.field,
        antes=alerta.old,
        depois=alerta.new,
        preco_ford=preco_ford,
        preco_ford_equivalente_id=preco_ford_equivalente_id,
        e_do_concorrente=e_do_concorrente,
    )

    caminho = alerta.field or ""
    evidencia_antes = _primeira_evidencia(antes.get(caminho)) if antes and caminho else None
    evidencia_depois = _primeira_evidencia(depois.get(caminho)) if depois and caminho else None

    return AlertaDetectado(
        type=tipo,
        field=alerta.field,
        old=alerta.old,
        new=alerta.new,
        evidencia_antes=evidencia_antes,
        evidencia_depois=evidencia_depois,
        impacto=impacto,
        reacoes=reactions.sugerir(tipo, impacto.direcao),
        is_simulated=is_simulated,
        motivo=alerta.motivo,
    )


def detectar(
    antes: StandardSpec,
    depois: StandardSpec,
    *,
    preco_ford: float | None = None,
    preco_ford_equivalente_id: str | None = None,
    e_do_concorrente: bool = True,
    exigir_evidencia: bool = True,
) -> list[AlertaDetectado]:
    """Todos os alertas do Radar entre duas fichas da mesma versão.

    `exigir_evidencia=True` (o padrão) **descarta** o alerta sem nenhuma das duas
    evidências, cumprindo a nota da spec. É desligável só para teste: em produção, alerta
    sem prova não sai.
    """
    from pipeline.diff import comparar

    detectados: list[AlertaDetectado] = []
    for bruto in comparar(antes, depois).alertas:
        alerta = enriquecer(
            bruto,
            antes=antes,
            depois=depois,
            preco_ford=preco_ford,
            preco_ford_equivalente_id=preco_ford_equivalente_id,
            e_do_concorrente=e_do_concorrente,
        )
        if exigir_evidencia and not alerta.tem_evidencia:
            continue
        detectados.append(alerta)
    return detectados


def da_divergencia_interna(
    divergencia: Any,
    *,
    evidencia_publica: Evidence | None = None,
) -> AlertaDetectado:
    """O alerta do Fogo Amigo: referência interna × fonte pública.

    A evidência do lado **interno** é o próprio documento que o gestor subiu, e ela não é
    um `Evidence` de coleta — é por isso que `evidencia_antes` fica com a citação do valor
    interno e `source_url` aponta para o documento. Quem lê tem de ver de onde saiu cada
    lado, e o lado interno é o que precisa de correção.
    """
    interna = Evidence(
        evidence_id=f"interno:{divergencia.campo}",
        source_url=f"interno://{divergencia.documento or 'referencia-interna'}",
        tier=1,  # `Evidence` exige tier 1–5; a origem interna viaja na URL e no tipo.
        quote=(divergencia.raw_interno or str(divergencia.valor_interno))[:300],
        captured_at="",
        raw_value=divergencia.raw_interno or None,
    )
    impacto = impact.calcular(
        campo=divergencia.campo,
        antes=divergencia.valor_interno,
        depois=divergencia.valor_publico,
    )
    return AlertaDetectado(
        type="referencia_interna_divergente",
        field=divergencia.campo,
        old=divergencia.valor_interno,
        new=divergencia.valor_publico,
        evidencia_antes=interna,
        evidencia_depois=evidencia_publica,
        impacto=impacto,
        reacoes=reactions.sugerir("referencia_interna_divergente"),
        motivo=(
            "o material interno afirma um valor que a fonte pública da montadora "
            "contradiz; o valor da fonte pública é o que vale"
        ),
    )
