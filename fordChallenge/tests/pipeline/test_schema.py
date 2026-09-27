"""WP-01 — o schema canônico é o contrato de saída e as regras invioláveis são código."""

from __future__ import annotations

import json

import jsonschema
import pytest
from pydantic import ValidationError

from pipeline.schema import (
    CAMPOS_VALIDACAO_EDITAL,
    GRUPOS,
    TOTAL_CAMPOS,
    UNIDADE_CANONICA,
    Conflict,
    Evidence,
    SpecField,
    Status,
    caminho_canonico,
    campos_canonicos,
    empty_spec,
    grupo_de,
    json_schema,
    resumo_validacao_edital,
    validar_contra_schema,
)


def _ev(**kw) -> Evidence:
    base = {
        "evidence_id": "ev-1",
        "source_url": "https://www.ford.com.br/picapes/ranger-raptor/",
        "tier": 1,
        "quote": "Potencia 397cv",
        "captured_at": "2026-09-01",
    }
    base.update(kw)
    return Evidence(**base)


# ------------------------------------------------------------------ estrutura da ficha
def test_empty_spec_valida_contra_o_json_schema():
    spec = empty_spec(job_id="job-1")
    spec.to_json()  # levanta se não validar
    validar_contra_schema(spec.to_dict())


def test_empty_spec_tem_exatamente_os_campos_obrigatorios_do_schema():
    dados = empty_spec().to_dict()
    esquema = json_schema()
    for grupo, definicao in esquema["properties"].items():
        if grupo in ("schema_version", "extras", "meta"):
            continue
        obrigatorios = set(definicao["required"])
        assert set(dados[grupo]) == obrigatorios, f"grupo {grupo} divergiu do JSON Schema"


def test_grupos_do_codigo_batem_com_o_json_schema():
    esquema = json_schema()
    for grupo, campos in GRUPOS.items():
        assert set(esquema["properties"][grupo]["required"]) == set(campos)
        # a ordem também é contrato: a ficha sai sempre na mesma ordem
        assert len(campos) == len(set(campos))


def test_total_de_campos_e_a_soma_dos_grupos():
    assert TOTAL_CAMPOS == sum(len(c) for c in GRUPOS.values()) == 58
    assert len(set(campos_canonicos())) == TOTAL_CAMPOS


def test_todo_campo_vazio_nasce_nao_encontrado_e_sem_valor():
    spec = empty_spec()
    for caminho, campo in spec.itens():
        assert campo.status is Status.NAO_ENCONTRADO, caminho
        assert campo.value is None, caminho
        assert campo.confidence == 0.0, caminho
        assert campo.evidences == [], caminho


def test_unidade_canonica_e_aplicada_no_campo_vazio():
    spec = empty_spec()
    assert spec.get("motorizacao.potencia_cv").unit == "cv"
    assert spec.get("motorizacao.torque_nm").unit == "Nm"
    assert spec.get("comercial.preco_sugerido_brl").unit == "BRL"
    assert spec.get("transmissao.paddle_shifters").unit is None


def test_acesso_por_caminho_curto_e_longo():
    spec = empty_spec()
    assert spec.get("potencia_cv") is spec.get("motorizacao.potencia_cv")
    assert spec.get("nao_existe_este_campo") is None
    assert caminho_canonico("paddle_shifters") == "transmissao.paddle_shifters"
    assert grupo_de("modos_direcao") == "modos"
    assert grupo_de("inventado") is None


# ---------------------------------------------------------- regras invioláveis de status
def test_status_sem_valor_rejeita_valor_nao_nulo():
    """`nao_encontrado` com valor é o pior erro possível: alucinação silenciosa."""
    for status in (Status.NAO_ENCONTRADO, Status.NAO_DISPONIVEL, Status.PENDENTE):
        with pytest.raises(ValidationError, match="value=None"):
            SpecField(value=397, status=status)


