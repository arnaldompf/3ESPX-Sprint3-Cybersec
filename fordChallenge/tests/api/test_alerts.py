"""WP-25 — `/alerts`, `/internal-references` e `/equivalents` pela API.

Dois critérios de aceite estão aqui: **vendedor recebe 403** em `/alerts`, e alerta
`is_simulated=true` chega marcado para a tela poder pintar o rótulo SIMULAÇÃO.

O resto cobre as permissões da matriz de `docs/12` §6.6 — a referência interna é **dado
sensível** (§7) e só gestor e admin a leem — e o formato do upload, que é onde um gestor
com uma planilha do Excel vai bater primeiro.
"""

from __future__ import annotations

import datetime as dt

import pytest

from api.app.models import Role

ALERTS = "/api/v1/alerts"
REFERENCIAS = "/api/v1/internal-references"
EQUIVALENTES = "/api/v1/equivalents"

CSV_DO_SLIDE = (
    "versao,campo,valor\n"
    "Raptor 3.0 V6 Bi-turbo 4WD AT,potencia_cv,400\n"
    "Raptor 3.0 V6 Bi-turbo 4WD AT,campo_inexistente,42\n"
)


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
def alertas(catalogo):
    """Três alertas: um real de preço, um real de campo, e um SIMULADO."""
    from api.app.db import session_scope
    from api.app.models import Alert
    from pipeline.radar import impact, reactions

    ids = {}
    with session_scope() as sessao:
        impacto = impact.calcular(
            campo="preco_sugerido_brl", antes=348790, depois=329990, preco_ford=340000
        )
        preco = Alert(
            type="preco_oficial",
            version_id=catalogo["srx"],
            field="preco_sugerido_brl",
            old=348790,
            new=329990,
            impact_json=impacto.to_dict(),
            reactions_json=reactions.to_dict("preco_oficial", impacto.direcao),
            is_simulated=False,
            created_at=dt.datetime(2026, 9, 5),
        )
        campo = Alert(
            type="campo_alterado",
            version_id=catalogo["raptor"],
            field="garantia_meses",
            old=36,
            new=60,
            is_simulated=False,
            created_at=dt.datetime(2026, 9, 6),
        )
        simulado = Alert(
            type="preco_fipe",
            version_id=catalogo["raptor"],
            field="preco_fipe_brl",
            old=452540,
            new=460000,
            is_simulated=True,
            created_at=dt.datetime(2026, 9, 7),
        )
        for linha in (preco, campo, simulado):
            sessao.add(linha)
        sessao.commit()
        ids = {"preco": preco.id, "campo": campo.id, "simulado": simulado.id}
    return ids


class TestCriteriosDeAceite:
    def test_vendedor_recebe_403_em_alerts(self, cliente_auth, alertas, vendedor):
        """Critério: `GET /alerts` com papel vendedor → 403.

        `docs/12` §6.1 diz "Vendedor não vê", e é decisão de produto: o Radar é ferramenta
        de inteligência competitiva, não de conversa de loja.
        """
        resposta = cliente_auth.get(ALERTS, headers=vendedor)
        assert resposta.status_code == 403
        assert resposta.headers["content-type"].startswith("application/problem+json")

    def test_alerta_simulado_chega_marcado(self, cliente_auth, alertas, analista):
        """Critério: `is_simulated=true` viaja na resposta para a tela pintar o rótulo."""
        corpo = cliente_auth.get(ALERTS, headers=analista).json()
        simulado = next(a for a in corpo if a["id"] == alertas["simulado"])
        assert simulado["is_simulated"] is True
        reais = [a for a in corpo if not a["is_simulated"]]
        assert len(reais) == 2

    def test_o_detalhe_traz_impacto_e_as_quatro_reacoes(self, cliente_auth, alertas, analista):
        resposta = cliente_auth.get(f"{ALERTS}/{alertas['preco']}", headers=analista)
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["impact"]["delta"] == -18800
        assert corpo["impact"]["gap_depois"] == 10010
        assert set(corpo["reactions"]) == {"marketing", "vendas", "produto", "ci"}


