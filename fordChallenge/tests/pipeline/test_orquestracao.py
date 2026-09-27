"""WP-12 — orquestração: a máquina de estados e a ficha que ela produz.

Dois defeitos travados aqui merecem destaque, porque nenhum dos dois dava erro:

* `TIPOS_COM_TABELA = ("pdf",)` nunca casava com o tipo real (`"pdf_oficial"`), então o
  **recorte de coluna por versão nunca rodava**. O sintoma não era exceção nenhuma: era a
  Hilux recebendo aro 17 e pneu 265/65 R17 — a coluna da SRX, não da SRX Plus;
* a montagem dos documentos existia em **duas** implementações (pipeline e gravador de
  fixtures), e elas divergiram. Prompt diferente → chave de fixture diferente → resposta
  gravada nunca encontrada. O replay parecia funcionar, só não respondia nada.
"""

from __future__ import annotations

import pytest

from pipeline.run import (
    ESTAGIOS,
    FINAIS,
    TIER_REFERENCIA_INTERNA,
    JobContext,
    campos_alvo,
    campos_canonicos,
    documentos_de,
    referencia_interna,
    run,
)
from pipeline.schema import GRUPOS, Status

RAPTOR = ("Ford", "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT", "ford_ranger_raptor_2026")
HILUX = ("Toyota", "Hilux", "SRX Plus AT (Cabine Dupla)", "toyota_hilux_srx_plus_at_2026")
INEXISTENTE = ("Toyota", "Hilux", "GR-Sport", "toyota_hilux_gr_sport_2026_inexistente")


@pytest.fixture(scope="module")
def ficha_raptor():
    return run(*RAPTOR[:3], version_id=RAPTOR[3], job_id="teste:raptor")


class TestCamposAlvo:
    def test_sem_atributos_e_a_ficha_inteira(self):
        # Um campo que ninguém tentou preencher é indistinguível de um campo que a fonte
        # não tem. O produto entrega ficha completa.
        assert len(campos_alvo()) == sum(len(c) for c in GRUPOS.values())

    def test_atributo_curto_vira_caminho_canonico(self):
        assert campos_alvo(["potencia_cv"]) == ["motorizacao.potencia_cv"]

    def test_atributo_desconhecido_nao_e_descartado_em_silencio(self):
        assert campos_alvo(["ganchos_de_reboque"]) == ["ganchos_de_reboque"]

    def test_todo_caminho_canonico_tem_grupo(self):
        assert all("." in c for c in campos_canonicos())


class TestMaquinaDeEstados:
    def test_a_ordem_dos_estagios_e_a_de_docs_05(self):
        assert ESTAGIOS[:4] == ("queued", "resolving", "fetching", "parsing")
        assert ESTAGIOS[-1] == "reconciling"
        assert set(FINAIS) == {"done", "failed", "versao_inexistente"}

    def test_nao_se_volta_um_estagio(self):
        ctx = JobContext(marca="Ford", modelo="Ranger", versao="Raptor")
        ctx.entra("extracting")
        with pytest.raises(ValueError, match="transição inválida"):
            ctx.entra("parsing")

    def test_estado_final_e_alcancavel_de_qualquer_estagio(self):
        ctx = JobContext(marca="Ford", modelo="Ranger", versao="Raptor")
        ctx.entra("resolving")
        ctx.entra("versao_inexistente")
        assert ctx.stage == "versao_inexistente"

    def test_cada_transicao_fica_registrada_com_o_tempo(self, ficha_raptor):
        ctx = JobContext(marca="Ford", modelo="Ranger", versao="Raptor")
        ctx.entra("resolving")
        ctx.entra("fetching")
        assert [t[0] for t in ctx.transicoes] == ["resolving", "fetching"]
        assert all(t[1] >= 0 for t in ctx.transicoes)


