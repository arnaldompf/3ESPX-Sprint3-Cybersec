"""WP-27 — `/showroom-sessions` e `/comparisons/{id}/arguments`.

O critério de aceite que dá o tom: **`POST` com nome ou telefone do cliente recebe 422**.
A recusa é estrutural (`extra="forbid"` no schema), não uma revisão de código — o dia em
que alguém acrescentar o campo, o teste falha antes de o dado existir no banco.

O outro é a **trava do gestor**: argumento travado ganha do template e da reescrita, e a
resposta sai com `aprovado=true` e o selo do Product Marketing.
"""

from __future__ import annotations

import datetime as dt

import pytest

from api.app.models import Role

SESSOES = "/api/v1/showroom-sessions"


@pytest.fixture
def vendedor(criar_usuario, logar):
    criar_usuario("vendedor@suno.example.com", Role.VENDEDOR)
    return logar("vendedor@suno.example.com")


@pytest.fixture
def outro_vendedor(criar_usuario, logar):
    criar_usuario("vendedor2@suno.example.com", Role.VENDEDOR)
    return logar("vendedor2@suno.example.com")


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def gestor(criar_usuario, logar):
    criar_usuario("gestor@suno.example.com", Role.GESTOR)
    return logar("gestor@suno.example.com")


@pytest.fixture
def fichas(catalogo):
    """Ficha nos dois lados: sem valor comparável não há argumento a montar."""
    from api.app.db import session_scope
    from api.app.models import Evidence, SpecValue

    with session_scope() as sessao:
        ford_ev = Evidence(
            source_url="https://www.ford.com.br/ranger-raptor",
            tier=1,
            quote="Potência 397 cv",
            captured_at=dt.datetime(2026, 9, 1),
        )
        conc_ev = Evidence(
            source_url="https://www.toyota.com.br/hilux",
            tier=1,
            quote="204 cv",
            captured_at=dt.datetime(2026, 9, 1),
        )
        sessao.add(ford_ev)
        sessao.add(conc_ev)
        sessao.flush()

        for version_id, evidencia, linhas in (
            (
                catalogo["raptor"],
                ford_ev,
                [
                    ("potencia_cv", 397, "cv"),
                    ("torque_nm", 583, "Nm"),
                    ("capacidade_carga_kg", 620, "kg"),
                    ("capacidade_reboque_kg", 2500, "kg"),
                    ("camera_360", True, None),
                ],
            ),
            (
                catalogo["srx"],
                conc_ev,
                [
                    ("potencia_cv", 204, "cv"),
                    ("torque_nm", 500, "Nm"),
                    ("capacidade_carga_kg", 1005, "kg"),
                    ("capacidade_reboque_kg", 3500, "kg"),
                    ("camera_360", False, None),
                ],
            ),
        ):
            for campo, valor, unidade in linhas:
                sessao.add(
                    SpecValue(
                        version_id=version_id,
                        field=campo,
                        value_json=valor,
                        unit=unidade,
                        status="verificado",
                        confidence=0.95,
                        evidence_id=evidencia.id,
                    )
                )
        sessao.commit()
    return catalogo


def par(catalogo) -> str:
    return f"{catalogo['raptor']}:{catalogo['srx']}"


def argumentos(cliente, headers, catalogo, **corpo):
    return cliente.post(
        f"/api/v1/comparisons/{par(catalogo)}/arguments", headers=headers, json=corpo
    )


