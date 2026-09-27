"""WP-34 — o Materiality Engine: as regras, os pesos e as quatro faixas.

Os dois critérios de aceite de regra estão aqui: **|Δ%| < 1% é RUIDO** (o preço FIPE da
Amarok) e **entrar na faixa de ±5% do par Ford é ALTA com `price_band_entry`** (a Hilux
baixando de preço).

O que o resto dos testes guarda é a auditabilidade: a faixa **nunca** viaja sem
`rules_fired`, todo peso tem descrição, e o YAML recusa regra que o motor não sabe avaliar
— porque uma regra ignorada em silêncio é uma linha de configuração que mente.
"""

from __future__ import annotations

import pytest

from pipeline.materiality import engine as m


def ctx(**kw) -> m.Contexto:
    return m.Contexto(**kw)


class TestCriteriosDeAceite:
    def test_delta_abaixo_de_1_pct_e_RUIDO(self):
        """Critério: alerta de preço FIPE com |Δ%| < 1% → `RUIDO`.

        O caso é o da Amarok: a tabela FIPE varia meio por cento de um mês para o outro sem
        nenhuma decisão comercial atrás.
        """
        r = m.avaliar(
            ctx(
                campo="preco_fipe_brl",
                antes=294378,
                depois=296000,
                delta_pct=0.55,
                dimensoes_afetadas=("preco", "revenda"),
            )
        )
        assert r.faixa == m.RUIDO
        assert "ruido_de_tabela" in [x.id for x in r.rules_fired]

    def test_o_veto_do_ruido_vence_a_soma(self):
        """A regressão que este teste tranca.

        Sem o veto, o peso da dimensão (+20) levava a variação de 0,55% para `BAIXA`, e a
        regra que existe para não interromper ninguém por arredondamento ficava inerte
        exatamente no caso que a motivou. `rules_fired` mostra as duas regras, e a faixa é
        `RUIDO` — a conta fica visível, a decisão é do veto.
        """
        r = m.avaliar(ctx(campo="preco_fipe_brl", delta_pct=0.55, dimensoes_afetadas=("preco",)))
        assert r.faixa == m.RUIDO
        assert r.pontos > 0
        assert {"ruido_de_tabela", "dimensao_de_peso_alto"} <= {x.id for x in r.rules_fired}

    def test_entrar_na_faixa_de_preco_e_ALTA_com_price_band_entry(self):
        """Critério: preço caindo para dentro de ±5% da Ranger comparável → `ALTA`."""
        r = m.avaliar(
            ctx(
                campo="preco_sugerido_brl",
                antes=420000,
                depois=395000,
                delta_pct=-5.95,
                dimensoes_afetadas=("preco",),
                preco_ford_comparavel=390000,
            )
        )
        assert r.faixa == m.ALTA
        assert "price_band_entry" in [x.id for x in r.rules_fired]

    def test_o_alerta_simulado_diz_que_a_cadeia_e_hipotese(self):
        """Critério: `is_simulated=true` → a cadeia diz "hipótese"."""
        r = m.avaliar(ctx(campo="preco_sugerido_brl", delta_pct=-8.0, is_simulated=True))
        assert r.is_simulated is True
        assert "SIMULAÇÃO" in r.nota_de_hipotese
        assert "hipótese" in r.nota_de_hipotese


class TestAFaixaNuncaVemSozinha:
    def test_o_dicionario_sempre_leva_as_regras(self):
        """ "ALTA" sozinho é oráculo; "ALTA porque X (40) + Y (45)" é afirmação."""
        dados = m.avaliar(ctx(campo="preco_sugerido_brl", delta_pct=-8.0)).to_dict()
        assert "materiality" in dados
        assert "rules_fired" in dados
        assert dados["rules_fired"]
        assert all(r["descricao"] for r in dados["rules_fired"])

    def test_cada_regra_disparada_traz_o_peso_e_o_detalhe(self):
        r = m.avaliar(ctx(campo="preco_sugerido_brl", delta_pct=-8.0))
        regra = next(x for x in r.rules_fired if x.id == "magnitude_alta")
        assert regra.peso == 45
        assert "8.00%" in regra.detalhe

    def test_a_versao_das_regras_viaja_na_resposta(self):
        """Leitura feita sob a régua de setembro não se confunde com a de outubro."""
        r = m.avaliar(ctx(delta_pct=-8.0))
        assert r.versao_das_regras == m.carregar().versao

    def test_a_nota_dos_pesos_acompanha_a_resposta(self):
        """Quem lê a nota tem de ler a ressalva de que os pesos são escolha, não lei.

        A frase deixou de citar `pipeline/materiality/rules.yaml` em 12/09/2026: o caminho
        do arquivo não diz nada a quem vende picape, e o que a ressalva precisa comunicar é
        que o peso é decisão declarada — e ajustável.
        """
        r = m.avaliar(ctx(delta_pct=-8.0))
        assert "escolha declarada" in r.nota_de_hipotese
        assert "ajustad" in r.nota_de_hipotese
        assert "yaml" not in r.nota_de_hipotese.lower()

    def test_todas_as_faixas_tem_significado(self):
        for faixa in m.carregar().faixas:
            assert len(faixa.significado) > 40, faixa.nome


