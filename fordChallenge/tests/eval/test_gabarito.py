"""WP-02 — carregador do gabarito e o mapa gabarito→canônico.

O gabarito é verdade-terra: se ele estiver incoerente, todas as métricas mentem. Estes
testes travam a forma dele e o mapa que liga seus atributos aos campos canônicos.
"""

from __future__ import annotations

import json

import pytest

from pipeline.eval.gabarito import GABARITO_PADRAO, carregar_gabarito
from pipeline.eval.mapping import (
    OBJETOS,
    STATUS_GABARITO_PARA_CANONICO,
    alvos_do_atributo,
    status_compativel,
    validar_mapa,
)
from pipeline.schema import grupo_de


@pytest.fixture(scope="module")
def gab():
    return carregar_gabarito()


# ------------------------------------------------------------------------------- mapa
def test_todo_campo_do_mapa_existe_no_schema_canonico():
    validar_mapa()


def test_mapa_cobre_todos_os_atributos_do_gabarito():
    """Atributo do gabarito sem alvo é campo que ninguém está medindo."""
    bruto = json.loads(GABARITO_PADRAO.read_text(encoding="utf-8"))
    nomes = {n for v in bruto["veiculos"] for n in (v.get("atributos") or {})}
    for nome in nomes:
        exemplo = next(
            v["atributos"][nome]["esperado"]
            for v in bruto["veiculos"]
            if nome in (v.get("atributos") or {})
        )
        assert alvos_do_atributo(nome, exemplo), f"atributo {nome} sem alvo no mapa"


def test_subcampo_desconhecido_levanta_em_vez_de_ser_ignorado():
    with pytest.raises(KeyError, match="subcampo desconhecido"):
        alvos_do_atributo("motor", {"deslocamento_l": 3.0, "cor_do_bloco": "azul"})


def test_amortecedores_aceita_escalar_e_objeto():
    """Na Raptor é string; nos concorrentes é objeto com suspensões."""
    escalar = alvos_do_atributo("amortecedores", "FOX Racing 2.5 Live Valve")
    assert [a.caminho for a in escalar] == ["chassi.amortecedores"]
    objeto = alvos_do_atributo(
        "amortecedores",
        {"suspensao_dianteira": "x", "suspensao_traseira": "y", "amortecedores": None},
    )
    assert {a.caminho for a in objeto} == {
        "chassi.suspensao_dianteira",
        "chassi.suspensao_traseira",
        "chassi.amortecedores",
    }


def test_status_compativel_segue_docs09():
    assert status_compativel("verificado", "verificado")
    assert not status_compativel("verificado", "nao_encontrado")
    assert status_compativel("verificado_tier3", "verificado")
    # nao_encontrado pode virar nao_disponivel se o pipeline achar a afirmação de ausência
    assert status_compativel("nao_encontrado", "nao_disponivel")
    assert status_compativel("nao_encontrado", "nao_encontrado")
    # ...mas nunca pode virar valor
    assert not status_compativel("nao_encontrado", "verificado")
    # pendente_coleta não é erro do pipeline
    for status in STATUS_GABARITO_PARA_CANONICO["pendente_coleta"]:
        assert status_compativel("pendente_coleta", status)


def test_status_desconhecido_levanta():
    with pytest.raises(KeyError):
        status_compativel("status_que_nao_existe", "verificado")


# -------------------------------------------------------------------------- carregador
def test_gabarito_carrega_os_seis_veiculos(gab):
    # v1.1 (10/09/2026): entrou a Ford Ranger Limited diesel de topo, coletada ao vivo e
    # marcada `extraído pelo pipeline; confirmação humana pendente`. Ver o bloco v1.1 no
    # topo de `gabarito/build_gabarito.py`.
    assert gab.versao == "1.1"
    assert len(gab.veiculos) == 6
    assert len(gab.veiculos_com_atributos) == 5  # o caso negativo não tem atributos


def test_todo_alvo_aponta_para_campo_canonico(gab):
    for veiculo in gab.veiculos:
        for campo in veiculo.campos:
            assert grupo_de(campo.campo) is not None, f"{veiculo.id}/{campo.origem}"
            assert campo.caminho.count(".") == 1


def test_caso_negativo_traz_a_resolucao_esperada(gab):
    grs = gab.por_id("toyota_hilux_gr_sport_2026_inexistente")
    assert grs.e_caso_negativo
    assert grs.resultado_esperado.status == "versao_inexistente"
    assert grs.resultado_esperado.sugestao_equivalente == "SRX Plus AT"
    assert "SRX Plus AT" in grs.nomes_da_linha_vigente
    assert grs.resultado_esperado.ultimo_ano_fipe == 2024


