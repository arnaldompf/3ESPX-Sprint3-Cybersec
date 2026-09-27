"""WP-13 — preço oficial: o valor só vale se a fonte o ligar **àquela versão**.

O erro que este arquivo existe para impedir: uma página de linha exibe o preço de todas
as versões (a S10 lista sete), e pegar "o preço da página" atribui à High Country o valor
da Cabine Simples. Erro grande, silencioso e plausível — o pior tipo.

Cada caso aqui é texto de fonte **real** salva na coleta, e o valor esperado é o do
`gabarito_v1.json`.
"""

from __future__ import annotations

import pytest

from pipeline.connectors.fipe import (
    CONFIANCA_MAXIMA_T3,
    JANELA_ANTES,
    PrecoOficial,
    preco_oficial,
    precos_plausiveis,
)

# ----------------------------------------------------------------- textos reais
#: `chevrolet_site`: o nome da versão fica na linha **anterior** ao preço, e a página
#: lista as sete versões da linha. Reproduz o espaço não separável (`\xa0`) do original.
CHEVROLET = """Escolha a sua S10

S10 CABINE SIMPLES
A partir de R$ 265.690
Ideal para o trabalho

S10 LTZ
A partir de R$\xa0333.690
Conforto e capacidade

Trail Boss
A partir de R$\xa0341.290
Feita para o off-road

S10 High Country
A partir de R$\xa0348.790
A S10 em sua forma mais exclusiva
"""

#: `autoesporte_amarok`: nome e preço na **mesma** linha, em dois formatos. A linha da
#: Barretos cita "Extreme" **depois** do preço, como descrição do que a série herda — e é
#: exatamente aí que uma janela simétrica pega o preço errado.
AUTOESPORTE = """A Volkswagen Amarok 2026 chega com preços a partir de R$ 339.990.

* **Volkswagen Amarok Comfortline -** R$ 339.990
* **Volkswagem Amarok Highline** \\- R$ 356.990
* **Volkswagen Amarok Extreme** \\- R$ 379.990
* **Volkswagem Amarok Barretos 70 anos (limitada a 200 unidades)** \\- R$ 389.990

O que cada versão traz:

* **Comfortline (R$ 339.990)** : seis airbags, rodas de 17 polegadas;
* **Highline (R$ 356.990)** : itens da Comfortline + rodas de 19 polegadas;
* **Extreme (R$ 379.990)** : itens da Highline + rodas de 20 polegadas;
* **Barretos 70 anos (R$ 389.990)** : itens da Extreme + capota marítima;
"""

#: `toyota_site_cd`: a página da **linha** Cabine Dupla exibe um preço só, o da versão de
#: entrada. O gabarito manda `pendente_coleta` para a SRX Plus — "não inferir".
TOYOTA = """Hilux Cabine Dupla

A partir de:
R$\xa0292.790,00

Selecione a cor
Branco Polar (040)
"""

#: `ford_site_versao`: página da própria versão, um preço só, e o "2" final é marcador de
#: rodapé colado pela conversão HTML→markdown.
FORD = """Ranger Raptor
Raptor 3.0 V6 Bi-turbo 4WD AT 2026 (AOD6)1

Preço a partir de

R$ 499.0002
"""


class TestPrecosPlausiveis:
    def test_acha_todos_os_precos_da_faixa(self):
        valores = [p.valor for p in precos_plausiveis(CHEVROLET)]
        assert valores == [265690, 333690, 341290, 348790]

    def test_espaco_nao_separavel_nao_esconde_o_preco(self):
        # `R$\xa0348.790` é o que a Chevrolet realmente serve.
        assert 348790 in [p.valor for p in precos_plausiveis(CHEVROLET)]

    def test_marcador_de_rodape_colado_nao_entra_no_valor(self):
        # "R$ 499.0002" é "R$ 499.000" + marcador "2". Ler o marcador daria 4.990.002.
        assert [p.valor for p in precos_plausiveis(FORD)] == [499000]

    def test_numero_fora_da_faixa_e_descartado(self):
        assert precos_plausiveis("Parcelas de R$ 4.999,00 e frete de R$ 2.500") == []

    def test_dois_offsets_porque_o_valor_pode_estar_em_outra_linha(self):
        # Na Ford, "a partir de" fica numa linha e os dígitos na seguinte. A citação sai
        # do offset dos dígitos: evidência sem o número não é evidência.
        (bruto,) = precos_plausiveis(FORD)
        assert bruto.inicio < bruto.inicio_valor
        assert FORD[bruto.inicio_valor :].startswith("499.000")


