"""WP-34 — a fila de prioridade (`/events`) e a cadeia do "Por quê?" (`/alerts/{id}/trace`).

Dois critérios de aceite estão aqui: **cada elo aponta para uma evidência existente (sem
elos vazios)** e **alerta `is_simulated=true` chega marcado, com a cadeia dizendo
"hipótese"**.

O teste que mais importa é `test_nenhum_elo_sai_em_branco`: um elo vazio na cadeia é pior
que um elo ausente, porque parece prova. Onde o dado não existe, o campo tem de dizer o
motivo — e é isso que o par `evidencias` / `motivo_sem_evidencia` garante.
"""

from __future__ import annotations

import datetime as dt

import pytest

from api.app.models import Role

EVENTOS = "/api/v1/events"
ALERTS = "/api/v1/alerts"

PRECO_DA_RANGER = 390_000.0


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def vendedor(criar_usuario, logar):
    criar_usuario("vendedor@suno.example.com", Role.VENDEDOR)
    return logar("vendedor@suno.example.com")


@pytest.fixture
def cenario(catalogo):
    """Três alertas com histórias diferentes, e a equivalência que dá sentido a elas.

    * **`faixa`** — a Hilux caindo de 420 para 395 mil com a Ranger comparável a 390 mil:
      é o caso `price_band_entry` do critério de aceite, e vem com as duas evidências e o
      snapshot para a cadeia poder ser conferida ponta a ponta;
    * **`ruido`** — o preço FIPE variando 0,55%, **sem evidência nenhuma**: serve para os
      dois lados, o veto do ruído e o elo que precisa dizer por que está vazio;
    * **`simulado`** — dado de demonstração, para a fila e a cadeia dizerem SIMULAÇÃO.
    """
    from api.app.db import session_scope
    from api.app.models import (
        Alert,
        Equivalent,
        Evidence,
        Snapshot,
        Source,
        SpecValue,
    )

    with session_scope() as sessao:
        sessao.add(
            SpecValue(
                version_id=catalogo["raptor"],
                field="preco_sugerido_brl",
                value_json=PRECO_DA_RANGER,
                unit="BRL",
                status="verificado",
                confidence=0.9,
                evidence_id=catalogo["evidencia"],
            )
        )
        sessao.add(
            Equivalent(
                competitor_version_id=catalogo["srx"],
                ford_version_id=catalogo["raptor"],
                nota="par declarado pelo gestor para o teste",
            )
        )

        fonte = Source(
            url="https://www.toyota.com.br/hilux/",
            tipo="site_oficial",
            tier=1,
            dominio="toyota.com.br",
            robots_ok=True,
        )
        sessao.add(fonte)
        sessao.flush()
        snapshot = Snapshot(
            source_id=fonte.id,
            version_id=catalogo["srx"],
            url="https://www.toyota.com.br/hilux/",
            captured_at=dt.datetime(2026, 9, 5),
            sha256="a" * 64,
            http_status=200,
        )
        sessao.add(snapshot)
        sessao.flush()

        antes = Evidence(
            snapshot_id=snapshot.id,
            source_url="https://www.toyota.com.br/hilux/",
            tier=1,
            quote="A partir de R$ 420.000",
            captured_at=dt.datetime(2026, 8, 5),
            raw_value="R$ 420.000",
        )
        depois = Evidence(
            snapshot_id=snapshot.id,
            source_url="https://www.toyota.com.br/hilux/",
            tier=1,
            quote="A partir de R$ 395.000",
            captured_at=dt.datetime(2026, 9, 5),
            raw_value="R$ 395.000",
        )
        sessao.add(antes)
        sessao.add(depois)
        sessao.flush()

        faixa = Alert(
            type="preco_oficial",
            version_id=catalogo["srx"],
            field="preco_sugerido_brl",
            old=420_000,
            new=395_000,
            evidence_before_id=antes.id,
            evidence_after_id=depois.id,
            impact_json={"delta_pct": -5.95, "dimensoes_afetadas": ["preco"]},
            is_simulated=False,
            created_at=dt.datetime(2026, 9, 5),
        )
        ruido = Alert(
            type="preco_fipe",
            version_id=catalogo["srx"],
            field="preco_fipe_brl",
            old=294_378,
            new=296_000,
            impact_json={"delta_pct": 0.55, "dimensoes_afetadas": ["preco", "revenda"]},
            is_simulated=False,
            created_at=dt.datetime(2026, 9, 6),
        )
        simulado = Alert(
            type="preco_oficial",
            version_id=catalogo["srx"],
            field="preco_sugerido_brl",
            old=430_000,
            new=395_600,
            impact_json={"delta_pct": -8.0, "dimensoes_afetadas": ["preco"]},
            is_simulated=True,
            created_at=dt.datetime(2026, 9, 7),
        )
        for linha in (faixa, ruido, simulado):
            sessao.add(linha)
        sessao.commit()
        ids = {
            "faixa": faixa.id,
            "ruido": ruido.id,
            "simulado": simulado.id,
            "evidencia_antes": antes.id,
            "evidencia_depois": depois.id,
            "snapshot": snapshot.id,
        }
    return ids


