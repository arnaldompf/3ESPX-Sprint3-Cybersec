"""Conector Chevrolet Brasil.

Linha vigente: `chevrolet.com.br/picapes/<modelo>` (+ "compare versões"). **Sem PDF de
ficha técnica** e com a **sala de imprensa protegida por CAPTCHA** — `media.gm.com/brasil`
está registrada como fonte `bloqueada`, e é assim que fica: bloqueio vira status, nunca
tentativa de contornar (`docs/02` ADR-7, `docs/12` §3.12).
"""

from __future__ import annotations

import re

from pipeline.connectors import _http
from pipeline.connectors.base import Connector, ResultadoLinha, SourceRef, VersionInfo, slug

BASE = "https://www.chevrolet.com.br/picapes"

#: Fonte conhecida e **bloqueada**. Fica na lista de consultadas para sustentar
#: `nao_encontrado` honesto; nunca é requisitada.
SALA_DE_IMPRENSA = "https://media.gm.com/brasil"

IMPRENSA: dict[str, str] = {
    "s10": (
        "https://autoesporte.globo.com/setor-automotivo/mercado-automotivo/noticia/2026/07/"
        "chevrolet-s10-2027-precos-versoes-equipamentos-consumo.ghtml"
    ),
}


class ChevroletConnector(Connector):
    marca = "Chevrolet"
    dominio = "chevrolet.com.br"
    modelos = ("S10", "Montana", "Silverado")
    tier = 1

    def url_do_modelo(self, modelo: str) -> str:
        return f"{BASE}/{slug(modelo)}"

    def lineup_live(self, modelo: str) -> ResultadoLinha:
        url = self.url_do_modelo(modelo)
        resultado = ResultadoLinha(url=url, origem=f"coleta ao vivo em {url}")
        # A sala de imprensa da GM é sabidamente protegida por CAPTCHA. Ela entra na
        # lista de bloqueadas **sem** requisição: pedir para receber 403 e depois marcar
        # bloqueado seria requisitar de graça.
        resultado.bloqueadas.append(SALA_DE_IMPRENSA)
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
                SourceRef(imprensa, "imprensa", 3, "a GM não publica PDF de ficha técnica")
            )
        fontes.append(
            SourceRef(
                SALA_DE_IMPRENSA,
                "sala_de_imprensa",
                1,
                "bloqueada por CAPTCHA; consta como consultada, nunca requisitada",
            )
        )
        return fontes


# ---------------------------------------------------------------------- parser ao vivo
_VERSAO = re.compile(
    r"\b(?P<nome>(?:S10\s+)?(?:High\s+Country|Trail\s+Boss|Cabine\s+Simples|LTZ|Z71|WT)"
    r"(?:\s+(?:AT|MT))?)\b",
    re.IGNORECASE,
)
_PRECO = re.compile(r"R\$\s?(?P<valor>[\d.]{6,12})")


def parse_lineup_html(html: str, *, modelo: str = "", url: str = "") -> list[VersionInfo]:
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
                marca="Chevrolet",
                modelo=modelo,
            )
    return list(vistos.values())
