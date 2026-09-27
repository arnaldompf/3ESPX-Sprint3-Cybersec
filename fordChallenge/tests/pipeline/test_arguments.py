"""WP-27 — argumentário: template, verificador e a reescrita que passa por ele.

Dois critérios de aceite vivem aqui: **3 pontos Ford + 1 do concorrente, cada um com
evidência**, e **texto do LLM com número inventado é rejeitado**, voltando ao template com
`gerado_por="template"`.

O verificador é o que dá ao LLM o direito de participar. Sem ele, uma reescrita "em tom
consultivo" poderia trocar 397 por 400 e o texto sairia mais bonito e menos verdadeiro —
a pior troca possível neste produto.
"""

from __future__ import annotations

from pipeline.arguments import llm_rewrite, template, verify

CELULAS = {
    "potencia_cv": template.CampoDaCelula(
        campo="potencia_cv",
        valor_ford=397,
        valor_concorrente=204,
        unidade="cv",
        evidence_id_ford="ev-ford-potencia",
        evidence_id_concorrente="ev-conc-potencia",
        fonte_ford="https://www.ford.com.br/ranger-raptor",
        fonte_concorrente="https://www.toyota.com.br/hilux",
        data_ford="2026-09-01T00:00:00",
        data_concorrente="2026-09-01T00:00:00",
    ),
    "torque_nm": template.CampoDaCelula(
        campo="torque_nm",
        valor_ford=583,
        valor_concorrente=500,
        unidade="Nm",
        evidence_id_ford="ev-ford-torque",
        evidence_id_concorrente="ev-conc-torque",
        fonte_ford="https://www.ford.com.br/ranger-raptor",
        fonte_concorrente="https://www.toyota.com.br/hilux",
        data_ford="2026-09-01T00:00:00",
        data_concorrente="2026-09-01T00:00:00",
    ),
    "capacidade_carga_kg": template.CampoDaCelula(
        campo="capacidade_carga_kg",
        valor_ford=620,
        valor_concorrente=1005,
        unidade="kg",
        evidence_id_ford="ev-ford-carga",
        evidence_id_concorrente="ev-conc-carga",
        fonte_ford="https://www.ford.com.br/ranger-raptor",
        fonte_concorrente="https://www.toyota.com.br/hilux",
        data_ford="2026-09-01T00:00:00",
        data_concorrente="2026-09-01T00:00:00",
    ),
    "garantia_meses": template.CampoDaCelula(
        campo="garantia_meses",
        valor_ford=36,
        valor_concorrente=36,
        unidade="meses",
        evidence_id_ford="ev-ford-garantia",
        evidence_id_concorrente="ev-conc-garantia",
    ),
    "camera_360": template.CampoDaCelula(
        campo="camera_360",
        valor_ford=True,
        valor_concorrente=False,
        evidence_id_ford="ev-ford-camera",
        evidence_id_concorrente="ev-conc-camera",
    ),
    "consumo_urbano_kml": template.CampoDaCelula(
        campo="consumo_urbano_kml",
        valor_ford=7.2,
        valor_concorrente=9.7,
        unidade="km/l",
        evidence_id_ford="ev-ford-consumo",
        evidence_id_concorrente="ev-conc-consumo",
    ),
}


def dimensao(
    nome: str,
    *,
    peso: float,
    campos: list[tuple[str, float, float]],
    rotulo: str = "",
) -> dict:
    """Uma dimensão avaliada, no formato que `engine.Aderencia.to_dict()` produz."""
    return {
        "dimensao": nome,
        "rotulo": rotulo or nome,
        "peso": peso,
        "nota_ford": sum(f for _, f, _ in campos) / len(campos),
        "nota_concorrente": sum(c for _, _, c in campos) / len(campos),
        "campos_usados": [c for c, _, _ in campos],
        "campos_sem_dado": [],
        "cobertura": 1.0,
        "insuficiente": False,
        "aviso": "",
        "detalhe_ford": [
            {"campo": c, "nota": f, "valor": None, "motivo": ""} for c, f, _ in campos
        ],
        "detalhe_concorrente": [
            {"campo": c, "nota": n, "valor": None, "motivo": ""} for c, _, n in campos
        ],
    }


