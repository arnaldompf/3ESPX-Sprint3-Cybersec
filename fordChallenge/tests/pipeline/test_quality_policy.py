"""Regressões P0: documentos reais e critérios de publicação do plano de qualidade."""

import json
from pathlib import Path

from pipeline.eval.compare import comparar_valor
from pipeline.parse.pdf import Tabela
from pipeline.parse.version_slicer import recortar_tabela
from pipeline.research.gaps import medir
from pipeline.schema import Status, empty_spec
from pipeline.status import Observacao, decidir


def test_adas_extra_incorreto_e_penalizado():
    assert not comparar_valor("adas_itens", ["ACC"], ["ACC", "piloto autônomo"]).igual


def test_mencao_negada_de_adas_nao_prova_equipamento():
    from pipeline.semantics import validate_list

    assert not validate_list("adas_itens", ["ACC"], "Esta versão não possui ACC.")
    assert not validate_list("adas_itens", ["ACC"], "ACC: não disponível.")
    assert not validate_list("adas_itens", ["AEB"], "Não possui ACC e AEB.")
    assert not validate_list("adas_itens", ["ACC"], "ACC: não possui.")
    assert validate_list("adas_itens", ["ACC"], "ACC de série; sem intervenção no pedal.")


def test_medida_nao_vira_tipo_de_pneu_e_metros_preservam_normalizacao():
    from pipeline.semantics import rejection_reason, validate_number

    assert rejection_reason("pneus_tipo", "Dianteiros | 255/50 R20")
    assert not rejection_reason("pneus_tipo", "Pneus 255/50 R20 all-terrain")
    assert validate_number("comprimento_mm", 5350, "5,35 metros de comprimento", "mm")
    assert not validate_number("comprimento_mm", 5350, "1,95 metros de largura", "mm")


def test_preco_de_outra_versao_nao_contamina_decisao_anterior():
    from pipeline.identity import VehicleTarget, claim_rejection
    from pipeline.publication import choose
    from pipeline.schema import Evidence, SpecField

    target = VehicleTarget("Volkswagen", "Amarok", "V6 Extreme", 2026)
    good = SpecField.verificado(
        379990,
        Evidence(
            evidence_id="good",
            source_url="https://example.com.br",
            tier=3,
            quote="Volkswagen Amarok Extreme 2026 R$ 379.990",
            captured_at="2026-09-14",
        ),
    )
    bad = SpecField.verificado(
        278176,
        Evidence(
            evidence_id="bad",
            source_url="https://example.com.br",
            tier=3,
            quote="Fixar veículo Volkswagen Amarok 2026 Comfortline R$ 278.176",
            captured_at="2026-09-14",
        ),
    )
    assert claim_rejection(target, bad.evidences[0].quote)
    merged = choose("preco_sugerido_brl", [good, bad], target=target)
    assert merged.value == 379990
    assert merged.status == Status.VERIFICADO
    assert [e.evidence_id for e in merged.evidences] == ["good"]


def test_coluna_vazia_sem_geometria_nao_herda():
    table = Tabela(1, [["VERSÃO", "Base", "Extreme"], ["Pneus", "265/65 R17", ""]])
    assert not recortar_tabela(table, "Extreme").celulas


def test_ausencia_sem_citacao_nao_resolve():
    d = decidir(
        "camera_360",
        [
            Observacao(
                "camera_360", None, "não disponível", source_id="s", tier=1, ausencia_declarada=True
            )
        ],
        textos={"s": "outra coisa"},
    )
    assert d.status != Status.NAO_DISPONIVEL


def test_divergencia_nao_conta_como_preenchimento():
    spec = empty_spec(job_id="test")
    decision = decidir(
        "potencia_cv",
        [
            Observacao("potencia_cv", 200, "200 cv", source_id="a", tier=1),
            Observacao("potencia_cv", 250, "250 cv", source_id="b", tier=1),
        ],
        textos={"a": "200 cv", "b": "250 cv"},
    )
    spec.set("motorizacao.potencia_cv", decision.spec)
    assert medir(spec).com_valor == 0


def test_baseline_preserva_falhas_reais():
    data = json.loads(Path("tests/fixtures/quality/baseline.json").read_text(encoding="utf-8"))
    rows = data["baseline"]["human-live"]
    assert any(r["field"] == "deslocamento_l" and r["value_json"] == 3.2 for r in rows)
    assert any(r["field"] == "rodas_aro_pol" and r["value_json"] == 15 for r in rows)


def test_tabela_fipe_de_portal_nao_vira_fonte_de_especificacoes():
    from pipeline.research.classify import classificar
    from pipeline.research.run import _tipo_concreto

    url = "https://www.webmotors.com.br/tabela-fipe/carros/ford/ranger/2026/limited"
    assert _tipo_concreto(classificar(url, marca="Ford", modelo="Ranger")) == "fipe"
