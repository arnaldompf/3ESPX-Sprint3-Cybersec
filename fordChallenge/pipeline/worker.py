"""O worker: consome a tabela `jobs`, roda o pipeline, grava o resultado.

A fila é uma tabela no banco (ADR-3: um worker, sem Redis). O que torna isso seguro é a
**tomada atômica** do job — e é aqui que a spec e o ambiente de dev discordam.

`specs/WP-14.md` pede `SELECT ... FOR UPDATE SKIP LOCKED`, que é a forma certa **no
Postgres** e não existe no SQLite. Como o dev e os testes rodam SQLite (D-05, Docker fora
do ar), o worker tem os dois caminhos:

* **Postgres:** `SELECT ... FOR UPDATE SKIP LOCKED`, como a spec manda;
* **SQLite:** `UPDATE jobs SET status='executando' WHERE id=? AND status='pendente'` e
  confere `rowcount == 1`. É compare-and-set: dois workers disputam a mesma linha e
  **exatamente um** vê `rowcount=1`. O outro volta para a fila.

As duas formas cumprem a mesma garantia (nenhum job roda duas vezes), e há teste com duas
threads disputando um job só para provar. Escolher só uma delas deixaria a garantia sem
teste no ambiente onde ela roda, o que é o pior dos dois mundos.

**Falha de job não derruba o worker**, e o `error` que vai para o banco **não** tem
traceback: o cliente da API leria o caminho de arquivos do servidor. O traceback vai
inteiro para o log estruturado, indexado pelo `job_id`.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import signal
import time
import traceback
from dataclasses import dataclass, field

import structlog
from sqlalchemy import text
from sqlmodel import Session, select

from api.app.db import database_url, engine
from api.app.models import Job, JobStatus, WorkerHeartbeat

log = structlog.get_logger(__name__)

#: Intervalo entre buscas na fila, em segundos (`specs/WP-14.md`).
INTERVALO_S = 2.0
#: Teto de tentativas por job. Acima disso, `falhou` de vez — um job que falha sempre
#: consumiria o worker para sempre.
TENTATIVAS_MAXIMAS = 3
#: Tamanho máximo da mensagem de erro gravada. A coluna aceita 2000; o corte é para a
#: mensagem caber legível na tela, não por limite de banco.
TAMANHO_DO_ERRO = 500

#: Depois de quantos segundos sem batimento o worker é considerado fora do ar.
#:
#: Três vezes o intervalo do laço: uma volta perdida por um job demorado não pode ser
#: confundida com morte, e seis segundos ainda é rápido o bastante para a tela avisar antes
#: de a pessoa desistir sozinha.
TOLERANCIA_DO_BATIMENTO_S = INTERVALO_S * 3


@dataclass
class Resultado:
    """O que uma rodada do worker fez. `once=True` devolve isto para o teste."""

    pegos: int = 0
    concluidos: int = 0
    falhados: int = 0
    ociosos: int = 0
    erros: list[str] = field(default_factory=list)


def _e_postgres() -> bool:
    return database_url().startswith(("postgres", "postgresql"))


def _agora() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def tomar_job(sessao: Session) -> Job | None:
    """Toma **um** job pendente, de forma atômica. `None` se a fila está vazia.

    Ver o docstring do módulo para o porquê dos dois caminhos.
    """
    if _e_postgres():
        # O caminho da spec. `SKIP LOCKED` faz o worker concorrente pular a linha travada
        # em vez de esperar por ela — fila com dois workers não serializa.
        linha = sessao.exec(
            text(
                "SELECT id FROM jobs WHERE status = :pendente "
                "ORDER BY criado_em FOR UPDATE SKIP LOCKED LIMIT 1"
            ).bindparams(pendente=JobStatus.PENDENTE.value)
        ).first()
        if linha is None:
            return None
        job = sessao.get(Job, linha[0])
        if job is None:
            return None
        job.status = JobStatus.EXECUTANDO.value
        job.iniciado_em = _agora()
        job.tentativas += 1
        sessao.add(job)
        sessao.commit()
        sessao.refresh(job)
        return job

    # SQLite: compare-and-set. Dois workers disputam a MESMA linha e exatamente um vê
    # `rowcount == 1`; o outro recebe 0 e volta para a fila.
    candidato = sessao.exec(
        select(Job).where(Job.status == JobStatus.PENDENTE.value).order_by(Job.criado_em).limit(1)
    ).first()
    if candidato is None:
        return None

    resultado = sessao.exec(
        text(
            "UPDATE jobs SET status = :executando, iniciado_em = :agora, "
            "tentativas = tentativas + 1, atualizado_em = :agora "
            "WHERE id = :id AND status = :pendente"
        ).bindparams(
            executando=JobStatus.EXECUTANDO.value,
            pendente=JobStatus.PENDENTE.value,
            agora=_agora(),
            id=candidato.id,
        )
    )
    sessao.commit()
    if resultado.rowcount != 1:
        # Outro worker chegou primeiro. Não é erro: é a garantia funcionando.
        return None
    sessao.expire_all()
    return sessao.get(Job, candidato.id)


def _estagio(sessao: Session, job: Job, stage: str) -> None:
    """Grava o passo atual. Um job que morre no meio tem de dizer **onde** morreu."""
    job.stage = stage
    job.atualizado_em = _agora()
    sessao.add(job)
    sessao.commit()


def bater(sessao: Session, *, jobs_concluidos: int = 0) -> None:
    """Carimba o sinal de vida. Uma linha só, `id="worker"`.

    Chamado a **cada volta do laço**, inclusive quando a fila está vazia — é justamente aí
    que ele importa: sem trabalho a fazer, nada mais no banco se move, e "nenhum job
    recente" seria indistinguível de "worker morto".

    Falha de escrita **não derruba o worker**: um batimento perdido é um aviso a menos, e
    perder o worker por causa do termômetro seria trocar o problema por um pior.
    """
    try:
        linha = sessao.get(WorkerHeartbeat, "worker")
        if linha is None:
            linha = WorkerHeartbeat(id="worker")
        linha.visto_em = _agora()
        linha.pid = os.getpid()
        linha.jobs_concluidos = jobs_concluidos
        sessao.add(linha)
        sessao.commit()
    except Exception as exc:  # pragma: no cover - falha de banco no termômetro
        log.warning("worker.batimento_falhou", erro=str(exc))
        with contextlib.suppress(Exception):
            sessao.rollback()


def _linha_de_evento(run_id: str, evento):
    """Indireção para o teste poder simular o banco do observador caindo."""
    from api.app.routers.research import linha_de_evento

    return linha_de_evento(run_id, evento)


def _executar_pesquisa(sessao: Session, job: Job) -> None:
    """Roda o Pesquisador (WP-41) e grava a trilha **enquanto ela acontece**.

    **Pela mesma fila da extração e do relatório, e isso é deliberado:** um segundo
    mecanismo seria um segundo lugar para um job travar, e um segundo lugar para procurar
    quando ele travar.

    **A trilha ao vivo.** Cada evento da pesquisa é gravado em `research_events` no
    momento em que acontece, por uma **sessão própria** (`escrita`), com um commit por
    evento. A sessão do job está ociosa durante a pesquisa (tudo o que ela tinha foi
    commitado em `_estagio`), então não há disputa de lock no SQLite. O `fim` fica de
    fora: ele sai em `gravar`, no mesmo commit de `status="concluida"` e do `version_id`,
    para quem faz polling não ver a pesquisa acabar antes de a ficha existir.

    A escrita ao vivo é cortesia para a tela: se falhar, o evento é perdido ali e recuperado
    por `gravar` no fim (dedupe por `ordem`). A pesquisa nunca morre por causa dela.

    A exceção vira `falhou` com o motivo, e o `ResearchRun` vai junto: uma pesquisa que
    morre sem deixar rastro é indistinguível de uma pesquisa que ninguém pediu.
    """
    import datetime as dt

    from api.app.models import ResearchRun
    from api.app.routers.research import gravar
    from pipeline.research import gaps
    from pipeline.research.checkpoint import job_path
    from pipeline.research.events import Tipo
    from pipeline.research.persistir import persistir_pesquisa
    from pipeline.research.run import pesquisar

    payload = job.payload or {}
    run_id = str(payload.get("run_id") or "")

    escrita = Session(engine()) if run_id else None

    def ao_evento(evento) -> None:
        if escrita is None or evento.tipo is Tipo.FIM:
            return
        try:
            escrita.add(_linha_de_evento(run_id, evento))
            escrita.commit()
        except Exception as exc:
            log.warning("worker.evento_nao_gravado_ao_vivo", run_id=run_id, erro=str(exc)[:200])
            with contextlib.suppress(Exception):
                escrita.rollback()

    try:
        _estagio(sessao, job, "executando")
        resultado = pesquisar(
            str(payload.get("marca") or ""),
            str(payload.get("modelo") or ""),
            str(payload.get("versao") or ""),
            ano=payload.get("ano"),
            campos=list(payload.get("atributos") or []) or None,
            orcamento=gaps.Orcamento(
                rodadas=int(payload.get("rodadas") or 2),
                paginas=int(payload.get("paginas") or 12),
                segundos=float(payload.get("segundos") or 180.0),
            ),
            ao_evento=ao_evento,
            checkpoint_path=str(job_path(job.id)),
        )
        # **A ficha entra no catálogo antes de o run fechar**, na mesma sessão e no mesmo
        # commit: quando a tela vir o `fim`, `version_id` já existe. Sem `ano` no pedido a
        # gravação recusa e explica — e o motivo vai para `ResearchRun.erro`, não para o log.
        gravacao = persistir_pesquisa(
            sessao,
            resultado,
            run_id=run_id,
            marca=str(payload.get("marca") or ""),
            modelo=str(payload.get("modelo") or ""),
            versao=str(payload.get("versao") or ""),
            ano_modelo=payload.get("ano"),
            job_id=job.id,
        )
        if run_id:
            gravar(sessao, run_id, resultado, gravacao=gravacao)
        job.payload = {
            **payload,
            "campos_com_valor": resultado.cobertura.com_valor,
            "campos_alvo": resultado.cobertura.total,
            "paginas": resultado.orcamento.paginas_gastas,
            "motivo_da_parada": resultado.motivo_da_parada.value,
            "version_id": gravacao.version_id,
            "gravacao": gravacao.to_dict(),
        }
        job.status = JobStatus.CONCLUIDO.value
        job.stage = "done"
        job.concluido_em = _agora()
        job.error = None
        log.info(
            "worker.pesquisa_concluida",
            job_id=job.id,
            run_id=run_id,
            campos=resultado.cobertura.com_valor,
            paginas=resultado.orcamento.paginas_gastas,
        )
    except Exception as exc:
        job.status = JobStatus.FALHOU.value
        job.error = f"{type(exc).__name__}: {exc}"[:2000]
        job.stage = "failed"
        if run_id:
            linha = sessao.get(ResearchRun, run_id)
            if linha is not None:
                linha.status = "falhou"
                linha.erro = job.error
                linha.concluido_em = dt.datetime.now(dt.UTC).replace(tzinfo=None)
                sessao.add(linha)
        log.warning("worker.pesquisa_falhou", job_id=job.id, erro=str(exc))
    finally:
        if escrita is not None:
            with contextlib.suppress(Exception):
                escrita.close()
    job.atualizado_em = _agora()
    sessao.add(job)
    sessao.commit()


def _executar_relatorio(sessao: Session, job: Job) -> None:
    """Gera o relatorio do par e grava o arquivo no payload.

    A excecao vira `falhou` com o motivo, como no job de extracao: um par sem ficha nos
    dois lados nao pode derrubar o worker.
    """
    from api.app.routers.reports import gerar

    try:
        # Os dois estágios REAIS, e não só o último. A tela lista três passos e o do
        # meio nunca acendia: o job nascia com `stage` nulo e ia direto para
        # "renderizando", então "montando a comparação" era decorativo.
        _estagio(sessao, job, "executando")
        _estagio(sessao, job, "renderizando")
        job.payload = gerar(sessao, job)
        job.status = JobStatus.CONCLUIDO.value
        job.stage = "done"
        job.concluido_em = _agora()
        job.error = None
        log.info(
            "worker.relatorio_gerado",
            job_id=job.id,
            arquivo=(job.payload or {}).get("arquivo"),
            formato=(job.payload or {}).get("formato"),
        )
    except Exception as exc:  # pragma: no cover - falha de dado do par
        job.status = JobStatus.FALHOU.value
        job.error = f"{type(exc).__name__}: {exc}"[:2000]
        job.stage = "failed"
        log.warning("worker.relatorio_falhou", job_id=job.id, erro=str(exc))
    job.atualizado_em = _agora()
    sessao.add(job)
    sessao.commit()


def executar_job(sessao: Session, job: Job) -> None:
    """Roda o pipeline do job e grava o resultado.

    A exceção é capturada aqui e virada em `falhou`: um job ruim não pode derrubar o
    worker, senão o primeiro payload estranho para a fila inteira.
    """
    from pipeline.run import run

    payload = job.payload or {}

    # Job de relatorio (WP-28) tem outro caminho: ele nao roda o pipeline de extracao,
    # monta o documento a partir do que ja esta no banco. O `tipo` decide, e um `tipo`
    # desconhecido cai no caminho de extracao como sempre — a fila e a mesma.
    if job.tipo == "pdf":
        _executar_relatorio(sessao, job)
        return

    if job.tipo == "research":
        _executar_pesquisa(sessao, job)
        return

    try:
        _estagio(sessao, job, "resolving")
        spec = run(
            marca=str(payload.get("marca") or ""),
            modelo=str(payload.get("modelo") or ""),
            versao=str(payload.get("versao") or ""),
            atributos=payload.get("attributes"),
            replay=os.environ.get("REPLAY_MODE", "1") not in {"0", "false", "False"},
            version_id=str(payload.get("version_id") or ""),
            job_id=job.id,
        )
    except Exception as exc:
        # O traceback vai para o LOG, indexado pelo job_id. Nunca para o banco: o cliente
        # da API leria o caminho de arquivos do servidor.
        log.error(
            "worker.job_falhou",
            job_id=job.id,
            tipo=job.tipo,
            erro=str(exc),
            traceback=traceback.format_exc(),
        )
        job.status = JobStatus.FALHOU.value
        job.error = f"{type(exc).__name__}: {exc}"[:TAMANHO_DO_ERRO]
        job.concluido_em = _agora()
        job.atualizado_em = _agora()
        sessao.add(job)
        sessao.commit()
        return

    _estagio(sessao, job, "persisting")
    novo_payload = dict(payload)
    from pipeline.research.gaps import medir

    cobertura = medir(spec)
    novo_payload["campos_com_valor"] = cobertura.com_valor
    novo_payload["campos_alvo"] = cobertura.total
    novo_payload["version_resolution"] = spec.meta.version_resolution.status
    if spec.meta.version_resolution.status != "encontrada":
        novo_payload["alternatives"] = list(spec.meta.version_resolution.alternatives)

    job.payload = novo_payload
    job.status = JobStatus.CONCLUIDO.value
    job.stage = "done"
    job.concluido_em = _agora()
    job.atualizado_em = _agora()
    sessao.add(job)
    sessao.commit()
    log.info(
        "worker.job_concluido",
        job_id=job.id,
        campos=novo_payload["campos_com_valor"],
        resolucao=novo_payload["version_resolution"],
    )


def rodar_uma_vez(resultado: Resultado | None = None) -> Resultado:
    """Pega e executa **um** job. É a unidade que o teste exercita."""
    resultado = resultado or Resultado()
    with Session(engine()) as sessao:
        job = tomar_job(sessao)
        if job is None:
            resultado.ociosos += 1
            return resultado
        resultado.pegos += 1
        job_id = job.id
        executar_job(sessao, job)
        sessao.expire_all()
        final = sessao.get(Job, job_id)
        if final is not None and final.status == JobStatus.CONCLUIDO.value:
            resultado.concluidos += 1
        else:
            resultado.falhados += 1
            if final is not None and final.error:
                resultado.erros.append(final.error)
    return resultado


def main(*, once: bool = False, intervalo: float = INTERVALO_S) -> int:
    """Laço do worker. `once=True` faz uma passada e sai (é o que o teste usa).

    `SIGINT`/`SIGTERM` pedem parada **limpa**: o job em andamento termina antes de o
    processo sair. Matar no meio deixaria o job em `executando` para sempre, e a
    recuperação seria mexer no banco à mão.
    """
    from pipeline import llm
    from pipeline.research.search import provedor_configurado

    log.info(
        "worker.configuracao",
        busca=provedor_configurado() or "ausente",
        chave_busca_presente=bool(os.environ.get("SEARCH_API_KEY")),
        modelo=llm.modelo_pequeno(),
        chave_modelo_presente=bool(llm.chave_do_provedor()),
        replay=os.environ.get("REPLAY_MODE", "1"),
        modelo_simulado=llm.modo_fake(),
    )

    parar = {"pedido": False}

    def _pedir_parada(_sinal, _quadro) -> None:  # pragma: no cover - depende de sinal
        parar["pedido"] = True
        log.info("worker.parada_pedida")

    for sinal in (signal.SIGINT, signal.SIGTERM):
        # Thread sem controle de sinal (o teste, por exemplo) levanta aqui — e nao ter
        # parada limpa num worker de teste nao e problema.
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sinal, _pedir_parada)

    log.info(
        "worker.iniciado",
        banco="postgres" if _e_postgres() else "sqlite",
        tomada="FOR UPDATE SKIP LOCKED" if _e_postgres() else "compare-and-set",
        once=once,
    )

    total = Resultado()
    while not parar["pedido"]:
        antes = total.pegos
        # O batimento vem ANTES da volta, e não depois: assim ele existe já no primeiro
        # ciclo, antes de qualquer job, e `/health` responde certo desde o primeiro
        # segundo em que o worker está de pé.
        with Session(engine(database_url())) as sessao:
            bater(sessao, jobs_concluidos=total.concluidos)
        rodar_uma_vez(total)
        if once:
            break
        if total.pegos == antes:
            # Fila vazia: espera. Sem isso o worker faria consulta em laço fechado.
            time.sleep(intervalo)

    print(
        f"worker: {total.pegos} job(s) pego(s), {total.concluidos} concluido(s), "
        f"{total.falhados} falhado(s)"
    )
    return 0 if not total.falhados else 1
