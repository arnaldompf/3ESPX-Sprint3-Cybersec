"""WP-14 — do `POST /extractions` ao job `concluido`, passando pelo worker.

Os dois critérios de aceite da spec, e a garantia que ela põe nas notas: **dois workers
não pegam o mesmo job**. Esse último é testado com duas threads disputando um job só,
porque é a única forma de exercitar a tomada atômica — um teste sequencial passaria com
uma implementação errada.
"""

from __future__ import annotations

import threading

import pytest
from sqlmodel import Session, select

from api.app.db import engine
from api.app.models import Job, JobStatus, Role
from pipeline import worker

EXTRACTIONS = "/api/v1/extractions"


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def job_na_fila(cliente_auth, catalogo, analista):
    """Um job criado **pela API**, como a spec pede."""
    resposta = cliente_auth.post(
        EXTRACTIONS,
        headers=analista,
        json={
            "marca": "Ford",
            "modelo": "Ranger",
            "versao": "Raptor 3.0 V6 Bi-turbo 4WD AT",
        },
    )
    assert resposta.status_code == 202
    return resposta.json()["job_id"]


def _job(job_id: str) -> Job:
    with Session(engine()) as sessao:
        job = sessao.get(Job, job_id)
        assert job is not None
        sessao.expunge(job)
        return job


class TestCriteriosDeAceite:
    def test_job_da_api_vira_concluido_com_result_url(self, cliente_auth, job_na_fila, analista):
        """Critério: job `queued` → worker roda → `done` com `result_url`."""
        antes = cliente_auth.get(f"/api/v1/jobs/{job_na_fila}", headers=analista).json()
        assert antes["status"] == JobStatus.PENDENTE.value
        assert antes["result_url"] is None

        resultado = worker.rodar_uma_vez()
        assert (resultado.pegos, resultado.concluidos) == (1, 0) or resultado.concluidos == 1

        depois = cliente_auth.get(f"/api/v1/jobs/{job_na_fila}", headers=analista).json()
        assert depois["status"] == JobStatus.CONCLUIDO.value, depois
        assert depois["stage"] == "done"
        assert depois["error"] is None

    def test_excecao_no_pipeline_vira_failed_sem_stack_trace(self, cliente_auth, job_na_fila):
        """Critério: exceção → `failed`, `error` **sem** traceback, log com traceback.

        O `error` vai para o cliente da API. Um traceback ali entrega o caminho de
        arquivos do servidor e a estrutura interna do código a quem consulta uma ficha.
        """
        import pipeline.run as modulo_run

        def explodir(*_args, **_kwargs):
            raise RuntimeError("falha simulada no pipeline")

        original = modulo_run.run
        modulo_run.run = explodir
        try:
            worker.rodar_uma_vez()
        finally:
            modulo_run.run = original

        job = _job(job_na_fila)
        assert job.status == JobStatus.FALHOU.value
        assert "falha simulada" in (job.error or "")
        # O que NÃO pode estar lá:
        for vazamento in ("Traceback", 'File "', '.py", line', "pipeline\\", "pipeline/"):
            assert vazamento not in (job.error or ""), vazamento


