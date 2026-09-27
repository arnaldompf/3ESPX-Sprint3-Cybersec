"""WP-11 — status e confiança: onde as regras de honestidade decidem.

Os cinco critérios de aceite da spec, mais as garantias que sustentam a promessa do
produto: grounding **antes** do agrupamento, divergência com todos os valores, e os dois
vazios como estados distintos.
"""

from __future__ import annotations

import pytest

from pipeline.ground import zerar_falhas
from pipeline.schema import Status
from pipeline.status import (
    BONUS_POR_CONCORDANTE,
    CONFIANCA_MAXIMA_TIER3,
    Observacao,
    decidir,
    decidir_todos,
)


def obs(campo, valor, quote, *, tier=1, source_id="s1", url="https://oficial", **kw):
    return Observacao(
        campo=campo, valor=valor, quote=quote, tier=tier, source_id=source_id, url=url, **kw
    )


@pytest.fixture(autouse=True)
def _zera():
    zerar_falhas()


# ------------------------------------------------------------ critérios de aceite
def test_t1_e_t3_concordantes_dao_verificado_com_095():
    """Critério: T1 583 Nm e T3 "59,4 kgfm" (582,5 Nm) → verificado, confiança 0,95."""
    d = decidir(
        "torque_nm",
        [
            obs("torque_nm", 583, "Torque 583Nm", tier=1, source_id="ford"),
            obs("torque_nm", 583, "59,4 kgfm", tier=3, source_id="revista", raw_value="59,4 kgfm"),
        ],
        textos={"ford": "Torque 583Nm no eixo", "revista": "torque de 59,4 kgfm medido"},
    )
    assert d.status is Status.VERIFICADO
    assert d.spec.confidence == 0.95
    assert len(d.spec.evidences) == 2
    assert d.spec.conflicts == []


def test_divergencia_expoe_todos_os_valores():
    """Critério: T1 "Off-Road" × slide "Baja" → `divergente` com os dois em `conflicts`."""
    d = decidir(
        "modos_amortecedor",
        [
            obs(
                "modos_amortecedor",
                ["normal", "sport", "off_road"],
                "Normal, Sport, Off-Road",
                source_id="ford",
            ),
            obs(
                "modos_amortecedor",
                ["normal", "sport", "baja"],
                "Normal, Sport, Baja",
                source_id="slide",
                url="interno://slide",
            ),
        ],
        textos={
            "ford": "3 modos de amortecedor: Normal, Sport, Off-Road",
            "slide": "3 modos de amortecedor: Normal, Sport, Baja",
        },
    )
    assert d.status is Status.DIVERGENTE
    valores = [d.spec.value, *(c.value for c in d.spec.conflicts)]
    assert ["normal", "sport", "off_road"] in valores
    assert ["normal", "sport", "baja"] in valores
    assert all(c.evidence.quote for c in d.spec.conflicts), "cada valor com sua evidência"
    assert "divergem" in (d.spec.notes or "")


def test_divergencia_nao_ganha_bonus_de_confianca():
    """Discordância não aumenta certeza: fica a base do melhor tier, sem bônus."""
    d = decidir(
        "potencia_cv",
        [
            obs("potencia_cv", 397, "397cv", source_id="a"),
            obs("potencia_cv", 420, "420cv", source_id="b"),
        ],
        textos={"a": "Potencia 397cv", "b": "Potencia 420cv"},
    )
    assert d.status is Status.DIVERGENTE
    assert d.spec.confidence == 0.90, "sem +0,05, apesar de haver duas fontes"


def test_quote_inventado_vira_nao_verificado_com_valor_nulo():
    """Critério: quote inventado → `nao_verificado` e valor **descartado**."""
    d = decidir(
        "potencia_cv",
        [obs("potencia_cv", 500, "Potencia 500cv")],
        textos={"s1": "Potencia 397cv"},
    )
    assert d.status is Status.NAO_VERIFICADO
    assert d.spec.value is None
    assert len(d.descartadas) == 1
    assert "não foi localizado" in (d.spec.notes or "")
    assert "auditoria" in (d.spec.notes or "")


