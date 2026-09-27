"""Do alerta ao evento: monta o contexto das regras e a **cadeia de prova**.

Duas responsabilidades, e as duas são de tradução — a régua fica em
`pipeline/materiality/`:

* **`avaliar_alerta`** junta o que as regras precisam saber (delta, gap, equivalência,
  comparabilidade, inversões de paridade) e grava o `competitive_events`;
* **`trace`** monta a cadeia do "Por quê?": ação sugerida → regra → mudança → campo →
  evidências → snapshots.

**Nenhum elo da cadeia pode ser vazio.** É critério de aceite, e a razão é o que o produto
promete: a cadeia existe para alguém **conferir**, e um elo que aponta para o nada é pior
que um elo ausente — ele parece prova. Onde o dado não existe, o elo diz o motivo em vez de
sair em branco.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlmodel import Session, select

from api.app.models import (
    Alert,
    Brand,
    CompetitiveEvent,
    Equivalent,
    Evidence,
    Snapshot,
    SpecValue,
    VehicleModel,
    Version,
)
from pipeline.materiality import engine

#: Campos de preço, para as regras de faixa e de gap.
CAMPOS_DE_PRECO = frozenset({"preco_sugerido_brl", "preco_fipe_brl"})

#: O que fazer, por faixa. Texto do produto, não de LLM.
#:
#: A ação é o primeiro elo da cadeia porque é a resposta a "e daí?" — e a spec pede que ela
#: esteja na tela em dois cliques. Uma cadeia que começa na regra obriga o leitor a deduzir
#: a ação, que é o trabalho que ele queria evitar.
ACAO_POR_FAIXA = {
    engine.ALTA: (
        "Revisar hoje o battlecard e o argumentário deste par, e conferir a faixa de preço "
        "com o gestor comercial."
    ),
    engine.MEDIA: "Entrar na revisão da semana: a mudança é real e não inverteu nada.",
    engine.BAIXA: "Nenhuma ação hoje. Fica registrado, com evidência, para o histórico.",
    engine.RUIDO: (
        "Nenhuma ação. Variação dentro do que a fonte muda sozinha — o alerta fica na "
        "lista, colapsado, e não entra na fila de prioridade."
    ),
}


def significado_de(faixa: str) -> str:
    """O que a faixa significa, **lido do YAML**.

    Não é texto de tela duplicado em TypeScript: a definição de cada faixa vive em
    `rules.yaml` ao lado dos pesos, e é lá que o gestor da Ford vai discuti-la. Duas
    cópias da mesma frase divergem na primeira revisão, e a que aparece para o usuário
    seria justamente a que ninguém reviu.
    """
    for linha in engine.carregar().faixas:
        if linha.nome == faixa:
            return linha.significado
    return ""


def _rotulo(sessao: Session, version_id: str | None) -> str:
    if not version_id:
        return ""
    version = sessao.get(Version, version_id)
    if version is None:
        return ""
    modelo = sessao.get(VehicleModel, version.model_id)
    marca = sessao.get(Brand, modelo.brand_id) if modelo else None
    partes = [p for p in (marca.nome if marca else "", modelo.nome if modelo else "") if p]
    return " ".join([*partes, version.nome_exato]).strip()


def _equivalente_de(sessao: Session, version_id: str | None) -> tuple[str | None, float | None]:
    """`(ford_version_id, preço)` do par comparável, ou `(None, None)`."""
    if not version_id:
        return None, None
    equivalencia = sessao.exec(
        select(Equivalent).where(Equivalent.competitor_version_id == version_id)
    ).first()
    if equivalencia is None or not equivalencia.ford_version_id:
        return None, None
    linha = sessao.exec(
        select(SpecValue).where(
            SpecValue.version_id == equivalencia.ford_version_id,
            SpecValue.field == "preco_sugerido_brl",
        )
    ).first()
    preco = linha.value_json if linha is not None else None
    return equivalencia.ford_version_id, (float(preco) if isinstance(preco, int | float) else None)


def _par_comparavel(sessao: Session, ford_id: str | None, conc_id: str | None) -> bool:
    """O par passa nos critérios de `pipeline/comparables.py`?

    Sem par cadastrado devolve `True` de propósito: a regra que trata a ausência é a
    `sem_equivalente`, e marcar "não comparável" aqui somaria duas penalidades pelo mesmo
    fato.
    """
    if not ford_id or not conc_id:
        return True
    from api.app.services import spec_assembler
    from pipeline import comparables

    ford = sessao.get(Version, ford_id)
    conc = sessao.get(Version, conc_id)
    if ford is None or conc is None:
        return True
    atributos_ford = comparables.atributos_de_spec(
        spec_assembler.montar(sessao, ford_id), versao=ford.nome_exato
    )
    atributos_conc = comparables.atributos_de_spec(
        spec_assembler.montar(sessao, conc_id), versao=conc.nome_exato
    )
    return comparables.avaliar(atributos_ford, atributos_conc).comparavel


def _parity_flips(alerta: Alert) -> list[dict[str, Any]]:
    """As inversões de paridade que este alerta produziu.

    Calculado do próprio alerta: o campo mudou de valor, e o estado de paridade **daquele
    campo** contra o par comparável pode ter virado. Só há inversão quando há os dois
    valores e um par para comparar — e é por isso que a lista costuma vir vazia num alerta
    de concorrente sem equivalente cadastrado.
    """
    if alerta.field is None or alerta.old is None or alerta.new is None:
        return []
    from pipeline import parity

    antes = parity.comparar_campo(alerta.field, valor_ford=alerta.old, valor_concorrente=alerta.old)
    depois = parity.comparar_campo(
        alerta.field, valor_ford=alerta.old, valor_concorrente=alerta.new
    )
    if antes.estado == depois.estado:
        return []
    return [
        {
            "campo": alerta.field,
            "antes": antes.estado,
            "depois": depois.estado,
            "motivo": depois.motivo,
        }
    ]


def contexto_de(sessao: Session, alerta: Alert) -> tuple[engine.Contexto, str | None]:
    """O contexto das regras, e o id da versão Ford comparável (quando houver)."""
    impacto = alerta.impact_json or {}
    ford_id, preco_ford = _equivalente_de(sessao, alerta.version_id)

    ctx = engine.Contexto(
        campo=alerta.field or "",
        antes=alerta.old,
        depois=alerta.new,
        delta_pct=impacto.get("delta_pct"),
        gap_antes=impacto.get("gap_antes"),
        gap_depois=impacto.get("gap_depois"),
        dimensoes_afetadas=tuple(impacto.get("dimensoes_afetadas") or ()),
        preco_ford_comparavel=preco_ford if (alerta.field in CAMPOS_DE_PRECO) else None,
        tem_equivalente=ford_id is not None,
        par_comparavel=_par_comparavel(sessao, ford_id, alerta.version_id),
        parity_flips=tuple(_parity_flips(alerta)),
        is_simulated=bool(alerta.is_simulated),
    )
    return ctx, ford_id


def avaliar_alerta(sessao: Session, alerta: Alert) -> CompetitiveEvent:
    """Avalia e **grava** o evento. Idempotente por alerta: reavaliar atualiza a linha.

    Reavaliar é esperado: mexer num peso do `rules.yaml` muda a leitura de todos os alertas,
    e a linha guarda `versao_das_regras` para que a leitura antiga não se confunda com a
    nova.
    """
    ctx, ford_id = contexto_de(sessao, alerta)
    resultado = engine.avaliar(ctx)

    linha = sessao.exec(
        select(CompetitiveEvent).where(CompetitiveEvent.alert_id == alerta.id)
    ).first()
    if linha is None:
        linha = CompetitiveEvent(alert_id=alerta.id)

    linha.version_id = alerta.version_id
    linha.comparable_version_id = ford_id
    linha.materiality = resultado.faixa
    linha.pontos = resultado.pontos
    linha.rules_fired = [r.to_dict() for r in resultado.rules_fired]
    linha.parity_flips = list(resultado.parity_flips)
    linha.priority_rank = resultado.priority_rank
    linha.versao_das_regras = resultado.versao_das_regras
    linha.is_simulated = bool(alerta.is_simulated)
    sessao.add(linha)
    sessao.commit()
    sessao.refresh(linha)
    return linha


def evento_de(sessao: Session, alerta: Alert) -> CompetitiveEvent:
    """O evento do alerta, avaliando na hora se ainda não existir."""
    linha = sessao.exec(
        select(CompetitiveEvent).where(CompetitiveEvent.alert_id == alerta.id)
    ).first()
    return linha if linha is not None else avaliar_alerta(sessao, alerta)


# --------------------------------------------------------------------------- cadeia
#: Os dois lados de uma mudança. É o que cada evidência do elo 5 declara sobre si.
LADO_ANTES = "antes"
LADO_DEPOIS = "depois"


def _evidencia_out(sessao: Session, evidence_id: str | None, lado: str) -> dict[str, Any] | None:
    """Uma evidência do elo 5, **dizendo de que lado da mudança ela é**.

    O `lado` viaja com a evidência por causa de um defeito medido (D-156): a tela
    rotulava cada bloco **pelo índice na lista**, e esta função filtra os `None` antes de
    montá-la. Quando só existe a evidência do *depois* — que é exatamente o caso do Fogo
    Amigo, onde `evidence_before_id` nunca é gravado —, ela caía no índice 0 e a tela
    imprimia "antes: 499" em cima da citação da página oficial da Ford. A citação estava
    certa; o rótulo em cima dela era do lado errado.

    Quem sabe o lado é quem lê o alerta, não quem conta posições numa lista já filtrada.
    """
    if not evidence_id:
        return None
    linha = sessao.get(Evidence, evidence_id)
    if linha is None:
        return None
    return {
        "evidence_id": linha.id,
        "source_url": linha.source_url,
        "quote": linha.quote,
        "captured_at": (linha.captured_at.isoformat() if linha.captured_at else ""),
        "tier": linha.tier,
        "page": linha.page,
        "lado": lado,
    }


def _snapshots_de(sessao: Session, urls: list[str]) -> list[dict[str, Any]]:
    """Os snapshots das URLs citadas: hash e data, que é o que a auditoria pede."""
    if not urls:
        return []
    linhas = sessao.exec(
        select(Snapshot).where(Snapshot.url.in_(urls))  # type: ignore[attr-defined]
    ).all()
    vistos: dict[str, dict[str, Any]] = {}
    for linha in linhas:
        # O mais recente por URL: a cadeia mostra o que sustenta o valor de hoje.
        atual = vistos.get(linha.url)
        if atual is None or (
            linha.captured_at and atual["captured_at"] < linha.captured_at.isoformat()
        ):
            vistos[linha.url] = {
                "snapshot_id": linha.id,
                "url": linha.url,
                "sha256": linha.sha256,
                "captured_at": (linha.captured_at.isoformat() if linha.captured_at else ""),
                "http_status": linha.http_status,
            }
    return [vistos[url] for url in sorted(vistos)]


#: O que dizer quando um elo não tem o dado. Elo em branco parece prova.
MOTIVO_SEM_EVIDENCIA = (
    "sem evidência gravada para este lado da mudança. O alerta é real (o valor mudou no "
    "banco), e a ponta que falta está dita em vez de aparecer em branco."
)
#: `fixture` e `replay` são palavras de dentro: a frase que explica a falta de cópia
#: arquivada tem de explicá-la a quem vende, não a quem mantém o pipeline (12/09/2026).
MOTIVO_SEM_SNAPSHOT = (
    "não há cópia arquivada da página para esta evidência. A fonte e a data continuam "
    "registradas; o que falta é a cópia do texto como ele estava no dia da coleta."
)


def trace(sessao: Session, alerta: Alert) -> dict[str, Any]:
    """A cadeia do "Por quê?", elo por elo. **Nenhum elo vazio** — ver o docstring."""
    evento = evento_de(sessao, alerta)
    evidencias = [
        e
        for e in (
            _evidencia_out(sessao, alerta.evidence_before_id, LADO_ANTES),
            _evidencia_out(sessao, alerta.evidence_after_id, LADO_DEPOIS),
        )
        if e
    ]
    urls = [str(e["source_url"]) for e in evidencias if e.get("source_url")]
    snapshots = _snapshots_de(sessao, urls)

    acao = ACAO_POR_FAIXA.get(evento.materiality, ACAO_POR_FAIXA[engine.RUIDO])
    if evento.is_simulated:
        acao = f"{engine.NOTA_DE_HIPOTESE} Ação sugerida, se o dado fosse real: {acao}"

    return {
        "alert_id": alerta.id,
        "materiality": evento.materiality,
        "significado": significado_de(evento.materiality),
        "pontos": evento.pontos,
        "priority_rank": evento.priority_rank,
        "is_simulated": evento.is_simulated,
        "versao_das_regras": evento.versao_das_regras,
        # A cadeia, na ordem em que a tela a mostra: da ação para a prova.
        "acao_sugerida": acao,
        "regras": list(evento.rules_fired or []),
        "mudanca": {
            "campo_canonico": alerta.field,
            "before": alerta.old,
            "after": alerta.new,
            "tipo_de_alerta": alerta.type,
            "detectado_em": (alerta.created_at.isoformat() if alerta.created_at else ""),
        },
        "parity_flips": list(evento.parity_flips or []),
        "comparavel": {
            "version_id": evento.comparable_version_id,
            "rotulo": _rotulo(sessao, evento.comparable_version_id),
            "motivo": (
                ""
                if evento.comparable_version_id
                else "nenhuma versão Ford equivalente cadastrada para este concorrente"
            ),
        },
        "evidencias": evidencias,
        "motivo_sem_evidencia": MOTIVO_SEM_EVIDENCIA if not evidencias else "",
        "snapshots": snapshots,
        "motivo_sem_snapshot": MOTIVO_SEM_SNAPSHOT if not snapshots else "",
        "nota_dos_pesos": engine.NOTA_DOS_PESOS,
        "gerado_em": dt.datetime.now(dt.UTC).replace(tzinfo=None).isoformat(),
    }
