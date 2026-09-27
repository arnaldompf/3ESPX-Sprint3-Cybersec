"""WP-05 — login, refresh com rotação, expiração e `/auth/me`.

Os critérios de aceite da spec estão em `TestCriteriosDeAceite`. O resto do arquivo cobre
o que a spec pede no escopo e o que a segurança exige mesmo sem estar escrito: que a
resposta de falha **não** diga se o e-mail existe, que um refresh não sirva de access, e
que reuso de refresh rotacionado derrube a família.
"""

from __future__ import annotations

import datetime as dt

import pytest

from api.app.security import criar_token
from tests.api.conftest import SENHA_DE_TESTE

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
ME = "/api/v1/auth/me"
LOGOUT = "/api/v1/auth/logout"


class TestCriteriosDeAceite:
    def test_token_com_exp_passado_da_401_com_titulo_token_expirado(
        self, cliente_auth, criar_usuario
    ):
        """Critério: `exp` no passado → 401 com `title="Token expirado"`."""
        usuario = criar_usuario("analista@suno.example.com", "analista")
        # TTL negativo em vez de congelar o relógio: um teste que mexe no tempo global
        # contamina o que roda depois dele.
        expirado, _ = criar_token(sub=usuario.id, role=usuario.role, ttl=dt.timedelta(minutes=-1))

        resposta = cliente_auth.get(ME, headers={"Authorization": f"Bearer {expirado}"})

        assert resposta.status_code == 401
        assert resposta.json()["title"] == "Token expirado"
        assert resposta.headers["content-type"].startswith("application/problem+json")

    def test_refresh_rotacionado_invalida_o_anterior(self, cliente_auth, criar_usuario):
        """Critério do escopo: o refresh anterior deixa de valer após a rotação."""
        criar_usuario("analista@suno.example.com", "analista")
        primeiro = cliente_auth.post(
            LOGIN, json={"email": "analista@suno.example.com", "senha": SENHA_DE_TESTE}
        ).json()["refresh_token"]

        rotacionado = cliente_auth.post(REFRESH, json={"refresh_token": primeiro})
        assert rotacionado.status_code == 200
        assert rotacionado.json()["refresh_token"] != primeiro

        reuso = cliente_auth.post(REFRESH, json={"refresh_token": primeiro})
        assert reuso.status_code == 401


