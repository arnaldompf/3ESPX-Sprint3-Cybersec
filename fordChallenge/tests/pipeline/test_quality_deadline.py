import pytest

from pipeline import deadline
from pipeline.research import checkpoint
from pipeline.research.planner import Alvo


def test_espera_maior_que_orcamento_nao_dorme():
    with deadline.budget(0.01), pytest.raises(TimeoutError):
        deadline.sleep(10)


def test_prazo_e_restaurado_apos_excecao():
    with pytest.raises(TimeoutError), deadline.budget(0):
        deadline.timeout(30)
    assert deadline.remaining() is None


def test_checkpoint_recusa_identidade_diferente(tmp_path):
    import json

    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps({"policy": "quality-1", "target": {"ano": 2023}}))
    with pytest.raises(ValueError):
        checkpoint.load(str(path), Alvo("Ford", "Ranger", "Limited", 2027))


def test_retomada_preserva_decisao_e_nao_repete_cobranca_com_orcamento_gasto(tmp_path, monkeypatch):
    import json

    from pipeline.research import gaps, run
    from pipeline.research.events import Trilha
    from pipeline.schema import Evidence, SpecField, empty_spec

    target = Alvo("Ford", "Ranger", "Limited 3.0 V6", 2027)
    budget = gaps.Orcamento(paginas=1)
    budget.paginas_gastas = 1
    budget.rodadas_gastas = 1
    budget.chamadas_llm_gastas = 2
    reader = run.Leitor(target, budget, Trilha())
    reader.pending = [{"url": "https://ford.com.br/proxima"}]
    spec = empty_spec()
    spec.set(
        "motorizacao.potencia_cv",
        SpecField.verificado(
            250,
            Evidence(
                evidence_id="p",
                source_url="https://ford.com.br/ficha",
                tier=1,
                quote="Potência 250 cv",
                captured_at="2026-09-14",
            ),
        ),
    )
    path = str(tmp_path / "resume.json")
    checkpoint.save(path, target, [], reader, spec, {"consulta anterior"})
    monkeypatch.setattr(run.busca, "buscar", lambda *a, **k: pytest.fail("repetiu busca paga"))
    result = run.pesquisar(
        target.marca,
        target.modelo,
        target.versao,
        ano=2027,
        campos=["potencia_cv"],
        orcamento=gaps.Orcamento(paginas=1),
        checkpoint_path=path,
    )
    assert result.spec.motorizacao["potencia_cv"].value == 250
    assert result.orcamento.chamadas_llm_gastas == 2
    assert result.orcamento.rodadas_gastas == 1
    assert result.motivo_da_parada == gaps.Motivo.PAGINAS
    assert json.loads((tmp_path / "resume.json").read_text())["pending"] == reader.pending
