"""`GET /benchmark/proposta` — o conjunto comparável proposto para uma versão Ford.

O que estes testes guardam não é a lista: é **o que a resposta se recusa a fazer**.

Não cai para outro ano-modelo quando o concorrente não existe no ano pedido; não aceita
partir de uma versão que não é Ford; não some com o par que a régua reprova; e não existe
quando `BENCHMARK_ENABLED` está desligada. Cada uma dessas recusas é um caminho pelo qual
sairia uma matriz impecável e enganosa.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.app.models import Role

PROPOSTA = "/api/v1/benchmark/proposta"


@pytest.fixture
def com_benchmark(monkeypatch: pytest.MonkeyPatch, schema_criado: None) -> Iterator[TestClient]:
    monkeypatch.setenv("BENCHMARK_ENABLED", "1")
    from api.app.main import create_app

    with TestClient(create_app()) as cliente:
        yield cliente


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def ranger(schema_criado: None) -> dict[str, str]:
    """Uma Ranger 2026 e uma Hilux 2026 — a única concorrente do mapa que existe aqui.

    Os outros seis modelos do segmento ficam de fora **de propósito**: é assim que se
    exercita o caminho "precisa pesquisa", que é o caminho normal de um catálogo real.
    """
    from api.app.db import session_scope
    from api.app.models import Brand, Evidence, SpecValue, VehicleModel, Version

    ids: dict[str, str] = {}
    with session_scope() as sessao:
        ford = Brand(nome="Ford")
        toyota = Brand(nome="Toyota")
        sessao.add(ford)
        sessao.add(toyota)
        sessao.flush()

        m_ranger = VehicleModel(brand_id=ford.id, nome="Ranger", segmento="picape média")
        m_hilux = VehicleModel(brand_id=toyota.id, nome="Hilux", segmento="picape média")
        sessao.add(m_ranger)
        sessao.add(m_hilux)
        sessao.flush()

        raptor = Version(
            model_id=m_ranger.id,
            nome_exato="Raptor 3.0 V6 Bi-turbo 4WD AT",
            ano_modelo=2026,
            in_lineup=True,
            lineup_checked_at=dt.datetime(2026, 9, 1),
        )
        srx = Version(
            model_id=m_hilux.id,
            nome_exato="SRX Plus AT (Cabine Dupla)",
            ano_modelo=2026,
            in_lineup=True,
            lineup_checked_at=dt.datetime(2026, 9, 1),
        )
        # Hilux de 2024: existe, e **não** pode ser escolhida para comparar com a 2026.
        antiga = Version(model_id=m_hilux.id, nome_exato="SRX 2024", ano_modelo=2024)
        for v in (raptor, srx, antiga):
            sessao.add(v)
        sessao.flush()

        # As duas de 2026 precisam de **célula**: versão sem ficha não é candidata a
        # comparação (ver `TestVersaoSemFicha`). Uma célula basta para ser candidata.
        evidencia = Evidence(
            source_url="https://www.exemplo.test/ficha",
            tier=1,
            quote="potência declarada",
            captured_at=dt.datetime(2026, 9, 1),
        )
        sessao.add(evidencia)
        sessao.flush()
        for versao, potencia in ((raptor, 397), (srx, 204)):
            sessao.add(
                SpecValue(
                    version_id=versao.id,
                    field="potencia_cv",
                    value_json=potencia,
                    unit="cv",
                    status="verificado",
                    confidence=0.9,
                    evidence_id=evidencia.id,
                )
            )
        ids = {"raptor": raptor.id, "srx": srx.id, "srx_antiga": antiga.id}
    return ids


def _propor(cliente, headers, version_id: str):
    return cliente.get(PROPOSTA, params={"version_id": version_id}, headers=headers)


class TestAProposta:
    def test_a_ranger_recebe_os_sete_concorrentes_do_mapa(self, com_benchmark, ranger, analista):
        corpo = _propor(com_benchmark, analista, ranger["raptor"]).json()
        assert corpo["segmento"]["id"] == "picape_media"
        assert corpo["segmento"]["origem"] == "mapa"
        assert len(corpo["candidatos"]) == 7

    def test_a_hilux_do_catalogo_entra_com_o_k_de_n(self, com_benchmark, ranger, analista):
        corpo = _propor(com_benchmark, analista, ranger["raptor"]).json()
        hilux = next(c for c in corpo["candidatos"] if c["modelo"] == "Hilux")
        assert hilux["no_catalogo"] is True
        assert hilux["version_id"] == ranger["srx"]
        assert "critérios atendidos" in hilux["comparabilidade"]["resumo"]
        assert "%" not in hilux["comparabilidade"]["resumo"], "k/n, nunca porcentagem"

    def test_os_que_faltam_pedem_pesquisa_com_o_motivo_escrito(
        self, com_benchmark, ranger, analista
    ):
        corpo = _propor(com_benchmark, analista, ranger["raptor"]).json()
        amarok = next(c for c in corpo["candidatos"] if c["modelo"] == "Amarok")
        assert amarok["precisa_pesquisa"] is True
        assert amarok["no_catalogo"] is False
        assert "2026" in amarok["motivo_da_pesquisa"]
        assert corpo["a_pesquisar"] == 6
        assert corpo["prontos"] == 1

    def test_a_toro_vem_por_ultimo_e_marcada(self, com_benchmark, ranger, analista):
        corpo = _propor(com_benchmark, analista, ranger["raptor"]).json()
        ultimo = corpo["candidatos"][-1]
        assert ultimo["modelo"] == "Toro"
        assert ultimo["categoria_diferente"] is True
        assert ultimo["motivo_da_categoria"], "marca sem motivo é o sistema opinando"

    def test_o_aviso_conta_quantos_faltam(self, com_benchmark, ranger, analista):
        corpo = _propor(com_benchmark, analista, ranger["raptor"]).json()
        assert "6 de 7" in corpo["aviso"]

    def test_a_versao_do_mapa_viaja_na_resposta(self, com_benchmark, ranger, analista):
        """Como a `versao` dos critérios de comparabilidade: nenhuma proposta exibida hoje
        pode ser confundida com uma feita sob outro mapa."""
        corpo = _propor(com_benchmark, analista, ranger["raptor"]).json()
        assert corpo["versao_do_mapa"] == "2026-09-13"


class TestAsRecusas:
    def test_nao_cai_para_outro_ano_modelo(self, com_benchmark, ranger, analista):
        """A Hilux 2024 existe no catálogo e **não** pode ser escolhida para a Ranger 2026.

        Cair para outro ano é o erro silencioso deste fluxo: a matriz sairia impecável,
        e nenhuma célula estaria errada."""
        corpo = _propor(com_benchmark, analista, ranger["raptor"]).json()
        hilux = next(c for c in corpo["candidatos"] if c["modelo"] == "Hilux")
        assert hilux["ano_modelo"] == 2026
        assert hilux["version_id"] != ranger["srx_antiga"]

    def test_partir_de_uma_versao_que_nao_e_ford_e_422(self, com_benchmark, ranger, analista):
        """Não é limitação técnica: o benchmark é a visão da Ford sobre a concorrência, e
        inverter os papéis produziria uma tabela com outro significado."""
        resposta = _propor(com_benchmark, analista, ranger["srx"])
        assert resposta.status_code == 422
        assert "Toyota" in resposta.json()["detail"]

    def test_versao_inexistente_e_404(self, com_benchmark, ranger, analista):
        assert _propor(com_benchmark, analista, "nao-existe").status_code == 404

    def test_sem_a_bandeira_a_rota_nao_existe(
        self, monkeypatch: pytest.MonkeyPatch, schema_criado, ranger, criar_usuario, logar
    ):
        """404, e não 403: sem `BENCHMARK_ENABLED` o roteador não é montado. Uma rota que
        anuncia existir e recusa é diferente de uma capacidade que não está no ar.

        **A bandeira é apagada aqui de propósito**, e não herdada do ambiente: este teste
        falhou em 13/09 quando o portão inteiro rodou com `BENCHMARK_ENABLED=1` exportada
        no shell. Um teste que afirma "a rota não existe" e depende de quem o chamou não
        afirma nada.
        """
        from fastapi.testclient import TestClient

        monkeypatch.delenv("BENCHMARK_ENABLED", raising=False)
        from api.app.main import create_app

        with TestClient(create_app()) as cliente:
            criar_usuario("analista@suno.example.com", Role.ANALISTA)
            resposta = cliente.get(
                PROPOSTA,
                params={"version_id": ranger["raptor"]},
                headers=logar("analista@suno.example.com"),
            )
        assert resposta.status_code == 404


class TestVersaoSemFicha:
    """Uma versão sem célula nenhuma **não** é candidata a comparação.

    **Achado por medição, em 13/09/2026.** O benchmark da Raptor escolheu a *Amarok V6
    Comfortline* — zero células — em vez da *V6 Extreme*, que tem 116. As duas empataram em
    critérios atendidos (a maioria sai do denominador por falta de dado), e o desempate
    alfabético entregou a errada. O sintoma na tela era "96 não sabemos": uma matriz
    impecável comparando contra uma coluna vazia.

    A regra passou a ser: entre as versões do mesmo ano, **só as que têm ficha** disputam;
    se nenhuma tem, o concorrente vai para a pesquisa, com o motivo escrito.
    """

    @pytest.fixture
    def amarok(self, schema_criado: None, ranger) -> dict[str, str]:
        from api.app.db import session_scope
        from api.app.models import Brand, Evidence, SpecValue, VehicleModel, Version

        with session_scope() as sessao:
            vw = Brand(nome="Volkswagen")
            sessao.add(vw)
            sessao.flush()
            modelo = VehicleModel(brand_id=vw.id, nome="Amarok", segmento="picape média")
            sessao.add(modelo)
            sessao.flush()
            # Alfabeticamente antes da Extreme, e **sem nenhuma célula**.
            vazia = Version(model_id=modelo.id, nome_exato="V6 Comfortline", ano_modelo=2026)
            cheia = Version(model_id=modelo.id, nome_exato="V6 Extreme", ano_modelo=2026)
            sessao.add(vazia)
            sessao.add(cheia)
            sessao.flush()
            evidencia = Evidence(
                source_url="https://www.vw.com.br/amarok/",
                tier=1,
                quote="258 cv",
                captured_at=dt.datetime(2026, 9, 1),
            )
            sessao.add(evidencia)
            sessao.flush()
            sessao.add(
                SpecValue(
                    version_id=cheia.id,
                    field="potencia_cv",
                    value_json=258,
                    unit="cv",
                    status="verificado",
                    confidence=0.9,
                    evidence_id=evidencia.id,
                )
            )
            return {"vazia": vazia.id, "cheia": cheia.id, **ranger}

    def test_a_versao_com_ficha_vence_a_que_vem_antes_no_alfabeto(
        self, com_benchmark, amarok, analista
    ):
        corpo = _propor(com_benchmark, analista, amarok["raptor"]).json()
        vw = next(c for c in corpo["candidatos"] if c["modelo"] == "Amarok")
        assert vw["version_id"] == amarok["cheia"]
        assert vw["rotulo"].endswith("V6 Extreme")

    def test_modelo_so_com_versoes_vazias_vai_para_a_pesquisa(
        self, com_benchmark, ranger, analista, schema_criado
    ):
        """Existir no catálogo e não ter ficha não é a mesma coisa que estar pronto."""
        from api.app.db import session_scope
        from api.app.models import Brand, VehicleModel, Version

        with session_scope() as sessao:
            marca = Brand(nome="RAM")
            sessao.add(marca)
            sessao.flush()
            modelo = VehicleModel(brand_id=marca.id, nome="Rampage", segmento="picape média")
            sessao.add(modelo)
            sessao.flush()
            sessao.add(Version(model_id=modelo.id, nome_exato="Laramie", ano_modelo=2026))

        corpo = _propor(com_benchmark, analista, ranger["raptor"]).json()
        rampage = next(c for c in corpo["candidatos"] if c["modelo"] == "Rampage")
        assert rampage["precisa_pesquisa"] is True
        assert "ficha" in rampage["motivo_da_pesquisa"]
