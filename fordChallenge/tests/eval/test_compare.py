"""WP-02 — o comparador e o grounding.

O eval é o oráculo de todo o projeto: qualquer mudança aqui exige teste (`specs/WP-02.md`).
"""

from __future__ import annotations

import pytest

from pipeline.eval.compare import (
    LIMIAR_GROUNDING,
    comparar_lista,
    comparar_qualquer,
    comparar_texto,
    comparar_valor,
    grounding,
    grounding_ok,
    normalize_grounding,
    tolerancia_de,
)


# ---------------------------------------------------------------------------- listas
def test_lista_compara_como_conjunto_apos_sinonimos_criterio_de_aceite():
    """Critério da spec: `["normal","esportivo","lama/terra"]` == `["normal","sport","lama"]`."""
    r = comparar_lista(
        "modos_conducao", ["normal", "esportivo", "lama/terra"], ["normal", "sport", "lama"]
    )
    assert r.igual
    assert r.modo == "conjunto"


def test_lista_ignora_ordem():
    assert comparar_lista("modos_direcao", ["normal", "sport"], ["sport", "normal"]).igual


def test_lista_diferente_mostra_o_que_falta_e_o_que_sobra():
    r = comparar_lista("modos_conducao", ["normal", "sport", "baja"], ["normal", "sport"])
    assert not r.igual
    assert "baja" in r.detalhe
    assert "faltando" in r.detalhe


def test_lista_com_modo_a_mais_no_pipeline_e_diferente():
    """Modo inventado é erro, não bônus."""
    r = comparar_lista("modos_direcao", ["normal"], ["normal", "hiperdrive"])
    assert not r.igual
    assert "sobrando" in r.detalhe


# --------------------------------------------------------------------------- números
@pytest.mark.parametrize(
    ("campo", "esperado", "obtido", "igual"),
    [
        ("potencia_cv", 397, 397, True),
        ("potencia_cv", 397, 398, True),  # ±1
        ("potencia_cv", 397, 399, False),
        ("torque_nm", 583, 582, True),
        ("torque_nm", 583, 585, False),
        ("potencia_rpm", 5650, 5690, True),  # ±50
        ("potencia_rpm", 5650, 5750, False),
        ("aceleracao_0_100_s", 5.8, 5.85, True),  # ±0,1
        ("aceleracao_0_100_s", 5.8, 6.5, False),
        ("preco_sugerido_brl", 499000, 500000, True),  # ±0,5%
        ("preco_sugerido_brl", 499000, 520000, False),
        ("deslocamento_l", 3.0, 2.98, True),
        ("numero_marchas", 10, 10, True),
        ("numero_marchas", 10, 9, False),  # sem tolerância: contagem é exata
    ],
)
def test_tolerancias_de_docs09(campo, esperado, obtido, igual):
    assert comparar_valor(campo, esperado, obtido).igual is igual


def test_tolerancia_de_campo_desconhecido_e_exata():
    assert tolerancia_de("campo_inventado").descricao() == "±0"


def test_numero_como_texto_e_aceito():
    """O pipeline pode trazer `"397 cv"`; o valor canônico é 397."""
    assert comparar_valor("potencia_cv", 397, "397 cv").igual
    assert comparar_valor("preco_sugerido_brl", 499000, "R$ 499.000").igual


def test_texto_nao_numerico_em_campo_numerico_e_diferente():
    r = comparar_valor("potencia_cv", 397, "muito forte")
    assert not r.igual
    assert "não numérico" in r.detalhe


# -------------------------------------------------------------------------- booleanos
def test_booleano_e_exato():
    assert comparar_valor("paddle_shifters", True, True).igual
    assert not comparar_valor("paddle_shifters", True, False).igual


# ----------------------------------------------------------------------------- textos
def test_texto_igual_apos_sinonimo():
    assert comparar_texto("tipo", "automatica", "AT").igual
    assert comparar_texto("farois_tipo", "Matrix LED", "matrix led").igual