ADERENCIA = {
    "aderencia_ford": 6.0,
    "aderencia_concorrente": 5.0,
    "pesos": {"desempenho": 35, "seguranca": 25, "conforto_tecnologia": 20, "capacidade": 12},
    "dimensoes": [
        dimensao(
            "desempenho",
            peso=35,
            rotulo="desempenho",
            campos=[("potencia_cv", 10.0, 2.0), ("torque_nm", 8.0, 5.0)],
        ),
        dimensao("seguranca", peso=25, rotulo="segurança", campos=[("camera_360", 10.0, 0.0)]),
        dimensao(
            "conforto_tecnologia",
            peso=20,
            rotulo="conforto e tecnologia",
            campos=[("garantia_meses", 6.0, 4.0)],
        ),
        dimensao(
            "capacidade",
            peso=12,
            rotulo="capacidade de carga e reboque",
            campos=[("capacidade_carga_kg", 2.0, 9.0)],
        ),
        dimensao(
            "economia",
            peso=8,
            rotulo="economia de combustível",
            campos=[("consumo_urbano_kml", 1.0, 8.0)],
        ),
    ],
    "vence_em": {
        "ford": ["desempenho", "seguranca", "conforto_tecnologia"],
        "concorrente": ["capacidade", "economia"],
    },
    "peso_considerado": 100,
    "avisos": [],
    "rotulo": "Aderência ao perfil informado — não é um ranking de qualidade",
    "versao_das_dimensoes": "teste",
    "versao_das_faixas": "teste",
}


def montar(aderencia=None, **kw):
    return template.montar(
        aderencia or ADERENCIA,
        CELULAS,
        rotulo_ford="Ford Ranger Raptor",
        rotulo_concorrente="Toyota Hilux SRX Plus",
        **kw,
    )


class TestCriterioDeAceite:
    def test_tres_pontos_ford_mais_um_do_concorrente(self):
        """Critério: exatamente 3 pontos Ford + 1 do concorrente."""
        r = montar()
        assert len(r.pontos) == 3
        assert all(p.a_favor for p in r.pontos)
        assert r.ponto_forte_concorrente is not None
        assert r.ponto_forte_concorrente.a_favor is False

    def test_cada_ponto_tem_evidencia_dos_dois_lados(self):
        """Critério: "cada um com evidências". Frase sem isso é alegação bem escrita."""
        r = montar()
        for ponto in [*r.pontos, r.ponto_forte_concorrente]:
            assert ponto is not None
            assert len(ponto.fonte_por_ponto) == 2
            assert all(e for e in ponto.fonte_por_ponto)

    def test_a_ordem_dos_pontos_e_por_PESO_da_dimensao(self):
        """O argumento mais importante é o da dimensão que o cliente priorizou."""
        r = montar()
        assert [p.dimensao for p in r.pontos] == [
            "desempenho",
            "seguranca",
            "conforto_tecnologia",
        ]
        assert [p.peso for p in r.pontos] == [35, 25, 20]

    def test_o_ponto_de_atencao_e_a_dimensao_de_maior_peso_do_concorrente(self):
        r = montar()
        assert r.ponto_forte_concorrente is not None
        assert r.ponto_forte_concorrente.dimensao == "capacidade"
        assert r.ponto_forte_concorrente.peso == 12


