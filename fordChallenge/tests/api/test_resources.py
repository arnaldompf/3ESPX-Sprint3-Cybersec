"""WP-06 — os recursos REST de `docs/04`: sucesso, 404, 422 e 401/403 em cada um.

Os três critérios de aceite estão em `TestCriteriosDeAceite`. O resto cobre o contrato
recurso por recurso, e dois comportamentos que são decisão de produto e não detalhe:

* `POST /resolutions` responde **200** para `versao_inexistente` — o cliente perguntou
  certo, e a resposta é que a versão saiu de linha;
* `POST /attributes/resolve` responde **200 com `extra_slug`** para termo desconhecido, em
  vez de 404 — a pergunta do usuário não é descartada.
"""

from __future__ import annotations

import datetime as dt

import pytest

from api.app.models import Role

BRANDS = "/api/v1/brands"
VEHICLES = "/api/v1/vehicles"
EXTRACTIONS = "/api/v1/extractions"
ATTRIBUTES = "/api/v1/attributes"
RESOLUTIONS = "/api/v1/resolutions"
COMPARISONS = "/api/v1/comparisons"
ALERTS = "/api/v1/alerts"
SOURCES = "/api/v1/sources"


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def vendedor(criar_usuario, logar):
    criar_usuario("vendedor@suno.example.com", Role.VENDEDOR)
    return logar("vendedor@suno.example.com")


@pytest.fixture
def admin(criar_usuario, logar):
    criar_usuario("admin@suno.example.com", Role.ADMIN)
    return logar("admin@suno.example.com")


class TestCriteriosDeAceite:
    def test_post_extractions_da_202_com_location_e_job_na_fila(
        self, cliente_auth, catalogo, analista
    ):
        """Critério: 202, `Location` para `/jobs/{id}`, job em fila."""
        resposta = cliente_auth.post(
            EXTRACTIONS,
            headers=analista,
            json={"marca": "Ford", "modelo": "Ranger", "versao": "Raptor 3.0 V6"},
        )
        assert resposta.status_code == 202
        corpo = resposta.json()
        assert resposta.headers["Location"] == f"/api/v1/jobs/{corpo['job_id']}"
        assert corpo["status"] == "pendente"

        job = cliente_auth.get(f"/api/v1/jobs/{corpo['job_id']}", headers=analista)
        assert job.status_code == 200
        assert job.json()["status"] == "pendente"

    def test_specs_com_filtro_mantem_os_outros_campos_com_status(
        self, cliente_auth, catalogo, analista
    ):
        """Critério: `?attributes=potencia_cv` filtra **valores**, não campos.

        Omitir os campos mudaria o significado da resposta: quem lê um JSON sem
        `torque_nm` não sabe se o torque não existe, não foi encontrado, ou ninguém
        perguntou.
        """
        resposta = cliente_auth.get(
            f"{VEHICLES}/{catalogo['raptor']}/specs?attributes=potencia_cv", headers=analista
        )
        assert resposta.status_code == 200
        ficha = resposta.json()

        assert ficha["motorizacao"]["potencia_cv"]["value"] == 397
        # O torque existe no banco, mas não foi pedido: presente, sem valor, e dizendo.
        torque = ficha["motorizacao"]["torque_nm"]
        assert torque["value"] is None
        assert torque["status"] == "nao_verificado"
        assert "não solicitado" in torque["notes"]
        # E os campos de outros grupos também estão lá.
        assert "tipo" in ficha["transmissao"]

    def test_attributes_resolve_cavalos_da_potencia_cv(self, cliente_auth, analista):
        """Critério: `{"text": "cavalos"}` → `canonical="potencia_cv"`."""
        resposta = cliente_auth.post(
            f"{ATTRIBUTES}/resolve", headers=analista, json={"text": "cavalos"}
        )
        assert resposta.status_code == 200
        assert resposta.json()["canonical"] == "potencia_cv"


