"""WP-31 — o FastAPI serve o build do front-end em `/app`, com fallback de SPA.

O defeito que estes testes existem para impedir é o mais comum de SPA servida por
back-end: recarregar a pagina numa rota interna (`/app/ficha/abc`) da 404, porque aquele
caminho nao e arquivo — e quem sabe o que ele significa e o React Router, no navegador.

E o contra-teste, que importa igual: o fallback **nao** pode cobrir `/api`. Um cliente que
pede `/api/v1/nao-existe` e recebe uma pagina HTML nao consegue nem descobrir que errou o
endereco.

`TestACspDeixaATelaCarregar` foi acrescentada depois de a tela abrir **em branco** no
Chrome do humano com todos os testes acima verdes (D-184). Eles conferiam status e
content-type — que estavam certos — e o `TestClient` nao aplica CSP. O navegador aplicava:
`default-src 'none'` bloqueava o proprio bundle que o teste acima confirma ser servido.
Licao que ficou no repo: status 200 nao e prova de tela; `scripts/verify/web-smoke.sh` e.
"""

from __future__ import annotations

import pytest

from api.app.middleware import CSP_API, CSP_APP, PREFIXO_DO_WEB_APP
from api.app.web import DIST, PREFIXO_WEB

pytestmark = pytest.mark.skipif(
    not (DIST / "index.html").exists(),
    reason="web/dist ausente: rode `cd web && npm ci && npm run build`",
)


class TestServeOFrontEnd:
    def test_a_raiz_do_app_devolve_html(self, cliente):
        resposta = cliente.get(PREFIXO_WEB)
        assert resposta.status_code == 200
        assert resposta.headers["content-type"].startswith("text/html")

    @pytest.mark.parametrize(
        "rota", ["/app/consulta", "/app/radar", "/app/ficha/abc123", "/app/matriz"]
    )
    def test_rota_interna_da_spa_devolve_o_index(self, cliente, rota):
        """Recarregar numa rota interna tem de funcionar."""
        resposta = cliente.get(rota)
        assert resposta.status_code == 200, rota
        assert resposta.headers["content-type"].startswith("text/html"), rota

    def test_o_html_carrega_o_bundle_com_o_caminho_de_app(self, cliente):
        """`base: '/app/'` no Vite: sem isso o navegador pediria `/assets/...` e falharia."""
        corpo = cliente.get(PREFIXO_WEB).text
        assert "/app/assets/" in corpo

    def test_o_asset_e_servido(self, cliente):
        import re

        corpo = cliente.get(PREFIXO_WEB).text
        achados = re.findall(r'/app/(assets/[^"\']+)', corpo)
        assert achados, "o index nao referencia nenhum asset"
        for caminho in achados[:3]:
            resposta = cliente.get(f"{PREFIXO_WEB}/{caminho}")
            assert resposta.status_code == 200, caminho


class TestOFallbackNaoInvadeAApi:
    def test_404_de_api_continua_problem_json(self, cliente):
        """O contra-teste. HTML aqui esconderia do cliente que ele errou o endereco."""
        resposta = cliente.get("/api/v1/nao-existe")
        assert resposta.status_code == 404
        assert resposta.headers["content-type"].startswith("application/problem+json")

    def test_health_continua_json(self, cliente):
        resposta = cliente.get("/api/v1/health")
        assert resposta.status_code == 200
        assert resposta.headers["content-type"].startswith("application/json")

    def test_o_openapi_continua_json(self, cliente):
        assert cliente.get("/openapi.json").status_code == 200


class TestACspDeixaATelaCarregar:
    """A CSP do `/app` tem de permitir exatamente o que o `index.html` pede.

    Sem isto, o servidor entrega os tres arquivos com 200 e o navegador recusa os dois que
    importam. E um defeito que so aparece em navegador de verdade, entao aqui fica a parte
    que da para travar sem um: a politica carimbada na resposta.
    """

    def test_o_app_nao_usa_a_csp_da_api(self, cliente):
        politica = cliente.get(PREFIXO_WEB).headers["Content-Security-Policy"]
        assert politica != CSP_API
        assert politica == CSP_APP

    @pytest.mark.parametrize(
        "diretiva",
        [
            "script-src 'self'",  # o bundle
            "style-src 'self' 'unsafe-inline'",  # a folha + `style={{ width }}`
            "connect-src 'self'",  # o fetch em /api/v1
            "img-src 'self' data:",
            "form-action 'self'",  # o formulario de login
        ],
    )
    def test_a_politica_libera_o_que_a_pagina_precisa(self, cliente, diretiva):
        assert diretiva in cliente.get(PREFIXO_WEB).headers["Content-Security-Policy"]

    def test_a_politica_continua_fechando_o_que_nao_e_da_origem(self, cliente):
        """Liberar nao e abrir: nenhum host de fora, e nada de iframe."""
        politica = cliente.get(PREFIXO_WEB).headers["Content-Security-Policy"]
        assert politica.startswith("default-src 'none'")
        assert "frame-ancestors 'none'" in politica
        assert "http://" not in politica and "https://" not in politica
        assert "'unsafe-eval'" not in politica
        # `unsafe-inline` so vale para estilo. Em script seria buraco de XSS.
        assert "script-src 'self';" in politica + ";"

    @pytest.mark.parametrize("rota", ["/app", "/app/", "/app/consulta", "/app/ficha/abc"])
    def test_toda_rota_da_spa_recebe_a_csp_do_app(self, cliente, rota):
        """O deep link tambem: e exatamente onde o humano bateu."""
        resposta = cliente.get(rota, follow_redirects=False)
        assert resposta.headers["Content-Security-Policy"] == CSP_APP, rota

    def test_o_asset_tambem_recebe_a_csp_do_app(self, cliente):
        resposta = cliente.get(f"{PREFIXO_WEB}/assets/")
        assert resposta.headers["Content-Security-Policy"] == CSP_APP

    def test_a_api_continua_com_a_csp_fechada(self, cliente):
        """O contra-teste: afrouxar o `/app` nao pode afrouxar o resto."""
        assert cliente.get("/api/v1/health").headers["Content-Security-Policy"] == CSP_API

    def test_csp_cobre_o_prefixo_do_web(self):
        """`PREFIXO_DO_WEB_APP` e `PREFIXO_WEB` sao a mesma rota em dois modulos."""
        assert PREFIXO_DO_WEB_APP == PREFIXO_WEB