class TestOTextoDaFrase:
    def test_a_frase_a_favor_tem_os_dois_valores_a_fonte_e_a_data(self):
        ponto = montar().pontos[0]
        assert "397 cv" in ponto.texto
        assert "204 cv" in ponto.texto
        assert "ford.com.br" in ponto.texto
        assert "01/09/2026" in ponto.texto

    def test_a_frase_de_atencao_nao_ameniza(self):
        """Sem "porém", sem "apesar de": o ponto é dito e pronto."""
        ponto = montar().ponto_forte_concorrente
        assert ponto is not None
        assert ponto.texto.startswith("Onde a Toyota Hilux SRX Plus leva vantagem")
        assert "1.005 kg" in ponto.texto
        assert "620 kg" in ponto.texto
        for amenizador in ("porém", "apesar", "mas a Ford"):
            assert amenizador not in ponto.texto

    def test_o_campo_escolhido_e_o_de_maior_diferenca_na_dimensao(self):
        """`potencia_cv` (10 contra 2) ganha de `torque_nm` (8 contra 5) em desempenho.

        É o que dá ao vendedor a frase mais **defensável**: uma vantagem de 2% seria verdade
        e não seria argumento — o cliente compara os dois números e conclui que dá no mesmo.
        """
        assert montar().pontos[0].campo == "potencia_cv"

    def test_booleano_sai_como_sim_e_nao(self):
        ponto = next(p for p in montar().pontos if p.campo == "camera_360")
        assert "sim" in ponto.texto
        assert "não" in ponto.texto

    def test_numero_grande_sai_com_separador_de_milhar(self):
        ponto = montar().ponto_forte_concorrente
        assert ponto is not None
        assert "1.005" in ponto.texto

    def test_decimal_sai_com_virgula(self):
        aderencia = dict(ADERENCIA, vence_em={"ford": [], "concorrente": ["economia"]})
        ponto = montar(aderencia).ponto_forte_concorrente
        assert ponto is not None
        assert "9,7 km/l" in ponto.texto


class TestQuandoFaltaMaterial:
    def test_menos_de_tres_dimensoes_vencedoras_da_menos_pontos_COM_aviso(self):
        """Repetir dimensão para chegar a três seria inflar o argumentário."""
        aderencia = dict(ADERENCIA, vence_em={"ford": ["desempenho"], "concorrente": []})
        r = montar(aderencia)
        assert len(r.pontos) == 1
        assert any("inflar o argumentário" in a for a in r.avisos)

    def test_sem_dimensao_do_concorrente_o_aviso_explica_o_que_isso_NAO_significa(self):
        aderencia = dict(ADERENCIA, vence_em={"ford": ["desempenho"], "concorrente": []})
        r = montar(aderencia)
        assert r.ponto_forte_concorrente is None
        aviso = next(a for a in r.avisos if "concorrente" in a)
        assert "não significa que ele não tenha nenhuma" in aviso

    def test_dimensao_sem_celula_para_o_campo_e_pulada(self):
        """A dimensão venceu, mas nenhum campo dela tem valor nos dois lados."""
        aderencia = dict(
            ADERENCIA,
            dimensoes=[
                dimensao("off_road", peso=35, campos=[("reduzida", 10.0, 0.0)]),
                *ADERENCIA["dimensoes"],
            ],
            vence_em={"ford": ["off_road", "desempenho"], "concorrente": []},
        )
        r = montar(aderencia)
        assert all(p.dimensao != "off_road" for p in r.pontos)

    def test_ficha_vazia_nao_gera_ponto_nenhum(self):
        r = template.montar(
            {"dimensoes": [], "vence_em": {"ford": [], "concorrente": []}},
            {},
            rotulo_ford="Ford",
            rotulo_concorrente="Concorrente",
        )
        assert r.pontos == []
        assert r.ponto_forte_concorrente is None
        assert len(r.avisos) == 2


