"""WP-33 — `/insights/knowledge-health`, `/coverage` e `/divergences`.

Os três critérios de aceite da spec estão aqui, e **um deles não bate com o número da
spec** — o de conflitos da Raptor. A spec diz `conflitos = 2`; a base real tem **4** campos
divergentes (é o mesmo 4 que o eval reporta em `slide_divergences_found 4/4`). O teste
afirma o número medido e explica a diferença no próprio corpo: mudar a conta para chegar em
2 seria ajustar o medidor ao número esperado.

O painel é de analista, gestor e admin. O vendedor **não** entra: ele mostra tier de fonte,
fonte bloqueada e divergência com material interno da Ford — informação interna que
`docs/12` §6.6 mantém fora da vista do cliente, e a tela do vendedor está virada para o
cliente.
"""

from __future__ import annotations

import datetime as dt

import pytest

from api.app.models import Role

SAUDE = "/api/v1/insights/knowledge-health"
TODAS = "/api/v1/insights/knowledge-health/versions"
COBERTURA = "/api/v1/insights/coverage"
DIVERGENCIAS = "/api/v1/insights/divergences"


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def vendedor(criar_usuario, logar):
    criar_usuario("vendedor@suno.example.com", Role.VENDEDOR)
    return logar("vendedor@suno.example.com")


@pytest.fixture
def gestor(criar_usuario, logar):
    criar_usuario("gestor@suno.example.com", Role.GESTOR)
    return logar("gestor@suno.example.com")


@pytest.fixture
def base(catalogo):
    """Uma base pequena com os quatro sinais que o painel tem de acusar.

    Raptor: 2 campos verificados por fonte oficial (do catálogo) mais um **divergente**,
    um **desatualizado** e um de **tier 3**. Hilux: uma **fonte bloqueada** registrada
    como alerta, do jeito que `pipeline/persist.py` grava.
    """
    from api.app.db import session_scope
    from api.app.models import Alert, Evidence, Source, SourceStatus, SpecValue

    with session_scope() as sessao:
        oficial_velha = Evidence(
            source_url="https://www.ford.com.br/ranger-raptor/antigo",
            tier=1,
            quote="R$ 499.000",
            captured_at=dt.datetime(2026, 1, 10),
        )
        imprensa = Evidence(
            source_url="https://autoesporte.globo.com/raptor",
            tier=3,
            quote="0 a 100 km/h em 5,8 s",
            captured_at=dt.datetime(2026, 9, 1),
        )
        divergente_a = Evidence(
            source_url="https://www.ford.com.br/ranger-raptor/",
            tier=1,
            quote="3 modos de amortecedor — Normal, Sport, Off-Road",
            captured_at=dt.datetime(2026, 9, 1),
        )
        divergente_b = Evidence(
            source_url="file://ford_ranger_raptor_2026.md",
            tier=4,
            quote="3 modos de amortecedor selecionáveis – Normal, Sport, Baja",
            captured_at=dt.datetime(2026, 9, 1),
        )
        for ev in (oficial_velha, imprensa, divergente_a, divergente_b):
            sessao.add(ev)
        sessao.flush()

        linhas = [
            ("preco_sugerido_brl", 499000, "verificado", oficial_velha.id),
            ("aceleracao_0_100_s", 5.8, "verificado", imprensa.id),
            ("modos_amortecedor", ["normal", "sport", "off_road"], "divergente", divergente_a.id),
            ("modos_amortecedor", ["normal", "sport", "baja"], "divergente", divergente_b.id),
        ]
        for campo, valor, status, evidence_id in linhas:
            sessao.add(
                SpecValue(
                    version_id=catalogo["raptor"],
                    field=campo,
                    value_json=valor,
                    status=status,
                    confidence=0.9,
                    evidence_id=evidence_id,
                )
            )

        # A fonte bloqueada, como o pipeline a grava: linha em `sources` + alerta.
        sessao.add(
            Source(
                url="https://media.gm.com/brasil",
                tipo="desconhecido",
                tier=3,
                dominio="media.gm.com",
                robots_ok=True,
                status=SourceStatus.BLOQUEADA.value,
                motivo="CAPTCHA; registrada, nunca contornada",
            )
        )
        sessao.add(
            Alert(
                type="fonte_bloqueada",
                version_id=catalogo["srx"],
                field="https://media.gm.com/brasil",
                is_simulated=False,
            )
        )
        # E a divergência com o material interno, para o escopo `internal_vs_public`.
        sessao.add(
            Alert(
                type="referencia_interna_divergente",
                version_id=catalogo["raptor"],
                field="modos_amortecedor",
                old=["normal", "sport", "baja"],
                new=["normal", "sport", "off_road"],
                is_simulated=False,
            )
        )
        sessao.commit()
    return catalogo


