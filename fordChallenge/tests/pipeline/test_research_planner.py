"""O planejador de consultas: por família de campos, e não por ângulo editorial.

É aqui que o Pesquisador se separa dos quatro motores de busca estudados em 12/09/2026. A
expansão deles é por ângulo ("o que é", "como compara", "o que dizem"); a nossa é por
**família de campos**, com um mapa `consulta → campos_alvo`. Sem isso, a segunda rodada
repetiria a busca inteira em vez de perguntar pelo que ficou vazio.
"""

from __future__ import annotations

from pipeline.research import planner
from pipeline.schema import GRUPOS


class TestPrimeiraRodada:
    def plano(self):
        return planner.planejar("Ford", "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT", ano=2026)

    def test_cobre_os_tres_tiers(self):
        """Uma consulta por tier, todas de uma vez.

        Esperar o T1 terminar para só então perguntar à FIPE gastaria metade do orçamento
        de três minutos em espera. O que é sequencial é a coleta, não a busca.
        """
        tiers = {c.tier for c in self.plano().consultas}
        assert tiers == {1, 2, 3}

    def test_a_consulta_restrita_e_a_aberta_saem_JUNTAS(self):
        """`site:` devolve vazio em vários backends — o gpt-researcher chega a proibi-lo.

        Descobrir isso só na segunda rodada custaria metade do orçamento, então a forma
        aberta vai na mesma leva e a queda fica medida.
        """
        consultas = self.plano().consultas
        assert any(c.tem_operador and "site:ford.com.br" in c.texto for c in consultas)
        assert any(not c.tem_operador and "ficha técnica oficial" in c.texto for c in consultas)

    def test_pede_pdf_de_catalogo_explicitamente(self):
        """O PDF de catálogo **é** a ficha: em tabela, sem JavaScript e sem escudo antibot."""
        textos = " | ".join(c.texto for c in self.plano().consultas)
        assert "filetype:pdf" in textos
        assert "catálogo pdf" in textos

    def test_a_FIPE_e_o_PBE_declaram_os_campos_que_vao_preencher(self):
        """`campos_alvo` é o que permite a rodada seguinte perguntar só pela lacuna."""
        por_texto = {c.texto: c for c in self.plano().consultas}
        fipe = next(c for t, c in por_texto.items() if t.startswith("tabela fipe"))
        assert "preco_fipe_brl" in fipe.campos_alvo
        pbe = next(c for t, c in por_texto.items() if "PBE" in t)
        assert "consumo_urbano_kml" in pbe.campos_alvo

    def test_marca_sem_dominio_cadastrado_ainda_tem_plano(self):
        """Pesquisar uma picape de marca nova é o caso de uso do Pesquisador — ele não pode
        começar sem plano só porque a marca não está no mapa de domínios.

        Sem domínio conhecido não há `site:`, e o plano cai para a busca aberta — que era a
        rede de segurança desde o começo. A fonte oficial ainda é achável: o classificador
        reconhece o domínio da marca pelo nome quando o resultado chega.
        """
        consultas = planner.planejar("GWM", "Poer", "P30").consultas
        assert len(consultas) >= 5
        assert {c.tier for c in consultas} == {1, 2, 3}
        assert all(not c.tem_operador for c in consultas), "sem domínio, sem `site:`"

    def test_marca_cadastrada_fora_das_quatro_do_catalogo_usa_site(self):
        """A RAM não tem conector nem ficha no banco, mas o domínio dela é conhecido — e o
        `site:` é o caminho mais curto para o PDF de catálogo."""
        consultas = planner.planejar("RAM", "Rampage", "Laramie").consultas
        assert any("site:ram.com.br" in c.texto for c in consultas)

    def test_toda_consulta_diz_por_que_existe(self):
        """O motivo aparece na tela, ao lado da consulta. Consulta sem motivo é ruído."""
        for consulta in self.plano().consultas:
            assert len(consulta.motivo) > 15, consulta

    def test_sem_operadores_devolve_o_plano_B(self):
        plano = self.plano()
        assert len(plano.sem_operadores()) < len(plano.consultas)
        assert all(not c.tem_operador for c in plano.sem_operadores())


