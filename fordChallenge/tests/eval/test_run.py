"""WP-02 — o harness do eval, e os relatorios honestos que ele produz.

Escrito quando `executar_pipeline` devolvia `empty_spec()`. Tres testes daqui
afirmavam o comportamento do **stub** ("o pipeline ainda nao existe"), e a WP-12 os
tornou falsos ao ligar a orquestracao. Foram reescritos para o invariante que
realmente protegiam, nao removidos: denominador visivel, metrica sem `n` saindo como
`null`, e o caso negativo do resolvedor sendo acusado.
"""

from __future__ import annotations

import json

import pytest

from pipeline.eval.gabarito import carregar_gabarito
from pipeline.eval.run import NOMES_METRICAS, Metrica, agregar, avaliar_veiculo, main, rodar


@pytest.fixture(scope="module")
def resultado():
    dados, gab, resultados, agregado = rodar(replay=True)
    return dados, gab, resultados, agregado


# ------------------------------------------------------------------- critério de aceite
def test_eval_roda_com_pipeline_stub_sem_excecao(resultado):
    dados, _, resultados, _ = resultado
    # 6 desde o gabarito v1.1: a Ranger Limited diesel de topo entrou em 10/09/2026.
    assert len(resultados) == 6
    assert "field_accuracy" in dados["aggregate"]


def test_field_accuracy_tem_denominador_visivel_e_esta_no_intervalo(resultado):
    """O denominador e o intervalo, nao o valor.

    Este teste ja afirmou `field_accuracy == 0.0`, e estava certo: media um pipeline que
    ainda nao existia (`executar_pipeline` devolvia `empty_spec()`). A WP-12 ligou o
    pipeline de proposito, e prender o numero aqui transformaria cada melhoria de
    extracao numa quebra de teste. O que continua valendo — e e o que `docs/09` pede — e
    que a metrica traga o denominador e nao invente valor fora de [0, 1].
    """
    dados = resultado[0]
    metrica = dados["aggregate"]["field_accuracy"]
    assert metrica["n"] > 0, "metrica sem denominador nao diz nada"
    assert metrica["acertos"] <= metrica["n"]
    assert 0.0 <= dados["field_accuracy"] <= 1.0


def test_coverage_e_1_com_ficha_completa(resultado):
    """`empty_spec()` já se pronuncia sobre todos os campos: cobertura total."""
    assert resultado[0]["aggregate"]["coverage"]["valor"] == 1.0


def test_hallucination_rate_zero(resultado):
    """Campo que o gabarito diz vazio nao pode vir com valor. Regra inviolavel."""
    agg = resultado[0]["aggregate"]["hallucination_rate"]
    assert agg["valor"] == 0.0
    assert agg["n"] > 0, "tem de haver campos nao_encontrado no gabarito para medir"


def test_metrica_sem_denominador_sai_como_null_nao_como_zero():
    """Metrica sem o que medir nao vira zero — zero pareceria resultado ruim.

    O invariante e da classe `Metrica`, e e a ela que o teste pergunta agora. Antes ele
    perguntava ao `grounding_rate` do relatorio, que tinha `n = 0` so porque nenhum valor
    era afirmado: a garantia dependia de o pipeline estar vazio, e desaparecia justamente
    quando o pipeline passasse a funcionar.
    """
    vazia = Metrica(nome="grounding_rate", meta="1,0")
    assert vazia.n == 0
    assert vazia.valor is None
    assert vazia.to_dict()["valor"] is None


def test_grounding_rate_e_1_quando_ha_valores_afirmados(resultado):
    """Todo valor na ficha tem trecho localizavel na fonte. Regra inviolavel."""
    agg = resultado[0]["aggregate"]["grounding_rate"]
    assert agg["n"] > 0, "o pipeline tem de afirmar algo para haver o que groundear"
    assert agg["valor"] == 1.0


def test_resolver_acerta_o_caso_negativo_do_gr_sport(resultado):
    """A GR-Sport nao existe na linha 2026, e o resolvedor tem de dizer isso.

    Este teste media o **stub**, que respondia `encontrada` para tudo e por isso errava o
    caso negativo. Com o resolvedor de verdade ligado (WP-07 + WP-12) o acerto e 1,0 — e o
    que ele protege agora e o mesmo de sempre, do lado certo: perguntar por uma versao que
    saiu de linha nao pode devolver a ficha da versao vizinha.
    """
    dados = resultado[0]
    grs = next(v for v in dados["vehicles"] if v["id"].startswith("toyota_hilux_gr_sport"))
    assert grs["metricas"]["resolver_accuracy"]["valor"] == 1.0
    assert "versao_inexistente" in grs["metricas"]["resolver_accuracy"]["detalhe"]