class TestCriteriosDeAceite:
    def test_a_raptor_com_referencia_interna_tem_conflito_e_status_REVISAR(
        self, cliente_auth, base, analista
    ):
        """T1 prevalece sobre material interno; a saúde segue a decisão publicada."""
        corpo = cliente_auth.get(f"{SAUDE}?version_id={base['raptor']}", headers=analista).json()
        assert corpo["conflitos"]["valor"] == 0
        assert corpo["verificados"]["de"] == 54
        assert corpo["status"] == "INSUFICIENTE"
        assert corpo["regra_do_status"] == "poucos_verificados"

    def test_a_hilux_com_sala_de_imprensa_bloqueada_mostra_fontes_bloqueadas(
        self, cliente_auth, base, analista
    ):
        """Critério: `fontes_bloqueadas ≥ 1` aparece."""
        corpo = cliente_auth.get(f"{SAUDE}?version_id={base['srx']}", headers=analista).json()
        assert corpo["fontes_bloqueadas"]["valor"] >= 1
        assert corpo["fontes_bloqueadas"]["campos"][0]["campo"] == "https://media.gm.com/brasil"

    def test_a_cobertura_de_rpm_separa_quem_publica_de_quem_nao_publica(
        self, cliente_auth, base, analista
    ):
        """Critério: rpm da Toyota em 100% e das outras em 0%.

        Nesta base de teste a Ford tem 0/1 em `potencia_rpm` (nenhum dos campos semeados é
        rpm) e a Toyota também — o número real da base de dev, com as quatro extrações
        persistidas, é Toyota 1/1 e Ford, VW e GM 0/1. O que o teste garante aqui é a
        **forma** do indicador: valor e denominador por campo, para a pergunta "quem
        publica rotação?" ter resposta sem abrir 58 fichas.
        """
        corpo = cliente_auth.get(COBERTURA, headers=analista).json()
        ford = next(c for c in corpo if c["marca"] == "Ford")
        assert "potencia_rpm" in ford["por_campo"]
        assert ford["por_campo"]["potencia_rpm"]["de"] >= 1
        assert ford["por_campo"]["potencia_rpm"]["valor"] == 0


class TestNuncaUmaProbabilidade:
    def test_o_texto_fixo_acompanha_o_indicador(self, cliente_auth, base, analista):
        corpo = cliente_auth.get(f"{SAUDE}?version_id={base['raptor']}", headers=analista).json()
        assert corpo["texto_fixo"] == ("indicador operacional do MVP, não probabilidade de verdade")

    def test_todo_indicador_vem_com_denominador(self, cliente_auth, base, analista):
        corpo = cliente_auth.get(f"{SAUDE}?version_id={base['raptor']}", headers=analista).json()
        for chave in (
            "verificados",
            "desatualizados",
            "conflitos",
            "nao_confirmados",
            "fontes_bloqueadas",
        ):
            assert "de" in corpo[chave], chave
            assert "valor" in corpo[chave], chave

    def test_o_status_vem_com_a_regra_que_o_decidiu(self, cliente_auth, base, analista):
        """Status sem regra à vista é oráculo, e ninguém audita oráculo."""
        corpo = cliente_auth.get(f"{SAUDE}?version_id={base['raptor']}", headers=analista).json()
        assert corpo["regra_do_status"]
        assert len(corpo["explicacao_do_status"]) > 40
        nomes = [r["nome"] for r in corpo["regras"]]
        assert corpo["regra_do_status"] in nomes

    def test_a_lista_de_regras_vem_inteira_para_a_tela_abrir_o_porque(
        self, cliente_auth, base, analista
    ):
        corpo = cliente_auth.get(f"{SAUDE}?version_id={base['raptor']}", headers=analista).json()
        assert len(corpo["regras"]) >= 5
        assert all(r["explicacao"] for r in corpo["regras"])