class TestConsultasDeLacuna:
    ALVO = planner.Alvo("Ford", "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT")

    def test_agrupa_por_familia_em_vez_de_uma_consulta_por_campo(self):
        """Quinze lacunas não podem virar quinze buscas.

        A página que responde "capacidade de carga" quase sempre responde "capacidade de
        reboque" na linha de baixo — são a mesma tabela. Perguntar pela família é perguntar
        pela tabela.
        """
        faltando = ["capacidade_carga_kg", "capacidade_reboque_kg", "tanque_l", "altura_mm"]
        consultas = planner.consultas_de_lacuna(self.ALVO, faltando)
        assert len(consultas) == 1
        assert set(consultas[0].campos_alvo) == set(faltando)
        assert "dimensões" in consultas[0].texto

    def test_a_familia_com_mais_lacunas_vem_primeiro(self):
        """É onde uma página só rende mais, e o orçamento é de doze páginas."""
        faltando = ["garantia_meses", "capacidade_carga_kg", "tanque_l", "altura_mm"]
        consultas = planner.consultas_de_lacuna(self.ALVO, faltando)
        assert len(consultas[0].campos_alvo) == 3

    def test_respeita_o_teto_de_consultas_dirigidas(self):
        faltando = [campo for campos in GRUPOS.values() for campo in campos]
        consultas = planner.consultas_de_lacuna(self.ALVO, faltando)
        assert len(consultas) <= planner.LIMITE_DE_CONSULTAS_DIRIGIDAS

    def test_nenhuma_consulta_carrega_nome_de_coluna_do_banco(self):
        """O mesmo defeito que o projeto já corrigiu em três telas: `preco_sugerido_brl`
        não é português, e um buscador não sabe o que fazer com ele."""
        faltando = ["preco_sugerido_brl", "aceleracao_0_100_s", "adas_itens", "codigo_fipe"]
        for consulta in planner.consultas_de_lacuna(self.ALVO, faltando):
            assert "_" not in consulta.texto, consulta.texto

    def test_sem_lacuna_nao_ha_segunda_rodada(self):
        assert planner.consultas_de_lacuna(self.ALVO, []) == []

    def test_continuacao_avanca_ate_todas_as_familias_sem_repetir_busca(self):
        faltando = [campo for campos in GRUPOS.values() for campo in campos]
        tentadas = set()
        cobertas = set()
        for _ in range(80):
            novas = planner.consultas_de_lacuna(self.ALVO, faltando, tentadas=tentadas)
            if not novas:
                break
            assert len(novas) <= planner.LIMITE_DE_CONSULTAS_DIRIGIDAS
            assert not tentadas.intersection(c.texto for c in novas)
            tentadas.update(c.texto for c in novas)
            cobertas.update(campo for c in novas for campo in c.campos_alvo)
        assert cobertas == set(faltando)
        assert not planner.consultas_de_lacuna(self.ALVO, faltando, tentadas=tentadas)

    def test_familia_ja_buscada_ganha_termos_dos_campos_pendentes(self):
        alvo = planner.Alvo("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT", ano=2027)
        campos = ["largura_mm", "capacidade_reboque_kg"]
        anteriores = planner.consultas_de_lacuna(alvo, campos)
        novas = planner.consultas_de_lacuna(alvo, campos, tentadas={c.texto for c in anteriores})
        assert novas, "a busca genérica fracassou, mas o planejador abandonou as lacunas"
        assert any("largura" in c.texto and "reboque" in c.texto for c in novas)
        assert all("2027" in c.texto and "Brasil" in c.texto for c in novas)
        assert all("Limited" in c.texto for c in novas)
        assert alvo.versao in novas[0].texto
        assert all(set(c.campos_alvo) <= set(campos) for c in novas)

    def test_retoma_com_busca_oficial_e_aberta_apos_esgotar_sites_de_ficha(self):
        alvo = planner.Alvo("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT", ano=2027)
        campos = ["garantia_meses"]
        tentadas = set()
        todas = []
        for _ in range(10):
            novas = planner.consultas_de_lacuna(alvo, campos, tentadas=tentadas)
            if not novas:
                break
            todas.extend(novas)
            tentadas.update(c.texto for c in novas)
        assert any(c.tier == 1 and "ford.com.br" in c.dominios for c in todas)
        assert any(not c.dominios and not c.tem_operador for c in todas)
        assert len({c.texto for c in todas}) == len(todas)

    def test_campos_respondidos_nao_voltam_nas_alternativas(self):
        alvo = planner.Alvo("Ford", "Ranger", "Limited", ano=2027)
        primeira = planner.consultas_de_lacuna(alvo, ["largura_mm", "capacidade_reboque_kg"])
        novas = planner.consultas_de_lacuna(
            alvo, ["capacidade_reboque_kg"], tentadas={c.texto for c in primeira}
        )
        assert novas
        assert all(c.campos_alvo == ("capacidade_reboque_kg",) for c in novas)
        assert all("largura" not in c.texto for c in novas)

    def test_marca_sem_dominio_nao_inventa_fonte_oficial(self):
        alvo = planner.Alvo("Marca nova", "Modelo", "Versão", ano=2027)
        campos = ["garantia_meses"]
        primeira = planner.consultas_de_lacuna(alvo, campos)
        novas = planner.consultas_de_lacuna(alvo, campos, tentadas={c.texto for c in primeira})
        assert novas
        assert all(not c.tem_operador and "site:" not in c.texto for c in novas)

    def test_consultas_especificas_nao_viram_lista_longa_de_atributos(self):
        alvo = planner.Alvo("Ford", "Ranger", "Limited", ano=2027)
        campos = list(GRUPOS["dimensoes"])
        primeira = planner.consultas_de_lacuna(alvo, campos)
        novas = planner.consultas_de_lacuna(alvo, campos, tentadas={c.texto for c in primeira})
        assert novas
        assert all(len(c.texto) < 400 for c in novas)
        assert all(1 <= len(c.campos_alvo) <= 2 for c in novas)

    def test_alternativas_ampliam_recuperacao_sem_tirar_versao_ano_ou_pais(self):
        alvo = planner.Alvo("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT", ano=2027)
        campos = ["garantia_meses"]
        primeira = planner.consultas_de_lacuna(alvo, campos)
        novas = planner.consultas_de_lacuna(alvo, campos, tentadas={c.texto for c in primeira})
        ampliadas = [c for c in novas if c.tier == 1 or not c.dominios]
        assert ampliadas
        for consulta in ampliadas:
            assert "Ford Ranger Limited" in consulta.texto
            assert "2027" in consulta.texto and "Brasil" in consulta.texto
            assert "4WD AT" not in consulta.texto
            assert "3.0 V6 Diesel" not in consulta.texto
        assert alvo.versao == "Limited 3.0 V6 Diesel 4WD AT", "identidade não muda com a consulta"

    def test_nome_curto_preserva_configuracao_composta_e_motor_quando_e_a_versao(self):
        for versao, esperado in [("High Country 2.8 Diesel 4x4 AT", "High Country"), ("V6", "V6")]:
            alvo = planner.Alvo("Chevrolet", "S10", versao, ano=2027)
            campos = ["garantia_meses"]
            primeira = planner.consultas_de_lacuna(alvo, campos)
            novas = planner.consultas_de_lacuna(alvo, campos, tentadas={c.texto for c in primeira})
            assert all(esperado in c.texto for c in novas)


