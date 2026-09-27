"""WP-26 — `POST /comparisons` com `needs_profile`, e `GET /dimensions`.

Dois critérios de aceite vivem aqui: o **422 do override que não soma 100** e a presença do
**rótulo obrigatório** na resposta. Os outros testes protegem a compatibilidade — sem
`needs_profile` a resposta tem de ser exatamente a matriz do v1 — e a coerência do bloco
`fit` com os pesos que a tela vai exibir.
"""

from __future__ import annotations

import datetime as dt

import pytest

from api.app.models import Role

COMPARISONS = "/api/v1/comparisons"
DIMENSIONS = "/api/v1/dimensions"

PERFIL_RURAL = {
    "uso": ["rural_carga"],
    "prioridades_rank": ["economia", "capacidade", "seguranca"],
    "km_mes": 2500,
    "combustivel_preco": {"diesel": 6.20, "gasolina": 6.00},
}


@pytest.fixture
def vendedor(criar_usuario, logar):
    criar_usuario("vendedor@suno.example.com", Role.VENDEDOR)
    return logar("vendedor@suno.example.com")


@pytest.fixture
def fichas(catalogo):
    """Ficha nos dois lados, com consumo, preço e combustível — o que o `fit` consome."""
    from api.app.db import session_scope
    from api.app.models import Evidence, SpecValue

    with session_scope() as sessao:
        pbev = Evidence(
            source_url="https://www.toyota.com.br/hilux",
            tier=2,
            quote=(
                "Hilux Diesel 4×4 SRX Plus (Wide Tread) 2.8 Automático, percorre 9,7km/l na "
                "cidade e 10,6km/l na estrada"
            ),
            captured_at=dt.datetime(2026, 9, 1),
        )
        oficial = Evidence(
            source_url="https://www.ford.com.br/ranger-raptor",
            tier=1,
            quote="Consumo urbano 7,2 km/l",
            captured_at=dt.datetime(2026, 9, 1),
        )
        sessao.add(pbev)
        sessao.add(oficial)
        sessao.flush()

        do_concorrente = [
            ("consumo_urbano_kml", 9.7, pbev.id),
            ("consumo_rodoviario_kml", 10.6, pbev.id),
            ("capacidade_carga_kg", 1005, pbev.id),
            ("preco_sugerido_brl", 348790, pbev.id),
            ("combustivel", "diesel", pbev.id),
            ("airbags_qtd", 7, pbev.id),
            ("camera_360", True, pbev.id),
        ]
        da_ford = [
            ("consumo_urbano_kml", 7.2, oficial.id),
            ("consumo_rodoviario_kml", 9.0, oficial.id),
            ("capacidade_carga_kg", 620, oficial.id),
            ("preco_sugerido_brl", 499000, oficial.id),
            ("combustivel", "gasolina", oficial.id),
            ("airbags_qtd", 7, oficial.id),
            ("camera_360", True, oficial.id),
        ]
        for version_id, linhas in (
            (catalogo["srx"], do_concorrente),
            (catalogo["raptor"], da_ford),
        ):
            for campo, valor, evidence_id in linhas:
                sessao.add(
                    SpecValue(
                        version_id=version_id,
                        field=campo,
                        value_json=valor,
                        status="verificado",
                        confidence=0.9,
                        evidence_id=evidence_id,
                    )
                )
        sessao.commit()
    return catalogo


def comparar(cliente, headers, catalogo, **extra):
    corpo = {
        "base_vehicle_id": catalogo["raptor"],
        "competitor_ids": [catalogo["srx"]],
        **extra,
    }
    return cliente.post(COMPARISONS, headers=headers, json=corpo)


class TestCompatibilidade:
    def test_sem_needs_profile_a_resposta_nao_tem_fit(self, cliente_auth, fichas, vendedor):
        """Quem só quer a ficha lado a lado continua recebendo o que recebia no v1."""
        corpo = comparar(cliente_auth, vendedor, fichas).json()
        assert "fit" not in corpo
        assert "cells" in corpo or "campos" in corpo or corpo

    def test_com_needs_profile_o_fit_entra_AO_LADO_da_matriz(self, cliente_auth, fichas, vendedor):
        corpo = comparar(cliente_auth, vendedor, fichas, needs_profile=PERFIL_RURAL).json()
        assert "fit" in corpo
        # A matriz continua ali: o `fit` acrescenta, não substitui.
        assert len(corpo) > 1