class TestMagnitude:
    @pytest.mark.parametrize(
        "pct,esperado",
        [
            (0.5, m.RUIDO),
            (1.5, m.BAIXA),
            (3.0, m.MEDIA),
            (8.0, m.ALTA),
        ],
    )
    def test_as_quatro_faixas_por_magnitude_pura(self, pct, esperado):
        """Sem dimensão, sem par, sem flip: só a magnitude decide."""
        assert m.avaliar(ctx(delta_pct=pct)).faixa == esperado

    def test_o_sinal_do_delta_nao_muda_a_magnitude(self):
        """Cair 8% e subir 8% importam igual — o **sentido** é do impacto (WP-25)."""
        assert m.avaliar(ctx(delta_pct=8.0)).pontos == m.avaliar(ctx(delta_pct=-8.0)).pontos

    def test_sem_delta_nenhuma_regra_de_magnitude_dispara(self):
        """Alerta de campo de texto não tem Δ%, e inventar um seria pior que não ter."""
        r = m.avaliar(ctx(campo="farois_tipo", antes="LED", depois="Matrix LED"))
        assert not [x for x in r.rules_fired if x.id.startswith("magnitude")]
        assert "ruido_de_tabela" not in [x.id for x in r.rules_fired]

    def test_as_faixas_de_magnitude_nao_se_sobrepoem(self):
        """Duas regras de magnitude no mesmo alerta somariam duas vezes o mesmo fato."""
        for pct in (0.5, 1.5, 3.0, 8.0):
            r = m.avaliar(ctx(delta_pct=pct))
            magnitudes = [
                x for x in r.rules_fired if x.id.startswith(("magnitude", "ruido_de_tabela"))
            ]
            assert len(magnitudes) == 1, (pct, [x.id for x in magnitudes])


class TestFaixaDePreco:
    def test_entrar_na_faixa_pesa_mais_que_sair(self):
        """Deixar de ser alternativa direta é boa notícia; ninguém age sobre ela hoje."""
        entrar = m.avaliar(
            ctx(
                campo="preco_sugerido_brl",
                antes=420000,
                depois=395000,
                preco_ford_comparavel=390000,
            )
        )
        sair = m.avaliar(
            ctx(
                campo="preco_sugerido_brl",
                antes=395000,
                depois=420000,
                preco_ford_comparavel=390000,
            )
        )
        assert "price_band_entry" in [x.id for x in entrar.rules_fired]
        assert "price_band_exit" in [x.id for x in sair.rules_fired]
        assert entrar.pontos > sair.pontos

    def test_ficar_dentro_da_faixa_nao_dispara_nada(self):
        """Mudança dentro da faixa não é entrada nem saída."""
        r = m.avaliar(
            ctx(
                campo="preco_sugerido_brl",
                antes=395000,
                depois=396000,
                preco_ford_comparavel=390000,
            )
        )
        ids = [x.id for x in r.rules_fired]
        assert "price_band_entry" not in ids
        assert "price_band_exit" not in ids

    def test_sem_par_comparavel_a_regra_de_faixa_nao_dispara(self):
        """Sem o preço da Ford equivalente não há faixa; afirmar entrada seria palpite."""
        r = m.avaliar(ctx(campo="preco_sugerido_brl", antes=420000, depois=395000))
        assert "price_band_entry" not in [x.id for x in r.rules_fired]

    def test_o_gap_que_piora_dispara_a_regra(self):
        """Gap positivo = Ford mais cara (`impact.py`). Piorar é aumentar."""
        r = m.avaliar(ctx(gap_antes=-30000, gap_depois=-5000))
        regra = next(x for x in r.rules_fired if x.id == "gap_aumentou_contra_a_ford")
        assert "25.000" in regra.detalhe

    def test_o_gap_que_melhora_nao_dispara(self):
        r = m.avaliar(ctx(gap_antes=-5000, gap_depois=-30000))
        assert "gap_aumentou_contra_a_ford" not in [x.id for x in r.rules_fired]


