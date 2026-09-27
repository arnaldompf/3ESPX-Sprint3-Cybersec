"""WP-09 — a regra de casamento de nome, num lugar só.

`pipeline/matching.py` nasceu porque o mesmo defeito apareceu **três vezes**: ontologia
(WP-01), resolvedor (WP-07) e recorte de coluna (WP-09). Estes testes travam a regra na
origem, para que a quarta ocorrência não exista.
"""

from __future__ import annotations

import pytest

from pipeline import matching


def _avaliar(alvo: str, candidatos: list[str], **kw):
    return matching.avaliar(alvo, candidatos, **kw)


# ------------------------------------------------------------------------- cobertura
def test_cobertura_conta_tokens_do_pedido_presentes_no_candidato():
    assert matching.cobertura(["srx", "plus"], ["srx", "plus"]) == 1.0
    assert matching.cobertura(["srx", "plus"], ["srx"]) == 0.5
    assert matching.cobertura(["srx", "plus"], ["outro"]) == 0.0
    assert matching.cobertura([], ["srx"]) == 0.0


def test_cobertura_tolera_erro_de_digitacao():
    """ "volnte" ≈ "volante": um caractere a menos não pode zerar a cobertura."""
    assert matching.cobertura(["volnte"], ["volante"]) == 1.0
    assert matching.cobertura(["pluss"], ["plus"]) == 1.0
    assert matching.cobertura(["srx"], ["srv"]) == 0.0


# ------------------------------------------------------------------- o defeito central
def test_subconjunto_de_tokens_nao_empata_com_o_nome_completo():
    """O defeito que motivou o módulo: `token_set_ratio` dá 100 para subconjunto.

    Quem pede "srx plus" não aceita "srx". A cobertura resolve: 2/2 contra 1/2.
    """
    r = _avaliar("srx plus", ["srx", "srx plus", "srv"])
    assert r.vencedor is not None
    assert r.vencedor.valor == "srx plus"
    assert not r.ambiguo


def test_pedido_mais_longo_que_o_candidato_ainda_casa_pelo_maximo_unico():
    """ "srx plus cabine dupla" (nome do gabarito) contra a coluna "srx plus" da tabela."""
    r = _avaliar("srx plus cabine dupla", ["std power pack", "sr", "srv", "srx", "srx plus"])
    assert r.vencedor is not None
    assert r.vencedor.valor == "srx plus"
    assert r.vencedor.cobertura == pytest.approx(0.5)


def test_pedido_curto_casa_com_candidato_longo():
    """ "raptor" contra "raptor 3.0 v6 bi turbo": cobertura 1/1."""
    r = _avaliar("raptor", ["raptor 3.0 v6 bi turbo"])
    assert r.vencedor is not None
    assert r.vencedor.cobertura == 1.0


def test_nome_identico_ganha_sozinho_mesmo_com_sufixo_por_perto():
    r = _avaliar("srx", ["srx", "srx plus"])
    assert r.vencedor is not None
    assert r.vencedor.valor == "srx"
    assert r.vencedor.exato


# ----------------------------------------------------------------------- ambiguidade
def test_empate_no_topo_e_ambiguidade_nao_escolha():
    """Seis versões contêm "s10"; escolher uma seria escolher em silêncio."""
    r = _avaliar("s10", ["s10 wt", "s10 ltz", "s10 z71"])
    assert r.vencedor is None
    assert r.ambiguo
    assert len(r.empatados) == 3


def test_dois_candidatos_identicos_tambem_sao_ambiguos():
    r = _avaliar("extreme", ["extreme", "extreme"])
    assert r.vencedor is None
    assert r.ambiguo


# ------------------------------------------------------------------------- rejeições
def test_cobertura_abaixo_do_minimo_rejeita():
    r = _avaliar("gr sport", ["std power pack", "sr", "srv", "srx", "srx plus"])
    assert r.vencedor is None
    assert not r.ambiguo


def test_pedido_vazio_rejeita():
    assert _avaliar("", ["srx"]).vencedor is None


def test_lista_vazia_rejeita():
    assert _avaliar("srx", []).vencedor is None
    assert _avaliar("srx", ["", ""]).vencedor is None


def test_dois_portoes_independentes_cobertura_e_similaridade():
    """ "raptor baja edition" contra "raptor 3.0 v6" é rejeitado por **ambos** os portões.

    Cobertura 1/3 = 0,33 (abaixo do mínimo de 0,5) **e** `token_set_ratio` 63 (abaixo do
    limiar de 85 de `docs/05`). Baixar só um dos dois não é suficiente — é o que faz o
    caso "pediu uma edição especial que não existe" ser rejeitado com folga.
    """
    alvo, candidatos = "raptor baja edition", ["raptor 3.0 v6"]
    avaliado = _avaliar(alvo, candidatos).todos[0]
    assert avaliado.cobertura == pytest.approx(1 / 3)
    assert avaliado.score < matching.LIMIAR_MATCH

    assert _avaliar(alvo, candidatos).vencedor is None
    # só a cobertura frouxa não passa: o limiar de similaridade continua barrando
    assert _avaliar(alvo, candidatos, cobertura_minima=0.3).vencedor is None
    # com os dois frouxos, passa — e é por isso que os dois existem
    assert _avaliar(alvo, candidatos, cobertura_minima=0.3, limiar=60).vencedor is not None


def test_similaridade_global_alta_nao_salva_cobertura_baixa():
    """O portão de cobertura é o que impede "srx" de ganhar de "srx plus".

    `token_set_ratio` daria 100 nos dois casos (subconjunto); a cobertura é o que
    diferencia, e ela é o critério **primário**.
    """
    r = _avaliar("srx plus turbo diesel automatico", ["srx"])
    assert r.todos[0].score == 100.0, "o scorer global premia subconjunto"
    assert r.todos[0].cobertura < matching.COBERTURA_MINIMA
    assert r.vencedor is None


def test_resultado_expoe_todos_os_candidatos_avaliados():
    r = _avaliar("srx plus", ["srx", "srx plus", "srv"])
    assert len(r.todos) == 3
    assert {m.valor for m in r.todos} == {"srx", "srx plus", "srv"}
    assert r.score == 100.0