class TestVerificador:
    def test_numero_que_existe_nas_celulas_passa(self):
        r = verify.verificar("A Ford tem 397 cv contra 204 cv.", [397, 204])
        assert r.aprovado is True

    def test_criterio_de_aceite_numero_inventado_reprova(self):
        """Critério: número que não existe nas células → rejeita."""
        r = verify.verificar("A Ford tem 400 cv contra 204 cv.", [397, 204])
        assert r.aprovado is False
        assert 400.0 in r.numeros_sem_respaldo
        assert "400" in r.motivo

    def test_o_motivo_diz_qual_numero_nao_tem_respaldo(self):
        r = verify.verificar("São 1.200 kg de carga.", [620, 1005])
        assert r.aprovado is False
        assert "1200" in r.motivo.replace(".", "")

    def test_numero_pequeno_de_portugues_normal_passa(self):
        """ "3 pontos", "as 4 rodas": exigir célula para isso reprovaria português."""
        r = verify.verificar("Três pontos e 2 observações sobre as 4 rodas.", [397])
        assert r.aprovado is True

    def test_a_data_da_fonte_passa(self):
        r = verify.verificar(
            "397 cv (site oficial, 01/09/2026).", [397], datas=["2026-09-01T00:00:00"]
        )
        assert r.aprovado is True

    def test_ano_de_quatro_digitos_passa_mesmo_sem_datas(self):
        r = verify.verificar("Linha 2026 com 397 cv.", [397])
        assert r.aprovado is True

    def test_lista_sustenta_a_propria_contagem(self):
        """ "Os 7 modos de condução" é sustentado por uma lista de 7 itens."""
        r = verify.verificar(
            "São 7 modos de condução.", [["normal", "sport", "lama", "areia", "baja", "rc", "esc"]]
        )
        assert r.aprovado is True

    def test_superlativo_reprova_sempre(self):
        r = verify.verificar("A melhor picape do mercado, com 397 cv.", [397])
        assert r.aprovado is False
        assert r.termos_proibidos

    def test_comparativo_sem_numero_reprova(self):
        r = verify.verificar("Tem o dobro de força.", [397, 204])
        assert r.aprovado is False
        assert "o dobro" in r.termos_proibidos

    def test_decimal_com_virgula_casa_com_o_valor_da_celula(self):
        r = verify.verificar("Faz 9,7 km/l na cidade.", [9.7])
        assert r.aprovado is True

    def test_valor_em_texto_na_celula_tambem_sustenta(self):
        r = verify.verificar("Pneus 285/70 R17.", ["285/70 R17"])
        assert r.aprovado is True

    def test_booleano_nao_sustenta_numero(self):
        """`True` não é 1: um booleano na célula não autoriza citar "1" como medida."""
        assert verify.numeros_das_celulas([True, False]) == set()

    def test_numero_que_e_parte_do_NOME_do_campo_passa(self):
        """A regressão que este teste tranca.

        "câmera 360 de série" foi reprovado porque nenhuma célula tem o valor 360 — só que
        o 360 é o **nome** do item (`camera_360`), não uma medida. O verificador reprovava
        exatamente o texto correto que citou o item pelo nome que a ficha usa. O mesmo
        valeria para "4x4", "V6" e "2.8".
        """
        sem_nome = verify.verificar("Tem câmera 360 de série.", [True])
        assert sem_nome.aprovado is False
        com_nome = verify.verificar(
            "Tem câmera 360 de série.", [True], nomes_de_campo=["camera_360"]
        )
        assert com_nome.aprovado is True


