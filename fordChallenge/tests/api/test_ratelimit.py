"""WP-05 — rate limit: 5/min no login por IP, 60/min por usuário autenticado.

O critério de aceite é a 6ª tentativa de login em 1 min devolvendo 429. O resto do
arquivo cobre a decisão que faz o limite ser **útil** em vez de só existir: a chave é o
**usuário** quando há token e o **IP** quando não há.

Por que isso importa numa concessionária: todo mundo sai pelo mesmo IP. Com o IP como
chave única, um vendedor consultando fichas esgotaria a cota dos colegas — e o suporte
receberia "o sistema caiu" sem ninguém ter feito nada de errado. Com o usuário como
chave, cada um tem a sua.
"""

from __future__ import annotations

import pytest

from api.app.models import Role
from api.app.rate_limit import chave_do_limite, limiter
from api.app.security import criar_token
from tests.api.conftest import SENHA_DE_TESTE

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


class TestCriteriosDeAceite:
    def test_sexta_tentativa_de_login_em_um_minuto_da_429(self, cliente_auth, criar_usuario):
        """Critério: 6 tentativas de login em 1 min → a 6ª é 429."""
        criar_usuario("analista@suno.example.com", Role.ANALISTA)
        corpo = {"email": "analista@suno.example.com", "senha": "errada-mas-longa"}

        for tentativa in range(5):
            assert cliente_auth.post(LOGIN, json=corpo).status_code == 401, tentativa

        sexta = cliente_auth.post(LOGIN, json=corpo)
        assert sexta.status_code == 429
        assert sexta.headers["content-type"].startswith("application/problem+json")
        assert sexta.json()["title"] == "Limite de requisições excedido"

    def test_o_limite_conta_tambem_os_logins_que_deram_certo(self, cliente_auth, criar_usuario):
        """Senão a força bruta bastaria intercalar um acerto para zerar o contador."""
        criar_usuario("analista@suno.example.com", Role.ANALISTA)
        bom = {"email": "analista@suno.example.com", "senha": SENHA_DE_TESTE}

        for _ in range(5):
            assert cliente_auth.post(LOGIN, json=bom).status_code == 200
        assert cliente_auth.post(LOGIN, json=bom).status_code == 429


class TestChaveDoLimite:
    """A chave é o que separa "limite por pessoa" de "limite por concessionária"."""

    def _requisicao(self, headers: dict[str, str] | None = None):
        from starlette.requests import Request

        escopo = {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "client": ("203.0.113.7", 12345),
            "method": "GET",
            "path": "/api/v1/health",
        }
        return Request(escopo)

    def test_sem_token_a_chave_e_o_ip(self):
        assert chave_do_limite(self._requisicao()) == "ip:203.0.113.7"

    def test_com_token_a_chave_e_o_usuario(self, ambiente_auth):
        token, _ = criar_token(sub="u-123", role="analista")
        chave = chave_do_limite(self._requisicao({"Authorization": f"Bearer {token}"}))
        assert chave == "user:u-123"

    def test_dois_usuarios_do_mesmo_ip_tem_cotas_separadas(self, ambiente_auth):
        # É o caso real: a concessionária inteira sai por um IP.
        a, _ = criar_token(sub="vendedor-a", role="vendedor")
        b, _ = criar_token(sub="vendedor-b", role="vendedor")
        chave_a = chave_do_limite(self._requisicao({"Authorization": f"Bearer {a}"}))
        chave_b = chave_do_limite(self._requisicao({"Authorization": f"Bearer {b}"}))
        assert chave_a != chave_b

    def test_token_ilegivel_cai_no_ip_em_vez_de_explodir(self):
        chave = chave_do_limite(self._requisicao({"Authorization": "Bearer lixo.nao.jwt"}))
        assert chave == "ip:203.0.113.7"

    def test_a_chave_nao_verifica_assinatura(self, ambiente_auth, monkeypatch):
        """De propósito: aqui é contador, não decisão de acesso.

        Verificar assinatura no limitador poria criptografia no caminho de **toda**
        requisição, inclusive das barradas. Um token forjado só consegue competir por uma
        cota alheia; a autorização de verdade acontece depois, em `deps.py`.
        """
        import jwt

        # Chave longa de proposito: o assunto do teste e a assinatura NAO conferida, e uma
        # chave curta so somaria um aviso de HMAC no relatorio.
        forjado = jwt.encode(
            {"sub": "u-999", "role": "admin"}, "outro-segredo-qualquer-com-mais-de-32-bytes"
        )
        chave = chave_do_limite(self._requisicao({"Authorization": f"Bearer {forjado}"}))
        assert chave == "user:u-999"


