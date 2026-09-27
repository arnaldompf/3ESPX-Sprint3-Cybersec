"""Equipamento de série VW Brasil, ligado à chave exata do modelo no configurador.

O HTML público contém estado SSR com modelo, ano e chave. O mesmo serviço público
usado pelo botão «Itens de série» recebe essa chave. A resposta não ecoa o modelId:
guardamos explicitamente essa limitação, a requisição e os hashes dos dois documentos.
Não existem valores de veículos cadastrados neste módulo, nem inferência por ausência.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from pipeline.extract.fastpath import extrair
from pipeline.extract.run import Candidato
from pipeline.fetch import http
from pipeline.identity import Applicability, VehicleTarget, assess
from pipeline.ontology import carregar, normalize
from pipeline.semantics import rejection_reason, validate_list, validate_number

PAGE = "https://www.vw.com.br/pt/carros.html/__app/amarok.app"
FORMAT = "vw-configurator-chain-v1"
KEY_FIELDS = ("carlineId", "salesgroupId", "trimId", "modelId", "modelYear", "modelVersion")
ALLOWED_FIELDS = {
    "motor_descricao",
    "cilindros",
    "deslocamento_l",
    "combustivel",
    "aspiracao",
    "potencia_cv",
    "torque_nm",
    "tipo",
    "numero_marchas",
    "tipo_tracao",
    "paddle_shifters",
    "bloqueio_diferencial",
    "farois_tipo",
    "farois_neblina",
    "rodas_aro_pol",
    "rodas_material",
    "pneus_medida",
    "pneus_tipo",
    "airbags_qtd",
    "camera_360",
    "adas_nome_comercial",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _official_page(url: str) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and parts.hostname in {"www.vw.com.br", "vw.com.br"}
            and parts.port in {None, 443}
            and parts.username is None
            and parts.password is None
        )
    except (TypeError, ValueError):
        return False


def _service(url: str) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and bool(re.fullmatch(r"v\d+-\d+-\d+\.mofa\.feature-app\.io", parts.hostname or ""))
            and parts.port in {None, 443}
            and parts.username is None
            and parts.password is None
            and parts.path == "/bff/model-overview"
            and parse_qs(parts.query).get("countryCode") == ["BR"]
        )
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class ModelSelection:
    model: dict
    key: dict
    title: str
    page_url: str
    page_sha256: str
    data_version: str
    overview_url: str = field(repr=False)


@dataclass(frozen=True)
class Collection:
    texto: str
    url: str
    captured_at: str
    sha256: str


def _matches(model: dict, target: VehicleTarget) -> bool:
    if normalize(target.marca) not in {"volkswagen", "vw"} or target.mercado != "BR":
        return False
    if not isinstance(model, dict):
        return False
    reference = model.get("referenceModel", {})
    if not isinstance(reference, dict):
        return False
    key = reference.get("key", {})
    if not isinstance(key, dict):
        return False
    if any(not isinstance(key.get(k), str) or not key[k] for k in KEY_FIELDS):
        return False
    if key["modelYear"] != str(target.ano_modelo):
        return False
    name = reference.get("modelName", "")
    if not isinstance(name, str) or not re.search(rf"\bModelo\s+{target.ano_modelo}\b", name, re.I):
        return False
    if normalize(model.get("carlineName", "")) != normalize(target.modelo):
        return False
    return assess(target, f"Volkswagen Brasil\n{name}", url=PAGE).status == Applicability.COMPATIBLE


def select_model(html: str, url: str, target: VehicleTarget) -> ModelSelection | None:
    """Seleciona uma única configuração do SSR, incluindo o ano declarado no nome."""
    if (
        normalize(target.marca) not in {"volkswagen", "vw"}
        or target.mercado != "BR"
        or not target.ano_modelo
        or not _official_page(url)
    ):
        return None
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if "volkswagen" not in normalize(title):
        return None
    matches = []
    for script in soup.find_all("script", attrs={"type": "x-feature-hub/serialized-states"}):
        try:
            states = json.loads(unquote(script.get_text()))
        except (ValueError, TypeError):
            continue
        if not isinstance(states, dict):
            continue
        for state in states.values():
            try:
                state = json.loads(state) if isinstance(state, str) else state
            except ValueError:
                continue
            if not isinstance(state, dict):
                continue
            overview = state.get("modelOverviewResult", {})
            if not isinstance(overview, dict):
                continue
            service_url = overview.get("url", "")
            if overview.get("status") != "loaded" or not _service(service_url):
                continue
            for node in _walk(overview.get("modelOverview", {})):
                model = node.get("data")
                if (
                    node.get("type") != "trim"
                    or node.get("category") != "private"
                    or not isinstance(model, dict)
                ):
                    continue
                if _matches(model, target):
                    matches.append(
                        ModelSelection(
                            model=model,
                            key=model["referenceModel"]["key"],
                            title=title,
                            page_url=url,
                            page_sha256=_sha(html),
                            data_version=str(overview.get("dataVersion", "")),
                            overview_url=service_url,
                        )
                    )
    return matches[0] if len(matches) == 1 else None


def _request(selection: ModelSelection) -> str:
    parts = urlsplit(selection.overview_url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    query.update(selection.key)
    query.update(category="private", ssr="false")
    return urlunsplit((parts.scheme, parts.netloc, "/bff/model-details", urlencode(query), ""))


def _same_version(expected: str, received: str) -> bool:
    # O serviço prefixa a versão do contrato (por exemplo «7-») no hash composto.
    return bool(expected) and (received == expected or re.sub(r"^\d+-", "", received) == expected)


def collect(target: VehicleTarget, *, page_url: str = PAGE, fetcher=None) -> Collection | None:
    """Duas leituras com o fetcher comum (robots, limite, cache e replay). Sem LLM."""
    if normalize(target.marca) not in {"volkswagen", "vw"} or target.mercado != "BR":
        return None
    if not _official_page(page_url):
        return None
    fetcher = fetcher or http.fetch
    page = fetcher(page_url, timeout=25, tentativas=1)
    if not page.ok or (page.url_final and not _official_page(page.url_final)):
        return None
    selection = select_model(page.texto, page.url_final or page_url, target)
    if selection is None:
        return None
    request_url = _request(selection)
    result = fetcher(request_url, timeout=25, tentativas=1)
    if not result.ok or (result.url_final and result.url_final != request_url):
        return None
    try:
        response = json.loads(result.texto)
    except (ValueError, TypeError):
        return None
    if not isinstance(response, dict) or not _same_version(
        selection.data_version, str(response.get("dataVersion", ""))
    ):
        return None
    retrieved_at = datetime.now(UTC).isoformat()
    captured_at = result.captured_at or retrieved_at
    parts = urlsplit(request_url)
    # Não publicar tokens técnicos presentes no bootstrap público da VW.
    public_query = {**selection.key, "countryCode": "BR", "category": "private"}
    public_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(public_query), ""))
    # O modelo é cópia literal do objeto SSR. A resposta original inteira é preservada;
    # as aspas JSON das citações também são literais no snapshot serializado.
    record = {
        "format": FORMAT,
        "captured_at": captured_at,
        "retrieved_at": retrieved_at,
        "discovery": {
            "page_url": selection.page_url,
            "page_sha256": selection.page_sha256,
            "page_title": selection.title,
            "data_version": selection.data_version,
        },
        "selected_model": selection.model,
        "request": {
            "url": public_url,
            "key": selection.key,
            "countryCode": "BR",
            "binding": "HTTPS request with exact SSR model key; response does not echo model ID",
        },
        "response": response,
        "response_sha256": _sha(result.texto),
        "response_raw": result.texto,
    }
    text = _json(record)
    return Collection(text, page_url, captured_at, _sha(text))


def candidatos(textpayload: str, url: str, target: VehicleTarget) -> list[Candidato]:
    """Extrai apenas equipamento explícito após revalidar a cadeia modelo→requisição."""
    if not _official_page(url):
        return []
    try:
        record = json.loads(textpayload)
        if not isinstance(record, dict) or not isinstance(record.get("captured_at"), str):
            return []
        request = record["request"]
        model = record["selected_model"]
        raw = record["response_raw"]
        response = record["response"]
        if (
            record["format"] != FORMAT
            or request["countryCode"] != "BR"
            or record["discovery"]["page_url"] != url
            or not _matches(model, target)
            or request["key"] != model["referenceModel"]["key"]
            or _sha(raw) != record["response_sha256"]
            or json.loads(raw) != response
            or not _same_version(record["discovery"]["data_version"], response["dataVersion"])
        ):
            return []
        parts = urlsplit(request["url"])
        request_params = parse_qs(parts.query)
        if parts.path != "/bff/model-details" or not _service(
            urlunsplit((parts.scheme, parts.netloc, "/bff/model-overview", parts.query, ""))
        ):
            return []
        if any(request_params.get(k) != [v] for k, v in request["key"].items()):
            return []
        groups = response["payload"]["standardEquipment"]
    except (ValueError, TypeError, KeyError, AttributeError):
        return []
    if not isinstance(groups, list):
        return []
    found = []

    def add(campo, valor, quote, unidade=None, notas=""):
        if (
            quote not in textpayload
            or len(quote) > 300
            or rejection_reason(campo, quote, url=url)
            or not validate_number(campo, valor, quote, unidade)
        ):
            return
        found.append(
            Candidato(
                campo,
                valor,
                quote,
                "fastpath:vw_configurator",
                unidade=unidade,
                source_id="vw-configurator-" + _sha(textpayload)[:20],
                source_text=textpayload,
                url=url,
                tier=1,
                captured_at=record["captured_at"],
                notas=notas,
            )
        )

    for group in groups:
        if not isinstance(group, dict):
            continue
        features = group.get("features", [])
        if not isinstance(features, list):
            continue
        for feature in features:
            if not isinstance(feature, dict) or not isinstance(feature.get("name"), str):
                continue
            name = feature["name"]
            normalized = normalize(name)
            if re.search(
                r"\b(?:opciona[il]s?|acessorios?|sem|nao possui|nao disponivel)\b", normalized
            ):
                continue
            quote = json.dumps(name, ensure_ascii=False)
            if quote not in textpayload:
                continue
            for item in extrair(name, campos=ALLOWED_FIELDS).achados:
                add(item.campo, item.valor, quote, item.unidade)
            if re.search(r"\bshift[ -]?paddles?\b", normalized):
                add("paddle_shifters", True, quote)
            if re.search(r"\bbloqueio eletronico do diferencial\b", normalized):
                add(
                    "bloqueio_diferencial",
                    True,
                    quote,
                    notas=(
                        "Bloqueio eletrônico EDS; esta evidência não afirma "
                        "bloqueio mecânico selecionável."
                    ),
                )
            # O contrato Evidence limita a citação a 300 caracteres e o núcleo não
            # une provas de membros diferentes de uma lista. Portanto, não montamos
            # ADAS pela união silenciosa de equipamentos distantes: seria truncado
            # e/ou esconderia funções cuja redação a ontologia ainda não reconhece.
            declared = re.fullmatch(r"(?:adas|assistentes de conducao)\s*:\s*(.+)", normalized)
            if declared and len(quote) <= 300:
                labels = [part.strip() for part in declared[1].split(";")]
                aliases = carregar().valores.get("adas_itens", {})
                if labels and all(label in aliases for label in labels):
                    values = sorted({aliases[label] for label in labels})
                    if validate_list("adas_itens", values, quote):
                        add("adas_itens", values, quote)
    return found
