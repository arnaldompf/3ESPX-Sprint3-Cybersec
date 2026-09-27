"""Uma política para publicação e leitura da projeção histórica."""

from __future__ import annotations

from pipeline.schema import SpecField, Status
from pipeline.status import Observacao, decidir

POLICY_VERSION = "quality-2"


def choose(
    field: str,
    fields: list[SpecField],
    *,
    target=None,
    source_texts: dict[str, str] | None = None,
    require_source_proof: bool = False,
    rejected_evidences: dict[str, str] | None = None,
) -> SpecField:
    """Recebe envelopes validados na extração; agrupa pela mesma política do pipeline."""
    observations = []
    texts = {}
    seen = set()
    rejected = []
    for cell in fields:
        if cell.status not in {Status.VERIFICADO, Status.DIVERGENTE} or cell.value is None:
            continue
        assertions = [(cell.value, e) for e in cell.evidences]
        assertions.extend((c.value, c.evidence) for c in cell.conflicts)
        for value, evidence in assertions:
            audit_reason = (rejected_evidences or {}).get(evidence.evidence_id)
            if audit_reason:
                rejected.append(audit_reason)
                continue
            proof_note = ""
            if target is not None:
                from pipeline.ground import locate
                from pipeline.identity import authoritative_model_years, claim_rejection
                from pipeline.semantics import (
                    rejection_reason,
                    validate_date,
                    validate_list,
                    validate_number,
                )

                source = (source_texts or {}).get(evidence.evidence_id, "")
                from pipeline.connectors import carrosnaweb, vw_manual_warranty
                from pipeline.connectors.pbe import supports as pbe_supports

                scoped_pbe = pbe_supports(
                    field, target, source, evidence.source_url, evidence.quote, value
                )
                scoped_warranty = vw_manual_warranty.supports(
                    field, target, source, evidence.source_url, evidence.quote, value
                )
                scoped_carrosnaweb = carrosnaweb.supports(
                    field, target, source, evidence.source_url, evidence.quote, value
                )
                if scoped_warranty:
                    proof_note = vw_manual_warranty.candidatos(source, evidence.source_url, target)[
                        0
                    ].notas
                if scoped_pbe and field == "direcao":
                    from pipeline.connectors.pbe import candidatos_direcao

                    proof_note = next(
                        c.notas
                        for c in candidatos_direcao(source, evidence.source_url, target)
                        if c.quote == evidence.quote and c.valor == value
                    )
                years = (
                    authoritative_model_years(source, target)
                    if source and not (scoped_pbe or scoped_warranty or scoped_carrosnaweb)
                    else set()
                )
                fipe_mismatch = False
                if source and field in {"preco_fipe_brl", "fipe_referencia", "codigo_fipe"}:
                    from pipeline.connectors.fipe import parse_pagina_fipe

                    query = parse_pagina_fipe(source, url=evidence.source_url)
                    # Zero km (32000) não informa qual ano-modelo foi avaliado.
                    fipe_mismatch = bool(
                        target.ano_modelo
                        and (query.codigo or query.zero_km or query.ano_modelo)
                        and query.ano_modelo != target.ano_modelo
                    )
                reason = (
                    (
                        "cadeia_garantia_vw_invalida_ou_campo_fora_do_escopo"
                        if vw_manual_warranty.is_chain(source) and not scoped_warranty
                        else None
                    )
                    or claim_rejection(
                        target,
                        evidence.quote,
                        source_text=(
                            "" if (scoped_pbe or scoped_warranty or scoped_carrosnaweb) else source
                        ),
                    )
                    or rejection_reason(field, evidence.quote, url=evidence.source_url)
                    or (
                        "ano_modelo_incompativel_no_documento"
                        if years and target.ano_modelo and years != {target.ano_modelo}
                        else None
                    )
                    or (
                        "snapshot_ausente_ou_hash_invalido"
                        if not source
                        and (require_source_proof or evidence.evidence_id in (source_texts or {}))
                        else None
                    )
                    or (
                        "evidencia_nao_localizada"
                        if source and not locate(evidence.quote, source).ok
                        else None
                    )
                    or (
                        "itens_sem_prova"
                        if not validate_list(field, value, evidence.quote)
                        else None
                    )
                    or (
                        "numero_sem_prova"
                        if not validate_number(field, value, evidence.quote, cell.unit)
                        else None
                    )
                    or (
                        "data_sem_prova"
                        if not validate_date(field, value, evidence.quote)
                        else None
                    )
                    or ("ano_fipe_incompativel" if fipe_mismatch else None)
                )
                if reason:
                    rejected.append(reason)
                    continue
            fingerprint = (repr(value), evidence.source_url, evidence.quote)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            key = evidence.evidence_id + ":" + evidence.quote
            texts[key] = evidence.quote
            observations.append(
                Observacao(
                    field,
                    value,
                    evidence.quote,
                    source_id=key,
                    url=evidence.source_url,
                    tier=evidence.tier,
                    captured_at=evidence.captured_at,
                    raw_value=evidence.raw_value or "",
                    unidade=cell.unit,
                    pagina=evidence.page,
                    tipo_de_afirmacao=evidence.tipo_de_afirmacao,
                    notas=proof_note or _scope_note(field, evidence.quote),
                    evidence_ref=evidence,
                )
            )
    if observations:
        return decidir(field, observations, textos=texts).spec
    if rejected:
        return SpecField.vazio(Status.NAO_VERIFICADO, notes="; ".join(sorted(set(rejected))))
    # Vazio novo não altera decisão anterior de ausência comprovada.
    return next(
        (c for c in fields if c.status == Status.NAO_DISPONIVEL),
        fields[0] if fields else SpecField.vazio(),
    )


def _scope_note(field: str, quote: str) -> str:
    import re

    from pipeline.ontology import normalize

    if field == "bloqueio_diferencial" and "eletronico" in normalize(quote):
        return "Bloqueio eletrônico (EDS); não comprova bloqueio mecânico selecionável."
    measure = re.search(r"\b\d+[,.](\d{1,2})\s*m\b", quote)
    if field.endswith("_mm") and measure:
        return (
            f"Fonte expressa a medida em metros com {len(measure.group(1))} casa(s) decimal(is); "
            "a conversão para milímetros não acrescenta precisão."
        )
    return ""


def from_rows(rows, field: str) -> SpecField:
    from api.app.services.spec_assembler import _evidencia_de

    cells = []
    for value, row in rows:
        evidence = _evidencia_de(row)
        if (
            value.value_json is not None
            and evidence is not None
            and value.status in {"verificado", "divergente"}
        ):
            cells.append(SpecField.verificado(value.value_json, evidence, unit=value.unit))
        elif value.value_json is None:
            status = Status(value.status)
            if status not in {Status.VERIFICADO, Status.DIVERGENTE}:
                cells.append(SpecField.vazio(status))
    return choose(field, cells)