class TestSemPII:
    def test_criterio_de_aceite_nome_do_cliente_e_422(self, cliente_auth, fichas, vendedor):
        """Critério: `POST` com campo de nome/telefone → 422 (schema não aceita PII)."""
        resposta = cliente_auth.post(
            SESSOES,
            headers=vendedor,
            json={
                "ford_version_id": fichas["raptor"],
                "competitor_version_ids": [fichas["srx"]],
                "nome_do_cliente": "João da Silva",
            },
        )
        assert resposta.status_code == 422

    @pytest.mark.parametrize(
        "campo", ["telefone", "email", "cpf", "whatsapp", "observacoes", "cliente"]
    )
    def test_qualquer_campo_extra_e_422(self, cliente_auth, fichas, vendedor, campo):
        """A recusa é do schema, não de uma lista de campos proibidos.

        `extra="forbid"` recusa **tudo** o que não está declarado — inclusive o campo que
        alguém inventar amanhã, que é o caso que uma lista de proibidos não pegaria.
        """
        resposta = cliente_auth.post(
            SESSOES,
            headers=vendedor,
            json={"ford_version_id": fichas["raptor"], campo: "qualquer coisa"},
        )
        assert resposta.status_code == 422

    def test_a_tabela_nao_tem_coluna_de_pii(self):
        """Defesa em profundidade: se o schema falhar, não há onde gravar."""
        from api.app.models import ShowroomSession

        colunas = set(ShowroomSession.model_fields)
        for proibida in ("nome", "telefone", "email", "cpf", "cliente", "observacoes"):
            assert not any(proibida in c for c in colunas), colunas


class TestCicloDaSessao:
    def test_cria_com_o_vendedor_do_TOKEN(self, cliente_auth, fichas, vendedor):
        """Deixar o corpo informar quem atendeu permitiria registrar no nome de outro."""
        resposta = cliente_auth.post(
            SESSOES,
            headers=vendedor,
            json={
                "ford_version_id": fichas["raptor"],
                "competitor_version_ids": [fichas["srx"]],
                "comparison_id": par(fichas),
            },
        )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["vendedor_id"]
        assert corpo["outcome"] == "em_andamento"
        assert corpo["is_simulated"] is False

    def test_fecha_em_tres_toques(self, cliente_auth, fichas, vendedor):
        criada = cliente_auth.post(
            SESSOES,
            headers=vendedor,
            json={"ford_version_id": fichas["raptor"], "competitor_version_ids": [fichas["srx"]]},
        ).json()
        resposta = cliente_auth.patch(
            f"{SESSOES}/{criada['id']}",
            headers=vendedor,
            json={
                "outcome": "perdeu",
                "motivos": ["preco", "prazo_entrega"],
                "atributo_decisivo": "preco_sugerido_brl",
            },
        )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["outcome"] == "perdeu"
        assert corpo["motivos"] == ["preco", "prazo_entrega"]
        assert corpo["updated_at"]

    def test_desfecho_fora_do_vocabulario_e_422(self, cliente_auth, fichas, vendedor):
        resposta = cliente_auth.post(
            SESSOES,
            headers=vendedor,
            json={"ford_version_id": fichas["raptor"], "outcome": "quase_fechou"},
        )
        assert resposta.status_code == 422

    def test_motivo_fora_do_vocabulario_e_422_com_a_lista(self, cliente_auth, fichas, vendedor):
        """Motivo em texto livre viraria trinta variações de "preço" e o painel não agruparia."""
        resposta = cliente_auth.post(
            SESSOES,
            headers=vendedor,
            json={"ford_version_id": fichas["raptor"], "motivos": ["achou_caro"]},
        )
        assert resposta.status_code == 422
        assert "preco" in resposta.text

    def test_versao_inexistente_da_404(self, cliente_auth, fichas, vendedor):
        resposta = cliente_auth.post(
            SESSOES, headers=vendedor, json={"ford_version_id": "nao-existe"}
        )
        assert resposta.status_code == 404


