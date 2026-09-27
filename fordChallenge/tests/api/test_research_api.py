"""`POST /research` e `GET /research/{id}/events`.

O Pesquisador pela API: 202 com o job, a trilha em JSON e em SSE, e a porta fechada para
quem não pode disparar uma pesquisa.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.app.models import ResearchEvent, ResearchRun, Role

RESEARCH = "/api/v1/research"


@pytest.fixture
def retomavel(com_pesquisador, analista, monkeypatch, tmp_path):
    from dataclasses import asdict

    from api.app.db import session_scope
    from api.app.models import Job
    from pipeline.publication import POLICY_VERSION
    from pipeline.research.checkpoint import job_path
    from pipeline.research.planner import Alvo

    monkeypatch.setenv("RESEARCH_CHECKPOINT_DIR", str(tmp_path / "checkpoints"))
    pedido = {"marca": "Ford", "modelo": "Ranger", "versao": "Limited", "ano": 2027}
    ids = com_pesquisador.post(RESEARCH, headers=analista, json=pedido).json()
    with session_scope() as sessao:
        run = sessao.get(ResearchRun, ids["run_id"])
        run.status = "concluida"
        job = sessao.get(Job, ids["job_id"])
        job.status = "concluido"
        sessao.add(run)
        sessao.add(job)
        sessao.commit()
    path = job_path(ids["job_id"])
    path.parent.mkdir(parents=True)
    saved = {
        "policy": POLICY_VERSION,
        "target": asdict(Alvo(**pedido)),
        "budget_spent": {"rodadas_gastas": 2, "paginas_gastas": 12, "decorrido": 180},
        "fontes": [{"texto": "Documento já pago"}],
        "consultas": ["consulta já feita"],
    }
    path.write_text(json.dumps(saved), encoding="utf-8")
    return ids, path


class TestContinuacao:
    def test_reusa_checkpoint_sem_alterar_anterior_e_deduplica_clique(
        self, retomavel, com_pesquisador, analista
    ):
        from api.app.db import session_scope
        from api.app.models import Job
        from pipeline.research.checkpoint import job_path

        ids, path = retomavel
        original = path.read_bytes()
        url = f"{RESEARCH}/{ids['run_id']}"
        assert com_pesquisador.get(url, headers=analista).json()["continuacao_disponivel"]
        primeira = com_pesquisador.post(url + "/continue", json={}, headers=analista)
        assert primeira.status_code == 202, primeira.text
        nova = primeira.json()
        repetida = com_pesquisador.post(url + "/continue", json={}, headers=analista)
        assert repetida.json()["job_id"] == nova["job_id"]
        assert path.read_bytes() == original
        assert json.loads(job_path(nova["job_id"]).read_text(encoding="utf-8")) == json.loads(
            original
        )
        with session_scope() as sessao:
            job = sessao.get(Job, nova["job_id"])
            assert job.payload["continued_from"] == ids["run_id"]
            assert job.payload["ano"] == 2027
            assert job.payload["segundos"] == 900
            assert sessao.get(ResearchRun, ids["run_id"]).status == "concluida"
        assert not com_pesquisador.get(url, headers=analista).json()["continuacao_disponivel"]

    @pytest.mark.parametrize(
        "caso", ["sem_arquivo", "identidade", "politica", "orçamento", "ativo"]
    )
    def test_recusa_checkpoint_invalido_ou_pesquisa_ativa(
        self, retomavel, com_pesquisador, analista, caso
    ):
        from api.app.db import session_scope

        ids, path = retomavel
        saved = json.loads(path.read_text())
        body = {}
        if caso == "sem_arquivo":
            path.unlink()
        elif caso == "identidade":
            saved["target"]["ano"] = 2026
            path.write_text(json.dumps(saved))
        elif caso == "politica":
            saved["policy"] = "obsoleta"
            path.write_text(json.dumps(saved))
        elif caso == "orçamento":
            body = {"segundos": 180}
        else:
            with session_scope() as sessao:
                run = sessao.get(ResearchRun, ids["run_id"])
                run.status = "pendente"
                sessao.add(run)
                sessao.commit()
        resposta = com_pesquisador.post(
            f"{RESEARCH}/{ids['run_id']}/continue", headers=analista, json=body
        )
        assert resposta.status_code == 409, resposta.text


@pytest.fixture
def com_pesquisador(monkeypatch: pytest.MonkeyPatch, schema_criado: None) -> Iterator[TestClient]:
    """A API com `RESEARCH_ENABLED=1`.

    O roteador fica atrás da bandeira porque o Pesquisador sai para a internet e gasta
    chamada de LLM — e a demonstração tem de poder rodar sem nenhum dos dois.
    """
    monkeypatch.setenv("RESEARCH_ENABLED", "1")
    from api.app.main import create_app

    with TestClient(create_app()) as cliente:
        yield cliente


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def vendedor(criar_usuario, logar):
    criar_usuario("vendedor@suno.example.com", Role.VENDEDOR)
    return logar("vendedor@suno.example.com")


def _semear_run(marca: str = "Ford", modelo: str = "Ranger") -> str:
    from api.app.db import session_scope

    with session_scope() as sessao:
        run = ResearchRun(
            marca=marca,
            modelo=modelo,
            status="concluida",
            motivo_da_parada="cobertura",
            campos_com_valor=31,
            campos_alvo=55,
        )
        sessao.add(run)
        sessao.flush()
        passos = [
            ("inicio", "procurando Ford Ranger", "FATO"),
            ("consulta", "Ford Ranger ficha técnica oficial", "FATO"),
            ("fonte_descartada", "youtube.com: vídeo, não há texto a citar", "INFERENCIA"),
            ("baixada", "ford.com.br: 48210 caracteres salvos", "FATO"),
            ("fim", "pesquisa concluída: 31 de 55 campos respondidos", "FATO"),
        ]
        for i, (tipo, texto, etiqueta) in enumerate(passos):
            sessao.add(
                ResearchEvent(
                    run_id=run.id,
                    ordem=i,
                    tipo=tipo,
                    texto=texto,
                    etiqueta=etiqueta,
                    dados={"url": "https://exemplo"} if "fonte" in tipo else {},
                )
            )
        sessao.commit()
        return run.id


class TestABandeira:
    def test_sem_RESEARCH_ENABLED_so_identificacao_de_catalogo_continua(
        self, monkeypatch: pytest.MonkeyPatch, schema_criado: None, catalogo, analista
    ):
        """A Consulta identifica no banco mesmo quando a pesquisa externa está desligada."""
        monkeypatch.delenv("RESEARCH_ENABLED", raising=False)
        from api.app.main import create_app

        cliente = TestClient(create_app())
        caminhos = cliente.get("/openapi.json").json()["paths"]
        assert "/api/v1/research" not in caminhos
        assert "/api/v1/research/identify" in caminhos
        resposta = cliente.post(
            f"{RESEARCH}/identify", headers=analista, json={"texto": "Ranger Raptor"}
        )
        assert resposta.status_code == 200
        assert resposta.json()["no_catalogo"]["version_id"]


class TestCriar:
    def test_responde_202_com_o_id_e_o_endereco_dos_eventos(
        self, com_pesquisador: TestClient, analista
    ):
        """202, e não 200: uma pesquisa leva até três minutos, e nenhuma requisição HTTP
        espera isso de pé."""
        resposta = com_pesquisador.post(
            RESEARCH,
            headers=analista,
            json={"marca": "Volkswagen", "modelo": "Amarok", "versao": "V6 Highline"},
        )
        assert resposta.status_code == 202, resposta.text
        corpo = resposta.json()
        assert corpo["run_id"]
        assert corpo["job_id"]
        assert corpo["events_url"].endswith("/events")

    def test_o_job_entra_na_MESMA_fila_da_extracao(self, com_pesquisador: TestClient, analista):
        """Um segundo mecanismo de fila seria um segundo lugar para um job travar — e um
        segundo lugar para procurar quando ele travar."""
        from api.app.db import session_scope
        from api.app.models import Job

        corpo = com_pesquisador.post(
            RESEARCH, headers=analista, json={"marca": "RAM", "modelo": "Rampage"}
        ).json()
        with session_scope() as sessao:
            job = sessao.get(Job, corpo["job_id"])
            assert job is not None
            assert job.tipo == "research"
            assert job.payload["run_id"] == corpo["run_id"]

    def test_lista_livre_de_atributos_e_resolvida_para_campos_canonicos_no_job(
        self, com_pesquisador: TestClient, analista
    ):
        """Edital: "lista livre de atributos". Texto do usuário -> campo canônico, antes
        de o job ir para a fila — o worker só precisa saber pedir `pesquisar(campos=...)`.
        """
        from api.app.db import session_scope
        from api.app.models import Job

        corpo = com_pesquisador.post(
            RESEARCH,
            headers=analista,
            json={
                "marca": "Ford",
                "modelo": "Ranger",
                "versao": "Raptor 3.0 V6 Bi-turbo 4WD AT",
                "atributos": ["cavalos", "modos de volante", "termo desconhecido xyz"],
            },
        ).json()
        with session_scope() as sessao:
            job = sessao.get(Job, corpo["job_id"])
            assert job.payload["atributos"] == ["potencia_cv", "modos_direcao"]

    def test_marca_e_modelo_sao_opcionais_quando_ha_lista_de_atributos(
        self, com_pesquisador: TestClient, analista
    ):
        """O edital pede marca+modelo+versão **e** lista livre de atributos, mas não diz
        que os três primeiros são obrigatórios em toda chamada — só a versão já era
        opcional; marca e modelo passam a ser também.
        """
        resposta = com_pesquisador.post(
            RESEARCH,
            headers=analista,
            json={"atributos": ["potencia_cv"]},
        )
        assert resposta.status_code == 202, resposta.text

    def test_campo_que_nao_existe_no_contrato_e_recusado(
        self, com_pesquisador: TestClient, analista
    ):
        """`extra="forbid"`: campo desconhecido é erro, não é ignorado em silêncio.

        E este campo em especial: o produto **não** guarda dado de cliente.
        """
        resposta = com_pesquisador.post(
            RESEARCH,
            headers=analista,
            json={"marca": "Ford", "modelo": "Ranger", "telefone": "11999999999"},
        )
        assert resposta.status_code == 422

    def test_o_orcamento_tem_teto_no_contrato(self, com_pesquisador: TestClient, analista):
        """Sem teto, um pedido de mil páginas viraria uma hora de coleta contra sites de
        terceiros — e scraping educado é regra inviolável."""
        resposta = com_pesquisador.post(
            RESEARCH,
            headers=analista,
            json={"marca": "Ford", "modelo": "Ranger", "paginas": 1000},
        )
        assert resposta.status_code == 422

    def test_o_vendedor_pode_disparar_o_fluxo_unificado(
        self, com_pesquisador: TestClient, vendedor
    ):
        resposta = com_pesquisador.post(
            RESEARCH, headers=vendedor, json={"marca": "Ford", "modelo": "Ranger"}
        )
        assert resposta.status_code == 202


class TestTrilha:
    def test_a_trilha_sai_em_JSON_na_ordem(self, com_pesquisador: TestClient, analista):
        run_id = _semear_run()
        corpo = com_pesquisador.get(f"{RESEARCH}/{run_id}/events", headers=analista).json()
        assert [e["ordem"] for e in corpo["eventos"]] == [0, 1, 2, 3, 4]
        assert corpo["campos_com_valor"] == 31
        assert corpo["motivo_da_parada"] == "cobertura"

    def test_a_fonte_descartada_aparece_na_trilha(self, com_pesquisador: TestClient, analista):
        """Mostrar só o que deu certo faria a tela parecer mais limpa e a pesquisa, menos
        conferível. Uma fonte descartada em silêncio é indistinguível de uma que ninguém
        viu."""
        run_id = _semear_run()
        corpo = com_pesquisador.get(f"{RESEARCH}/{run_id}/events", headers=analista).json()
        descartadas = [e for e in corpo["eventos"] if e["tipo"] == "fonte_descartada"]
        assert descartadas
        assert "não há texto a citar" in descartadas[0]["texto"]

    def test_todo_evento_leva_etiqueta(self, com_pesquisador: TestClient, analista):
        """`docs/13` §2 vale aqui também: nenhuma informação na tela sem etiqueta."""
        run_id = _semear_run()
        corpo = com_pesquisador.get(f"{RESEARCH}/{run_id}/events", headers=analista).json()
        for evento in corpo["eventos"]:
            assert evento["etiqueta"] in {"FATO", "INFERENCIA", "SIMULACAO"}

    def test_o_SSE_transmite_ate_o_fim_e_para(self, com_pesquisador: TestClient, analista):
        """O painel ao vivo lê por aqui. O `fim` encerra a conexão — sem ele, a tela
        ficaria aberta esperando um evento que não vem."""
        run_id = _semear_run()
        with com_pesquisador.stream(
            "GET",
            f"{RESEARCH}/{run_id}/events",
            headers={**analista, "Accept": "text/event-stream"},
        ) as resposta:
            assert resposta.status_code == 200
            assert "text/event-stream" in resposta.headers["content-type"]
            corpo = "".join(resposta.iter_text())

        assert "event: inicio" in corpo
        assert "event: fim" in corpo
        # Cada `data:` numa linha só: JSON com quebra de linha quebra o protocolo, e um
        # painel que engasga no meio da pesquisa é pior que um painel que não existe.
        for linha in corpo.split("\n"):
            if linha.startswith("data: "):
                json.loads(linha[len("data: ") :])

    def test_pesquisa_que_nao_existe_da_404(self, com_pesquisador: TestClient, analista):
        assert com_pesquisador.get(f"{RESEARCH}/nao-existe", headers=analista).status_code == 404


class TestAFichaNoCatalogo:
    def test_a_trilha_traz_o_version_id_quando_a_ficha_foi_gravada(
        self, com_pesquisador: TestClient, analista
    ):
        """É o elo que a tela usa para o botão "abrir ficha": sem ele, a pesquisa termina
        e a pessoa não tem para onde ir."""
        from api.app.db import session_scope
        from api.app.models import Brand, VehicleModel, Version

        with session_scope() as sessao:
            marca = Brand(nome="Mitsubishi")
            sessao.add(marca)
            sessao.flush()
            modelo = VehicleModel(brand_id=marca.id, nome="Triton")
            sessao.add(modelo)
            sessao.flush()
            versao = Version(model_id=modelo.id, nome_exato="HPE-S", ano_modelo=2026)
            sessao.add(versao)
            sessao.flush()
            run = ResearchRun(
                marca="Mitsubishi",
                modelo="Triton",
                versao="HPE-S",
                status="concluida",
                motivo_da_parada="cobertura",
                version_id=versao.id,
                tokens=4400,
                custo_brl=0.19,
            )
            sessao.add(run)
            sessao.commit()
            run_id, version_id = run.id, versao.id

        corpo = com_pesquisador.get(f"{RESEARCH}/{run_id}", headers=analista).json()
        assert corpo["version_id"] == version_id
        assert corpo["tokens"] == 4400
        assert corpo["custo_brl"] == 0.19
        assert corpo["erro"] is None

    def test_sem_ficha_gravada_o_version_id_e_nulo(self, com_pesquisador: TestClient, analista):
        run_id = _semear_run()
        corpo = com_pesquisador.get(f"{RESEARCH}/{run_id}", headers=analista).json()
        assert corpo["version_id"] is None


class TestIdentificar:
    IDENTIFY = f"{RESEARCH}/identify"

    def test_o_que_ja_esta_no_catalogo_resolve_e_diz_de_quando_sao_os_dados(
        self, com_pesquisador: TestClient, analista, catalogo
    ):
        corpo = com_pesquisador.post(
            self.IDENTIFY, headers=analista, json={"texto": "Ranger Raptor"}
        ).json()
        assert corpo["estado"] == "resolvido", corpo
        assert (corpo["marca"], corpo["modelo"]) == ("Ford", "Ranger")
        assert corpo["ano_origem"] == "catalogo" and corpo["ano"]
        assert corpo["no_catalogo"] is not None
        assert corpo["no_catalogo"]["version_id"]
        assert corpo["no_catalogo"]["ano_modelo"] == corpo["ano"]
        assert "gasto_rodada" in corpo

    def test_alias_oficial_nao_duplica_a_raptor_nem_torna_o_pedido_ambiguo(
        self, com_pesquisador: TestClient, analista, catalogo
    ):
        """O título curto e o nome completo da mesma página Ford são uma versão só."""
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import Brand, VehicleModel, Version

        with session_scope() as sessao:
            ranger = sessao.exec(
                select(VehicleModel)
                .join(Brand, Brand.id == VehicleModel.brand_id)
                .where(Brand.nome == "Ford", VehicleModel.nome == "Ranger")
            ).one()
            sessao.add(
                Version(
                    model_id=ranger.id,
                    nome_exato="Raptor 4WD AT",
                    ano_modelo=2026,
                    in_lineup=True,
                )
            )
            sessao.commit()

        corpo = com_pesquisador.post(
            self.IDENTIFY, headers=analista, json={"texto": "Ranger Raptor"}
        ).json()
        assert corpo["estado"] == "resolvido", corpo
        assert corpo["versao"] == "Raptor 3.0 V6 Bi-turbo 4WD AT"
        assert corpo["no_catalogo"]["tem_ficha"] is True

    def test_fora_do_catalogo_e_sem_modelo_diz_que_nao_entendeu(
        self, com_pesquisador: TestClient, analista, catalogo
    ):
        """Em `LLM_FAKE=1` não há busca nem modelo: a resposta é honesta, não um chute."""
        corpo = com_pesquisador.post(
            self.IDENTIFY, headers=analista, json={"texto": "Triton"}
        ).json()
        assert corpo["estado"] == "nao_entendi"
        assert "modelo configurado" in corpo["motivo"]
        assert corpo["no_catalogo"] is None and corpo["opcoes"] == []

    def test_o_vendedor_identifica_no_fluxo_unificado(self, com_pesquisador: TestClient, vendedor):
        resposta = com_pesquisador.post(self.IDENTIFY, headers=vendedor, json={"texto": "Triton"})
        assert resposta.status_code == 200

    def test_campo_fora_do_contrato_e_recusado(self, com_pesquisador: TestClient, analista):
        resposta = com_pesquisador.post(
            self.IDENTIFY, headers=analista, json={"texto": "Triton", "marca": "Mitsubishi"}
        )
        assert resposta.status_code == 422
