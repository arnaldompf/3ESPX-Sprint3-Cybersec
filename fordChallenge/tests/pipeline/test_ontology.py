"""WP-01 — ontologia: sinônimo não pode virar `nao_encontrado`.

O caso-âncora é real (`gabarito/README.md`): o slide interno da Ford diz "modos de
**volante**", a ficha pública diz "modos de **direção**", e um agente genérico marcou
`nao_encontrado` por procurar a palavra errada.
"""

from __future__ import annotations

import pytest

from pipeline.ontology import (
    canonicalizar_lista,
    normalize,
    resolve_attribute,
    resolve_attribute_path,
    resolve_unit,
    resolve_value,
    slugify,
    total_sinonimos,
)
from pipeline.schema import grupo_de


# ---------------------------------------------------------------------- normalização
def test_normalize_remove_acento_aspas_e_colapsa_espaco():
    assert normalize("  Modos   de  Direção ") == "modos de direcao"
    assert normalize("“Potência”") == "potencia"
    assert normalize("lama/terra") == "lama terra"


def test_slugify_gera_chave_de_extras():
    assert slugify("Ganchos de Reboque") == "ganchos_de_reboque"
    assert slugify("!!!") == "atributo"


# ---------------------------------------------------------- resolução de campo (aceite)
def test_modos_de_volante_resolve_para_modos_direcao():
    campo, score = resolve_attribute("modos de volante")
    assert campo == "modos_direcao"
    assert score >= 85


def test_aletas_no_volante_resolve_para_paddle_shifters():
    campo, score = resolve_attribute("aletas no volante")
    assert campo == "paddle_shifters"
    assert score >= 85
    caminho, _ = resolve_attribute_path("aletas no volante")
    assert caminho == "transmissao.paddle_shifters"


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("modos de direção", "modos_direcao"),
        ("steering modes", "modos_direcao"),
        ("borboletas", "paddle_shifters"),
        ("paddle shift", "paddle_shifters"),
        ("potência", "potencia_cv"),
        ("torque máximo", "torque_nm"),
        ("cilindrada", "deslocamento_l"),
        ("tração", "tipo_tracao"),
        ("4Motion", "tipo_tracao"),
        ("caixa de redução", "reduzida"),
        ("câmbio", "tipo"),
        ("10 velocidades", "numero_marchas"),
        ("Toyota Safety Sense", "adas_nome_comercial"),
        ("Co-Pilot360", "adas_nome_comercial"),
        ("IQ.Drive", "adas_nome_comercial"),
        ("câmera 360", "camera_360"),
        ("carga útil", "capacidade_carga_kg"),
        ("distância entre eixos", "entre_eixos_mm"),
        ("0 a 100", "aceleracao_0_100_s"),
        ("amortecedores", "amortecedores"),
        ("tabela fipe", "preco_fipe_brl"),
        ("a partir de", "preco_sugerido_brl"),
        ("modos de amortecedor", "modos_amortecedor"),
        ("modos de escapamento", "modos_escapamento"),
        ("modos de condução", "modos_conducao"),
    ],
)
def test_termos_reais_resolvem_para_o_campo_certo(texto, esperado):
    campo, score = resolve_attribute(texto)
    assert campo == esperado, f"{texto!r} -> {campo!r} (score {score:.0f})"
    assert score >= 85


def test_termo_desconhecido_devolve_none_em_vez_de_inventar_campo():
    campo, _ = resolve_attribute("cor do porta-luvas de um jato")
    assert campo is None


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        # erro de digitação: precisa passar pelo caminho difuso, não pelo índice exato
        ("modos de volnte", "modos_direcao"),
        ("potencia maxma", "potencia_cv"),
        # pergunta em linguagem natural: as palavras vazias não podem decidir o campo
        ("quantos modos de direcao tem", "modos_direcao"),
        ("potencia maxima do motor", "potencia_cv"),
        ("tipo de pneu AT", "pneus_tipo"),
        ("qual a capacidade de carga da cacamba", "capacidade_carga_kg"),
        ("tem paddle shifters?", "paddle_shifters"),
        ("quantos modos de amortecedor", "modos_amortecedor"),
        ("preco fipe do carro", "preco_fipe_brl"),
    ],
)
def test_caminho_difuso_resolve_typo_e_pergunta(texto, esperado):
    """Regressão: `token_set_ratio` puro devolve 100 para subconjunto de tokens, e por
    isso "quantos modos de direção tem" casava com `direcao` (chassi) e "potência máxima
    do motor" casava com `motor`. O ranqueamento por cobertura da consulta corrigiu."""
    campo, score = resolve_attribute(texto)
    assert campo == esperado, f"{texto!r} -> {campo!r} (score {score:.0f})"
    assert score >= 85


