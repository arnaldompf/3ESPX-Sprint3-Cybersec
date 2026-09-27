"""Guardas de significado antes da normalização; nenhuma equivalência por palpite."""

from pipeline.ontology import normalize


def validate_date(field: str, value, quote: str) -> bool:
    """Exige calendário válido e vínculo literal com preço ou referência FIPE."""
    import re
    from datetime import date

    from pipeline.connectors.fipe import MESES

    if field not in {"preco_data", "fipe_referencia"} or value is None:
        return True
    expected = str(value)
    expected_pattern = r"\d{4}-\d{2}-\d{2}" if field == "preco_data" else r"\d{4}-\d{2}"
    if not re.fullmatch(expected_pattern, expected):
        return False
    try:
        date.fromisoformat(expected if field == "preco_data" else expected + "-01")
    except ValueError:
        return False

    months = "|".join(MESES)
    pattern = re.compile(
        r"(?<![\w/-])(?:"
        r"(?P<iso>\d{4}-\d{2}(?:-\d{2})?)"
        r"|(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})"
        r"|(?P<nmonth>\d{1,2})/(?P<nyear>\d{4})"
        r"|(?:(?P<wday>\d{1,2})(?:º|°)?\s+(?:de\s+)?)?"
        rf"(?P<wmonth>{months})\s+(?:de\s+)?(?P<wyear>\d{{4}})"
        r")(?![\w/-])",
        re.I,
    )
    commercial_label = (
        r"\b(?:mes\s*(?:de\s*)?referencia|referencia(?:\s+fipe)?|tabela\s+fipe)\b"
        if field == "fipe_referencia"
        else r"\b(?:data\s+(?:do\s+)?preco|preco\s+data|"
        r"(?:precos?|ofertas?)\s+(?:sugeridos?\s+)?(?:vigentes?|valid[oa]s?|"
        r"atualizad[oa]s?|em\b|de\s+referencia)|"
        r"vigencia\s+(?:d[oa]s?\s+)?(?:precos?|ofertas?))\b"
    )
    unrelated = (
        r"\b(?:copyright|captur|colet|acess|consultad|publica|published|postad|"
        r"artigo|noticia|ultima\s+atualizacao)|©"
    )
    source = re.sub(r"https?://[^\s)]+", "", quote)
    # Uma cláusula de captura não contamina outra cláusula com vigência explícita.
    # Mantém quebras de linha: rótulo e valor podem estar em linhas consecutivas.
    for clause in re.split(r"[;!?]|[.,](?!\d)", source):
        if re.search(unrelated, normalize(clause)):
            continue
        for match in pattern.finditer(clause):
            if not re.search(commercial_label, normalize(clause[: match.start()])):
                continue
            groups = match.groupdict()
            if groups["iso"]:
                observed = groups["iso"]
            elif groups["year"]:
                observed = f"{groups['year']}-{int(groups['month']):02}-{int(groups['day']):02}"
            elif groups["nyear"]:
                observed = f"{groups['nyear']}-{int(groups['nmonth']):02}"
            else:
                observed = f"{groups['wyear']}-{MESES[groups['wmonth'].lower()]:02}"
                if groups["wday"]:
                    observed += f"-{int(groups['wday']):02}"
            try:
                # Não aproveitar o mês de uma data completa inválida, como 31/02.
                date.fromisoformat(observed if len(observed) == 10 else observed + "-01")
            except ValueError:
                continue
            supported = observed if field == "preco_data" else observed[:7]
            if expected == supported:
                return True
    return False


