"""WP-26 — Customer Need Engine: pesos, notas, dimensões e aderência.

A nota da spec é **"nunca penalizar dado faltante em silêncio"**, e é o que a maior parte
destes testes cerca. As três formas de violá-la:

* tirar o campo só do lado que não tem (o outro ganharia por ter sido melhor coletado);
* diluir a dimensão insuficiente no total (falta de dado viraria nota baixa);
* devolver a aderência sem dizer sobre quanto do peso ela foi calculada.

O outro grupo de testes protege o **rótulo obrigatório** de `docs/12` §6.2: sem ele,
"aderência 8,4" se lê como nota de qualidade, e não é — trocar de perfil muda o número sem
nada mudar no carro.
"""

from __future__ import annotations

import pytest

from pipeline.fit import dimensions, engine, ranges
from pipeline.fit.engine import NeedsProfile

FAIXAS = ranges.Faixas(
    versao="teste",
    por_campo={
        "potencia_cv": ranges.Faixa("potencia_cv", 200.0, 400.0, 4, "teste"),
        "torque_nm": ranges.Faixa("torque_nm", 500.0, 600.0, 4, "teste"),
        "aceleracao_0_100_s": ranges.Faixa("aceleracao_0_100_s", 5.0, 11.0, 3, "teste"),
        "capacidade_carga_kg": ranges.Faixa("capacidade_carga_kg", 600.0, 1100.0, 3, "teste"),
        "consumo_urbano_kml": ranges.Faixa("consumo_urbano_kml", 7.0, 11.0, 3, "teste"),
        "consumo_rodoviario_kml": ranges.Faixa("consumo_rodoviario_kml", 8.0, 12.0, 3, "teste"),
        "preco_sugerido_brl": ranges.Faixa("preco_sugerido_brl", 300000.0, 500000.0, 3, "teste"),
        # De propósito insuficiente: exercita a nota neutra e a régua do par.
        "tanque_l": ranges.Faixa("tanque_l", 80.0, 80.0, 1, "teste", insuficiente=True),
    },
)


def perfil(**kw) -> NeedsProfile:
    kw.setdefault("prioridades_rank", ["economia", "capacidade", "seguranca"])
    return NeedsProfile(**kw)


def avaliar(ford: dict, conc: dict, p: NeedsProfile | None = None):
    return engine.avaliar(ford, conc, p or perfil(), faixas=FAIXAS)


class TestPesos:
    def test_criterio_de_aceite_35_25_20_e_o_resto_zero(self):
        """Critério: ranking [economia, capacidade, seguranca] → 35/25/20, demais 0."""
        pesos = engine.pesos_de(perfil())
        assert pesos["economia"] == 35
        assert pesos["capacidade"] == 25
        assert pesos["seguranca"] == 20
        assert pesos["desempenho"] == 0
        assert pesos["preco"] == 0

    def test_toda_dimensao_aparece_nos_pesos_inclusive_com_zero(self):
        """A tela exibe os pesos; dimensão ausente do mapa não se distingue de peso zero."""
        pesos = engine.pesos_de(perfil())
        assert set(pesos) == set(dimensions.carregar().dimensoes)

    def test_os_cinco_pesos_somam_100(self):
        assert sum(dimensions.carregar().pesos_por_rank) == 100

    def test_ranking_completo_usa_os_cinco_e_zera_o_resto(self):
        p = perfil(
            prioridades_rank=[
                "economia",
                "capacidade",
                "seguranca",
                "desempenho",
                "conforto_tecnologia",
                "off_road",
                "preco",
            ]
        )
        pesos = engine.pesos_de(p)
        assert [pesos[d] for d in p.prioridades_rank] == [35, 25, 20, 12, 8, 0, 0]

    def test_override_soma_100_e_aceito(self):
        p = perfil(pesos_override={"economia": 60, "preco": 40})
        pesos = engine.pesos_de(p)
        assert pesos["economia"] == 60
        assert pesos["preco"] == 40
        assert pesos["capacidade"] == 0

    def test_criterio_de_aceite_override_que_nao_soma_100_e_recusado(self):
        """Critério: "override soma 100 ou 422". O erro diz **quanto** somou."""
        with pytest.raises(ValueError, match="soma 93"):
            perfil(pesos_override={"economia": 60, "preco": 33})

    def test_override_com_dimensao_desconhecida_e_recusado(self):
        with pytest.raises(ValueError, match="desconhecida"):
            perfil(pesos_override={"inventada": 100})

    def test_prioridade_desconhecida_e_recusada_com_a_lista(self):
        with pytest.raises(ValueError, match="Válidas"):
            perfil(prioridades_rank=["preco_baixo"])

    def test_prioridade_repetida_e_recusada(self):
        with pytest.raises(ValueError, match="repetida"):
            perfil(prioridades_rank=["economia", "economia"])

    def test_uso_desconhecido_e_recusado_com_a_lista(self):
        with pytest.raises(ValueError, match="Válidos"):
            perfil(uso=["corrida"])

    def test_o_perfil_nao_aceita_campo_extra(self):
        """Anônimo é requisito: `extra="forbid"` impede dado pessoal de entrar de carona."""
        with pytest.raises(ValueError):
            NeedsProfile(nome_do_cliente="João")  # type: ignore[call-arg]


