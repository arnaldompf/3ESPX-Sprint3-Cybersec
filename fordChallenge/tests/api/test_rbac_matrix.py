"""WP-28 — a matriz de `docs/12` §6.6 exercitada **pela rota**, papel por papel.

`tests/api/test_rbac.py` (WP-05) testa a matriz como dado: `escopo_de(papel, acao)`. Este
arquivo testa o outro lado — que **cada rota está amarrada à ação certa**. São coisas
diferentes, e a segunda é a que falha na prática: a matriz pode estar perfeita e a rota
exigir a ação errada, que foi exatamente o que aconteceu duas vezes nesta noite
(`/showroom-sessions` na listagem, `/jobs/{id}` no relatório).

O critério de aceite da WP-28 é a linha do **vendedor**: ele acessa `showroom/*` e
`POST /showroom-sessions`, e recebe **403** em `/alerts`, `/extractions` e
`/insights/summary`.
"""

from __future__ import annotations

import datetime as dt

import pytest

from api.app.models import Role
from api.app.permissions import MATRIZ, Acao, Escopo, escopo_de

PAPEIS = [Role.VENDEDOR, Role.ANALISTA, Role.GESTOR, Role.ADMIN]


@pytest.fixture
def usuarios(criar_usuario, logar):
    """Um usuário de cada papel, com o cabeçalho de cada um."""
    cabecalhos = {}
    for papel in PAPEIS:
        email = f"{papel.value}@suno.example.com"
        criar_usuario(email, papel)
        cabecalhos[papel] = logar(email)
    return cabecalhos


@pytest.fixture
def base(catalogo):
    """O mínimo para as rotas responderem 200 quando o papel permite."""
    from api.app.db import session_scope
    from api.app.models import Evidence, SpecValue

    with session_scope() as sessao:
        evidencia = Evidence(
            source_url="https://www.ford.com.br/x",
            tier=1,
            quote="Potência 397 cv",
            captured_at=dt.datetime(2026, 9, 1),
        )
        sessao.add(evidencia)
        sessao.flush()
        for version_id in (catalogo["raptor"], catalogo["srx"]):
            sessao.add(
                SpecValue(
                    version_id=version_id,
                    field="potencia_cv",
                    value_json=397 if version_id == catalogo["raptor"] else 204,
                    unit="cv",
                    status="verificado",
                    confidence=0.9,
                    evidence_id=evidencia.id,
                )
            )
        sessao.commit()
    return catalogo


def par(catalogo) -> str:
    return f"{catalogo['raptor']}:{catalogo['srx']}"


class TestOCriterioDeAceiteDoVendedor:
    def test_vendedor_cria_sessao_de_showroom(self, cliente_auth, base, usuarios):
        resposta = cliente_auth.post(
            "/api/v1/showroom-sessions",
            headers=usuarios[Role.VENDEDOR],
            json={"ford_version_id": base["raptor"]},
        )
        assert resposta.status_code == 201

    def test_vendedor_consulta_ficha_matriz_e_argumentos(self, cliente_auth, base, usuarios):
        """O que o showroom precisa: ficha, comparação, paridade e argumentário."""
        cabecalho = usuarios[Role.VENDEDOR]
        assert (
            cliente_auth.get(
                f"/api/v1/vehicles/{base['raptor']}/specs", headers=cabecalho
            ).status_code
            == 200
        )
        assert (
            cliente_auth.get(
                f"/api/v1/parity?ford_version={base['raptor']}&competitors={base['srx']}",
                headers=cabecalho,
            ).status_code
            == 200
        )
        assert (
            cliente_auth.post(
                f"/api/v1/comparisons/{par(base)}/arguments", headers=cabecalho, json={}
            ).status_code
            == 200
        )
        assert cliente_auth.get("/api/v1/dimensions", headers=cabecalho).status_code == 200

    @pytest.mark.parametrize(
        "metodo,rota",
        [
            ("get", "/api/v1/alerts"),
            ("post", "/api/v1/extractions"),
            ("get", "/api/v1/insights/summary"),
        ],
    )
    def test_vendedor_recebe_403(self, cliente_auth, base, usuarios, metodo, rota):
        """Critério: 403 em `/alerts`, `/extractions` e `/insights/summary`."""
        chamada = getattr(cliente_auth, metodo)
        resposta = (
            chamada(rota, headers=usuarios[Role.VENDEDOR], json={})
            if metodo == "post"
            else chamada(rota, headers=usuarios[Role.VENDEDOR])
        )
        assert resposta.status_code == 403, resposta.text
        assert resposta.headers["content-type"].startswith("application/problem+json")

    def test_o_403_diz_quais_papeis_tem_acesso(self, cliente_auth, base, usuarios):
        """Erro que não diz o que fazer é erro que gera ticket."""
        corpo = cliente_auth.get("/api/v1/alerts", headers=usuarios[Role.VENDEDOR]).json()
        assert "Papéis com acesso" in corpo["detail"]
        assert "analista" in corpo["detail"]