def test_ausencia_declarada_por_fonte_oficial_e_nao_disponivel():
    """Critério: "—" na coluna da versão de tabela oficial → `nao_disponivel`."""
    d = decidir(
        "camera_360",
        [obs("camera_360", None, "—", tier=1, source_id="pdf", ausencia_declarada=True)],
        textos={"pdf": "Câmera 360   —"},
    )
    assert d.status is Status.NAO_DISPONIVEL
    assert d.spec.value is None
    assert "oficial" in (d.spec.notes or "")


def test_nenhuma_fonte_menciona_e_nao_encontrado_com_fontes_listadas():
    d = decidir(
        "capacidade_reboque_kg",
        [],
        textos={},
        sources_checked=["https://ford.com.br", "https://fipe"],
    )
    assert d.status is Status.NAO_ENCONTRADO
    assert d.spec.value is None
    assert d.spec.sources_checked == ["https://ford.com.br", "https://fipe"]


# ------------------------------------------------------------ os dois vazios
def test_os_dois_vazios_nao_se_colapsam():
    """ "A Ford diz que não tem" não é "não achei". A tela mostra os dois diferente."""
    nao_disponivel = decidir(
        "camera_360",
        [obs("camera_360", None, "—", tier=1, ausencia_declarada=True)],
        textos={"s1": "Câmera 360  —"},
    )
    nao_encontrado = decidir("camera_360", [], textos={}, sources_checked=["https://a"])
    assert nao_disponivel.status is Status.NAO_DISPONIVEL
    assert nao_encontrado.status is Status.NAO_ENCONTRADO
    assert nao_disponivel.status is not nao_encontrado.status


def test_ausencia_afirmada_so_por_imprensa_nao_e_nao_disponivel():
    """Imprensa não mencionar não é a fonte oficial **afirmar** que não existe."""
    d = decidir(
        "camera_360",
        [obs("camera_360", None, "-", tier=3, source_id="revista", ausencia_declarada=True)],
        textos={"revista": "não vimos câmera 360  -"},
    )
    assert d.status is Status.NAO_ENCONTRADO
    assert "não é afirmação de ausência" in (d.spec.notes or "")


# ------------------------------------------------------ grounding vem primeiro
def test_valor_sem_grounding_nao_entra_no_agrupamento():
    """Se entrasse, poderia **vencer por maioria** e virar valor da ficha sem evidência.

    Aqui dois valores errados (sem trecho na fonte) contra um certo: o certo ganha,
    porque os outros dois nem chegam a ser contados.
    """
    d = decidir(
        "potencia_cv",
        [
            obs("potencia_cv", 500, "Potencia 500cv", source_id="a"),
            obs("potencia_cv", 500, "Potencia 500cv de forca", source_id="b"),
            obs("potencia_cv", 397, "397cv", source_id="c"),
        ],
        textos={"a": "Potencia 397cv", "b": "Potencia 397cv", "c": "Potencia 397cv"},
    )
    assert d.status is Status.VERIFICADO
    assert d.spec.value == 397
    assert len(d.descartadas) == 2


def test_falha_de_grounding_e_contada():
    from pipeline.ground import grounding_fail_total

    decidir(
        "potencia_cv",
        [obs("potencia_cv", 500, "Potencia 500cv")],
        textos={"s1": "Potencia 397cv"},
    )
    assert grounding_fail_total() == 1


# ------------------------------------------------------------------- confiança
def test_confianca_e_base_do_melhor_tier_mais_bonus():
    uma = decidir("potencia_cv", [obs("potencia_cv", 397, "397cv")], textos={"s1": "397cv"})
    assert uma.spec.confidence == 0.90

    duas = decidir(
        "potencia_cv",
        [
            obs("potencia_cv", 397, "397cv", source_id="a"),
            obs("potencia_cv", 397, "397 cv", source_id="b"),
        ],
        textos={"a": "397cv", "b": "397 cv"},
    )
    assert duas.spec.confidence == pytest.approx(0.90 + BONUS_POR_CONCORDANTE)


