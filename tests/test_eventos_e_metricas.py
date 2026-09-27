"""Eventos de segurança no log estruturado e a rota /metrics."""

from __future__ import annotations

from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from seguranca.app_segura import criar_app_segura
from seguranca.metricas import REGISTRO
from tests.constantes import SEGREDO_DE_TESTE


def _eventos(logs: list[dict], nome: str) -> list[dict]:
    return [e for e in logs if e.get("event") == nome]


def test_acesso_negado_vira_evento_com_ip_pseudonimizado(ambiente):
    ambiente(AUTH_ENABLED="1", JWT_SECRET=SEGREDO_DE_TESTE)
    cliente = TestClient(criar_app_segura())

    with capture_logs() as logs:
        resposta = cliente.get("/api/v1/auth/me")

    assert resposta.status_code == 401
    [evento] = _eventos(logs, "seguranca.acesso_negado")
    assert evento["status"] == 401
    assert evento["rota"] == "/api/v1/auth/me"
    assert evento["origem"] != "testclient"  # o IP nunca vai em claro
    assert len(evento["origem"]) == 16
    assert REGISTRO.valor("specradar_eventos_seguranca_total", tipo="acesso_negado") == 1


def test_escrita_em_recurso_critico_e_auditada(ambiente):
    ambiente(AUTH_ENABLED="1", JWT_SECRET=SEGREDO_DE_TESTE)
    cliente = TestClient(criar_app_segura())

    with capture_logs() as logs:
        cliente.post("/api/v1/users", json={"email": "x@exemplo.com"})

    assert _eventos(logs, "auditoria.alteracao_critica")
    assert REGISTRO.valor("specradar_eventos_seguranca_total", tipo="alteracao_critica") == 1


def test_limite_excedido_vira_evento(ambiente):
    ambiente(RATE_LIMIT_ENABLED="1", RATE_LIMIT_DEFAULT="2/minute")
    cliente = TestClient(criar_app_segura())

    with capture_logs() as logs:
        for _ in range(3):
            cliente.get("/api/v1/rota-que-nao-existe")

    assert len(_eventos(logs, "seguranca.limite_excedido")) == 1


def test_metrics_expoe_requisicoes_e_latencia_por_modelo_de_rota(ambiente):
    cliente = TestClient(criar_app_segura())
    cliente.get("/api/v1/health")

    corpo = cliente.get("/metrics").text

    assert (
        'specradar_http_requisicoes_total{metodo="GET",rota="/api/v1/health",status="200"} 1'
        in corpo
    )
    assert "specradar_http_latencia_segundos_bucket" in corpo
    assert "# TYPE specradar_http_latencia_segundos histogram" in corpo


def test_metrics_exige_token_quando_configurado(ambiente):
    ambiente(METRICS_TOKEN="token-de-metricas")
    cliente = TestClient(criar_app_segura())

    assert cliente.get("/metrics").status_code == 404
    autorizado = cliente.get("/metrics", headers={"Authorization": "Bearer token-de-metricas"})
    assert autorizado.status_code == 200


def test_cabecalhos_de_seguranca_da_solucao_continuam_valendo(ambiente):
    resposta = TestClient(criar_app_segura()).get("/api/v1/health")

    assert resposta.headers["X-Content-Type-Options"] == "nosniff"
    assert resposta.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in resposta.headers["Content-Security-Policy"]
    assert resposta.headers["X-Request-ID"]


def test_metrics_publica_a_qualidade_do_ultimo_eval(tmp_path):
    import json

    from seguranca.app_segura import _coletar_eval

    relatorio = tmp_path / "eval.json"
    relatorio.write_text(
        json.dumps(
            {
                "aggregate": {
                    "field_accuracy": {"valor": 0.8083, "acertos": 97.0, "n": 120},
                    "hallucination_rate": {"valor": 0.0, "acertos": 0.0, "n": 16},
                    "time_per_vehicle_s": {"valor": None},
                }
            }
        )
    )

    _coletar_eval(relatorio)

    assert REGISTRO.valor("specradar_eval_metrica", metrica="field_accuracy") == 0.8083
    assert REGISTRO.valor("specradar_eval_metrica", metrica="hallucination_rate") == 0.0
    assert 'metrica="time_per_vehicle_s"' not in REGISTRO.exportar()
