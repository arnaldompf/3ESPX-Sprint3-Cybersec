"""Aplicabilidade de evidência. Similaridade nunca supera contradição explícita."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlparse

from pipeline.ontology import normalize

_VERSION_MODIFIERS = frozenset(
    {
        "plus",
        "extreme",
        "highline",
        "comfortline",
        "raptor",
        "xl",
        "xls",
        "xlt",
        "sr",
        "srv",
        "srx",
        "limited",
        "black",
        "storm",
        "sport",
        "tremor",
        "wildtrak",
    }
)


class Applicability(StrEnum):
    COMPATIBLE = "compativel"
    INCOMPATIBLE = "incompativel"
    INSUFFICIENT = "insuficiente"


@dataclass(frozen=True)
class VehicleTarget:
    marca: str
    modelo: str
    versao: str
    ano_modelo: int | None
    mercado: str = "BR"
    version_id: str = ""
    motorizacao: str = ""
    transmissao: str = ""
    tracao: str = ""
    configuracao: str = ""
    pacote_opcional: str = ""
    evidencias: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentityAssessment:
    status: Applicability
    reasons: tuple[str, ...] = ()
    observed: dict = field(default_factory=dict)


def claim_rejection(target: VehicleTarget, quote: str, *, source_text: str = "") -> str | None:
    """Contradição no trecho prevalece sobre a identidade geral da página."""
    trims = (
        "limited plus",
        "limited",
        "extreme",
        "comfortline",
        "highline",
        "raptor",
        "high country",
        "trail boss",
        "srx plus",
        "srx",
        "srv",
        "xls",
        "xlt",
        "xl",
        "tremor",
        "wildtrak",
        "black",
    )

    def mentioned(text: str) -> set[str]:
        found = set()
        for trim in trims:
            if re.search(r"\b" + re.escape(trim) + r"\b", text):
                found.add(trim)
                text = re.sub(r"\b" + re.escape(trim) + r"\b", " ", text)
        return found

    wanted = mentioned(normalize(target.versao))
    observed = mentioned(normalize(quote))
    if wanted and observed and observed != wanted:
        return "trecho_de_outra_versao_ou_multiversao_ambigua"
    # Uma citação curta pode omitir o cabeçalho que a limita ao pacote opcional.
    # Só atribuímos uma seção quando existe título curto com versão e ano/motor.
    # Uma ocorrência também no bloco padrão comprova um item comum aos dois.
    if source_text and quote:
        from pipeline.ground import sem_acento

        headings = []
        optional_level = None
        before_optional = None
        offset = 0
        lines = [sem_acento(line) for line in source_text.splitlines() if line.strip()]
        source_normalized = " ".join(lines)
        quote_normalized = sem_acento(quote)
        for line in lines:
            normalized = normalize(line).strip("#* |-\t\r\n")
            trim = mentioned(normalized)
            markdown = re.match(r"^\s*(#{1,6})\s+", line)
            level = len(markdown[1]) if markdown else None
            optional = re.fullmatch(r"(?:kit|pacote)s? (?:de )?opciona(?:l|is)[: ]*", normalized)
            if optional_level and level and level <= optional_level and not optional:
                headings.append((offset, before_optional))
                optional_level = None
            if optional:
                if optional_level is None and level:
                    before_optional = headings[-1][1] if headings else None
                    optional_level = level
                reason = None if target.pacote_opcional else "trecho_no_bloco_de_pacote_opcional"
                headings.append((offset, reason))
            elif (
                len(normalized) < 160
                and trim
                and (re.search(r"\b20\d{2}\b", normalized) or _engines(normalized))
            ):
                reason = None
                if wanted and trim != wanted:
                    reason = "trecho_no_bloco_de_outra_versao"
                elif not target.pacote_opcional and re.search(
                    r"\b(?:kit|pacote) opciona[li]", normalized
                ):
                    reason = "trecho_no_bloco_de_pacote_opcional"
                if optional_level and not target.pacote_opcional:
                    reason = reason or "trecho_no_bloco_de_pacote_opcional"
                headings.append((offset, reason))
            offset += len(line) + 1
        contexts = []
        start = 0
        while (
            quote_normalized and (position := source_normalized.find(quote_normalized, start)) >= 0
        ):
            previous = [(offset, reason) for offset, reason in headings if offset <= position]
            if previous:
                contexts.append(previous[-1][1])
            start = position + len(quote_normalized)
        if contexts and all(contexts):
            return contexts[0]
    return None


def _engines(text: str) -> set[str]:
    return {
        x.replace(",", ".")
        for x in re.findall(
            r"(?<!\d)([1-8][.,]\d)(?=\s*(?:l\b|v[468]\b|diesel|turbo|tdi|duratorq|ecoboost))",
            text.lower(),
        )
    }


def _year_context(text: str, target: VehicleTarget) -> tuple[list[str], list[str]]:
    """Somente texto visível, antes de recomendações; nunca anos em URLs/imagens."""
    visible = re.sub(r"!\[[^\]]*\]\((?:\\.|[^)])*\)", "", text)
    visible = re.sub(r"\[([^\[\]]*)\]\((?:\\.|[^)])*\)", r"\1", visible)
    visible = re.sub(r"https?://[^\s<>]+", "", visible)
    lines = []
    for raw in visible.splitlines():
        line = normalize(raw.replace("\t", "|")).strip("|#* ")
        if re.match(
            r"^(?:veja tambem|ultimas noticias|comparativos relacionados|"
            r"(?:carros|veiculos|modelos) (?:relacionados|recomendados|semelhantes)|"
            r"recomendacoes|recomendados|voce tambem)\b",
            line,
        ):
            break
        if line:
            lines.append(line)
    brands = [normalize(target.marca)]
    if target.marca.lower() == "volkswagen":
        brands.append("vw")
    prefix = r"(?:" + "|".join(re.escape(b) for b in brands) + r")\s+"
    prefix += re.escape(normalize(target.modelo)) + r"\b"
    titles = [
        line
        for line in lines
        if len(line) < 180
        and re.match(r"(?:nov[oa]\s+)?" + prefix, line)
        and len([cell for cell in line.split("|") if cell.strip()]) == 1
    ]
    if titles:
        lines = lines[lines.index(titles[0]) :]
    return lines, titles


def _explicit_years(lines: list[str], titles: list[str]) -> set[int]:
    years = set()
    for title in titles:
        content = re.split(r"\b(?:captura|publicado|copyright)\b", title)[0]
        years.update(int(y) for y in re.findall(r"\b(20\d{2})\b", content))
    label = r"(?:ano(?:[ -]modelo)?|modelo|my)"
    for index, line in enumerate(lines):
        # O valor visível de uma célula individual, não múltiplas colunas de anos.
        cells = [cell.strip("* :") for cell in line.split("|")]
        for pos, cell in enumerate(cells[:-1]):
            if re.fullmatch(label, cell) and re.fullmatch(r"20\d{2}", cells[pos + 1]):
                following = [value for value in cells[pos + 1 :] if value]
                if len(following) == 1:
                    years.add(int(cells[pos + 1]))
        pair = re.fullmatch(label + r"\s*[:=-]\s*(20\d{2})", line)
        if pair:
            years.add(int(pair[1]))
        if re.fullmatch(label, line) and index + 1 < len(lines):
            value = lines[index + 1].strip("| ")
            if re.fullmatch(r"20\d{2}", value):
                years.add(int(value))
    return years


def authoritative_model_years(text: str, target: VehicleTarget) -> set[int]:
    """Anos explícitos de uma ficha individual, para revalidar evidência histórica.

    Sem título individual inequívoco, retorna vazio. Isso evita aplicar o cabeçalho
    global de um documento multiversão a uma coluna já recortada e comprovada.
    """
    lines, titles = _year_context(text, target)
    wanted = set(normalize(target.versao).split()) & _VERSION_MODIFIERS
    if len(titles) != 1 or not wanted:
        return set()
    observed = set(titles[0].replace("|", " ").split()) & _VERSION_MODIFIERS
    if observed != wanted:
        return set()
    # Cabeçalhos de grade com várias versões continuam dependentes do recorte.
    for line in lines:
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        if len(cells) > 2 and (
            re.match(r"^vers(?:ao|oes)\b", line)
            or sum(bool(set(cell.split()) & _VERSION_MODIFIERS) for cell in cells) > 1
            or sum(bool(re.fullmatch(r"20\d{2}", cell)) for cell in cells) > 1
        ):
            return set()
    return _explicit_years(lines, titles)


def assess(target: VehicleTarget, text: str, *, url: str = "") -> IdentityAssessment:
    """Confirma identidade no conteúdo; URL ajuda a rejeitar, nunca prova ano-modelo.

    Escopo multiversão deve ser recortado antes desta chamada. Ano de captura e copyright
    não contam. Informação ausente permanece pendente em vez de ganhar compatibilidade.
    """
    body = normalize(text)
    path = normalize(urlparse(url).path.replace("-", " "))
    host = (urlparse(url).hostname or "").lower()
    reasons: list[str] = []
    missing: list[str] = []
    # Uma ficha individual tem título próprio. Menus e recomendações de outras
    # versões no rodapé não podem tornar esse título compatível.
    year_lines, titles = _year_context(text, target)
    primary = titles[0] if titles else ""
    modifiers = _VERSION_MODIFIERS
    target_modifiers = set(normalize(target.versao).split()) & modifiers
    source_modifiers = set(primary.replace("|", " ").split()) & modifiers
    if source_modifiers and target_modifiers and source_modifiers != target_modifiers:
        reasons.append("versao_ou_pacote_incompativel")
    for name, value in [("marca", target.marca), ("modelo", target.modelo)]:
        aliases = [normalize(value)]
        if value.lower() == "volkswagen":
            aliases.append("vw")
        if not any(re.search(r"\b" + re.escape(a) + r"\b", body) for a in aliases):
            missing.append(name)
    # Marcação de mercado no documento ou segmento explícito da URL.
    foreign = bool(
        re.search(
            r"\b(?:mercado|market)\s*(?:de|:)?\s*"
            r"(?:united states|usa|australia|south africa|argentina)\b",
            body[:3000],
        )
    )
    foreign = foreign or host.endswith((".com.au", ".co.za", ".com.ar"))
    foreign = foreign or ((host == "ford.com" or host == "www.ford.com") and "/configure/" in url)
    if target.mercado == "BR" and foreign:
        reasons.append("mercado_incompativel")
    elif not (
        re.search(r"\bbrasil\b|\bbrazil\b|\bmercado brasileiro\b", body)
        or host.endswith(".com.br")
        or "/br/" in url
        or "/pt/br/" in url
    ):
        missing.append("mercado")
    engines = _engines(text)
    expected = _engines(target.motorizacao or target.versao)
    if engines and expected and not expected.intersection(engines):
        reasons.append("motor_incompativel")
    elif expected and not engines:
        missing.append("motor")
    transmission_target = normalize(target.transmissao or target.versao)
    expects_auto = bool(re.search(r"\b(?:at|aut|automatic[ao])\b", transmission_target))
    expects_manual = bool(re.search(r"\b(?:mt|manual)\b", transmission_target))
    observed_transmission = re.findall(
        r"\b(?:cambio|transmissao)\s*[:|=-]?\s*(automatic[ao]|manual)\b", body
    )
    if (expects_auto and "manual" in observed_transmission) or (
        expects_manual and any(t.startswith("automatic") for t in observed_transmission)
    ):
        reasons.append("transmissao_incompativel")
    traction_target = normalize(target.tracao or target.versao)
    expects_four = bool(re.search(r"\b(?:4wd|4x4|awd|4motion|integral)\b", traction_target))
    expects_two = bool(re.search(r"\b(?:4x2|2wd)\b", traction_target))
    observed_traction = re.findall(
        r"\btracao\s*[:|=-]?\s*(4x2|2wd|4x4|4wd|awd|integral|traseira|dianteira)\b", body
    )
    if (
        expects_four
        and any(t in {"4x2", "2wd", "traseira", "dianteira"} for t in observed_traction)
    ) or (expects_two and any(t in {"4x4", "4wd", "awd", "integral"} for t in observed_traction)):
        reasons.append("tracao_incompativel")
    # Somente anos ligados a modelo/linha/MY ou à identificação do veículo.
    explicit_years = _explicit_years(year_lines, titles)
    years = {
        int(y)
        for y in re.findall(
            r"\b(?:ano[ -]?modelo|modelo|linha|my)\s*[: -]?\s*(20\d{2})\b",
            "\n".join(year_lines),
        )
    }
    for line in year_lines:
        n = re.split(r"\b(?:captura|publicado|copyright)\b", normalize(line))[0]
        trim_title = (
            len(n) < 240
            and target_modifiers
            and target_modifiers <= set(n.split())
            and bool(expected & _engines(n))
        )
        if normalize(target.modelo) in n or trim_title:
            years.update(int(y) for y in re.findall(r"\b(20\d{2})\b", n))
    if explicit_years:
        years = explicit_years
    if target.ano_modelo and years and target.ano_modelo not in years:
        reasons.append("ano_modelo_incompativel")
    elif target.ano_modelo and len(years) > 1:
        reasons.append("ano_modelo_conflitante")
    elif target.ano_modelo and target.ano_modelo not in years:
        missing.append("ano_modelo")
    tokens = set(re.findall(r"[a-z]+", normalize(target.versao))) - {
        "v",
        "at",
        "aut",
        "automatico",
        "diesel",
        "turbo",
        "wd",
        "l",
        "bi",
        "cabine",
        "dupla",
    }
    if tokens and not tokens.issubset(set(re.findall(r"[a-z]+", body))):
        missing.append("versao")
    if "acessorios" in host or re.search(
        r"\b(?:catalogo de acessorios|acessorios originais)\b", body[:2000]
    ):
        reasons.append("acessorio_nao_e_equipamento_de_serie")
    # Um documento explicitamente de outro modelo não serve nem para campos compartilhados.
    if "modelo" in missing and path and normalize(target.modelo) not in path:
        reasons.append("modelo_nao_comprovado")
    state = (
        Applicability.INCOMPATIBLE
        if reasons
        else Applicability.INSUFFICIENT
        if missing
        else Applicability.COMPATIBLE
    )
    return IdentityAssessment(
        state,
        tuple(reasons or ["identidade_ausente:" + m for m in missing]),
        {
            "anos_modelo": sorted(years),
            "anos_modelo_autoritativos": sorted(authoritative_model_years(text, target)),
            "motores": sorted(engines),
        },
    )