class TestFontesConsultadas:
    def test_fonte_bloqueada_entra_em_sources_checked(self):
        # É o que separa `nao_disponivel` de `nao_encontrado`. Uma fonte que fechou a
        # porta foi consultada, e o registro disso é o que dá sentido ao vazio.
        ficha = run(*HILUX[:3], version_id=HILUX[3])
        assert ficha.meta.sources_checked

    def test_o_bloqueio_da_gm_aparece_na_ficha_da_s10(self):
        ficha = run(
            "Chevrolet", "S10", "High Country", version_id="chevrolet_s10_high_country_2027"
        )
        assert any("media.gm.com" in f for f in ficha.meta.sources_checked)

    def test_textos_incluem_fonte_que_nao_e_snapshot(self):
        # A referência interna do cliente não é captura de página. Fora do dicionário de
        # textos, ela reprovaria no grounding sem ter culpa.
        ctx = JobContext(marca="Ford", modelo="Ranger", versao="Raptor", version_id=RAPTOR[3])
        documento = referencia_interna(RAPTOR[3])
        ctx.documentos.append(documento)
        assert ctx.textos["referencia_interna"] == documento.texto


class TestDocumentosDe:
    def test_o_pdf_da_toyota_tem_a_coluna_da_versao_recortada(self):
        # O defeito: comparar `tipo == "pdf"` com o tipo real `"pdf_oficial"`. Nunca
        # casava, o recorte nunca rodava, e a Hilux ganhava o aro da versão vizinha.
        documentos, _, _ = documentos_de(HILUX[3], "SRX Plus AT")
        com_celulas = [d for d in documentos if d.celulas]
        assert com_celulas, "nenhum documento com células: o recorte por versão não rodou"
        assert com_celulas[0].n_tabelas > 0

    def test_pagina_html_nao_tem_recorte_de_coluna(self):
        documentos, _, _ = documentos_de(HILUX[3], "SRX Plus AT")
        site = next(d for d in documentos if d.source_id == "toyota_site_cd")
        assert site.celulas == ()

    def test_pdf_com_celulas_recortadas_e_marcado_multiversao(self):
        """Defeito real: `Documento.multiversao` nasce `False` e `documentos_de` nunca a
        liga. `extrair_documento` só chama `_identidade_tabular` (que confere a coluna
        recortada, não a ficha inteira) quando `multiversao` é `True` — sem isso, todo PDF
        tabular vai para `identity.assess` com o texto inteiro, que menciona câmbio manual
        e anos de OUTRAS versões na mesma ficha, e a Hilux inteira saía `incompativel`
        mesmo com a coluna certa recortada e correta.
        """
        documentos, _, _ = documentos_de(HILUX[3], "SRX Plus AT")
        com_celulas = [d for d in documentos if d.celulas]
        assert com_celulas, "nenhum documento com células: o recorte por versão não rodou"
        assert com_celulas[0].multiversao is True

    def test_a_mesma_funcao_serve_pipeline_e_gravador_de_fixtures(self):
        # Duas montagens divergiram uma vez; agora há uma só, e o gravador chama esta.
        from scripts.record_llm_fixtures import documentos_do_veiculo

        pelo_pipeline, _, _ = documentos_de(HILUX[3], "SRX Plus AT")
        pelo_gravador = documentos_do_veiculo(HILUX[3], "SRX Plus AT")
        assert [d.source_id for d in pelo_pipeline] == [d.source_id for d in pelo_gravador]
        assert [len(d.celulas) for d in pelo_pipeline] == [len(d.celulas) for d in pelo_gravador]


class TestFichaDoRaptor:
    def test_a_ficha_tem_todos_os_campos_do_schema(self, ficha_raptor):
        assert len(list(ficha_raptor.itens())) == sum(len(c) for c in GRUPOS.values())

    def test_a_resolucao_da_versao_viaja_no_meta(self, ficha_raptor):
        assert ficha_raptor.meta.version_resolution.status == "encontrada"
        assert ficha_raptor.meta.version_resolution.matched_version

    def test_todo_valor_afirmado_tem_evidencia(self, ficha_raptor):
        sem_evidencia = [
            caminho
            for caminho, campo in ficha_raptor.itens()
            if campo.value is not None and not campo.evidences
        ]
        assert not sem_evidencia, f"valor sem evidência: {sem_evidencia}"

    def test_os_campos_comerciais_vem_do_conector_nao_do_fastpath(self, ficha_raptor):
        assert ficha_raptor.get("comercial.preco_sugerido_brl").value == 499000
        assert ficha_raptor.get("comercial.preco_fipe_brl").value == 452540
        assert ficha_raptor.get("comercial.fipe_referencia").value == "2026-09"

    def test_a_aceleracao_nao_e_zero(self, ficha_raptor):
        # Regressão do defeito mais perigoso desta WP: normalizar o texto bruto
        # ("0 a 100 km/h em 5,8 segundos") pegava o primeiro número da frase.
        assert ficha_raptor.get("desempenho.aceleracao_0_100_s").value == 5.8


