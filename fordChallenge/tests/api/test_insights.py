"""WP-27 — `/insights/competitors` e `/insights/summary`: win/loss com o `n` à vista.

O critério de aceite é a regra do `n`: **15 sessões reais mostram contagens, não
percentuais**; com 60 simuladas, os percentuais aparecem **em bloco separado e rotulado
SIMULAÇÃO**. "67% de perda" sobre três sessões parece estatística e é ruído — e é
justamente o número que vira slide e depois vira decisão.
"""

from __future__ import annotations

import datetime as dt

import pytest

from api.app.models import Role
from api.app.services import winloss

COMPETITORS = "/api/v1/insights/competitors"
SUMMARY = "/api/v1/insights/summary"


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def vendedor(criar_usuario, logar):
    criar_usuario("vendedor@suno.example.com", Role.VENDEDOR)
    return logar("vendedor@suno.example.com")


def semear(catalogo, *, quantidade: int, simulada: bool, vendedor_id: str | None = None):
    """Cria sessões com desfecho previsível, para as contagens serem verificáveis."""
    from api.app.db import session_scope
    from api.app.models import ShowroomSession

    agora = dt.datetime(2026, 9, 9, 12, 0, 0)
    with session_scope() as sessao:
        for indice in range(quantidade):
            desfecho = "perdeu" if indice % 3 == 0 else "fechou"
            sessao.add(
                ShowroomSession(
                    vendedor_id=vendedor_id,
                    ford_version_id=catalogo["raptor"],
                    competitor_version_ids=[catalogo["srx"]],
                    needs_profile_json={"uso": ["rural_carga"]},
                    outcome=desfecho,
                    motivos=["preco"] if desfecho == "perdeu" else [],
                    atributo_decisivo="preco_sugerido_brl",
                    is_simulated=simulada,
                    created_at=agora - dt.timedelta(days=indice),
                )
            )
        sessao.commit()


class TestARegraDoN:
    def test_criterio_de_aceite_15_sessoes_dao_contagem_e_nao_percentual(
        self, cliente_auth, catalogo, analista
    ):
        """Critério: 15 sessões reais → contagens, sem percentuais."""
        semear(catalogo, quantidade=15, simulada=False)
        corpo = cliente_auth.get(COMPETITORS, headers=analista).json()
        conc = corpo["real"][0]
        assert conc["n"] == 15
        assert conc["mostra_percentual"] is False
        assert conc["fechou"]["percentual"] is None
        assert conc["fechou"]["valor"] == 10
        assert conc["perdeu"]["valor"] == 5
        assert "menos de 20 sessões" in conc["aviso"]

    def test_criterio_de_aceite_60_simuladas_dao_percentual_em_bloco_separado(
        self, cliente_auth, catalogo, analista
    ):
        """Critério: com 60 simuladas, percentuais rotulados SIMULAÇÃO em bloco separado."""
        semear(catalogo, quantidade=15, simulada=False)
        semear(catalogo, quantidade=60, simulada=True)
        corpo = cliente_auth.get(COMPETITORS, headers=analista).json()

        assert corpo["n_real"] == 15
        assert corpo["n_simulado"] == 60
        assert corpo["rotulo_simulacao"] == "SIMULAÇÃO — dados de demonstração"

        real = corpo["real"][0]
        simulado = corpo["simulado"][0]
        assert real["mostra_percentual"] is False
        assert simulado["mostra_percentual"] is True
        assert simulado["fechou"]["percentual"] is not None

    def test_as_duas_populacoes_NUNCA_sao_somadas(self, cliente_auth, catalogo, analista):
        """Com 60 simuladas contra 15 reais, a média das duas apagaria o real."""
        semear(catalogo, quantidade=15, simulada=False)
        semear(catalogo, quantidade=60, simulada=True)
        corpo = cliente_auth.get(COMPETITORS, headers=analista).json()
        assert corpo["real"][0]["n"] == 15
        assert corpo["simulado"][0]["n"] == 60
        assert "total" not in corpo

    def test_exatamente_20_ja_mostra_percentual(self, cliente_auth, catalogo, analista):
        """O limiar é "≥ 20", e o teste fixa a borda."""
        semear(catalogo, quantidade=20, simulada=False)
        corpo = cliente_auth.get(COMPETITORS, headers=analista).json()
        assert corpo["real"][0]["mostra_percentual"] is True
        assert winloss.N_MINIMO_PARA_PERCENTUAL == 20

    def test_dezenove_ainda_nao(self, cliente_auth, catalogo, analista):
        semear(catalogo, quantidade=19, simulada=False)
        assert (
            cliente_auth.get(COMPETITORS, headers=analista).json()["real"][0]["mostra_percentual"]
            is False
        )

    def test_o_limiar_viaja_na_resposta(self, cliente_auth, catalogo, analista):
        """Sem ele, a tela teria de repetir o número 20 — e os dois divergiriam."""
        corpo = cliente_auth.get(COMPETITORS, headers=analista).json()
        assert corpo["n_minimo_para_percentual"] == 20


