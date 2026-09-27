"""Cobertura contratual Ford Brasil por modelo e ano-modelo explícitos.

A página é multiveículo. Sua aplicabilidade é limitada a ``garantia_meses``:
nunca comprova motor, equipamento, versão ou período de um componente.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from pipeline.extract.run import Candidato
from pipeline.identity import VehicleTarget
from pipeline.ontology import normalize

URL = "https://www.ford.com.br/servico-ao-cliente/garantia/"
_FIELD = "garantia_meses"


def _source_text(text: str) -> str:
    if not re.search(r"<(?:h[1-6]|p|div|html)\b", text, re.I):
        return text
    soup = BeautifulSoup(text, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return soup.get_text("\n", strip=True)


def _matches(text: str, url: str, target: VehicleTarget) -> list[re.Match[str]]:
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        return []
    if (
        parsed.scheme != "https"
        or host not in {"ford.com.br", "www.ford.com.br"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path.rstrip("/") != "/servico-ao-cliente/garantia"
        or normalize(target.marca) != "ford"
        or target.mercado != "BR"
        or target.ano_modelo is None
    ):
        return []

    model = target.modelo.strip()
    if normalize(model) == "ranger" and "raptor" in normalize(target.versao).split():
        model += " Raptor"
    # Cabeçalho literal e rótulo contratual adjacentes: nem copyright, nem o ano
    # de outra seção, nem "Bateria: 1 ano" podem completar o campo.
    line_decoration = r"[ \t#*]*"
    gap = r"[ \t\r\n#*]*"
    pattern = re.compile(
        r"^"
        + line_decoration
        + re.escape(model)
        + r"[ \t]+"
        + str(target.ano_modelo)
        + line_decoration
        + r"\r?\n"
        + gap
        + r"Prazo[ \t]+de[ \t]+Cobertura"
        + gap
        + r"\(Garantia[ \t]+Contratual\)"
        + gap
        + r"(?P<duration>(?P<years>[1-9]\d?)[ \t]+anos?)\b",
        re.I | re.M,
    )
    return list(pattern.finditer(text))


def candidatos(
    texto: str,
    url: str,
    target: VehicleTarget,
    source_id: str = "",
    captured_at: str = "",
) -> list[Candidato]:
    """Retorna somente durações lidas, sem rede, IA ou valor de garantia fixo."""
    source = _source_text(texto)
    results: list[Candidato] = []
    seen: set[str] = set()
    for match in _matches(source, url, target):
        quote = match.group(0).strip()
        if quote in seen:
            continue
        seen.add(quote)
        results.append(
            Candidato(
                campo=_FIELD,
                valor=int(match.group("years")) * 12,
                unidade="meses",
                valor_bruto=match.group("duration"),
                quote=quote,
                origem="fastpath:ford_garantia_contratual_por_modelo_ano",
                source_id=source_id,
                source_text=source,
                url=url,
                tier=1,
                captured_at=captured_at,
                notas="Aplicabilidade restrita à garantia contratual do modelo/ano; anos × 12.",
            )
        )
    return results


def supports(field: str, target: VehicleTarget, text: str, url: str, quote: str) -> bool:
    """Confere prova e escopo da exceção de identidade, para auditoria/publicação."""
    if field != _FIELD or not quote:
        return False
    source = _source_text(text)
    if quote not in source:
        return False
    return any(match.group(0).strip() == quote for match in _matches(source, url, target))