class TestVersaoInexistente:
    def test_e_estado_final_legitimo_nao_falha(self):
        ficha = run(*INEXISTENTE[:3], version_id=INEXISTENTE[3])
        assert ficha.meta.version_resolution.status == "versao_inexistente"

    def test_nao_devolve_a_ficha_da_versao_mais_parecida(self):
        # O erro tentador: responder com a SRX Plus quando perguntaram GR-Sport. Isso põe
        # dado certo de um veículo na resposta sobre outro, e pareceria bom.
        ficha = run(*INEXISTENTE[:3], version_id=INEXISTENTE[3])
        com_valor = [c for c, campo in ficha.itens() if campo.value is not None]
        assert not com_valor

    def test_as_alternativas_ficam_visiveis(self):
        ficha = run(*INEXISTENTE[:3], version_id=INEXISTENTE[3])
        assert ficha.meta.version_resolution.alternatives

    def test_todo_campo_fica_nao_encontrado(self):
        ficha = run(*INEXISTENTE[:3], version_id=INEXISTENTE[3])
        assert all(campo.status is Status.NAO_ENCONTRADO for _, campo in ficha.itens())


class TestReferenciaInterna:
    def test_ausente_para_veiculo_sem_deck(self):
        assert referencia_interna("vw_amarok_v6_extreme_2026") is None

    def test_tier_4_abaixo_de_toda_fonte_publica(self):
        assert TIER_REFERENCIA_INTERNA == 4
        assert referencia_interna(RAPTOR[3]).tier == 4


class TestOVersionIdAdivinhadoPelaCLI:
    """`specradar extract Volkswagen Amarok "V6 Extreme"` tem de achar os snapshots.

    A chave do snapshot da Amarok é `vw_amarok_v6_extreme_2026` — com a **abreviação** da
    marca. Sem canonizar o alias, a cobertura contra o pedido "Volkswagen Amarok V6
    Extreme" fica em 0,60 (três de cinco tokens), o id é rejeitado pelo limiar de 0,75, e
    a extração roda **sem fonte nenhuma**: volta com um campo só (o do FIPE, que tem
    conector próprio) e **nenhum erro**.

    O eval não pega isto porque ele lê o `version_id` direto do gabarito. Pegou o ensaio da
    demo, onde a matriz de paridade da Amarok apareceu quase toda `desconhecido`.
    """

    def test_o_alias_da_marca_e_canonizado_nos_dois_lados(self):
        from pipeline.run import _version_id_provavel

        # O nome por extenso acha o id abreviado...
        assert _version_id_provavel("Volkswagen", "Amarok", "V6 Extreme") == (
            "vw_amarok_v6_extreme_2026"
        )
        # ...e a abreviação também, que é a simetria que faltava na primeira correção.
        assert _version_id_provavel("VW", "Amarok", "V6 Extreme") == ("vw_amarok_v6_extreme_2026")
        assert _version_id_provavel("GM", "S10", "High Country") == (
            "chevrolet_s10_high_country_2027"
        )

    def test_os_ids_sem_alias_continuam_resolvendo(self):
        from pipeline.run import _version_id_provavel

        assert _version_id_provavel("Ford", "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT") == (
            "ford_ranger_raptor_2026"
        )
        assert _version_id_provavel("Toyota", "Hilux", "SRX Plus AT (Cabine Dupla)") == (
            "toyota_hilux_srx_plus_at_2026"
        )

    def test_veiculo_sem_snapshot_devolve_vazio_em_vez_de_chutar(self):
        """O limiar de 0,75 continua valendo: ler o veículo errado é o pior resultado."""
        from pipeline.run import _version_id_provavel

        assert _version_id_provavel("Ford", "Bronco", "Wildtrak") == ""
        assert _version_id_provavel("Fiat", "Toro", "Ranch") == ""
