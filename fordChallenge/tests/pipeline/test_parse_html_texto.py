"""HTML bruto vira texto antes de virar evidência.

Medido ao vivo em 13/09/2026, na primeira pesquisa da Triton com o modelo de verdade: o
Pesquisador entregava ao extrator o `resposta.text` do `fetch` — **HTML cru**. As citações
gravadas traziam `<p class="content-text__container">`, e o fast-path achou "1.6l" e "5.5l"
dentro de caminhos de `<svg d="...">` e gravou como cilindrada. O pipeline clássico nunca
passou por isso porque lê o markdown que o navegador salvou; a pesquisa lê da rede.

Duas garantias: o texto que sobra é legível (é o que a gaveta de evidência mostra), e o que
não é conteúdo — script, estilo, SVG, cabeçalho — não entra, porque é de lá que saem os
números falsos.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.parse.html import decodificar_html, html_para_texto, parece_html

FIXTURES_HTML = Path(__file__).resolve().parents[1] / "fixtures" / "html"

PAGINA = """<!DOCTYPE html><html lang="pt-BR"><head><title>Triton</title>
<style>.x{width:1.6l}</style><script>var a = "2.9l";</script></head>
<body><nav><a href="/">Início</a></nav>
<h1>Mitsubishi Triton HPE-S</h1>
<svg viewBox="0 0 24 24"><path d="M87.4,27.5c0-3.4-2.5-6-5.8-6 5.5l"/></svg>
<p class="content-text__container">Comprimento: 5,285 m</p>
<p>Motor 2.4 litros, <b>205 cv</b> &amp; 470 Nm</p>
<table><tr><td>Airbags</td><td>7</td></tr></table>
<noscript>ative o javascript</noscript>
</body></html>"""


class TestConversao:
    def test_tags_somem_e_o_conteudo_fica_legivel(self):
        texto = html_para_texto(PAGINA)
        assert "<p" not in texto and "<svg" not in texto and "class=" not in texto
        assert "Comprimento: 5,285 m" in texto
        assert "Motor 2.4 litros, 205 cv & 470 Nm" in texto
        assert "Mitsubishi Triton HPE-S" in texto

    def test_script_estilo_svg_e_noscript_nao_viram_numero(self):
        texto = html_para_texto(PAGINA)
        for lixo in ("1.6l", "2.9l", "5.5l", "M87.4", "ative o javascript"):
            assert lixo not in texto, lixo

    def test_blocos_viram_linhas_separadas(self):
        texto = html_para_texto(PAGINA)
        linhas = [linha for linha in texto.splitlines() if linha.strip()]
        assert "Comprimento: 5,285 m" in linhas
        # Célula de tabela ao lado do rótulo: o fast-path lê pares rótulo/valor por linha.
        assert any("Airbags" in linha and "7" in linha for linha in linhas)

    def test_texto_que_nao_e_html_volta_intacto(self):
        puro = "Ficha técnica\nPotência: 205 cv\n"
        assert not parece_html(puro)
        assert html_para_texto(puro) == puro

    def test_html_e_reconhecido_por_estrutura_nao_por_extensao(self):
        assert parece_html(PAGINA)
        assert parece_html("<html><body>oi</body></html>")
        assert parece_html("<div><p>a</p><p>b</p></div>")
        assert not parece_html("a < b e c > d")

    def test_html_vazio_ou_quebrado_nao_levanta(self):
        assert html_para_texto("") == ""
        assert "oi" in html_para_texto("<div><p>oi")


#: Uma ficha em layout de tabela aninhada, como os sites de ficha antigos (ASP) escrevem:
#: a página inteira dentro de uma `<table>` de layout, e a ficha numa `<table>` dentro dela.
FICHA_ANINHADA = """<html><body>
<table><tr><td>
  <table><tr><td>Menu</td><td>Catálogo</td></tr></table>
  <table>
    <tr><th>Motor</th><th>2.8 Turbodiesel</th></tr>
    <tr><td>Potência máxima</td><td>207 cv</td></tr>
    <tr><td>Torque máximo</td><td>52,0 kgfm</td></tr>
    <tr><td>Cilindros</td><td>4 em linha</td></tr>
    <tr><td>Suspensão</td><td>Dianteira<br>Traseira</td></tr>
  </table>