class TestListagemEFiltros:
    def test_mais_recentes_primeiro(self, cliente_auth, alertas, analista):
        corpo = cliente_auth.get(ALERTS, headers=analista).json()
        datas = [a["created_at"] for a in corpo]
        assert datas == sorted(datas, reverse=True)

    def test_filtra_por_tipo(self, cliente_auth, alertas, analista):
        corpo = cliente_auth.get(f"{ALERTS}?type=preco_oficial", headers=analista).json()
        assert [a["id"] for a in corpo] == [alertas["preco"]]

    def test_tipo_invalido_e_422(self, cliente_auth, alertas, analista):
        """Vocabulário fechado: tipo inventado não devolve lista vazia, devolve erro."""
        resposta = cliente_auth.get(f"{ALERTS}?type=tipo_inventado", headers=analista)
        assert resposta.status_code == 422

    def test_filtra_por_concorrente(self, cliente_auth, alertas, catalogo, analista):
        corpo = cliente_auth.get(f"{ALERTS}?competitor={catalogo['srx']}", headers=analista).json()
        assert [a["id"] for a in corpo] == [alertas["preco"]]

    def test_filtra_por_data(self, cliente_auth, alertas, analista):
        corpo = cliente_auth.get(f"{ALERTS}?since=2026-09-06T00:00:00", headers=analista).json()
        assert len(corpo) == 2

    def test_pode_esconder_os_simulados(self, cliente_auth, alertas, analista):
        """Vêm por padrão (sempre marcados); desligar mostra só o real."""
        corpo = cliente_auth.get(f"{ALERTS}?incluir_simulados=false", headers=analista).json()
        assert all(not a["is_simulated"] for a in corpo)
        assert len(corpo) == 2

    def test_alerta_inexistente_da_404(self, cliente_auth, alertas, analista):
        assert cliente_auth.get(f"{ALERTS}/nao-existe", headers=analista).status_code == 404


class TestMarcacao:
    def test_analista_marca_como_lido(self, cliente_auth, alertas, analista):
        resposta = cliente_auth.patch(
            f"{ALERTS}/{alertas['preco']}", headers=analista, json={"read": True}
        )
        assert resposta.status_code == 200
        assert resposta.json()["lido"] is True

    def test_analista_NAO_marca_como_tratado(self, cliente_auth, alertas, analista):
        """ "Tratado" afirma que alguém resolveu, e a equipe passa a confiar nisso."""
        resposta = cliente_auth.patch(
            f"{ALERTS}/{alertas['preco']}", headers=analista, json={"tratado": True}
        )
        assert resposta.status_code == 403

    def test_gestor_marca_como_tratado_e_fica_no_audit_log(self, cliente_auth, alertas, gestor):
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import AuditLog

        resposta = cliente_auth.patch(
            f"{ALERTS}/{alertas['preco']}", headers=gestor, json={"tratado": True}
        )
        assert resposta.status_code == 200
        assert resposta.json()["tratado"] is True

        with session_scope() as sessao:
            linhas = sessao.exec(select(AuditLog).where(AuditLog.acao == "alerta_tratado")).all()
            assert len(linhas) == 1


