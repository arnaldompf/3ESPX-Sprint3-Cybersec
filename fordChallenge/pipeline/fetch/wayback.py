"""Wayback Machine como fonte oficial **arquivada** — o último recurso da coleta.

Quando a borda da montadora recusa tanto o cliente HTTP quanto o navegador real (a Ford
respondeu `403 Akamai` às duas na madrugada de 10/09/2026), ainda existe uma cópia da
página oficial que **não** exige burlar nada: a captura do Internet Archive. Ela é a
mesma página, com a data em que foi tirada, e é assim que ela entra aqui:

* o snapshot continua **tier 1** — a fonte é a montadora, o arquivo é só o meio;
* `arquivado=True` e `captured_at` = a data da **captura**, não a de hoje. Um valor de
  abril de 2026 não pode se passar por valor de hoje;
* a URL original fica em `url_final`, e a URL do arquivo em `url_arquivo`. As duas viajam
  no `meta.json`, porque quem audita precisa das duas.

O que este módulo **não** faz: fingir que a captura é atual, e escolher uma captura mais
antiga do que a mais recente disponível. A CDX é consultada com `limit=-N` (as N últimas)
e o resultado sai ordenado da mais nova para a mais velha.

`docs/13` §3 já previa o Wayback como fonte na onda 2 (WP-36, "time machine"). Aqui ele
entra pelo lado mais simples: uma captura, a mais recente, quando não há outro caminho.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from pipeline.fetch import http

CDX_URL = "https://web.archive.org/cdx/search/cdx"
#: `id_` devolve o conteúdo **como foi capturado**, sem a barra de navegação do arquivo.
PREFIXO_CONTEUDO = "https://web.archive.org/web/{timestamp}id_/{url}"


@dataclass(frozen=True)
class Captura:
    """Uma linha da CDX: uma captura de uma URL, com data e tipo."""

    timestamp: str
    url_original: str
    mimetype: str
    status: str
    digest: str = ""

    @property
    def data_iso(self) -> str:
        """`20260423042159` → `2026-04-23`. É esta data que vira `captured_at`."""
        return datetime.strptime(self.timestamp[:8], "%Y%m%d").strftime("%Y-%m-%d")

    @property
    def url_arquivo(self) -> str:
        return PREFIXO_CONTEUDO.format(timestamp=self.timestamp, url=self.url_original)


def _chave_cdx(url: str) -> str:
    """A CDX indexa sem esquema. `https://www.ford.com.br/x/` → `ford.com.br/x/`."""
    sem_esquema = url.split("://", 1)[-1]
    return sem_esquema.removeprefix("www.")


def capturas(url: str, *, limite: int = 8, so_ok: bool = True) -> list[Captura]:
    """As `limite` capturas mais recentes de uma URL, da mais nova para a mais velha.

    Lista vazia quando não há captura nenhuma — e isso é um resultado, não um erro:
    significa que nem o arquivo tem a página, e a coleta fica `pendente_coleta`.
    """
    consulta = (
        f"{CDX_URL}?url={_chave_cdx(url)}&output=json&collapse=digest&limit=-{max(int(limite), 1)}"
    )
    if so_ok:
        consulta += "&filter=statuscode:200"
    resultado = http.fetch(consulta, usar_cache=False)
    if not resultado.ok or not resultado.texto.strip():
        return []
    try:
        linhas = json.loads(resultado.texto)
    except ValueError:
        return []
    if not linhas or len(linhas) < 2:
        return []
    cabecalho = linhas[0]
    achados = [dict(zip(cabecalho, linha, strict=False)) for linha in linhas[1:]]
    capturas_ = [
        Captura(
            timestamp=str(d.get("timestamp", "")),
            url_original=str(d.get("original", url)),
            mimetype=str(d.get("mimetype", "")),
            status=str(d.get("statuscode", "")),
            digest=str(d.get("digest", "")),
        )
        for d in achados
        if str(d.get("timestamp", "")).isdigit()
    ]
    return sorted(capturas_, key=lambda c: c.timestamp, reverse=True)


def captura_mais_recente(url: str) -> Captura | None:
    """A captura mais nova, ou `None` quando o arquivo não tem a página."""
    achadas = capturas(url, limite=8)
    return achadas[0] if achadas else None


@dataclass
class ResultadoArquivo:
    """O conteúdo de uma captura, com a data da captura junto."""

    url_original: str
    url_arquivo: str
    captured_at: str
    status: str
    texto: str = ""
    conteudo: bytes = b""
    motivo: str = ""

    @property
    def ok(self) -> bool:
        return self.status == http.STATUS_OK


def buscar_arquivada(url: str) -> ResultadoArquivo:
    """Baixa a captura mais recente da URL. Nunca levanta: devolve status e motivo."""
    captura = captura_mais_recente(url)
    if captura is None:
        return ResultadoArquivo(
            url_original=url,
            url_arquivo="",
            captured_at="",
            status=http.STATUS_ERRO,
            motivo=f"o Internet Archive não tem captura de {url}",
        )
    resposta = http.fetch(captura.url_arquivo, usar_cache=False)
    if not resposta.ok:
        return ResultadoArquivo(
            url_original=captura.url_original,
            url_arquivo=captura.url_arquivo,
            captured_at=captura.data_iso,
            status=resposta.status,
            motivo=f"captura de {captura.data_iso} não pôde ser lida: {resposta.motivo}",
        )
    return ResultadoArquivo(
        url_original=captura.url_original,
        url_arquivo=captura.url_arquivo,
        captured_at=captura.data_iso,
        status=http.STATUS_OK,
        texto=resposta.texto,
        conteudo=resposta.conteudo,
        motivo=f"captura arquivada de {captura.data_iso} (Internet Archive)",
    )


__all__ = [
    "CDX_URL",
    "Captura",
    "ResultadoArquivo",
    "buscar_arquivada",
    "captura_mais_recente",
    "capturas",
]