class TestNotaDeCampo:
    def campo(self, nome: str, tipo: str, **kw) -> dimensions.CampoDaDimensao:
        return dimensions.CampoDaDimensao(campo=nome, tipo=tipo, **kw)

    def test_numerico_escala_dentro_da_faixa(self):
        c = self.campo("potencia_cv", "numerico", direcao="maior")
        assert engine.nota_de_campo(c, 400, faixas=FAIXAS).nota == 10.0
        assert engine.nota_de_campo(c, 200, faixas=FAIXAS).nota == 0.0
        assert engine.nota_de_campo(c, 300, faixas=FAIXAS).nota == 5.0

    def test_direcao_menor_inverte_a_escala(self):
        c = self.campo("aceleracao_0_100_s", "numerico", direcao="menor")
        assert engine.nota_de_campo(c, 5.0, faixas=FAIXAS).nota == 10.0
        assert engine.nota_de_campo(c, 11.0, faixas=FAIXAS).nota == 0.0

    def test_valor_fora_da_faixa_satura_em_vez_de_extrapolar(self):
        """Nota 12 é número que a tela não desenha e que a faixa não sustenta."""
        c = self.campo("potencia_cv", "numerico", direcao="maior")
        assert engine.nota_de_campo(c, 600, faixas=FAIXAS).nota == 10.0
        assert engine.nota_de_campo(c, 50, faixas=FAIXAS).nota == 0.0

    def test_faixa_insuficiente_da_nota_neutra_COM_motivo(self):
        c = self.campo("tanque_l", "numerico", direcao="maior")
        nota = engine.nota_de_campo(c, 80, faixas=FAIXAS)
        assert nota.nota == ranges.NOTA_NEUTRA
        assert "insuficiente" in nota.motivo

    def test_booleano_e_zero_ou_dez(self):
        c = self.campo("reduzida", "booleano")
        assert engine.nota_de_campo(c, True, faixas=FAIXAS).nota == 10.0
        assert engine.nota_de_campo(c, False, faixas=FAIXAS).nota == 0.0

    def test_False_nao_e_ausencia_de_valor(self):
        """ "Não tem reduzida" é informação; `nao_encontrado` é a falta dela."""
        c = self.campo("reduzida", "booleano")
        assert engine.nota_de_campo(c, False, faixas=FAIXAS).tem_nota is True
        assert engine.nota_de_campo(c, None, faixas=FAIXAS).tem_nota is False

    def test_contagem_normaliza_pelo_teto(self):
        c = self.campo("modos_conducao", "contagem")
        assert engine.nota_de_campo(c, ["a"] * 7, faixas=FAIXAS).nota == 10.0
        assert engine.nota_de_campo(c, ["a"] * 3, faixas=FAIXAS).nota == pytest.approx(
            4.29, abs=0.01
        )

    def test_contagem_acima_do_teto_nao_passa_de_dez(self):
        c = self.campo("modos_conducao", "contagem")
        assert engine.nota_de_campo(c, ["a"] * 12, faixas=FAIXAS).nota == 10.0

    def test_ordinal_usa_a_ordem_declarada(self):
        """A ordem do YAML está em slug; a ficha guarda a canônica de exibição.

        `"Matrix LED"` é o que o banco tem, `matrix` é o que o `dimensions.yaml` escreve.
        Comparar os dois crus fazia **todo** valor real cair em "fora da ordem" e receber
        nota neutra: a escala ordinal inteira ficava inerte, sem erro nenhum aparecer. A
        comparação passa pela ontologia dos dois lados.
        """
        c = self.campo("farois_tipo", "ordinal", ordem=("halogeno", "led", "full_led", "matrix"))
        assert engine.nota_de_campo(c, "Matrix LED", faixas=FAIXAS).nota == 10.0
        assert engine.nota_de_campo(c, "Full LED", faixas=FAIXAS).nota == pytest.approx(6.67)
        assert engine.nota_de_campo(c, "LED", faixas=FAIXAS).nota == pytest.approx(3.33)
        assert engine.nota_de_campo(c, "halógeno", faixas=FAIXAS).nota == 0.0

    def test_ordinal_generico_demais_fica_neutro_com_o_motivo(self):
        """`"4WD"` diz tração nas quatro rodas sem dizer **qual**.

        Ranqueá-lo como "sob demanda" seria adivinhar o tipo; como 4x2, seria errado. Nota
        neutra com o motivo é o que a informação sustenta — e é o valor que a ficha da
        Raptor realmente tem.
        """
        c = self.campo("tipo_tracao", "ordinal", ordem=("4x2", "4x4_sob_demanda", "4x4_permanente"))
        nota = engine.nota_de_campo(c, "4WD", faixas=FAIXAS)
        assert nota.nota == ranges.NOTA_NEUTRA
        assert nota.motivo == engine.MOTIVO_SEM_ORDEM
        assert engine.nota_de_campo(c, "4x4 permanente", faixas=FAIXAS).nota == 10.0

    def test_ordinal_com_valor_fora_da_ordem_e_neutro_e_nao_zero(self):
        """Zero afirmaria "o pior da escala"; o que se sabe é que não reconhecemos o valor."""
        c = self.campo("farois_tipo", "ordinal", ordem=("halogeno", "led"))
        nota = engine.nota_de_campo(c, "laser", faixas=FAIXAS)
        assert nota.nota == ranges.NOTA_NEUTRA
        assert nota.motivo == engine.MOTIVO_SEM_ORDEM

    def test_presenca_de_termo(self):
        c = self.campo("amortecedores", "presenca_de_termo", termos=("fox", "live valve"))
        alta = engine.nota_de_campo(c, 'Live Valve FOX Racing 2.5"', faixas=FAIXAS)
        assert alta.nota == 10.0
        assert "fox" in alta.motivo
        assert engine.nota_de_campo(c, "hidráulico convencional", faixas=FAIXAS).nota == 0.0


