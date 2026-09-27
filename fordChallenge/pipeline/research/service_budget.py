"""Orçamento de serviços por execução, separado de tokens e saldo de contas.

Reservas incertas continuam contabilizadas após timeout ou retomada. Preços são tarifas
conservadoras de referência; créditos promocionais e faturamento não são presumidos.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation
from threading import Lock

TAVILY_CREDIT_USD = 0.008
TAVILY_SEARCH_BASIC_USD = 0.008
TAVILY_SEARCH_ADVANCED_USD = 0.016
TAVILY_EXTRACT_ADVANCED_USD = 0.016
EXA_SEARCH_USD = 0.007
BRAVE_SEARCH_USD = 0.005
_PROVIDERS = {"tavily", "exa", "brave"}
_OPERATIONS = {"search", "extract"}
_USAGE_KEYS = {"credits", "total", "pages", "tokens", "estimated_total_usd"}
_BASES = {"usage_credits", "provider_usd", ""}
_current: ContextVar[ServiceBudget | None] = ContextVar("research_service_budget", default=None)


class BudgetExceeded(RuntimeError):
    """A próxima chamada ultrapassaria o teto; nenhuma requisição deve ser enviada."""


def _money(value) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("valor monetário inválido") from exc
    if (
        isinstance(value, bool)
        or not number.is_finite()
        or number < 0
        or not math.isfinite(float(number))
    ):
        raise ValueError("valor monetário deve ser finito e não negativo")
    return number


def _safe_usage(usage: dict | None) -> dict[str, float]:
    clean = {}
    for key, value in (usage if isinstance(usage, dict) else {}).items():
        if key not in _USAGE_KEYS:
            continue
        try:
            clean[key] = float(_money(value))
        except ValueError:
            continue
    return clean


class Reservation:
    def __init__(self, budget: ServiceBudget, number: int):
        self._budget = budget
        self.number = number

    def to_dict(self) -> dict:
        with self._budget._lock:
            record = self._budget._records[self.number]
            return {**record, "usage": dict(record["usage"])}

    def settle(self, actual_usd, *, usage=None, actual_basis="") -> None:
        self._budget.settle(self, actual_usd, usage=usage, actual_basis=actual_basis)

    def note_estimate(self, estimated_usd) -> None:
        """Estimativa do fornecedor não é consumo confirmado e não libera a reserva."""
        value = float(_money(estimated_usd))
        with self._budget._lock:
            record = self._budget._records[self.number]
            record["provider_estimate_usd"] = value
            record["usage"]["estimated_total_usd"] = value
        self._budget._changed()


class ServiceBudget:
    def __init__(self, max_usd=None, max_calls=None, on_change: Callable[[], None] | None = None):
        self.max_usd = float(
            _money(
                (os.environ.get("RESEARCH_SERVICES_MAX_USD") or "1") if max_usd is None else max_usd
            )
        )
        value = (
            (os.environ.get("RESEARCH_SERVICES_MAX_CALLS") or "30")
            if max_calls is None
            else max_calls
        )
        if isinstance(value, bool) or str(value) != str(int(value)) or int(value) < 0:
            raise ValueError("max_calls deve ser inteiro não negativo")
        self.max_calls = int(value)
        self._lock = Lock()
        self._records: dict[int, dict] = {}
        self.on_change = on_change

    def _changed(self) -> None:
        # O callback persiste a reserva antes do HTTP. Nunca executá-lo segurando o lock:
        # ele precisa poder chamar to_dict. Falha propaga, sem desfazer a reserva incerta.
        if self.on_change is not None:
            self.on_change()

    def _sum(self, kind: str) -> Decimal:
        values = []
        for record in self._records.values():
            value = record["actual_usd"] if kind == "actual" else record["estimated_usd"]
            if kind == "accounted" and record["actual_usd"] is not None:
                value = record["actual_usd"]
            elif kind == "accounted" and record["provider_estimate_usd"] is not None:
                value = max(_money(value), _money(record["provider_estimate_usd"]))
            if value is not None:
                values.append(_money(value))
        return sum(values, Decimal(0))

    @property
    def calls(self) -> int:
        with self._lock:
            return len(self._records)

    @property
    def estimated_usd(self) -> float:
        with self._lock:
            return float(self._sum("estimated"))

    @property
    def actual_usd(self) -> float | None:
        with self._lock:
            if not any(r["actual_usd"] is not None for r in self._records.values()):
                return None
            return float(self._sum("actual"))

    @property
    def accounted_usd(self) -> float:
        with self._lock:
            return float(self._sum("accounted"))

    def reserve(self, provider: str, operation: str, estimated_usd) -> Reservation:
        if provider not in _PROVIDERS or operation not in _OPERATIONS:
            raise ValueError("provedor ou operação sem tarifa de referência")
        value = _money(estimated_usd)
        with self._lock:
            if len(self._records) >= self.max_calls:
                raise BudgetExceeded("orçamento de serviços: limite de chamadas atingido")
            if self._sum("accounted") + value > _money(self.max_usd):
                raise BudgetExceeded("orçamento de serviços: próxima chamada excederia o teto USD")
            number = len(self._records) + 1
            self._records[number] = {
                "number": number,
                "provider": provider,
                "operation": operation,
                "estimated_usd": float(value),
                "actual_usd": None,
                "actual_basis": "",
                "provider_estimate_usd": None,
                "usage": {},
            }
        self._changed()
        return Reservation(self, number)

    def settle(self, receipt: Reservation, actual_usd, *, usage=None, actual_basis="") -> None:
        if receipt._budget is not self or actual_basis not in _BASES:
            raise ValueError("reserva ou base de custo inválida")
        value = float(_money(actual_usd))
        clean = _safe_usage(usage)
        with self._lock:
            record = self._records[receipt.number]
            if record["actual_usd"] is not None and record["actual_usd"] != value:
                raise ValueError("reserva já acertada com outro valor")
            record["actual_usd"] = value
            record["actual_basis"] = actual_basis
            record["usage"].update(clean)
        self._changed()

    def to_dict(self) -> dict:
        with self._lock:
            records = [{**r, "usage": dict(r["usage"])} for r in self._records.values()]
            return {
                "version": 1,
                "max_usd": self.max_usd,
                "max_calls": self.max_calls,
                "calls": len(records),
                "estimated_usd": float(self._sum("estimated")),
                "actual_usd": (
                    float(self._sum("actual"))
                    if any(r["actual_usd"] is not None for r in records)
                    else None
                ),
                "accounted_usd": float(self._sum("accounted")),
                "reservations": records,
            }

    @classmethod
    def from_dict(cls, value: dict) -> ServiceBudget:
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("checkpoint de orçamento incompatível")
        budget = cls(max_usd=value["max_usd"], max_calls=value["max_calls"])
        records = value.get("reservations")
        if not isinstance(records, list) or len(records) > budget.max_calls:
            raise ValueError("reservas inválidas no checkpoint")
        for number, record in enumerate(records, 1):
            if (
                not isinstance(record, dict)
                or record.get("number") != number
                or record.get("provider") not in _PROVIDERS
                or record.get("operation") not in _OPERATIONS
                or record.get("actual_basis", "") not in _BASES
            ):
                raise ValueError("reserva inválida no checkpoint")
            # Não usar reserve: usage confirmada pode ter excedido a previsão original.
            budget._records[number] = {
                "number": number,
                "provider": record["provider"],
                "operation": record["operation"],
                "estimated_usd": float(_money(record["estimated_usd"])),
                "actual_usd": (
                    None
                    if record.get("actual_usd") is None
                    else float(_money(record["actual_usd"]))
                ),
                "actual_basis": record.get("actual_basis", ""),
                "provider_estimate_usd": (
                    None
                    if record.get("provider_estimate_usd") is None
                    else float(_money(record["provider_estimate_usd"]))
                ),
                "usage": _safe_usage(record.get("usage")),
            }
        return budget


def current_budget() -> ServiceBudget | None:
    return _current.get()


@contextmanager
def scope(budget: ServiceBudget | None = None, *, max_usd=None, max_calls=None):
    if budget is None:
        budget = current_budget() if max_usd is None and max_calls is None else None
        budget = budget or ServiceBudget(max_usd=max_usd, max_calls=max_calls)
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def reserve(provider: str, operation: str, estimated_usd) -> Reservation:
    budget = current_budget() or ServiceBudget()
    return budget.reserve(provider, operation, estimated_usd)


def settle_tavily(receipt: Reservation, payload: dict) -> None:
    usage = payload.get("usage")
    if not isinstance(usage, dict) or "credits" not in usage:
        return
    try:
        credits = _money(usage["credits"])
    except ValueError:
        return
    receipt.settle(
        credits * _money(TAVILY_CREDIT_USD),
        usage={"credits": float(credits)},
        actual_basis="usage_credits",
    )