class TestParityFlip:
    def test_virar_gap_pesa_mais_que_virar_vantagem(self):
        """Perder é o que faz um argumentário aprovado ficar errado sem ninguém ver."""
        perdeu = m.avaliar(
            ctx(parity_flips=({"campo": "potencia_cv", "antes": "vantagem", "depois": "gap"},))
        )
        ganhou = m.avaliar(
            ctx(parity_flips=({"campo": "potencia_cv", "antes": "gap", "depois": "vantagem"},))
        )
        assert perdeu.pontos > ganhou.pontos
        assert "parity_flip_perdemos" in [x.id for x in perdeu.rules_fired]
        assert "parity_flip_ganhamos" in [x.id for x in ganhou.rules_fired]

    def test_virar_desconhecido_e_perda_de_cobertura(self):
        r = m.avaliar(
            ctx(
                parity_flips=(
                    {"campo": "potencia_rpm", "antes": "paridade", "depois": "desconhecido"},
                )
            )
        )
        regra = next(x for x in r.rules_fired if x.id == "parity_flip_desconhecido")
        assert "potencia_rpm" in regra.detalhe

    def test_varios_flips_contam_numa_regra_com_os_campos_no_detalhe(self):
        r = m.avaliar(
            ctx(
                parity_flips=(
                    {"campo": "potencia_cv", "antes": "vantagem", "depois": "gap"},
                    {"campo": "torque_nm", "antes": "paridade", "depois": "gap"},
                )
            )
        )
        regra = next(x for x in r.rules_fired if x.id == "parity_flip_perdemos")
        assert "2 campo(s)" in regra.detalhe
        assert "potencia_cv" in regra.detalhe and "torque_nm" in regra.detalhe
        # Uma regra, não duas: o peso da inversão não se multiplica por campo.
        assert len([x for x in r.rules_fired if x.id == "parity_flip_perdemos"]) == 1


class TestComparabilidade:
    def test_par_nao_comparavel_SUBTRAI(self):
        """Mudança na Raptor a gasolina não muda a conversa de quem compara diesel."""
        comparavel = m.avaliar(ctx(delta_pct=8.0, par_comparavel=True))
        nao = m.avaliar(ctx(delta_pct=8.0, par_comparavel=False))
        assert nao.pontos < comparavel.pontos
        assert "par_nao_comparavel" in [x.id for x in nao.rules_fired]

    def test_sem_equivalente_subtrai_menos(self):
        r = m.avaliar(ctx(delta_pct=8.0, tem_equivalente=False))
        regra = next(x for x in r.rules_fired if x.id == "sem_par_cadastrado")
        assert regra.peso == -5

    def test_pontuacao_negativa_cai_em_RUIDO_e_nao_quebra(self):
        r = m.avaliar(ctx(delta_pct=1.5, par_comparavel=False, tem_equivalente=False))
        assert r.pontos < 0
        assert r.faixa == m.RUIDO


class TestFilaDePrioridade:
    def test_alta_vem_antes_de_media_sempre(self):
        """Os degraus de 1000 garantem que a pontuação não cruze a fronteira da faixa.

        O caso apertado é o da fronteira: um `MEDIA` com um ponto a menos que o mínimo de
        `ALTA` não pode passar na frente do `ALTA` mais fraco possível.
        """
        limiar = next(f.minimo for f in m.carregar().faixas if f.nome == m.ALTA)
        assert m.rank_de(m.ALTA, limiar) < m.rank_de(m.MEDIA, limiar - 1)

    def test_dentro_da_faixa_mais_pontos_vem_primeiro(self):
        assert m.rank_de(m.ALTA, 125) < m.rank_de(m.ALTA, 70)

    def test_ruido_vai_para_o_fim(self):
        assert m.rank_de(m.RUIDO, 20) > m.rank_de(m.BAIXA, 20)

    def test_o_rank_esta_na_resposta(self):
        r = m.avaliar(ctx(delta_pct=8.0))
        assert r.priority_rank == m.rank_de(r.faixa, r.pontos)