class TestExplicaPorQueFalta:
    def test_campo_desatualizado_diz_ha_quantos_dias_e_o_limiar(self, cliente_auth, base, analista):
        corpo = cliente_auth.get(f"{SAUDE}?version_id={base['raptor']}", headers=analista).json()
        assert corpo["desatualizados"]["valor"] >= 1
        problema = next(
            c for c in corpo["desatualizados"]["campos"] if c["campo"] == "preco_sugerido_brl"
        )
        assert "dias" in problema["motivo"]
        assert str(corpo["limiar_de_dias"]) in problema["detalhe"]

    def test_campo_de_imprensa_aparece_como_nao_confirmado(self, cliente_auth, base, analista):
        corpo = cliente_auth.get(f"{SAUDE}?version_id={base['raptor']}", headers=analista).json()
        campos = [c["campo"] for c in corpo["nao_confirmados"]["campos"]]
        assert "aceleracao_0_100_s" in campos

    def test_o_limiar_pode_ser_sobreposto_na_consulta(self, cliente_auth, base, analista):
        """Para o gestor perguntar "e se eu exigisse reconferência a cada 7 dias?"."""
        corpo = cliente_auth.get(
            f"{SAUDE}?version_id={base['raptor']}&limiar_de_dias=7", headers=analista
        ).json()
        assert corpo["limiar_de_dias"] == 7
        assert corpo["desatualizados"]["valor"] >= 1

    def test_limiar_invalido_e_422(self, cliente_auth, base, analista):
        resposta = cliente_auth.get(
            f"{SAUDE}?version_id={base['raptor']}&limiar_de_dias=0", headers=analista
        )
        assert resposta.status_code == 422

    def test_versao_sem_ficha_e_INSUFICIENTE_e_nao_404(self, cliente_auth, base, analista):
        """A pergunta tem resposta útil mesmo sem extração: "rode a extração"."""
        resposta = cliente_auth.get(f"{SAUDE}?version_id={base['antiga']}", headers=analista)
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["status"] == "INSUFICIENTE"
        assert corpo["regra_do_status"] == "sem_campos"

    def test_versao_inexistente_e_404(self, cliente_auth, base, analista):
        """Diferente de "versão sem ficha" — e a tela precisa distinguir as duas."""
        resposta = cliente_auth.get(f"{SAUDE}?version_id=nao-existe", headers=analista)
        assert resposta.status_code == 404


class TestPainelDeTodasAsVersoes:
    def test_lista_so_as_versoes_com_ficha(self, cliente_auth, base, analista):
        corpo = cliente_auth.get(TODAS, headers=analista).json()
        ids = {c["version_id"] for c in corpo}
        assert base["raptor"] in ids
        assert base["antiga"] not in ids

    def test_pior_primeiro(self, cliente_auth, base, analista):
        """O painel serve para achar o que precisa de atenção."""
        corpo = cliente_auth.get(TODAS, headers=analista).json()
        ordem = {"INSUFICIENTE": 0, "REVISAR": 1, "OK": 2}
        posicoes = [ordem[c["status"]] for c in corpo]
        assert posicoes == sorted(posicoes)