def test_campo_so_de_imprensa_nao_passa_de_060():
    """`docs/05`: apenas T3 → verificado com confiança ≤ 0,60."""
    d = decidir(
        "aceleracao_0_100_s",
        [
            obs("aceleracao_0_100_s", 5.8, "5,8 s", tier=3, source_id="a"),
            obs("aceleracao_0_100_s", 5.8, "5,8 s medidos", tier=3, source_id="b"),
        ],
        textos={"a": "0 a 100 em 5,8 s", "b": "aceleração 5,8 s medidos"},
    )
    assert d.status is Status.VERIFICADO
    assert d.spec.confidence <= CONFIANCA_MAXIMA_TIER3


def test_confianca_nunca_passa_de_um():
    observacoes = [
        obs("potencia_cv", 397, "397cv", source_id=f"s{i}", url=f"https://f{i}") for i in range(8)
    ]
    d = decidir("potencia_cv", observacoes, textos={f"s{i}": "397cv" for i in range(8)})
    assert d.spec.confidence <= 1.0


# ------------------------------------------------------------------- evidência
def test_evidencia_carrega_url_tier_data_e_raw_value():
    d = decidir(
        "torque_nm",
        [
            obs(
                "torque_nm",
                499,
                "50,9 / 2.800",
                tier=1,
                source_id="pdf",
                url="https://media.toyota.com.br/x.pdf",
                captured_at="2026-09-01",
                raw_value="50,9 kgf.m",
                pagina=7,
            )
        ],
        textos={"pdf": "Torque (kgf.m/rpm) 50,9 / 2.800"},
    )
    evidencia = d.spec.evidences[0]
    assert evidencia.source_url == "https://media.toyota.com.br/x.pdf"
    assert evidencia.tier == 1
    assert evidencia.captured_at == "2026-09-01"
    assert evidencia.raw_value == "50,9 kgf.m"
    assert evidencia.page == 7
    assert evidencia.snapshot_id == "pdf"


def test_o_campo_decidido_valida_contra_o_schema():
    """Um campo que não valida no schema não pode sair do pipeline."""
    from pipeline.schema import empty_spec

    d = decidir("potencia_cv", [obs("potencia_cv", 397, "397cv")], textos={"s1": "397cv"})
    spec = empty_spec(job_id="teste")
    spec.set("motorizacao.potencia_cv", d.spec)
    spec.to_json()


# --------------------------------------------------------------------- em lote
def test_decidir_todos_preenche_campo_sem_observacao():
    decisoes = decidir_todos(
        {"potencia_cv": [obs("potencia_cv", 397, "397cv")]},
        textos={"s1": "397cv"},
        campos=["potencia_cv", "torque_nm"],
        sources_checked=["https://ford"],
    )
    assert decisoes["potencia_cv"].status is Status.VERIFICADO
    assert decisoes["torque_nm"].status is Status.NAO_ENCONTRADO
    assert decisoes["torque_nm"].spec.sources_checked == ["https://ford"]


def test_agrupamento_usa_a_mesma_tolerancia_do_eval():
    """583 e 583,4 são o mesmo torque (±1). Se a reconciliação discordasse do eval, o
    pipeline concordaria consigo mesmo e discordaria da régua."""
    d = decidir(
        "torque_nm",
        [
            obs("torque_nm", 583, "583Nm", source_id="a"),
            obs("torque_nm", 584, "584Nm", source_id="b"),
        ],
        textos={"a": "Torque 583Nm", "b": "Torque 584Nm"},
    )
    assert d.status is Status.VERIFICADO, "±1 Nm é a tolerância de docs/09"