# ------------------------------------------------------------------------- estrutura
def test_todas_as_nove_metricas_aparecem(resultado):
    agg = resultado[0]["aggregate"]
    for nome, _ in NOMES_METRICAS:
        assert nome in agg, nome
    assert "time_per_vehicle_s" in agg
    assert "cost_per_vehicle_brl" in agg


def test_agregacao_soma_denominadores_em_vez_de_media_de_medias():
    a = Metrica("x", acertos=1, n=1)
    b = Metrica("x", acertos=0, n=9)
    total = agregar(
        [
            type("R", (), {"metricas": {"field_accuracy": a}})(),
            type("R", (), {"metricas": {"field_accuracy": b}})(),
        ]
    )
    # média de médias daria 0,5; a agregação correta dá 1/10
    assert total["field_accuracy"].valor == 0.1


def test_replay_encontra_os_snapshots_das_fixtures(resultado):
    """`--replay` tem de apontar para `tests/fixtures/snapshots`, não para `data/`."""
    dados = resultado[0]
    s10 = next(v for v in dados["vehicles"] if v["id"].startswith("chevrolet"))
    assert s10["fontes_bloqueadas"] == ["https://media.gm.com/brasil"]
    assert not any("nenhum snapshot" in o for v in dados["vehicles"] for o in v["observacoes"])


def test_fonte_bloqueada_aparece_como_status_nao_como_silencio(resultado):
    dados = resultado[0]
    s10 = next(v for v in dados["vehicles"] if v["id"].startswith("chevrolet"))
    assert any("bloqueada" in o for o in s10["observacoes"])


def test_nao_avaliados_ficam_visiveis(resultado):
    """Subcampo do gabarito sem campo canônico não pode desaparecer do relatório."""
    dados = resultado[0]
    raptor = next(v for v in dados["vehicles"] if v["id"] == "ford_ranger_raptor_2026")
    assert "tracao.descricao" in raptor["nao_avaliados"]
    assert "rodas_pneus.marca_pneu" in raptor["nao_avaliados"]


def test_pendente_coleta_da_hilux_nao_conta_como_erro(resultado):
    dados = resultado[0]
    hilux = next(v for v in dados["vehicles"] if v["id"] == "toyota_hilux_srx_plus_at_2026")
    precos = [c for c in hilux["campos"] if c["caminho"] == "comercial.preco_sugerido_brl"]
    assert precos and precos[0]["valor_ok"] is None
    assert precos[0]["status_ok"] is True


def test_avaliar_um_veiculo_isolado():
    veiculo = carregar_gabarito().por_id("ford_ranger_raptor_2026")
    r = avaliar_veiculo(veiculo, replay=True)
    assert r.metricas["coverage"].valor == 1.0
    # +2 desde a Fase 2 do plano 18/18: potencia_rpm e torque_rpm saem de nao_encontrado
    # (fora da medida) para valor com fonte (CarrosNaWeb, tier 3) — entram na medida.
    assert r.metricas["field_accuracy"].n == 29


# ------------------------------------------------------------------------- relatórios
def test_main_escreve_json_e_md(tmp_path):
    saida_json = tmp_path / "eval.json"
    saida_md = tmp_path / "eval.md"
    assert main(replay=True, saida_json=str(saida_json), saida_md=str(saida_md)) == 0
    dados = json.loads(saida_json.read_text(encoding="utf-8"))
    assert dados["aggregate"]["coverage"]["valor"] == 1.0
    md = saida_md.read_text(encoding="utf-8")
    assert "Relatorio do eval" in md or "Relatório do eval" in md
    assert "denominador" in md
    # o relatorio precisa dizer o que ficou fora e o que estava bloqueado
    assert "Fora da avaliacao" in md or "Fora da avaliação" in md
    assert "media.gm.com/brasil" in md


def test_relatorios_do_repo_sao_gerados(raiz):
    """`python scripts/task.py eval` grava em reports/; o portao de 11/09 le daqui."""
    assert main(replay=True) == 0
    dados = json.loads((raiz / "reports" / "eval.json").read_text(encoding="utf-8"))
    assert "field_accuracy" in dados["aggregate"]
    assert (raiz / "reports" / "eval.md").exists()
