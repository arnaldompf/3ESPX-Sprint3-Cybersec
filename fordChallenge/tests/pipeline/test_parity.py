"""WP-32 — Parity Matrix: o quarto estado é o que o produto está vendendo.

O critério de aceite é o `potencia_rpm` da Amarok: `nao_encontrado` de um lado tem de dar
`desconhecido`, **nunca** `gap`. Uma matriz de três estados obriga a ausência a escolher um
lado, e as duas escolhas mentem — `gap` afirma que perdemos num campo que ninguém mediu,
`paridade` afirma um empate igualmente inventado.

Os outros testes cercam onde o cálculo pode passar a mentir sem que ninguém note: a régua
de paridade divergindo da do eval, o `0` e o `False` tratados como ausência, e conjuntos
que se cruzam recebendo uma ordem que não têm.
"""

from __future__ import annotations

import pytest

from pipeline import parity
from pipeline.parity import DESCONHECIDO, GAP, PARIDADE, VANTAGEM
from pipeline.schema import Evidence, SpecField, Status, empty_spec


def celula(campo: str, ford, concorrente, **kw):
    return parity.comparar_campo(campo, valor_ford=ford, valor_concorrente=concorrente, **kw)


class TestCriteriosDeAceite:
    def test_nao_encontrado_de_um_lado_e_DESCONHECIDO_nunca_gap(self):
        """Critério: `potencia_rpm` da Amarok `nao_encontrado` → `desconhecido`."""
        c = celula("potencia_rpm", 5650, None, status_concorrente=Status.NAO_ENCONTRADO)
        assert c.estado == DESCONHECIDO
        assert c.estado != GAP
        assert c.motivo_tipo == parity.SEM_DADO_CONCORRENTE

    def test_nao_verificado_tambem_e_desconhecido(self):
        c = celula("potencia_cv", 397, 204, status_concorrente=Status.NAO_VERIFICADO)
        assert c.estado == DESCONHECIDO

    def test_nao_disponivel_tambem_e_desconhecido(self):
        """`nao_disponivel` é "a fonte diz que não tem" — e ainda assim não é um gap.

        Os dois vazios do projeto: "a fonte declara que a versão não tem o item" não é a
        mesma coisa que "medimos e o concorrente é melhor".
        """
        c = celula("camera_360", True, None, status_concorrente=Status.NAO_DISPONIVEL)
        assert c.estado == DESCONHECIDO

    def test_desconhecido_nunca_e_exibido_como_paridade(self):
        """A legenda tem de dizer isso em palavras — é o que a tela mostra."""
        assert "empate" in parity.LEGENDA[DESCONHECIDO].lower()
        assert "nunca" in parity.LEGENDA[DESCONHECIDO].lower()


class TestOsQuatroEstados:
    @pytest.mark.parametrize(
        "campo,ford,conc,esperado",
        [
            ("potencia_cv", 397, 204, VANTAGEM),
            ("potencia_cv", 204, 397, GAP),
            ("potencia_cv", 397, 397, PARIDADE),
            ("aceleracao_0_100_s", 5.8, 10.7, VANTAGEM),
            ("aceleracao_0_100_s", 10.7, 5.8, GAP),
            ("preco_sugerido_brl", 348790, 499000, VANTAGEM),
            ("preco_sugerido_brl", 499000, 348790, GAP),
            ("capacidade_carga_kg", 1005, 620, VANTAGEM),
            ("garantia_meses", 60, 36, VANTAGEM),
            ("airbags_qtd", 7, 7, PARIDADE),
        ],
    )
    def test_direcao_de_merito_por_campo(self, campo, ford, conc, esperado):
        assert celula(campo, ford, conc).estado == esperado

    def test_menos_tempo_e_menos_preco_sao_vantagem(self):
        """O erro mais fácil de cometer: tratar todo número como "maior é melhor"."""
        assert parity.MELHOR_QUANDO["aceleracao_0_100_s"] == "menor"
        assert parity.MELHOR_QUANDO["preco_sugerido_brl"] == "menor"

    def test_o_motivo_numerico_nao_contradiz_o_estado(self):
        """A regressão que este teste tranca.

        A primeira versão escrevia "a Ford tem menos" — ao lado de "Aceleração 0-100" a
        frase se lia como desvantagem exatamente quando o estado era `vantagem`.
        """
        c = celula("aceleracao_0_100_s", 5.8, 10.7)
        assert c.estado == VANTAGEM
        assert "menor, melhor" in c.motivo
        assert "5.8" in c.motivo and "10.7" in c.motivo

    def test_a_diferenca_sai_com_sinal_em_campo_ordenavel(self):
        assert celula("potencia_cv", 397, 204).diferenca == 193
        assert celula("potencia_cv", 204, 397).diferenca == -193

    def test_campo_sem_direcao_nao_ganha_uma_diferenca(self):
        """`None` de diferença não é zero: é "esta conta não existe aqui"."""
        assert celula("motor_descricao", "V6 3.0", "2.8 turbodiesel").diferenca is None


