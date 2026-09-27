"""WP-11 — grounding: o gate que impede valor sem evidência.

Este é o teste mais importante do projeto. Se o grounding aceitar um trecho que não está
na fonte, tudo o que vem depois — status, confiança, comparação, argumentário — passa a
falar de um valor que ninguém pode conferir.
"""

from __future__ import annotations

import pytest

from pipeline.ground import (
    JANELA_DIFUSA,
    LIMIAR_DIFUSO,
    MODO_DIFUSO,
    MODO_EXATO,
    MODO_FALHOU,
    MODO_SEM_ACENTO,
    MODO_SEM_QUOTE,
    MODO_SEM_TEXTO,
    falhas_por_campo,
    grounding_fail_total,
    grounding_ok,
    localizar_em_varios,
    locate,
    normalize_texto,
    registrar_falha,
    sem_acento,
    zerar_falhas,
)


# ---------------------------------------------------------------- normalizações
def test_normalize_texto_segue_docs05_e_mantem_acento():
    assert normalize_texto("  Potência   “máxima”  ") == 'potência "máxima"'
    assert normalize_texto("2.5–3.0") == "2.5-3.0"
    assert normalize_texto("Linha 1\nLinha 2") == "linha 1 linha 2"


def test_sem_acento_dobra_acento_alem_do_resto():
    assert sem_acento("Potência máxima") == "potencia maxima"
    assert sem_acento("Faróis") == "farois"


# ------------------------------------------------------------- os três caminhos
def test_caminho_exato():
    r = locate("397cv", "Motor 3.0 V6. Potencia 397cv de forca.")
    assert r.ok
    assert r.modo == MODO_EXATO
    assert r.offset >= 0
    assert r.score == 100.0


def test_caminho_exato_ignora_caixa_espaco_e_aspas():
    r = locate('amortecedores fox 2.5" racing', "Amortecedores   FOX 2.5”  Racing com")
    assert r.ok
    assert r.modo == MODO_EXATO


def test_caminho_sem_acento_e_deterministico_nao_um_limiar():
    """Critério de aceite da spec: quote "Potencia 397cv" × texto "Potência 397cv".

    Este caso caía no difuso e pontuava 92,9 — à beira do limiar de 92. Um trecho mais
    longo com um acento a menos escorregaria abaixo e um valor **correto** seria
    descartado. O caminho `sem_acento` aceita outra grafia do mesmo texto, nunca outro
    valor.
    """
    r = locate("Potencia 397cv", "Ficha: Potência 397cv de potência máxima")
    assert r.ok
    assert r.modo == MODO_SEM_ACENTO
    assert r.score == 100.0
    assert "acentuação diferente" in r.detalhe


def test_caminho_difuso_para_ruido_de_conversao():
    r = locate("Amortecedores FOX 2.5 Racng", "Amortecedores FOX 2.5 Racing com Live Valve")
    assert r.ok
    assert r.modo == MODO_DIFUSO
    assert r.score >= LIMIAR_DIFUSO


def test_difuso_usa_janela_e_nao_o_texto_inteiro():
    """`docs/05` pede janela. Num documento enorme, o `partial_ratio` global acha
    semelhança em qualquer lugar, e o caminho difuso viraria um "sim" quase garantido."""
    ruido = "texto irrelevante sobre outra coisa. " * 400
    assert len(ruido) > JANELA_DIFUSA * 5
    r = locate("capacidade de reboque de 3.500 kg", ruido)
    assert not r.ok
    assert r.modo == MODO_FALHOU


# --------------------------------------------------------------------- rejeições
def test_quote_inventado_e_rejeitado():
    """Critério de aceite: quote inventado → falha (e o valor será descartado)."""
    r = locate("Potencia 500cv", "Potencia 397cv")
    assert not r.ok
    assert r.modo == MODO_FALHOU
    assert r.offset == -1
    assert "abaixo de 92" in r.detalhe


def test_numero_diferente_no_meio_de_frase_igual_e_rejeitado():
    """O defeito mais perigoso possível, encontrado por este teste.

    `"Torque máximo de 900 Nm a 2.750 rpm no eixo traseiro"` contra um texto que diz
    **583 Nm**: 51 caracteres, um token de 3 dígitos diferente, `partial_ratio` ≈ 94 —
    **acima** do limiar de 92. O caminho difuso aceitava, e um valor errado entrava na
    ficha com evidência aparentemente válida.

    A guarda: o difuso existe para ruído de conversão em **letras**; número do trecho que
    não está na fonte reprova. Número é exatamente o que os valores são.
    """
    texto = "Torque máximo de 583 Nm a 2.750 rpm no eixo traseiro"
    r = locate("Torque máximo de 900 Nm a 2.750 rpm no eixo traseiro", texto)
    assert not r.ok
    assert r.score >= LIMIAR_DIFUSO, "a similaridade passaria; foi a guarda que reprovou"
    assert "não estão na fonte" in r.detalhe
    assert "900" in r.detalhe