class TestCriteriosDeAceite:
    def test_cada_elo_aponta_para_evidencia_existente(self, cliente_auth, cenario, analista):
        """Critério: `GET /alerts/{id}/trace` → cada elo aponta para evidência existente."""
        resposta = cliente_auth.get(f"{ALERTS}/{cenario['faixa']}/trace", headers=analista)
        assert resposta.status_code == 200, resposta.text
        cadeia = resposta.json()

        assert cadeia["acao_sugerida"]
        assert cadeia["regras"]
        assert cadeia["mudanca"]["campo_canonico"] == "preco_sugerido_brl"
        assert cadeia["mudanca"]["before"] == 420_000
        assert cadeia["mudanca"]["after"] == 395_000

        ids = {e["evidence_id"] for e in cadeia["evidencias"]}
        assert ids == {cenario["evidencia_antes"], cenario["evidencia_depois"]}
        for evidencia in cadeia["evidencias"]:
            assert evidencia["quote"]
            assert evidencia["source_url"]
            assert evidencia["captured_at"]
        assert cadeia["motivo_sem_evidencia"] == ""

        # Cada evidência diz **de que lado da mudança** ela é, pelo `evidence_id` de
        # onde veio — não pela posição na lista. Ver D-156 e o teste abaixo.
        por_id = {e["evidence_id"]: e["lado"] for e in cadeia["evidencias"]}
        assert por_id[cenario["evidencia_antes"]] == "antes"
        assert por_id[cenario["evidencia_depois"]] == "depois"

        assert [s["snapshot_id"] for s in cadeia["snapshots"]] == [cenario["snapshot"]]
        assert cadeia["snapshots"][0]["sha256"] == "a" * 64
        assert cadeia["motivo_sem_snapshot"] == ""

    def test_com_uma_evidencia_so_o_lado_continua_correto(self, cliente_auth, cenario, analista):
        """O defeito D-156, do lado do servidor.

        No **Fogo Amigo** o `evidence_before_id` nunca é gravado: só existe a evidência do
        *depois*, a da fonte pública. `trace` filtra os `None` antes de montar a lista, e
        a tela rotulava cada bloco pelo índice — a evidência do *depois* caía no índice 0
        e a tela imprimia "antes: 499" em cima da citação da página oficial da Ford.

        Este teste reproduz a forma do alerta: apaga o lado *antes* e confere que o que
        sobra continua se declarando **depois**. Sem o `lado` no contrato, a única
        informação disponível para a tela seria a posição — que aqui é 0.
        """
        from api.app.db import session_scope
        from api.app.models import Alert

        with session_scope() as sessao:
            alerta = sessao.get(Alert, cenario["faixa"])
            alerta.evidence_before_id = None
            sessao.add(alerta)

        cadeia = cliente_auth.get(f"{ALERTS}/{cenario['faixa']}/trace", headers=analista).json()

        assert len(cadeia["evidencias"]) == 1, "só a ponta do depois foi gravada"
        (unica,) = cadeia["evidencias"]
        assert unica["evidence_id"] == cenario["evidencia_depois"]
        assert unica["lado"] == "depois", "o índice 0 não faz dela a evidência do antes"

    def test_nenhum_elo_sai_em_branco(self, cliente_auth, cenario, analista):
        """Critério, do outro lado: sem evidência gravada, o elo **diz por que**.

        É a razão de o par `evidencias` / `motivo_sem_evidencia` existir. Uma lista vazia
        sem explicação deixaria quem lê achando que o sistema perdeu a prova.
        """
        cadeia = cliente_auth.get(f"{ALERTS}/{cenario['ruido']}/trace", headers=analista).json()
        assert cadeia["evidencias"] == []
        assert "sem evidência gravada" in cadeia["motivo_sem_evidencia"]
        assert cadeia["snapshots"] == []
        assert cadeia["motivo_sem_snapshot"]
        # Nenhum elo da cadeia fica em branco sem um motivo escrito ao lado.
        assert cadeia["acao_sugerida"]
        assert cadeia["regras"]
        assert cadeia["comparavel"]["version_id"] or cadeia["comparavel"]["motivo"]

    def test_alerta_simulado_na_fila_e_na_cadeia(self, cliente_auth, cenario, analista):
        """Critério: `is_simulated=true` → a fila marca e a cadeia diz "hipótese"."""
        fila = cliente_auth.get(EVENTOS, headers=analista).json()
        evento = next(e for e in fila if e["alert_id"] == cenario["simulado"])
        assert evento["is_simulated"] is True
        assert evento["alerta"]["is_simulated"] is True

        cadeia = cliente_auth.get(f"{ALERTS}/{cenario['simulado']}/trace", headers=analista).json()
        assert cadeia["is_simulated"] is True
        assert "SIMULAÇÃO" in cadeia["acao_sugerida"]
        assert "hipótese" in cadeia["acao_sugerida"]

    def test_a_variacao_de_menos_de_1_pct_e_RUIDO_pela_api(self, cliente_auth, cenario, analista):
        """O critério do motor, atravessando a API: 0,55% no FIPE → `RUIDO`."""
        fila = cliente_auth.get(EVENTOS, headers=analista).json()
        evento = next(e for e in fila if e["alert_id"] == cenario["ruido"])
        assert evento["materiality"] == "RUIDO"
        assert "ruido_de_tabela" in [r["id"] for r in evento["rules_fired"]]

    def test_entrar_na_faixa_e_ALTA_com_price_band_entry_pela_api(
        self, cliente_auth, cenario, analista
    ):
        """O outro critério do motor pela API, com o par comparável vindo do banco."""
        fila = cliente_auth.get(EVENTOS, headers=analista).json()
        evento = next(e for e in fila if e["alert_id"] == cenario["faixa"])
        assert evento["materiality"] == "ALTA"
        assert "price_band_entry" in [r["id"] for r in evento["rules_fired"]]


