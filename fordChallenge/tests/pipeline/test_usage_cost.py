"""WP-26 — custo mensal de combustível.

O critério de aceite é uma conta: `km_mes=2500`, consumo 9,5 km/l e diesel R$ 6,20 →
**R$ 1.632/mês**. O resto dos testes cerca as três formas de esse número virar mentira:

* usar o preço do combustível **errado** (a Raptor é gasolina; as concorrentes, diesel);
* apresentar consumo informado pelo vendedor como se fosse medição do Inmetro;
* devolver **zero** onde falta entrada — que na tela se lê como "custo zero".
"""

from __future__ import annotations

import datetime as dt

import pytest

from pipeline.fit import usage_cost

DATA = dt.date(2026, 9, 9)


def calcular(**kw):
    kw.setdefault("data", DATA)
    return usage_cost.calcular(**kw)


class TestCriterioDeAceite:
    def test_2500_km_9_5_kml_diesel_6_20_da_1632(self):
        """Critério da spec, com a conta à vista: 2500/9,5 = 263,16 L × 6,20 = 1.631,58."""
        r = calcular(
            atributos={
                "combustivel": "diesel",
                "consumo_urbano_kml": 9.5,
                "consumo_rodoviario_kml": 9.5,
            },
            km_mes=2500,
            precos={"diesel": 6.20},
        )
        assert r.litros_mes == pytest.approx(263.16, abs=0.01)
        assert r.custo_mes == pytest.approx(1631.58, abs=0.01)
        assert round(r.custo_mes or 0) == 1632

    def test_a_frase_fixa_vem_com_a_fonte_e_a_data(self):
        r = calcular(
            atributos={
                "combustivel": "diesel",
                "consumo_urbano_kml": 9.5,
                "consumo_rodoviario_kml": 9.5,
            },
            km_mes=2500,
            precos={"diesel": 6.20},
            origem_por_campo={"consumo_urbano_kml": "pbe"},
        )
        assert r.frase == (
            "Estimativa de combustível baseada em consumo medido pelo PBE/Inmetro e preços "
            "informados em 09/09/2026. Não inclui seguro, manutenção ou depreciação."
        )

    def test_a_frase_fixa_e_literal_e_diz_o_que_nao_inclui(self):
        for termo in ("seguro", "manutenção", "depreciação"):
            assert termo in usage_cost.FRASE_FIXA
        assert "{fonte}" in usage_cost.FRASE_FIXA
        assert "{data}" in usage_cost.FRASE_FIXA


class TestOCombustivelCerto:
    def test_gasolina_usa_o_preco_da_gasolina(self):
        r = calcular(
            atributos={"combustivel": "gasolina", "consumo_urbano_kml": 7.0},
            km_mes=1000,
            precos={"diesel": 6.20, "gasolina": 6.00},
        )
        assert r.preco_por_litro == 6.00

    def test_sem_o_preco_do_combustivel_do_veiculo_NAO_ha_custo(self):
        """Usar o preço do outro combustível faria a comparação dizer o contrário do posto."""
        r = calcular(
            atributos={"combustivel": "gasolina", "consumo_urbano_kml": 7.0},
            km_mes=1000,
            precos={"diesel": 6.20},
        )
        assert r.custo_mes is None
        assert "preço do gasolina" in r.motivo_sem_custo

    def test_flex_usa_o_preco_da_gasolina_e_isso_esta_declarado(self):
        r = calcular(
            atributos={"combustivel": "flex", "consumo_urbano_kml": 8.0},
            km_mes=1000,
            precos={"gasolina": 6.00},
        )
        assert r.preco_por_litro == 6.00
        assert usage_cost.COMBUSTIVEL_DO_FLEX == "gasolina"

    def test_combustivel_desconhecido_nao_calcula_e_diz_o_valor(self):
        r = calcular(
            atributos={"combustivel": "hidrogenio", "consumo_urbano_kml": 8.0},
            km_mes=1000,
            precos={"gasolina": 6.00},
        )
        assert r.custo_mes is None
        assert "hidrogenio" in r.motivo_sem_custo

    def test_combustivel_ausente_e_dito_como_ausente(self):
        r = calcular(atributos={"consumo_urbano_kml": 8.0}, km_mes=1000, precos={"gasolina": 6.0})
        assert r.custo_mes is None
        assert "ausente" in r.motivo_sem_custo