#: A ponte entre a matriz e a API: cada ação, e uma rota que a exige.
#:
#: Se uma ação não tiver rota aqui, `test_toda_acao_da_matriz_tem_rota_ou_motivo` acusa.
#: Foi este mapa que pegou `criar_sessao_showroom` sendo exigida para **listar** sessão.
#:
#: Fica no módulo, e não na classe, porque `parametrize` é avaliado no import — e porque
#: `RUF012` (default mutável em atributo de classe) está certo em reclamar.
ROTA_POR_ACAO: dict[Acao, tuple[str, str]] = {
    Acao.CONSULTAR_FICHAS: ("get", "/api/v1/vehicles"),
    Acao.CRIAR_SESSAO_SHOWROOM: ("post", "/api/v1/showroom-sessions"),
    Acao.CRIAR_EXTRACOES: ("post", "/api/v1/extractions"),
    Acao.VER_ALERTAS: ("get", "/api/v1/alerts"),
    Acao.VER_EVIDENCIAS_BRUTAS: ("get", "/api/v1/evidences/qualquer-id"),
    Acao.VER_INSIGHTS: ("get", "/api/v1/insights/competitors"),
    Acao.GERIR_REFERENCIA_INTERNA: ("get", "/api/v1/internal-references"),
    Acao.GERIR_EQUIVALENCIAS: ("post", "/api/v1/equivalents"),
    Acao.GERIR_USUARIOS: ("get", "/api/v1/users"),
    Acao.GERIR_FONTES: ("get", "/api/v1/sources"),
}

#: Ações sem rota própria, com o motivo. Nada de omissão silenciosa.
SEM_ROTA: dict[Acao, str] = {
    Acao.APROVAR_ARGUMENTOS: (
        "a rota `PUT /comparisons/{par}/arguments` usa `exige_papel(GESTOR, ADMIN)` em "
        "vez da ação, porque a governança do argumentário é do gestor por papel e não "
        "por escopo; o teste de `test_showroom_sessions.py` cobre o 403 do vendedor"
    ),
    Acao.PUBLICAR: "`/publications` é escopo da WP-22 e não existe ainda",
}


class TestUmaLinhaPorAcao:
    """Cada ação da matriz, exercitada por uma rota que a exige."""

    def test_toda_acao_da_matriz_tem_rota_ou_motivo(self):
        for acao in Acao:
            assert acao in ROTA_POR_ACAO or acao in SEM_ROTA, acao

    @pytest.mark.parametrize("acao", sorted(ROTA_POR_ACAO, key=lambda a: a.value))
    def test_quem_NAO_tem_a_acao_recebe_403(self, cliente_auth, base, usuarios, acao):
        """A linha da matriz, pela rota: papel sem a ação não passa da porta."""
        metodo, rota = ROTA_POR_ACAO[acao]
        for papel in PAPEIS:
            if escopo_de(papel, acao) is not Escopo.NENHUM:
                continue
            chamada = getattr(cliente_auth, metodo)
            resposta = (
                chamada(rota, headers=usuarios[papel], json={})
                if metodo == "post"
                else chamada(rota, headers=usuarios[papel])
            )
            assert resposta.status_code == 403, f"{papel.value} em {rota}: {resposta.status_code}"

    @pytest.mark.parametrize("acao", sorted(ROTA_POR_ACAO, key=lambda a: a.value))
    def test_quem_TEM_a_acao_passa_da_porta(self, cliente_auth, base, usuarios, acao):
        """Passar da porta é não receber 403.

        O código de sucesso varia (200, 201, 404 de id inexistente, 422 de corpo vazio), e
        **não** é o que este teste mede: ele mede autorização. Um teste que exigisse 200
        precisaria montar o corpo válido de dez rotas e passaria a falhar por motivos que
        não têm nada a ver com permissão.
        """
        metodo, rota = ROTA_POR_ACAO[acao]
        for papel in PAPEIS:
            if escopo_de(papel, acao) is Escopo.NENHUM:
                continue
            chamada = getattr(cliente_auth, metodo)
            resposta = (
                chamada(rota, headers=usuarios[papel], json={})
                if metodo == "post"
                else chamada(rota, headers=usuarios[papel])
            )
            assert resposta.status_code != 403, f"{papel.value} em {rota} levou 403"


