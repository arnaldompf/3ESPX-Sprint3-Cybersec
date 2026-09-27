"""WP-11 / docs/09 — `grounding_rate` sobre o gabarito e as fixtures reais.

`docs/09` põe a meta em **1,0**: todo valor não-nulo tem trecho localizado no texto salvo.
Aqui a medida é feita contra as fontes de verdade, não contra exemplos inventados.
"""

from __future__ import annotations

import pytest

from pipeline.eval.gabarito import carregar_gabarito
from pipeline.ground import MODO_DIFUSO, MODO_EXATO, MODO_SEM_ACENTO, locate
from pipeline.store import FIXTURES, snapshots_de


@pytest.fixture(scope="module")
def gab():
    return carregar_gabarito()


def test_quote_inventado_e_rejeitado_em_fonte_real(gab):
    """Critério de aceite da WP-02, medido contra o texto salvo da Raptor."""
    textos = list(
        {s.source_id: s.texto for s in snapshots_de("ford_ranger_raptor_2026", FIXTURES)}.values()
    )
    assert textos
    inventados = [
        "Potencia 900cv",
        "Torque 1.200Nm",
        "Capacidade de reboque de 5.000 kg",
        "Motor V12 4.0 biturbo",
    ]
    for quote in inventados:
        assert not any(locate(quote, t).ok for t in textos), f"{quote!r} não deveria groundar"


def test_todo_valor_do_pipeline_tem_trecho_localizado(gab):
    """A conta de `grounding_rate`, feita com o pipeline de extração de verdade."""
    from pipeline.extract.run import Documento, extrair_fontes

    sem_grounding: list[str] = []
    total = 0
    for veiculo in gab.veiculos_com_atributos:
        snaps = snapshots_de(veiculo.id, FIXTURES)
        textos = {s.source_id: s.texto for s in snaps}
        docs = [
            Documento(texto=s.texto, source_id=s.source_id, url=s.url, tier=s.tier) for s in snaps
        ]
        resultado = extrair_fontes(docs, {c.campo for c in veiculo.campos})
        for candidato in resultado.candidatos:
            total += 1
            if not locate(candidato.quote, textos.get(candidato.source_id, "")).ok:
                sem_grounding.append(f"{veiculo.id}/{candidato.campo}: {candidato.quote[:60]!r}")

    assert total > 0
    taxa = 1 - len(sem_grounding) / total
    assert taxa == 1.0, (
        f"grounding_rate {taxa:.4f} ({len(sem_grounding)} de {total} sem trecho):\n"
        + "\n".join(sem_grounding[:10])
    )


def test_modos_de_grounding_usados_nas_fontes_reais(gab):
    """Qual caminho confirma o quê, nas fontes de verdade.

    O caminho `exato` tem de dominar. Se o `difuso` dominasse, o grounding estaria
    passando por semelhança em vez de por identidade, e a métrica valeria menos.
    """
    from pipeline.extract.run import Documento, extrair_fontes

    contagem = {MODO_EXATO: 0, MODO_SEM_ACENTO: 0, MODO_DIFUSO: 0}
    for veiculo in gab.veiculos_com_atributos:
        snaps = snapshots_de(veiculo.id, FIXTURES)
        textos = {s.source_id: s.texto for s in snaps}
        docs = [
            Documento(texto=s.texto, source_id=s.source_id, url=s.url, tier=s.tier) for s in snaps
        ]
        for candidato in extrair_fontes(docs, {c.campo for c in veiculo.campos}).candidatos:
            achado = locate(candidato.quote, textos.get(candidato.source_id, ""))
            if achado.ok:
                contagem[achado.modo] += 1

    total = sum(contagem.values())
    assert total > 0
    assert contagem[MODO_EXATO] >= 0.9 * total, f"caminhos usados: {contagem}"


def test_trecho_do_gabarito_com_numero_errado_nao_grounda(gab):
    """A guarda numérica do caminho difuso, contra fonte real.

    Trocar só o número de um trecho que existe na fonte é o defeito mais perigoso do
    domínio, porque tudo em volta confere.
    """
    raptor = gab.por_id("ford_ranger_raptor_2026")
    textos = list({s.source_id: s.texto for s in snapshots_de(raptor.id, FIXTURES)}.values())
    potencia = raptor.por_caminho("motorizacao.potencia_cv")
    assert potencia.trecho
    assert any(locate(potencia.trecho, t).ok for t in textos), "o trecho real tem de groundar"

    adulterado = potencia.trecho.replace("397", "497")
    assert adulterado != potencia.trecho
    assert not any(locate(adulterado, t).ok for t in textos), (
        "trecho com número trocado não pode groundar"
    )