class TestNotaDoPar:
    """A régua do par, quando o segmento não tem faixa. Ver `notas_do_par`."""

    def campo(self, nome: str, direcao: str = "maior") -> dimensions.CampoDaDimensao:
        return dimensions.CampoDaDimensao(campo=nome, tipo="numerico", direcao=direcao)

    def test_faixa_insuficiente_mas_dois_valores_NAO_vira_empate(self):
        """A regressão que este teste tranca.

        A primeira versão dava nota neutra aos dois quando a faixa do segmento era
        insuficiente — e com 9,7 contra 7,2 km/l a ordem é **conhecida**. Devolver 5,0 para
        ambos descartava informação existente, que é o mesmo erro que o produto combate na
        matriz de paridade.
        """
        c = self.campo("tanque_l")
        f, cc = engine.notas_do_par(c, 100, 70, faixas=FAIXAS)
        assert f.nota is not None and cc.nota is not None
        assert f.nota > cc.nota

    def test_a_nota_do_par_diz_que_e_relativa_ao_par(self):
        c = self.campo("tanque_l")
        f, _ = engine.notas_do_par(c, 100, 70, faixas=FAIXAS)
        assert "dois veículos comparados" in f.motivo

    def test_diferenca_pequena_da_notas_proximas(self):
        """9,7 contra 9,6 não pode virar 10 e 0."""
        c = self.campo("tanque_l")
        f, cc = engine.notas_do_par(c, 9.7, 9.6, faixas=FAIXAS)
        assert f.nota is not None and cc.nota is not None
        assert abs((f.nota or 0) - (cc.nota or 0)) < 2

    def test_diferenca_grande_satura(self):
        c = self.campo("tanque_l")
        f, cc = engine.notas_do_par(c, 100, 40, faixas=FAIXAS)
        assert f.nota == 10.0
        assert cc.nota == 0.0

    def test_valores_iguais_dao_neutro_nos_dois(self):
        c = self.campo("tanque_l")
        f, cc = engine.notas_do_par(c, 80, 80, faixas=FAIXAS)
        assert f.nota == cc.nota == ranges.NOTA_NEUTRA

    def test_faixa_do_segmento_tem_precedencia_sobre_o_par(self):
        """Com faixa boa, a nota fica comparável entre consultas."""
        c = self.campo("potencia_cv")
        f, cc = engine.notas_do_par(c, 400, 200, faixas=FAIXAS)
        assert (f.nota, cc.nota) == (10.0, 0.0)
        assert "faixa 200..400" in (f.motivo or "")

    def test_direcao_menor_no_par(self):
        c = self.campo("tanque_l", direcao="menor")
        f, cc = engine.notas_do_par(c, 100, 40, faixas=FAIXAS)
        assert f.nota == 0.0
        assert cc.nota == 10.0