def test_os_dois_vazios_sao_estados_distintos():
    nao_disponivel = SpecField(value=None, status=Status.NAO_DISPONIVEL, notes="ficha diz '-'")
    nao_encontrado = SpecField(
        value=None, status=Status.NAO_ENCONTRADO, sources_checked=["https://ford.com.br"]
    )
    assert nao_disponivel.status != nao_encontrado.status
    # e o JSON Schema aceita os dois, com value nulo
    for campo in (nao_disponivel, nao_encontrado):
        jsonschema.validate(
            instance=campo.model_dump(mode="json"),
            schema={**json_schema()["$defs"]["SpecField"], "$defs": json_schema()["$defs"]},
        )


def test_verificado_exige_evidencia():
    with pytest.raises(ValidationError, match="ao menos uma evidência"):
        SpecField(value=397, status=Status.VERIFICADO, confidence=0.9)
    campo = SpecField.verificado(397, _ev(), unit="cv")
    assert campo.status is Status.VERIFICADO
    assert campo.confidence == 0.90  # base do tier 1
    assert campo.evidences[0].quote == "Potencia 397cv"


def test_divergente_preserva_todos_os_valores():
    with pytest.raises(ValidationError, match="conflicts"):
        SpecField(value=5.8, status=Status.DIVERGENTE, evidences=[_ev()])
    campo = SpecField(
        value=5.8,
        status=Status.DIVERGENTE,
        confidence=0.6,
        evidences=[_ev(quote="0 a 100 km/h em 5,8 s")],
        conflicts=[
            Conflict(
                value=6.5,
                evidence=_ev(
                    evidence_id="ev-2",
                    tier=3,
                    quote="medimos 6,5 s",
                    source_url="https://autoesporte.globo.com/teste",
                ),
                notes="medido em teste",
            )
        ],
    )
    valores = {campo.value, *(c.value for c in campo.conflicts)}
    assert valores == {5.8, 6.5}


def test_evidencia_exige_quote_nao_vazio_e_tier_valido():
    with pytest.raises(ValidationError):
        _ev(quote="   ")
    with pytest.raises(ValidationError):
        _ev(tier=0)
    with pytest.raises(ValidationError):
        _ev(tier=6)


def test_confianca_fica_entre_0_e_1():
    with pytest.raises(ValidationError):
        SpecField(value=None, status=Status.NAO_VERIFICADO, confidence=1.5)


def test_campo_extra_no_envelope_e_rejeitado():
    with pytest.raises(ValidationError):
        SpecField(value=None, status=Status.NAO_ENCONTRADO, inventado=True)


# ------------------------------------------------------------------------ extras e meta
def test_extras_recebe_atributo_livre_com_as_mesmas_regras():
    spec = empty_spec()
    spec.set("extras.ganchos_de_reboque", SpecField.vazio(Status.NAO_ENCONTRADO))
    spec.to_json()
    assert spec.get("extras.ganchos_de_reboque").status is Status.NAO_ENCONTRADO
    assert ("extras.ganchos_de_reboque", spec.extras["ganchos_de_reboque"]) in list(spec.itens())


def test_meta_carrega_resolucao_de_versao():
    spec = empty_spec(job_id="job-42")
    assert spec.meta.job_id == "job-42"
    assert spec.meta.version_resolution.status == "encontrada"
    spec.meta.version_resolution.status = "versao_inexistente"
    spec.meta.version_resolution.alternatives = ["SRX Plus AT"]
    dados = json.loads(spec.to_json())
    assert dados["meta"]["version_resolution"]["alternatives"] == ["SRX Plus AT"]


def test_json_schema_rejeita_ficha_adulterada():
    dados = empty_spec().to_dict()
    dados["identificacao"]["marca"]["status"] = "chute"
    with pytest.raises(jsonschema.ValidationError):
        validar_contra_schema(dados)


def test_toda_unidade_canonica_pertence_a_um_campo_real():
    for campo in UNIDADE_CANONICA:
        assert grupo_de(campo) is not None, f"{campo} não é campo canônico"


def test_todo_campo_da_validacao_do_edital_e_canonico():
    for campo in CAMPOS_VALIDACAO_EDITAL:
        assert grupo_de(campo) is not None, f"{campo} não é campo canônico"