class TestCatalogo:
    def test_lista_marcas(self, cliente_auth, catalogo, analista):
        nomes = [m["nome"] for m in cliente_auth.get(BRANDS, headers=analista).json()]
        assert nomes == ["Ford", "Toyota"]

    def test_modelos_de_marca_inexistente_da_404(self, cliente_auth, catalogo, analista):
        assert cliente_auth.get(f"{BRANDS}/nao-existe/models", headers=analista).status_code == 404

    def test_lineup_current_exclui_e_CONTA_a_versao_sem_checagem(
        self, cliente_auth, catalogo, analista
    ):
        """Omissão nunca é silenciosa: a resposta diz quantas ficaram de fora e por quê."""
        resposta = cliente_auth.get(
            f"/api/v1/models/{catalogo['model_hilux']}/versions?lineup=current", headers=analista
        )
        corpo = resposta.json()
        assert [v["nome_exato"] for v in corpo["versions"]] == ["SRX Plus AT (Cabine Dupla)"]
        assert corpo["sem_checagem_de_linha"] == 1

    def test_sem_filtro_traz_tudo(self, cliente_auth, catalogo, analista):
        resposta = cliente_auth.get(
            f"/api/v1/models/{catalogo['model_hilux']}/versions", headers=analista
        )
        assert resposta.json()["total"] == 2

    def test_a_data_da_checagem_viaja_com_o_in_lineup(self, cliente_auth, catalogo, analista):
        """`in_lineup` sem `lineup_checked_at` é afirmação sem validade."""
        versoes = cliente_auth.get(
            f"/api/v1/models/{catalogo['model_hilux']}/versions", headers=analista
        ).json()["versions"]
        na_linha = next(v for v in versoes if v["in_lineup"])
        assert na_linha["lineup_checked_at"] is not None


class TestVeiculos:
    def test_lista_e_filtra_por_marca(self, cliente_auth, catalogo, analista):
        resposta = cliente_auth.get(f"{VEHICLES}?marca=Ford", headers=analista)
        assert [v["modelo"] for v in resposta.json()] == ["Ranger"]

    def test_um_veiculo_traz_marca_e_modelo_resolvidos(self, cliente_auth, catalogo, analista):
        corpo = cliente_auth.get(f"{VEHICLES}/{catalogo['raptor']}", headers=analista).json()
        assert (corpo["marca"], corpo["modelo"]) == ("Ford", "Ranger")

    def test_veiculo_inexistente_da_404(self, cliente_auth, catalogo, analista):
        assert cliente_auth.get(f"{VEHICLES}/nao-existe", headers=analista).status_code == 404

    def test_specs_de_veiculo_inexistente_da_404(self, cliente_auth, catalogo, analista):
        assert cliente_auth.get(f"{VEHICLES}/nao-existe/specs", headers=analista).status_code == 404

    def test_specs_sem_valor_gravado_devolve_ficha_vazia_e_nao_404(
        self, cliente_auth, catalogo, analista
    ):
        """Versão sem extração é ficha vazia, não erro: é a resposta honesta."""
        resposta = cliente_auth.get(f"{VEHICLES}/{catalogo['srx']}/specs", headers=analista)
        assert resposta.status_code == 200
        ficha = resposta.json()
        assert ficha["motorizacao"]["potencia_cv"]["value"] is None
        assert ficha["motorizacao"]["potencia_cv"]["status"] == "nao_encontrado"

    def test_a_evidencia_viaja_na_ficha(self, cliente_auth, catalogo, analista):
        ficha = cliente_auth.get(f"{VEHICLES}/{catalogo['raptor']}/specs", headers=analista).json()
        evidencias = ficha["motorizacao"]["potencia_cv"]["evidences"]
        assert evidencias and evidencias[0]["quote"] == "Potência 397cv"
        assert evidencias[0]["tier"] == 1

    def test_validacao_edital_conta_o_que_o_slide_pede_e_explica_o_vazio(
        self, cliente_auth, catalogo, analista
    ):
        from pipeline.schema import CAMPOS_VALIDACAO_EDITAL

        resposta = cliente_auth.get(
            f"{VEHICLES}/{catalogo['raptor']}/validacao-edital", headers=analista
        )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["total"] == len(CAMPOS_VALIDACAO_EDITAL)
        assert "potencia_cv" in corpo["campos_achados"]
        assert corpo["achados"] == len(corpo["campos_achados"])
        assert corpo["com_valor"] == corpo["achados"]
        assert corpo["respondidos"] == corpo["com_valor"] + corpo["vazio_justificado"]
        assert corpo["sem_resposta"] == corpo["total"] - corpo["respondidos"]
        for vazio in corpo["campos_vazios"]:
            assert vazio["status"] in ("nao_encontrado", "nao_disponivel", "nao_verificado")
            assert isinstance(vazio["vazio_justificado"], bool)
            assert isinstance(vazio["sources_checked"], list)

    def test_validacao_edital_de_veiculo_inexistente_da_404(self, cliente_auth, analista):
        resposta = cliente_auth.get(f"{VEHICLES}/nao-existe/validacao-edital", headers=analista)
        assert resposta.status_code == 404


