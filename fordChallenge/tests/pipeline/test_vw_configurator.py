import copy
import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from pipeline.connectors import vw_configurator as vw
from pipeline.fetch.http import Resultado
from pipeline.identity import VehicleTarget
from pipeline.publication import choose
from pipeline.reconcile import reconciliar
from pipeline.schema import Status
from pipeline.semantics import rejection_reason, validate_list, validate_number

TARGET = VehicleTarget("Volkswagen", "Amarok", "V6 Extreme", 2026)
PAGE = "https://www.vw.com.br/pt/carros.html/__app/amarok.app"
KEY = {
    "carlineId": "30348",
    "salesgroupId": "38596",
    "trimId": "V6 Extreme",
    "modelId": "AGDD8A$GYI3YI3",
    "modelYear": "2026",
    "modelVersion": "0",
}


def bootstrap(key=None, extra_nodes=()):
    key = key or KEY
    node = {
        "type": "trim",
        "nodeId": "/amarok/v6-extreme",
        "category": "private",
        "data": {
            "name": "V6 Extreme",
            "carlineName": "Amarok",
            "referenceModel": {
                "key": key,
                "modelName": (
                    "Amarok Extreme 258 cv 3.0 V6 TDI turbo diesel Automática de "
                    f"8 velocidades Diesel Modelo {key['modelYear']}"
                ),
            },
        },
    }
    state = {
        "carros_featureAppSection": {
            "modelOverviewResult": {
                "status": "loaded",
                "dataVersion": "abc-def",
                "url": "https://v1-566-0.mofa.feature-app.io/bff/model-overview?countryCode=BR&language=pt&currency=BRL&dataVersion=abc-def&oneapiKey=public-client-value",
                "modelOverview": {"nodes": [node, *extra_nodes]},
            }
        }
    }
    encoded = quote(json.dumps({k: json.dumps(v) for k, v in state.items()}))
    return (
        "<title>Carros Volkswagen Brasil</title>"
        f'<script type="x-feature-hub/serialized-states">{encoded}</script>'
    )


def equipment(names=None):
    names = names or [
        "6 Airbags (2 frontais, 2 laterais dianteiros e 2 de cortina)",
        "Motor 3.0 V6 Turbo diesel com potência de 258 cv e torque de 59,1 kgfm",
        'Transmissão automática de 8 velocidades com tração "4Motion" permanente',
        'Rodas de liga leve 20"',
        "Pneus 255/50 R20",
        "ESC- Controle eletrônico de estabilidade /ASR- Controle de tração "
        "e EDS- Bloqueio eletrônico do diferencial",
        "Alerta de colisão com pedestres e ciclistas, saída de faixa e limite de velocidade",
        "Sensores de estacionamento dianteiros e traseiros com câmera de ré",
        'Volante com comandos para troca de marchas "shift-paddles"',
    ]
    return json.dumps(
        {
            "dataVersion": "7-abc-def",
            "payload": {
                "standardEquipment": [
                    {"features": [{"code": f"M{i}", "name": name} for i, name in enumerate(names)]}
                ]
            },
        },
        ensure_ascii=False,
    )


def collect(html=None, response=None):
    urls = []

    def fetch(url, **kw):
        urls.append(url)
        return Resultado(
            url,
            "ok",
            texto=(html or bootstrap()) if len(urls) == 1 else (response or equipment()),
            http_status=200,
            url_final=url,
        )

    return vw.collect(TARGET, fetcher=fetch), urls


def test_collects_exact_model_and_every_quote_is_in_auditable_snapshot():
    result, urls = collect()
    assert result is not None
    query = parse_qs(urlsplit(urls[1]).query)
    assert all(query[k] == [v] for k, v in KEY.items())
    assert query["countryCode"] == ["BR"]
    assert "public-client-value" not in result.texto
    candidates = vw.candidatos(result.texto, result.url, TARGET)
    values = {c.campo: c.valor for c in candidates}
    assert values["airbags_qtd"] == 6
    assert values["potencia_cv"] == 258
    assert values["numero_marchas"] == 8
    assert values["paddle_shifters"] is True
    assert values["bloqueio_diferencial"] is True
    assert "camera_360" not in values
    assert "pneus_tipo" not in values
    assert "adas_itens" not in values
    for c in candidates:
        assert c.quote in result.texto
        assert validate_number(c.campo, c.valor, c.quote, c.unidade)
        assert validate_list(c.campo, c.valor, c.quote)
        assert rejection_reason(c.campo, c.quote, url=c.url) is None
    lock = next(c for c in candidates if c.campo == "bloqueio_diferencial")
    assert "eletrônico" in lock.notas and "mecânico" in lock.notas


@pytest.mark.parametrize(
    "target",
    [
        replace(TARGET, ano_modelo=2025),
        replace(TARGET, versao="V6 Highline"),
        replace(TARGET, versao="V6 Extreme Barretos 70 Anos"),
        replace(TARGET, mercado="AR"),
        replace(TARGET, marca="Ford"),
    ],
)
def test_rejects_wrong_identity_without_equipment_request(target):
    urls = []

    def fetch(url, **kw):
        urls.append(url)
        return Resultado(url, "ok", texto=bootstrap(), http_status=200, url_final=url)

    assert vw.collect(target, fetcher=fetch) is None
    assert len(urls) <= 1


def test_model_key_and_description_year_must_agree():
    html = bootstrap().replace("2026", "2025", 1)
    result, urls = collect(html=html)
    assert result is None
    assert len(urls) == 1