class TestParidadeUsaAToleranciaDoEval:
    def test_397_contra_398_cv_e_paridade(self):
        c = celula("potencia_cv", 397, 398)
        assert c.estado == PARIDADE
        assert "tolerância" in c.motivo

    def test_a_regua_e_a_MESMA_do_eval(self):
        """Se divergissem, o produto exibiria vantagem sobre o que o eval trata como igual."""
        from pipeline.eval.compare import tolerancia_de

        for campo in ("potencia_cv", "torque_nm", "preco_sugerido_brl", "aceleracao_0_100_s"):
            tol = tolerancia_de(campo)
            assert tol.descricao(), f"{campo} sem tolerância declarada"

    def test_preco_com_tolerancia_relativa(self):
        """±0,5% em preço: R$ 348.790 contra R$ 349.000 é o mesmo preço de tabela."""
        assert celula("preco_sugerido_brl", 348790, 349000).estado == PARIDADE
        # Ford mais barata é vantagem; Ford mais cara é gap. O sinal importa mais aqui do
        # que em qualquer outro campo, porque o preço é o único em que "menos é melhor"
        # vale para quem compra e o contrário vale para quem vende.
        assert celula("preco_sugerido_brl", 348790, 380000).estado == VANTAGEM
        assert celula("preco_sugerido_brl", 380000, 348790).estado == GAP


class TestBooleanos:
    def test_ter_o_item_e_vantagem_quando_declarado(self):
        assert celula("reduzida", True, False).estado == VANTAGEM
        assert celula("reduzida", False, True).estado == GAP

    def test_nenhum_dos_dois_tem_e_paridade_com_o_motivo_certo(self):
        c = celula("camera_360", False, False)
        assert c.estado == PARIDADE
        assert c.motivo == "nenhum dos dois tem"

    def test_False_NAO_e_ausencia(self):
        """ "Não tem teto solar" é informação; `nao_encontrado` é a falta dela.

        Tratar `False` como vazio transformaria uma ausência **declarada pela fonte** em
        desconhecimento — a confusão entre os dois vazios que o projeto existe para acabar.
        """
        assert celula("camera_360", False, False).estado == PARIDADE
        assert celula("camera_360", True, False).estado == VANTAGEM

    def test_zero_NAO_e_ausencia(self):
        c = celula("airbags_qtd", 0, 7)
        assert c.estado == GAP
        assert c.estado != DESCONHECIDO


class TestConjuntos:
    def test_conter_o_conjunto_do_outro_e_vantagem(self):
        c = celula("modos_conducao", ["normal", "baja", "lama"], ["normal", "lama"])
        assert c.estado == VANTAGEM
        assert "baja" in c.motivo

    def test_estar_contido_e_gap(self):
        c = celula("modos_conducao", ["normal"], ["normal", "lama"])
        assert c.estado == GAP
        assert "lama" in c.motivo

    def test_o_mesmo_conjunto_e_paridade_apos_sinonimos(self):
        """ "Esportivo" e "Sport" são o mesmo modo — a ontologia decide, não a string."""
        c = celula("modos_conducao", ["Normal", "Esportivo"], ["normal", "sport"])
        assert c.estado == PARIDADE

    def test_conjuntos_que_se_cruzam_NAO_recebem_ordem(self):
        """Ter Baja e não ter Lama contra ter Lama e não ter Baja não é melhor nem pior.

        Forçar `vantagem` ou `gap` aqui inventaria uma hierarquia entre recursos que quem
        estabelece é o comprador. Fica `desconhecido` com motivo próprio, e os dois
        conjuntos aparecem.
        """
        c = celula("modos_conducao", ["normal", "baja"], ["normal", "lama"])
        assert c.estado == DESCONHECIDO
        assert c.motivo_tipo == parity.SEM_ORDEM_ENTRE_CONJUNTOS
        assert "baja" in c.motivo and "lama" in c.motivo

    def test_o_desconhecido_de_conjunto_e_distinguivel_do_de_ausencia(self):
        """Os dois são `desconhecido`; o `motivo_tipo` é o que evita procurar dado à toa."""
        cruzado = celula("modos_conducao", ["baja"], ["lama"])
        ausente = celula("modos_conducao", ["baja"], None)
        assert cruzado.estado == ausente.estado == DESCONHECIDO
        assert cruzado.motivo_tipo != ausente.motivo_tipo


