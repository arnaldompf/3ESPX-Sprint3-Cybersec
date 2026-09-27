"""SSRF: destinos internos bloqueados antes da requisição e em cada redirecionamento."""

from __future__ import annotations

import httpx
import pytest

from seguranca.ssrf import DestinoProibido, HttpxSeguro, proteger_pipeline, validar_destino

DNS_FALSO = {
    "fabricante.com.br": ["200.160.2.3"],
    "metadados.evil": ["169.254.169.254"],
    "interno.evil": ["10.0.0.5"],
    "misto.evil": ["200.160.2.3", "127.0.0.1"],
    "v6.evil": ["::1"],
    "mapeado.evil": ["::ffff:127.0.0.1"],
}


def resolver(host: str, _porta: int) -> list[str]:
    return DNS_FALSO.get(host, [host])


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/iam/",
        "http://metadados.evil/",
        "http://interno.evil/admin",
        "http://misto.evil/",  # basta UM endereço interno
        "http://v6.evil/",
        "http://mapeado.evil/",
        "http://127.0.0.1/",
        "file:///etc/passwd",
        "gopher://fabricante.com.br/",
        "http://fabricante.com.br:5432/",
        "https://usuario:senha@fabricante.com.br/",
    ],
)
def test_destinos_proibidos(url):
    with pytest.raises(DestinoProibido):
        validar_destino(url, resolver=resolver)


def test_destino_publico_passa():
    validar_destino("https://fabricante.com.br/ficha-tecnica", resolver=resolver)


def test_redirecionamento_para_rede_interna_e_bloqueado():
    def servidor(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.host == "fabricante.com.br":
            return httpx.Response(302, headers={"Location": "http://metadados.evil/latest/"})
        return httpx.Response(200, text="credenciais da nuvem")

    seguro = HttpxSeguro(resolver=resolver, transporte=httpx.MockTransport(servidor))

    with pytest.raises(DestinoProibido):
        seguro.get("https://fabricante.com.br/carro", follow_redirects=True)


def test_redirecionamento_publico_segue_normalmente():
    def servidor(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path == "/antigo":
            return httpx.Response(301, headers={"Location": "/novo"})
        return httpx.Response(200, text="ficha")

    seguro = HttpxSeguro(resolver=resolver, transporte=httpx.MockTransport(servidor))

    assert seguro.get("https://fabricante.com.br/antigo", follow_redirects=True).text == "ficha"


def test_bloqueio_e_um_httperror_para_o_laco_de_tentativas_da_solucao():
    assert issubclass(DestinoProibido, httpx.HTTPError)


def test_coletor_da_solucao_devolve_erro_em_vez_de_acessar_a_rede_interna(monkeypatch):
    from pipeline.fetch import http as coletor

    monkeypatch.setenv("REPLAY_MODE", "0")
    monkeypatch.setattr(coletor, "httpx", coletor.httpx)  # desfeito no fim do teste
    proteger_pipeline()
    assert isinstance(coletor.httpx, HttpxSeguro)

    resultado = coletor.fetch("http://127.0.0.1:80/admin", usar_cache=False, tentativas=1)

    assert not resultado.ok
    assert "DestinoProibido" in resultado.motivo


def test_todo_bloqueio_por_politica_vira_evento_de_seguranca():
    from structlog.testing import capture_logs

    from seguranca.metricas import REGISTRO

    with capture_logs() as logs:
        for url in ("http://db:5432/", "file:///etc/passwd", "http://metadados.evil/"):
            with pytest.raises(DestinoProibido):
                validar_destino(url, resolver=resolver)

    assert [e["event"] for e in logs] == ["seguranca.ssrf_bloqueado"] * 3
    assert REGISTRO.valor("specradar_eventos_seguranca_total", tipo="ssrf_bloqueado") == 3