class TestJobEhDoDono:
    def test_o_vendedor_acompanha_o_PROPRIO_job(self, cliente_auth, base, usuarios):
        """A regressão que este teste tranca.

        `GET /jobs/{id}` morava no roteador de extrações, sob `criar_extracoes` — e o
        vendedor recebia 403 ao acompanhar o **próprio** relatório. Seguir um job que eu
        pedi não é criar extração.
        """
        pedido = cliente_auth.post(
            f"/api/v1/comparisons/{par(base)}/pdf",
            headers=usuarios[Role.VENDEDOR],
            json={},
        )
        assert pedido.status_code == 202
        job_id = pedido.json()["job_id"]
        resposta = cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=usuarios[Role.VENDEDOR])
        assert resposta.status_code == 200

    def test_outro_vendedor_NAO_le_o_job(self, cliente_auth, base, usuarios, criar_usuario, logar):
        criar_usuario("outro@suno.example.com", Role.VENDEDOR)
        outro = logar("outro@suno.example.com")
        job_id = cliente_auth.post(
            f"/api/v1/comparisons/{par(base)}/pdf",
            headers=usuarios[Role.VENDEDOR],
            json={},
        ).json()["job_id"]
        assert cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=outro).status_code == 403

    def test_gestor_le_o_job_de_qualquer_um(self, cliente_auth, base, usuarios):
        job_id = cliente_auth.post(
            f"/api/v1/comparisons/{par(base)}/pdf",
            headers=usuarios[Role.VENDEDOR],
            json={},
        ).json()["job_id"]
        assert (
            cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=usuarios[Role.GESTOR]).status_code
            == 200
        )


class TestAMatrizComoDado:
    def test_negar_por_omissao(self):
        """Papel ausente numa ação é `NENHUM`: o único default seguro."""
        assert escopo_de(Role.VENDEDOR, Acao.GERIR_USUARIOS) is Escopo.NENHUM
        assert escopo_de("papel_inventado", Acao.CONSULTAR_FICHAS) is Escopo.NENHUM

    def test_a_matriz_nao_e_hierarquia_linear(self):
        """O vendedor abre showroom e o analista não — nenhuma hierarquia expressa isso.

        É a razão de a WP-05 ter trocado a hierarquia por matriz (D-61), e o teste fica
        aqui para o dia em que alguém propuser "simplificar" com níveis.
        """
        assert escopo_de(Role.VENDEDOR, Acao.CRIAR_SESSAO_SHOWROOM) is Escopo.TODOS
        assert escopo_de(Role.ANALISTA, Acao.CRIAR_SESSAO_SHOWROOM) is Escopo.NENHUM
        assert escopo_de(Role.ANALISTA, Acao.CRIAR_EXTRACOES) is Escopo.TODOS
        assert escopo_de(Role.VENDEDOR, Acao.CRIAR_EXTRACOES) is Escopo.NENHUM

    def test_o_vendedor_tem_escopo_proprios_em_insights(self):
        assert escopo_de(Role.VENDEDOR, Acao.VER_INSIGHTS) is Escopo.PROPRIOS
        assert escopo_de(Role.ANALISTA, Acao.VER_INSIGHTS) is Escopo.TODOS

    def test_toda_acao_tem_ao_menos_um_papel(self):
        """Ação sem papel nenhum seria código morto com aparência de regra."""
        for acao in Acao:
            assert MATRIZ.get(acao), acao