class TestLimiteGeral:
    def test_o_limite_geral_vem_do_ambiente(self, ambiente_auth, monkeypatch):
        from api.app.config import get_settings

        monkeypatch.setenv("RATE_LIMIT_DEFAULT", "7/minute")
        get_settings.cache_clear()
        assert get_settings().rate_limit_default == "7/minute"

    def test_rota_autenticada_respeita_o_limite_geral(
        self, monkeypatch, criar_usuario, logar, cliente_auth
    ):
        """Com um limite baixo, a rota autenticada devolve 429 — e é por usuário."""
        from api.app.config import get_settings

        criar_usuario("analista@suno.example.com", Role.ANALISTA)
        headers = logar("analista@suno.example.com")

        monkeypatch.setenv("RATE_LIMIT_DEFAULT", "3/minute")
        get_settings.cache_clear()
        limiter.reset()

        codigos = [cliente_auth.get(ME, headers=headers).status_code for _ in range(5)]
        assert 429 in codigos, codigos
        assert codigos.count(200) == 3, codigos


class TestOArquivoDaTelaNaoGastaACotaDaApi:
    """D-187 — o limite de docs/04 e da API; o estatico do web app sai da conta.

    Defeito medido pelo `web-smoke`: cada carregamento de tela pede dois arquivos
    (`index-*.js` e `index-*.css`) alem das chamadas de dado, e eles passavam pela mesma
    conta. Trocando de aba algumas vezes, a folha de estilo comecava a voltar
    **429 `application/problem+json`**; o navegador recusava aplica-la ("not a supported
    stylesheet MIME type") e a tela ficava em branco. O limite que existe para proteger
    a API derrubava a tela.
    """

    def test_o_estatico_nao_toma_429_com_limite_baixo(self, cliente_auth, monkeypatch):
        from api.app.config import get_settings

        monkeypatch.setenv("RATE_LIMIT_DEFAULT", "2/minute")
        get_settings.cache_clear()
        limiter.reset()

        codigos = [cliente_auth.get("/app/", follow_redirects=False).status_code for _ in range(6)]
        assert 429 not in codigos, codigos

    def test_a_api_continua_contando(self, cliente_auth, monkeypatch, criar_usuario, logar):
        """O contra-teste. Isentar o `/app` nao pode isentar `/api`."""
        from api.app.config import get_settings

        criar_usuario("analista@suno.example.com", Role.ANALISTA)
        headers = logar("analista@suno.example.com")
        monkeypatch.setenv("RATE_LIMIT_DEFAULT", "3/minute")
        get_settings.cache_clear()
        limiter.reset()

        codigos = [cliente_auth.get(ME, headers=headers).status_code for _ in range(5)]
        assert 429 in codigos, codigos


class TestIsolamentoEntreTestes:
    """O contador é singleton de módulo; sem `reset` ele atravessaria os testes.

    Foi defeito real: o 6º login de um teste caía como 429 no seguinte, com a falha
    aparecendo a arquivos de distância da causa. `ambiente_auth` zera o limitador, e
    estes dois testes garantem que a garantia é estrutural.
    """

    @pytest.mark.parametrize("rodada", [1, 2])
    def test_cada_teste_comeca_com_a_cota_cheia(self, cliente_auth, criar_usuario, rodada):
        criar_usuario("analista@suno.example.com", Role.ANALISTA)
        corpo = {"email": "analista@suno.example.com", "senha": "errada-mas-longa"}
        for _ in range(5):
            assert cliente_auth.post(LOGIN, json=corpo).status_code == 401
