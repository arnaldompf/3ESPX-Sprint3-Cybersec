"""Lacunas explicáveis, sem transformar falta de coleta em ausência pública."""

from pipeline.identity import Applicability, VehicleTarget, assess, claim_rejection
from pipeline.research.gaps import campos_procuraveis
from pipeline.schema import Status


def observation_records(leitor):
    from dataclasses import asdict

    from pipeline.ground import locate
    from pipeline.normalize import NaoNormalizavel
    from pipeline.reconcile import observacao_de

    records = []
    target = VehicleTarget(
        leitor.alvo.marca, leitor.alvo.modelo, leitor.alvo.versao, leitor.alvo.ano
    )
    for key, candidates in leitor.candidatos.items():
        if key == "__fipe__":
            continue
        for candidate in candidates:
            reason = (
                claim_rejection(
                    target,
                    candidate.quote,
                    source_text=candidate.source_text or leitor.textos.get(candidate.source_id, ""),
                )
                or ""
            )
            try:
                observacao_de(candidate)
                if not locate(candidate.quote, leitor.textos.get(candidate.source_id, "")).ok:
                    reason = "trecho_nao_localizado"
            except NaoNormalizavel as exc:
                reason = str(exc)
            records.append(
                {
                    "kind": "candidato",
                    "candidate": asdict(candidate),
                    "validation": "rejeitada" if reason else "validada_pipeline",
                    "reason": reason,
                }
            )
    return records


def diagnose(spec, target, fontes, avisos, consultas, motivo, segundos, *, leituras=None):
    applicable = []
    rejected = []
    pending = []
    for source in fontes:
        pages = [
            {"pagina": d.get("pagina"), "status": d.get("status")}
            for d in getattr(getattr(source, "documento_pdf", None), "diagnosticos", [])
            if d.get("status") not in {"complete", "empty"}
        ]
        reading = (leituras or {}).get(source.source_id, {})
        blocks = reading.get("pendentes", 0)
        parse_status = getattr(source, "parse_status", "")
        if pages or blocks or parse_status in {"partial", "failed", "timeout", "missing_original"}:
            pending.append(
                {
                    "url": source.url,
                    "parse_status": parse_status,
                    "paginas": pages,
                    "blocos_pendentes": blocks,
                    "campo_presente_confirmado": False,
                }
            )
        if not source.baixada or source.tipo in {"pbe", "fipe"}:
            continue
        result = assess(
            VehicleTarget(target.marca, target.modelo, target.versao, target.ano),
            source.texto,
            url=source.url,
        )
        if result.status == Applicability.COMPATIBLE:
            applicable.append(source.url)
        else:
            rejected.append({"url": source.url, "motivos": list(result.reasons)})
    fields = {path.split(".")[-1]: field for path, field in spec.itens()}
    gaps = []
    for name in campos_procuraveis():
        field = fields[name]
        if field.value is not None and field.status == Status.VERIFICADO:
            continue
        reasons = [warning for warning in avisos if warning.startswith(name + ":")]
        if field.status == Status.NAO_DISPONIVEL:
            reason, next_step = "ausencia_comprovada", "manter_evidencia"
        elif field.status == Status.DIVERGENTE:
            reason, next_step = "conflito_legitimo", "buscar_evidencia_de_desempate"
        elif reasons:
            reason, next_step = "mapeamento_semantico_incorreto", "reler_trecho_e_unidade"
        elif motivo in {"tempo", "paginas", "teto_de_gasto", "modelo_sem_saldo", "teto_servicos"}:
            reason, next_step = "limite_de_tempo_custo", "retomar_documentos_preservados"
        elif not applicable and rejected:
            reason, next_step = (
                "incompatibilidade_ou_identidade_insuficiente",
                "localizar_fonte_aplicavel",
            )
        elif not applicable and any(f.bloqueada for f in fontes):
            reason, next_step = "fonte_bloqueada", "buscar_fonte_alternativa"
        elif any(p["paginas"] or p["parse_status"] == "partial" for p in pending):
            reason, next_step = "leitura_parcial_pdf", "reprocessar_ou_revisar_paginas_pendentes"
        elif any(p["blocos_pendentes"] for p in pending):
            reason, next_step = "blocos_ainda_nao_lidos", "retomar_blocos_do_documento"
        elif any(f.erro and not f.bloqueada for f in fontes):
            reason, next_step = "falha_de_leitura", "reprocessar_documento"
        elif applicable:
            reason, next_step = "documento_sem_informacao_suficiente", "pesquisar_familia_do_campo"
        else:
            reason, next_step = "fonte_ainda_nao_descoberta", "consultar_acervo_e_busca"
        gaps.append(
            {
                "campo": name,
                "etapa_em_que_parou": reason,
                "fontes_consultadas": [f.url for f in fontes],
                "evidencias_encontradas": [e.model_dump(mode="json") for e in field.evidences],
                "motivo_da_rejeicao": reasons,
                "fontes_sem_aplicabilidade": rejected,
                "documentos_com_leitura_pendente": pending,
                "estrategias_ja_tentadas": sorted(consultas),
                "proxima_estrategia": next_step,
                "tempo_total_execucao_s": segundos,
                "custo_por_campo_usd": None,
            }
        )
    return gaps