def test_limiar_e_realmente_aplicado():
    """Com limiar alto, o caminho difuso rejeita; o índice exato continua respondendo."""
    assert resolve_attribute("modos de volnte", limiar=99.0)[0] is None
    assert resolve_attribute("modos de volante", limiar=99.0)[0] == "modos_direcao"


def test_todo_campo_da_semente_e_canonico():
    """A semente não pode citar um campo que o schema não tem."""
    from pipeline.ontology import carregar

    for entrada in carregar().campos:
        assert grupo_de(entrada.campo_canonico) is not None, entrada.campo_canonico
        assert entrada.grupo == grupo_de(entrada.campo_canonico)


def test_semente_tem_sinonimos_suficientes_para_o_seed_do_wp03():
    assert total_sinonimos() > 20


# ------------------------------------------------------------- resolução de valor
@pytest.mark.parametrize(
    ("campo", "bruto", "esperado"),
    [
        ("modos_conducao", "Esportivo", "sport"),
        ("modos_conducao", "lama/terra", "lama"),
        ("modos_conducao", "Rock Crawl", "rock_crawl"),
        ("modos_direcao", "Comfort", "conforto"),
        ("modos_amortecedor", "Off-Road", "off_road"),
        ("modos_escapamento", "Silencioso", "silencioso"),
        ("tipo", "AT", "automatica"),
        ("tipo_tracao", "4WD", "4x4"),
        ("tipo_tracao", "4Motion", "4x4 permanente"),
        ("farois_tipo", "matrix led", "Matrix LED"),
        ("pneus_tipo", "All-Terrain", "AT"),
        ("adas_nome_comercial", "TSS", "Toyota Safety Sense"),
        ("aspiracao", "Bi-Turbo", "biturbo"),
    ],
)
def test_resolve_value(campo, bruto, esperado):
    assert resolve_value(campo, bruto) == esperado


def test_resolve_value_desconhecido_preserva_o_token():
    """Não descartamos informação: token sem mapa vira token normalizado."""
    assert resolve_value("modos_conducao", "Modo Fazenda") == "modo_fazenda"
    assert resolve_value("campo_sem_mapa", "Qualquer Coisa") == "qualquer_coisa"
    assert resolve_value("modos_conducao", "   ") is None


def test_canonicalizar_lista_compara_como_conjunto_apos_sinonimos():
    """O caso do gabarito: slide e ficha usam palavras diferentes para o mesmo conjunto."""
    ficha = canonicalizar_lista(
        "modos_conducao", ["Normal", "Esportivo", "Escorregadio", "Lama/Terra", "Areia", "Baja"]
    )
    slide = canonicalizar_lista(
        "modos_conducao", ["normal", "sport", "escorregadio", "lama", "areia", "baja"]
    )
    assert set(ficha) == set(slide)


def test_canonicalizar_lista_remove_duplicata_e_preserva_ordem():
    assert canonicalizar_lista("modos_direcao", ["Normal", "normal", "Comfort", "conforto"]) == [
        "normal",
        "conforto",
    ]


# --------------------------------------------------------------------------- unidades
def test_resolve_unit():
    assert resolve_unit("potencia", "hp") == "cv"
    assert resolve_unit("potencia", "kW") == "cv"
    assert resolve_unit("torque", "kgf.m") == "Nm"
    assert resolve_unit("torque", "mkgf") == "Nm"
    assert resolve_unit("torque", "furlongs") is None