class TestDadoFaltante:
    def test_criterio_de_aceite_campo_faltando_sai_dos_DOIS(self):
        """Critério: campo `nao_encontrado` num veículo não entra para nenhum dos dois."""
        ford = {"potencia_cv": 397, "torque_nm": 583, "aceleracao_0_100_s": 5.8}
        conc = {"potencia_cv": None, "torque_nm": 500, "aceleracao_0_100_s": 10.7}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["desempenho"]), faixas=FAIXAS)
        desempenho = next(d for d in r.dimensoes if d.id == "desempenho")
        assert "potencia_cv" not in desempenho.campos_usados
        assert any(c["campo"] == "potencia_cv" for c in desempenho.campos_sem_dado)

    def test_o_motivo_diz_de_qual_lado_falta(self):
        ford = {"potencia_cv": 397, "torque_nm": 583, "aceleracao_0_100_s": 5.8}
        conc = {"potencia_cv": None, "torque_nm": 500, "aceleracao_0_100_s": 10.7}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["desempenho"]), faixas=FAIXAS)
        desempenho = next(d for d in r.dimensoes if d.id == "desempenho")
        motivo = next(c["motivo"] for c in desempenho.campos_sem_dado)
        assert "concorrente" in motivo
        assert "Ford" not in motivo

    def test_dado_faltante_nao_beneficia_quem_tem_o_dado(self):
        """O erro que a regra impede: premiar a própria cobertura em vez de medir o carro.

        Se o campo saísse só do lado que falta, a Ford ganharia `desempenho` por ter três
        valores contra dois — sem que o carro dela fosse melhor em nada.
        """
        ford = {"potencia_cv": 250, "torque_nm": 520, "aceleracao_0_100_s": 9.0}
        conc = {"potencia_cv": None, "torque_nm": 520, "aceleracao_0_100_s": 9.0}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["desempenho"]), faixas=FAIXAS)
        desempenho = next(d for d in r.dimensoes if d.id == "desempenho")
        assert desempenho.nota_ford == desempenho.nota_concorrente

    def test_parecer_item7_desempenho_sem_aceleracao_do_concorrente_nao_infla_a_ford(self):
        """O caso do parecer de uso de 12/09/2026, fixado com números.

        Relato: "dimensão com dado faltante em um dos lados NUNCA recebe 0,0". O avaliador
        viu a Hilux com nota quase zero em `desempenho` — a mesma dimensão em que faltava a
        aceleração dela — e leu as duas coisas como causa e efeito.

        Este teste prova que **não são**: com potência e torque IGUAIS dos dois lados e a
        aceleração só do lado Ford, as notas empatam. Qualquer volta ao comportamento
        errado (contar a aceleração só de quem a tem) faz `nota_ford > nota_concorrente` e
        quebra este teste na hora.

        A causa real do quase-zero que ele viu está em `test_nota_no_piso_da_faixa_*`,
        logo abaixo: a Hilux é o **mínimo da amostra** em potência.
        """
        ford = {"potencia_cv": 300, "torque_nm": 550, "aceleracao_0_100_s": 5.8}
        conc = {"potencia_cv": 300, "torque_nm": 550, "aceleracao_0_100_s": None}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["desempenho"]), faixas=FAIXAS)
        d = next(x for x in r.dimensoes if x.id == "desempenho")

        assert d.campos_usados == ["potencia_cv", "torque_nm"]
        assert "aceleracao_0_100_s" not in d.campos_usados
        assert d.insuficiente is False  # 2 de 3 = 67% > 50%
        assert d.nota_ford == d.nota_concorrente, "a Ford ganhou por ter o dado, não pelo carro"
        assert d.nota_concorrente != 0.0
        assert "desempenho" not in r.vence_em["ford"]

    def test_nota_no_piso_da_faixa_vem_com_o_motivo_escrito(self):
        """Uma nota perto de zero é **posição na amostra**, e a tela tem de dizer isso.

        O concorrente do parecer tem 204 cv — que é o mínimo dos quatro veículos da
        amostra —, e a escala linear satura em 0 no piso. O número está certo; lido ao
        lado de um 10,0, ele comunica "este carro não tem desempenho nenhum", que é falso
        e é exatamente o tipo de exagero que `docs/12` §3 proíbe.

        A correção não é mexer no número (saturar é decisão declarada): é **nomear a
        régua**, como o projeto faz com todo percentual.
        """
        ford = {"potencia_cv": 397, "torque_nm": 583}
        conc = {"potencia_cv": 204, "torque_nm": 499}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["desempenho"]), faixas=FAIXAS)
        d = next(x for x in r.dimensoes if x.id == "desempenho")

        assert d.nota_concorrente is not None and d.nota_concorrente < 1.0
        assert d.nota_no_piso == ["concorrente"], d.nota_no_piso
        assert d.aviso_da_escala, "nota no piso sem explicação é um exagero sem ressalva"
        assert "menor" in d.aviso_da_escala.lower()
        # E o aviso diz o tamanho da amostra: quem lê precisa saber que são poucos carros.
        assert "4" in d.aviso_da_escala

    def test_nota_alta_sem_saturacao_nao_ganha_aviso(self):
        """Contra-teste: o aviso é para o piso, não para toda nota baixa."""
        ford = {"potencia_cv": 300, "torque_nm": 550}
        conc = {"potencia_cv": 250, "torque_nm": 520}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["desempenho"]), faixas=FAIXAS)
        d = next(x for x in r.dimensoes if x.id == "desempenho")
        assert d.nota_no_piso == []
        assert d.aviso_da_escala is None

    def test_criterio_de_aceite_cobertura_abaixo_de_50_e_insuficiente_e_excluida(self):
        """Critério: dimensão com cobertura < 50% → `insuficiente=true`, fora do total."""
        # `desempenho` tem 3 campos; com 1 só comparável a cobertura é 33%.
        ford = {"potencia_cv": 397, "torque_nm": 583, "aceleracao_0_100_s": 5.8}
        conc = {"potencia_cv": 204, "torque_nm": None, "aceleracao_0_100_s": None}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["desempenho"]), faixas=FAIXAS)
        desempenho = next(d for d in r.dimensoes if d.id == "desempenho")
        assert desempenho.insuficiente is True
        assert desempenho.cobertura is not None and desempenho.cobertura < 0.5
        assert "excluída do total" in desempenho.aviso
        # E o total não considerou aquele peso.
        assert r.peso_considerado == 0
        assert r.aderencia_ford is None

    def test_o_aviso_nao_mostra_nome_de_campo_do_banco_nem_asterisco(self):
        """QA-BUG-13: o aviso saía com `torque_nm, aceleracao_0_100_s` e com `**` literal.

        Este texto aparece na tela do **vendedor**, no Showroom, e é o mesmo que sai no
        documento do cliente. Medido em 11/09/2026, na comparação Ranger Limited ×
        Hilux SRX Plus: "dimensão **excluída do total**. Sem dado comparável em:
        reduzida, bloqueio_diferencial, pneus_tipo, amortecedores." — asterisco de
        Markdown que a tela não interpreta, e quatro nomes de coluna de banco.
        """
        ford = {"potencia_cv": 397, "torque_nm": 583, "aceleracao_0_100_s": 5.8}
        conc = {"potencia_cv": 204, "torque_nm": None, "aceleracao_0_100_s": None}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["desempenho"]), faixas=FAIXAS)
        desempenho = next(d for d in r.dimensoes if d.id == "desempenho")

        assert "**" not in desempenho.aviso
        assert "_" not in desempenho.aviso
        assert "excluída do total" in desempenho.aviso
        assert "torque nm" in desempenho.aviso
        assert "aceleracao 0 100 s" in desempenho.aviso

    def test_a_dimensao_insuficiente_com_peso_gera_aviso_no_topo(self):
        ford = {"potencia_cv": 397, "torque_nm": 583, "aceleracao_0_100_s": 5.8}
        conc = {"potencia_cv": 204, "torque_nm": None, "aceleracao_0_100_s": None}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["desempenho"]), faixas=FAIXAS)
        assert any("ficou fora do total" in a for a in r.avisos)

    def test_o_total_divide_pelo_peso_CONSIDERADO_e_nao_por_100(self):
        """Dividir por 100 diluiria a nota pelo peso das dimensões excluídas.

        Isso transformaria falta de dado em nota baixa — a penalização silenciosa que a
        regra proíbe. Com só `desempenho` (peso 35) comparável e nota 10, a aderência é
        **10,0**, não 3,5.
        """
        ford = {"potencia_cv": 400, "torque_nm": 600, "aceleracao_0_100_s": 5.0}
        conc = {"potencia_cv": 200, "torque_nm": 500, "aceleracao_0_100_s": 11.0}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["desempenho"]), faixas=FAIXAS)
        assert r.peso_considerado == 35
        assert r.aderencia_ford == 10.0
        assert r.aderencia_concorrente == 0.0
        assert any("35% do peso" in a for a in r.avisos)

    def test_sem_nenhuma_dimensao_comparavel_a_aderencia_e_None_e_nao_zero(self):
        r = engine.avaliar({}, {}, perfil(), faixas=FAIXAS)
        assert r.aderencia_ford is None
        assert r.aderencia_concorrente is None
        assert any("seria invenção" in a for a in r.avisos)