class TestIdentificacaoVemDoCatalogo:
    """O cabeçalho da Ficha mostra marca, modelo, versão, ano e FIPE; o bloco
    Identificação, logo abaixo, dizia "não encontrado nas fontes" nos **mesmos** campos.

    A causa: `spec_assembler.montar` partia da ficha vazia e lia só `spec_values`. Não
    havia JOIN nenhum com `versions`/`models`/`brands` — o catálogo, que a mesma tela já
    exibia no topo, nunca chegava ao grupo. Achado por um avaliador em 12/09/2026.

    A correção é no back, e não no front, porque `montar` alimenta também a Matriz, a
    paridade, o Radar e o motor de aderência: um remendo na Ficha consertaria uma tela e
    deixaria quatro consumidores errados — além do JSON e do PDF.
    """

    def test_identificacao_traz_marca_modelo_versao_ano_e_fipe(
        self, cliente_auth, catalogo, analista
    ):
        ficha = cliente_auth.get(f"{VEHICLES}/{catalogo['raptor']}/specs", headers=analista).json()
        ident = ficha["identificacao"]
        assert ident["marca"]["value"] == "Ford"
        assert ident["modelo"]["value"] == "Ranger"
        assert ident["versao"]["value"] == "Raptor 3.0 V6 Bi-turbo 4WD AT"
        assert ident["ano_modelo"]["value"] == 2026
        assert ident["codigo_fipe"]["value"] == "003506-8"
        for campo in ("marca", "modelo", "versao", "ano_modelo", "codigo_fipe"):
            assert ident[campo]["status"] != "nao_encontrado", campo
            assert ident[campo]["origem"] == "catalogo", campo
            # A nota diz de onde veio, e por quê. Sem ela, "catálogo" é só uma palavra.
            assert ident[campo]["notes"], campo

    def test_o_catalogo_preenche_mas_nunca_inventa(self, cliente_auth, catalogo, analista):
        """Contra-teste. A SRX Plus não tem `codigo_fipe` no catálogo: o campo continua
        vazio, e o vazio continua sendo `nao_encontrado`. Preencher com o catálogo não
        pode virar "preencher de qualquer jeito"."""
        ficha = cliente_auth.get(f"{VEHICLES}/{catalogo['srx']}/specs", headers=analista).json()
        fipe = ficha["identificacao"]["codigo_fipe"]
        assert fipe["value"] is None
        assert fipe["status"] == "nao_encontrado"
        assert fipe["origem"] is None

    def test_valor_extraido_pelo_pipeline_ganha_do_catalogo(self, cliente_auth, catalogo, analista):
        """Se o pipeline provou o campo com evidência, o catálogo não sobrescreve.

        A hierarquia é a do produto: evidência de fonte vence identidade interna.
        """
        from api.app.db import session_scope
        from api.app.models import Evidence, SpecValue

        with session_scope() as sessao:
            evidencia = Evidence(
                source_url="https://www.ford.com.br/picapes/ranger-raptor/",
                tier=1,
                quote="Ranger Raptor 2027",
                captured_at=dt.datetime(2026, 9, 1),
            )
            sessao.add(evidencia)
            sessao.flush()
            sessao.add(
                SpecValue(
                    version_id=catalogo["raptor"],
                    field="ano_modelo",
                    value_json=2027,
                    status="verificado",
                    confidence=0.95,
                    evidence_id=evidencia.id,
                )
            )
            sessao.commit()

        ident = cliente_auth.get(f"{VEHICLES}/{catalogo['raptor']}/specs", headers=analista).json()[
            "identificacao"
        ]
        assert ident["ano_modelo"]["value"] == 2027
        assert ident["ano_modelo"]["status"] == "verificado"
        assert ident["ano_modelo"]["origem"] is None

    def test_o_filtro_de_atributos_continua_mandando(self, cliente_auth, catalogo, analista):
        """O catálogo preenche o que a pessoa pediu, e nada além."""
        ficha = cliente_auth.get(
            f"{VEHICLES}/{catalogo['raptor']}/specs?attributes=marca", headers=analista
        ).json()
        assert ficha["identificacao"]["marca"]["value"] == "Ford"
        assert ficha["identificacao"]["modelo"]["value"] is None