class TestEscopoDoVendedor:
    def test_vendedor_ve_so_as_proprias(self, cliente_auth, fichas, vendedor, outro_vendedor):
        cliente_auth.post(SESSOES, headers=vendedor, json={"ford_version_id": fichas["raptor"]})
        cliente_auth.post(
            SESSOES, headers=outro_vendedor, json={"ford_version_id": fichas["raptor"]}
        )
        minhas = cliente_auth.get(SESSOES, headers=vendedor).json()
        assert len(minhas) == 1

    def test_analista_ve_todas_mas_NAO_cria(
        self, cliente_auth, fichas, vendedor, outro_vendedor, analista
    ):
        """Pela matriz de `docs/12` §6.6 o analista não atende no salão, mas usa os dados.

        Por isso **ler** é `ver_insights` e **criar** é `criar_sessao_showroom`: exigir a
        ação de criar para listar barraria justamente quem consome a informação.
        """
        assert (
            cliente_auth.post(
                SESSOES, headers=analista, json={"ford_version_id": fichas["raptor"]}
            ).status_code
            == 403
        )
        self._ve_todas(cliente_auth, fichas, vendedor, outro_vendedor, analista)

    def _ve_todas(self, cliente_auth, fichas, vendedor, outro_vendedor, analista):
        cliente_auth.post(SESSOES, headers=vendedor, json={"ford_version_id": fichas["raptor"]})
        cliente_auth.post(
            SESSOES, headers=outro_vendedor, json={"ford_version_id": fichas["raptor"]}
        )
        todas = cliente_auth.get(SESSOES, headers=analista).json()
        assert len(todas) == 2

    def test_vendedor_nao_altera_sessao_de_outro(
        self, cliente_auth, fichas, vendedor, outro_vendedor
    ):
        do_outro = cliente_auth.post(
            SESSOES, headers=outro_vendedor, json={"ford_version_id": fichas["raptor"]}
        ).json()
        resposta = cliente_auth.patch(
            f"{SESSOES}/{do_outro['id']}", headers=vendedor, json={"outcome": "fechou"}
        )
        assert resposta.status_code == 403

    def test_sessao_simulada_nao_e_editavel(self, cliente_auth, fichas, gestor):
        """Editá-la faria o painel misturar dado semeado com dado de uso."""
        from api.app.db import session_scope
        from api.app.models import ShowroomSession

        with session_scope() as sessao:
            linha = ShowroomSession(
                ford_version_id=fichas["raptor"],
                competitor_version_ids=[fichas["srx"]],
                outcome="fechou",
                is_simulated=True,
            )
            sessao.add(linha)
            sessao.commit()
            simulada_id = linha.id

        # Gestor e não analista: pela matriz, quem **altera** sessão é quem pode criá-la.
        resposta = cliente_auth.patch(
            f"{SESSOES}/{simulada_id}", headers=gestor, json={"outcome": "perdeu"}
        )
        assert resposta.status_code == 422
        assert "demonstração" in resposta.json()["detail"]

    def test_sem_credencial_da_401(self, cliente_auth, fichas):
        assert cliente_auth.get(SESSOES).status_code == 401
        assert cliente_auth.post(SESSOES, json={"ford_version_id": "x"}).status_code == 401


class TestArgumentario:
    def test_tres_pontos_mais_um_do_concorrente_com_evidencia(self, cliente_auth, fichas, vendedor):
        corpo = argumentos(
            cliente_auth,
            vendedor,
            fichas,
            needs_profile={"prioridades_rank": ["desempenho", "seguranca", "capacidade"]},
        ).json()
        assert len(corpo["pontos"]) >= 1
        assert corpo["ponto_forte_concorrente"] is not None
        for fontes in corpo["fonte_por_ponto"]:
            assert len(fontes) == 2

    def test_o_caminho_padrao_e_o_template(self, cliente_auth, fichas, vendedor):
        """Sem fixture de LLM, `gerado_por="template"` — e é o caminho da demo."""
        corpo = argumentos(cliente_auth, vendedor, fichas, permitir_llm=False).json()
        assert corpo["gerado_por"] == "template"
        assert corpo["reescrita"]["gerado_por"] == "template"

    def test_par_invalido_e_422_com_o_formato(self, cliente_auth, fichas, vendedor):
        resposta = cliente_auth.post(
            "/api/v1/comparisons/sem-separador/arguments", headers=vendedor, json={}
        )
        assert resposta.status_code == 422
        assert "fordVersionId" in resposta.json()["detail"]

    def test_versao_inexistente_no_par_da_404(self, cliente_auth, fichas, vendedor):
        resposta = cliente_auth.post(
            f"/api/v1/comparisons/{fichas['raptor']}:nao-existe/arguments",
            headers=vendedor,
            json={},
        )
        assert resposta.status_code == 404

    def test_par_com_a_mesma_versao_e_422(self, cliente_auth, fichas, vendedor):
        resposta = cliente_auth.post(
            f"/api/v1/comparisons/{fichas['raptor']}:{fichas['raptor']}/arguments",
            headers=vendedor,
            json={},
        )
        assert resposta.status_code == 422

    def test_sem_perfil_o_argumentario_sai_com_os_avisos(self, cliente_auth, fichas, vendedor):
        """Priorizar por conta própria seria decidir o que importa para um cliente que
        ninguém entrevistou."""
        corpo = argumentos(cliente_auth, vendedor, fichas).json()
        assert corpo["pesos"]
        assert all(peso == 0 for peso in corpo["pesos"].values())