class TestAFila:
    def test_ordena_por_prioridade_com_o_ruido_no_fim(self, cliente_auth, cenario, analista):
        fila = cliente_auth.get(EVENTOS, headers=analista).json()
        assert [e["priority_rank"] for e in fila] == sorted(e["priority_rank"] for e in fila)
        assert fila[-1]["alert_id"] == cenario["ruido"]
        assert fila[0]["materiality"] == "ALTA"

    def test_o_filtro_de_prioridade_devolve_so_a_faixa_pedida(
        self, cliente_auth, cenario, analista
    ):
        corpo = cliente_auth.get(f"{EVENTOS}?priority=ALTA", headers=analista).json()
        assert corpo
        assert {e["materiality"] for e in corpo} == {"ALTA"}

    def test_faixa_inexistente_da_422_com_as_validas(self, cliente_auth, cenario, analista):
        resposta = cliente_auth.get(f"{EVENTOS}?priority=URGENTE", headers=analista)
        assert resposta.status_code == 422
        detalhe = resposta.json()["detail"]
        assert "URGENTE" in detalhe
        for faixa in ("ALTA", "MEDIA", "BAIXA", "RUIDO"):
            assert faixa in detalhe

    def test_desligar_o_ruido_esconde_da_fila_e_nao_do_sistema(
        self, cliente_auth, cenario, analista
    ):
        """`RUIDO` sai da **fila**; o alerta continua em `/alerts`, com evidência."""
        sem_ruido = cliente_auth.get(f"{EVENTOS}?incluir_ruido=false", headers=analista).json()
        assert cenario["ruido"] not in [e["alert_id"] for e in sem_ruido]

        alertas = cliente_auth.get(ALERTS, headers=analista).json()
        assert cenario["ruido"] in [a["id"] for a in alertas]

    def test_dá_para_esconder_os_simulados(self, cliente_auth, cenario, analista):
        corpo = cliente_auth.get(f"{EVENTOS}?incluir_simulados=false", headers=analista).json()
        assert cenario["simulado"] not in [e["alert_id"] for e in corpo]
        assert not [e for e in corpo if e["is_simulated"]]

    def test_a_fila_avalia_alerta_gravado_antes_da_wp(self, cliente_auth, cenario, analista):
        """Alerta sem evento não desaparece: a fila o avalia na hora.

        Um alerta invisível porque ninguém rodou o motor seria pior que um alerta sem
        materialidade — e é exatamente o que aconteceria com o que já estava no banco.
        """
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import CompetitiveEvent

        with session_scope() as sessao:
            assert sessao.exec(select(CompetitiveEvent)).all() == []

        fila = cliente_auth.get(EVENTOS, headers=analista).json()
        assert len(fila) == 3

        with session_scope() as sessao:
            assert len(sessao.exec(select(CompetitiveEvent)).all()) == 3

    def test_reavaliar_atualiza_a_linha_em_vez_de_duplicar(self, cliente_auth, cenario, analista):
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import CompetitiveEvent

        primeira = cliente_auth.get(EVENTOS, headers=analista).json()
        segunda = cliente_auth.get(EVENTOS, headers=analista).json()
        assert [e["id"] for e in primeira] == [e["id"] for e in segunda]
        with session_scope() as sessao:
            assert len(sessao.exec(select(CompetitiveEvent)).all()) == 3

    def test_a_versao_das_regras_viaja_na_fila(self, cliente_auth, cenario, analista):
        """Leitura feita sob a régua de setembro não se confunde com a de outubro."""
        from pipeline.materiality import engine

        fila = cliente_auth.get(EVENTOS, headers=analista).json()
        assert {e["versao_das_regras"] for e in fila} == {engine.carregar().versao}

    def test_a_fila_traz_o_alerta_embutido(self, cliente_auth, cenario, analista):
        """Sem isso a tela faria uma chamada por linha só para escrever o título."""
        fila = cliente_auth.get(EVENTOS, headers=analista).json()
        evento = next(e for e in fila if e["alert_id"] == cenario["faixa"])
        assert evento["alerta"]["type"] == "preco_oficial"
        assert evento["alerta"]["field"] == "preco_sugerido_brl"

    def test_o_limite_e_respeitado(self, cliente_auth, cenario, analista):
        corpo = cliente_auth.get(f"{EVENTOS}?limite=1", headers=analista).json()
        assert len(corpo) == 1
        assert corpo[0]["materiality"] == "ALTA"