class TestOrigemDoConsumo:
    def test_a_media_e_a_ponderada_do_pbe_e_nao_50_50(self):
        """55/45 é a ponderação do próprio programa; 50/50 daria um combinado de ninguém."""
        r = usage_cost.consumo_de({"consumo_urbano_kml": 9.7, "consumo_rodoviario_kml": 10.6})
        assert r.valor_kml == pytest.approx(9.7 * 0.55 + 10.6 * 0.45, abs=0.01)
        assert usage_cost.PESO_URBANO + usage_cost.PESO_RODOVIARIO == 1.0

    def test_com_um_ciclo_so_usa_o_que_existe_e_diz_qual(self):
        r = usage_cost.consumo_de({"consumo_urbano_kml": 9.7})
        assert r.valor_kml == 9.7
        assert r.campo == "consumo_urbano_kml"

    def test_o_informado_pelo_vendedor_e_rotulado_como_tal(self):
        r = usage_cost.consumo_de({}, informado_kml=8.0)
        assert r.origem == "informado"
        assert "vendedor" in usage_cost.ROTULO_DA_ORIGEM["informado"]

    def test_a_fonte_da_ficha_tem_precedencia_sobre_o_informado(self):
        """O vendedor digita um palpite; a ficha tem evidência. A evidência ganha."""
        r = usage_cost.consumo_de({"consumo_urbano_kml": 9.7}, informado_kml=15.0)
        assert r.valor_kml == 9.7
        assert r.origem != "informado"

    def test_a_origem_pbe_muda_a_frase(self):
        """ "9,5 km/l" medido e "9,5 km/l" digitado têm o mesmo formato e confiança diferente."""
        medido = calcular(
            atributos={"combustivel": "diesel", "consumo_urbano_kml": 9.5},
            km_mes=1000,
            precos={"diesel": 6.0},
            origem_por_campo={"consumo_urbano_kml": "pbe"},
        )
        digitado = calcular(
            atributos={"combustivel": "diesel"},
            km_mes=1000,
            precos={"diesel": 6.0},
            informado_kml=9.5,
        )
        assert "PBE/Inmetro" in medido.frase
        assert "informado pelo vendedor" in digitado.frase
        assert medido.custo_mes == digitado.custo_mes

    def test_sem_consumo_nenhum_nao_ha_custo(self):
        r = calcular(atributos={"combustivel": "diesel"}, km_mes=1000, precos={"diesel": 6.0})
        assert r.custo_mes is None
        assert "consumo" in r.motivo_sem_custo


class TestAusenciaNaoViraZero:
    def test_sem_km_mes_o_custo_e_None(self):
        """Zero apareceria na tela como "custo zero" — pior que a ausência."""
        r = calcular(
            atributos={"combustivel": "diesel", "consumo_urbano_kml": 9.5},
            km_mes=None,
            precos={"diesel": 6.0},
        )
        assert r.custo_mes is None
        assert r.custo_ano is None
        assert "km por mês" in r.motivo_sem_custo

    def test_km_mes_zero_tambem_nao_calcula(self):
        r = calcular(
            atributos={"combustivel": "diesel", "consumo_urbano_kml": 9.5},
            km_mes=0,
            precos={"diesel": 6.0},
        )
        assert r.custo_mes is None

    def test_o_motivo_lista_TODAS_as_faltas(self):
        """Uma por vez faria o vendedor descobrir a segunda depois de preencher a primeira."""
        r = calcular(atributos={}, km_mes=None, precos={})
        assert "km por mês" in r.motivo_sem_custo
        assert "consumo" in r.motivo_sem_custo
        assert "combustível" in r.motivo_sem_custo


class TestComparacao:
    def diesel(self, consumo: float = 9.5):
        return calcular(
            atributos={"combustivel": "diesel", "consumo_urbano_kml": consumo},
            km_mes=2500,
            precos={"diesel": 6.20},
            rotulo="concorrente diesel",
        )

    def gasolina(self, consumo: float = 7.0):
        return calcular(
            atributos={"combustivel": "gasolina", "consumo_urbano_kml": consumo},
            km_mes=2500,
            precos={"gasolina": 6.00},
            rotulo="Ford gasolina",
        )

    def test_a_diferenca_anual_e_o_numero_que_fecha_a_conversa(self):
        c = usage_cost.comparar(self.gasolina(), self.diesel())
        assert c.diferenca_mes is not None
        assert c.diferenca_ano == pytest.approx((c.diferenca_mes or 0) * 12, abs=0.01)
        assert c.quem_gasta_menos == "concorrente"

    def test_ford_mais_economica_aparece_como_tal(self):
        c = usage_cost.comparar(self.gasolina(consumo=14.0), self.diesel())
        assert c.quem_gasta_menos == "ford"

    def test_sem_um_dos_lados_a_diferenca_e_None_e_nao_zero(self):
        """Zero diria "custam o mesmo", que é uma afirmação."""
        sem = calcular(atributos={"combustivel": "diesel"}, km_mes=2500, precos={"diesel": 6.2})
        c = usage_cost.comparar(self.gasolina(), sem)
        assert c.diferenca_mes is None
        assert c.diferenca_ano is None
        assert "concorrente" in c.motivo_sem_diferenca

    def test_custos_iguais_dao_empate_explicito(self):
        a = self.diesel()
        c = usage_cost.comparar(a, a)
        assert c.diferenca_mes == 0
        assert c.quem_gasta_menos == "empate"


class TestSerializacao:
    def test_o_dicionario_leva_a_origem_e_a_frase(self):
        r = calcular(
            atributos={"combustivel": "diesel", "consumo_urbano_kml": 9.5},
            km_mes=2500,
            precos={"diesel": 6.20},
            origem_por_campo={"consumo_urbano_kml": "pbe"},
        )
        dados = r.to_dict()
        assert dados["consumo"]["origem"] == "pbe"
        assert dados["consumo"]["rotulo_da_origem"] == "medido pelo PBE/Inmetro"
        assert dados["frase"]
        assert dados["custo_ano"] == pytest.approx((dados["custo_mes"] or 0) * 12, abs=0.01)