class TestVenceEm:
    def test_criterio_de_aceite_o_concorrente_vence_economia_com_consumo_maior(self):
        """Critério: `vence_em.concorrente` contém "economia" quando o consumo é maior."""
        ford = {"consumo_urbano_kml": 7.2, "consumo_rodoviario_kml": 9.0}
        conc = {"consumo_urbano_kml": 9.7, "consumo_rodoviario_kml": 10.6}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["economia"]), faixas=FAIXAS)
        assert "economia" in r.vence_em["concorrente"]
        assert "economia" not in r.vence_em["ford"]

    def test_a_decomposicao_lista_os_campos_usados(self):
        """Critério: "a decomposição lista os campos usados"."""
        ford = {"consumo_urbano_kml": 7.2, "consumo_rodoviario_kml": 9.0}
        conc = {"consumo_urbano_kml": 9.7, "consumo_rodoviario_kml": 10.6}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["economia"]), faixas=FAIXAS)
        economia = next(d for d in r.dimensoes if d.id == "economia")
        assert set(economia.campos_usados) == {"consumo_urbano_kml", "consumo_rodoviario_kml"}
        assert len(economia.detalhe_ford) == 2
        assert all(n.motivo for n in economia.detalhe_ford)

    def test_dimensao_insuficiente_nao_e_vitoria_de_ninguem(self):
        """Listá-la daria ao vendedor um argumento sem base."""
        ford = {"potencia_cv": 397, "torque_nm": 583, "aceleracao_0_100_s": 5.8}
        conc = {"potencia_cv": 204, "torque_nm": None, "aceleracao_0_100_s": None}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["desempenho"]), faixas=FAIXAS)
        assert "desempenho" not in r.vence_em["ford"]
        assert "desempenho" not in r.vence_em["concorrente"]

    def test_empate_nao_entra_em_nenhum_dos_dois(self):
        ford = {"consumo_urbano_kml": 9.0, "consumo_rodoviario_kml": 10.0}
        conc = dict(ford)
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["economia"]), faixas=FAIXAS)
        assert "economia" not in r.vence_em["ford"]
        assert "economia" not in r.vence_em["concorrente"]

    def test_vence_em_conta_dimensao_com_peso_zero(self):
        """O peso zero afeta o total, **não** a leitura de quem é melhor no campo.

        Um cliente que não priorizou desempenho ainda quer saber que a Ford ganha nele —
        e o argumentário da WP-27 depende dessa lista.
        """
        ford = {"potencia_cv": 400, "torque_nm": 600, "aceleracao_0_100_s": 5.0}
        conc = {"potencia_cv": 200, "torque_nm": 500, "aceleracao_0_100_s": 11.0}
        r = engine.avaliar(ford, conc, perfil(prioridades_rank=["economia"]), faixas=FAIXAS)
        assert engine.pesos_de(perfil(prioridades_rank=["economia"]))["desempenho"] == 0
        assert "desempenho" in r.vence_em["ford"]