class TestResolucoes:
    def test_versao_inexistente_responde_200_e_nao_404(self, cliente_auth, analista):
        """Não é erro do cliente: a resposta é que a versão saiu de linha.

        Um 404 faria a tela dizer "não encontrado" onde o produto tem algo melhor a
        dizer — "saiu de linha; a atual é a SRX Plus".
        """
        resposta = cliente_auth.post(
            RESOLUTIONS,
            headers=analista,
            json={"marca": "Toyota", "modelo": "Hilux", "versao": "GR-Sport"},
        )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["status"] == "versao_inexistente"
        assert corpo["alternatives"]

    def test_versao_existente_resolve(self, cliente_auth, analista):
        resposta = cliente_auth.post(
            RESOLUTIONS,
            headers=analista,
            json={"marca": "Toyota", "modelo": "Hilux", "versao": "SRX Plus AT"},
        )
        assert resposta.json()["status"] == "encontrada"

    def test_corpo_incompleto_e_422(self, cliente_auth, analista):
        resposta = cliente_auth.post(RESOLUTIONS, headers=analista, json={"marca": "Ford"})
        assert resposta.status_code == 422


class TestAtributos:
    def test_lista_os_58_campos_canonicos(self, cliente_auth, analista):
        from pipeline.schema import GRUPOS

        corpo = cliente_auth.get(ATTRIBUTES, headers=analista).json()
        assert len(corpo) == sum(len(c) for c in GRUPOS.values())
        assert all("." in a["caminho"] for a in corpo)

    def test_termo_desconhecido_vira_extra_slug_e_nao_404(self, cliente_auth, analista):
        resposta = cliente_auth.post(
            f"{ATTRIBUTES}/resolve",
            headers=analista,
            json={"text": "cor do forro do porta-malas"},
        )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["canonical"] is None
        assert corpo["extra_slug"].startswith("extras.")

    def test_texto_vazio_e_422(self, cliente_auth, analista):
        assert (
            cliente_auth.post(
                f"{ATTRIBUTES}/resolve", headers=analista, json={"text": ""}
            ).status_code
            == 422
        )


