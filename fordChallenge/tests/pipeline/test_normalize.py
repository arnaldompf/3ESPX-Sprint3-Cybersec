"""WP-11 — normalização: valor bruto da fonte → valor canônico da ficha.

Duas garantias travadas aqui: a unidade canônica sempre, e o `raw_value` **nunca** se
perde. Sem a segunda, "583 Nm" na tela seria indistinguível de um número digitado por
alguém — e é justamente essa distinção que o produto promete.
"""

from __future__ import annotations

import pytest

from pipeline.normalize import (
    MARCAS_DE_AUSENCIA,
    NaoNormalizavel,
    normalizar_campo,
    parece_ausencia,
    resolver_atributo,
    resolver_atributos,
)


# --------------------------------------------------------------------- unidades
def test_torque_em_kgfm_vira_nm_com_a_conversao_registrada():
    n = normalizar_campo("torque_nm", "50,9", unidade="kgfm")
    assert n.valor == 499
    assert n.unidade == "Nm"
    assert n.raw_value == "50,9"
    assert "kgfm→Nm" in n.conversao


def test_torque_ja_em_nm_nao_registra_conversao():
    n = normalizar_campo("torque_nm", "583", unidade="Nm")
    assert (n.valor, n.conversao) == (583, "")


def test_potencia_em_hp_e_kw():
    assert normalizar_campo("potencia_cv", 258, unidade="hp").valor == pytest.approx(262, abs=1)
    assert normalizar_campo("potencia_cv", 190, unidade="kW").valor == pytest.approx(258, abs=1)
    assert normalizar_campo("potencia_cv", 397, unidade="cv").conversao == ""


def test_cilindrada_em_cm3_vira_litros():
    n = normalizar_campo("deslocamento_l", "2755", unidade="cm3")
    assert n.valor == 2.76 or n.valor == pytest.approx(2.755, abs=0.01)
    assert n.conversao == "cm³→l"


def test_comprimento_em_metros_vira_mm():
    n = normalizar_campo("comprimento_mm", "5,325", unidade="m")
    assert n.valor == 5325
    assert n.conversao == "m→mm"


def test_preco_ptbr_vira_inteiro():
    assert normalizar_campo("preco_sugerido_brl", "R$ 499.000").valor == 499000
    assert normalizar_campo("preco_fipe_brl", "452.540").valor == 452540


def test_rpm_com_separador_de_milhar():
    assert normalizar_campo("potencia_rpm", "3.400 rpm").valor == 3400


def test_medida_de_pneu_fica_canonica():
    assert normalizar_campo("pneus_medida", "285/70R17").valor == "285/70 R17"


def test_raw_value_e_sempre_preservado():
    for campo, bruto in (
        ("torque_nm", "50,9 kgf.m"),
        ("potencia_cv", "397cv"),
        ("preco_sugerido_brl", "R$ 499.000"),
        ("modos_conducao", "Normal, Esportivo"),
        ("farois_tipo", "Matrix LED"),
    ):
        n = normalizar_campo(campo, bruto)
        assert n.raw_value == bruto, campo


# ----------------------------------------------------------------------- listas
def test_lista_de_modos_passa_pela_ontologia():
    n = normalizar_campo("modos_conducao", "Normal, Esportivo, Lama/Terra, Areia")
    assert n.valor == ["normal", "sport", "lama", "areia"]
    assert "sinônimos" in n.conversao


def test_lista_ja_em_lista_tambem_funciona():
    assert normalizar_campo("modos_direcao", ["Normal", "Comfort"]).valor == [
        "normal",
        "conforto",
    ]


def test_lista_sem_nada_reconhecivel_levanta():
    with pytest.raises(NaoNormalizavel, match="nenhuma opção"):
        normalizar_campo("modos_conducao", "x")


# -------------------------------------------------------------------- booleanos
@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [("•", True), ("Sim", True), ("de série", True), ("Paddle Shifters", True), ("Não", False)],
)
def test_booleano_de_ficha_de_equipamento(bruto, esperado):
    assert normalizar_campo("paddle_shifters", bruto).valor is esperado


# ---------------------------------------------------------------------- datas
def test_data_em_varios_formatos():
    assert normalizar_campo("preco_data", "2026-09-01").valor == "2026-09-01"
    assert normalizar_campo("preco_data", "01/09/2026").valor == "2026-09-01"
    assert normalizar_campo("fipe_referencia", "2026-09").valor == "2026-09"
    assert normalizar_campo("fipe_referencia", "9/2026").valor == "2026-09"


def test_data_irreconhecivel_levanta():
    with pytest.raises(NaoNormalizavel, match="data"):
        normalizar_campo("preco_data", "setembro de dois mil e vinte e seis")


# ------------------------------------------------------- ausência declarada
@pytest.mark.parametrize("marca", sorted(MARCAS_DE_AUSENCIA))
def test_marcas_de_ausencia_sao_reconhecidas(marca):
    assert parece_ausencia(marca)


def test_ausencia_declarada_nao_vira_valor():
    """Critério de aceite: "—" na coluna da versão é `nao_disponivel`, não um valor."""
    n = normalizar_campo("camera_360", "—")
    assert n.ausencia_declarada
    assert n.valor is None


