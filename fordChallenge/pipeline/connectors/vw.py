"""Conector Volkswagen Brasil.

Linha vigente: `vw.com.br/pt/carros/<modelo>.html`. **Sem PDF de ficha técnica** — a VW
não publica um; por isso a cobertura da Amarok depende mais da página e da imprensa
(tier 3), e é dela que vêm os `nao_encontrado` legítimos dos modos de condução.
"""

from __future__ import annotations

import re

from pipeline.connectors import _http
from pipeline.connectors.base import Connector, ResultadoLinha, SourceRef, VersionInfo, slug

BASE = "https://www.vw.com.br/pt/carros"

#: Páginas de imprensa (tier 3) que cobrem preço e equipamentos por versão.
IMPRENSA: dict[str, str] = {
    "amarok": (
        "https://autoesporte.globo.com/setor-automotivo/mercado-automotivo/noticia/2025/08/"
        "volkswagen-amarok-2026-precos-versoes-equipamentos.ghtml"
    ),
}


class VWConnector(Connector):
    marca = "Volkswagen"
    dominio = "vw.com.br"
    modelos = ("Amarok", "Saveiro", "Taos", "Nivus")
    tier = 1

    def url_do_modelo(self, modelo: str) -> str:
        return f"{BASE}/{slug(modelo)}.html"

    def lineup_live(self, modelo: str) -> ResultadoLinha:
        url = self.url_do_modelo(modelo)
        resultado = ResultadoLinha(url=url, origem=f"coleta ao vivo em {url}")
        try:
            html = _http.get_text(url)
        except _http.FonteBloqueada as exc:
            resultado.bloqueadas.append(url)
            resultado.nota = f"fonte bloqueada: {exc}"
            return resultado
        resultado.versoes = parse_lineup_html(html, modelo=modelo, url=url)
        if not resultado.versoes:
            resultado.nota = "nenhuma versão reconhecida na página do modelo"
        return resultado

    def sources(self, versao: VersionInfo) -> list[SourceRef]:
        fontes: list[SourceRef] = []
        if versao.url:
            fontes.append(SourceRef(versao.url, "pagina_oficial", 1))
        imprensa = IMPRENSA.get(slug(versao.modelo or ""))
        if imprensa:
            fontes.append(
                SourceRef(
                    imprensa,
                    "imprensa",
                    3,
                    "a VW não publica PDF de ficha técnica; imprensa cobre preço por versão",
                )
            )
        return fontes


# ---------------------------------------------------------------------- parser ao vivo
#: A VW escreve "V6 Extreme", nunca "Extreme V6". Um sufixo `(?:\s+V6)?` opcional fazia o
#: regex atravessar a fronteira de bloco e capturar "Extreme V6" de
#: "...Extreme</p><p>V6 Highline" — versão que não existe.
_VERSAO = re.compile(
    r"\b(?P<nome>(?:V6\s+)?(?:Extreme|Highline|Comfortline|Trendline|Pacific|Robust))\b"
)
_PRECO = re.compile(r"R\$\s?(?P<valor>[\d.]{6,12})")


def parse_lineup_html(html: str, *, modelo: str = "", url: str = "") -> list[VersionInfo]:
    """Extrai versões da página do modelo, com o preço quando estiver por perto.

    Como a VW usa os mesmos rótulos de acabamento em vários modelos, o parser só aceita
    os rótulos conhecidos e nunca deduz um nome a partir de texto solto.
    """
    texto = re.sub(r"<[^>]+>", " ", html)
    texto = re.sub(r"\s+", " ", texto)
    vistos: dict[str, VersionInfo] = {}
    for achado in _VERSAO.finditer(texto):
        nome = " ".join(achado.group("nome").split())
        janela = texto[achado.end() : achado.end() + 200]
        preco = None
        preco_achado = _PRECO.search(janela)
        if preco_achado:
            bruto = preco_achado.group("valor").replace(".", "")
            if bruto.isdigit() and 50_000 <= int(bruto) <= 2_000_000:
                preco = int(bruto)
        chave = nome.lower()
        anterior = vistos.get(chave)
        if anterior is None or (anterior.preco_a_partir_brl is None and preco is not None):
            vistos[chave] = VersionInfo(
                nome_exato=nome,
                preco_a_partir_brl=preco,
                url=url,
                marca="Volkswagen",
                modelo=modelo,
            )
    return _sem_sufixos_redundantes(vistos)


def _sem_sufixos_redundantes(vistos: dict[str, VersionInfo]) -> list[VersionInfo]:
    """Descarta o nome que é sufixo de outro já reconhecido.

    A coleta ao vivo da Amarok devolvia "V6 Extreme" **e** "Extreme": o rótulo aparece
    sozinho em outro ponto da página. Duas entradas para a mesma versão fariam o
    resolvedor responder `ambigua` para "Extreme", que é justamente o pedido mais comum.
    """
    nomes = sorted(vistos, key=len, reverse=True)
    manter: list[str] = []
    for chave in nomes:
        if any(mantido.endswith(chave) and mantido != chave for mantido in manter):
            continue
        manter.append(chave)
    return [vistos[c] for c in nomes if c in manter]