class TestExtracoes:
    def test_idempotencia_por_versao_e_dia(self, cliente_auth, catalogo, analista):
        """Duplo clique não pode custar duas coletas.

        Coleta gasta cota de site e dinheiro de LLM; o mesmo pedido no mesmo dia devolve
        o mesmo job.
        """
        corpo = {"marca": "Ford", "modelo": "Ranger", "versao": "Raptor 3.0 V6"}
        primeiro = cliente_auth.post(EXTRACTIONS, headers=analista, json=corpo).json()
        segundo = cliente_auth.post(EXTRACTIONS, headers=analista, json=corpo).json()
        assert segundo["job_id"] == primeiro["job_id"]
        assert segundo["reaproveitado"] is True

    def test_force_refresh_cria_job_novo(self, cliente_auth, catalogo, analista):
        corpo = {"marca": "Ford", "modelo": "Ranger", "versao": "Raptor 3.0 V6"}
        primeiro = cliente_auth.post(EXTRACTIONS, headers=analista, json=corpo).json()
        segundo = cliente_auth.post(
            EXTRACTIONS, headers=analista, json={**corpo, "force_refresh": True}
        ).json()
        assert segundo["job_id"] != primeiro["job_id"]

    def test_vendedor_nao_cria_extracao(self, cliente_auth, catalogo, vendedor):
        """Matriz de `docs/12` §6.6: criar extração é de analista para cima."""
        resposta = cliente_auth.post(
            EXTRACTIONS,
            headers=vendedor,
            json={"marca": "Ford", "modelo": "Ranger", "versao": "Raptor"},
        )
        assert resposta.status_code == 403

    def test_from_image_aceita_png_e_devolve_202(self, cliente_auth, catalogo, analista):
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        resposta = cliente_auth.post(
            f"{EXTRACTIONS}/from-image",
            headers=analista,
            files={"image": ("ficha.png", png, "image/png")},
            data={"marca": "Ford"},
        )
        assert resposta.status_code == 202
        assert resposta.headers["Location"].startswith("/api/v1/jobs/")

    def test_from_image_recusa_tipo_estranho(self, cliente_auth, catalogo, analista):
        resposta = cliente_auth.post(
            f"{EXTRACTIONS}/from-image",
            headers=analista,
            files={"image": ("script.sh", b"rm -rf /", "application/x-sh")},
        )
        assert resposta.status_code == 422

    def test_from_image_recusa_arquivo_vazio(self, cliente_auth, catalogo, analista):
        resposta = cliente_auth.post(
            f"{EXTRACTIONS}/from-image",
            headers=analista,
            files={"image": ("vazio.png", b"", "image/png")},
        )
        assert resposta.status_code == 422

    def test_o_nome_enviado_nao_vira_caminho_no_disco(self, cliente_auth, catalogo, analista):
        """Nome de arquivo vindo de fora é o vetor clássico de escrita fora do diretório.

        O arquivo é gravado com o sha256 do **conteúdo**; o nome enviado fica registrado
        como dado, no payload do job.
        """
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import Job

        cliente_auth.post(
            f"{EXTRACTIONS}/from-image",
            headers=analista,
            files={"image": ("../../etc/passwd.png", b"\x89PNG" + b"0" * 32, "image/png")},
        )
        with session_scope() as sessao:
            job = sessao.exec(select(Job).where(Job.tipo == "extract_from_image")).first()
            arquivo = job.payload["arquivo"]
            enviado = job.payload["nome_enviado"]
        assert ".." not in arquivo and "/" not in arquivo
        assert enviado == "../../etc/passwd.png"


class TestJobs:
    def test_job_inexistente_da_404(self, cliente_auth, catalogo, analista):
        assert cliente_auth.get("/api/v1/jobs/nao-existe", headers=analista).status_code == 404

    def test_job_de_outro_usuario_da_403(
        self, cliente_auth, catalogo, analista, criar_usuario, logar
    ):
        job_id = cliente_auth.post(
            EXTRACTIONS,
            headers=analista,
            json={"marca": "Ford", "modelo": "Ranger", "versao": "Raptor"},
        ).json()["job_id"]

        criar_usuario("outro@suno.example.com", Role.ANALISTA)
        outro = logar("outro@suno.example.com")
        assert cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=outro).status_code == 403

    def test_gestor_ve_job_de_qualquer_um(
        self, cliente_auth, catalogo, analista, criar_usuario, logar
    ):
        job_id = cliente_auth.post(
            EXTRACTIONS,
            headers=analista,
            json={"marca": "Ford", "modelo": "Ranger", "versao": "Raptor"},
        ).json()["job_id"]

        criar_usuario("gestor@suno.example.com", Role.GESTOR)
        gestor = logar("gestor@suno.example.com")
        assert cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=gestor).status_code == 200


