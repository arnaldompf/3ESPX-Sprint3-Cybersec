"""O teto de serviços vale antes da rede, inclusive em retomadas e concorrência."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from pipeline.research import service_budget


def test_defaults_sao_independentes_do_orcamento_llm(monkeypatch):
    monkeypatch.delenv("RESEARCH_SERVICES_MAX_USD", raising=False)
    monkeypatch.delenv("RESEARCH_SERVICES_MAX_CALLS", raising=False)
    budget = service_budget.ServiceBudget()
    assert budget.max_usd == 1.0
    assert budget.max_calls == 30


def test_reserva_impede_exceder_valor_e_chamadas():
    budget = service_budget.ServiceBudget(max_usd=0.016, max_calls=2)
    budget.reserve("tavily", "search", 0.008)
    budget.reserve("tavily", "search", 0.008)
    with pytest.raises(service_budget.BudgetExceeded):
        budget.reserve("tavily", "search", 0.008)
    assert budget.calls == 2
    assert budget.accounted_usd == 0.016
    assert budget.actual_usd is None


def test_teto_de_chamadas_tambem_vale_quando_usage_informa_zero():
    budget = service_budget.ServiceBudget(max_usd=1, max_calls=1)
    receipt = budget.reserve("tavily", "search", 0.008)
    receipt.settle(0, usage={"credits": 0}, actual_basis="usage_credits")
    with pytest.raises(service_budget.BudgetExceeded):
        budget.reserve("tavily", "search", 0.008)
    assert budget.accounted_usd == budget.actual_usd == 0


def test_usage_explicita_ajusta_previsao_sem_apagar_historico():
    budget = service_budget.ServiceBudget(max_usd=0.024, max_calls=3)
    one = budget.reserve("tavily", "extract", 0.016)
    one.settle(0.008, usage={"credits": 1}, actual_basis="usage_credits")
    budget.reserve("tavily", "extract", 0.016)
    assert budget.estimated_usd == 0.032
    assert budget.actual_usd == 0.008
    assert budget.accounted_usd == 0.024
    with pytest.raises(service_budget.BudgetExceeded):
        budget.reserve("exa", "search", 0.007)


def test_custo_real_maior_que_previsao_e_preservado_e_bloqueia_proxima():
    budget = service_budget.ServiceBudget(max_usd=0.007, max_calls=3)
    receipt = budget.reserve("exa", "search", 0.007)
    receipt.settle(0.009, usage={"total": 0.009}, actual_basis="provider_usd")
    assert budget.accounted_usd == 0.009
    with pytest.raises(service_budget.BudgetExceeded):
        budget.reserve("exa", "search", 0.007)


def test_acerto_e_idempotente_e_nao_pode_trocar_valor_confirmado():
    budget = service_budget.ServiceBudget(max_usd=1, max_calls=2)
    receipt = budget.reserve("exa", "search", 0.007)
    receipt.settle(0.006, usage={"total": 0.006})
    receipt.settle(0.006, usage={"total": 0.006})
    with pytest.raises(ValueError):
        receipt.settle(0)
    assert budget.accounted_usd == 0.006


def test_checkpoint_preserva_reserva_incerta_e_nao_confia_em_totais_editados():
    original = service_budget.ServiceBudget(max_usd=0.015, max_calls=2)
    original.reserve("tavily", "search", 0.008)
    payload = original.to_dict()
    payload["accounted_usd"] = 0
    restored = service_budget.ServiceBudget.from_dict(json.loads(json.dumps(payload)))
    assert restored.accounted_usd == 0.008
    assert restored.calls == 1
    restored.reserve("exa", "search", 0.007)
    with pytest.raises(service_budget.BudgetExceeded):
        restored.reserve("brave", "search", 0.005)


def test_checkpoint_nao_armazena_payload_chave_ou_consulta():
    budget = service_budget.ServiceBudget(max_usd=1, max_calls=2)
    receipt = budget.reserve("tavily", "search", 0.008)
    receipt.settle(
        0.008,
        usage={"credits": 1, "api_key": "segredo", "query": "cliente identificado"},
    )
    serialized = json.dumps(budget.to_dict())
    assert "segredo" not in serialized and "cliente identificado" not in serialized
    assert "api_key" not in serialized and "query" not in serialized


@pytest.mark.parametrize("valor", [-1, float("nan"), float("inf"), True, "1e10000"])
def test_orcamento_invalido_e_rejeitado(valor):
    with pytest.raises(ValueError):
        service_budget.ServiceBudget(max_usd=valor, max_calls=2)


def test_scope_restaura_contexto_e_aninhamento_nao_renova_teto():
    assert service_budget.current_budget() is None
    budget = service_budget.ServiceBudget(max_usd=0.007, max_calls=1)
    with service_budget.scope(budget):
        assert service_budget.current_budget() is budget
        with service_budget.scope() as nested:
            assert nested is budget
            service_budget.reserve("exa", "search", 0.007)
        with pytest.raises(service_budget.BudgetExceeded):
            service_budget.reserve("exa", "search", 0.007)
    assert service_budget.current_budget() is None


def test_reservas_concorrentes_respeitam_teto_compartilhado():
    budget = service_budget.ServiceBudget(max_usd=0.035, max_calls=5)

    def reserve(_):
        with service_budget.scope(budget):
            try:
                service_budget.reserve("exa", "search", 0.007)
            except service_budget.BudgetExceeded:
                return False
        return True

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(reserve, range(50)))
    assert sum(results) == budget.calls == 5
    assert budget.accounted_usd == 0.035


def test_callback_checkpoint_pode_ler_budget_sem_deadlock():
    changes = []
    budget = service_budget.ServiceBudget(max_usd=1, max_calls=2)
    budget.on_change = lambda: changes.append(budget.to_dict())
    receipt = budget.reserve("exa", "search", 0.007)
    receipt.note_estimate(0.006)
    receipt.settle(0.007, actual_basis="provider_usd")
    assert len(changes) == 3
    assert changes[0]["accounted_usd"] == 0.007
    assert changes[1]["reservations"][0]["provider_estimate_usd"] == 0.006
    assert changes[2]["actual_usd"] == 0.007


def test_estimativa_menor_nao_libera_reserva_e_maior_e_conservada():
    budget = service_budget.ServiceBudget(max_usd=0.014, max_calls=3)
    receipt = budget.reserve("exa", "search", 0.007)
    receipt.note_estimate(0.006)
    assert budget.accounted_usd == 0.007
    receipt.note_estimate(0.014)
    assert budget.accounted_usd == 0.014
    assert budget.actual_usd is None
    with pytest.raises(service_budget.BudgetExceeded):
        budget.reserve("exa", "search", 0.007)
