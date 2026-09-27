"""`/health` sabe se o worker está vivo.

**O defeito** (12/09/2026): um avaliador pediu o documento do cliente e a tela girou até
desistir. O worker tinha morrido, e **nada no sistema sabia disso** — nem quem olhava a
tela, nem `/health`, nem quem administra a máquina. A tela dizia "quem cuida da máquina
precisa religar o processador de fila": jargão, e inútil, porque quem lê aquela frase é um
vendedor.

**Por que uma tabela e não `jobs`.** `Job.atualizado_em` só se move quando existe job. Com
a fila vazia — o estado normal — não há linha para carimbar, e "nenhum job recente" fica
indistinguível de "worker morto".
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlmodel import select

from api.app.db import session_scope
from api.app.models import WorkerHeartbeat
from pipeline import worker

HEALTH = "/api/v1/health"


def _carimbar(segundos_atras: float, *, pid: int = 4242) -> None:
    agora = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    with session_scope() as sessao:
        linha = sessao.get(WorkerHeartbeat, "worker") or WorkerHeartbeat(id="worker")
        linha.visto_em = agora - dt.timedelta(seconds=segundos_atras)
        linha.pid = pid
        sessao.add(linha)
        sessao.commit()


class TestOWorkerNoHealth:
    def test_sem_batimento_nenhum_o_worker_nao_esta_ok_e_diz_por_que(
        self, cliente: TestClient, schema_criado: None
    ) -> None:
        """ "Nunca subiu" é diferente de "subiu e morreu", e a diferença importa."""
        corpo = cliente.get(HEALTH).json()
        assert corpo["worker"]["ok"] is False
        assert "nunca subiu" in corpo["worker"]["motivo"]
        assert corpo["worker"]["visto_em"] is None

    def test_batimento_recente_e_worker_vivo(
        self, cliente: TestClient, schema_criado: None
    ) -> None:
        _carimbar(0.5)
        corpo = cliente.get(HEALTH).json()
        assert corpo["worker"]["ok"] is True
        assert corpo["worker"]["pid"] == 4242
        assert corpo["worker"]["ha_quantos_segundos"] < worker.TOLERANCIA_DO_BATIMENTO_S
        assert corpo["worker"]["motivo"] is None

    def test_batimento_velho_e_worker_fora_do_ar(
        self, cliente: TestClient, schema_criado: None
    ) -> None:
        _carimbar(worker.TOLERANCIA_DO_BATIMENTO_S + 30)
        corpo = cliente.get(HEALTH).json()
        assert corpo["worker"]["ok"] is False
        assert "último sinal de vida" in corpo["worker"]["motivo"]
        assert corpo["worker"]["visto_em"] is not None

    def test_o_status_da_API_nao_degrada_por_causa_do_worker(
        self, cliente: TestClient, schema_criado: None
    ) -> None:
        """A API está de pé. Dizer o contrário faria um monitor externo reiniciar o
        processo errado — o que quebra com o worker fora é a geração de documento, e é
        isso que o bloco `worker` informa."""
        _carimbar(3600)
        corpo = cliente.get(HEALTH).json()
        assert corpo["status"] == "ok"
        assert corpo["db"]["ok"] is True
        assert corpo["worker"]["ok"] is False

    def test_o_health_continua_publico_e_sem_a_url_do_banco(
        self, cliente: TestClient, schema_criado: None
    ) -> None:
        _carimbar(1)
        resposta = cliente.get(HEALTH)
        assert resposta.status_code == 200
        assert "sqlite:///" not in resposta.text
        assert "postgresql" not in resposta.text


class TestOBatimento:
    def test_bater_cria_e_atualiza_uma_linha_so(self, schema_criado: None) -> None:
        """É termômetro, não histórico: a pergunta é "está vivo agora?"."""
        with session_scope() as sessao:
            worker.bater(sessao, jobs_concluidos=0)
            worker.bater(sessao, jobs_concluidos=3)
        # Sessão nova: o `commit` do `bater` desliga as instâncias da anterior.
        with session_scope() as sessao:
            linhas = list(sessao.exec(select(WorkerHeartbeat)))
            assert len(linhas) == 1
            assert linhas[0].id == "worker"
            assert linhas[0].jobs_concluidos == 3
            assert linhas[0].pid is not None

    def test_falha_de_escrita_nao_derruba_o_worker(self, schema_criado: None) -> None:
        """Um batimento perdido é um aviso a menos; perder o worker por causa do
        termômetro seria trocar o problema por um pior."""

        class SessaoQuebrada:
            def get(self, *_args, **_kwargs):
                raise RuntimeError("banco fora")

            def rollback(self):
                pass

        worker.bater(SessaoQuebrada(), jobs_concluidos=1)  # type: ignore[arg-type]

    def test_o_laco_carimba_antes_de_trabalhar(self, schema_criado: None) -> None:
        """O batimento vem antes da volta: assim `/health` responde certo já no primeiro
        segundo em que o worker está de pé, com a fila ainda vazia."""
        worker.main(once=True, intervalo=0.01)
        with session_scope() as sessao:
            linha = sessao.get(WorkerHeartbeat, "worker")
            assert linha is not None
            assert linha.visto_em is not None