class TestRotuloObrigatorio:
    def test_criterio_de_aceite_o_rotulo_esta_na_resposta(self):
        """Critério: a resposta contém "Aderência ao perfil informado — não é um ranking
        de qualidade"."""
        r = avaliar({"potencia_cv": 397}, {"potencia_cv": 204})
        assert r.rotulo == "Aderência ao perfil informado — não é um ranking de qualidade"
        assert r.to_dict()["rotulo"] == r.rotulo

    def test_o_yaml_sem_rotulo_e_recusado(self, tmp_path):
        arquivo = tmp_path / "d.yaml"
        arquivo.write_text(
            "versao: t\npesos_por_rank: [100]\ndimensoes:\n"
            "  economia:\n    campos:\n      - campo: consumo_urbano_kml\n"
            "        tipo: numerico\n        direcao: maior\n",
            encoding="utf-8",
        )
        dimensions.carregar.cache_clear()
        with pytest.raises(dimensions.DimensaoInvalida, match="rotulo_obrigatorio"):
            dimensions.carregar(str(arquivo))
        dimensions.carregar.cache_clear()

    def test_as_versoes_das_reguas_viajam_na_resposta(self):
        """Aderência calculada hoje não se confunde com uma sob outra tabela."""
        r = avaliar({"potencia_cv": 397}, {"potencia_cv": 204})
        assert r.versao_das_dimensoes == dimensions.carregar().versao
        assert r.versao_das_faixas == "teste"