def test_obtido_mais_especifico_que_o_gabarito_e_compativel():
    """O gabarito diz `4x4`; a ficha da Raptor detalha `4x4 sob demanda`."""
    r = comparar_texto("tipo_tracao", "4x4", "4x4 sob demanda")
    assert r.igual
    assert r.modo == "contido", "compatível não é idêntico; o modo tem de ficar registrado"


def test_gabarito_mais_especifico_que_o_obtido_nao_e_compativel():
    """O contrário não vale: perder informação é erro."""
    assert not comparar_texto("tipo_tracao", "4x4 sob demanda", "4x4").igual


def test_texto_diferente_mostra_os_dois_valores():
    r = comparar_texto("rodas_material", "liga leve", "aço estampado")
    assert not r.igual
    assert "liga leve" in r.detalhe and "aço estampado" in r.detalhe


# ------------------------------------------------------------------------ sem valor
def test_pipeline_sem_valor_nunca_conta_como_acerto():
    r = comparar_valor("potencia_cv", 397, None)
    assert not r.igual
    assert r.modo == "sem_obtido"


def test_comparar_qualquer_aceita_qualquer_valor_registrado():
    """Campo com divergência registrada: acertar um dos valores é acertar."""
    assert comparar_qualquer("aceleracao_0_100_s", (5.8, 6.5), 6.5).igual
    assert comparar_qualquer("aceleracao_0_100_s", (5.8, 6.5), 5.8).igual
    assert not comparar_qualquer("aceleracao_0_100_s", (5.8, 6.5), 7.9).igual


# -------------------------------------------------------------------------- grounding
def test_quote_inventado_e_rejeitado_criterio_de_aceite():
    texto = "Motor 3.0L V6 Bi-turbo de 397cv com 583Nm de torque."
    assert grounding_ok("Potencia 397cv", texto) is False
    assert grounding_ok("397cv", texto) is True
    assert grounding_ok("motor de 500cv", texto) is False


def test_grounding_exato_ignora_caixa_e_espaco():
    texto = "Amortecedores   FOX 2.5”  Racing  com tecnologia Live Valve"
    r = grounding('amortecedores fox 2.5" racing com tecnologia live valve', texto)
    assert r.ok
    assert r.modo == "exato"


def test_diferenca_de_acento_e_resolvida_sem_limiar():
    """Acento é diferença de **grafia**, e é tratado por normalização, não por limiar.

    Antes este caso caía no caminho difuso e pontuava 92,9 — à beira do limiar de 92.
    Um trecho mais longo com um acento a menos escorregaria para baixo e um valor
    correto seria descartado. O caminho `sem_acento` é determinístico: aceita outra
    grafia do mesmo texto, nunca outro valor.
    """
    texto = "Potência máxima de 397 cv e torque de 583 N.m"
    r = grounding("Potencia maxima de 397 cv", texto)
    assert r.ok
    assert r.modo == "sem_acento"
    assert r.score == 100.0


def test_grounding_difuso_tolera_ruido_de_conversao():
    """O caminho difuso existe para ruído de conversão, não para acento."""
    texto = "Amortecedores FOX 2.5  Racing com tecnologia Live Valve"
    r = grounding("Amortecedores FOX 2.5 Racng com tecnologia Live Valve", texto)
    assert r.ok
    assert r.modo == "difuso"
    assert r.score >= LIMIAR_GROUNDING


def test_grounding_falha_quando_o_texto_nao_sustenta():
    r = grounding("capacidade de reboque de 3.500 kg", "Motor 3.0 V6 de 397 cv")
    assert not r.ok
    assert r.modo == "falhou"


def test_grounding_sem_quote_ou_sem_texto_e_falha_explicita():
    assert grounding(None, "qualquer coisa").modo == "sem_quote"
    assert grounding("   ", "qualquer coisa").modo == "sem_quote"
    assert grounding("algo", "").modo == "sem_texto"
    assert grounding("algo", None).modo == "sem_texto"


def test_normalize_grounding_unifica_aspas_e_hifens_mas_mantem_acento():
    assert normalize_grounding("  Potência   “máxima”  ") == 'potência "máxima"'
    assert normalize_grounding("2.5–3.0") == "2.5-3.0"
