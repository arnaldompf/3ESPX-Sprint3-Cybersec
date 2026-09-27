"""A trilha da pesquisa chega à tabela **enquanto** a pesquisa acontece.

Até 13/09/2026 `Trilha` acumulava em memória e `research.gravar` escrevia tudo no fim. A
tela lia da tabela: o "painel ao vivo" via a pesquisa pronta. Este arquivo fixa o contrário,
e fixa também o que não pode acontecer com a gravação em dois tempos — duplicata.

O `pesquisar` é dublado por um que emite três eventos e, **no meio**, abre outra sessão e
conta as linhas gravadas. Se a escrita fosse só no fim, a contagem no meio seria zero.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, select

from api.app.db import engine
from api.app.models import Job, JobStatus, ResearchEvent, ResearchRun
from pipeline import worker
from pipeline.research import gaps
from pipeline.research.events import Tipo, Trilha
from pipeline.schema import empty_spec


@pytest.fixture
def pesquisa_na_fila(schema_criado: None) -> tuple[str, str]:
    """Um `ResearchRun` e o `Job(tipo=research)` que o worker vai pegar."""
    from api.app.db import session_scope

    with session_scope() as sessao:
        run = ResearchRun(marca="Mitsubishi", modelo="Triton", versao="HPE-S", status="pendente")
        sessao.add(run)
        sessao.flush()
        job = Job(
            tipo="research",
            status=JobStatus.PENDENTE.value,
            payload={
                "run_id": run.id,
                "marca": "Mitsubishi",
                "modelo": "Triton",
                "versao": "HPE-S",
                "ano": 2026,
                "rodadas": 1,
                "paginas": 2,
                "segundos": 30,
            },
        )
        sessao.add(job)
        sessao.commit()
        return run.id, job.id


def _contar(run_id: str) -> int:
    with Session(engine()) as s:
        return len(s.exec(select(ResearchEvent).where(ResearchEvent.run_id == run_id)).all())


def _resultado_falso(trilha: Trilha):
    from pipeline import llm
    from pipeline.research import run as modulo

    spec = empty_spec(job_id="research:teste")
    return modulo.Resultado(
        marca="Mitsubishi",
        modelo="Triton",
        versao="HPE-S",
        spec=spec,
        trilha=trilha,
        cobertura=gaps.medir(spec),
        orcamento=gaps.Orcamento(rodadas=1, paginas=2, segundos=30),
        motivo_da_parada=gaps.Motivo.COBERTURA,
        fontes=[],
        avisos=[],
        medicao=llm.Medicao(),
    )


class TestAoVivo:
    def test_cada_evento_esta_na_tabela_antes_do_fim(self, pesquisa_na_fila, monkeypatch):
        run_id, job_id = pesquisa_na_fila
        vistos_no_meio: list[int] = []

        def pesquisar_falso(*_args, ao_evento=None, **_kw):
            trilha = Trilha(ao_registrar=ao_evento)
            trilha.registrar(Tipo.INICIO, "procurando Mitsubishi Triton HPE-S")
            trilha.registrar(Tipo.CONSULTA, "Mitsubishi Triton HPE-S ficha técnica oficial")
            # **No meio da pesquisa**, outra sessão já vê os dois passos gravados.
            vistos_no_meio.append(_contar(run_id))
            trilha.registrar(Tipo.FIM, "pesquisa concluída: 0 de 55 campos respondidos")
            return _resultado_falso(trilha)

        monkeypatch.setattr("pipeline.research.run.pesquisar", pesquisar_falso)
        resultado = worker.rodar_uma_vez()

        assert resultado.concluidos == 1, resultado.erros
        assert vistos_no_meio == [2], "a trilha só foi gravada no fim"
        assert _contar(run_id) == 3, "o fim entrou duas vezes, ou não entrou"

        with Session(engine()) as s:
            linha = s.get(ResearchRun, run_id)
            assert linha is not None and linha.status == "concluida"
            ordens = sorted(
                e.ordem for e in s.exec(select(ResearchEvent).where(ResearchEvent.run_id == run_id))
            )
            assert ordens == [0, 1, 2]
            job = s.get(Job, job_id)
            assert job is not None and job.status == JobStatus.CONCLUIDO.value

    def test_o_fim_so_aparece_quando_o_run_ja_esta_concluido(self, pesquisa_na_fila, monkeypatch):
        """Quem faz polling e vê `fim` pode ir buscar o `version_id` sem corrida: o `fim`
        sai no mesmo commit de `status="concluida"`."""
        run_id, _ = pesquisa_na_fila
        estado_no_fim: list[str] = []

        def pesquisar_falso(*_args, ao_evento=None, **_kw):
            trilha = Trilha(ao_registrar=ao_evento)
            trilha.registrar(Tipo.INICIO, "procurando")
            trilha.registrar(Tipo.FIM, "fim")
            # Logo depois de o FIM ser registrado na trilha, a tabela ainda não o tem —
            # e o run ainda não está concluído. Os dois viram juntos, em `gravar`.
            with Session(engine()) as s:
                estado_no_fim.append(s.get(ResearchRun, run_id).status)
                estado_no_fim.append(str(_contar(run_id)))
            return _resultado_falso(trilha)

        monkeypatch.setattr("pipeline.research.run.pesquisar", pesquisar_falso)
        worker.rodar_uma_vez()
        assert estado_no_fim == ["pendente", "1"]
        assert _contar(run_id) == 2

    def test_observador_com_banco_quebrado_nao_derruba_a_pesquisa(
        self, pesquisa_na_fila, monkeypatch
    ):
        """A escrita incremental é cortesia para a tela; a pesquisa e a gravação final não
        podem morrer porque ela falhou."""
        run_id, _ = pesquisa_na_fila

        def pesquisar_falso(*_args, ao_evento=None, **_kw):
            trilha = Trilha(ao_registrar=ao_evento)
            trilha.registrar(Tipo.INICIO, "procurando")
            trilha.registrar(Tipo.FIM, "fim")
            return _resultado_falso(trilha)

        monkeypatch.setattr("pipeline.research.run.pesquisar", pesquisar_falso)

        original = worker._linha_de_evento

        def explode(*_a, **_k):
            raise RuntimeError("banco do observador caiu")

        monkeypatch.setattr(worker, "_linha_de_evento", explode)
        resultado = worker.rodar_uma_vez()
        monkeypatch.setattr(worker, "_linha_de_evento", original)

        assert resultado.concluidos == 1, resultado.erros
        # `gravar` no fim escreveu o que o observador não conseguiu.
        assert _contar(run_id) == 2