</td></tr></table>
</body></html>"""


class TestTabelaAninhada:
    """Medido em 13/09/2026 na ficha da S10 do `carrosnaweb`: 13 mil caracteres viravam
    **3 linhas** e o fast-path lia 2 campos. A `<tr>` de layout, processada primeiro,
    engolia a tabela da ficha inteira e devolvia tudo numa linha só."""

    def test_a_tabela_de_dentro_sobrevive_a_tabela_de_layout(self):
        linhas = [linha for linha in html_para_texto(FICHA_ANINHADA).splitlines() if linha.strip()]
        assert "Potência máxima	207 cv" in linhas
        assert "Torque máximo	52,0 kgfm" in linhas
        assert "Cilindros	4 em linha" in linhas
        assert "Motor	2.8 Turbodiesel" in linhas, "o cabeçalho `th` também é par rótulo/valor"

    def test_a_pagina_nao_colapsa_numa_linha(self):
        linhas = [linha for linha in html_para_texto(FICHA_ANINHADA).splitlines() if linha.strip()]
        assert len(linhas) >= 6, linhas
        com_tab = [linha for linha in linhas if "	" in linha]
        assert len(com_tab) >= 5, com_tab

    def test_a_quebra_dentro_da_celula_separa_os_dois_valores(self):
        """`<br>` dentro de célula vira **espaço**, não linha nova.

        Virar linha partiria o par rótulo/valor em dois — "Suspensão" numa linha e
        "Dianteira" na outra —, e é justamente o par que o fast-path lê.
        """
        linhas = [linha for linha in html_para_texto(FICHA_ANINHADA).splitlines() if linha.strip()]
        assert "Suspensão\tDianteira Traseira" in linhas

    def test_a_linha_de_menu_nao_vira_par_da_ficha(self):
        linhas = [linha for linha in html_para_texto(FICHA_ANINHADA).splitlines() if linha.strip()]
        assert "Menu	Catálogo" in linhas, "a tabela de menu vira a sua própria linha, não some"


class TestDecodificarHtml:
    """A ficha do `carrosnaweb` é windows-1252; sem isto o `httpx` a decodifica como
    utf-8 com substituição, o acento vira "�" e o `evidence_quote` verbatim deixa de
    casar no texto salvo — o grounding falha em silêncio. Fixture real, em bytes, salva
    em `tests/fixtures/html/carrosnaweb_ficha_cp1252.html`.
    """

    def test_decodifica_pelo_meta_charset_da_pagina(self):
        conteudo = (FIXTURES_HTML / "carrosnaweb_ficha_cp1252.html").read_bytes()
        saida = decodificar_html(conteudo)
        assert "�" not in saida
        assert "Potência máxima" in saida
        assert "kgfm a 3500 rpm" in saida
        assert "SUSPENSÃO" in saida

    def test_nunca_usa_errors_replace_mesmo_sem_meta_charset(self):
        # Os mesmos bytes, sem a pista do <meta charset> — só o fallback cp1252 resolve.
        conteudo = "Suspensão dianteira".encode("windows-1252")
        saida = decodificar_html(conteudo)
        assert "�" not in saida
        assert saida == "Suspensão dianteira"

    def test_texto_utf8_continua_utf8(self):
        conteudo = "Potência máxima".encode()
        assert decodificar_html(conteudo) == "Potência máxima"

    def test_declarado_tem_prioridade_sobre_o_fallback(self):
        conteudo = "Suspensão".encode("windows-1252")
        assert decodificar_html(conteudo, declarado="windows-1252") == "Suspensão"