def test_raptor_tem_as_duas_divergencias_e_os_dois_rpm_ausentes(gab):
    """Fogo Amigo, atualizado pela Fase 2 do plano 18/18 (CarrosNaWeb, 2026-09-15):
    `potencia_rpm` (6250) diverge do slide (5650) e `torque_rpm` (3500) concorda com o
    slide — deixa de ser "ausente em fonte pública" para virar `verificado_tier3`. As
    duas divergências de modos continuam; `torque_rpm` sai de vez da contagem (nem
    ausente, nem divergente — concorda), e o total cai de 4 para 3."""
    raptor = gab.por_id("ford_ranger_raptor_2026")
    divergentes = {c.caminho for c in raptor.campos if c.status == "divergente"}
    assert divergentes == {
        "modos.modos_direcao",
        "modos.modos_amortecedor",
        "motorizacao.potencia_rpm",
    }
    ausentes = {c.caminho for c in raptor.campos_ausentes_em_fonte_publica}
    assert ausentes == set()
    assert len(divergentes) + len(ausentes) == 3


def test_divergencia_registrada_expoe_todos_os_valores(gab):
    """5,8 s da fonte oficial e 6,5 s medidos pela imprensa: os dois contam."""
    campo = gab.por_id("ford_ranger_raptor_2026").por_caminho("desempenho.aceleracao_0_100_s")
    assert campo.status == "verificado_tier3"
    assert campo.tem_divergencia_registrada
    assert set(campo.valores_esperados) == {5.8, 6.5}


def test_subcampo_nulo_em_atributo_verificado_nao_e_avaliado(gab):
    """`pacote_adas` é verificado, mas a Ford não usa nome comercial na ficha BR."""
    campo = gab.por_id("ford_ranger_raptor_2026").por_caminho("seguranca.adas_nome_comercial")
    assert campo.status == "verificado"
    assert campo.valor is None
    assert campo.avalia_status is False
    assert campo.avalia_valor is False


def test_fallback_descritivo_da_s10(gab):
    """A fonte oficial da S10 diz algo da suspensão sem nomear o amortecedor."""
    campo = gab.por_id("chevrolet_s10_high_country_2027").por_caminho("chassi.amortecedores")
    assert campo.status == "verificado"
    assert campo.valor == "suspensão com calibração refinada"


def test_preco_gera_tambem_data_e_referencia(gab):
    raptor = gab.por_id("ford_ranger_raptor_2026")
    assert raptor.por_caminho("comercial.preco_data").valor == "2026-09-01"
    assert raptor.por_caminho("comercial.fipe_referencia").valor == "2026-09"


def test_pendente_coleta_da_hilux_nao_exige_valor(gab):
    hilux = gab.por_id("toyota_hilux_srx_plus_at_2026")
    for caminho in ("comercial.preco_sugerido_brl", "comercial.preco_fipe_brl"):
        campo = hilux.por_caminho(caminho)
        assert campo.status == "pendente_coleta"
        assert campo.valor is None
        assert campo.avalia_valor is False


def test_gabarito_com_verdade_terra_incoerente_e_rejeitado(tmp_path):
    """`nao_encontrado` com valor esperado exigiria alucinação do pipeline."""
    bruto = json.loads(GABARITO_PADRAO.read_text(encoding="utf-8"))
    limited = next(v for v in bruto["veiculos"] if v["id"] == "ford_ranger_limited_2027")
    assert limited["atributos"]["amortecedores"]["status"] == "nao_encontrado"
    limited["atributos"]["amortecedores"]["esperado"] = "Bilstein"
    arquivo = tmp_path / "gabarito_ruim.json"
    arquivo.write_text(json.dumps(bruto, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="não pode exigir valor"):
        carregar_gabarito(arquivo)


def test_verificado_sem_fontes_e_rejeitado(tmp_path):
    bruto = json.loads(GABARITO_PADRAO.read_text(encoding="utf-8"))
    bruto["veiculos"][0]["atributos"]["potencia_cv"]["fontes"] = []
    arquivo = tmp_path / "gabarito_sem_fonte.json"
    arquivo.write_text(json.dumps(bruto, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="exige `fontes`"):
        carregar_gabarito(arquivo)


def test_objetos_do_mapa_nao_repetem_campo_canonico():
    """Dois subcampos apontando para o mesmo campo se sobrescreveriam em silêncio."""
    for nome, mapa in OBJETOS.items():
        destinos = list(mapa.values())
        assert len(destinos) == len(set(destinos)), f"{nome} tem destino repetido"
