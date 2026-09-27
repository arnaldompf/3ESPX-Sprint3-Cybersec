"""Conector Ford Brasil.

Linha vigente: `ford.com.br/picapes/<modelo>/`. Fontes de atributos: a página da versão
mais o PDF de ficha técnica — a ficha traz o que a página não traz (modos de condução,
por exemplo) e é a fonte que expôs a divergência com o slide interno.
"""

from __future__ import annotations

import re

from pipeline.connectors import _http
from pipeline.connectors.base import (
    Connector,
    ResultadoLinha,
    SourceRef,
    VersionInfo,
    slug,
)

BASE = "https://www.ford.com.br"

#: PDFs de ficha técnica conhecidos, por modelo+versão (a URL não é derivável do nome).
FICHAS_PDF: dict[str, str] = {
    "raptor": (
        "https://www.ford.com.br/content/dam/Ford/website-assets/latam/br/nameplate/2025/"
        "ranger-raptor/pdf/fbr-ranger-raptor-ficha-tecnica.pdf"
    ),
    # A ficha da linha Ranger (não-Raptor) é uma só, com uma coluna por versão. O
    # `version_slicer` recorta a coluna certa; sem ele, a Limited herdaria número da XL.
    "limited": (
        "https://www.ford.com.br/content/dam/Ford/website-assets/latam/br/nameplate/2025/"
        "nova-geracao-ranger/pdf/fbr-ranger-ficha-tecnica.pdf"
    ),
    "xlt": (
        "https://www.ford.com.br/content/dam/Ford/website-assets/latam/br/nameplate/2025/"
        "nova-geracao-ranger/pdf/fbr-ranger-ficha-tecnica.pdf"
    ),
    "xls": (
        "https://www.ford.com.br/content/dam/Ford/website-assets/latam/br/nameplate/2025/"
        "nova-geracao-ranger/pdf/fbr-ranger-ficha-tecnica.pdf"
    ),
}

#: Página que lista **todas** as versões com o "a partir de". É a rota que tem o dado.
#:
#: Medido em 10/09/2026, e o resultado é menos óbvio do que "a Ford bloqueia":
#:
#: * `ford.com.br/picapes/ranger/` responde **200** ao cliente HTTP — e o HTML não tem
#:   versão nem preço nenhum: a página monta a linha por JavaScript. Coletar dali e não
#:   reconhecer nada não é bloqueio, é página vazia para quem não roda script;
#: * a mesma raiz responde **403 (Akamai)** ao Chromium do Playwright. O escudo pega o
#:   navegador headless, não o cliente simples;
#: * `ford.com.br/picapes/ranger/compare-as-versoes.html` responde **200** ao cliente
#:   simples **com** as 12 versões e os preços no HTML.
#:
#: Não há truque nisso: é outra rota do mesmo site oficial, com o mesmo user-agent
#: identificado e o mesmo robots.txt consultado antes.
COMPARADOR_DE_VERSOES = f"{BASE}/picapes/{{modelo}}/compare-as-versoes.html"


class FordConnector(Connector):
    marca = "Ford"
    dominio = "ford.com.br"
    modelos = ("Ranger", "Ranger Raptor", "Maverick")
    tier = 1

    # ------------------------------------------------------------------ linha vigente
    def url_do_modelo(self, modelo: str) -> str:
        return f"{BASE}/picapes/{slug(modelo)}/"

    def url_do_comparador(self, modelo: str) -> str:
        """A rota que lista todas as versões com preço. Ver :data:`COMPARADOR_DE_VERSOES`."""
        return COMPARADOR_DE_VERSOES.format(modelo=slug(modelo))

    def lineup_live(self, modelo: str) -> ResultadoLinha:
        """Coleta a linha vigente na página do modelo.

        A Ford lista as versões em blocos com o nome exato e o preço "a partir de".
        O parser é deliberadamente conservador: extrai o que reconhece e **não** completa
        o que não reconheceu — linha vigente incompleta é melhor que linha inventada.
        """
        url = self.url_do_modelo(modelo)
        resultado = ResultadoLinha(url=url, origem=f"coleta ao vivo em {url}")
        try:
            html = _http.get_text(url)
        except _http.FonteBloqueada as exc:
            resultado.bloqueadas.append(url)
            html = ""
            motivo_da_raiz = f"fonte bloqueada: {exc}"
        else:
            motivo_da_raiz = ""

        resultado.versoes = (
            parse_lineup_html(html, marca=self.marca, modelo=modelo, url=url) if html else []
        )
        if resultado.versoes:
            return resultado

        # A raiz não deu linha — por bloqueio ou porque monta tudo por JavaScript. Os
        # dois casos têm a mesma saída: tentar a rota irmã do **mesmo site oficial**,
        # que publica a linha com preço em HTML. Se ela também não der, aí sim acabou.
        alternativa = self.url_do_comparador(modelo)
        try:
            html_alternativo = _http.get_text(alternativa)
        except _http.FonteBloqueada as exc_alt:
            resultado.bloqueadas.append(alternativa)
            resultado.nota = (
                motivo_da_raiz + " · " if motivo_da_raiz else ""
            ) + f"e o comparador de versões também: {exc_alt}"
            return resultado

        resultado.versoes = parse_lineup_html(
            html_alternativo, marca=self.marca, modelo=modelo, url=alternativa
        )
        resultado.url = alternativa
        resultado.origem = f"coleta ao vivo em {alternativa}"
        resultado.nota = (
            motivo_da_raiz or f"a página do modelo ({url}) respondeu sem nenhuma versão no HTML"
        ) + "; a linha vigente veio do comparador de versões, do mesmo site oficial"
        if not resultado.versoes:
            resultado.nota += " — e nem ali nenhuma versão foi reconhecida: o layout mudou"
        return resultado

    # -------------------------------------------------------------------------- fontes
    def sources(self, versao: VersionInfo) -> list[SourceRef]:
        fontes: list[SourceRef] = []
        if versao.url:
            fontes.append(SourceRef(versao.url, "pagina_oficial", 1))
        chave = next(
            (k for k in FICHAS_PDF if k in slug(versao.nome_exato)),
            None,
        )
        if chave:
            fontes.append(SourceRef(FICHAS_PDF[chave], "pdf_oficial", 1, "ficha técnica oficial"))
        return fontes