class TestReferenciaInterna:
    def test_analista_nao_le_referencia_interna(self, cliente_auth, catalogo, analista):
        """`docs/12` §7: material interno da Ford é **dado sensível**."""
        assert cliente_auth.get(REFERENCIAS, headers=analista).status_code == 403

    def test_vendedor_nao_le_referencia_interna(self, cliente_auth, catalogo, vendedor):
        assert cliente_auth.get(REFERENCIAS, headers=vendedor).status_code == 403

    def test_gestor_sobe_o_csv_e_gera_o_alerta_de_divergencia(self, cliente_auth, catalogo, gestor):
        """O Fogo Amigo com o dado do cliente: 397 na fonte pública, 400 no slide."""
        resposta = cliente_auth.post(
            REFERENCIAS,
            headers=gestor,
            files={"arquivo": ("slide-raptor.csv", CSV_DO_SLIDE, "text/csv")},
        )
        assert resposta.status_code == 201, resposta.text
        corpo = resposta.json()

        assert corpo["importadas"] == 1
        # A linha do campo inexistente é recusada COM O NOME — recusa silenciosa faria o
        # gestor achar que subiu.
        assert any("campo_inexistente" in r for r in corpo["recusadas"])
        assert corpo["alertas_gerados"] == 1
        assert corpo["divergencias"][0]["valor_interno"] == 400
        assert corpo["divergencias"][0]["valor_publico"] == 397

    def test_o_alerta_gerado_e_do_tipo_certo_e_tem_as_duas_pontas(
        self, cliente_auth, catalogo, gestor, analista
    ):
        cliente_auth.post(
            REFERENCIAS,
            headers=gestor,
            files={"arquivo": ("slide.csv", CSV_DO_SLIDE, "text/csv")},
        )
        lista = cliente_auth.get(
            f"{ALERTS}?type=referencia_interna_divergente", headers=analista
        ).json()
        assert len(lista) == 1
        detalhe = cliente_auth.get(f"{ALERTS}/{lista[0]['id']}", headers=analista).json()
        assert (detalhe["old"], detalhe["new"]) == (400, 397)
        assert detalhe["reactions"]["vendas"]
        # A evidência do lado público é a da ficha; a do lado interno é o documento.
        assert detalhe["evidence_after"] is not None

    def test_reimportar_atualiza_em_vez_de_duplicar(self, cliente_auth, catalogo, gestor):
        for _ in range(2):
            cliente_auth.post(
                REFERENCIAS,
                headers=gestor,
                files={"arquivo": ("slide.csv", CSV_DO_SLIDE, "text/csv")},
            )
        corpo = cliente_auth.get(REFERENCIAS, headers=gestor).json()
        assert len([r for r in corpo if r["field"] == "potencia_cv"]) == 1

    def test_versao_desconhecida_e_recusada_com_o_nome(self, cliente_auth, catalogo, gestor):
        resposta = cliente_auth.post(
            REFERENCIAS,
            headers=gestor,
            files={
                "arquivo": (
                    "x.csv",
                    "versao,campo,valor\nPicape Que Nao Existe,potencia_cv,400\n",
                    "text/csv",
                )
            },
        )
        assert resposta.status_code == 201
        assert any("Picape Que Nao Existe" in r for r in resposta.json()["recusadas"])

    def test_arquivo_sem_as_colunas_e_422_com_a_lista(self, cliente_auth, catalogo, gestor):
        resposta = cliente_auth.post(
            REFERENCIAS,
            headers=gestor,
            files={"arquivo": ("x.csv", "coluna_estranha\nvalor\n", "text/csv")},
        )
        assert resposta.status_code == 422
        assert "campo" in resposta.json()["detail"]

    def test_a_referencia_interna_NAO_entra_em_spec_values(self, cliente_auth, catalogo, gestor):
        """A regra que protege o "Fogo Amigo" de se inverter.

        `docs/12` §6.1 diz "linhas viram `spec_values` tier 0". Aqui elas vão para a tabela
        `internal_references`, e a diferença não é de gosto: na ordenação do projeto
        **menor é mais forte** (1 = montadora), então uma linha em `spec_values` com
        `tier=0` venceria o site oficial na hora de montar a ficha — o slide desatualizado
        do cliente passaria a ser o valor exibido, com evidência e tudo.

        A comparação com o valor público continua acontecendo (é o alerta), e o valor
        interno fica guardado e consultável. O que não acontece é ele virar o valor da
        ficha.
        """
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import Evidence, SpecValue

        antes = 0
        with session_scope() as sessao:
            antes = len(sessao.exec(select(SpecValue)).all())

        cliente_auth.post(
            REFERENCIAS,
            headers=gestor,
            files={"arquivo": ("slide.csv", CSV_DO_SLIDE, "text/csv")},
        )

        with session_scope() as sessao:
            assert len(sessao.exec(select(SpecValue)).all()) == antes
            # E nenhuma evidência com tier 0 foi criada por este caminho.
            tiers = [e.tier for e in sessao.exec(select(Evidence)).all()]
            assert 0 not in tiers

    def test_o_modelo_de_csv_diz_o_formato(self, cliente_auth, catalogo, gestor):
        """Formato descoberto por tentativa é formato que gera arquivo recusado."""
        corpo = cliente_auth.get(f"{REFERENCIAS}/modelo.csv", headers=gestor).json()
        assert "versao,campo,valor" in corpo["csv"]
        assert "potencia_cv" in corpo["csv"]


