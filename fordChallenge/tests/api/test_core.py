"""Critérios de aceite da WP-04: núcleo da API, erros padronizados, health e OpenAPI.

Os três critérios da spec estão nos testes `test_health_*`, `test_rota_inexistente_*` e
`test_excecao_nao_tratada_*`. O resto cobre o que as regras invioláveis exigem e que um
critério em BDD não expressa: o 422 do Pydantic não pode voltar como eco do corpo, a URL
do banco não pode sair em `/health` (endpoint público), e o CORS não pode virar `*`.

Dois detalhes de mecânica, porque não são óbvios:

* o 500 só é observável com `raise_server_exceptions=False` (ver `conftest.py`);
* `structlog.testing.capture_logs` desliga os processadores configurados, inclusive o
  `merge_contextvars`. Por isso o código loga `request_id` como argumento explícito e
  não confia no contexto — o teste do log seria verde por acidente do outro jeito.
"""

from __future__ import annotations

import json
import secrets

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from structlog.testing import capture_logs

from api.app.config import get_settings, versao_do_pacote
from api.app.errors import TIPO_CONTEUDO, registrar_handlers
from api.app.middleware import registrar_middlewares


class ConsultaFalsa(BaseModel):
    """Corpo com validação, só para provocar o 422.

    No nível do módulo de propósito: com `from __future__ import annotations`, o FastAPI
    resolve a anotação do parâmetro pelos globais do módulo e um modelo declarado dentro
    da função não seria encontrado.
    """

    marca: str = Field(max_length=60)
    ano_modelo: int


# --------------------------------------------------------------------------------------
# Critério 1 — GET /api/v1/health
# --------------------------------------------------------------------------------------
def test_health_responde_200_com_db_e_version(cliente: TestClient) -> None:
    resposta = cliente.get("/api/v1/health")
    assert resposta.status_code == 200

    corpo = resposta.json()
    assert corpo["status"] == "ok"
    assert corpo["version"] == versao_do_pacote()
    assert corpo["version"]
    assert corpo["db"]["ok"] is True
    assert corpo["db"]["dialeto"] == "sqlite"
    assert corpo["db"]["nome"].endswith(".db")
    # Etiqueta obrigatória em toda informação que chega ao cliente (CLAUDE.md): o health
    # é observação direta, não inferência.
    assert corpo["etiqueta"] == "FATO"


def test_health_nunca_expoe_a_url_do_banco(cliente: TestClient, monkeypatch) -> None:
    """`/health` é público (docs/04); uma DSN de Postgres carrega credencial no texto."""
    senha = secrets.token_urlsafe(16)
    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgresql+psycopg://analista:{senha}@banco.interno:5432/specradar",
    )

    resposta = cliente.get("/api/v1/health")
    assert resposta.status_code == 200

    corpo = resposta.json()
    assert corpo["db"] == {
        "ok": False,
        "dialeto": "postgresql",
        "nome": "specradar",
        "erro": corpo["db"]["erro"],
    }
    assert corpo["status"] == "degradado"
    for vazamento in (senha, "analista", "banco.interno", "5432"):
        assert vazamento not in resposta.text


# --------------------------------------------------------------------------------------
# Critério 2 — rota inexistente
# --------------------------------------------------------------------------------------
def test_rota_inexistente_devolve_problem_json_com_instance_igual_ao_request_id(
    cliente: TestClient,
) -> None:
    resposta = cliente.get("/api/v1/nao-existe")
    assert resposta.status_code == 404
    assert resposta.headers["content-type"].startswith(TIPO_CONTEUDO)

    corpo = resposta.json()
    assert set(corpo) >= {"type", "title", "status", "detail", "instance"}
    assert corpo["status"] == 404
    assert corpo["instance"] == resposta.headers["X-Request-ID"]