class TestLogin:
    def test_credencial_correta_devolve_o_par_de_tokens(self, cliente_auth, criar_usuario):
        criar_usuario("analista@suno.example.com", "analista")
        resposta = cliente_auth.post(
            LOGIN, json={"email": "analista@suno.example.com", "senha": SENHA_DE_TESTE}
        )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["access_token"] and corpo["refresh_token"]
        assert corpo["token_type"] == "bearer"
        assert corpo["expires_in"] > 0

    def test_senha_errada_da_401(self, cliente_auth, criar_usuario):
        criar_usuario("analista@suno.example.com", "analista")
        resposta = cliente_auth.post(
            LOGIN, json={"email": "analista@suno.example.com", "senha": "errada-mas-longa"}
        )
        assert resposta.status_code == 401

    def test_a_resposta_nao_revela_se_o_email_existe(self, cliente_auth, criar_usuario):
        """Enumeração de contas: as duas falhas têm de ser indistinguíveis.

        Sem isto, um atacante lista quem trabalha na empresa sem acertar uma senha.
        """
        criar_usuario("analista@suno.example.com", "analista")
        existe = cliente_auth.post(
            LOGIN, json={"email": "analista@suno.example.com", "senha": "errada-mas-longa"}
        )
        nao_existe = cliente_auth.post(
            LOGIN, json={"email": "ninguem@suno.example.com", "senha": "errada-mas-longa"}
        )
        assert existe.status_code == nao_existe.status_code == 401
        assert existe.json()["detail"] == nao_existe.json()["detail"]
        assert existe.json()["title"] == nao_existe.json()["title"]

    def test_usuario_inativo_nao_entra(self, cliente_auth, criar_usuario):
        criar_usuario("saiu@suno.example.com", "analista", ativo=False)
        resposta = cliente_auth.post(
            LOGIN, json={"email": "saiu@suno.example.com", "senha": SENHA_DE_TESTE}
        )
        assert resposta.status_code == 401

    def test_a_falha_de_login_fica_no_audit_log(self, cliente_auth, criar_usuario):
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import AuditLog

        criar_usuario("analista@suno.example.com", "analista")
        cliente_auth.post(
            LOGIN, json={"email": "analista@suno.example.com", "senha": "errada-mas-longa"}
        )
        # Os campos sao lidos DENTRO da sessao: fora dela o objeto esta desanexado e
        # qualquer atributo ainda nao carregado levanta `DetachedInstanceError`.
        with session_scope() as sessao:
            linhas = sessao.exec(select(AuditLog).where(AuditLog.acao == "login_falhou")).all()
            registros = [(linha.ator_email, dict(linha.detalhe or {})) for linha in linhas]
        assert len(registros) == 1
        email, detalhe = registros[0]
        # O motivo real fica na trilha (o time precisa dele); na resposta, nao.
        assert detalhe["motivo"] == "senha_incorreta"
        assert email == "analista@suno.example.com"

    def test_o_audit_log_nao_guarda_senha_nem_hash(self, cliente_auth, criar_usuario):
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import AuditLog

        criar_usuario("analista@suno.example.com", "analista")
        cliente_auth.post(
            LOGIN, json={"email": "analista@suno.example.com", "senha": SENHA_DE_TESTE}
        )
        with session_scope() as sessao:
            linhas = sessao.exec(select(AuditLog)).all()
            serializado = " ".join(str(linha.detalhe) for linha in linhas)
        assert SENHA_DE_TESTE not in serializado
        assert "argon2" not in serializado

    def test_corpo_com_campo_desconhecido_e_422(self, cliente_auth, criar_usuario):
        criar_usuario("analista@suno.example.com", "analista")
        resposta = cliente_auth.post(
            LOGIN,
            json={"email": "analista@suno.example.com", "senha": SENHA_DE_TESTE, "admin": True},
        )
        assert resposta.status_code == 422


class TestMe:
    def test_devolve_quem_esta_autenticado(self, cliente_auth, criar_usuario, logar):
        criar_usuario("gestor@suno.example.com", "gestor")
        resposta = cliente_auth.get(ME, headers=logar("gestor@suno.example.com"))
        assert resposta.status_code == 200
        assert resposta.json()["email"] == "gestor@suno.example.com"
        assert resposta.json()["role"] == "gestor"

    def test_sem_header_da_401_com_www_authenticate(self, cliente_auth):
        resposta = cliente_auth.get(ME)
        assert resposta.status_code == 401
        assert resposta.headers.get("WWW-Authenticate") == "Bearer"

    def test_assinatura_invalida_da_401(self, cliente_auth, criar_usuario):
        criar_usuario("analista@suno.example.com", "analista")
        resposta = cliente_auth.get(ME, headers={"Authorization": "Bearer nao.e.um.token"})
        assert resposta.status_code == 401

    def test_refresh_nao_serve_como_access(self, cliente_auth, criar_usuario):
        """Sem a checagem de tipo, o refresh (7 dias) valeria como access (30 min).

        O TTL curto do access é a razão de ele existir; aceitar refresh no header
        anularia isso sem que nada parecesse errado.
        """
        criar_usuario("analista@suno.example.com", "analista")
        refresh = cliente_auth.post(
            LOGIN, json={"email": "analista@suno.example.com", "senha": SENHA_DE_TESTE}
        ).json()["refresh_token"]

        resposta = cliente_auth.get(ME, headers={"Authorization": f"Bearer {refresh}"})
        assert resposta.status_code == 401
        assert resposta.json()["title"] == "Tipo de token inválido"

    def test_usuario_desativado_depois_do_login_perde_o_acesso(
        self, cliente_auth, criar_usuario, logar
    ):
        # `usuario_atual` relê o banco a cada requisição de propósito: sem isso, um
        # desligado seguiria com acesso até o access expirar.
        usuario = criar_usuario("analista@suno.example.com", "analista")
        headers = logar("analista@suno.example.com")

        from api.app.db import session_scope
        from api.app.models import User

        with session_scope() as sessao:
            linha = sessao.get(User, usuario.id)
            linha.ativo = False
            sessao.add(linha)
            sessao.commit()

        assert cliente_auth.get(ME, headers=headers).status_code == 401