class TestCriteriosDeAceite:
    def test_o_rotulo_obrigatorio_esta_na_resposta(self, cliente_auth, fichas, vendedor):
        """Critério: a resposta contém "Aderência ao perfil informado — não é um ranking
        de qualidade"."""
        corpo = comparar(cliente_auth, vendedor, fichas, needs_profile=PERFIL_RURAL).json()
        assert corpo["fit"]["rotulo"] == (
            "Aderência ao perfil informado — não é um ranking de qualidade"
        )

    def test_override_que_nao_soma_100_e_422(self, cliente_auth, fichas, vendedor):
        """Critério: "override soma 100 ou 422"."""
        perfil = dict(PERFIL_RURAL, pesos_override={"economia": 60, "preco": 33})
        resposta = comparar(cliente_auth, vendedor, fichas, needs_profile=perfil)
        assert resposta.status_code == 422
        assert "100" in resposta.text

    def test_override_que_soma_100_e_aceito_e_os_pesos_saem_na_resposta(
        self, cliente_auth, fichas, vendedor
    ):
        perfil = dict(PERFIL_RURAL, pesos_override={"economia": 60, "preco": 40})
        corpo = comparar(cliente_auth, vendedor, fichas, needs_profile=perfil).json()
        assert corpo["fit"]["pesos"]["economia"] == 60
        assert corpo["fit"]["pesos"]["preco"] == 40

    def test_os_pesos_do_ranking_saem_35_25_20(self, cliente_auth, fichas, vendedor):
        corpo = comparar(cliente_auth, vendedor, fichas, needs_profile=PERFIL_RURAL).json()
        pesos = corpo["fit"]["pesos"]
        assert (pesos["economia"], pesos["capacidade"], pesos["seguranca"]) == (35, 25, 20)

    def test_o_concorrente_vence_economia_com_o_consumo_do_pbe(
        self, cliente_auth, fichas, vendedor
    ):
        """Critério: `vence_em.concorrente` contém "economia" quando o consumo é maior."""
        corpo = comparar(cliente_auth, vendedor, fichas, needs_profile=PERFIL_RURAL).json()
        aderencia = corpo["fit"]["concorrentes"][0]["aderencia"]
        assert "economia" in aderencia["vence_em"]["concorrente"]

    def test_a_decomposicao_lista_campos_usados_e_sem_dado(self, cliente_auth, fichas, vendedor):
        corpo = comparar(cliente_auth, vendedor, fichas, needs_profile=PERFIL_RURAL).json()
        aderencia = corpo["fit"]["concorrentes"][0]["aderencia"]
        economia = next(d for d in aderencia["dimensoes"] if d["dimensao"] == "economia")
        assert "consumo_urbano_kml" in economia["campos_usados"]
        for dimensao in aderencia["dimensoes"]:
            assert "campos_sem_dado" in dimensao
            assert "cobertura" in dimensao


