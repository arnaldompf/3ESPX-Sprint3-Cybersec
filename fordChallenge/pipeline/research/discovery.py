"""Descobre documentos citados na página; links são localizadores, nunca evidência."""

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


def url_key(url: str) -> str:
    """Deduplica navegação equivalente, preservando identificadores de ficha/versão."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        # A descoberta não deve abortar antes de o classificador rejeitar uma URL ruim.
        return "invalid:" + url
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid"}
    ]
    # urlsplit mantém parâmetros de caminho (;versao=...), diferentemente de urlparse.
    # Eles podem selecionar uma ficha e não são rastreamento descartável.
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return urlunsplit(("", host, path, urlencode(query), "")).lstrip("/") or host


def document_links(text: str, base: str, *, limit: int = 8) -> list[tuple[str, str]]:
    """Links técnicos HTML/Markdown, limitados; autoridade e robots são conferidos depois."""
    from bs4 import BeautifulSoup

    if limit <= 0:
        return []
    pairs = []
    if re.search(r"<a\s", text, re.I):
        soup = BeautifulSoup(text, "html.parser")
        pairs.extend(
            (a.get("href", ""), a.get_text(" ", strip=True)) for a in soup.find_all("a", href=True)
        )
    pairs.extend(
        (url, title)
        for title, url in re.findall(r"(?<!!)\[([^\]\n]+)\]\(<?([^\s)>]+)>?(?:\s+[^)]*)?\)", text)
    )
    found = []
    seen = set()
    for href, title in pairs:
        try:
            url = urljoin(base, href)
            parts = urlsplit(url)
        except ValueError:
            continue
        if (
            parts.scheme not in {"https", "http"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            continue
        technical = bool(
            re.search(r"ficha|cat[aá]logo|especifica[çc]|dados t[eé]cnicos", title, re.I)
        )
        if not parts.path.lower().endswith(".pdf") and not technical:
            continue
        if parts.path.lower().endswith((".jpg", ".png", ".svg", ".webp")):
            continue
        key = url_key(url)
        if key in seen:
            continue
        seen.add(key)
        found.append((urlunsplit(parts._replace(fragment="")), title))
        if len(found) >= limit:
            break
    return found
