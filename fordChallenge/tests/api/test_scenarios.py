"""WP-35 — `POST /scenarios` pela API.

O critério de aceite que **só** pode ser verificado aqui é o segundo:
`test_nenhum_registro_novo_em_spec_values`. O motor não conhece banco, mas a rota conhece —
e é a rota que teria de resistir à tentação de "salvar o cenário para o usuário não perder".

O resto cobre o que a tela consome (os dois painéis, o rótulo em cada um, o aviso de
comparabilidade nas duas colunas) e o que a API recusa com o motivo por extenso: cenário
sem Ford, cenário sem concorrente, `delta_pct` absurdo, campo que não existe.
"""

from __future__ import annotations

import pytest

from api.app.models import Role

CENARIOS = "/api/v1/scenarios"


@pytest.fixture
def vendedor(criar_usuario, logar):
    criar_usuario("vendedor@suno.example.com", Role.VENDEDOR)
    return logar("vendedor@suno.example.com")


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def precos(catalogo):
    """Dá preço às duas versões: sem preço não há o que simular em −5%.

    A Ranger a 410 mil e a Hilux a 420 mil — a mesma razão do teste do motor: com a Ford a
    400 mil, o −5% da spec cairia dentro da tolerância de 0,5% do preço e o estado não
    inverteria.
    """
    from api.app.db import session_scope
    from api.app.models import SpecValue

    with session_scope() as sessao:
        for version_id, valor in (
            (catalogo["raptor"], 410000),
            (catalogo["srx"], 420000),
        ):
            sessao.add(
                SpecValue(
                    version_id=version_id,
                    field="preco_sugerido_brl",
                    value_json=valor,
                    unit="BRL",
                    status="verificado",
                    confidence=0.9,
                    evidence_id=catalogo["evidencia"],
                )
            )
        sessao.commit()
    return catalogo


def contar_spec_values() -> int:
    from sqlmodel import select

    from api.app.db import session_scope
    from api.app.models import SpecValue

    with session_scope() as sessao:
        return len(sessao.exec(select(SpecValue)).all())


def corpo_de(catalogo, **extra):
    return {
        "base_version_ids": [catalogo["raptor"], catalogo["srx"]],
        "overrides": [
            {"version_id": catalogo["srx"], "campo": "preco_sugerido_brl", "delta_pct": -5}
        ],
        **extra,
    }


class TestCriteriosDeAceite:
    def test_nenhum_registro_novo_em_spec_values(self, cliente_auth, precos, analista):
        """Critério: override de −5% e **nenhum** registro novo em `spec_values`.

        É o critério que a rota poderia quebrar sozinha: guardar o cenário "para o usuário
        não perder" transformaria uma hipótese em linha de banco, e a próxima leitura da
        ficha não saberia distinguir as duas.
        """
        antes = contar_spec_values()
        resposta = cliente_auth.post(CENARIOS, json=corpo_de(precos), headers=analista)
        assert resposta.status_code == 200, resposta.text
        assert contar_spec_values() == antes

    def test_a_resposta_traz_os_diffs_de_paridade(self, cliente_auth, precos, analista):
        """Critério: a resposta traz os estados de paridade que mudaram."""
        corpo = cliente_auth.post(CENARIOS, json=corpo_de(precos), headers=analista).json()
        diff = corpo["diffs"][0]
        preco = next(m for m in diff["paridade"] if m["campo"] == "preco_sugerido_brl")
        assert preco["antes"] == "vantagem"
        assert preco["depois"] == "gap"
        assert preco["motivo_depois"]

    def test_a_resposta_traz_a_materialidade_do_cenario(self, cliente_auth, precos, analista):
        corpo = cliente_auth.post(CENARIOS, json=corpo_de(precos), headers=analista).json()
        materialidade = corpo["diffs"][0]["materialidade"]
        assert materialidade["materiality"] in ("ALTA", "MEDIA", "BAIXA", "RUIDO")
        assert materialidade["rules_fired"]
        assert materialidade["is_simulated"] is True

    def test_o_rotulo_de_simulacao_esta_em_todos_os_paineis_do_cenario(
        self, cliente_auth, precos, analista
    ):
        """Critério: a faixa "SIMULAÇÃO — não é dado observado" visível em **todos**."""
        corpo = cliente_auth.post(CENARIOS, json=corpo_de(precos), headers=analista).json()
        assert corpo["is_simulation"] is True
        assert corpo["rotulo"] == "SIMULAÇÃO — não é dado observado"
        assert corpo["cenario"]
        for painel in corpo["cenario"]:
            assert painel["is_simulation"] is True
            assert painel["rotulo_simulacao"] == corpo["rotulo"]
        # E o painel da realidade **não** leva o rótulo: ele é FATO.
        for painel in corpo["atual"]:
            assert painel["is_simulation"] is False
            assert painel["rotulo_simulacao"] == ""

    def test_a_origem_do_numero_viaja_na_resposta(self, cliente_auth, precos, analista):
        """A nota da spec: de onde veio o −5%? "do usuário"."""
        corpo = cliente_auth.post(CENARIOS, json=corpo_de(precos), headers=analista).json()
        assert "usuário" in corpo["origem_dos_numeros"]
        aplicado = corpo["overrides_aplicados"][0]
        assert aplicado["antes"] == 420000
        assert aplicado["depois"] == 399000
        assert "usuário" in aplicado["origem"]


