"""Métricas no formato de exposição do Prometheus, sem dependência nova.

A solução não tem `prometheus_client` e esta camada não altera as dependências dela. O
formato texto do Prometheus é simples o bastante para ser escrito à mão: contador,
histograma e gauge, com rótulos. Thread-safe porque o uvicorn atende em threads (rotas
síncronas do FastAPI rodam no threadpool).

Cardinalidade: o rótulo de rota é o **modelo** da rota (`/api/v1/vehicles/{vehicle_id}`),
nunca o caminho concreto. Caminho concreto com id cria uma série por veículo e derruba o
Prometheus; quem garante isso é `app_segura`, que passa o modelo.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Iterable

Rotulos = tuple[tuple[str, str], ...]

#: Faixas do histograma de latência, em segundos. Cobrem do cache (5 ms) à extração lenta.
FAIXAS_LATENCIA = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _escapar(valor: str) -> str:
    return valor.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _formatar_rotulos(rotulos: Rotulos, extra: Iterable[tuple[str, str]] = ()) -> str:
    pares = [*rotulos, *extra]
    if not pares:
        return ""
    return "{" + ",".join(f'{k}="{_escapar(v)}"' for k, v in pares) + "}"


class Registro:
    """Contadores, histogramas e gauges de um processo."""

    def __init__(self) -> None:
        self._trava = threading.Lock()
        self._ajuda: dict[str, tuple[str, str]] = {}
        self._contadores: dict[str, dict[Rotulos, float]] = defaultdict(dict)
        self._gauges: dict[str, dict[Rotulos, float]] = defaultdict(dict)
        self._hist: dict[str, dict[Rotulos, list[float]]] = defaultdict(dict)

    def declarar(self, nome: str, tipo: str, ajuda: str) -> None:
        self._ajuda[nome] = (tipo, ajuda)

    def incrementar(self, nome: str, valor: float = 1.0, **rotulos: str) -> None:
        chave = tuple(sorted(rotulos.items()))
        with self._trava:
            serie = self._contadores[nome]
            serie[chave] = serie.get(chave, 0.0) + valor

    def definir(self, nome: str, valor: float, **rotulos: str) -> None:
        chave = tuple(sorted(rotulos.items()))
        with self._trava:
            self._gauges[nome][chave] = valor

    def limpar_gauge(self, nome: str) -> None:
        with self._trava:
            self._gauges.pop(nome, None)

    def observar(self, nome: str, valor: float, **rotulos: str) -> None:
        chave = tuple(sorted(rotulos.items()))
        with self._trava:
            # [contagem por faixa..., +Inf, soma]
            baldes = self._hist[nome].setdefault(chave, [0.0] * (len(FAIXAS_LATENCIA) + 2))
            for i, limite in enumerate(FAIXAS_LATENCIA):
                if valor <= limite:
                    baldes[i] += 1
            baldes[len(FAIXAS_LATENCIA)] += 1
            baldes[len(FAIXAS_LATENCIA) + 1] += valor

    def valor(self, nome: str, **rotulos: str) -> float:
        """Leitura pontual, para teste."""
        chave = tuple(sorted(rotulos.items()))
        with self._trava:
            if nome in self._contadores:
                return self._contadores[nome].get(chave, 0.0)
            return self._gauges.get(nome, {}).get(chave, 0.0)

    def zerar(self) -> None:
        with self._trava:
            self._contadores.clear()
            self._gauges.clear()
            self._hist.clear()

    def exportar(self) -> str:
        """O corpo de `/metrics` (text/plain; version=0.0.4)."""
        linhas: list[str] = []
        with self._trava:
            for nome in sorted({*self._contadores, *self._gauges, *self._hist}):
                tipo, ajuda = self._ajuda.get(nome, ("untyped", ""))
                if ajuda:
                    linhas.append(f"# HELP {nome} {ajuda}")
                linhas.append(f"# TYPE {nome} {tipo}")
                for chave, v in sorted(self._contadores.get(nome, {}).items()):
                    linhas.append(f"{nome}{_formatar_rotulos(chave)} {v:g}")
                for chave, v in sorted(self._gauges.get(nome, {}).items()):
                    linhas.append(f"{nome}{_formatar_rotulos(chave)} {v:g}")
                for chave, baldes in sorted(self._hist.get(nome, {}).items()):
                    for i, limite in enumerate(FAIXAS_LATENCIA):
                        rot = _formatar_rotulos(chave, [("le", f"{limite:g}")])
                        linhas.append(f"{nome}_bucket{rot} {baldes[i]:g}")
                    total = baldes[len(FAIXAS_LATENCIA)]
                    linhas.append(
                        f"{nome}_bucket{_formatar_rotulos(chave, [('le', '+Inf')])} {total:g}"
                    )
                    linhas.append(f"{nome}_sum{_formatar_rotulos(chave)} {baldes[-1]:.6f}")
                    linhas.append(f"{nome}_count{_formatar_rotulos(chave)} {total:g}")
        return "\n".join(linhas) + "\n"


REGISTRO = Registro()
REGISTRO.declarar("specradar_http_requisicoes_total", "counter", "Requisicoes HTTP atendidas.")
REGISTRO.declarar("specradar_http_latencia_segundos", "histogram", "Latencia das requisicoes HTTP.")
REGISTRO.declarar(
    "specradar_eventos_seguranca_total",
    "counter",
    "Eventos de seguranca: acesso_negado, limite_excedido, alteracao_critica, ssrf_bloqueado.",
)
REGISTRO.declarar("specradar_jobs", "gauge", "Jobs do pipeline por status (fila no banco).")
REGISTRO.declarar(
    "specradar_eval_metrica", "gauge", "Qualidade do pipeline de extracao (ultimo eval)."
)
REGISTRO.declarar(
    "specradar_coleta_metricas_falhou", "gauge", "1 quando um coletor de metricas falhou."
)
