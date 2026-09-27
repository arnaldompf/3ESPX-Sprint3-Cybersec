"""WP-09 — PDF para texto e grade de tabela.

Os testes rodam contra as fixtures geradas (`tests/fixtures/pdf/`), que o CI usa sem
precisar do extra `pdf` nem baixar modelo do Docling — é o que `specs/WP-09.md` pede. Os
que exigem o PDF de verdade são marcados `slow` e ficam fora do `verify-quick`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.parse.pdf import (
    DocumentoPdf,
    PdfIlegivel,
    Tabela,
    motor_preferido,
    motores_disponiveis,
    parse_arquivo,
    parse_pdf,
)

ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "gabarito" / "raw"
FIXTURES_PDF = ROOT / "tests" / "fixtures" / "pdf" / "toyota_hilux_my26"
PDF_TOYOTA = RAW / "toyota_hilux_my26_ficha_oficial.pdf"
FICHA_FORD = RAW / "ford_raptor_ficha_tecnica_oficial.txt"

tem_pdfplumber = motores_disponiveis()["pdfplumber"]
tem_docling = motores_disponiveis()["docling"]


# ------------------------------------------------------------------ fixtures geradas
@pytest.fixture(scope="module")
def doc_da_fixture() -> DocumentoPdf:
    """Documento montado a partir das fixtures — o caminho que o CI usa."""
    dados = json.loads((FIXTURES_PDF / "tables.json").read_text(encoding="utf-8"))
    markdown = (FIXTURES_PDF / "doc.md").read_text(encoding="utf-8")
    return DocumentoPdf(
        markdown=markdown,
        paginas=markdown.split("\n\n"),
        tabelas=[Tabela.from_dict(t) for t in dados["tabelas"]],
        motor=dados["motor"],
    )


def test_fixtures_do_pdf_existem_e_declaram_a_origem():
    meta = json.loads((FIXTURES_PDF / "meta.json").read_text(encoding="utf-8"))
    assert meta["arquivo_de_origem"].endswith("toyota_hilux_my26_ficha_oficial.pdf")
    assert len(meta["sha256_do_pdf"]) == 64
    assert meta["motor"] in {"pdfplumber", "docling", "pypdf", "pdftotext"}
    assert meta["paginas"] == 10


def test_doc_md_da_fixture_traz_a_linha_de_tabela_inteira(doc_da_fixture):
    """O que a WP-09 tem de entregar para o grounding funcionar.

    O gabarito registra `"204/ 3.400 (cv/rpm)"` — leitura por coluna feita por humano.
    No texto extraído a linha real é `Potência (cv/rpm)  204 / 3.400`, e é **essa** que o
    `evidence_quote` do pipeline vai citar. Ver DECISOES_NOITE D-21.
    """
    texto = doc_da_fixture.markdown
    assert "204 / 3.400" in texto
    assert "50,9 / 2.800" in texto
    assert "265/60 R18" in texto
    assert "265/65 R17" in texto


def test_grade_de_tabela_da_fixture_tem_o_cabecalho_de_versoes(doc_da_fixture):
    tabelas = [t for t in doc_da_fixture.tabelas if t.linha_de_cabecalho() is not None]
    assert tabelas, "nenhuma tabela com linha 'VERSÃO'"
    tabela = tabelas[0]
    cabecalho = tabela.linhas[tabela.linha_de_cabecalho()]
    assert cabecalho[0].strip().upper().startswith("VERS")
    assert any("SRX Plus" in (c or "") for c in cabecalho)


def test_tabela_serializa_e_desserializa_sem_perda(doc_da_fixture):
    original = doc_da_fixture.tabelas[0]
    copia = Tabela.from_dict(json.loads(json.dumps(original.to_dict())))
    assert copia.linhas == original.linhas
    assert (copia.pagina, copia.indice) == (original.pagina, original.indice)


# ------------------------------------------------------------------- PDF de verdade
@pytest.mark.skipif(not tem_pdfplumber, reason="extra `pdf` (pdfplumber) não instalado")
@pytest.mark.slow
def test_parse_do_pdf_toyota_recupera_texto_e_grade():
    documento = parse_arquivo(PDF_TOYOTA)
    assert documento.motor in {"pdfplumber", "docling"}
    assert documento.n_paginas == 10
    assert documento.tabelas, "o motor tem de expor a grade da tabela"
    assert "204 / 3.400" in documento.markdown


@pytest.mark.skipif(not tem_docling, reason="extra `docling` não instalado")
@pytest.mark.slow
def test_docling_forcado_processa_o_pdf_real_sem_fallback_mascarado():
    """Prova reproduzível da integração, usando o PDF oficial real do repositório."""
    documento = parse_arquivo(PDF_TOYOTA, motor="docling")
    assert documento.motor == "docling", "o Docling falhou e parse_pdf caiu para outro motor"
    assert documento.n_paginas == 10
    assert documento.tabelas, "o Docling precisa preservar ao menos uma grade de tabela"
    assert "204" in documento.markdown
    assert "265/60 R18" in documento.markdown


@pytest.mark.skipif(not tem_pdfplumber, reason="extra `pdf` (pdfplumber) não instalado")
@pytest.mark.slow
def test_a_fixture_gerada_bate_com_o_pdf_atual():
    """Se o PDF mudar e ninguém regerar, a fixture mente. Este teste acusa."""
    documento = parse_arquivo(PDF_TOYOTA)
    esperado = (FIXTURES_PDF / "doc.md").read_text(encoding="utf-8")
    assert documento.markdown == esperado, "rode `python scripts/build_fixtures.py`"


def test_pypdf_le_o_texto_mas_nao_expoe_grade():
    """Contrato do fallback: sem geometria, `tabelas` vem vazio — e isso é honesto.

    Devolver grade inventada seria pior que não devolver: o slicer atribuiria a coluna
    errada e o pipeline afirmaria o pneu de outra versão.
    """
    documento = parse_pdf(PDF_TOYOTA.read_bytes(), motor="pypdf")
    assert documento.motor == "pypdf"
    assert documento.tabelas == []
    assert "204" in documento.markdown


def test_conteudo_que_nao_e_pdf_levanta():
    with pytest.raises(PdfIlegivel, match="assinatura"):
        parse_pdf(b"<html>nao sou pdf</html>")


def test_motor_desconhecido_cai_para_a_ordem_de_fallback(monkeypatch):
    """Nome de motor que não existe não derruba: cai para o primeiro que funciona.

    O Docling sai da ordem de propósito. Ele carrega um modelo de visão a cada chamada: com
    ele nesta lista, **este teste sozinho levava 143 s**, e o que ele mede é o fallback, não
    a qualidade da leitura.
    """
    from pipeline.parse import pdf as modulo

    monkeypatch.setattr(
        modulo, "ORDEM_DE_FALLBACK", tuple(m for m in modulo.ORDEM_DE_FALLBACK if m != "docling")
    )
    documento = parse_pdf(PDF_TOYOTA.read_bytes(), motor="motor_que_nao_existe")
    assert documento.motor in {"pdfplumber", "pypdf", "pdftotext"}


def test_motor_pode_ser_forcado_por_env(monkeypatch):
    monkeypatch.setenv("PDF_MOTOR", "pypdf")
    assert motor_preferido() == "pypdf"
    monkeypatch.delenv("PDF_MOTOR")
    esperado = "pdfplumber" if tem_pdfplumber else "docling" if tem_docling else "pypdf"
    assert motor_preferido() == esperado


# ------------------------------------------------------------- ficha técnica da Ford
def test_ficha_da_ford_traz_paddle_shifters_e_matrix():
    """Critério de aceite da spec, sobre a ficha técnica oficial da Raptor.

    A ficha da Ford veio da coleta já como texto (`gabarito/raw/*.txt`), não como PDF —
    é o `doc.md` daquela fonte, e é onde estão os dois itens que o slide interno e a
    página da versão não trazem juntos.
    """
    texto = FICHA_FORD.read_text(encoding="utf-8")
    assert "Paddle Shifters" in texto
    assert "Matrix" in texto
    assert "Faróis Matrix LED" in texto


def test_ficha_da_ford_e_o_doc_md_do_snapshot_de_replay():
    """O mesmo texto tem de estar no snapshot, senão o grounding em replay não acha."""
    from pipeline.snapshots import snapshot_de_url
    from pipeline.store import FIXTURES

    url = (
        "https://www.ford.com.br/content/dam/Ford/website-assets/latam/br/nameplate/"
        "2025/ranger-raptor/pdf/fbr-ranger-raptor-ficha-tecnica.pdf"
    )
    snap = snapshot_de_url(url, [FIXTURES])
    assert snap.tipo == "pdf_oficial"
    assert "Paddle Shifters" in snap.texto
    assert "Matrix" in snap.texto
