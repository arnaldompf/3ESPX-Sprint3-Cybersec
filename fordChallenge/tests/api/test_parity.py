"""WP-32 — `/comparables` e `/parity` pela API.

O que estes testes guardam é a honestidade da tabela quando ela chega na tela: o aviso de
comparabilidade vindo **junto** da matriz (e não numa segunda chamada, que deixaria a
tabela aparecer sem ressalva por um instante), o `desconhecido` contado em vez de filtrado,
e a flag dos 1.000 kg saindo com o texto fixo e a fonte.

O papel `vendedor` **tem** acesso aqui, ao contrário do Radar: a matriz de paridade é
exatamente a tela de que ele precisa no showroom, e o que fica escondido dele (tier,
confiança) é filtrado na apresentação, não no acesso.
"""

from __future__ import annotations

import datetime as dt

import pytest

from api.app.models import Role

COMPARABLES = "/api/v1/comparables"
PARITY = "/api/v1/parity"


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def vendedor(criar_usuario, logar):
    criar_usuario("vendedor@suno.example.com", Role.VENDEDOR)
    return logar("vendedor@suno.example.com")


@pytest.fixture
def fichas(catalogo):
    """Dá ficha aos dois lados, para os quatro estados aparecerem de verdade.

    A Raptor já vem do catálogo com `potencia_cv` e `torque_nm`. Aqui a Hilux recebe os
    campos que produzem cada estado: potência menor (vantagem da Ford), preço menor (gap),
    torque igual dentro da tolerância (paridade) e carga de 1.005 kg (a flag dos 1.000 kg).
    `potencia_rpm` fica de fora dos dois lados de propósito — é o `desconhecido`.
    """
    from api.app.db import session_scope
    from api.app.models import Evidence, SpecValue

    with session_scope() as sessao:
        evidencia = Evidence(
            source_url="https://www.toyota.com.br/hilux/ficha.pdf",
            tier=1,
            quote="Capacidade de carga 1.005 kg",
            captured_at=dt.datetime(2026, 9, 1),
            page=3,
        )
        sessao.add(evidencia)
        sessao.flush()

        campos = [
            ("potencia_cv", 204, "cv"),
            ("torque_nm", 583, "Nm"),
            ("preco_sugerido_brl", 348790, "BRL"),
            ("capacidade_carga_kg", 1005, "kg"),
            ("combustivel", "diesel", None),
            ("segmento", "picape media", None),
            ("carroceria", "cabine dupla", None),
        ]
        for campo, valor, unidade in campos:
            sessao.add(
                SpecValue(
                    version_id=catalogo["srx"],
                    field=campo,
                    value_json=valor,
                    unit=unidade,
                    status="verificado",
                    confidence=0.95,
                    evidence_id=evidencia.id,
                )
            )
        # A Raptor ganha preço e combustível, para o par ficar avaliável nos dois lados.
        for campo, valor, unidade in [
            ("preco_sugerido_brl", 499000, "BRL"),
            ("combustivel", "gasolina", None),
            ("segmento", "picape media", None),
            ("carroceria", "cabine dupla", None),
        ]:
            sessao.add(
                SpecValue(
                    version_id=catalogo["raptor"],
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


def _matriz(cliente, headers, catalogo, **params):
    consulta = {
        "ford_version": catalogo["raptor"],
        "competitors": catalogo["srx"],
        **params,
    }
    query = "&".join(f"{k}={v}" for k, v in consulta.items())
    return cliente.get(f"{PARITY}?{query}", headers=headers)


class TestOsQuatroEstados:
    def test_a_matriz_traz_os_quatro_estados_contados(self, cliente_auth, fichas, analista):
        corpo = _matriz(cliente_auth, analista, fichas).json()
        contagem = corpo["colunas"][0]["contagem"]
        assert contagem["vantagem"] >= 1
        assert contagem["gap"] >= 1
        assert contagem["paridade"] >= 1
        assert contagem["desconhecido"] >= 1
        assert contagem["total"] == sum(
            contagem[e] for e in ("vantagem", "paridade", "gap", "desconhecido")
        )

    def test_o_denominador_honesto_exclui_o_desconhecido(self, cliente_auth, fichas, analista):
        contagem = _matriz(cliente_auth, analista, fichas).json()["colunas"][0]["contagem"]
        assert contagem["comparados"] == contagem["total"] - contagem["desconhecido"]

    def test_campo_sem_dado_de_um_lado_vem_DESCONHECIDO(self, cliente_auth, fichas, analista):
        """Critério de aceite, pela API: `potencia_rpm` sem valor não é `gap`."""
        celulas = _matriz(cliente_auth, analista, fichas).json()["colunas"][0]["celulas"]
        rpm = next(c for c in celulas if c["campo"] == "potencia_rpm")
        assert rpm["estado"] == "desconhecido"
        assert rpm["motivo_tipo"] == "sem_dado_nos_dois"

    def test_o_desconhecido_NAO_e_filtrado_da_resposta(self, cliente_auth, fichas, analista):
        """A tentação é limpar a tabela; seria esconder a lacuna a fechar."""
        celulas = _matriz(cliente_auth, analista, fichas).json()["colunas"][0]["celulas"]
        assert any(c["estado"] == "desconhecido" for c in celulas)

    def test_a_legenda_dos_quatro_estados_vem_na_resposta(self, cliente_auth, fichas, analista):
        """A mesma frase serve tela e PDF: duas legendas divergiriam na primeira revisão."""
        legenda = _matriz(cliente_auth, analista, fichas).json()["legenda"]
        assert set(legenda) == {"vantagem", "paridade", "gap", "desconhecido"}
        assert "nunca" in legenda["desconhecido"].lower()

    def test_a_celula_traz_o_id_da_evidencia_dos_dois_lados(self, cliente_auth, fichas, analista):
        celulas = _matriz(cliente_auth, analista, fichas).json()["colunas"][0]["celulas"]
        potencia = next(c for c in celulas if c["campo"] == "potencia_cv")
        assert potencia["evidence_id_ford"]
        assert potencia["evidence_id_concorrente"]


class TestAvisoDeComparabilidade:
    def test_vem_DENTRO_da_coluna_da_matriz(self, cliente_auth, fichas, analista):
        """Numa segunda chamada, a tabela apareceria sem a ressalva por um instante."""
        coluna = _matriz(cliente_auth, analista, fichas).json()["colunas"][0]
        assert coluna["comparabilidade"]["comparavel"] is False
        assert coluna["comparabilidade"]["aviso"]

    def test_o_resumo_e_k_de_n(self, cliente_auth, fichas, analista):
        coluna = _matriz(cliente_auth, analista, fichas).json()["colunas"][0]
        assert "/" in coluna["comparabilidade"]["resumo"]
        assert "%" not in coluna["comparabilidade"]["resumo"]

    def test_a_versao_dos_criterios_esta_na_resposta(self, cliente_auth, fichas, analista):
        corpo = _matriz(cliente_auth, analista, fichas).json()
        assert corpo["versao_dos_criterios"]


class TestFiltroPorDimensao:
    def test_filtra_por_grupo_do_schema(self, cliente_auth, fichas, analista):
        corpo = _matriz(cliente_auth, analista, fichas, grupos="motorizacao").json()
        grupos = {c["grupo"] for c in corpo["colunas"][0]["celulas"]}
        assert grupos == {"motorizacao"}

    def test_dimensao_inexistente_e_422_com_a_lista_das_validas(
        self, cliente_auth, fichas, analista
    ):
        resposta = _matriz(cliente_auth, analista, fichas, grupos="inventada")
        assert resposta.status_code == 422
        assert "motorizacao" in resposta.json()["detail"]


class TestFlagDe1000kg:
    def test_a_hilux_com_1005_kg_liga_a_flag_com_o_texto_fixo(self, cliente_auth, fichas, analista):
        flag = _matriz(cliente_auth, analista, fichas).json()["colunas"][0]["flag_de_carga"]
        assert flag["aplicavel"] is True
        assert flag["valor"] is True
        assert flag["etiqueta"] == "INFERENCIA"
        assert "≥ 1.000 kg" in flag["texto"]
        assert "confirmar enquadramento fiscal com a Ford" in flag["texto"]

    def test_a_fonte_entra_no_texto(self, cliente_auth, fichas, analista):
        """A frase existe para alguém poder conferir o número. Sem fonte, é inútil."""
        flag = _matriz(cliente_auth, analista, fichas).json()["colunas"][0]["flag_de_carga"]
        assert "toyota.com.br" in flag["texto"]

    def test_o_texto_nao_fala_de_imposto(self, cliente_auth, fichas, analista):
        flag = _matriz(cliente_auth, analista, fichas).json()["colunas"][0]["flag_de_carga"]
        for proibido in ("IPI", "ICMS", "imposto", "isento"):
            assert proibido.lower() not in flag["texto"].lower()

    def test_sem_carga_a_flag_e_indeterminada(self, cliente_auth, fichas, analista):
        """A Raptor não tem carga na ficha de teste: a flag não é falsa, é não avaliável."""
        flag = _matriz(cliente_auth, analista, fichas).json()["flag_de_carga_ford"]
        assert flag["aplicavel"] is False
        assert flag["valor"] is None
        assert "não é avaliável" in flag["motivo"]


class TestComparables:
    def test_lista_as_versoes_ford_ordenadas_por_criterios_atendidos(
        self, cliente_auth, fichas, analista
    ):
        corpo = cliente_auth.get(
            f"{COMPARABLES}?version_id={fichas['srx']}", headers=analista
        ).json()
        assert len(corpo) >= 1
        atendidos = [c["comparabilidade"]["criterios_atendidos"] for c in corpo]
        assert atendidos == sorted(atendidos, reverse=True)

    def test_o_par_reprovado_continua_na_lista_com_o_aviso(self, cliente_auth, fichas, analista):
        """Esconder Raptor × Hilux tiraria do analista uma pergunta legítima."""
        corpo = cliente_auth.get(
            f"{COMPARABLES}?version_id={fichas['srx']}", headers=analista
        ).json()
        raptor = next(c for c in corpo if c["version_id"] == fichas["raptor"])
        assert raptor["comparabilidade"]["comparavel"] is False
        assert raptor["comparabilidade"]["aviso"]

    def test_pode_pedir_so_os_comparaveis(self, cliente_auth, fichas, analista):
        corpo = cliente_auth.get(
            f"{COMPARABLES}?version_id={fichas['srx']}&incluir_nao_comparaveis=false",
            headers=analista,
        ).json()
        assert all(c["comparabilidade"]["comparavel"] for c in corpo)

    def test_a_propria_versao_nao_entra_como_candidata(self, cliente_auth, fichas, analista):
        corpo = cliente_auth.get(
            f"{COMPARABLES}?version_id={fichas['raptor']}", headers=analista
        ).json()
        assert all(c["version_id"] != fichas["raptor"] for c in corpo)

    def test_versao_inexistente_da_404(self, cliente_auth, fichas, analista):
        resposta = cliente_auth.get(f"{COMPARABLES}?version_id=nao-existe", headers=analista)
        assert resposta.status_code == 404


class TestPermissoesEValidacao:
    def test_o_vendedor_VE_a_matriz(self, cliente_auth, fichas, vendedor):
        """Ao contrário do Radar: é a tela do showroom."""
        assert _matriz(cliente_auth, vendedor, fichas).status_code == 200

    def test_o_vendedor_ve_os_comparaveis(self, cliente_auth, fichas, vendedor):
        resposta = cliente_auth.get(f"{COMPARABLES}?version_id={fichas['srx']}", headers=vendedor)
        assert resposta.status_code == 200

    def test_sem_credencial_da_401(self, cliente_auth, fichas):
        assert _matriz(cliente_auth, None, fichas).status_code == 401
        assert cliente_auth.get(f"{COMPARABLES}?version_id=x").status_code == 401

    def test_concorrente_vazio_e_422(self, cliente_auth, fichas, analista):
        resposta = _matriz(cliente_auth, analista, fichas, competitors="")
        assert resposta.status_code == 422

    def test_a_referencia_nao_pode_ser_o_concorrente(self, cliente_auth, fichas, analista):
        resposta = _matriz(cliente_auth, analista, fichas, competitors=fichas["raptor"])
        assert resposta.status_code == 422
        assert "referência" in resposta.json()["detail"]

    def test_muitos_concorrentes_e_422_com_o_teto(self, cliente_auth, fichas, analista):
        muitos = ",".join(f"v{i}" for i in range(9))
        resposta = _matriz(cliente_auth, analista, fichas, competitors=muitos)
        assert resposta.status_code == 422
        assert "6" in resposta.json()["detail"]

    def test_concorrente_inexistente_da_404(self, cliente_auth, fichas, analista):
        resposta = _matriz(cliente_auth, analista, fichas, competitors="nao-existe")
        assert resposta.status_code == 404
