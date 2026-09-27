"""WP-09 — limpeza do markdown de página.

Duas garantias, e a segunda importa mais que a primeira:

1. tira navegação, cookies e rodapé jurídico;
2. **não perde especificação** e **não reescreve** o que fica — se reescrevesse, o
   `evidence_quote` deixaria de ser localizável no texto salvo e o grounding cairia.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.parse.html import (
    LIMITE_PARAGRAFO_JURIDICO,
    dividir_em_blocos,
    limpar,
    limpar_markdown,
)

RAW = Path(__file__).resolve().parent.parent.parent / "gabarito" / "raw"
PAGINAS = (
    "chevrolet_s10_site.md",
    "vw_amarok.md",
    "toyota_hilux_site.md",
    "ford_raptor_site_versao.md",
)


def _texto(nome: str) -> str:
    return (RAW / nome).read_text(encoding="utf-8")


# --------------------------------------------------------------- o que tem de sair
def test_navegacao_sai():
    bruto = "Menu\nSobre a S10\nPerformance\nSolicitar contato\nPotência 397 cv\n"
    resultado = limpar_markdown(bruto)
    assert "Potência 397 cv" in resultado.texto
    assert "Performance" not in resultado.texto
    assert "Solicitar contato" not in resultado.texto
    assert resultado.por_regra()["navegacao"] >= 3


def test_rodape_juridico_longo_sai_classificado_como_juridico():
    juridico = (
        "A Volkswagen do Brasil informa que importadores de veículos independentes "
        "não estão autorizados a importar veículos pela Empresa. " + "Texto legal. " * 40
    )
    assert len(juridico) >= LIMITE_PARAGRAFO_JURIDICO
    resultado = limpar_markdown(f"Potência 258 cv\n{juridico}\n")
    assert "Potência 258 cv" in resultado.texto
    assert "importadores de veículos independentes" not in resultado.texto
    assert resultado.por_regra().get("juridico") == 1


def test_frase_promocional_curta_sai_como_promocional():
    resultado = limpar_markdown("Imagem meramente ilustrativa.\nTorque 583 Nm\n")
    assert "Torque 583 Nm" in resultado.texto
    assert resultado.por_regra().get("promocional") == 1


def test_social_e_contato_saem():
    bruto = (
        "@toyotadobrasil\n/toyotabrasil\nSAC: 0800 703 0206\n"
        "clientes@sac.toyota.com.br\nPneus 265/60 R18\n"
    )
    resultado = limpar_markdown(bruto)
    assert "265/60 R18" in resultado.texto
    assert resultado.por_regra()["social"] == 4


# ------------------------------------------------------------ o que NÃO pode sair
@pytest.mark.parametrize(
    ("pagina", "chaves"),
    [
        ("chevrolet_s10_site.md", ["High Country", "2.8", "turbodiesel"]),
        ("vw_amarok.md", ["V6", "Extreme"]),
        ("toyota_hilux_site.md", ["SRX Plus", "265/60"]),
        ("ford_raptor_site_versao.md", ["397", "583", "FOX", "Matrix"]),
    ],
)
def test_limpeza_nao_perde_especificacao(pagina, chaves):
    bruto = _texto(pagina)
    limpo = limpar(bruto)
    perdidas = [c for c in chaves if c in bruto and c not in limpo]
    assert not perdidas, f"a limpeza engoliu {perdidas}"


@pytest.mark.parametrize("pagina", PAGINAS)
def test_toda_linha_mantida_e_identica_a_original(pagina):
    """A garantia que o grounding depende: nada de reescrever o que fica."""
    bruto = _texto(pagina)
    originais = {linha.rstrip() for linha in bruto.splitlines()}
    for linha in limpar(bruto).splitlines():
        if linha.strip():
            assert linha in originais, f"linha reescrita pela limpeza: {linha[:80]!r}"


@pytest.mark.parametrize("pagina", PAGINAS)
def test_limpeza_registra_o_que_tirou(pagina):
    """Limpeza silenciosa que engole uma especificação é indistinguível de fonte pobre."""
    resultado = limpar_markdown(_texto(pagina))
    assert resultado.n_removidas > 0
    assert sum(resultado.por_regra().values()) == resultado.n_removidas
    for regra, _ in resultado.removidas:
        assert regra in {"navegacao", "social", "juridico", "promocional"}


@pytest.mark.parametrize("pagina", PAGINAS)
def test_limpeza_nao_esvazia_a_pagina(pagina):
    bruto = _texto(pagina)
    limpo = limpar(bruto)
    assert len(limpo) > 0.5 * len(bruto), "removeu mais da metade: heurística agressiva demais"


def test_cabecalho_de_proveniencia_e_preservado():
    """O título e a linha `**URL:**` são proveniência, não conteúdo de página."""
    bruto = "# S10 2027 | Chevrolet Brasil\n\n**URL:** https://www.chevrolet.com.br/picapes/s10\n\nMenu\n"
    limpo = limpar(bruto)
    assert "**URL:** https://www.chevrolet.com.br/picapes/s10" in limpo
    assert "# S10 2027" in limpo
    assert "Menu" not in limpo


def test_palavra_de_menu_dentro_de_frase_nao_e_removida():
    """ "Performance" sozinho é menu; dentro de uma frase é conteúdo."""
    bruto = "Performance\nA performance do motor V6 entrega 397 cv\n"
    limpo = limpar(bruto)
    assert "A performance do motor V6 entrega 397 cv" in limpo
    assert "\nPerformance\n" not in f"\n{limpo}\n"


# ------------------------------------------------------------------------- chunking
def test_blocos_nao_estouram_o_limite_e_nao_perdem_linha():
    texto = _texto("vw_amarok.md")
    blocos = dividir_em_blocos(texto, max_chars=6000)
    assert len(blocos) > 1
    assert all(len(b) <= 6000 for b in blocos)
    linhas_originais = [linha for linha in texto.splitlines() if linha.strip()]
    linhas_nos_blocos = [linha for b in blocos for linha in b.splitlines() if linha.strip()]
    assert len(linhas_nos_blocos) == len(linhas_originais)


def test_texto_pequeno_vira_um_bloco():
    assert dividir_em_blocos("linha unica", max_chars=6000) == ["linha unica"]


def test_blocos_preferem_cortar_em_linha_vazia():
    texto = "\n".join(["a" * 100, "", "b" * 100, "", "c" * 100])
    blocos = dividir_em_blocos(texto, max_chars=220)
    assert len(blocos) >= 2
    # nenhum bloco começa no meio de uma linha de 100 caracteres
    for bloco in blocos:
        for linha in bloco.splitlines():
            assert linha.strip() in {"a" * 100, "b" * 100, "c" * 100, ""}
