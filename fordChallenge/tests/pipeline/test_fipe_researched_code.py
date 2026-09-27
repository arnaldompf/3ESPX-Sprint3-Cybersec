import json
from pathlib import Path

from pipeline.connectors.fipe import parse_resposta_api
from pipeline.research import gaps, planner, run
from pipeline.research.events import Trilha


def test_codigo_da_resposta_compativel_e_pesquisavel_com_prova():
    text = json.dumps(
        {
            "Valor": "R$ 100.000,00",
            "Marca": "Volkswagen",
            "Modelo": "AMAROK Extreme CD 3.0 V6 TDI 4x4 Dies.",
            "AnoModelo": 2026,
            "Combustivel": "Diesel",
            "CodigoFipe": "005525-7",
            "MesReferencia": "setembro de 2026",
            "TipoVeiculo": 1,
        }
    )
    query = parse_resposta_api(text, url="https://parallelum.com.br/fipe/api/v1/carros/test")
    assert query.quote_codigo == '"CodigoFipe": "005525-7"'
    fonte = run.Fonte(
        url=query.url,
        texto=text,
        tier=2,
        tipo="fipe",
        baixada=True,
        motivo="resposta original",
        consulta="teste",
    )
    leitor = run.Leitor(
        planner.Alvo("Volkswagen", "Amarok", "V6 Extreme", 2026),
        gaps.Orcamento(chamadas_llm=0),
        Trilha(),
    )
    spec, _ = leitor.ler([], campos=["codigo_fipe"], fontes=[fonte])
    assert spec.identificacao["codigo_fipe"].value == "005525-7"
    assert spec.identificacao["codigo_fipe"].evidences[0].quote in text


def test_offline_revalidation_reads_existing_reference_page_and_never_calls_api(monkeypatch):
    import hashlib

    from pipeline.identity import VehicleTarget
    from pipeline.publication import choose
    from pipeline.schema import Status
    from scripts.audit_quality import check_proof

    page = (
        Path(__file__).parents[1]
        / "fixtures/snapshots/vw_amarok_v6_extreme_2026/2026-09-01T00-00-00Z/fipe_amarok/page.md"
    )
    text = page.read_text(encoding="utf-8")
    url = text.split("**URL:** ")[1].splitlines()[0]
    from pipeline.connectors.fipe import parse_pagina_fipe

    assert parse_pagina_fipe(text, url=url).source_text == text

    def no_network(*args, **kwargs):
        raise AssertionError("offline FIPE must not call API or catalog")

    monkeypatch.setattr("pipeline.connectors.fipe.price", no_network)
    monkeypatch.setattr("pipeline.run._codigo_fipe_da_versao", no_network)
    fonte = run.Fonte(
        url=url,
        texto=text,
        tier=2,
        tipo="fipe",
        baixada=True,
        motivo="captura original",
        consulta="offline",
    )
    leitor = run.Leitor(
        planner.Alvo("Volkswagen", "Amarok", "V6 Extreme", 2026),
        gaps.Orcamento(chamadas_llm=0),
        Trilha(),
        fipe_somente_snapshots=True,
    )
    spec, _ = leitor.ler([], campos=["codigo_fipe"], fontes=[fonte])
    cell = spec.identificacao["codigo_fipe"]
    target = VehicleTarget("Volkswagen", "Amarok", "V6 Extreme", 2026)
    published = choose(
        "codigo_fipe",
        [cell],
        target=target,
        require_source_proof=True,
        source_texts={e.evidence_id: text for e in cell.evidences},
    )
    assert published.value == "005506-9" and published.status == Status.VERIFICADO
    assert published.evidences[0].quote == "Código FIPE:\t005506-9"
    result = check_proof(
        "codigo_fipe",
        {
            **published.evidences[0].model_dump(),
            "value": published.value,
            "text_path": str(page),
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        },
        target,
    )
    assert result["valid"]
    wrong = run.Leitor(
        planner.Alvo("Volkswagen", "Amarok", "V6 Extreme", 2027),
        gaps.Orcamento(chamadas_llm=0),
        Trilha(),
        fipe_somente_snapshots=True,
    )
    missing, _ = wrong.ler([], campos=["codigo_fipe"], fontes=[fonte])
    assert missing.identificacao["codigo_fipe"].value is None