class TestGovernancaDoArgumentario:
    def test_vendedor_nao_aprova(self, cliente_auth, fichas, vendedor):
        resposta = cliente_auth.put(
            f"/api/v1/comparisons/{par(fichas)}/arguments",
            headers=vendedor,
            json={"aprovado": True},
        )
        assert resposta.status_code == 403

    def test_gestor_aprova_e_a_resposta_ganha_o_selo(self, cliente_auth, fichas, gestor, vendedor):
        aprovacao = cliente_auth.put(
            f"/api/v1/comparisons/{par(fichas)}/arguments",
            headers=gestor,
            json={"aprovado": True, "nota": "revisado pelo PMM"},
        )
        assert aprovacao.status_code == 200
        assert aprovacao.json()["selo"] == "aprovado pelo Product Marketing"

        corpo = argumentos(cliente_auth, vendedor, fichas).json()
        assert corpo["aprovado"] is True
        assert corpo["selo"] == "aprovado pelo Product Marketing"

    def test_criterio_de_aceite_travado_ganha_do_template(
        self, cliente_auth, fichas, gestor, vendedor
    ):
        """Critério: gestor trava → a resposta usa o texto travado e `aprovado=true`."""
        travado = ["Texto travado pelo Product Marketing para esta campanha."]
        cliente_auth.put(
            f"/api/v1/comparisons/{par(fichas)}/arguments",
            headers=gestor,
            json={"aprovado": True, "travado": True, "textos": travado},
        )
        corpo = argumentos(cliente_auth, vendedor, fichas).json()
        assert corpo["aprovado"] is True
        assert corpo["travado"] is True
        assert corpo["gerado_por"] == "travado_pelo_gestor"
        assert corpo["pontos"][0]["texto"] == travado[0]

    def test_travar_sem_texto_e_422(self, cliente_auth, fichas, gestor):
        """Seria "trave o que o sistema gerar", que é o contrário de travar."""
        resposta = cliente_auth.put(
            f"/api/v1/comparisons/{par(fichas)}/arguments",
            headers=gestor,
            json={"travado": True},
        )
        assert resposta.status_code == 422

    def test_aprovar_duas_vezes_atualiza_em_vez_de_duplicar(self, cliente_auth, fichas, gestor):
        primeira = cliente_auth.put(
            f"/api/v1/comparisons/{par(fichas)}/arguments",
            headers=gestor,
            json={"aprovado": True},
        ).json()
        segunda = cliente_auth.put(
            f"/api/v1/comparisons/{par(fichas)}/arguments",
            headers=gestor,
            json={"aprovado": False},
        ).json()
        assert primeira["id"] == segunda["id"]
        assert segunda["aprovado"] is False

    def test_a_aprovacao_fica_no_audit_log(self, cliente_auth, fichas, gestor):
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import AuditLog

        cliente_auth.put(
            f"/api/v1/comparisons/{par(fichas)}/arguments",
            headers=gestor,
            json={"aprovado": True},
        )
        with session_scope() as sessao:
            linhas = sessao.exec(
                select(AuditLog).where(AuditLog.acao == "argumento_aprovado")
            ).all()
            assert len(linhas) == 1