# ---------------------------------------------------------------------- parser ao vivo
#: Rótulos de versão da Ford Ranger/Maverick.
_ROTULOS = r"Raptor|Limited|Wildtrak|Storm|Black|XLT|XLS|XL"

#: "Raptor 3.0 V6 Bi-turbo 4WD AT 2026", "XLT 2.0 Turbo Diesel 4x4 AT 2026", etc.
#:
#: A negativa `(?!\s+(?:rótulo))` existe por defeito real: a página traz
#: "Ranger Raptor" seguido de "Raptor 3.0 V6 Bi-turbo 4WD AT 2026", e sem ela o match
#: começava no primeiro "Raptor" e produzia o nome duplicado
#: "Raptor Raptor 3.0 V6 Bi-turbo 4WD AT".
_NOME_VERSAO = re.compile(
    r"\b(?P<nome>(?:" + _ROTULOS + r")(?!\s+(?:" + _ROTULOS + r")\b)"
    r"(?:\s+[\w.,ºª\-À-ÿ]+){0,7}?)\s+(?P<ano>20\d{2})\b"
)
_PRECO = re.compile(r"R\$\s?(?P<valor>[\d.]{6,12})")


def parse_lineup_html(
    html: str,
    *,
    marca: str = "Ford",
    modelo: str = "",
    url: str = "",
    uma_por_rotulo: bool = True,
) -> list[VersionInfo]:
    """Extrai `(nome_exato, ano_modelo, preco)` do HTML/markdown da página do modelo.

    Conservador de propósito: só aceita nome que comece por um dos rótulos de versão
    conhecidos da Ford e que venha seguido de ano-modelo. Um regex ganancioso aqui
    inventaria versões, e versão inventada é pior que versão faltando.

    `uma_por_rotulo=False` devolve **todas** as entradas reconhecidas. O padrão continua
    colapsando por rótulo porque é o que a página do modelo exige (a mesma versão
    aparece em dois anos-modelo), mas a página do comparador é outra coisa: ali cada
    linha é uma versão diferente que compartilha o rótulo — "XL 2.0 CS Diesel 4x4 MT" e
    "XL 2.0 CD Diesel 4x4 AT" são duas, com R$ 10 mil de diferença, e colapsar as duas
    numa só esconde metade da linha vigente.
    """
    texto = re.sub(r"<[^>]+>", " ", html)
    texto = re.sub(r"\s+", " ", texto)
    vistos: dict[str, VersionInfo] = {}
    for achado in _NOME_VERSAO.finditer(texto):
        nome = achado.group("nome").strip(" -,.")
        ano = int(achado.group("ano"))
        if len(nome) < 3:
            continue
        janela = texto[achado.end() : achado.end() + 240]
        preco_achado = _PRECO.search(janela)
        preco = None
        if preco_achado:
            bruto = preco_achado.group("valor").replace(".", "")
            if bruto.isdigit() and 50_000 <= int(bruto) <= 2_000_000:
                preco = int(bruto)
        chave = nome.lower()
        anterior = vistos.get(chave)
        if anterior is None or (anterior.preco_a_partir_brl is None and preco is not None):
            vistos[chave] = VersionInfo(
                nome_exato=nome,
                ano_modelo=ano,
                preco_a_partir_brl=preco,
                url=url,
                marca=marca,
                modelo=modelo,
            )
    if not uma_por_rotulo:
        return sorted(vistos.values(), key=lambda v: (-(v.preco_a_partir_brl or 0), v.nome_exato))
    return _uma_por_rotulo(vistos.values())


def _uma_por_rotulo(versoes) -> list[VersionInfo]:
    """Uma entrada por rótulo de versão: a do ano-modelo mais recente.

    A mesma página traz o título "Conheça a versão Raptor 4WD AT **2024**" e, no corpo, o
    nome de catálogo "Raptor 3.0 V6 Bi-turbo 4WD AT **2026**". São a mesma versão em dois
    anos-modelo, e a linha **vigente** é a do ano corrente. Empate de ano fica com o nome
    mais específico, que é o de catálogo.
    """
    melhor: dict[str, VersionInfo] = {}
    for v in versoes:
        rotulo = v.nome_exato.split()[0].lower()
        atual = melhor.get(rotulo)
        if atual is None:
            melhor[rotulo] = v
            continue
        chave_nova = ((v.ano_modelo or 0), len(v.nome_exato.split()))
        chave_atual = ((atual.ano_modelo or 0), len(atual.nome_exato.split()))
        if chave_nova > chave_atual:
            melhor[rotulo] = v
    return list(melhor.values())
