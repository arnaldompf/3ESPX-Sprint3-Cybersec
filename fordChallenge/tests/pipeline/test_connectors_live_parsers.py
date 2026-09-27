"""WP-07 — os parsers do caminho ao vivo, exercitados sem rede.

Os conectores só buscam a página fora de `REPLAY_MODE`, mas o **parser** é código como
qualquer outro e precisa de teste. Aqui ele roda contra HTML sintético e contra os textos
já salvos em `gabarito/raw/`, sem uma única requisição.

O que estes testes travam vem de defeito real observado numa coleta ao vivo da Amarok
(a única das quatro marcas que respondeu 200 a um cliente HTTP simples nesta noite).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.connectors.chevrolet import parse_lineup_html as parse_gm
from pipeline.connectors.ford import parse_lineup_html as parse_ford
from pipeline.connectors.toyota import parse_lineup_html as parse_toyota
from pipeline.connectors.vw import parse_lineup_html as parse_vw

RAW = Path(__file__).resolve().parent.parent.parent / "gabarito" / "raw"


# ------------------------------------------------------------------------------- VW
def test_vw_nao_produz_duplicata_por_sufixo():
    """Defeito real: a coleta ao vivo devolvia "V6 Extreme" **e** "Extreme".

    O rótulo aparece sozinho em outro ponto da página. Duas entradas para a mesma versão
    fariam o resolvedor responder `ambigua` para "Extreme" — o pedido mais comum.
    """
    html = (
        "<p>Amarok V6 Extreme R$ 379.990</p><p>Conheca a Extreme</p>"
        "<p>V6 Highline R$ 356.990</p><p>V6 Comfortline R$ 339.990</p>"
    )
    versoes = parse_vw(html, modelo="Amarok", url="https://exemplo.test")
    nomes = [v.nome_exato for v in versoes]
    assert nomes == ["V6 Comfortline", "V6 Highline", "V6 Extreme"]
    assert {v.preco_a_partir_brl for v in versoes} == {339990, 356990, 379990}


def test_vw_nao_inventa_versao_atravessando_fronteira_de_bloco():
    """Defeito real: o regex capturava "Extreme V6" de "...Extreme</p><p>V6 Highline"."""
    html = "<p>Extreme</p><p>V6 Highline</p>"
    nomes = [v.nome_exato for v in parse_vw(html, modelo="Amarok")]
    assert "Extreme V6" not in nomes


def test_vw_ignora_preco_fora_de_faixa_plausivel():
    html = "<p>V6 Extreme R$ 379.990</p><p>V6 Highline R$ 1.990</p>"
    precos = {v.nome_exato: v.preco_a_partir_brl for v in parse_vw(html, modelo="Amarok")}
    assert precos["V6 Extreme"] == 379990
    assert precos["V6 Highline"] is None, "R$ 1.990 não é preço de picape; melhor None"


# ---------------------------------------------------------------------------- Toyota
def test_toyota_le_so_o_bloco_conheca_as_versoes():
    """A palavra "SRX" aparece dezenas de vezes em nota de rodapé da página salva.

    Varrer a página inteira produziria duplicatas e falsos positivos; o parser tem de
    ficar dentro do bloco de versões.
    """
    texto = (RAW / "toyota_hilux_site.md").read_text(encoding="utf-8")
    versoes = parse_toyota(texto, modelo="Hilux", url="https://exemplo.test", ano_modelo=2026)
    nomes = [v.nome_exato for v in versoes]
    assert "SRX Plus AT" in nomes
    assert "SRX AT" in nomes
    assert "SR AT" in nomes
    assert len(nomes) == len(set(nomes)), "sem duplicata"
    assert len(nomes) <= 8, f"parser vazou para fora do bloco: {nomes}"


def test_toyota_nao_inventa_gr_sport_a_partir_do_texto_da_pagina():
    """O caso negativo depende disso: a GR-Sport não pode aparecer na linha 2026."""
    texto = (RAW / "toyota_hilux_site.md").read_text(encoding="utf-8")
    nomes = [v.nome_exato.lower() for v in parse_toyota(texto, modelo="Hilux")]
    assert not any("gr" in n and "sport" in n for n in nomes)


# ------------------------------------------------------------------------------ Ford
def test_ford_reconhece_o_nome_exato_da_raptor_na_pagina_salva():
    texto = (RAW / "ford_raptor_site_versao.md").read_text(encoding="utf-8")
    versoes = parse_ford(texto, modelo="Ranger", url="https://exemplo.test")
    nomes = [v.nome_exato for v in versoes]
    assert any(n.startswith("Raptor 3.0 V6 Bi-turbo") for n in nomes), nomes
    assert all(v.ano_modelo and 2020 <= v.ano_modelo <= 2035 for v in versoes)


def test_ford_exige_ano_modelo_para_aceitar_uma_versao():
    """Nome sem ano-modelo por perto é menção solta, não entrada de catálogo."""
    assert parse_ford("<p>Ranger Raptor é uma picape</p>", modelo="Ranger") == []
    assert parse_ford("<p>XLT 2.0 Diesel 4x4 AT 2026</p>", modelo="Ranger")


# ------------------------------------------------------------------------- Chevrolet
def test_chevrolet_reconhece_as_versoes_na_pagina_salva():
    texto = (RAW / "chevrolet_s10_site.md").read_text(encoding="utf-8")
    nomes = {v.nome_exato.lower() for v in parse_gm(texto, modelo="S10", url="https://x")}
    assert any("high country" in n for n in nomes), nomes


@pytest.mark.parametrize("parser", [parse_ford, parse_toyota, parse_vw, parse_gm])
def test_parser_com_html_vazio_devolve_lista_vazia(parser):
    """Página vazia é linha vigente desconhecida, nunca uma versão inventada."""
    assert parser("", modelo="Qualquer") == []
    assert parser("<html><body></body></html>", modelo="Qualquer") == []