def test_vazio_nao_e_ausencia_declarada():
    """String vazia é "não sei", não "a fonte disse que não tem"."""
    assert not parece_ausencia("")
    assert not parece_ausencia(None)
    with pytest.raises(NaoNormalizavel, match="vazio"):
        normalizar_campo("camera_360", "   ")


# ------------------------------------------------------------- atributo livre
def test_atributo_que_casa_vai_para_campo_canonico():
    r = resolver_atributo("modos de volante")
    assert r.campo == "modos_direcao"
    assert r.caminho == "modos.modos_direcao"
    assert not r.e_extra


def test_atributo_que_nao_casa_vai_para_extras():
    r = resolver_atributo("ganchos de reboque")
    assert r.campo is None
    assert r.caminho == "extras.ganchos_de_reboque"
    assert r.e_extra
    assert r.chave == "ganchos_de_reboque"


def test_atributo_livre_nunca_e_descartado():
    """Atributo que o usuário pediu e o sistema ignorou em silêncio é pior que um
    `nao_encontrado`: ele desaparece da ficha sem explicação."""
    pedidos = ["potência", "modos de volante", "cor do porta-luvas", "capacidade de carga"]
    resolvidos = resolver_atributos(pedidos)
    assert len(resolvidos) == len(pedidos)
    assert all(r.caminho for r in resolvidos)
    assert {r.pedido for r in resolvidos} == set(pedidos)


def test_extras_recebe_slug_estavel():
    assert resolver_atributo("Cor do Porta-Luvas!").caminho == "extras.cor_do_porta_luvas"


class TestSoUmTipoAtravessaAFronteira:
    """Achado ao vivo em 13/09/2026, na pesquisa da Nissan Frontier PRO-4X.

    Uma fonte escreveu *"seis"* airbags por extenso. `parse_number_ptbr` levantou um
    `ValueError` simples — que não é `NaoNormalizavel` nem `UnidadeDesconhecida` — e
    **a pesquisa inteira morreu** depois de 10 páginas e 4 chamadas de modelo pagas. É o
    mesmo defeito da unidade em `"metros"` (D-267), uma exceção adiante: listar tipos
    irmãos é uma lista que envelhece.
    """

    @pytest.mark.parametrize(
        ("campo", "bruto", "unidade"),
        [
            ("airbags_qtd", "seis", None),
            ("potencia_cv", "duzentos e cinco", "cv"),
            ("comprimento_mm", "cinco metros", "metros"),
            ("pneus_medida", "aro grande", None),
            ("tanque_l", "cheio", "l"),
        ],
    )
    def test_valor_ilegivel_vira_NaoNormalizavel_com_o_campo_no_motivo(
        self, campo: str, bruto: str, unidade: str | None
    ):
        with pytest.raises(NaoNormalizavel) as erro:
            normalizar_campo(campo, bruto, unidade=unidade)
        assert campo in str(erro.value)

    def test_o_motivo_original_nao_se_perde(self):
        with pytest.raises(NaoNormalizavel) as erro:
            normalizar_campo("airbags_qtd", "seis")
        assert "seis" in str(erro.value)
        assert isinstance(erro.value.__cause__, ValueError)

    def test_o_que_normaliza_continua_normalizando(self):
        assert normalizar_campo("airbags_qtd", "7").valor == 7
        assert normalizar_campo("comprimento_mm", "5,285", unidade="metros").valor == 5285


class TestCilindradaImplausivel:
    """Cilindrada abaixo de meio litro não é motor de picape — é separador de milhar perdido.

    Medido na pesquisa ao vivo da S10 em 14/09/2026. A página dizia `Cilindrada: 2.776 cm³`;
    o modelo devolveu o número **já como float** `2.776` (ponto lido à inglesa) com a
    unidade `cm³`. A conversão fez `2,776 / 1000 = 0,003`, que arredondou para **0** — e a
    ficha ganhou um motor de zero litro com `status=verificado` e citação verdadeira ao lado.

    Zero é pior que lacuna: a lacuna se vê, o zero passa. Recusar devolve o campo para
    `nao_verificado`, que é o estado honesto de "li, não entendi".
    """

    def test_cilindrada_que_daria_zero_e_recusada(self):
        with pytest.raises(NaoNormalizavel) as erro:
            normalizar_campo("deslocamento_l", 2.776, unidade="cm³")
        assert "deslocamento_l" in str(erro.value)

    def test_cilindrada_absurda_para_cima_tambem(self):
        with pytest.raises(NaoNormalizavel):
            normalizar_campo("deslocamento_l", 2776, unidade="l")

    def test_a_cilindrada_de_verdade_continua_passando(self):
        assert normalizar_campo("deslocamento_l", "2.776 cm³", unidade="cm³").valor == 2.78
        assert normalizar_campo("deslocamento_l", 2776, unidade="cm3").valor == 2.78
        assert normalizar_campo("deslocamento_l", "2,8", unidade="l").valor == 2.8
        assert normalizar_campo("deslocamento_l", 999, unidade="cm3").valor == 1.0