def test_resumo_da_validacao_do_edital_separa_achado_de_vazio_explicado():
    spec = empty_spec()
    spec.set("motorizacao.potencia_cv", SpecField.verificado(397, _ev(), unit="cv"))
    spec.set(
        "motorizacao.potencia_rpm",
        SpecField(
            value=None, status=Status.NAO_ENCONTRADO, sources_checked=["https://ford.com.br"]
        ),
    )
    resumo = resumo_validacao_edital(spec)
    assert resumo["total"] == len(CAMPOS_VALIDACAO_EDITAL)
    assert "potencia_cv" in resumo["campos_achados"]
    assert resumo["achados"] == 1
    vazio_rpm = next(v for v in resumo["campos_vazios"] if v["campo"] == "potencia_rpm")
    assert vazio_rpm["status"] == "nao_encontrado"
    # os outros 16 campos nasceram vazios em empty_spec() e também entram como vazios
    assert len(resumo["campos_vazios"]) == len(CAMPOS_VALIDACAO_EDITAL) - 1


def test_resumo_da_validacao_do_edital_conta_divergente_como_achado():
    spec = empty_spec()
    spec.set(
        "desempenho.aceleracao_0_100_s",
        SpecField(
            value=5.8,
            status=Status.DIVERGENTE,
            evidences=[_ev()],
            conflicts=[Conflict(value=5.8, evidence=_ev()), Conflict(value=6.5, evidence=_ev())],
            confidence=0.9,
        ),
    )
    resumo = resumo_validacao_edital(spec)
    assert "aceleracao_0_100_s" in resumo["campos_achados"]


def test_resumo_da_validacao_do_edital_separa_duas_camadas():
    """`respondidos` (o que a tela mostra) soma com_valor + vazio_justificado — os dois
    vazios que provam que o sistema procurou. `sem_resposta` é só o resto: campo que o
    pipeline nunca tentou (nao_encontrado sem sources_checked) ou extraiu sem localizar
    o trecho (nao_verificado)."""
    spec = empty_spec()
    spec.set("motorizacao.potencia_cv", SpecField.verificado(397, _ev(), unit="cv"))
    # nao_disponivel: fonte oficial afirma a ausência — sempre justificado.
    spec.set(
        "transmissao.paddle_shifters",
        SpecField(
            value=None, status=Status.NAO_DISPONIVEL, sources_checked=["https://ford.com.br"]
        ),
    )
    # nao_encontrado com sources_checked não vazio: procuramos e nenhuma fonte cita —
    # é o caso dos 3 modos exclusivos de performance numa picape sem eles.
    spec.set(
        "modos.modos_direcao",
        SpecField(
            value=None,
            status=Status.NAO_ENCONTRADO,
            sources_checked=["https://ford.com.br", "https://carrosnaweb.com.br"],
        ),
    )
    # nao_encontrado sem sources_checked: nunca nem tentamos — continua sem_resposta.
    spec.set("motorizacao.potencia_rpm", SpecField(value=None, status=Status.NAO_ENCONTRADO))

    resumo = resumo_validacao_edital(spec)
    total = len(CAMPOS_VALIDACAO_EDITAL)
    assert resumo["com_valor"] == 1
    assert resumo["vazio_justificado"] == 2
    assert resumo["respondidos"] == 3
    assert resumo["sem_resposta"] == total - 3
    # compatibilidade: `achados` continua existindo e igual a `com_valor`.
    assert resumo["achados"] == resumo["com_valor"]

    por_campo = {v["campo"]: v for v in resumo["campos_vazios"]}
    assert por_campo["paddle_shifters"]["vazio_justificado"] is True
    assert por_campo["modos_direcao"]["vazio_justificado"] is True
    assert por_campo["modos_direcao"]["sources_checked"] == [
        "https://ford.com.br",
        "https://carrosnaweb.com.br",
    ]
    assert por_campo["potencia_rpm"]["vazio_justificado"] is False