class TestComparacoes:
    def test_matriz_marca_diff_quando_um_lado_esta_vazio(self, cliente_auth, catalogo, analista):
        """ "O concorrente tem e nós não sabemos" é tão acionável quanto uma diferença."""
        resposta = cliente_auth.post(
            COMPARISONS,
            headers=analista,
            json={
                "base_vehicle_id": catalogo["raptor"],
                "competitor_ids": [catalogo["srx"]],
                "attributes": ["potencia_cv"],
            },
        )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["attributes"] == ["potencia_cv"]
        base, concorrente = corpo["cells"][0]
        assert base["value"] == 397 and base["diff"] is False
        # A SRX não tem potência gravada: vazio contra 397 é diferença.
        assert concorrente["value"] is None and concorrente["diff"] is True

    def test_veiculo_inexistente_da_404(self, cliente_auth, catalogo, analista):
        resposta = cliente_auth.post(
            COMPARISONS,
            headers=analista,
            json={"base_vehicle_id": catalogo["raptor"], "competitor_ids": ["nao-existe"]},
        )
        assert resposta.status_code == 404

    def test_base_entre_os_concorrentes_e_422(self, cliente_auth, catalogo, analista):
        resposta = cliente_auth.post(
            COMPARISONS,
            headers=analista,
            json={
                "base_vehicle_id": catalogo["raptor"],
                "competitor_ids": [catalogo["raptor"]],
            },
        )
        assert resposta.status_code == 422

    def test_lista_de_concorrentes_vazia_e_422(self, cliente_auth, catalogo, analista):
        resposta = cliente_auth.post(
            COMPARISONS,
            headers=analista,
            json={"base_vehicle_id": catalogo["raptor"], "competitor_ids": []},
        )
        assert resposta.status_code == 422


class TestEvidenciasESnapshots:
    def test_analista_le_evidencia(self, cliente_auth, catalogo, analista):
        resposta = cliente_auth.get(f"/api/v1/evidences/{catalogo['evidencia']}", headers=analista)
        assert resposta.status_code == 200
        assert resposta.json()["quote"] == "Potência 397cv"

    def test_vendedor_nao_le_evidencia_bruta(self, cliente_auth, catalogo, vendedor):
        """O vendedor vê fonte e data na ficha; o texto capturado é material de auditoria."""
        resposta = cliente_auth.get(f"/api/v1/evidences/{catalogo['evidencia']}", headers=vendedor)
        assert resposta.status_code == 403

    def test_evidencia_inexistente_da_404(self, cliente_auth, catalogo, analista):
        assert cliente_auth.get("/api/v1/evidences/nao-existe", headers=analista).status_code == 404

    def test_snapshot_inexistente_da_404(self, cliente_auth, catalogo, analista):
        assert cliente_auth.get("/api/v1/snapshots/nao-existe", headers=analista).status_code == 404


class TestAlertas:
    @pytest.fixture
    def alerta(self, catalogo):
        from api.app.db import session_scope
        from api.app.models import Alert

        with session_scope() as sessao:
            linha = Alert(
                type="preco",
                version_id=catalogo["raptor"],
                field="preco_sugerido_brl",
                old=499000,
                new=512000,
            )
            sessao.add(linha)
            sessao.commit()
            sessao.refresh(linha)
            return linha.id

    def test_lista_alertas(self, cliente_auth, alerta, analista):
        corpo = cliente_auth.get(ALERTS, headers=analista).json()
        assert len(corpo) == 1
        assert (corpo[0]["old"], corpo[0]["new"]) == (499000, 512000)

    def test_analista_marca_como_lido(self, cliente_auth, alerta, analista):
        resposta = cliente_auth.patch(f"{ALERTS}/{alerta}", headers=analista, json={"read": True})
        assert resposta.status_code == 200
        assert resposta.json()["lido"] is True

    def test_analista_nao_marca_como_tratado(self, cliente_auth, alerta, analista):
        """ "Tratado" afirma que a divergência foi resolvida — e a equipe confia nisso."""
        resposta = cliente_auth.patch(
            f"{ALERTS}/{alerta}", headers=analista, json={"tratado": True}
        )
        assert resposta.status_code == 403

    def test_gestor_marca_como_tratado(self, cliente_auth, alerta, criar_usuario, logar):
        criar_usuario("gestor@suno.example.com", Role.GESTOR)
        resposta = cliente_auth.patch(
            f"{ALERTS}/{alerta}",
            headers=logar("gestor@suno.example.com"),
            json={"tratado": True},
        )
        assert resposta.status_code == 200
        assert resposta.json()["tratado"] is True

    def test_vendedor_nao_ve_alertas(self, cliente_auth, alerta, vendedor):
        assert cliente_auth.get(ALERTS, headers=vendedor).status_code == 403

    def test_alerta_inexistente_da_404(self, cliente_auth, catalogo, analista):
        assert (
            cliente_auth.patch(
                f"{ALERTS}/nao-existe", headers=analista, json={"read": True}
            ).status_code
            == 404
        )