def validate_number(field: str, value, quote: str, unit: str | None) -> bool:
    """O valor deve resultar de um número do trecho, usando a mesma conversão de unidade."""
    import math
    import re

    from pipeline.eval.compare import comparar_valor
    from pipeline.normalize import NaoNormalizavel, normalizar_campo

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return True
    if not math.isfinite(value):
        return False
    # Parâmetros de links não são números da ficha.
    quote = re.sub(r"https?://[^\s)]+", "", quote)
    if field == "garantia_meses":
        durations = re.findall(r"\b(\d+)\s*(anos?|meses|m[eê]s)\b", quote, re.I)
        if durations:
            return any(
                int(amount) * (12 if period.lower().startswith("ano") else 1) == value
                for amount, period in durations
            )
    units = {
        "torque_nm": [(r"kgf[. ]?m|kgfm", "kgfm"), (r"\bNm\b", "Nm")],
        "potencia_cv": [(r"\bhp\b", "hp"), (r"\bkW\b", "kW"), (r"\bcv\b", "cv")],
    }
    if field.endswith("_mm"):
        units[field] = [(r"\bmm\b", "mm"), (r"\bcm\b", "cm"), (r"\b(?:m|metros?)\b", "m")]
    for pattern, observed_unit in units.get(field, []):
        if re.search(pattern, quote, re.I):
            unit = observed_unit
            break
    tokens = re.findall(r"(?<!\w)\d+(?:[.,]\d+)*", quote)
    if field in {"preco_sugerido_brl", "preco_fipe_brl"}:
        # HTML linearizado pode concatenar o sobrescrito de rodapé ao preço:
        # R$ 499.000² -> R$ 499.0002. A gramática monetária é a do conector.
        tokens = re.findall(r"R\$\s*(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+(?:,\d{2})?)", quote)
    if field in {"airbags_qtd", "numero_marchas", "cilindros", "lugares"}:
        words = {
            "um": 1,
            "dois": 2,
            "tres": 3,
            "quatro": 4,
            "cinco": 5,
            "seis": 6,
            "sete": 7,
            "oito": 8,
            "nove": 9,
            "dez": 10,
        }
        tokens.extend(str(words[word]) for word in normalize(quote).split() if word in words)
    for token in tokens:
        try:
            number = normalizar_campo(field, token, unidade=unit).valor
        except (NaoNormalizavel, ValueError):
            continue
        if comparar_valor(field, value, number).igual:
            return True
    return False


def validate_list(field: str, value, quote: str) -> bool:
    """Cada item precisa estar no trecho, literalmente ou por alias explícito."""
    import re

    from pipeline.ontology import carregar, resolve_value

    if field != "adas_itens" or not isinstance(value, list):
        return True
    text = normalize(quote)
    aliases = carregar().valores.get(field, {})
    for item in value:
        canonical = resolve_value(field, item)
        labels = {normalize(item), normalize(canonical or item)}
        labels.update(alias for alias, target in aliases.items() if target == canonical)
        affirmed = False
        for label in labels:
            for match in re.finditer(r"\b" + re.escape(label) + r"\b", text):
                prefix = re.split(r"[.;\n]|\b(?:mas|porem|contudo)\b", text[: match.start()])[-1]
                suffix = text[match.end() :]
                negated = re.search(
                    r"\b(?:nao (?:tem|possui|oferece|inclui)|sem)\s+[^.;]{0,160}$", prefix
                )
                absent = re.match(
                    r"\s*[:|=-]?\s*(?:nao (?:disponivel|possui|tem|equipado)|ausente)\b", suffix
                )
                if not negated and not absent:
                    affirmed = True
        if not affirmed:
            return False
    return True


def rejection_reason(field: str, quote: str, *, url: str = "") -> str | None:
    import re

    text = normalize(quote)
    if field == "preco_sugerido_brl" and "fixar veiculo" in text:
        return "preco_de_listagem_nao_comprova_preco_sugerido"
    if (
        field == "pneus_tipo"
        and re.search(r"\d{3}[/ ]\d{2}\s*r\d{2}", text)
        and not re.search(r"\b(?:at|mt|ht|all.?terrain|mud.?terrain|highway.?terrain)\b", text)
    ):
        return "medida_do_pneu_nao_comprova_tipo_de_uso"
    if (
        field == "rodas_aro_pol"
        and any(x in text for x in ("sync", "carplay", "multimidia", "touchscreen"))
        and not any(x in text for x in ("aro", "rodas", "pneu"))
    ):
        return "tela_multimidia_nao_e_aro"
    if field == "largura_mm" and "com espelhos" in text:
        return "largura_com_espelhos_nao_e_largura_da_carroceria"
    if field == "capacidade_reboque_kg" and "sem freio" in text:
        return "reboque_sem_freio_requer_contexto_distinto"
    if field == "potencia_cv" and "combinada" in text:
        return "potencia_combinada_nao_e_potencia_do_motor"
    if field == "deslocamento_l" and any(
        x in text for x in ("oleo", "lubrificante", "arrefecimento")
    ):
        return "capacidade_de_fluido_nao_e_cilindrada"
    if field in {
        "rodas_aro_pol",
        "rodas_material",
        "pneus_medida",
        "pneus_tipo",
        "adas_itens",
        "camera_360",
        "paddle_shifters",
    } and (
        any(x in text for x in ("acessorio", "opcional", "vendido separadamente"))
        or "acessorios." in url
    ):
        return "opcional_nao_e_item_de_serie"
    if field == "garantia_meses" and any(
        x in text for x in ("bateria", "pintura", "corrosao", "pecas")
    ):
        return "garantia_de_componente_nao_e_garantia_geral"
    if field == "preco_sugerido_brl" and any(
        x in text for x in ("entrada", "parcelas", "taxista", "pcd", "cnpj")
    ):
        return "oferta_condicionada_nao_e_preco_sugerido"
    return None