class TestOQueOPainelDiz:
    def test_top_motivos_vem_com_a_contagem(self, cliente_auth, catalogo, analista):
        """ "Top motivo: preço" não diz se foram 12 sessões ou 2."""
        semear(catalogo, quantidade=15, simulada=False)
        conc = cliente_auth.get(COMPETITORS, headers=analista).json()["real"][0]
        assert conc["top_motivos"][0]["chave"] == "preco"
        assert conc["top_motivos"][0]["n"] == 5

    def test_so_a_sessao_perdida_informa_motivo(self, cliente_auth, catalogo, analista):
        """Contar o motivo de uma venda fechada misturaria "pesou contra" com "comentou"."""
        semear(catalogo, quantidade=15, simulada=False)
        conc = cliente_auth.get(COMPETITORS, headers=analista).json()["real"][0]
        assert sum(m["n"] for m in conc["top_motivos"]) == conc["perdeu"]["valor"]

    def test_traz_atributo_decisivo_e_perfis(self, cliente_auth, catalogo, analista):
        semear(catalogo, quantidade=15, simulada=False)
        conc = cliente_auth.get(COMPETITORS, headers=analista).json()["real"][0]
        assert conc["top_atributos_decisivos"][0]["chave"] == "preco_sugerido_brl"
        assert conc["perfis"][0]["chave"] == "rural_carga"

    def test_o_rotulo_do_concorrente_e_legivel(self, cliente_auth, catalogo, analista):
        semear(catalogo, quantidade=3, simulada=False)
        conc = cliente_auth.get(COMPETITORS, headers=analista).json()["real"][0]
        assert "Hilux" in conc["rotulo"]

    def test_sem_sessao_nenhuma_a_lista_e_vazia_e_nao_erro(self, cliente_auth, catalogo, analista):
        corpo = cliente_auth.get(COMPETITORS, headers=analista).json()
        assert corpo["real"] == []
        assert corpo["n_real"] == 0

    def test_filtra_por_ford_version(self, cliente_auth, catalogo, analista):
        semear(catalogo, quantidade=5, simulada=False)
        corpo = cliente_auth.get(
            f"{COMPETITORS}?ford_version={catalogo['srx']}", headers=analista
        ).json()
        assert corpo["n_real"] == 0

    def test_filtra_por_since(self, cliente_auth, catalogo, analista):
        semear(catalogo, quantidade=15, simulada=False)
        corpo = cliente_auth.get(
            f"{COMPETITORS}?since=2026-09-05T00:00:00", headers=analista
        ).json()
        assert 0 < corpo["n_real"] < 15


class TestResumo:
    def test_traz_real_e_simulado_separados(self, cliente_auth, catalogo, analista):
        semear(catalogo, quantidade=15, simulada=False)
        semear(catalogo, quantidade=60, simulada=True)
        corpo = cliente_auth.get(SUMMARY, headers=analista).json()
        assert corpo["real"]["n"] == 15
        assert corpo["simulado"]["n"] == 60
        assert corpo["real"]["mostra_percentual"] is False
        assert corpo["simulado"]["mostra_percentual"] is True

    def test_o_aviso_explica_por_que_nao_ha_percentual(self, cliente_auth, catalogo, analista):
        semear(catalogo, quantidade=5, simulada=False)
        corpo = cliente_auth.get(SUMMARY, headers=analista).json()
        assert "pareceria estatística e seria ruído" in corpo["real"]["aviso"]


