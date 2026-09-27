"""Rate limit: a vulnerabilidade da solução original e a correção de `app_segura`."""

from __future__ import annotations

import jwt
from api.app import rate_limit
from api.app.main import create_app
from api.app.security import criar_token
from fastapi.testclient import TestClient
from starlette.requests import Request

from seguranca.app_segura import (
    CHAVE_ORIGINAL_DA_SOLUCAO,
    chave_do_limite_verificada,
    criar_app_segura,
)
from tests.constantes import SEGREDO_DE_TESTE

ROTA = "/api/v1/rota-que-nao-existe"  # passa pelo limitador e não toca o banco


def _token_forjado(sub: str) -> str:
    """Assinado com uma chave que o servidor não conhece: o atacante não precisa dela."""
    return jwt.encode({"sub": sub, "type": "access"}, "chave-do-atacante" * 3, "HS256")


def _rajada(cliente: TestClient, quantidade: int) -> list[int]:
    return [
        cliente.get(
            ROTA, headers={"Authorization": f"Bearer {_token_forjado(f'x-{i}')}"}
        ).status_code
        for i in range(quantidade)
    ]


def test_solucao_original_e_burlada_trocando_o_sub_do_token(ambiente, monkeypatch):
    """Evidência da vulnerabilidade: limite de 3/min, 10 requisições, nenhum 429."""
    ambiente(RATE_LIMIT_ENABLED="1", RATE_LIMIT_DEFAULT="3/minute")
    monkeypatch.setattr(rate_limit, "chave_do_limite", CHAVE_ORIGINAL_DA_SOLUCAO)
    monkeypatch.setattr(rate_limit.limiter, "_key_func", CHAVE_ORIGINAL_DA_SOLUCAO)

    respostas = _rajada(TestClient(create_app()), 10)

    assert 429 not in respostas


def test_app_segura_conta_token_forjado_pelo_ip(ambiente):
    ambiente(RATE_LIMIT_ENABLED="1", RATE_LIMIT_DEFAULT="3/minute", JWT_SECRET=SEGREDO_DE_TESTE)

    respostas = _rajada(TestClient(criar_app_segura()), 10)

    assert respostas[:3] == [404, 404, 404]
    assert set(respostas[3:]) == {429}


def _requisicao(token: str | None) -> Request:
    headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
    return Request({"type": "http", "headers": headers, "client": ("203.0.113.7", 1234)})


def test_chave_e_o_usuario_so_com_token_valido(ambiente):
    ambiente(JWT_SECRET=SEGREDO_DE_TESTE)
    valido, _ = criar_token(sub="usuario-1", role="analista")

    assert chave_do_limite_verificada(_requisicao(valido)) == "user:usuario-1"
    assert chave_do_limite_verificada(_requisicao(_token_forjado("usuario-1"))) == "ip:203.0.113.7"
    assert chave_do_limite_verificada(_requisicao(None)) == "ip:203.0.113.7"


def test_refresh_nao_serve_como_chave_de_usuario(ambiente):
    ambiente(JWT_SECRET=SEGREDO_DE_TESTE)
    refresh, _ = criar_token(sub="usuario-1", role="analista", tipo="refresh")

    assert chave_do_limite_verificada(_requisicao(refresh)) == "ip:203.0.113.7"