# --------------------------------------------------------------------------------------
# Critério 3 — exceção não tratada
# --------------------------------------------------------------------------------------
def test_excecao_nao_tratada_devolve_500_sem_stack_trace_e_loga_request_id(
    ambiente_api: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.app.main import create_app

    monkeypatch.setenv("SPECRADAR_DEBUG_BOOM", "1")
    get_settings.cache_clear()
    app = create_app()

    with TestClient(app, raise_server_exceptions=False) as cliente, capture_logs() as registros:
        resposta = cliente.get("/api/v1/_debug/boom")

    assert resposta.status_code == 500
    assert resposta.headers["content-type"].startswith(TIPO_CONTEUDO)

    corpo = resposta.json()
    assert corpo["status"] == 500
    assert corpo["instance"] == resposta.headers["X-Request-ID"]
    for marca_de_traceback in ("Traceback", "RuntimeError", "main.py", "line ", "raise "):
        assert marca_de_traceback not in resposta.text

    erros = [r for r in registros if r["event"] == "http.erro_nao_tratado"]
    assert len(erros) == 1, "o 500 tem de gerar exatamente um evento de erro no log"
    assert erros[0]["request_id"] == corpo["instance"]
    assert erros[0]["excecao"] == "RuntimeError"
    assert "Traceback" in erros[0]["traceback"], "o traceback tem de ficar só no log"


def test_rota_de_excecao_nao_existe_sem_a_variavel(cliente: TestClient) -> None:
    """A rota que estoura nunca pode estar de pé por default."""
    assert cliente.get("/api/v1/_debug/boom").status_code == 404


# --------------------------------------------------------------------------------------
# 422 do Pydantic no mesmo formato, sem eco do corpo
# --------------------------------------------------------------------------------------
def test_422_do_pydantic_vira_problem_json_sem_ecoar_valores() -> None:
    """App descartável: a WP-04 não tem rota de domínio para validar corpo."""
    app = FastAPI()
    registrar_handlers(app)
    registrar_middlewares(app)

    @app.post("/consulta")
    def _consulta(dados: ConsultaFalsa) -> dict[str, str]:
        return {"marca": dados.marca}

    valor_longo = "x" * 80
    valor_invalido = f"nao-e-numero-{secrets.token_hex(4)}"
    with TestClient(app, raise_server_exceptions=False) as cliente:
        resposta = cliente.post(
            "/consulta", json={"marca": valor_longo, "ano_modelo": valor_invalido}
        )

    assert resposta.status_code == 422
    assert resposta.headers["content-type"].startswith(TIPO_CONTEUDO)

    corpo = resposta.json()
    assert corpo["status"] == 422
    assert corpo["instance"] == resposta.headers["X-Request-ID"]
    assert {campo["campo"] for campo in corpo["errors"]} == {"body.marca", "body.ano_modelo"}
    assert all({"campo", "regra", "mensagem"} == set(campo) for campo in corpo["errors"])
    assert valor_longo not in resposta.text
    assert valor_invalido not in resposta.text


def test_corpo_mal_formado_nao_volta_dentro_do_erro() -> None:
    """JSON quebrado chega inteiro em `input`; ele não pode aparecer na resposta."""
    app = FastAPI()
    registrar_handlers(app)
    registrar_middlewares(app)

    @app.post("/consulta")
    def _consulta(dados: ConsultaFalsa) -> dict[str, str]:
        return {"marca": dados.marca}

    lixo = f"{{marca: {secrets.token_hex(8)}"
    with TestClient(app, raise_server_exceptions=False) as cliente:
        resposta = cliente.post(
            "/consulta", content=lixo, headers={"Content-Type": "application/json"}
        )

    assert resposta.status_code == 422
    assert lixo not in resposta.text


# --------------------------------------------------------------------------------------
# Request-id, tempo de resposta e headers de segurança
# --------------------------------------------------------------------------------------
def test_request_id_do_cliente_e_respeitado(cliente: TestClient) -> None:
    """Um id só atravessando web app, API e worker é o que torna o log correlacionável."""
    enviado = "trace-2026.09.08_abc:123"
    resposta = cliente.get("/api/v1/health", headers={"X-Request-ID": enviado})
    assert resposta.headers["X-Request-ID"] == enviado


def test_request_id_malformado_do_cliente_e_descartado(cliente: TestClient) -> None:
    """Header é entrada de usuário: id fora do formato é substituído, não repassado."""
    # Só ASCII: o próprio httpx recusa acento em header, então o vetor realista é
    # espaco/virgula/ponto-e-virgula, que passa pelo cliente e sujaria o log.
    injecao = "id com espaco, virgula; e ponto-e-virgula"
    resposta = cliente.get("/api/v1/health", headers={"X-Request-ID": injecao})
    gerado = resposta.headers["X-Request-ID"]
    assert gerado != injecao
    assert gerado.isalnum()


def test_headers_de_seguranca_e_tempo_de_resposta(cliente: TestClient) -> None:
    resposta = cliente.get("/api/v1/health")
    assert resposta.headers["X-Content-Type-Options"] == "nosniff"
    assert resposta.headers["X-Frame-Options"] == "DENY"
    assert resposta.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in resposta.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in resposta.headers["Content-Security-Policy"]
    # HSTS em dev fixaria o navegador em HTTPS para localhost e quebraria o web app.
    assert "Strict-Transport-Security" not in resposta.headers
    assert float(resposta.headers["X-Response-Time-ms"]) >= 0


def test_headers_de_seguranca_tambem_no_erro(cliente: TestClient) -> None:
    """O 500 não passa de volta pelo middleware; o handler tem de carimbar os headers."""
    resposta = cliente.get("/api/v1/nao-existe")
    assert resposta.headers["X-Content-Type-Options"] == "nosniff"
    assert resposta.headers["Referrer-Policy"] == "no-referrer"


# --------------------------------------------------------------------------------------
# Log estruturado
# --------------------------------------------------------------------------------------
def test_log_da_requisicao_em_json_com_o_essencial_e_nada_de_mais(cliente: TestClient) -> None:
    valor_na_query = secrets.token_hex(6)
    with capture_logs() as registros:
        resposta = cliente.get(f"/api/v1/health?segredo={valor_na_query}")

    evento = next(r for r in registros if r["event"] == "http.request")
    assert evento["request_id"] == resposta.headers["X-Request-ID"]
    assert evento["metodo"] == "GET"
    assert evento["rota"] == "/api/v1/health"
    assert evento["status"] == 200
    assert evento["duracao_ms"] >= 0
    # Log fica 90 dias (docs/08): query string não entra, nem IP.
    assert valor_na_query not in json.dumps(evento)
    assert "client" not in evento

    # Fora do `capture_logs`, a saída configurada é JSON (docs/08).
    renderizador = structlog.get_config()["processors"][-1]
    assert isinstance(renderizador, structlog.processors.JSONRenderer)


# --------------------------------------------------------------------------------------
# OpenAPI e CORS
# --------------------------------------------------------------------------------------
def test_openapi_serializa_em_json_e_documenta_os_erros(app: FastAPI) -> None:
    esquema = app.openapi()
    json.dumps(esquema)  # o comando de verificação da spec, literalmente

    assert esquema["info"]["title"] == "SpecRadar API"
    assert esquema["info"]["version"] == versao_do_pacote()
    assert esquema["info"]["description"].strip()
    assert "saude" in {tag["name"] for tag in esquema["tags"]}
    assert "/api/v1/_debug/boom" not in esquema["paths"]

    operacao = esquema["paths"]["/api/v1/health"]["get"]
    assert operacao["tags"] == ["saude"]
    exemplo_404 = operacao["responses"]["404"]["content"][TIPO_CONTEUDO]["example"]
    assert exemplo_404["status"] == 404
    assert exemplo_404["instance"]
    exemplo_422 = operacao["responses"]["422"]["content"][TIPO_CONTEUDO]["example"]
    assert exemplo_422["errors"][0]["campo"]
    assert "Problema" in esquema["components"]["schemas"]


def test_docs_e_openapi_sao_publicos(cliente: TestClient) -> None:
    assert cliente.get("/docs").status_code == 200
    assert cliente.get("/openapi.json").status_code == 200


def test_cors_restrito_as_origens_configuradas(cliente: TestClient, origem_permitida: str) -> None:
    permitida = cliente.get("/api/v1/health", headers={"Origin": origem_permitida})
    assert permitida.headers["access-control-allow-origin"] == origem_permitida

    intrusa = cliente.get("/api/v1/health", headers={"Origin": "https://intrusa.example"})
    assert "access-control-allow-origin" not in intrusa.headers


def test_cors_nunca_libera_asterisco(monkeypatch: pytest.MonkeyPatch) -> None:
    """`*` configurado por engano é descartado, não repassado (docs/04 e docs/08)."""
    monkeypatch.setenv("CORS_ORIGINS", "*, http://localhost:5173 ,")
    get_settings.cache_clear()
    try:
        assert get_settings().origens_cors == ("http://localhost:5173",)
    finally:
        get_settings.cache_clear()