class TestRefresh:
    def test_refresh_valido_devolve_par_novo(self, cliente_auth, criar_usuario):
        criar_usuario("analista@suno.example.com", "analista")
        tokens = cliente_auth.post(
            LOGIN, json={"email": "analista@suno.example.com", "senha": SENHA_DE_TESTE}
        ).json()
        novo = cliente_auth.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
        assert novo.status_code == 200
        assert novo.json()["access_token"] != tokens["access_token"]

    def test_reuso_revoga_a_familia_inteira(self, cliente_auth, criar_usuario):
        """Reuso é o sinal clássico de token roubado — derruba todas as sessões.

        Revogar só o token apresentado deixaria o ladrão com a cadeia nova em mão.
        """
        criar_usuario("analista@suno.example.com", "analista")
        primeiro = cliente_auth.post(
            LOGIN, json={"email": "analista@suno.example.com", "senha": SENHA_DE_TESTE}
        ).json()["refresh_token"]
        segundo = cliente_auth.post(REFRESH, json={"refresh_token": primeiro}).json()[
            "refresh_token"
        ]

        reuso = cliente_auth.post(REFRESH, json={"refresh_token": primeiro})
        assert reuso.status_code == 401
        assert reuso.json()["title"] == "Refresh reutilizado"
        # O que o ladrão obteve na rotação também morre.
        assert cliente_auth.post(REFRESH, json={"refresh_token": segundo}).status_code == 401

    def test_refresh_desconhecido_da_401(self, cliente_auth, criar_usuario):
        usuario = criar_usuario("analista@suno.example.com", "analista")
        forjado, _ = criar_token(sub=usuario.id, role=usuario.role, tipo="refresh")
        # Assinatura válida, mas o `jti` nunca foi emitido por este servidor.
        resposta = cliente_auth.post(REFRESH, json={"refresh_token": forjado})
        assert resposta.status_code == 401

    def test_access_nao_serve_como_refresh(self, cliente_auth, criar_usuario):
        criar_usuario("analista@suno.example.com", "analista")
        access = cliente_auth.post(
            LOGIN, json={"email": "analista@suno.example.com", "senha": SENHA_DE_TESTE}
        ).json()["access_token"]
        assert cliente_auth.post(REFRESH, json={"refresh_token": access}).status_code == 401


class TestLogout:
    def test_logout_encerra_todas_as_sessoes(self, cliente_auth, criar_usuario, logar):
        criar_usuario("analista@suno.example.com", "analista")
        primeira = cliente_auth.post(
            LOGIN, json={"email": "analista@suno.example.com", "senha": SENHA_DE_TESTE}
        ).json()
        headers = logar("analista@suno.example.com")

        assert cliente_auth.post(LOGOUT, headers=headers).status_code == 204
        # A sessão aberta antes do logout também cai: "sair" derruba tudo.
        reuso = cliente_auth.post(REFRESH, json={"refresh_token": primeira["refresh_token"]})
        assert reuso.status_code == 401

    def test_logout_sem_credencial_da_401(self, cliente_auth):
        assert cliente_auth.post(LOGOUT).status_code == 401


class TestSegredo:
    @pytest.mark.parametrize("valor", ["", "curto", "a" * 31])
    def test_segredo_curto_e_recusado(self, ambiente_auth, monkeypatch, valor):
        """HS256 com segredo curto é força bruta viável. Recusa explícita, não silêncio."""
        from api.app.config import get_settings
        from api.app.security import SegredoInvalido, segredo

        monkeypatch.setenv("JWT_SECRET", valor)
        get_settings.cache_clear()
        with pytest.raises(SegredoInvalido):
            segredo()