class TestPrecoDaVersaoCerta:
    def test_chevrolet_nome_na_linha_anterior(self):
        r = preco_oficial(CHEVROLET, versao="S10 High Country", tier=1)
        assert r.valor_brl == 348790  # gabarito: verificado, tier 1
        assert "348.790" in r.quote
        assert "High Country" in r.contexto

    @pytest.mark.parametrize("versao", ["S10 CABINE SIMPLES", "S10 LTZ", "Trail Boss"])
    def test_chevrolet_cada_versao_recebe_o_seu(self, versao):
        # O teste que importa: nenhuma versão herda o preço da vizinha.
        esperados = {"S10 CABINE SIMPLES": 265690, "S10 LTZ": 333690, "Trail Boss": 341290}
        assert preco_oficial(CHEVROLET, versao=versao, tier=1).valor_brl == esperados[versao]

    def test_amarok_meia_cobertura_basta(self):
        # O catálogo diz "V6 Extreme"; a reportagem escreve só "Extreme".
        r = preco_oficial(AUTOESPORTE, versao="V6 Extreme", tier=3)
        assert r.valor_brl == 379990  # gabarito: verificado_tier3, tier 3

    def test_amarok_nao_pega_o_preco_da_barretos(self):
        # `"Barretos 70 anos (R$ 389.990) : itens da Extreme + capota"` tem a versão
        # pedida na mesma linha, mas **depois** do preço. Ler só para trás resolve isso
        # pela estrutura da frase ("Versão — R$ X"), não por sorte de ordenação.
        r = preco_oficial(AUTOESPORTE, versao="V6 Extreme", tier=3)
        assert r.valor_brl != 389990

    def test_ford_pagina_da_versao_com_um_preco_so(self):
        r = preco_oficial(FORD, versao="Raptor 3.0 V6 Bi-turbo 4WD AT", tier=1, escopo="versao")
        assert r.valor_brl == 499000  # gabarito: verificado, tier 1
        assert "499.000" in r.quote
        assert "escopo da página" in r.nota

    def test_escopo_de_versao_nao_vale_para_pagina_com_varios_precos(self):
        # Se a página tem sete preços, ela não é da versão — a exceção não se aplica.
        r = preco_oficial(CHEVROLET, versao="Colorado ZR2", tier=1, escopo="versao")
        assert r.valor_brl is None

    def test_escopo_invalido_e_erro_de_programacao(self):
        with pytest.raises(ValueError, match="escopo"):
            preco_oficial(CHEVROLET, versao="S10 High Country", escopo="pagina")


class TestSemValorEmVezDeChute:
    def test_toyota_pendente_em_vez_do_preco_da_versao_de_entrada(self):
        # O caso do gabarito: "Site exibe apenas 'A partir de R$ 292.790,00' para a linha
        # (versão de entrada). Coletar no configurador Toyota ou release; não inferir."
        r = preco_oficial(TOYOTA, versao="SRX Plus AT (Cabine Dupla)", tier=1)
        assert r.valor_brl is None
        assert not r.ok
        assert "292.790" in r.nota
        assert "não inferir" in r.nota

    def test_nao_existe_fallback_para_o_menor_preco_da_pagina(self):
        # A tentação: "a partir de" é o menor, então o menor serve. Não serve — o menor é
        # o preço da versão de entrada, e a pergunta era sobre outra versão.
        r = preco_oficial(CHEVROLET, versao="Colorado ZR2", tier=1)
        assert r.valor_brl is None
        assert r.valor_brl != 265690

    def test_versao_antes_de_precos_diferentes_nao_devolve_valor(self):
        texto = "Extreme - R$ 379.990 no lançamento\nExtreme - R$ 401.500 com o pacote"
        r = preco_oficial(texto, versao="Extreme", tier=1)
        assert r.valor_brl is None
        # Divergência se expõe: os dois valores aparecem na nota.
        assert "379.990" in r.nota and "401.500" in r.nota

    def test_pagina_sem_preco_diz_que_nao_tem_preco(self):
        r = preco_oficial("Consulte o seu concessionário.", versao="S10 High Country")
        assert r.valor_brl is None
        assert "não exibe preço" in r.nota

    def test_sem_versao_pedida_nao_ha_o_que_associar(self):
        r = preco_oficial(CHEVROLET, versao="", tier=1)
        assert r.valor_brl is None


class TestRebaixamentoT3:
    def test_criterio_de_aceite_amarok_t3_com_nota_e_confianca_limitada(self):
        """Critério de aceite: site sem preço por versão → T3, nota, confiança ≤ 0,6."""
        r = preco_oficial(AUTOESPORTE, versao="V6 Extreme", tier=3, fonte="autoesporte")
        assert r.valor_brl == 379990
        assert r.tier == 3
        assert r.confianca <= CONFIANCA_MAXIMA_T3 == 0.60
        assert "imprensa" in r.nota

    def test_tier_1_mantem_confianca_alta(self):
        r = preco_oficial(CHEVROLET, versao="S10 High Country", tier=1)
        assert r.confianca == 0.90

    def test_a_janela_e_curta_de_proposito(self):
        # A folga medida nas fontes: os acertos precisam de 8 e 12 caracteres, o falso
        # positivo mais próximo precisa de 30. Uma janela que crescesse até lá começaria
        # a atribuir preço errado — e para o lado que engana.
        assert 12 < JANELA_ANTES < 30


class TestPrecoOficialOk:
    def test_sem_valor_nao_esta_ok(self):
        assert not PrecoOficial().ok

    def test_com_valor_esta_ok(self):
        assert PrecoOficial(valor_brl=348790).ok
