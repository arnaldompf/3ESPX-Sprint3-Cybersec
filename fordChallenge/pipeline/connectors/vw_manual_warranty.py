"""Garantia geral Amarok: índice oficial com MY → PDF original → cláusula contratual.

O vínculo é restrito a garantia_meses. A advertência de versões/equipamentos do
manual permanece válida para todos os campos técnicos. Nenhuma chamada de rede.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
from pdfminer.pdfexceptions import PDFException

from pipeline.extract.run import Candidato
from pipeline.identity import VehicleTarget
from pipeline.ontology import normalize

FORMAT = "VW_MANUAL_WARRANTY_CHAIN_V1"
INDEX_URL = "https://www.vw.com.br/pt/servicos-e-acessorios/servicos-e-produtos/manuais-e-garantia/manuais.html"
FIELD = "garantia_meses"
# Páginas físicas do PDF. O número impresso é um a menos, exceto a capa.
PAGES = (1, 7, 260, 261)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _official(url: str, *, index: bool = False) -> bool:
    try:
        p = urlsplit(url)
        return bool(
            p.scheme == "https"
            and p.hostname in {"vw.com.br", "www.vw.com.br"}
            and p.port in {None, 443}
            and p.username is None
            and p.password is None
            and not p.query
            and not p.fragment
            and (
                p.path == urlsplit(INDEX_URL).path
                if index
                else p.path.startswith(
                    "/idhub/content/dam/onehub_pkw/importers/br/literatura-de-bordo/manual-amarok/"
                )
                and p.path.lower().endswith(".pdf")
            )
        )
    except (TypeError, ValueError):
        return False


@lru_cache(maxsize=2)
def _extract_pages(raw: bytes) -> tuple[str, ...]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        return tuple(pdf.pages[number - 1].extract_text() or "" for number in PAGES)


def build(
    *,
    index_html: str,
    index_url: str,
    index_captured_at: str,
    pdf_path: str | Path,
    pdf_url: str,
    pdf_captured_at: str,
) -> str:
    """Guarda os originais com fronteiras por comprimento; nunca costura citações."""
    path = Path(pdf_path).resolve(strict=True)
    raw = path.read_bytes()
    pages = _extract_pages(raw)
    parts = (index_html, *pages)
    metadata = {
        "index_url": index_url,
        "index_captured_at": index_captured_at,
        "pdf_url": pdf_url,
        "pdf_captured_at": pdf_captured_at,
        "pdf_path": str(path),
        "pdf_sha256": _sha(raw),
        "pages": PAGES,
        "lengths": [len(part) for part in parts],
        "sha256_texts": [_sha(part.encode("utf-8")) for part in parts],
    }
    return FORMAT + "\n" + json.dumps(metadata, ensure_ascii=False) + "\n" + "\n".join(parts)


def is_chain(text: str) -> bool:
    return isinstance(text, str) and text.startswith(FORMAT + "\n")


@dataclass(frozen=True)
class Proof:
    metadata: dict
    index_html: str
    pages: tuple[str, ...]


def read(text: str) -> Proof | None:
    """Reconfere SHA256 completo e a extração contra o PDF ainda preservado."""
    if not is_chain(text):
        return None
    try:
        _, header, body = text.split("\n", 2)
        metadata = json.loads(header)
        if tuple(metadata["pages"]) != PAGES or len(metadata["lengths"]) != len(PAGES) + 1:
            return None
        if len(metadata["sha256_texts"]) != len(PAGES) + 1:
            return None
        parts, pos = [], 0
        for i, length in enumerate(metadata["lengths"]):
            if not isinstance(length, int) or length < 1:
                return None
            part = body[pos : pos + length]
            if len(part) != length or _sha(part.encode()) != metadata["sha256_texts"][i]:
                return None
            parts.append(part)
            pos += length
            if i < len(PAGES):
                if body[pos : pos + 1] != "\n":
                    return None
                pos += 1
        if pos != len(body):
            return None
        raw = Path(metadata["pdf_path"]).read_bytes()
        if _sha(raw) != metadata["pdf_sha256"] or tuple(parts[1:]) != _extract_pages(raw):
            return None
        return Proof(metadata, parts[0], tuple(parts[1:]))
    except (OSError, ValueError, TypeError, KeyError, IndexError, PDFException):
        return None


def _flat(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", normalize(re.sub(r"-\s*\n", "", text))).split())


def _matches(text: str, url: str, target: VehicleTarget):
    proof = read(text)
    if (
        proof is None
        or normalize(target.marca) not in {"volkswagen", "vw"}
        or normalize(target.modelo) != "amarok"
        or target.mercado != "BR"
        or not target.ano_modelo
        or not _official(url)
        or url != proof.metadata["pdf_url"]
        or not _official(proof.metadata["index_url"], index=True)
    ):
        return None, []
    soup = BeautifulSoup(proof.index_html, "html.parser")
    expected = f"Amarok {target.ano_modelo} - Manual de instruções"
    links = [
        a
        for a in soup.find_all("a", href=True)
        if a.get("title") == expected
        and expected in a.get_text(" ", strip=True)
        and urljoin(proof.metadata["index_url"], a["href"]) == url
    ]
    # O MY vem do rótulo do índice; o caminho deve concordar, não criá-lo sozinho.
    if not links or f"/my{str(target.ano_modelo)[-2:]}/" not in unquote(url).lower():
        return None, []
    cover, scope, warranty, terms = proof.pages
    if (
        "Amarok" not in cover
        or "Brazil, pt_BR" not in cover
        or "este manual de instrucoes versao digital e valido" not in _flat(scope)[:400]
        or "para todas as versoes e modelos disponiveis" not in _flat(scope)[:400]
        or "garantia volkswagen cobertura da garantia" not in _flat(warranty)
        or "volkswagen do brasil" not in _flat(warranty)
        or "ii prazo de validade" not in _flat(terms)
        or "em caso de uso comercial" not in _flat(terms)
    ):
        return None, []
    pattern = re.compile(
        r"A garantia tem duração de (?P<years>[1-9]\d?) anos? "
        r"\(já incluído o prazo\s+de garantia legal\) para o veículo completo"
    )
    matches = list(pattern.finditer(warranty))
    # Prazo geral e comercial devem concordar com o prazo geral destacado.
    if len(matches) != 1:
        return None, []
    years = matches[0].group("years")
    folded_terms = _flat(terms)
    if (
        f"{years} anos apos o termo inicial" not in folded_terms
        or f"em caso de uso comercial {years} anos ou" not in folded_terms
    ):
        return None, []
    return proof, matches


def candidatos(texto: str, url: str, target: VehicleTarget, source_id="", captured_at=""):
    proof, matches = _matches(texto, url, target)
    if proof is None:
        return []
    commercial = re.search(r"uso comercial,\s*\d+ anos ou (?P<km>[\d.]+) km", proof.pages[3])
    if commercial is None:
        return []
    return [
        Candidato(
            campo=FIELD,
            valor=int(match.group("years")) * 12,
            unidade="meses",
            valor_bruto=match.group("years") + " anos",
            quote=match.group(0),
            origem="fastpath:vw_garantia_manual_com_elo_oficial_my",
            source_id=source_id,
            source_text=texto,
            url=url,
            tier=1,
            captured_at=captured_at or proof.metadata["pdf_captured_at"],
            pagina=259,
            notas=(
                "Garantia geral do veículo; anos × 12. Uso comercial: "
                + commercial.group("km")
                + " km ou o prazo, o que ocorrer primeiro. Condicionada às revisões na rede VW; "
                "peças, desgaste e acessórios têm exceções nas páginas 259–261. "
                "Índice oficial vincula o MY ao PDF; escopo contratual para todas as versões."
            ),
        )
        for match in matches
    ]


def supports(field: str, target: VehicleTarget, text: str, url: str, quote: str, value=None):
    if field != FIELD or not quote:
        return False
    return any(
        candidate.quote == quote and (value is None or candidate.valor == value)
        for candidate in candidatos(text, url, target)
    )