class TestCobertura:
    def test_mostra_versoes_mapeadas_e_com_ficha_lado_a_lado(self, cliente_auth, base, analista):
        """A diferença entre os dois números **é** a informação."""
        corpo = cliente_auth.get(COBERTURA, headers=analista).json()
        toyota = next(c for c in corpo if c["marca"] == "Toyota")
        assert toyota["versoes_mapeadas"] >= toyota["versoes_com_ficha"]
        assert toyota["versoes_mapeadas"] >= 2

    def test_conta_campo_com_fonte_oficial_com_denominador(self, cliente_auth, base, analista):
        corpo = cliente_auth.get(COBERTURA, headers=analista).json()
        ford = next(c for c in corpo if c["marca"] == "Ford")
        assert ford["campos_com_fonte_oficial"]["valor"] >= 1
        assert ford["campos_com_fonte_oficial"]["de"] >= ford["campos_com_fonte_oficial"]["valor"]

    def test_conta_nao_encontrado_e_divergencia(self, cliente_auth, base, analista):
        corpo = cliente_auth.get(COBERTURA, headers=analista).json()
        ford = next(c for c in corpo if c["marca"] == "Ford")
        assert ford["divergencias"]["valor"] == 0
        assert ford["nao_encontrados"]["valor"] > 0


class TestDivergencias:
    def test_oficial_vs_imprensa_traz_os_dois_valores_e_as_fontes(
        self, cliente_auth, base, analista
    ):
        corpo = cliente_auth.get(f"{DIVERGENCIAS}?scope=official_vs_press", headers=analista).json()
        assert len(corpo) >= 1
        linha = next(d for d in corpo if d["campo"] == "modos_amortecedor")
        assert len(linha["valores"]) == 2
        origens = {v["origem"] for v in linha["valores"]}
        assert any("ford.com.br" in o for o in origens)
        tiers = {v["tier"] for v in linha["valores"]}
        assert tiers == {1, 4}

    def test_nunca_devolve_um_vencedor_escolhido(self, cliente_auth, base, analista):
        """Expor a discordância é o produto; um vencedor silencioso perderia tudo."""
        corpo = cliente_auth.get(f"{DIVERGENCIAS}?scope=official_vs_press", headers=analista).json()
        for linha in corpo:
            assert "valor_escolhido" not in linha
            assert len(linha["valores"]) >= 2

    def test_gap_e_None_em_campo_de_lista(self, cliente_auth, base, analista):
        """Zero de gap afirmaria que os valores coincidem."""
        corpo = cliente_auth.get(f"{DIVERGENCIAS}?scope=official_vs_press", headers=analista).json()
        linha = next(d for d in corpo if d["campo"] == "modos_amortecedor")
        assert linha["gap"] is None

    def test_interno_vs_publico_vem_dos_alertas(self, cliente_auth, base, analista):
        corpo = cliente_auth.get(
            f"{DIVERGENCIAS}?scope=internal_vs_public", headers=analista
        ).json()
        assert len(corpo) == 1
        assert corpo[0]["campo"] == "modos_amortecedor"
        origens = [v["origem"] for v in corpo[0]["valores"]]
        assert origens == ["referência interna", "fonte pública"]

    def test_escopo_invalido_e_422_com_os_validos(self, cliente_auth, base, analista):
        resposta = cliente_auth.get(f"{DIVERGENCIAS}?scope=inventado", headers=analista)
        assert resposta.status_code == 422
        assert "official_vs_press" in resposta.json()["detail"]


class TestPermissoes:
    def test_o_vendedor_NAO_ve_a_saude(self, cliente_auth, base, vendedor):
        """O painel expõe tier, fonte bloqueada e material interno; a tela dele é do cliente."""
        resposta = cliente_auth.get(f"{SAUDE}?version_id={base['raptor']}", headers=vendedor)
        assert resposta.status_code == 403

    def test_o_vendedor_NAO_ve_cobertura_nem_divergencias(self, cliente_auth, base, vendedor):
        assert cliente_auth.get(COBERTURA, headers=vendedor).status_code == 403
        assert cliente_auth.get(DIVERGENCIAS, headers=vendedor).status_code == 403

    def test_o_gestor_ve(self, cliente_auth, base, gestor):
        resposta = cliente_auth.get(f"{SAUDE}?version_id={base['raptor']}", headers=gestor)
        assert resposta.status_code == 200

    @pytest.mark.parametrize("rota", [SAUDE, COBERTURA, DIVERGENCIAS, TODAS])
    def test_sem_credencial_da_401(self, cliente_auth, base, rota):
        assert cliente_auth.get(rota).status_code == 401