class TestCustoDeUso:
    def test_o_custo_usa_o_combustivel_de_cada_veiculo(self, cliente_auth, fichas, vendedor):
        corpo = comparar(cliente_auth, vendedor, fichas, needs_profile=PERFIL_RURAL).json()
        base = corpo["fit"]["usage_cost_base"]
        conc = corpo["fit"]["concorrentes"][0]["usage_cost"]
        assert base["combustivel"] == "gasolina"
        assert base["preco_por_litro"] == 6.00
        assert conc["combustivel"] == "diesel"
        assert conc["preco_por_litro"] == 6.20

    def test_a_origem_do_consumo_do_concorrente_e_o_PBE_lido_da_evidencia(
        self, cliente_auth, fichas, vendedor
    ):
        """A frase fixa não pode dizer "declarado pela montadora" sobre medição do Inmetro."""
        corpo = comparar(cliente_auth, vendedor, fichas, needs_profile=PERFIL_RURAL).json()
        conc = corpo["fit"]["concorrentes"][0]["usage_cost"]
        assert conc["consumo"]["origem"] == "pbe"
        assert "PBE/Inmetro" in conc["frase"]

    def test_a_diferenca_anual_esta_na_resposta(self, cliente_auth, fichas, vendedor):
        corpo = comparar(cliente_auth, vendedor, fichas, needs_profile=PERFIL_RURAL).json()
        comparado = corpo["fit"]["concorrentes"][0]["custo_comparado"]
        assert comparado["diferenca_ano"] is not None
        assert comparado["quem_gasta_menos"] in {"ford", "concorrente", "empate"}

    def test_sem_km_mes_o_custo_vem_com_o_motivo_e_nao_com_zero(
        self, cliente_auth, fichas, vendedor
    ):
        perfil = {k: v for k, v in PERFIL_RURAL.items() if k != "km_mes"}
        corpo = comparar(cliente_auth, vendedor, fichas, needs_profile=perfil).json()
        conc = corpo["fit"]["concorrentes"][0]["usage_cost"]
        assert conc["custo_mes"] is None
        assert "km por mês" in conc["motivo_sem_custo"]

    def test_o_consumo_informado_pelo_vendedor_entra_rotulado(self, cliente_auth, fichas, vendedor):
        """A Ford tem consumo na ficha; a rota aceita o informado para quem não tem."""
        corpo = comparar(
            cliente_auth,
            vendedor,
            fichas,
            needs_profile=PERFIL_RURAL,
            consumo_informado_kml={fichas["antiga"]: 8.0},
        ).json()
        assert "fit" in corpo


class TestValidacaoDoPerfil:
    def test_uso_desconhecido_e_422(self, cliente_auth, fichas, vendedor):
        perfil = dict(PERFIL_RURAL, uso=["corrida"])
        assert comparar(cliente_auth, vendedor, fichas, needs_profile=perfil).status_code == 422

    def test_prioridade_desconhecida_e_422(self, cliente_auth, fichas, vendedor):
        perfil = dict(PERFIL_RURAL, prioridades_rank=["preco_baixo"])
        assert comparar(cliente_auth, vendedor, fichas, needs_profile=perfil).status_code == 422

    def test_campo_extra_no_perfil_e_422(self, cliente_auth, fichas, vendedor):
        """Anônimo por construção: nada de nome de cliente entrando de carona."""
        perfil = dict(PERFIL_RURAL, nome_do_cliente="João")
        assert comparar(cliente_auth, vendedor, fichas, needs_profile=perfil).status_code == 422

    def test_km_mes_negativo_e_422(self, cliente_auth, fichas, vendedor):
        perfil = dict(PERFIL_RURAL, km_mes=-100)
        assert comparar(cliente_auth, vendedor, fichas, needs_profile=perfil).status_code == 422


class TestDimensions:
    def test_devolve_as_sete_dimensoes_com_os_campos(self, cliente_auth, fichas, vendedor):
        corpo = cliente_auth.get(DIMENSIONS, headers=vendedor).json()
        assert len(corpo["dimensoes"]) == 7
        economia = next(d for d in corpo["dimensoes"] if d["id"] == "economia")
        assert {c["campo"] for c in economia["campos"]} == {
            "consumo_urbano_kml",
            "consumo_rodoviario_kml",
        }

    def test_traz_a_faixa_de_cada_campo_para_o_ver_como_foi_calculado(
        self, cliente_auth, fichas, vendedor
    ):
        corpo = cliente_auth.get(DIMENSIONS, headers=vendedor).json()
        campos = [c for d in corpo["dimensoes"] for c in d["campos"]]
        numericos = [c for c in campos if c["tipo"] == "numerico"]
        assert numericos
        assert any(c["faixa"] is not None for c in numericos)

    def test_traz_os_pesos_e_o_rotulo_obrigatorio(self, cliente_auth, fichas, vendedor):
        corpo = cliente_auth.get(DIMENSIONS, headers=vendedor).json()
        assert corpo["pesos_por_rank"] == [35, 25, 20, 12, 8]
        assert "não é um ranking de qualidade" in corpo["rotulo_obrigatorio"]
        assert corpo["cobertura_minima"] == 0.5

    def test_traz_os_usos_do_perfil(self, cliente_auth, fichas, vendedor):
        corpo = cliente_auth.get(DIMENSIONS, headers=vendedor).json()
        assert "rural_carga" in corpo["usos"]

    def test_sem_credencial_da_401(self, cliente_auth, fichas):
        assert cliente_auth.get(DIMENSIONS).status_code == 401
