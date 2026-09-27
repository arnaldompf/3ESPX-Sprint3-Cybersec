"""WP-09 — recorte da versão alvo numa tabela multi-versão.

O critério de aceite da spec é o caso mais difícil do gabarito: seis versões da Hilux em
colunas, células mescladas, e a pergunta "qual pneu é da SRX Plus AT?". Errar aqui é
atribuir a especificação de outra versão — a inferência que o projeto proíbe.

Os valores esperados vêm do **gabarito**, não de números repetidos aqui.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pipeline.eval.gabarito import carregar_gabarito
from pipeline.parse.pdf import DocumentoPdf, Tabela
from pipeline.parse.version_slicer import (
    celulas_da_linha,
    coluna_da_versao,
    recortar,
    recortar_tabela,
    versoes_do_documento,
)

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_PDF = ROOT / "tests" / "fixtures" / "pdf" / "toyota_hilux_my26"

VERSOES_HILUX = [
    "STD Power Pack MT",
    "STD Power Pack AT",
    "SR AT",
    "SRV AT",
    "SRX AT",
    "SRX Plus AT",
]


@pytest.fixture(scope="module")
def doc() -> DocumentoPdf:
    dados = json.loads((FIXTURES_PDF / "tables.json").read_text(encoding="utf-8"))
    markdown = (FIXTURES_PDF / "doc.md").read_text(encoding="utf-8")
    return DocumentoPdf(
        markdown=markdown,
        paginas=markdown.split("\n\n"),
        tabelas=[Tabela.from_dict(t) for t in dados["tabelas"]],
        motor=dados["motor"],
    )


@pytest.fixture(scope="module")
def recorte(doc):
    return recortar(doc, "SRX Plus AT")


@pytest.fixture(scope="module")
def hilux_do_gabarito():
    return carregar_gabarito().por_id("toyota_hilux_srx_plus_at_2026")


# --------------------------------------------------------- alcance de célula mesclada
def test_valor_abre_alcance_que_segue_pelas_colunas_vazias():
    """A regra única do módulo, isolada."""
    linha = ["Pneus", "265/65 R17", "", "", "265/60 R18", "", ""]
    celulas = celulas_da_linha(
        linha, VERSOES_HILUX, rotulo="Pneus", pagina=7, indice=22, spans={"22:1": 3, "22:4": 3}
    )
    assert len(celulas) == 2
    primeira, segunda = celulas
    assert primeira.valor == "265/65 R17"
    assert primeira.versoes_cobertas == ("STD Power Pack MT", "STD Power Pack AT", "SR AT")
    assert segunda.valor == "265/60 R18"
    assert segunda.versoes_cobertas == ("SRV AT", "SRX AT", "SRX Plus AT")
    assert primeira.compartilhado and segunda.compartilhado


def test_valor_em_coluna_unica_nao_e_compartilhado():
    linha = ["Item", "", "", "", "", "", "só na última"]
    celulas = celulas_da_linha(linha, VERSOES_HILUX, rotulo="Item", pagina=1, indice=1)
    assert len(celulas) == 1
    assert celulas[0].versoes_cobertas == ("SRX Plus AT",)
    assert not celulas[0].compartilhado


def test_valor_unico_na_primeira_coluna_cobre_todas():
    linha = ["Cilindrada (cm3)", "2755", "", "", "", "", ""]
    celulas = celulas_da_linha(
        linha, VERSOES_HILUX, rotulo="Cilindrada", pagina=7, indice=8, spans={"8:1": 6}
    )
    assert celulas[0].versoes_cobertas == tuple(VERSOES_HILUX)


def test_linha_mais_curta_que_o_cabecalho_nao_estoura():
    celulas = celulas_da_linha(["Rótulo", "x"], VERSOES_HILUX, rotulo="R", pagina=1, indice=1)
    assert celulas[0].versoes_cobertas == (VERSOES_HILUX[0],)


# ------------------------------------------------------------------ coluna da versão
def test_coluna_da_versao_por_nome_exato():
    cabecalho = ["VERSÃO", *VERSOES_HILUX]
    assert coluna_da_versao(cabecalho, "SRX Plus AT") == 6
    assert coluna_da_versao(cabecalho, "SRX AT") == 5
    assert coluna_da_versao(cabecalho, "SR AT") == 3


def test_coluna_da_versao_com_carroceria_no_pedido():
    """O gabarito chama a versão de "SRX Plus AT (Cabine Dupla)"."""
    cabecalho = ["VERSÃO", *VERSOES_HILUX]
    assert coluna_da_versao(cabecalho, "SRX Plus AT (Cabine Dupla)") == 6


def test_coluna_desconhecida_devolve_none_em_vez_de_chutar():
    cabecalho = ["VERSÃO", *VERSOES_HILUX]
    assert coluna_da_versao(cabecalho, "GR-Sport") is None
    assert coluna_da_versao(cabecalho, "") is None


def test_pedido_ambiguo_devolve_none():
    """Duas colunas casando igualmente bem é motivo para não escolher nenhuma."""
    assert coluna_da_versao(["VERSÃO", "Extreme", "Extreme"], "Extreme") is None


# ---------------------------------------------------- critério de aceite da spec
def test_recorte_da_srx_plus_bate_com_o_gabarito(recorte, hilux_do_gabarito):
    """Os valores do recorte contra a verdade-terra, sem repetir números aqui."""
    esperado = {c.campo: c.valor for c in hilux_do_gabarito.campos if c.valor is not None}

    pneus = recorte.valor("Pneus")
    assert pneus == esperado["pneus_medida"], f"{pneus!r} != {esperado['pneus_medida']!r}"

    rodas = recorte.valor("Rodas")
    assert esperado["rodas_material"].lower() in rodas.lower()
    assert str(esperado["rodas_aro_pol"]) in rodas

    torque = recorte.valor("Torque")
    assert "50,9" in torque and "2.800" in torque

    potencia = recorte.valor("Potência")
    assert "204" in potencia and "3.400" in potencia

    traseira = recorte.valor("Traseira")
    assert esperado["suspensao_traseira"].split(",")[0].lower() in traseira.lower()
    assert "barra estabilizadora" in traseira.lower()


def test_texto_do_recorte_contem_potencia_e_torque(recorte):
    """Critério de aceite literal: o texto recortado contém "204/" e "50,9/".

    No PDF o texto é `204 / 3.400`, com espaços; `"204/"` como substring literal não
    ocorre. A checagem é com espaço opcional, que é o que o critério quer dizer — a mesma
    constatação de DECISOES_NOITE D-21 sobre os trechos montados por humano.
    """
    assert re.search(r"204\s*/", recorte.texto)
    assert re.search(r"50,9\s*/", recorte.texto)
    assert "265/60 R18" in recorte.texto


def test_recorte_encontrou_as_seis_versoes(recorte):
    for nome in VERSOES_HILUX:
        assert nome in recorte.versoes_da_tabela, nome
    assert recorte.encontrou_a_versao
    assert not recorte.avisos


def test_recorte_agrega_especificacao_e_equipamento(recorte):
    """Regressão: ficar com "a maior tabela" devolvia 35 equipamentos e zero especificação.

    A ficha MY26 tem especificação numa página e equipamentos em outra, com contagens de
    coluna diferentes. Perder uma delas em silêncio custaria justamente os campos medidos.
    """
    assert recorte.valor("Pneus"), "faltou a tabela de especificação"
    assert recorte.valor("Faróis"), "faltou a tabela de equipamentos"
    paginas = {c.pagina for c in recorte.celulas}
    assert len(paginas) >= 2, f"células de uma só página: {paginas}"
    assert len(recorte.celulas) > 100


def test_cada_celula_carrega_pagina_e_linha(recorte):
    """Proveniência: sem página e linha, duas fontes viram sobrescrita."""
    for celula in recorte.celulas:
        assert celula.pagina >= 1
        assert celula.linha >= 0
        assert celula.versoes_cobertas
        assert "SRX Plus AT" in celula.versoes_cobertas


def test_versao_inexistente_no_documento_avisa_em_vez_de_recortar(doc):
    recorte = recortar(doc, "GR-Sport")
    assert not recorte.encontrou_a_versao
    assert recorte.celulas == []
    assert recorte.avisos
    assert "não corresponde a nenhuma coluna" in recorte.avisos[0]


def test_versoes_do_documento_lista_os_cabecalhos(doc):
    nomes = versoes_do_documento(doc)
    for esperado in VERSOES_HILUX:
        assert esperado in nomes


# ---------------------------------------------------------------------- sem grade
def test_documento_sem_grade_avisa_e_preserva_o_texto():
    """Motor sem geometria não pode recortar — e diz isso, em vez de adivinhar."""
    documento = DocumentoPdf(markdown="Pneus 265/65 R17 265/60 R18", tabelas=[], motor="pypdf")
    recorte = recortar(documento, "SRX Plus AT")
    assert not recorte.grade_disponivel
    assert recorte.celulas == []
    assert recorte.texto == documento.markdown
    assert "não expõe a grade" in recorte.avisos[0]
    assert "pdfplumber" in recorte.avisos[0]


def test_tabela_sem_cabecalho_de_versao_avisa():
    tabela = Tabela(pagina=1, linhas=[["Rótulo", "a", "b"], ["Pneus", "x", "y"]])
    recorte = recortar_tabela(tabela, "SRX Plus AT")
    assert not recorte.grade_disponivel
    assert "cabeçalho" in recorte.avisos[0]


def test_recorte_serializa_para_dict(recorte):
    dados = recorte.to_dict()
    assert dados["versao"] == "SRX Plus AT"
    assert dados["coluna"] == 6 or dados["coluna"] == 5
    assert dados["celulas"]
    primeira = dados["celulas"][0]
    for chave in ("rotulo", "valor", "coluna", "alcance", "versoes_cobertas", "compartilhado"):
        assert chave in primeira