class TestOYamlValida:
    def test_toda_regra_tem_descricao(self):
        for regra in m.carregar().regras:
            assert len(regra.descricao) > 30, regra.id

    def test_tipo_desconhecido_levanta_com_a_lista(self, tmp_path):
        """Regra que o motor ignora em silêncio é configuração que mente."""
        arquivo = tmp_path / "r.yaml"
        arquivo.write_text(
            "versao: t\nfaixas:\n  ALTA: {minimo: 60, significado: " + '"' + "x" * 50 + '"' + "}\n"
            "  MEDIA: {minimo: 35, significado: y}\n"
            "  BAIXA: {minimo: 15, significado: z}\n"
            "  RUIDO: {minimo: 0, significado: w}\n"
            "regras:\n  - id: x\n    peso: 10\n    tipo: adivinhacao\n"
            "    descricao: uma descricao suficientemente longa para passar da validacao\n",
            encoding="utf-8",
        )
        m.carregar.cache_clear()
        with pytest.raises(m.RegraInvalida, match="adivinhacao"):
            m.carregar(str(arquivo))
        m.carregar.cache_clear()

    def test_faixas_diferentes_das_quatro_levantam(self, tmp_path):
        arquivo = tmp_path / "r.yaml"
        arquivo.write_text(
            "versao: t\nfaixas:\n  URGENTE: {minimo: 60, significado: "
            + '"'
            + "x" * 50
            + '"'
            + "}\n"
            "regras:\n  - id: x\n    peso: 10\n    tipo: delta_percentual\n"
            "    descricao: uma descricao suficientemente longa para passar da validacao\n",
            encoding="utf-8",
        )
        m.carregar.cache_clear()
        with pytest.raises(m.RegraInvalida, match="quatro"):
            m.carregar(str(arquivo))
        m.carregar.cache_clear()

    def test_regra_sem_descricao_levanta(self, tmp_path):
        arquivo = tmp_path / "r.yaml"
        arquivo.write_text(
            "versao: t\nfaixas:\n  ALTA: {minimo: 60, significado: " + '"' + "x" * 50 + '"' + "}\n"
            "  MEDIA: {minimo: 35, significado: y}\n"
            "  BAIXA: {minimo: 15, significado: z}\n"
            "  RUIDO: {minimo: 0, significado: w}\n"
            "regras:\n  - id: x\n    peso: 10\n    tipo: delta_percentual\n",
            encoding="utf-8",
        )
        m.carregar.cache_clear()
        with pytest.raises(m.RegraInvalida, match="auditável"):
            m.carregar(str(arquivo))
        m.carregar.cache_clear()

    def test_o_arquivo_declara_que_os_pesos_sao_hipotese(self):
        """`specs/WP-34.md`: "Pesos marcados 'hipótese do MVP, configuráveis'"."""
        texto = m.ARQUIVO.read_text(encoding="utf-8")
        assert "hipótese do MVP" in texto
        assert "configuráve" in texto


class TestOsDoisVocabulariosDeDimensao:
    """O repo tem **duas** listas de dimensões, e trocá-las deixa a regra inerte.

    `pipeline/radar/impact.py` fala `custo_de_uso`/`carga`; `pipeline/fit/dimensions.yaml`
    fala `economia`/`capacidade`. Quem preenche `dimensoes_afetadas` no alerta é o
    primeiro, e a primeira versão de `dimensao_de_peso_alto` escreveu os nomes do segundo:
    a regra valia só para `preco` e passava nos dois BDDs — que são de preço — sem nada
    acusar. Estes testes existem para que a próxima troca reprove a suíte.
    """

    def test_toda_dimensao_da_regra_e_emitida_pelo_impact(self):
        from pipeline.radar.impact import DIMENSOES_POR_CAMPO

        emitidas = {d for dims in DIMENSOES_POR_CAMPO.values() for d in dims}
        for regra in m.carregar().regras:
            inertes = set(regra.dimensoes) - emitidas
            assert not inertes, (
                f"{regra.id} pede {sorted(inertes)}, que o impact.py nunca emite: "
                f"a regra fica inerte em silêncio. Emitidas: {sorted(emitidas)}"
            )

    def test_todo_campo_do_mapa_de_dimensoes_e_canonico(self):
        """A causa raiz do mesmo defeito, um nível abaixo.

        `DIMENSOES_POR_CAMPO` apontava para `consumo_cidade_kml`/`consumo_estrada_kml`, que
        não existem no schema (`consumo_urbano_kml`/`consumo_rodoviario_kml`). Uma mudança
        de consumo saía com `dimensoes_afetadas` vazia — e nenhuma regra de dimensão podia
        disparar por ela.
        """
        from pipeline.radar.impact import DIMENSOES_POR_CAMPO
        from pipeline.schema import campos_canonicos

        canonicos = set(campos_canonicos())
        fantasmas = [c for c in DIMENSOES_POR_CAMPO if c not in canonicos]
        assert not fantasmas, f"campos que o schema não tem: {fantasmas}"

    def test_a_mudanca_de_consumo_agora_dispara_a_dimensao(self):
        r = m.avaliar(
            ctx(
                campo="consumo_urbano_kml",
                antes=8.2,
                depois=9.5,
                delta_pct=15.85,
                dimensoes_afetadas=("custo_de_uso",),
            )
        )
        assert "dimensao_de_peso_alto" in [x.id for x in r.rules_fired]
        assert r.faixa == m.ALTA