class TestOMapaCobreOSchema:
    def test_toda_familia_e_um_grupo_do_schema(self):
        for familia in planner.FAMILIAS:
            assert familia in GRUPOS, familia

    def test_todo_grupo_tem_familia_menos_identificacao(self):
        """Um grupo sem família nunca viraria consulta dirigida: as lacunas dele ficariam
        invisíveis para a segunda rodada, em silêncio."""
        faltam = set(GRUPOS) - set(planner.FAMILIAS) - {"identificacao"}
        assert faltam == set(), faltam

    def test_todo_campo_tem_como_ser_perguntado_em_portugues(self):
        for campos in GRUPOS.values():
            for campo in campos:
                pergunta = planner.como_se_pergunta(campo)
                assert "_" not in pergunta, campo


class TestABuscaOndeTemFicha:
    """A pesquisa procura **onde tem ficha**, e não na web inteira.

    Medido na primeira pesquisa ao vivo da S10 High Country (13/09/2026): 15 dos 20
    resultados da primeira rodada saíram como "domínio não reconhecido" — buscas pagas por
    páginas que a coleta jamais aceitaria. A Tavily aceita `include_domains` e **não cobra
    a mais** por isso.
    """

    def test_a_primeira_rodada_pergunta_aos_sites_de_ficha(self):
        from pipeline.research import fontes

        consultas = planner.primeira_rodada(planner.Alvo("Chevrolet", "S10", "High Country"))
        restritas = [c for c in consultas if c.dominios]
        assert restritas, "nenhuma consulta foi aos sites que a sondagem aprovou"
        assert restritas[0].tier == 3
        assert set(restritas[0].dominios) == set(fontes.dominios_de_ficha())
        assert "ficha" in restritas[0].motivo

    def test_a_forma_aberta_continua_junto(self):
        """`include_domains` com lista estreita pode voltar vazio, e rodada sem resultado é
        pior que rodada com resultado ruim — o classificador filtra depois."""
        consultas = planner.primeira_rodada(planner.Alvo("Ford", "Ranger", "Raptor"))
        abertas = [c for c in consultas if c.tier == 3 and not c.dominios]
        assert len(abertas) >= 2

    def test_as_lacunas_perguntam_aos_sites_de_ficha(self):
        """O que sobra depois da primeira rodada é o que a montadora não publica —
        dimensões, suspensão, freios —, e é o que a ficha de terceiro traz em tabela."""
        faltando = ["comprimento_mm", "largura_mm", "altura_mm", "suspensao_dianteira"]
        consultas = planner.consultas_de_lacuna(
            planner.Alvo("Chevrolet", "S10", "High Country"), faltando
        )
        assert consultas
        assert all(c.dominios for c in consultas)
        assert all(c.tier == 3 for c in consultas)

    def test_os_dominios_viajam_para_a_trilha(self):
        consultas = planner.primeira_rodada(planner.Alvo("Chevrolet", "S10"))
        restrita = next(c for c in consultas if c.dominios)
        assert restrita.to_dict()["dominios"] == list(restrita.dominios)