class TestDimensionsYaml:
    def test_as_sete_dimensoes_de_docs_12(self):
        assert set(dimensions.carregar().dimensoes) == {
            "economia",
            "capacidade",
            "seguranca",
            "desempenho",
            "off_road",
            "conforto_tecnologia",
            "preco",
        }

    def test_todo_campo_existe_no_schema_canonico(self):
        from pipeline.schema import GRUPOS

        canonicos = {c for campos in GRUPOS.values() for c in campos}
        for dimensao in dimensions.carregar().dimensoes.values():
            for campo in dimensao.campos:
                assert campo.campo in canonicos, campo.campo

    def test_campo_numerico_sem_direcao_e_recusado(self, tmp_path):
        arquivo = tmp_path / "d.yaml"
        arquivo.write_text(
            "versao: t\npesos_por_rank: [100]\nrotulo_obrigatorio: x\ndimensoes:\n"
            "  economia:\n    campos:\n      - campo: consumo_urbano_kml\n"
            "        tipo: numerico\n",
            encoding="utf-8",
        )
        dimensions.carregar.cache_clear()
        with pytest.raises(dimensions.DimensaoInvalida, match="direcao"):
            dimensions.carregar(str(arquivo))
        dimensions.carregar.cache_clear()

    def test_ordinal_sem_ordem_e_recusado(self, tmp_path):
        arquivo = tmp_path / "d.yaml"
        arquivo.write_text(
            "versao: t\npesos_por_rank: [100]\nrotulo_obrigatorio: x\ndimensoes:\n"
            "  exterior:\n    campos:\n      - campo: farois_tipo\n        tipo: ordinal\n",
            encoding="utf-8",
        )
        dimensions.carregar.cache_clear()
        with pytest.raises(dimensions.DimensaoInvalida, match="ordinal"):
            dimensions.carregar(str(arquivo))
        dimensions.carregar.cache_clear()

    def test_peso_que_nao_soma_100_e_recusado(self, tmp_path):
        arquivo = tmp_path / "d.yaml"
        arquivo.write_text(
            "versao: t\npesos_por_rank: [50, 30]\nrotulo_obrigatorio: x\ndimensoes:\n"
            "  economia:\n    campos:\n      - campo: consumo_urbano_kml\n"
            "        tipo: numerico\n        direcao: maior\n",
            encoding="utf-8",
        )
        dimensions.carregar.cache_clear()
        with pytest.raises(dimensions.DimensaoInvalida, match="soma 80"):
            dimensions.carregar(str(arquivo))
        dimensions.carregar.cache_clear()

    def test_campo_fora_do_schema_e_recusado(self, tmp_path):
        arquivo = tmp_path / "d.yaml"
        arquivo.write_text(
            "versao: t\npesos_por_rank: [100]\nrotulo_obrigatorio: x\ndimensoes:\n"
            "  economia:\n    campos:\n      - campo: inventado_kml\n"
            "        tipo: numerico\n        direcao: maior\n",
            encoding="utf-8",
        )
        dimensions.carregar.cache_clear()
        with pytest.raises(dimensions.DimensaoInvalida, match="schema canônico"):
            dimensions.carregar(str(arquivo))
        dimensions.carregar.cache_clear()