def test_guarda_numerica_nao_atrapalha_ruido_em_letras():
    """Com os números iguais, o difuso continua aceitando ruído nas letras."""
    texto = "Amortecedores FOX 2.5 Racing com tecnologia Live Valve"
    r = locate("Amortecedores FOX 2.5 Racng com tecnologa Live Valve", texto)
    assert r.ok
    assert r.modo == MODO_DIFUSO


def test_guarda_numerica_aceita_separador_ptbr():
    texto = "Torque (kgf.m/rpm) 50,9 / 2.800 no eixo"
    assert grounding_ok("Torque (kgf.m/rpm) 50,9 / 2.800 no eixo", texto)
    assert not grounding_ok("Torque (kgf.m/rpm) 50,9 / 3.800 no eixo", texto)


def test_quote_ou_texto_vazio_falha_com_motivo_proprio():
    assert locate(None, "qualquer coisa").modo == MODO_SEM_QUOTE
    assert locate("   ", "qualquer coisa").modo == MODO_SEM_QUOTE
    assert locate("algo", "").modo == MODO_SEM_TEXTO
    assert locate("algo", None).modo == MODO_SEM_TEXTO


# ------------------------------------------------------------------ várias fontes
def test_localizar_em_varios_prefere_o_caminho_mais_literal():
    """Evidência mais literal é evidência mais forte."""
    textos = {
        "difuso": "Potencia 397 cv aproximadamente",
        "exato": "Ficha oficial: Potencia 397cv",
    }
    source_id, achado = localizar_em_varios("Potencia 397cv", textos)
    assert source_id == "exato"
    assert achado.modo == MODO_EXATO


def test_localizar_em_varios_sem_nenhuma_fonte_confirmando():
    source_id, achado = localizar_em_varios("Potencia 900cv", {"a": "Potencia 397cv"})
    assert not achado.ok
    assert source_id == "a"


def test_localizar_em_varios_com_dicionario_vazio():
    _, achado = localizar_em_varios("x", {})
    assert not achado.ok


# --------------------------------------------------------------------- contador
def test_contador_de_falhas_de_grounding():
    """`grounding_fail_total` é a métrica que a spec pede."""
    zerar_falhas()
    assert grounding_fail_total() == 0
    registrar_falha("potencia_cv")
    registrar_falha("potencia_cv")
    registrar_falha("torque_nm")
    assert grounding_fail_total() == 3
    assert falhas_por_campo() == {"potencia_cv": 2, "torque_nm": 1}
    zerar_falhas()
    assert grounding_fail_total() == 0


# -------------------------------------------------- o eval usa a MESMA função
def test_o_eval_reexporta_o_grounding_do_pipeline():
    """Se o eval medisse outro grounding, `grounding_rate` não mediria o produto."""
    from pipeline.eval import compare

    assert compare.LIMIAR_GROUNDING == LIMIAR_DIFUSO
    assert compare.normalize_grounding("Potência") == normalize_texto("Potência")
    for quote, texto in (
        ("397cv", "Potencia 397cv"),
        ("Potencia 397cv", "Potência 397cv"),
        ("Potencia 900cv", "Potencia 397cv"),
    ):
        assert compare.grounding(quote, texto).ok == locate(quote, texto).ok
        assert compare.grounding(quote, texto).modo == locate(quote, texto).modo


@pytest.mark.parametrize(
    ("quote", "texto", "esperado"),
    [
        ("583Nm", "Torque 583Nm", True),
        ("583 Nm", "Torque 583Nm", False),  # espaço a mais não existe no texto
        ("Torque 583Nm", "torque   583nm", True),  # espaço a menos no texto, sim
        ("50,9 / 2.800", "Torque (kgf.m/rpm) 42,8 / 3.400   50,9 / 2.800", True),
        ("42,8 / 2.800", "Torque (kgf.m/rpm) 42,8 / 3.400   50,9 / 2.800", False),
    ],
)
def test_matriz_de_grounding(quote, texto, esperado):
    assert grounding_ok(quote, texto) is esperado