class TestEquivalentes:
    def test_analista_le_a_tabela(self, cliente_auth, catalogo, analista):
        assert cliente_auth.get(EQUIVALENTES, headers=analista).status_code == 200

    def test_analista_nao_cadastra(self, cliente_auth, catalogo, analista):
        """Equivalência é decisão comercial, não cálculo: é do gestor."""
        resposta = cliente_auth.post(
            EQUIVALENTES,
            headers=analista,
            json={"competitor_version_id": catalogo["srx"], "ford_version_id": catalogo["raptor"]},
        )
        assert resposta.status_code == 403

    def test_gestor_cadastra_com_a_nota_do_criterio(self, cliente_auth, catalogo, gestor):
        resposta = cliente_auth.post(
            EQUIVALENTES,
            headers=gestor,
            json={
                "competitor_version_id": catalogo["srx"],
                "ford_version_id": catalogo["raptor"],
                "nota": "mesma faixa de preço e uso",
            },
        )
        assert resposta.status_code == 201
        assert resposta.json()["nota"] == "mesma faixa de preço e uso"

    def test_sem_equivalente_direto_e_afirmacao_legitima(self, cliente_auth, catalogo, gestor):
        """`ford_version_id: null` afirma "não há par" — diferente de não ter cadastrado.

        A Raptor não tem equivalente entre as picapes diesel de trabalho (`docs/12` §6.1),
        e deixar em branco por omissão seria diferente de dizer isso.
        """
        resposta = cliente_auth.post(
            EQUIVALENTES,
            headers=gestor,
            json={
                "competitor_version_id": catalogo["raptor"],
                "ford_version_id": None,
                "nota": "sem par direto: picape de desempenho a gasolina",
            },
        )
        assert resposta.status_code == 201
        assert resposta.json()["ford_version_id"] is None

    def test_versao_inexistente_da_404(self, cliente_auth, catalogo, gestor):
        resposta = cliente_auth.post(
            EQUIVALENTES, headers=gestor, json={"competitor_version_id": "nao-existe"}
        )
        assert resposta.status_code == 404

    def test_versao_equivalente_a_si_mesma_e_422(self, cliente_auth, catalogo, gestor):
        resposta = cliente_auth.post(
            EQUIVALENTES,
            headers=gestor,
            json={
                "competitor_version_id": catalogo["srx"],
                "ford_version_id": catalogo["srx"],
            },
        )
        assert resposta.status_code == 422

    def test_par_repetido_e_409(self, cliente_auth, catalogo, gestor):
        corpo = {
            "competitor_version_id": catalogo["srx"],
            "ford_version_id": catalogo["raptor"],
        }
        assert cliente_auth.post(EQUIVALENTES, headers=gestor, json=corpo).status_code == 201
        assert cliente_auth.post(EQUIVALENTES, headers=gestor, json=corpo).status_code == 409

    def test_o_cadastro_fica_no_audit_log(self, cliente_auth, catalogo, gestor):
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import AuditLog

        cliente_auth.post(
            EQUIVALENTES,
            headers=gestor,
            json={
                "competitor_version_id": catalogo["srx"],
                "ford_version_id": catalogo["raptor"],
            },
        )
        with session_scope() as sessao:
            linhas = sessao.exec(
                select(AuditLog).where(AuditLog.acao == "equivalencia_definida")
            ).all()
            assert len(linhas) == 1


class TestAutenticacao:
    @pytest.mark.parametrize("rota", [ALERTS, REFERENCIAS, EQUIVALENTES])
    def test_sem_credencial_da_401(self, cliente_auth, catalogo, rota):
        assert cliente_auth.get(rota).status_code == 401
