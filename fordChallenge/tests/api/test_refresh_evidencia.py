"""O alerta de divergência interna aponta para uma evidência que **existe no banco**.

Defeito real, encontrado no ensaio da demo: `alertas_de_referencia_interna` copiava o
`evidence_id` da ficha **recém-rodada** pelo pipeline, onde o id é sintético
(`source_id:campo`) e não é chave de nenhuma linha de `evidences`. O alerta guardava
`"ford_ficha_tecnica:modos_direcao"`, e a cadeia do "Por quê?" (WP-34) não achava a
evidência: o elo da prova saía com o motivo de ausência **na cena-assinatura do Fogo
Amigo**.

Nada acusava. O campo é opcional, `_evidencia_out` devolve `None` para id inexistente, e a
cadeia — que foi feita justamente para nunca ter elo vazio — mostrava o texto correto para
o motivo errado.
"""

from __future__ import annotations

import datetime as dt

import pytest

from api.app.models import Role

ALERTS = "/api/v1/alerts"


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def divergencia(catalogo):
    """Valor público com evidência no banco + material interno discordando.

    A ficha entregue a `alertas_de_referencia_interna` é montada como o **pipeline** a
    monta: com id de evidência sintético. É o que reproduz o defeito.
    """
    from api.app.db import session_scope
    from api.app.models import Evidence, InternalReference, SpecValue
    from pipeline.refresh import ResultadoDoRefresh, alertas_de_referencia_interna
    from pipeline.schema import Evidence as EvidenciaDoPipeline
    from pipeline.schema import SpecField, empty_spec

    with session_scope() as sessao:
        evidencia = Evidence(
            source_url="https://www.ford.com.br/picapes/ranger-raptor/",
            tier=1,
            quote="4 modos de direção selecionáveis – Normal, Conforto, Sport, Off-Road",
            captured_at=dt.datetime(2026, 9, 1),
            raw_value="Normal, Conforto, Sport, Off-Road",
        )
        sessao.add(evidencia)
        sessao.flush()
        evidencia_id = evidencia.id

        sessao.add(
            SpecValue(
                version_id=catalogo["raptor"],
                field="modos_direcao",
                value_json=["normal", "conforto", "sport", "off_road"],
                status="verificado",
                confidence=0.9,
                evidence_id=evidencia_id,
            )
        )
        sessao.add(
            InternalReference(
                version_id=catalogo["raptor"],
                field="modos_direcao",
                value_json=["normal", "sport", "conforto"],
                raw_value="Normal, Sport, Conforto",
                documento="deck comercial da Raptor",
            )
        )
        sessao.commit()

        # A ficha "recém-rodada", com o id sintético do pipeline.
        # `set` pelo caminho canônico: os grupos são dicionários no modelo.
        ficha = empty_spec()
        ficha.set(
            "modos.modos_direcao",
            SpecField.verificado(
                ["normal", "conforto", "sport", "off_road"],
                EvidenciaDoPipeline(
                    evidence_id="ford_ficha_tecnica:modos_direcao",
                    source_url="https://www.ford.com.br/picapes/ranger-raptor/",
                    tier=1,
                    quote="4 modos de direção selecionáveis – Normal, Conforto, Sport",
                    captured_at="2026-09-01",
                ),
            ),
        )

    from api.app.models import Version

    with session_scope() as sessao:
        version = sessao.get(Version, catalogo["raptor"])
        alertas = alertas_de_referencia_interna(
            sessao, version, ficha, resultado=ResultadoDoRefresh()
        )
        ids = [a.id for a in alertas]
    return {"alertas": ids, "evidencia": evidencia_id}


class TestAEvidenciaDoAlertaInterno:
    def test_o_alerta_aponta_para_a_linha_do_banco(self, divergencia):
        from api.app.db import session_scope
        from api.app.models import Alert, Evidence

        assert divergencia["alertas"], "nenhum alerta de divergência interna foi criado"
        with session_scope() as sessao:
            for alerta_id in divergencia["alertas"]:
                alerta = sessao.get(Alert, alerta_id)
                assert alerta.evidence_after_id == divergencia["evidencia"]
                # O ponto do teste: o id **resolve**.
                assert sessao.get(Evidence, alerta.evidence_after_id) is not None

    def test_a_cadeia_do_porque_mostra_a_citacao(self, cliente_auth, divergencia, analista):
        """O efeito visível: o elo da prova deixa de dizer "sem evidência gravada"."""
        alerta_id = divergencia["alertas"][0]
        cadeia = cliente_auth.get(f"{ALERTS}/{alerta_id}/trace", headers=analista).json()
        assert cadeia["evidencias"], cadeia["motivo_sem_evidencia"]
        assert cadeia["motivo_sem_evidencia"] == ""
        assert "modos de direção" in cadeia["evidencias"][0]["quote"]

    def test_valor_do_banco_diferente_do_publico_nao_ganha_citacao(self, catalogo):
        """Citar o trecho de **outro** valor seria prova de outra coisa.

        Se o banco tem 397 cv com evidência e a ficha nova diz 400, o alerta não pode
        anexar a citação do 397: o elo fica vazio e a cadeia diz o motivo (WP-34).
        """
        from api.app.db import session_scope
        from api.app.models import Alert, Evidence, InternalReference, SpecValue, Version
        from pipeline.refresh import ResultadoDoRefresh, alertas_de_referencia_interna
        from pipeline.schema import Evidence as EvidenciaDoPipeline
        from pipeline.schema import SpecField, empty_spec

        with session_scope() as sessao:
            evidencia = Evidence(
                source_url="https://www.ford.com.br/picapes/ranger-raptor/",
                tier=1,
                quote="Potência 397cv",
                captured_at=dt.datetime(2026, 9, 1),
            )
            sessao.add(evidencia)
            sessao.flush()
            sessao.add(
                SpecValue(
                    version_id=catalogo["srx"],
                    field="potencia_cv",
                    value_json=397,
                    status="verificado",
                    confidence=0.9,
                    evidence_id=evidencia.id,
                )
            )
            sessao.add(
                InternalReference(
                    version_id=catalogo["srx"],
                    field="potencia_cv",
                    value_json=380,
                    raw_value="380 cv",
                    documento="deck",
                )
            )
            sessao.commit()

            ficha = empty_spec()
            # A ficha nova diz 400: o valor do banco (397) não sustenta este número.
            ficha.set(
                "motorizacao.potencia_cv",
                SpecField.verificado(
                    400,
                    EvidenciaDoPipeline(
                        evidence_id="ford_site:potencia_cv",
                        source_url="https://www.ford.com.br/picapes/ranger-raptor/",
                        tier=1,
                        quote="Potência 400cv",
                        captured_at="2026-09-02",
                    ),
                ),
            )
            version = sessao.get(Version, catalogo["srx"])
            alertas = alertas_de_referencia_interna(
                sessao, version, ficha, resultado=ResultadoDoRefresh()
            )
            assert alertas
            for alerta in alertas:
                assert alerta.evidence_after_id is None
                # E o alerta continua sendo criado: a divergência é real.
                assert isinstance(alerta, Alert)
