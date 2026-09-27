"""`GET /jobs/{id}` — o estado de um job, para quem o pediu.

**Por que esta rota saiu de `extractions.py`.** Ela morava lá, sob a permissão do roteador
inteiro (`criar_extracoes`), e isso quebrou no dia em que o **vendedor** passou a pedir um
relatório (WP-28): ele recebia 403 ao tentar acompanhar o **próprio** job. Seguir um job que
eu mesmo pedi não é "criar extração" — é ler o estado de um pedido meu.

A permissão passou a ser `consultar_fichas` (todos os papéis) e **a guarda de verdade é a
de dono**: quem não pediu, e não é gestor, recebe 403. Era assim antes; o que estava errado
era a porta da frente estar fechada para quem tinha a chave do quarto.

`result_url` aponta para coisas diferentes conforme o tipo do job: a ficha, quando é
extração; o arquivo, quando é relatório. Sem essa distinção, um job de PDF concluído
devolveria `result_url` nulo e a tela não teria o que abrir.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.app.deps import SessaoDep, UsuarioDep, exige
from api.app.errors import ProblemaHTTP
from api.app.models import Job, JobStatus, Version
from api.app.permissions import Acao

router = APIRouter(tags=["jobs"])

#: Papéis que leem qualquer job. Os demais leem só os que pediram.
PAPEIS_QUE_MANDAM = frozenset({"gestor", "admin"})


class JobOut(BaseModel):
    id: str
    tipo: str
    status: str
    stage: str | None = None
    error: str | None = None
    result_url: str | None = None
    criado_em: str


@router.get(
    "/jobs/{job_id}",
    response_model=JobOut,
    summary="Estado de um job",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
async def obter_job(job_id: str, sessao: SessaoDep, usuario: UsuarioDep) -> JobOut:
    """`docs/04` restringe a "dono/gestor": quem pediu, ou quem manda.

    Sem isso, qualquer usuário leria o payload de qualquer job — que inclui o que outro
    time está pesquisando. Não é segredo de estado, mas também não é da conta de todos.
    """
    job = sessao.get(Job, job_id)
    if job is None:
        raise ProblemaHTTP(404, f"Job {job_id} não existe.")

    dono = str((job.payload or {}).get("solicitado_por") or "")
    if dono and dono != usuario.id and usuario.role not in PAPEIS_QUE_MANDAM:
        raise ProblemaHTTP(403, "Este job foi pedido por outro usuário.")

    result_url = None
    if job.status == JobStatus.CONCLUIDO.value:
        payload = job.payload or {}
        # Relatório aponta para o arquivo; extração, para a ficha. Ver o docstring.
        arquivo = payload.get("arquivo")
        version_id = payload.get("version_id")
        if arquivo:
            result_url = f"/api/v1/reports/{arquivo}"
        elif version_id and sessao.get(Version, version_id) is not None:
            result_url = f"/api/v1/vehicles/{version_id}/specs"

    return JobOut(
        id=job.id,
        tipo=job.tipo,
        status=job.status,
        stage=job.stage,
        error=job.error,
        result_url=result_url,
        criado_em=job.criado_em.isoformat(),
    )