class TestFaixas:
    def test_faixa_com_um_valor_e_insuficiente(self):
        faixas = ranges.calcular(incluir_banco=False)
        for faixa in faixas.por_campo.values():
            if faixa.amostras < ranges.MINIMO_DE_AMOSTRAS:
                assert faixa.insuficiente is True

    def test_toda_faixa_registra_a_procedencia(self):
        """Sem `de_onde`, a nota não é auditável: ninguém sabe o que formou a régua."""
        for faixa in ranges.calcular(incluir_banco=False).por_campo.values():
            assert faixa.de_onde

    def test_as_faixas_vem_do_gabarito_e_nao_de_constante(self):
        faixas = ranges.calcular(incluir_banco=False)
        potencia = faixas.de("potencia_cv")
        assert potencia is not None
        assert potencia.minimo == 204.0  # S10 High Country, do gabarito
        assert potencia.maximo == 397.0  # Raptor, do gabarito
        assert "gabarito" in potencia.de_onde

    def test_o_arquivo_versionado_carrega(self):
        faixas = ranges.carregar()
        assert faixas.versao
        assert faixas.por_campo

    def test_campo_sem_valor_nenhum_fica_declarado_e_insuficiente(self):
        """A faixa vazia existe para o motor dizer "sem faixa" em vez de dividir por zero."""
        faixas = ranges.calcular(incluir_banco=False)
        vazia = [f for f in faixas.por_campo.values() if f.amostras == 0]
        assert all(f.insuficiente for f in vazia)
        assert all("nenhum valor observado" in f.de_onde for f in vazia)