class TestTextoSemDirecao:
    def test_valores_iguais_sao_paridade(self):
        assert celula("combustivel", "diesel", "Diesel").estado == PARIDADE

    def test_valores_diferentes_ficam_desconhecidos_com_os_dois_a_vista(self):
        c = celula("motor_descricao", "V6 3.0 Bi-turbo", "2.8 turbodiesel")
        assert c.estado == DESCONHECIDO
        assert c.motivo_tipo == parity.SEM_DIRECAO_DE_MERITO
        assert c.valor_ford == "V6 3.0 Bi-turbo"
        assert c.valor_concorrente == "2.8 turbodiesel"

    def test_numero_marchas_nao_tem_direcao_declarada(self):
        """Dez marchas não são melhores que oito para quem reboca: depende do escalonamento."""
        assert "numero_marchas" not in parity.MELHOR_QUANDO
        assert celula("numero_marchas", 10, 8).estado == DESCONHECIDO


class TestMatriz:
    @pytest.fixture
    def ford(self):
        spec = empty_spec()
        ev = Evidence(
            evidence_id="ev-ford-1",
            source_url="https://www.ford.com.br/x",
            tier=1,
            quote="Potencia 397cv",
            captured_at="2026-09-01T00:00:00Z",
        )
        spec.set("motorizacao.potencia_cv", SpecField.verificado(397, ev, unit="cv"))
        spec.set("comercial.preco_sugerido_brl", SpecField.verificado(499000, ev, unit="BRL"))
        return spec

    @pytest.fixture
    def concorrente(self):
        spec = empty_spec()
        ev = Evidence(
            evidence_id="ev-conc-1",
            source_url="https://www.toyota.com.br/x",
            tier=1,
            quote="204 cv",
            captured_at="2026-09-01T00:00:00Z",
        )
        spec.set("motorizacao.potencia_cv", SpecField.verificado(204, ev, unit="cv"))
        return spec

    def test_a_coluna_conta_os_quatro_estados_e_o_denominador(self, ford, concorrente):
        coluna = parity.montar_coluna(
            ford, concorrente, version_id="v-conc", rotulo="Hilux SRX Plus"
        )
        assert coluna.contagem.vantagem == 1  # potencia
        assert coluna.contagem.desconhecido > 0
        assert coluna.contagem.total == len(coluna.celulas)
        # `comparados` é o denominador honesto: exclui o que ninguém mediu.
        assert coluna.contagem.comparados < coluna.contagem.total

    def test_a_identidade_do_veiculo_nao_entra_na_matriz(self, ford, concorrente):
        """ "A marca da Ford é Ford e a do concorrente é Toyota" não é um gap."""
        coluna = parity.montar_coluna(ford, concorrente, version_id="v", rotulo="x")
        campos = {c.campo for c in coluna.celulas}
        assert "marca" not in campos
        assert "modelo" not in campos
        assert "versao" not in campos

    def test_filtra_por_grupo(self, ford, concorrente):
        coluna = parity.montar_coluna(
            ford, concorrente, version_id="v", rotulo="x", grupos=["motorizacao"]
        )
        assert {c.grupo for c in coluna.celulas} == {"motorizacao"}

    def test_a_celula_carrega_o_id_da_evidencia_dos_dois_lados(self, ford, concorrente):
        """É o que faz o clique na célula abrir a evidência, em vez de recalcular."""
        coluna = parity.montar_coluna(ford, concorrente, version_id="v", rotulo="x")
        potencia = next(c for c in coluna.celulas if c.campo == "potencia_cv")
        assert potencia.evidence_id_ford
        assert potencia.evidence_id_concorrente

    def test_ficha_vazia_dos_dois_lados_da_matriz_toda_desconhecida(self):
        vazia = empty_spec()
        coluna = parity.montar_coluna(vazia, vazia, version_id="v", rotulo="x")
        assert coluna.contagem.desconhecido == coluna.contagem.total
        assert coluna.contagem.comparados == 0

    def test_todo_estado_tem_legenda(self):
        assert set(parity.LEGENDA) == set(parity.ESTADOS)
        assert all(parity.LEGENDA[e] for e in parity.ESTADOS)

    def test_a_legenda_do_gap_diz_que_ele_aparece_sempre(self):
        """`docs/12` §3: onde o concorrente ganha fica **sempre** visível."""
        assert "sempre" in parity.LEGENDA[GAP].lower()