def test_duplicate_matching_variants_are_ambiguous():
    h = bootstrap()
    selection = vw.select_model(h, PAGE, TARGET)
    assert selection is not None
    extra = {"type": "trim", "category": "private", "data": copy.deepcopy(selection.model)}
    extra["data"]["referenceModel"]["key"]["modelId"] += "OTHER"
    result, urls = collect(html=bootstrap(extra_nodes=[extra]))
    assert result is None
    assert len(urls) == 1


def test_changed_backend_data_version_is_not_silently_accepted():
    result, _ = collect(response=equipment().replace("7-abc-def", "7-other"))
    assert result is None


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/model-overview",
        "http://127.0.0.1/bff/model-overview",
        "https://user:password@v1-566-0.mofa.feature-app.io/bff/model-overview",
        "https://[broken/bff/model-overview",
    ],
)
def test_hydration_cannot_redirect_connector_to_arbitrary_service(url):
    html = bootstrap().replace(
        quote("https://v1-566-0.mofa.feature-app.io/bff/model-overview"), quote(url)
    )
    result, urls = collect(html=html)
    assert result is None
    assert len(urls) == 1


def test_tampered_response_or_request_breaks_provenance_chain():
    result, _ = collect()
    assert result is not None
    record = json.loads(result.texto)
    record["response"]["payload"]["standardEquipment"][0]["features"][0]["name"] = "99 Airbags"
    assert vw.candidatos(json.dumps(record, ensure_ascii=False), PAGE, TARGET) == []
    record = json.loads(result.texto)
    record["request"]["key"]["modelYear"] = "2025"
    assert vw.candidatos(json.dumps(record, ensure_ascii=False), PAGE, TARGET) == []


def test_negated_optional_features_are_not_promoted_and_absence_is_not_inferred():
    result, _ = collect(
        response=equipment(
            ["Sem câmera 360", "Rodas de liga leve 22 polegadas opcionais", "Pneus 255/50 R20"]
        )
    )
    assert result is not None
    candidates = vw.candidatos(result.texto, result.url, TARGET)
    assert all(c.campo not in {"camera_360", "pneus_tipo", "adas_itens"} for c in candidates)
    assert all(c.valor != 22 for c in candidates)


def test_blocked_page_does_not_trigger_bypass():
    urls = []

    def fetch(url, **kw):
        urls.append(url)
        return Resultado(url, "blocked", http_status=403)

    assert vw.collect(TARGET, fetcher=fetch) is None
    assert urls == [PAGE]


@pytest.mark.parametrize(
    "page",
    [
        "https://user:password@www.vw.com.br/pt/carros.html",
        "https://www.vw.com.br:invalid/pt/carros.html",
        "https://[broken",
    ],
)
def test_page_credentials_or_malformed_authority_never_issue_network_call(page):
    def unexpected_fetch(*args, **kwargs):
        pytest.fail("invalid URL must not reach fetcher")

    assert vw.collect(TARGET, page_url=page, fetcher=unexpected_fetch) is None


def _published(result):
    candidates = vw.candidatos(result.texto, result.url, TARGET)
    fields = sorted({c.campo for c in candidates} | {"adas_itens"})
    texts = {c.source_id: result.texto for c in candidates}
    reconciled = reconciliar(candidates, textos=texts, campos=fields, target=TARGET)
    return {
        key: choose(key, [decision.spec], target=TARGET)
        for key, decision in reconciled.decisoes.items()
    }


def test_short_complete_adas_declaration_survives_reconciliation_and_publication():
    result, _ = collect(
        response=equipment(["ADAS: alerta de colisão; alerta de saída de faixa; câmera de ré"])
    )
    published = _published(result)["adas_itens"]
    assert published.status == Status.VERIFICADO
    assert set(published.value) == {"alerta_de_colisao", "alerta_de_faixa", "camera_de_re"}
    assert all(validate_list("adas_itens", published.value, e.quote) for e in published.evidences)


def test_unrecognized_adas_member_does_not_publish_recognized_subset():
    result, _ = collect(
        response=equipment(
            ["ADAS: alerta de colisão; correção quântica não catalogada; câmera de ré"]
        )
    )
    assert _published(result)["adas_itens"].status == Status.NAO_ENCONTRADO


def test_real_equipment_response_preserves_claims_through_reconciliation_and_publication():
    path = Path(__file__).parents[1] / "fixtures/vw_configurator/amarok_my26_equipment.json"
    result, _ = collect(
        response=path.read_text(encoding="utf-8").replace(
            "7-759475876B2F41D2924350BF878FF673-A913CA7844CA614EC9021563FE736223-DCE1C7E2C46CB34C02D54E2007B90BD7",
            "7-abc-def",
        )
    )
    published = _published(result)
    assert published["adas_itens"].status == Status.NAO_ENCONTRADO
    assert published["bloqueio_diferencial"].value is True
    assert published["airbags_qtd"].value == 6
    assert all(
        cell.status == Status.VERIFICADO for key, cell in published.items() if key != "adas_itens"
    )


@pytest.mark.parametrize("body", ["null", "[]", '"text"', '{"format": "vw-configurator-chain-v1"}'])
def test_malformed_record_is_rejected(body):
    assert vw.candidatos(body, PAGE, TARGET) == []


def test_long_feature_is_not_sent_to_a_truncating_evidence_contract():
    result, _ = collect(response=equipment(["6 Airbags " + "nota " * 100]))
    assert vw.candidatos(result.texto, result.url, TARGET) == []
