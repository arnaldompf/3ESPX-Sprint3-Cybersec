"""`GET /catalog/suggest` — a caixa única da Consulta, do lado do servidor.

A regra de ordenação é testada sem banco em `tests/pipeline/test_sugestao.py`. Aqui se
testa o que só o servidor sabe: quem tem ficha gravada, quais anos existem, e que o
vendedor — que é quem usa a caixa no showroom — consegue chamar a rota.
"""

from __future__ import annotations

import pytest

from api.app.models import Role

SUGGEST = "/api/v1/catalog/suggest"


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def vendedor(criar_usuario, logar):
    criar_usuario("vendedor@suno.example.com", Role.VENDEDOR)
    return logar("vendedor@suno.example.com")


def _buscar(cliente, headers, q: str, **params):
    return cliente.get(SUGGEST, params={"q": q, **params}, headers=headers).json()


class TestAcha:
    def test_texto_solto_acha_a_versao(self, cliente_auth, catalogo, analista):
        corpo = _buscar(cliente_auth, analista, "raptor")
        assert corpo["melhor"]["versao"] == "Raptor 3.0 V6 Bi-turbo 4WD AT"
        assert corpo["melhor"]["marca"] == "Ford"
        assert corpo["vazia"] is False
        assert corpo["desempate"] == "regra"

    def test_meia_palavra_da_versao_basta(self, cliente_auth, catalogo, analista):
        """*"hilux srx"* — o que se digita de verdade, não o nome completo da montadora."""
        corpo = _buscar(cliente_auth, analista, "hilux srx")
        # A caixa usa o nome canônico; o qualificador redundante da fixture antiga
        # não pode reaparecer como uma segunda versão na Consulta.
        assert corpo["melhor"]["versao"] == "SRX Plus AT"

    def test_o_texto_montado_e_o_que_a_tela_mostra(self, cliente_auth, catalogo, analista):
        corpo = _buscar(cliente_auth, analista, "raptor")
        assert corpo["melhor"]["texto"] == "Ford Ranger Raptor 3.0 V6 Bi-turbo 4WD AT"

    def test_fora_do_catalogo_devolve_vazio_e_nao_o_primo(self, cliente_auth, catalogo, analista):
        """O sinal para a tela cair no Pesquisador. Devolver a versão mais parecida
        diria que temos ficha de um carro que ninguém coletou."""
        corpo = _buscar(cliente_auth, analista, "amarok v6 highline")
        assert corpo["vazia"] is True
        assert corpo["melhor"] is None
        assert corpo["motivo"]


class TestFichaEAno:
    def test_diz_quem_tem_ficha_gravada(self, cliente_auth, catalogo, analista):
        """A Raptor tem `spec_values`; a SRX não. A caixa precisa saber a diferença
        para não oferecer um ano que abre uma ficha vazia."""
        raptor = _buscar(cliente_auth, analista, "raptor")["melhor"]
        srx = _buscar(cliente_auth, analista, "hilux srx")["melhor"]
        assert raptor["ano"]["tem_ficha"] is True
        assert srx["ano"]["tem_ficha"] is False

    def test_o_ano_padrao_e_o_do_catalogo(self, cliente_auth, catalogo, analista):
        corpo = _buscar(cliente_auth, analista, "raptor")
        assert corpo["melhor"]["ano"]["ano_modelo"] == 2026
        assert corpo["melhor"]["ano"]["codigo_fipe"] == "003506-8"

    def test_ano_sem_copia_e_nomeado_em_vez_de_trocado_em_silencio(
        self, cliente_auth, catalogo, analista
    ):
        """*"raptor 2025"*: não temos 2025. A resposta oferece 2026 **e diz** que o 2025
        pedido não existe — trocar sem avisar faria o vendedor citar o ano errado."""
        corpo = _buscar(cliente_auth, analista, "raptor 2025")
        assert corpo["ano_pedido"] == 2025
        assert corpo["melhor"]["ano_pedido_sem_ficha"] == 2025
        assert corpo["melhor"]["ano"]["ano_modelo"] == 2026

    def test_todos_os_anos_da_versao_viajam_na_resposta(self, cliente_auth, catalogo, analista):
        corpo = _buscar(cliente_auth, analista, "hilux gr-sport")
        anos = [a["ano_modelo"] for a in corpo["melhor"]["anos"]]
        assert anos == [2024]


class TestContrato:
    def test_o_vendedor_pode_usar_a_caixa(self, cliente_auth, catalogo, vendedor):
        """É a tela dele. Uma caixa de busca que o vendedor não pode chamar não serve."""
        resposta = cliente_auth.get(SUGGEST, params={"q": "raptor"}, headers=vendedor)
        assert resposta.status_code == 200

    def test_consulta_vazia_e_422(self, cliente_auth, catalogo, analista):
        assert cliente_auth.get(SUGGEST, params={"q": ""}, headers=analista).status_code == 422

    def test_limite_corta_as_outras(self, cliente_auth, catalogo, analista):
        corpo = _buscar(cliente_auth, analista, "hilux", limite=1)
        assert len(corpo["outras"]) <= 1

    def test_sem_ia_por_padrao_o_empate_fica_de_pe(self, cliente_auth, catalogo, analista):
        """`desempatar_com_ia` é opt-in: a caixa dispara a cada tecla, e uma chamada de
        LLM por tecla é como se transforma uma busca em conta de provedor."""
        corpo = _buscar(cliente_auth, analista, "toyota hilux")
        assert corpo["ambigua"] is True
        assert corpo["desempate"] == "regra"
        assert corpo["melhor"] is None
        assert len(corpo["empatadas"]) == 2


class TestAlvoDePesquisa:
    def test_o_trio_do_pesquisador_vem_pronto(self, cliente_auth, catalogo, analista):
        """Sem isto a tela teria de partir a frase sozinha, e *"amarok v6 highline"*
        viraria marca "amarok" — três consultas de busca erradas, orçamento gasto."""
        corpo = _buscar(cliente_auth, analista, "ranger raptor especial")
        assert corpo["para_pesquisar"]["marca"] == "Ford"
        assert corpo["para_pesquisar"]["modelo"] == "Ranger"
        assert corpo["para_pesquisar"]["de_onde"] == "catalogo"

    def test_sem_quase_acerto_o_chute_vem_marcado(self, cliente_auth, catalogo, analista):
        corpo = _buscar(cliente_auth, analista, "byd shark gl")
        assert corpo["para_pesquisar"]["de_onde"] == "texto"