class TestReescrita:
    def test_sem_llm_devolve_o_template_e_diz_por_que(self):
        r = llm_rewrite.reescrever(montar(), CELULAS, permitir_llm=False)
        assert r.gerado_por == "template"
        assert "desligada" in r.motivo
        assert len(r.textos) == 4

    def test_criterio_de_aceite_com_LLM_FAKE_sem_fixture_fica_o_template(self, monkeypatch):
        """Critério, na prática: sem material do LLM, `gerado_por="template"`."""
        monkeypatch.setenv("LLM_FAKE", "1")
        r = llm_rewrite.reescrever(montar(), CELULAS)
        assert r.gerado_por == "template"
        assert r.textos == [p.texto for p in montar().pontos] + [
            montar().ponto_forte_concorrente.texto  # type: ignore[union-attr]
        ]

    def test_texto_do_llm_com_numero_inventado_volta_ao_template(self, monkeypatch):
        """O critério de aceite, com o LLM respondendo de verdade (dublado)."""
        from pipeline import llm

        def falso(**kw):
            return llm.RespostaLLM(
                dados={"pontos": ["A Ford tem 400 cv contra 204 cv."]},
                uso=llm.Uso("dublado"),
                ok=True,
                motivo="dublado",
            )

        monkeypatch.setattr(llm, "extrair_json", falso)
        r = llm_rewrite.reescrever(montar(), CELULAS)
        assert r.gerado_por == "template"
        assert r.verificacao is not None and r.verificacao.aprovado is False
        assert "400" in r.motivo

    def test_texto_verificado_e_aceito_como_llm(self, monkeypatch):
        from pipeline import llm

        bons = [
            "Quem prioriza desempenho vai sentir os 397 cv contra 204 cv da concorrente.",
            "Segurança: câmera 360 de série, o que a concorrente não traz.",
            "Conforto: 36 meses de garantia nas duas.",
            "Onde a Hilux leva vantagem: 1.005 kg de carga contra 620 kg.",
        ]

        def falso(**kw):
            return llm.RespostaLLM(
                dados={"pontos": bons}, uso=llm.Uso("dublado"), ok=True, motivo="dublado"
            )

        monkeypatch.setattr(llm, "extrair_json", falso)
        r = llm_rewrite.reescrever(montar(), CELULAS)
        assert r.gerado_por == "llm"
        assert r.textos == bons

    def test_quantidade_diferente_de_pontos_reprova(self, monkeypatch):
        """O modelo juntou dois pontos: a correspondência texto ↔ fonte se perderia."""
        from pipeline import llm

        def falso(**kw):
            return llm.RespostaLLM(
                dados={"pontos": ["397 cv e 583 Nm num texto só."]},
                uso=llm.Uso("dublado"),
                ok=True,
                motivo="dublado",
            )

        monkeypatch.setattr(llm, "extrair_json", falso)
        r = llm_rewrite.reescrever(montar(), CELULAS)
        assert r.gerado_por == "template"
        assert "correspondência entre texto e fonte" in r.motivo

    def test_o_sistema_proibe_dado_novo_e_superlativo(self):
        """O prompt não é a garantia — o verificador é. Mas ele tem de pedir o certo."""
        assert "SOMENTE" in llm_rewrite.SISTEMA
        assert "não acrescente nenhum dado novo" in llm_rewrite.SISTEMA
        assert "sem amenizá-lo" in llm_rewrite.SISTEMA