class TestACadeia:
    def test_a_regra_vem_com_peso_e_descricao(self, cliente_auth, cenario, analista):
        """ "ALTA" sozinho é oráculo. A cadeia mostra a régua inteira."""
        cadeia = cliente_auth.get(f"{ALERTS}/{cenario['faixa']}/trace", headers=analista).json()
        for regra in cadeia["regras"]:
            assert regra["id"]
            assert regra["descricao"]
            assert "peso" in regra
        assert cadeia["pontos"] == sum(r["peso"] for r in cadeia["regras"])

    def test_o_significado_da_faixa_vem_do_yaml(self, cliente_auth, cenario, analista):
        """A frase que define a faixa mora em `rules.yaml`, não duplicada em TypeScript.

        Duas cópias da mesma definição divergem na primeira revisão — e a que o usuário
        veria seria justamente a que ninguém reviu.
        """
        from pipeline.materiality import engine

        cadeia = cliente_auth.get(f"{ALERTS}/{cenario['faixa']}/trace", headers=analista).json()
        esperado = next(f.significado for f in engine.carregar().faixas if f.nome == "ALTA")
        assert cadeia["significado"] == esperado

        fila = cliente_auth.get(EVENTOS, headers=analista).json()
        assert all(e["significado"] for e in fila)

    def test_a_nota_dos_pesos_esta_na_cadeia(self, cliente_auth, cenario, analista):
        cadeia = cliente_auth.get(f"{ALERTS}/{cenario['faixa']}/trace", headers=analista).json()
        assert "escolha declarada" in cadeia["nota_dos_pesos"]
        assert "yaml" not in cadeia["nota_dos_pesos"].lower()

    def test_o_par_comparavel_aparece_com_rotulo_legivel(self, cliente_auth, cenario, analista):
        cadeia = cliente_auth.get(f"{ALERTS}/{cenario['faixa']}/trace", headers=analista).json()
        assert cadeia["comparavel"]["rotulo"].startswith("Ford Ranger")
        assert cadeia["comparavel"]["motivo"] == ""

    def test_a_acao_sugerida_muda_com_a_faixa(self, cliente_auth, cenario, analista):
        alta = cliente_auth.get(f"{ALERTS}/{cenario['faixa']}/trace", headers=analista).json()
        ruido = cliente_auth.get(f"{ALERTS}/{cenario['ruido']}/trace", headers=analista).json()
        assert alta["acao_sugerida"] != ruido["acao_sugerida"]
        assert "hoje" in alta["acao_sugerida"]
        assert "Nenhuma ação" in ruido["acao_sugerida"]

    def test_alerta_inexistente_da_404_de_problem_json(self, cliente_auth, cenario, analista):
        resposta = cliente_auth.get(f"{ALERTS}/nao-existe/trace", headers=analista)
        assert resposta.status_code == 404
        assert resposta.headers["content-type"].startswith("application/problem+json")


