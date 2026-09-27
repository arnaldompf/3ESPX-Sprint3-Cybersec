"""`/comparisons/{id}/pdf` e `/reports/{arquivo}` — o documento para o cliente (WP-28).

**202 e job, não 200 e espera.** Gerar o relatório monta duas fichas, roda o motor de
aderência, o custo de uso e o argumentário, e renderiza o documento. Segurar a requisição
HTTP por isso é o caminho mais curto para um timeout no meio de uma conversa de venda —
`docs/04` pede 202 com `Location`, e a fila já existe (a mesma tabela `jobs` da WP-14).

**O arquivo é servido por rota autenticada, não por caminho estático.** Um diretório
público de relatórios seria um vazamento silencioso: o link vive no WhatsApp de quem
recebeu, e sem autenticação qualquer pessoa com o endereço leria a comparação de outra
concessionária. A rota confere o papel e o nome do arquivo.

**Nenhum contato do cliente é armazenado** (`specs/WP-28.md`). O corpo do `POST` não tem
campo para isso, e o compartilhamento é feito pelo próprio sistema operacional a partir da
tela — o produto não vê o destinatário.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from api.app.deps import SessaoDep, UsuarioDep, exige
from api.app.errors import ProblemaHTTP
from api.app.models import Job, JobStatus, Version
from api.app.permissions import Acao
from api.app.services import argument_service
from pipeline.fit.engine import NeedsProfile
from pipeline.report import render

log = structlog.get_logger(__name__)
router = APIRouter(tags=["relatorios"])

#: O nome do arquivo aceito na rota de download.
#:
#: Só o que o próprio gerador produz: `relatorio-<par>-<job>.pdf|html`. A validação existe
#: contra travessia de diretório (`../../.env`) — a rota lê do disco, e o nome vem da URL.
NOME_DE_ARQUIVO = re.compile(r"^[A-Za-z0-9._-]{1,120}\.(pdf|html)$")

TIPO_DE_JOB = "pdf"


class PdfIn(BaseModel):
    """O que o relatório precisa. **Sem nenhum campo de contato do cliente.**"""

    model_config = ConfigDict(extra="forbid")

    needs_profile: NeedsProfile | None = None
    permitir_llm: bool = True


class JobDeRelatorio(BaseModel):
    job_id: str
    status: str
    location: str


@router.post(
    "/comparisons/{comparison_id}/pdf",
    response_model=JobDeRelatorio,
    status_code=202,
    summary="Enfileira o relatório do par para o cliente (202 + job)",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
async def pedir_pdf(
    comparison_id: str,
    corpo: PdfIn,
    sessao: SessaoDep,
    usuario: UsuarioDep,
    response: Response,
) -> JobDeRelatorio:
    """Enfileira e devolve 202 com `Location`. Quem gera é o worker."""
    try:
        ford_id, conc_id = argument_service.par_de(comparison_id)
    except argument_service.ParInvalido as exc:
        raise ProblemaHTTP(422, str(exc)) from exc
    for version_id in (ford_id, conc_id):
        if sessao.get(Version, version_id) is None:
            raise ProblemaHTTP(404, f"Versão {version_id!r} não existe.")
    if ford_id == conc_id:
        raise ProblemaHTTP(422, "O par não pode ter a mesma versão nas duas pontas.")

    job = Job(
        tipo=TIPO_DE_JOB,
        status=JobStatus.PENDENTE.value,
        payload={
            "comparison_id": comparison_id,
            "ford_version_id": ford_id,
            "competitor_version_id": conc_id,
            "needs_profile": (
                corpo.needs_profile.model_dump(mode="json") if corpo.needs_profile else None
            ),
            "permitir_llm": corpo.permitir_llm,
            # Quem pediu, para `GET /jobs/{id}` poder restringir a dono/gestor. É o id do
            # **usuário**, não do cliente: não há cliente registrado em lugar nenhum.
            "solicitado_por": usuario.id,
        },
    )
    sessao.add(job)
    sessao.commit()
    sessao.refresh(job)

    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    log.info("relatorio.enfileirado", job_id=job.id, comparison_id=comparison_id)
    return JobDeRelatorio(job_id=job.id, status=job.status, location=f"/api/v1/jobs/{job.id}")


@router.get(
    "/reports/{arquivo}",
    summary="Baixa o relatório gerado (autenticado)",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
async def baixar_relatorio(arquivo: str) -> FileResponse:
    """Serve o arquivo do diretório de relatórios, **e só de lá**.

    O nome é validado contra um padrão fechado antes de tocar o disco: a rota lê caminho
    vindo da URL, e `../../.env` é o primeiro teste que alguém faz.
    """
    if not NOME_DE_ARQUIVO.match(arquivo):
        raise ProblemaHTTP(
            422,
            "Nome de arquivo inválido. São aceitos apenas os nomes que o próprio gerador "
            "produz, terminando em .pdf ou .html.",
        )
    caminho = render.DIRETORIO / arquivo
    # `resolve()` nos dois lados: o padrão já barra `..`, e esta é a segunda linha de
    # defesa — a que continua valendo se o padrão for afrouxado algum dia.
    if not caminho.resolve().is_relative_to(render.DIRETORIO.resolve()):
        raise ProblemaHTTP(422, "Caminho fora do diretório de relatórios.")
    if not caminho.exists():
        raise ProblemaHTTP(
            404,
            f"Relatório {arquivo!r} não existe. Ele é gerado por um job — confira o estado "
            "em `/jobs/{id}` antes de baixar.",
        )
    tipo = "application/pdf" if caminho.suffix == ".pdf" else "text/html; charset=utf-8"
    return FileResponse(path=str(caminho), media_type=tipo, filename=caminho.name)


def gerar(sessao: Any, job: Job) -> dict[str, Any]:
    """Gera o relatório de um job de `tipo="pdf"`. Chamado pelo worker.

    Devolve o payload atualizado com o arquivo, o formato e o motivo (quando o PDF não pôde
    ser renderizado). Fica aqui, e não no worker, para o worker continuar sendo só o laço
    da fila.
    """
    from api.app.routers.domain import comparar as _  # noqa: F401  (garante o import do app)
    from api.app.services import fit_service
    from pipeline.report import html as gerador_html

    payload = dict(job.payload or {})
    ford_id = str(payload.get("ford_version_id") or "")
    conc_id = str(payload.get("competitor_version_id") or "")
    perfil = NeedsProfile(**(payload.get("needs_profile") or {}))

    fit = fit_service.montar(
        sessao,
        base_version_id=ford_id,
        concorrentes=[conc_id],
        perfil=perfil,
    )
    argumentario = argument_service.montar(
        sessao,
        ford_version_id=ford_id,
        competitor_version_id=conc_id,
        perfil=perfil,
        permitir_llm=bool(payload.get("permitir_llm", True)),
    )

    relatorio = gerador_html.de_dados(
        comparacao={"fit": fit},
        argumentario=argumentario,
        gerado_em=job.criado_em.isoformat() if job.criado_em else "",
    )
    relatorio.fontes = _fontes_de(sessao, ford_id, conc_id)
    documento = gerador_html.montar(relatorio)

    vazados = gerador_html.termos_internos_no_texto(documento)
    if vazados:
        # Falha alto em vez de entregar o documento: o critério de aceite é "nenhum texto
        # contém 'confiança', 'tier' ou 'LLM'", e um documento que vaza mecânica interna
        # na mão do cliente é pior que um job que falhou.
        raise ValueError(
            f"o relatório vazou termo interno ({', '.join(vazados)}); documento não gerado"
        )

    resultado = render.renderizar(documento, f"relatorio-{job.id}")
    payload.update(
        {
            "arquivo": resultado.caminho.name,
            "formato": resultado.formato,
            # Qual motor gerou, legível por máquina e por gente: `weasyprint`, `xhtml2pdf`
            # ou `html`. Proveniência do arquivo não é adivinhação (WP-28, D-121).
            "motor": resultado.motor,
            "renderizador": resultado.renderizador,
            "motivo_do_formato": resultado.motivo,
            "bytes": resultado.bytes_gerados,
            "pontos": len(argumentario.get("pontos") or []),
            "tem_ponto_do_concorrente": bool(argumentario.get("ponto_forte_concorrente")),
        }
    )
    return payload


def _fontes_de(sessao: Any, *version_ids: str) -> list[Any]:
    """As fontes das duas fichas: URL, data e os campos que cada uma sustenta."""
    from sqlmodel import select

    from api.app.models import Evidence, SpecValue
    from pipeline.report.html import Fonte

    por_url: dict[str, Fonte] = {}
    for version_id in version_ids:
        linhas = sessao.exec(
            select(SpecValue, Evidence)
            .join(Evidence, Evidence.id == SpecValue.evidence_id)
            .where(SpecValue.version_id == version_id)
        ).all()
        for valor, evidencia in linhas:
            if evidencia is None or not evidencia.source_url:
                continue
            fonte = por_url.setdefault(
                evidencia.source_url,
                Fonte(
                    url=evidencia.source_url,
                    data=(evidencia.captured_at.isoformat() if evidencia.captured_at else ""),
                ),
            )
            if valor.field not in fonte.campos:
                fonte.campos.append(valor.field)
    # Ordem estável: a lista de fontes num documento não pode mudar de ordem entre duas
    # gerações do mesmo par.
    for fonte in por_url.values():
        fonte.campos.sort()
    return [por_url[url] for url in sorted(por_url)]