class TestFontes:
    def test_admin_cadastra_fonte_com_robots_ok_falso(self, cliente_auth, catalogo, admin):
        """`robots_ok` nasce `False` **sempre**: quem responde por isso é a coleta.

        Deixar um humano marcar `true` à mão criaria o caminho que o ADR-7 proíbe.
        """
        resposta = cliente_auth.post(
            SOURCES,
            headers=admin,
            json={
                "url": "https://www.ford.com.br/picapes/ranger",
                "tipo": "site_oficial",
                "tier": 1,
            },
        )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["robots_ok"] is False
        assert corpo["dominio"] == "www.ford.com.br"
        assert corpo["confianca_base"] == 0.90

    def test_robots_ok_nao_e_editavel(self, cliente_auth, catalogo, admin):
        criada = cliente_auth.post(
            SOURCES,
            headers=admin,
            json={"url": "https://exemplo.com.br/x", "tipo": "midia", "tier": 3},
        ).json()
        resposta = cliente_auth.patch(
            f"{SOURCES}/{criada['id']}", headers=admin, json={"robots_ok": True}
        )
        assert resposta.status_code == 422

    def test_tipo_desconhecido_e_422(self, cliente_auth, catalogo, admin):
        resposta = cliente_auth.post(
            SOURCES,
            headers=admin,
            json={"url": "https://exemplo.com.br/y", "tipo": "blog-do-zé", "tier": 3},
        )
        assert resposta.status_code == 422

    def test_url_repetida_e_409(self, cliente_auth, catalogo, admin):
        corpo = {"url": "https://exemplo.com.br/z", "tipo": "midia", "tier": 3}
        assert cliente_auth.post(SOURCES, headers=admin, json=corpo).status_code == 201
        assert cliente_auth.post(SOURCES, headers=admin, json=corpo).status_code == 409

    def test_reativar_zera_a_data_de_checagem(self, cliente_auth, catalogo, admin):
        """Manter a data antiga afirmaria que a fonte respondeu — e ela não respondeu."""
        criada = cliente_auth.post(
            SOURCES,
            headers=admin,
            json={"url": "https://bloqueada.com.br/a", "tipo": "midia", "tier": 3},
        ).json()
        cliente_auth.patch(
            f"{SOURCES}/{criada['id']}",
            headers=admin,
            json={"status": "bloqueada", "motivo": "HTTP 403"},
        )
        reativada = cliente_auth.patch(
            f"{SOURCES}/{criada['id']}", headers=admin, json={"status": "ativa"}
        ).json()
        assert reativada["status"] == "ativa"
        assert reativada["ultima_checagem_em"] is None

    def test_analista_nao_gerencia_fontes(self, cliente_auth, catalogo, analista):
        assert cliente_auth.get(SOURCES, headers=analista).status_code == 403


class TestAutenticacaoEmTodoRecurso:
    @pytest.mark.parametrize(
        "metodo,rota",
        [
            ("get", BRANDS),
            ("get", VEHICLES),
            ("get", ATTRIBUTES),
            ("get", ALERTS),
            ("get", SOURCES),
            ("post", RESOLUTIONS),
            ("post", EXTRACTIONS),
            ("post", COMPARISONS),
            ("post", f"{ATTRIBUTES}/resolve"),
        ],
    )
    def test_sem_credencial_da_401(self, cliente_auth, catalogo, metodo, rota):
        # `TestClient.get` nao aceita `json=`; so o POST leva corpo.
        resposta = cliente_auth.post(rota, json={}) if metodo == "post" else cliente_auth.get(rota)
        assert resposta.status_code == 401, rota
