"""HTML → o `page.md` que as fixtures usam. Sem reescrever o conteúdo.

O formato é o mesmo que `scripts/build_fixtures.py` já espera:

    # <título>

    **URL:** <url>

    ---

    <texto, uma linha por bloco>

A regra que importa: **o texto que sobra não é reescrito**. O `evidence_quote` do
grounding é procurado dentro deste arquivo, e qualquer normalização aqui (colapsar
espaço dentro da frase, trocar aspas, reordenar) faria a citação da fonte deixar de ser
encontrável no texto salvo da fonte — que é exatamente a regra inviolável do projeto.
O que se faz é tirar `<script>`/`<style>`, virar tag de bloco em quebra de linha e
decodificar entidade HTML.
"""

from __future__ import annotations

import html as _html
import re

#: Tags cujo fim é fim de linha. Sem isto, "Potência 250 cvTorque 600 Nm" vira uma
#: palavra só e nenhum regex de campo acha o número.
_BLOCOS = (
    "p|div|br|li|tr|h[1-6]|section|article|header|footer|nav|ul|ol|table|thead|tbody"
    "|dl|dt|dd|figure|figcaption|blockquote|option|label|span"
)
_ABRE_OU_FECHA_BLOCO = re.compile(rf"</?(?:{_BLOCOS})\b[^>]*>", re.IGNORECASE)
_SCRIPT_OU_STYLE = re.compile(
    r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_COMENTARIO = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_TITULO = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_LINHAS_VAZIAS = re.compile(r"\n{3,}")


def titulo_de(html: str) -> str:
    achado = _TITULO.search(html)
    return " ".join(_html.unescape(achado.group(1)).split()) if achado else ""


def texto_de(html: str) -> str:
    """Só o texto visível, uma linha por bloco, com as entidades decodificadas."""
    sem_codigo = _SCRIPT_OU_STYLE.sub(" ", _COMENTARIO.sub(" ", html))
    com_quebras = _ABRE_OU_FECHA_BLOCO.sub("\n", sem_codigo)
    sem_tags = _TAG.sub("", com_quebras)
    texto = _html.unescape(sem_tags)
    linhas = [" ".join(linha.split()) for linha in texto.splitlines()]
    return _LINHAS_VAZIAS.sub("\n\n", "\n".join(linhas)).strip()


def page_md(html: str, *, url: str, titulo: str = "") -> str:
    """O arquivo completo, no formato das fixtures."""
    cabecalho = titulo or titulo_de(html) or url
    return f"# {cabecalho}\n\n**URL:** {url}\n\n---\n\n{texto_de(html)}\n"


__all__ = ["page_md", "texto_de", "titulo_de"]