class TestOQueATelaConsome:
    def test_os_dois_paineis_vem_com_a_contagem(self, cliente_auth, precos, analista):
        corpo = cliente_auth.post(CENARIOS, json=corpo_de(precos), headers=analista).json()
        atual = corpo["atual"][0]["coluna"]["contagem"]
        cenario = corpo["cenario"][0]["coluna"]["contagem"]
        assert atual["total"] == cenario["total"]
        assert atual["vantagem"] - 1 == cenario["vantagem"]
        assert atual["gap"] + 1 == cenario["gap"]

    def test_o_aviso_de_comparabilidade_esta_nas_duas_colunas(self, cliente_auth, precos, analista):
        """Presente só no cenário, o aviso pareceria ter mudado com a hipótese."""
        corpo = cliente_auth.post(CENARIOS, json=corpo_de(precos), headers=analista).json()
        for painel in (corpo["atual"][0], corpo["cenario"][0]):
            comparabilidade = painel["coluna"]["comparabilidade"]
            assert comparabilidade is not None
            assert comparabilidade["resumo"]
            assert comparabilidade["aviso"]
            assert "não torna um par comparável" in comparabilidade["escopo"]

    def test_a_ford_de_referencia_vem_identificada(self, cliente_auth, precos, analista):
        corpo = cliente_auth.post(CENARIOS, json=corpo_de(precos), headers=analista).json()
        assert corpo["ford"]["version_id"] == precos["raptor"]
        assert corpo["ford"]["rotulo"].startswith("Ford Ranger")

    def test_sem_perfil_a_aderencia_diz_por_que_falta(self, cliente_auth, precos, analista):
        corpo = cliente_auth.post(CENARIOS, json=corpo_de(precos), headers=analista).json()
        assert corpo["atual"][0]["aderencia"] is None
        assert "perfil" in corpo["motivo_sem_aderencia"]

    def test_com_perfil_os_dois_lados_ganham_aderencia(self, cliente_auth, precos, analista):
        corpo = cliente_auth.post(
            CENARIOS,
            json=corpo_de(precos, needs_profile={"prioridades_rank": ["preco", "economia"]}),
            headers=analista,
        ).json()
        assert corpo["atual"][0]["aderencia"] is not None
        assert corpo["cenario"][0]["aderencia"] is not None
        assert "não é um ranking de qualidade" in corpo["cenario"][0]["aderencia"]["rotulo"]

    def test_cenario_sem_override_e_igual_a_realidade_e_diz_isso(
        self, cliente_auth, precos, analista
    ):
        corpo = cliente_auth.post(
            CENARIOS,
            json={"base_version_ids": [precos["raptor"], precos["srx"]], "overrides": []},
            headers=analista,
        ).json()
        assert corpo["diffs"][0]["paridade"] == []
        assert corpo["diffs"][0]["materialidade"] is None
        assert "nenhum override" in corpo["diffs"][0]["motivo_sem_materialidade"]

    def test_a_rota_de_campos_diz_o_que_o_simulador_aceita(self, cliente_auth, precos, analista):
        """Sem ela, a tela teria a própria lista — e ofereceria slider que a API recusa."""
        corpo = cliente_auth.get(f"{CENARIOS}/fields", headers=analista).json()
        assert "preco_sugerido_brl" in corpo["delta_pct"]["campos"]
        assert corpo["delta_pct"]["minimo"] < 0 < corpo["delta_pct"]["maximo"]
        assert corpo["rotulo"] == "SIMULAÇÃO — não é dado observado"
        assert "usuário" in corpo["origem_dos_numeros"]
        # `airbags_qtd` fica fora: "6,3 airbags" é número que não existe no mundo.
        assert "airbags_qtd" not in corpo["delta_pct"]["campos"]


