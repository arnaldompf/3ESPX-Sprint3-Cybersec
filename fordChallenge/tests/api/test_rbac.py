"""WP-05 — RBAC pela **matriz** de `docs/12` §6.6, não por hierarquia.

O ponto que este arquivo existe para provar: a matriz **não é linear**, então nenhuma
ordem de papéis a expressa.

    | Ação                      | vendedor | analista | gestor | admin |
    | Criar sessão de showroom   |    ✓     |    —     |   ✓    |   ✓   |
    | Criar extrações            |    —     |    ✓     |   ✓    |   ✓   |

Com `vendedor < analista < gestor < admin`, qualquer regra que libere o vendedor libera o
analista — e o analista passaria a poder registrar venda. `TestAMatrizNaoEHierarquia`
trava exatamente esse cruzamento, que é o que quebraria se alguém "simplificasse" a
autorização de volta para níveis.
"""

from __future__ import annotations

import pytest

from api.app.models import Role
from api.app.permissions import MATRIZ, Acao, Escopo, escopo_de, papeis_com, pode

USERS = "/api/v1/users"


class TestCriteriosDeAceite:
    def test_analista_em_rota_de_admin_da_403_problem_json(
        self, cliente_auth, criar_usuario, logar
    ):
        """Critério: analista chamando rota de admin → 403 problem+json."""
        criar_usuario("analista@suno.example.com", Role.ANALISTA)
        resposta = cliente_auth.get(USERS, headers=logar("analista@suno.example.com"))

        assert resposta.status_code == 403
        assert resposta.headers["content-type"].startswith("application/problem+json")
        corpo = resposta.json()
        assert corpo["title"] == "Papel insuficiente"
        assert corpo["status"] == 403
        # O 403 diz **quem** alcança: a matriz é contrato público de docs/12, e "acesso
        # negado" sem mais nada custa uma ida ao suporte.
        assert "admin" in corpo["detail"]


class TestAMatrizNaoEHierarquia:
    def test_vendedor_pode_showroom_e_analista_nao(self):
        """O cruzamento que derruba qualquer hierarquia linear.

        Se alguém trocar a matriz por níveis, é este teste que acusa.
        """
        assert pode(Role.VENDEDOR, Acao.CRIAR_SESSAO_SHOWROOM)
        assert not pode(Role.ANALISTA, Acao.CRIAR_SESSAO_SHOWROOM)

    def test_analista_pode_extrair_e_vendedor_nao(self):
        assert pode(Role.ANALISTA, Acao.CRIAR_EXTRACOES)
        assert not pode(Role.VENDEDOR, Acao.CRIAR_EXTRACOES)

    def test_nao_existe_ordem_de_papeis_que_explique_as_duas(self):
        """Prova por exaustão: nenhuma das 24 ordens possíveis satisfaz a matriz.

        Uma hierarquia linear autoriza uma ação para todos os papéis a partir de um
        limiar. Se existisse ordem que explicasse a matriz, haveria um limiar por ação
        compatível com ela — e não há.
        """
        import itertools

        papeis = list(Role)
        acoes = [Acao.CRIAR_SESSAO_SHOWROOM, Acao.CRIAR_EXTRACOES]

        def linear(ordem) -> bool:
            for acao in acoes:
                permitidos = {p for p in papeis if pode(p, acao)}
                indices = sorted(ordem.index(p) for p in permitidos)
                # Um limiar produz um sufixo contíguo da ordem.
                if indices != list(range(indices[0], len(ordem))):
                    return False
            return True

        assert not any(linear(list(o)) for o in itertools.permutations(papeis))


class TestEscopo:
    def test_vendedor_ve_apenas_os_proprios_insights(self):
        """`PROPRIOS` não é um booleano: tratá-lo como "pode ver" vazaria sessão alheia."""
        assert escopo_de(Role.VENDEDOR, Acao.VER_INSIGHTS) is Escopo.PROPRIOS
        assert escopo_de(Role.GESTOR, Acao.VER_INSIGHTS) is Escopo.TODOS

    def test_pode_devolve_true_para_escopo_proprios(self):
        # Documenta a pegadinha: quem lista tem de olhar o escopo, não só `pode`.
        assert pode(Role.VENDEDOR, Acao.VER_INSIGHTS)


class TestNegarPorOmissao:
    def test_papel_desconhecido_nao_alcanca_nada(self):
        """Papel novo no banco (migração pela metade, alteração à mão) não ganha acesso."""
        for acao in Acao:
            assert escopo_de("diretor-de-marketing", acao) is Escopo.NENHUM

    def test_acao_fora_da_matriz_e_negada(self):
        assert escopo_de(Role.ADMIN, "acao_que_nao_existe") is Escopo.NENHUM  # type: ignore[arg-type]

    @pytest.mark.parametrize("acao", list(Acao))
    def test_toda_acao_tem_ao_menos_um_papel(self, acao):
        """Ação sem ninguém é código morto — ou pior, um recurso inalcançável."""
        assert papeis_com(acao), acao

    def test_o_admin_alcanca_tudo(self):
        """Não por hierarquia: por a matriz de `docs/12` marcar ✓ em toda linha."""
        for acao in Acao:
            assert pode(Role.ADMIN, acao), acao

    def test_a_matriz_cobre_todas_as_acoes_declaradas(self):
        assert set(MATRIZ) == set(Acao)


