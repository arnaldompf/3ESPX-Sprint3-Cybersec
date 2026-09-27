"""Conector Toyota Brasil.

Linha vigente: `toyota.com.br/modelos/<modelo>` (a Hilux mora em `hilux-cabine-dupla`).
Fonte principal de atributos: o PDF "lista de equipamentos" do ano-modelo, que é onde a
Toyota publica rpm — coisa que Ford, VW e GM não publicam (lição 3 do gabarito).

Este é o conector do **caso negativo**: a GR-Sport não está na linha 2026, e o resolvedor
tem de dizer isso com as alternativas na mão, em vez de extrair a ficha de um carro que
saiu de linha.
"""

from __future__ import annotations

import re

from pipeline.connectors import _http
from pipeline.connectors.base import Connector, ResultadoLinha, SourceRef, VersionInfo

BASE = "https://www.toyota.com.br"

#: A Hilux Cabine Dupla tem página própria; o nome do modelo não vira slug direto.
SLUG_POR_MODELO: dict[str, str] = {
    "hilux": "hilux-cabine-dupla",
    "hilux cabine dupla": "hilux-cabine-dupla",
    "corolla cross": "corolla-cross",
    "sw4": "sw4",
}

#: PDFs de lista de equipamentos conhecidos, por modelo.
LISTAS_PDF: dict[str, str] = {
    "hilux": "https://media.toyota.com.br/d400f124-b3ac-4d73-a885-5d6828812f11.pdf",
}


class ToyotaConnector(Connector):
    marca = "Toyota"
    dominio = "toyota.com.br"
    modelos = ("Hilux", "Hilux Cabine Dupla", "SW4", "Corolla Cross")
    tier = 1

    def url_do_modelo(self, modelo: str) -> str:
        alvo = SLUG_POR_MODELO.get(modelo.strip().lower(), modelo.strip().lower().replace(" ", "-"))
        return f"{BASE}/modelos/{alvo}"

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
            resultado.nota = "nenhuma versão reconhecida no bloco 'Conheça as versões'"
        return resultado

    def sources(self, versao: VersionInfo) -> list[SourceRef]:
        fontes: list[SourceRef] = []
        modelo = (versao.modelo or "hilux").strip().lower()
        pdf = LISTAS_PDF.get(modelo)
        if pdf:
            fontes.append(SourceRef(pdf, "pdf_oficial", 1, "lista de equipamentos do ano-modelo"))
        if versao.url:
            fontes.append(SourceRef(versao.url, "pagina_oficial", 1))
        return fontes


# ---------------------------------------------------------------------- parser ao vivo
#: A Toyota lista as versões em bloco depois de "Conheça as versões".
_BLOCO = re.compile(r"Conhe[çc]a as vers[õo]es(?P<corpo>.{0,1200})", re.IGNORECASE | re.DOTALL)
_VERSAO = re.compile(
    r"\b(?P<nome>(?:STD(?:\s+Power\s+Pack)?|SRX\s+Plus|SRX|SRV|SR|GR-?Sport|Diamond|Platinum)"
    r"(?:\s+(?:AT|MT|MAN\.?|Diesel|Flex|4x4|4x2))*)\b",
    re.IGNORECASE,
)


def parse_lineup_html(
    html: str, *, modelo: str = "", url: str = "", ano_modelo: int | None = None
) -> list[VersionInfo]:
    """Extrai as versões do bloco "Conheça as versões" da página do modelo.

    Só olha dentro do bloco: a palavra "SRX" aparece dezenas de vezes em notas de rodapé
    ("Disponível nas versões SRX e SRX Plus"), e varrer a página inteira produziria
    duplicatas e falsos positivos.
    """
    texto = re.sub(r"<[^>]+>", " ", html)
    texto = re.sub(r"[ \t]+", " ", texto)
    bloco = _BLOCO.search(texto)
    escopo = bloco.group("corpo") if bloco else texto[:1200]
    vistos: list[VersionInfo] = []
    nomes: set[str] = set()
    for achado in _VERSAO.finditer(escopo):
        nome = " ".join(achado.group("nome").split())
        chave = nome.lower()
        if chave in nomes:
            continue
        nomes.add(chave)
        vistos.append(
            VersionInfo(
                nome_exato=nome,
                ano_modelo=ano_modelo,
                url=url,
                marca="Toyota",
                modelo=modelo,
            )
        )
    return vistos