class TestEscopo:
    def test_vendedor_ve_so_as_proprias(self, cliente_auth, catalogo, vendedor):
        """A taxa de fechamento de um colega não é informação dele."""
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import User

        with session_scope() as sessao:
            eu = sessao.exec(select(User).where(User.email == "vendedor@suno.example.com")).first()
            assert eu is not None
            meu_id = eu.id

        semear(catalogo, quantidade=4, simulada=False, vendedor_id=meu_id)
        semear(catalogo, quantidade=7, simulada=False, vendedor_id=None)

        corpo = cliente_auth.get(COMPETITORS, headers=vendedor).json()
        assert corpo["n_real"] == 4
        assert corpo["escopo"] == "proprios"
        assert "apenas as sessões que registrou" in corpo["aviso_de_escopo"]

    def test_analista_ve_todas_e_sem_aviso_de_escopo(self, cliente_auth, catalogo, analista):
        semear(catalogo, quantidade=7, simulada=False)
        corpo = cliente_auth.get(COMPETITORS, headers=analista).json()
        assert corpo["n_real"] == 7
        assert corpo["escopo"] == "todos"
        assert corpo["aviso_de_escopo"] == ""

    def test_o_vendedor_ENTRA_aqui_ao_contrario_da_saude(self, cliente_auth, catalogo, vendedor):
        """Contraste deliberado com `/insights/knowledge-health` (D-103).

        Lá a tela inteira é dado interno da Ford; aqui é o resultado do trabalho dele.
        """
        assert cliente_auth.get(COMPETITORS, headers=vendedor).status_code == 200
        assert (
            cliente_auth.get(
                f"/api/v1/insights/knowledge-health?version_id={catalogo['raptor']}",
                headers=vendedor,
            ).status_code
            == 403
        )

    @pytest.mark.parametrize("rota", [COMPETITORS, SUMMARY])
    def test_sem_credencial_da_401(self, cliente_auth, catalogo, rota):
        assert cliente_auth.get(rota).status_code == 401


class TestSementeSimulada:
    def test_a_distribuicao_esta_declarada_no_script(self):
        """`docs/12` §6.5: a distribuição é declarada, não "descoberta"."""
        from api.app.seed import DISTRIBUICAO_DE_SESSOES, SEMENTE_ALEATORIA

        assert set(DISTRIBUICAO_DE_SESSOES["desfecho"]) == {
            "fechou",
            "perdeu",
            "em_andamento",
        }
        assert abs(sum(DISTRIBUICAO_DE_SESSOES["desfecho"].values()) - 1.0) < 1e-9
        assert abs(sum(DISTRIBUICAO_DE_SESSOES["motivos"].values()) - 1.0) < 1e-9
        # Semente fixa: a demo tem de mostrar o mesmo painel duas vezes seguidas.
        assert isinstance(SEMENTE_ALEATORIA, int)

    def test_toda_sessao_semeada_e_marcada(self, catalogo):
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import ShowroomSession
        from api.app.seed import semear_sessoes_simuladas

        criadas = semear_sessoes_simuladas(10)
        assert criadas == 10
        with session_scope() as sessao:
            linhas = sessao.exec(select(ShowroomSession)).all()
            assert linhas
            assert all(linha.is_simulated for linha in linhas)

    def test_a_semente_e_reprodutivel(self, catalogo):
        """Número que muda a cada `seed` faria alguém achar que o dado é vivo."""
        from sqlmodel import delete, select

        from api.app.db import session_scope
        from api.app.models import ShowroomSession
        from api.app.seed import semear_sessoes_simuladas

        def desfechos() -> list[str]:
            with session_scope() as sessao:
                return [
                    linha.outcome
                    for linha in sessao.exec(
                        select(ShowroomSession).order_by(ShowroomSession.created_at)  # type: ignore[attr-defined]
                    ).all()
                ]

        semear_sessoes_simuladas(12)
        primeira = desfechos()
        with session_scope() as sessao:
            sessao.exec(delete(ShowroomSession))
            sessao.commit()
        semear_sessoes_simuladas(12)
        assert desfechos() == primeira