class TestRotaDeAdmin:
    @pytest.mark.parametrize("papel", [Role.VENDEDOR, Role.ANALISTA, Role.GESTOR])
    def test_ninguem_abaixo_de_admin_lista_usuarios(
        self, cliente_auth, criar_usuario, logar, papel
    ):
        email = f"{papel.value}@suno.example.com"
        criar_usuario(email, papel)
        assert cliente_auth.get(USERS, headers=logar(email)).status_code == 403

    def test_admin_lista_usuarios(self, cliente_auth, criar_usuario, logar):
        criar_usuario("admin@suno.example.com", Role.ADMIN)
        resposta = cliente_auth.get(USERS, headers=logar("admin@suno.example.com"))
        assert resposta.status_code == 200
        assert any(u["email"] == "admin@suno.example.com" for u in resposta.json())

    def test_sem_credencial_da_401_e_nao_403(self, cliente_auth):
        """Quem não se identificou é 401. 403 confirmaria que a rota existe e é de admin."""
        assert cliente_auth.get(USERS).status_code == 401

    def test_admin_cria_usuario_e_a_senha_nao_volta(self, cliente_auth, criar_usuario, logar):
        criar_usuario("admin@suno.example.com", Role.ADMIN)
        resposta = cliente_auth.post(
            USERS,
            headers=logar("admin@suno.example.com"),
            json={
                "email": "novo@suno.example.com",
                "nome": "Novo",
                "senha": "senha-bem-longa-de-teste",
                "role": "vendedor",
            },
        )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["role"] == "vendedor"
        assert "senha" not in corpo and "password_hash" not in corpo

    def test_senha_curta_e_recusada(self, cliente_auth, criar_usuario, logar):
        criar_usuario("admin@suno.example.com", Role.ADMIN)
        resposta = cliente_auth.post(
            USERS,
            headers=logar("admin@suno.example.com"),
            json={"email": "novo@suno.example.com", "nome": "Novo", "senha": "curta"},
        )
        assert resposta.status_code == 422

    def test_email_repetido_da_409(self, cliente_auth, criar_usuario, logar):
        criar_usuario("admin@suno.example.com", Role.ADMIN)
        criar_usuario("ja@suno.example.com", Role.VENDEDOR)
        resposta = cliente_auth.post(
            USERS,
            headers=logar("admin@suno.example.com"),
            json={
                "email": "ja@suno.example.com",
                "nome": "Duplicado",
                "senha": "senha-bem-longa-de-teste",
            },
        )
        assert resposta.status_code == 409


class TestAdminNaoDaPeNoProprioPe:
    def test_admin_nao_se_rebaixa(self, cliente_auth, criar_usuario, logar):
        """Sem esta guarda, o último admin se remove por acidente e sobra mexer no banco."""
        admin = criar_usuario("admin@suno.example.com", Role.ADMIN)
        resposta = cliente_auth.patch(
            f"{USERS}/{admin.id}",
            headers=logar("admin@suno.example.com"),
            json={"role": "vendedor"},
        )
        assert resposta.status_code == 409

    def test_admin_nao_se_desativa(self, cliente_auth, criar_usuario, logar):
        admin = criar_usuario("admin@suno.example.com", Role.ADMIN)
        resposta = cliente_auth.patch(
            f"{USERS}/{admin.id}",
            headers=logar("admin@suno.example.com"),
            json={"ativo": False},
        )
        assert resposta.status_code == 409

    def test_admin_rebaixa_outro(self, cliente_auth, criar_usuario, logar):
        criar_usuario("admin@suno.example.com", Role.ADMIN)
        outro = criar_usuario("gestor@suno.example.com", Role.GESTOR)
        resposta = cliente_auth.patch(
            f"{USERS}/{outro.id}",
            headers=logar("admin@suno.example.com"),
            json={"role": "vendedor"},
        )
        assert resposta.status_code == 200
        assert resposta.json()["role"] == "vendedor"

    def test_rebaixar_tem_efeito_imediato(self, cliente_auth, criar_usuario, logar):
        """O access que já está na mão do rebaixado perde o poder na hora.

        `usuario_atual` relê o banco a cada requisição de propósito: confiar no claim
        `role` deixaria um ex-admin com poder de admin por 30 minutos.
        """
        criar_usuario("admin@suno.example.com", Role.ADMIN)
        vitima = criar_usuario("admin2@suno.example.com", Role.ADMIN)
        headers_vitima = logar("admin2@suno.example.com")
        assert cliente_auth.get(USERS, headers=headers_vitima).status_code == 200

        cliente_auth.patch(
            f"{USERS}/{vitima.id}",
            headers=logar("admin@suno.example.com"),
            json={"role": "vendedor"},
        )
        assert cliente_auth.get(USERS, headers=headers_vitima).status_code == 403

    def test_alteracao_fica_no_audit_log(self, cliente_auth, criar_usuario, logar):
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import AuditLog

        criar_usuario("admin@suno.example.com", Role.ADMIN)
        outro = criar_usuario("gestor@suno.example.com", Role.GESTOR)
        cliente_auth.patch(
            f"{USERS}/{outro.id}",
            headers=logar("admin@suno.example.com"),
            json={"role": "vendedor"},
        )
        with session_scope() as sessao:
            linhas = sessao.exec(select(AuditLog).where(AuditLog.acao == "usuario_alterado")).all()
            mudancas = [dict(linha.detalhe or {}) for linha in linhas]
        assert mudancas == [{"role": "gestor -> vendedor"}]