class TestOQueAApiRecusa:
    def test_cenario_sem_versao_ford_da_422_com_o_motivo(
        self, cliente_auth, precos, analista, catalogo
    ):
        resposta = cliente_auth.post(
            CENARIOS,
            json={"base_version_ids": [catalogo["srx"], catalogo["antiga"]], "overrides": []},
            headers=analista,
        )
        assert resposta.status_code == 422
        assert "exatamente uma versão Ford" in resposta.json()["detail"]

    def test_cenario_sem_concorrente_da_422(self, cliente_auth, precos, analista, catalogo):
        """Duas Ford é "exatamente uma Ford" reprovado: o cenário compara com alguém."""
        from api.app.db import session_scope
        from api.app.models import VehicleModel, Version

        with session_scope() as sessao:
            modelo = sessao.get(VehicleModel, catalogo["model_ranger"])
            outra = Version(model_id=modelo.id, nome_exato="XLS 2.2 4x2", ano_modelo=2026)
            sessao.add(outra)
            sessao.commit()
            outra_id = outra.id

        resposta = cliente_auth.post(
            CENARIOS,
            json={"base_version_ids": [catalogo["raptor"], outra_id], "overrides": []},
            headers=analista,
        )
        assert resposta.status_code == 422
        assert "Ford" in resposta.json()["detail"]

    def test_delta_pct_absurdo_da_422_com_a_faixa(self, cliente_auth, precos, analista):
        resposta = cliente_auth.post(
            CENARIOS,
            json={
                "base_version_ids": [precos["raptor"], precos["srx"]],
                "overrides": [
                    {
                        "version_id": precos["srx"],
                        "campo": "preco_sugerido_brl",
                        "delta_pct": 900,
                    }
                ],
            },
            headers=analista,
        )
        assert resposta.status_code == 422
        assert "fora da faixa" in resposta.json()["detail"]

    def test_campo_inexistente_da_422_em_vez_de_criar(self, cliente_auth, precos, analista):
        resposta = cliente_auth.post(
            CENARIOS,
            json={
                "base_version_ids": [precos["raptor"], precos["srx"]],
                "overrides": [
                    {"version_id": precos["srx"], "campo": "cor_do_teto", "novo_valor": "azul"}
                ],
            },
            headers=analista,
        )
        assert resposta.status_code == 422
        assert "não é campo canônico" in resposta.json()["detail"]

    def test_duas_formas_de_override_ao_mesmo_tempo_da_422(self, cliente_auth, precos, analista):
        resposta = cliente_auth.post(
            CENARIOS,
            json={
                "base_version_ids": [precos["raptor"], precos["srx"]],
                "overrides": [
                    {
                        "version_id": precos["srx"],
                        "campo": "potencia_cv",
                        "delta_pct": -5,
                        "novo_valor": 200,
                    }
                ],
            },
            headers=analista,
        )
        assert resposta.status_code == 422
        assert "exatamente um" in resposta.json()["detail"]

    def test_versao_inexistente_da_404(self, cliente_auth, precos, analista):
        resposta = cliente_auth.post(
            CENARIOS,
            json={"base_version_ids": [precos["raptor"], "nao-existe"], "overrides": []},
            headers=analista,
        )
        assert resposta.status_code == 404

    def test_override_de_versao_fora_do_cenario_da_422(self, cliente_auth, precos, analista):
        resposta = cliente_auth.post(
            CENARIOS,
            json={
                "base_version_ids": [precos["raptor"], precos["srx"]],
                "overrides": [
                    {"version_id": precos["antiga"], "campo": "potencia_cv", "novo_valor": 1}
                ],
            },
            headers=analista,
        )
        assert resposta.status_code == 422
        assert "não está no cenário" in resposta.json()["detail"]

    def test_campo_extra_no_corpo_da_422(self, cliente_auth, precos, analista):
        """`extra="forbid"`: campo desconhecido não é ignorado em silêncio."""
        resposta = cliente_auth.post(
            CENARIOS,
            json=corpo_de(precos, salvar_como="cenario A"),
            headers=analista,
        )
        assert resposta.status_code == 422

    def test_perfil_com_dado_pessoal_e_recusado(self, cliente_auth, precos, analista):
        """O `NeedsProfile` é anônimo por construção (`extra="forbid"`)."""
        resposta = cliente_auth.post(
            CENARIOS,
            json=corpo_de(precos, needs_profile={"prioridades_rank": ["preco"], "nome": "João"}),
            headers=analista,
        )
        assert resposta.status_code == 422


class TestPermissoes:
    def test_o_vendedor_pode_simular(self, cliente_auth, precos, vendedor):
        """Deliberado: "e se a Hilux baixar 5%?" é a pergunta do cliente no showroom."""
        resposta = cliente_auth.post(CENARIOS, json=corpo_de(precos), headers=vendedor)
        assert resposta.status_code == 200

    def test_sem_token_da_401(self, cliente_auth, precos):
        assert cliente_auth.post(CENARIOS, json=corpo_de(precos)).status_code == 401