class TestPermissoes:
    def test_vendedor_recebe_403_na_fila(self, cliente_auth, cenario, vendedor):
        """A fila é a mesma informação do Radar: `docs/12` §6.1 diz "Vendedor não vê"."""
        assert cliente_auth.get(EVENTOS, headers=vendedor).status_code == 403

    def test_vendedor_recebe_403_na_cadeia(self, cliente_auth, cenario, vendedor):
        resposta = cliente_auth.get(f"{ALERTS}/{cenario['faixa']}/trace", headers=vendedor)
        assert resposta.status_code == 403

    def test_sem_token_da_401(self, cliente_auth, cenario):
        assert cliente_auth.get(EVENTOS).status_code == 401
        assert cliente_auth.get(f"{ALERTS}/{cenario['faixa']}/trace").status_code == 401


class TestOsFiltrosDaFila:
    """A fila **substitui** a lista na tela, e por isso filtra pelos mesmos parâmetros.

    Sem isso a tela precisaria de duas consultas para a mesma informação, e as duas
    poderiam discordar sobre quantos alertas de um tipo existem.
    """

    def test_filtra_por_tipo(self, cliente_auth, cenario, analista):
        corpo = cliente_auth.get(f"{EVENTOS}?type=preco_fipe", headers=analista).json()
        assert [e["alert_id"] for e in corpo] == [cenario["ruido"]]

    def test_filtra_por_concorrente(self, cliente_auth, cenario, analista, catalogo):
        todos = cliente_auth.get(f"{EVENTOS}?competitor={catalogo['srx']}", headers=analista).json()
        assert len(todos) == 3
        nenhum = cliente_auth.get(
            f"{EVENTOS}?competitor={catalogo['raptor']}", headers=analista
        ).json()
        assert nenhum == []

    def test_filtra_por_data(self, cliente_auth, cenario, analista):
        corpo = cliente_auth.get(f"{EVENTOS}?since=2026-09-07T00:00:00", headers=analista).json()
        assert [e["alert_id"] for e in corpo] == [cenario["simulado"]]

    def test_tipo_invalido_da_422(self, cliente_auth, cenario, analista):
        """Vocabulário fechado dos sete tipos, igual ao de `/alerts`."""
        assert (
            cliente_auth.get(f"{EVENTOS}?type=tipo_do_futuro", headers=analista).status_code == 422
        )