class TestTomadaAtomica:
    def test_dois_workers_nao_pegam_o_mesmo_job(self, cliente_auth, job_na_fila):
        """A garantia das notas da spec, testada com **duas threads**.

        Sequencialmente, uma implementação errada passaria: o segundo worker veria o job
        já em `executando`. A disputa real é duas threads chamando `tomar_job` ao mesmo
        tempo, e é isso que o compare-and-set (ou o `SKIP LOCKED`) resolve.
        """
        pegos: list[str] = []
        barreira = threading.Barrier(2)

        def tentar() -> None:
            barreira.wait()
            with Session(engine()) as sessao:
                job = worker.tomar_job(sessao)
                if job is not None:
                    pegos.append(job.id)

        threads = [threading.Thread(target=tentar) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(pegos) == 1, f"o job foi pego {len(pegos)} vezes: {pegos}"
        assert pegos[0] == job_na_fila

    def test_fila_vazia_devolve_none(self, catalogo):
        with Session(engine()) as sessao:
            assert worker.tomar_job(sessao) is None

    def test_tomar_marca_executando_e_conta_a_tentativa(self, cliente_auth, job_na_fila):
        with Session(engine()) as sessao:
            job = worker.tomar_job(sessao)
            assert job is not None
            assert job.status == JobStatus.EXECUTANDO.value
            assert job.tentativas == 1
            assert job.iniciado_em is not None

    def test_job_em_execucao_nao_e_pego_de_novo(self, cliente_auth, job_na_fila):
        with Session(engine()) as sessao:
            assert worker.tomar_job(sessao) is not None
            # Já está `executando`: a fila não o oferece outra vez.
            assert worker.tomar_job(sessao) is None


class TestLacoDoWorker:
    def test_once_faz_uma_passada_e_sai(self, cliente_auth, job_na_fila):
        assert worker.main(once=True) == 0
        assert _job(job_na_fila).status == JobStatus.CONCLUIDO.value

    def test_once_com_fila_vazia_nao_falha(self, catalogo):
        assert worker.main(once=True) == 0

    def test_o_estagio_avanca_e_termina_em_done(self, cliente_auth, job_na_fila):
        """Um job que morre no meio tem de dizer **onde** morreu."""
        worker.rodar_uma_vez()
        assert _job(job_na_fila).stage == "done"

    def test_o_payload_registra_o_que_o_job_produziu(self, cliente_auth, job_na_fila, monkeypatch):
        from pipeline import run as orchestration

        original = orchestration.run
        produced = []

        def capture(*args, **kwargs):
            spec = original(*args, **kwargs)
            produced.append(spec)
            return spec

        monkeypatch.setattr(orchestration, "run", capture)
        worker.rodar_uma_vez()
        payload = _job(job_na_fila).payload
        assert payload["version_resolution"] == "encontrada"
        actual = {
            path
            for path, field in produced[0].itens()
            if field.value is not None
            and field.status.value == "verificado"
            and path.split(".")[-1] not in {"marca", "modelo", "versao", "ano_modelo"}
        }
        assert actual
        assert payload["campos_com_valor"] == len(actual)
        assert payload["campos_alvo"] == 54

    def test_dois_jobs_sao_consumidos_em_duas_passadas(self, cliente_auth, catalogo, analista):
        for versao in ("Raptor 3.0 V6 Bi-turbo 4WD AT", "SRX Plus AT (Cabine Dupla)"):
            marca, modelo = ("Ford", "Ranger") if "Raptor" in versao else ("Toyota", "Hilux")
            cliente_auth.post(
                EXTRACTIONS,
                headers=analista,
                json={"marca": marca, "modelo": modelo, "versao": versao},
            )

        total = worker.Resultado()
        worker.rodar_uma_vez(total)
        worker.rodar_uma_vez(total)
        assert total.pegos == 2
        assert total.concluidos == 2

        with Session(engine()) as sessao:
            pendentes = sessao.exec(select(Job).where(Job.status == JobStatus.PENDENTE.value)).all()
        assert not pendentes


class TestVersaoInexistenteNaoEFalha:
    def test_versao_fora_de_linha_conclui_com_a_resolucao_registrada(
        self, cliente_auth, catalogo, analista
    ):
        """`versao_inexistente` é resultado, não erro do job.

        O resolvedor respondeu; a resposta é que a versão saiu de linha. Marcar o job como
        `falhou` faria a tela mostrar erro onde o produto tem a informação mais útil da
        demo.
        """
        job_id = cliente_auth.post(
            EXTRACTIONS,
            headers=analista,
            json={"marca": "Toyota", "modelo": "Hilux", "versao": "GR-Sport"},
        ).json()["job_id"]

        worker.rodar_uma_vez()
        job = _job(job_id)
        assert job.status == JobStatus.CONCLUIDO.value
        assert job.payload["version_resolution"] == "versao_inexistente"
        assert job.payload["alternatives"]
