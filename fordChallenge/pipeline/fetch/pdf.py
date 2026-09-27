"""Download de PDF com sha256 e extração de texto sem binário externo.

Duas razões para o PDF ter caminho próprio: ele é a **melhor** fonte do projeto (só a
Toyota publica rpm, e só no PDF de lista de equipamentos), e o texto dele sai em layout
de tabela, que o grounding precisa preservar (`docs/09`, e o teste que trava
`Potência (cv/rpm) 204 / 3.400`).

O `sha256` do arquivo bruto entra no `meta.json`: é o que permite dizer "este é o mesmo
PDF que eu li em tal data", e é o que sustenta a evidência quando a montadora troca a
ficha sem mudar a URL.

A extração usa `pypdf` (dependência base) e, se o extra `pdf` estiver instalado,
`pdfplumber` para as páginas em que o layout importa. Nenhum binário externo —
`pdftotext` existe nesta máquina, mas depender dele quebraria o CI (DECISOES_NOITE D-09).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.fetch import http


@dataclass
class PdfBaixado:
    url: str
    status: str
    conteudo: bytes = b""
    sha256: str = ""
    http_status: int | None = None
    motivo: str = ""
    de_replay: bool = False
    texto_de_replay: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {http.STATUS_OK, http.STATUS_CACHE, http.STATUS_REPLAY}


def baixar(url: str, *, timeout: float = 60.0) -> PdfBaixado:
    """Baixa um PDF. Em replay, devolve o **texto** já convertido do snapshot.

    Em `REPLAY_MODE=1` não há o binário do PDF salvo (as fixtures guardam `doc.md`), então
    o resultado traz `texto_de_replay` em vez de `conteudo`. Quem chama usa
    :func:`texto_do_pdf` e não precisa saber a diferença.
    """
    if http.modo_replay():
        from pipeline.snapshots import snapshot_de_url

        snap = snapshot_de_url(url)
        return PdfBaixado(
            url=url,
            status=http.STATUS_REPLAY,
            sha256=snap.meta.get("sha256", ""),
            de_replay=True,
            texto_de_replay=snap.texto,
            motivo=f"replay do snapshot {snap.source_id}",
        )

    resultado = http.fetch(url, timeout=timeout, usar_cache=False)
    if not resultado.ok:
        return PdfBaixado(
            url=url,
            status=resultado.status,
            http_status=resultado.http_status,
            motivo=resultado.motivo,
        )
    dados = resultado.conteudo
    if not dados.startswith(b"%PDF"):
        return PdfBaixado(
            url=url,
            status=http.STATUS_ERRO,
            http_status=resultado.http_status,
            motivo="a resposta não é um PDF (sem assinatura %PDF)",
        )
    return PdfBaixado(
        url=url,
        status=http.STATUS_OK,
        conteudo=dados,
        sha256=hashlib.sha256(dados).hexdigest(),
        http_status=resultado.http_status,
        motivo=resultado.motivo,
    )


@dataclass
class TextoDePdf:
    texto: str
    paginas: list[str] = field(default_factory=list)
    motor: str = ""

    @property
    def n_paginas(self) -> int:
        return len(self.paginas)


def extrair_texto(dados: bytes, *, preservar_layout: bool = True) -> TextoDePdf:
    """Texto de um PDF em memória, uma entrada por página.

    Com `preservar_layout` e o extra `pdf` instalado, usa `pdfplumber`, que mantém a
    posição das colunas — é o que faz a linha `Potência (cv/rpm) 204 / 3.400` aparecer
    inteira em vez de partida em "204/" e "3.400" em pontos distantes do texto.
    """
    if preservar_layout:
        try:
            import io

            import pdfplumber

            paginas: list[str] = []
            with pdfplumber.open(io.BytesIO(dados)) as documento:
                for pagina in documento.pages:
                    paginas.append(pagina.extract_text(layout=True) or "")
            return TextoDePdf("\n\n".join(paginas), paginas, "pdfplumber")
        except ImportError:
            pass  # cai para pypdf, que é dependência base

    import io

    from pypdf import PdfReader

    leitor = PdfReader(io.BytesIO(dados))
    paginas = [(p.extract_text() or "") for p in leitor.pages]
    return TextoDePdf("\n\n".join(paginas), paginas, "pypdf")


def texto_do_pdf(url: str, **kw) -> tuple[str, PdfBaixado]:
    """`(texto, registro do download)` — o caminho que o pipeline usa."""
    baixado = baixar(url, **kw)
    if baixado.de_replay:
        return baixado.texto_de_replay, baixado
    if not baixado.ok:
        return "", baixado
    return extrair_texto(baixado.conteudo).texto, baixado


def salvar(dados: bytes, destino: Path) -> str:
    """Grava o PDF bruto e devolve o sha256."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(dados)
    return hashlib.sha256(dados).hexdigest()