# --------------------------------------------------- campo de lista: contagem, não catálogo
#
# Um avaliador usou o sistema em 12/09/2026 e leu, no argumentário, uma frase com os
# catorze itens de ADAS dos dois veículos emendados: "a Ford ... tem adas itens de
# assistente de permanência em faixa, assistente autônomo de frenagem, alerta de colisão,
# ... contra Pre-crash System (PCS) com frenagem automática (carros, pedestres, ciclistas),
# Lane Departure Alert (LDA), ... da Toyota". Ninguém fala isso em pé, e o uso é exatamente
# esse — o vendedor lendo em voz alta com o cliente ao lado.
#
# Havia um erro de conteúdo junto do de forma: a nota que gerou o ponto é de CONTAGEM
# (`dimensions.yaml`: `adas_itens` é `tipo: contagem`), e a frase enumerava o que a nota
# não mede enquanto omitia o número que ela mede.
class TestCampoDeLista:
    def _aderencia(self, vence_em: dict, nota_ford: float = 8.0, nota_conc: float = 6.0) -> dict:
        return {
            "dimensoes": [
                {
                    "dimensao": "seguranca",
                    "rotulo": "segurança",
                    "peso": 40,
                    "nota_ford": nota_ford,
                    "nota_concorrente": nota_conc,
                    "campos_usados": ["adas_itens"],
                    "campos_sem_dado": [],
                    "cobertura": 1.0,
                    "insuficiente": False,
                    "aviso": "",
                    # `_campo_mais_forte` escolhe pela diferença de nota entre os lados,
                    # e é por aqui que ele acha `adas_itens`.
                    "detalhe_ford": [{"campo": "adas_itens", "nota": nota_ford}],
                    "detalhe_concorrente": [{"campo": "adas_itens", "nota": nota_conc}],
                }
            ],
            "vence_em": vence_em,
            "rotulo": "aderência ao perfil informado",
            "versao_das_dimensoes": "teste",
            "versao_das_faixas": "teste",
        }

    def _celulas(self, itens_ford: list[str], itens_conc: list[str]) -> dict:
        return {
            "adas_itens": template.CampoDaCelula(
                campo="adas_itens",
                valor_ford=itens_ford,
                valor_concorrente=itens_conc,
                unidade=None,
                evidence_id_ford="ev-ford-adas",
                evidence_id_concorrente="ev-conc-adas",
                fonte_ford="https://www.ford.com.br/ranger",
                fonte_concorrente="https://www.toyota.com.br/hilux",
                data_ford="2026-09-01T00:00:00",
                data_concorrente="2026-09-01T00:00:00",
            )
        }

    def test_a_frase_diz_a_contagem_e_tres_exemplos_nunca_a_lista_inteira(self):
        ford = [f"item {i}" for i in range(1, 9)]
        conc = [f"outro {i}" for i in range(1, 7)]
        celulas = self._celulas(ford, conc)
        resultado = template.montar(
            self._aderencia({"ford": ["seguranca"], "concorrente": []}),
            celulas,
            rotulo_ford="Ford Ranger Limited",
            rotulo_concorrente="Toyota Hilux SRX Plus",
        )
        texto = resultado.pontos[0].texto

        assert "8 itens de assistência à condução" in texto
        assert "traz 6" in texto, texto
        assert "entre eles item 1, item 2 e item 3" in texto, texto
        # O quarto item não entra: a frase é falada, não um catálogo.
        assert "item 4" not in texto
        # E o nome do campo não vaza como slug.
        assert "adas itens de" not in texto
        assert "adas_itens" not in texto
        # A fonte e a data continuam na frase — é a promessa do produto.
        assert "ford.com.br" in texto
        assert "01/09/2026" in texto

    def test_a_frase_do_concorrente_tambem_conta_em_vez_de_enumerar(self):
        celulas = self._celulas(["a", "b"], ["x", "y", "z", "w"])
        resultado = template.montar(
            self._aderencia(
                {"ford": [], "concorrente": ["seguranca"]}, nota_ford=4.0, nota_conc=9.0
            ),
            celulas,
            rotulo_ford="Ford Ranger Limited",
            rotulo_concorrente="Toyota Hilux SRX Plus",
        )
        texto = resultado.ponto_forte_concorrente.texto
        assert "4 itens de assistência à condução" in texto, texto
        assert "a Ford Ranger Limited traz 2" in texto, texto
        assert "toyota.com.br" in texto

    def test_campo_escalar_nao_muda_de_frase(self):
        """Contra-teste: a frase de contagem é só para lista dos DOIS lados."""
        resultado = montar()
        assert any("contra" in p.texto for p in resultado.pontos), [
            p.texto for p in resultado.pontos
        ]

    def test_lista_de_um_lado_so_nao_vira_frase_de_contagem(self):
        """Comparar "8 itens" com um número solto não é comparação."""
        celulas = self._celulas(["a", "b"], [])
        celulas["adas_itens"].valor_concorrente = 3
        assert template._e_lista(celulas["adas_itens"]) is False

    def test_um_exemplo_so_nao_ganha_e_no_meio(self):
        assert template._exemplos(["único"]) == "único"
        assert template._exemplos(["a", "b"]) == "a e b"
        assert template._exemplos(["a", "b", "c", "d"]) == "a, b e c"

    def test_a_contagem_passa_no_verificador(self):
        """A frase só pode dizer número que a célula sustenta.

        `verify` aceita `len(valor)` para lista — é o que permite "8 itens" sem afrouxar
        nada. Se este teste quebrar, a frase passou a afirmar algo sem respaldo.
        """
        celulas = self._celulas(["a", "b", "c"], ["x", "y"])
        resultado = template.montar(
            self._aderencia({"ford": ["seguranca"], "concorrente": []}),
            celulas,
            rotulo_ford="Ford Ranger",
            rotulo_concorrente="Toyota Hilux",
        )
        conferido = verify.verificar(resultado.pontos[0].texto, celulas)
        assert conferido.aprovado, conferido
        assert conferido.numeros_sem_respaldo == [], conferido
        # O 3 e o 2 da frase são `len` das duas listas: é o respaldo que existe.
        assert 3.0 in conferido.numeros_do_texto
        assert 2.0 in conferido.numeros_do_texto
