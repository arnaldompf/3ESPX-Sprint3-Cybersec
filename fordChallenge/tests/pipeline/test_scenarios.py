"""WP-35 — o simulador: **hipótese do usuário**, nunca observação.

O critério de aceite de regra está em `TestCriterioDeAceite`: um override de −5% no preço
da Hilux produz `diffs` com os estados de paridade e a materialidade que mudaram.

O resto guarda a separação que dá sentido ao módulo: o valor simulado **não** ganha
evidência (inventar citação para um número que ninguém observou seria o pior defeito deste
produto), o valor simulado **não** desaparece da comparação (que é o outro jeito de errar:
o simulador ficaria inerte sem acusar nada), e a origem de todo número hipotético é dita —
"do usuário", como pede a nota da spec.
"""

from __future__ import annotations

import pytest

from pipeline import scenarios
from pipeline.fit.engine import NeedsProfile

FORD = {
    "versao": "Limited 3.0 V6 Diesel 4WD AT",
    # 410 mil e nao 400: com 400, o -5% do critério de aceite levaria a Hilux a 399 mil, a
    # 0,25% da Ford — DENTRO da tolerância de 0,5% do preço (`pipeline/eval/compare.py`), e
    # o estado sairia `paridade`. A tolerância está certa (R$ 1.000 em R$ 400.000 não muda
    # conversa nenhuma) e o −5% é o número da spec; quem cede é a ficha do teste.
    "preco_sugerido_brl": 410000,
    "potencia_cv": 250,
    "torque_nm": 600,
    "capacidade_carga_kg": 1080,
    "consumo_urbano_kml": 8.2,
    "consumo_rodoviario_kml": 10.1,
    "combustivel": "diesel",
    "garantia_meses": 36,
}

CONCORRENTE = {
    "versao": "SRX Plus AT (Cabine Dupla)",
    "preco_sugerido_brl": 420000,
    "potencia_cv": 204,
    "torque_nm": 500,
    "capacidade_carga_kg": 1000,
    "consumo_urbano_kml": 9.7,
    "consumo_rodoviario_kml": 10.6,
    "combustivel": "diesel",
    "garantia_meses": 60,
}


def valores(atributos: dict) -> dict[str, dict]:
    """Mapa no formato de `parity.valores_de_spec`, com tudo verificado."""
    return {
        campo: {
            "valor": valor,
            "status": "verificado",
            "unidade": None,
            "evidence_id": f"ev-{campo}",
        }
        for campo, valor in atributos.items()
    }


def simular(*overrides: scenarios.Override, perfil: NeedsProfile | None = None):
    return scenarios.simular(
        ford=scenarios.Lado(
            version_id="v-ranger", rotulo="Ford Ranger Limited", valores=valores(FORD)
        ),
        concorrentes=[
            scenarios.Lado(
                version_id="v-srx",
                rotulo="Toyota Hilux SRX Plus",
                valores=valores(CONCORRENTE),
            )
        ],
        overrides=list(overrides),
        perfil=perfil,
    )


class TestCriterioDeAceite:
    def test_preco_menos_5_pct_produz_diffs(self):
        """Critério: override de −5% no preço da Hilux → `diffs` com o que mudou.

        Aos 420 mil a Hilux é mais caro que a Ranger de 410 mil, e o campo de preço é
        `vantagem` da Ford. A 399 mil ele passa a ser mais barato: o estado vira `gap`. É a
        inversão que o cenário existe para mostrar **antes** de acontecer.
        """
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        assert r.is_simulation is True

        diff = r.diffs[0]
        preco = next(m for m in diff.paridade if m.campo == "preco_sugerido_brl")
        assert preco.antes == "vantagem"
        assert preco.depois == "gap"

    def test_a_materialidade_do_cenario_vem_do_mesmo_motor(self):
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        materialidade = r.diffs[0].materialidade
        assert materialidade["materiality"] in ("ALTA", "MEDIA", "BAIXA", "RUIDO")
        assert materialidade["rules_fired"], "a faixa sem as regras é um oráculo"
        # A cadeia da simulação diz que é hipótese, como na WP-34.
        assert "hipótese" in materialidade["nota_de_hipotese"]
        assert materialidade["is_simulated"] is True

    def test_a_inversao_de_paridade_alimenta_a_materialidade(self):
        """O flip que o cenário calcula é o mesmo que a régua de materialidade pesa."""
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        flips = r.diffs[0].materialidade["parity_flips"]
        assert any(f["campo"] == "preco_sugerido_brl" for f in flips)
        assert "parity_flip_perdemos" in [x["id"] for x in r.diffs[0].materialidade["rules_fired"]]

    def test_nada_e_gravado_porque_o_motor_nao_conhece_banco(self):
        """O critério "nenhum registro novo em `spec_values`", garantido por construção.

        O motor recebe dicionários e devolve dicionários: não importa `sqlmodel` nem
        `api.app`, então não existe caminho pelo qual ele possa escrever.

        A checagem é na **árvore sintática**, não no texto do arquivo: a primeira versão
        procurava as palavras no fonte inteiro e reprovava por causa do próprio docstring,
        que cita "commit" e "api.app" para explicar que não os usa. Regra que acusa código
        certo é regra ruim (a mesma lição do passo [4] do verify da WP-33).
        """
        import ast
        import pathlib

        arvore = ast.parse(pathlib.Path(scenarios.__file__).read_text(encoding="utf-8"))
        importados: list[str] = []
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                importados += [a.name for a in no.names]
            elif isinstance(no, ast.ImportFrom):
                importados.append(no.module or "")
        for proibido in ("sqlmodel", "sqlalchemy", "api.app", "api"):
            assert not any(m == proibido or m.startswith(f"{proibido}.") for m in importados), (
                f"o motor importa {proibido}: passou a poder escrever"
            )

        # E nenhuma chamada a `.commit()` / `.add()` em lugar nenhum.
        chamadas = [
            no.func.attr
            for no in ast.walk(arvore)
            if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
        ]
        assert "commit" not in chamadas and "flush" not in chamadas


class TestOValorSimuladoNaoGanhaEvidencia:
    def test_o_campo_alterado_perde_o_evidence_id(self):
        """Uma citação ao lado de um número hipotético seria prova de algo inexistente."""
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        celula = next(c for c in r.cenario[0].coluna.celulas if c.campo == "preco_sugerido_brl")
        assert celula.evidence_id_concorrente is None
        # O lado que ninguém mexeu **mantém** a evidência: só o simulado a perde.
        assert celula.evidence_id_ford == "ev-preco_sugerido_brl"

    def test_o_valor_real_continua_com_evidencia_no_painel_de_realidade(self):
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        celula = next(c for c in r.atual[0].coluna.celulas if c.campo == "preco_sugerido_brl")
        assert celula.evidence_id_concorrente == "ev-preco_sugerido_brl"

    def test_o_campo_simulado_continua_comparavel(self):
        """A regressão que este teste tranca.

        O outro jeito de errar era dar ao valor hipotético um status de ausência: o campo
        sumiria da comparação e o simulador ficaria inerte **sem erro nenhum** — a tela
        diria "nenhuma mudança" para um corte de 5% no preço.
        """
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        celula = next(c for c in r.cenario[0].coluna.celulas if c.campo == "preco_sugerido_brl")
        assert celula.estado != "desconhecido"
        assert celula.valor_concorrente == 399000

    def test_a_origem_do_numero_e_dita(self):
        """A nota da spec: se perguntarem de onde veio o −5%, a resposta é "do usuário"."""
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        aplicado = r.overrides_aplicados[0]
        assert aplicado.origem == scenarios.ORIGEM
        assert "usuário" in aplicado.origem
        assert aplicado.antes == 420000
        assert aplicado.depois == 399000
        assert "−5" in aplicado.descricao or "-5" in aplicado.descricao


class TestOsTresTiposDeOverride:
    def test_delta_pct_arredonda_preco_para_inteiro(self):
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        assert r.overrides_aplicados[0].depois == 399000

    def test_novo_valor_entra_como_veio(self):
        r = simular(scenarios.Override(version_id="v-srx", campo="potencia_cv", novo_valor=260))
        celula = next(c for c in r.cenario[0].coluna.celulas if c.campo == "potencia_cv")
        assert celula.valor_concorrente == 260
        # 250 contra 260: a Ford passa a perder no campo.
        assert celula.estado == "gap"

    def test_remover_vira_ausencia_declarada_e_o_campo_sai_da_comparacao(self):
        """`remover` é "o item deixa de existir na versão", que é `nao_disponivel`.

        E aí o campo **tem** de sair da comparação: sem valor de um lado, o estado é
        `desconhecido`, nunca empate. Este é o único caso em que o simulado deixa de ser
        comparável, e é porque a hipótese é justamente a ausência.
        """
        r = simular(
            scenarios.Override(version_id="v-srx", campo="capacidade_carga_kg", remover=True)
        )
        celula = next(c for c in r.cenario[0].coluna.celulas if c.campo == "capacidade_carga_kg")
        assert celula.estado == "desconhecido"
        assert celula.valor_concorrente is None
        assert r.overrides_aplicados[0].depois is None
        assert "não existe" in r.overrides_aplicados[0].descricao

    def test_delta_pct_em_campo_de_texto_recusa_com_o_motivo(self):
        with pytest.raises(scenarios.OverrideInvalido, match="não é número"):
            simular(scenarios.Override(version_id="v-srx", campo="combustivel", delta_pct=-5))

    def test_um_override_por_vez_e_so_um_dos_tres(self):
        with pytest.raises(scenarios.OverrideInvalido, match="exatamente um"):
            scenarios.Override(
                version_id="v-srx", campo="potencia_cv", delta_pct=-5, novo_valor=200
            )
        with pytest.raises(scenarios.OverrideInvalido, match="exatamente um"):
            scenarios.Override(version_id="v-srx", campo="potencia_cv")

    def test_campo_desconhecido_recusa_em_vez_de_criar(self):
        """Criar campo por override inventaria atributo que o schema não tem."""
        with pytest.raises(scenarios.OverrideInvalido, match="não é campo canônico"):
            scenarios.Override(version_id="v-srx", campo="cor_do_teto", novo_valor="azul")

    def test_override_de_versao_fora_da_base_recusa(self):
        with pytest.raises(scenarios.OverrideInvalido, match="não está no cenário"):
            simular(scenarios.Override(version_id="v-fantasma", campo="potencia_cv", novo_valor=1))

    def test_delta_pct_fora_da_faixa_recusa(self):
        """A tela oferece −10%…+10%; a API não aceita 900% em silêncio."""
        with pytest.raises(scenarios.OverrideInvalido, match="entre"):
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=900)

    def test_da_para_simular_a_Ford_tambem(self):
        """O simulador não é só sobre o concorrente: "e se a Ranger baixar?" também vale."""
        r = simular(
            scenarios.Override(version_id="v-ranger", campo="preco_sugerido_brl", delta_pct=-5)
        )
        celula = next(c for c in r.cenario[0].coluna.celulas if c.campo == "preco_sugerido_brl")
        assert celula.valor_ford == 389500
        assert celula.evidence_id_ford is None


class TestOsDiffs:
    def test_campo_que_nao_mudou_nao_entra_no_diff(self):
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        campos = [m.campo for m in r.diffs[0].paridade]
        assert campos == ["preco_sugerido_brl"]

    def test_mudanca_dentro_da_tolerancia_nao_vira_diff(self):
        """1% no preço não muda o estado: os dois lados seguem na mesma ordem."""
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-1)
        )
        assert r.diffs[0].paridade == []

    def test_a_contagem_dos_dois_lados_vem_junto(self):
        """ "Realidade × Cenário" precisa dos dois totais, não só do que mudou."""
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        assert r.atual[0].coluna.contagem.total == r.cenario[0].coluna.contagem.total
        assert r.atual[0].coluna.contagem.vantagem - 1 == r.cenario[0].coluna.contagem.vantagem
        assert r.atual[0].coluna.contagem.gap + 1 == r.cenario[0].coluna.contagem.gap

    def test_sem_override_nenhum_diff(self):
        """Cenário vazio é igual à realidade — e diz isso, em vez de parecer quebrado."""
        r = simular()
        assert r.diffs[0].paridade == []
        assert r.overrides_aplicados == []
        assert r.diffs[0].materialidade is None
        assert "nenhum override" in r.diffs[0].motivo_sem_materialidade

    def test_dois_overrides_no_mesmo_cenario(self):
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5),
            scenarios.Override(version_id="v-srx", campo="potencia_cv", novo_valor=260),
        )
        campos = {m.campo for m in r.diffs[0].paridade}
        assert campos == {"preco_sugerido_brl", "potencia_cv"}
        assert len(r.overrides_aplicados) == 2

    def test_a_realidade_nao_muda_quando_o_cenario_muda(self):
        """O mapa de entrada é copiado: o painel "Realidade" não pode ser contaminado."""
        entrada = valores(CONCORRENTE)
        r = scenarios.simular(
            ford=scenarios.Lado(version_id="v-ranger", rotulo="Ford", valores=valores(FORD)),
            concorrentes=[scenarios.Lado(version_id="v-srx", rotulo="Hilux", valores=entrada)],
            overrides=[
                scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
            ],
        )
        assert entrada["preco_sugerido_brl"]["valor"] == 420000
        assert r.cenario[0].coluna.celulas is not r.atual[0].coluna.celulas


class TestAderencia:
    def test_sem_perfil_a_aderencia_diz_por_que_falta(self):
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        assert r.atual[0].aderencia is None
        assert "perfil" in r.motivo_sem_aderencia

    def test_com_perfil_recalcula_os_dois_lados(self):
        perfil = NeedsProfile(prioridades_rank=["preco", "capacidade", "economia"])
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5),
            perfil=perfil,
        )
        assert r.atual[0].aderencia is not None
        assert r.cenario[0].aderencia is not None
        # Baixando o preço, a nota do concorrente na dimensão de preço tem de subir.
        antes = next(d for d in r.atual[0].aderencia.dimensoes if d.id == "preco")
        depois = next(d for d in r.cenario[0].aderencia.dimensoes if d.id == "preco")
        assert (depois.nota_concorrente or 0) > (antes.nota_concorrente or 0)

    def test_a_dimensao_que_mudou_entra_no_diff_com_os_dois_numeros(self):
        perfil = NeedsProfile(prioridades_rank=["preco", "capacidade", "economia"])
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5),
            perfil=perfil,
        )
        mudou = next(d for d in r.diffs[0].aderencia if d["dimensao"] == "preco")
        assert mudou["antes"] != mudou["depois"]
        assert mudou["rotulo"]

    def test_o_rotulo_obrigatorio_da_aderencia_sobrevive_ao_cenario(self):
        perfil = NeedsProfile(prioridades_rank=["preco"])
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5),
            perfil=perfil,
        )
        assert "não é um ranking de qualidade" in (r.cenario[0].aderencia.rotulo or "")


class TestORotuloDeSimulacao:
    def test_o_texto_e_literal_e_esta_no_topo_da_resposta(self):
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        assert r.rotulo == scenarios.ROTULO
        assert r.rotulo == "SIMULAÇÃO — não é dado observado"

    def test_todo_painel_de_cenario_leva_o_rotulo(self):
        """`docs/13` §2: nenhuma informação exibida sem etiqueta."""
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        dados = r.to_dict()
        assert dados["is_simulation"] is True
        assert dados["rotulo"] == scenarios.ROTULO
        for painel in dados["cenario"]:
            assert painel["is_simulation"] is True
            assert painel["rotulo_simulacao"] == scenarios.ROTULO
        # E o painel da REALIDADE não leva o rótulo: ele é FATO.
        for painel in dados["atual"]:
            assert painel["is_simulation"] is False
            assert painel["rotulo_simulacao"] == ""


class TestAFlagDeCarga:
    """A regra dos 1.000 kg recalculada por painel.

    É o caso em que a diferença entre "não avaliada" e "não atingida" tem consequência:
    a frase fixa da flag fala de **enquadramento fiscal**, e um cenário que remove a
    capacidade de carga não pode produzir "não atinge 1.000 kg" a partir de uma ausência.
    """

    def test_a_realidade_traz_a_flag_com_a_fonte_da_ficha(self):
        r = simular(
            scenarios.Override(version_id="v-srx", campo="preco_sugerido_brl", delta_pct=-5)
        )
        flag = r.atual[0].to_dict()["coluna"]["flag_de_carga"]
        assert flag["aplicavel"] is True
        assert flag["valor"] is True  # 1.000 kg ≥ 1.000 kg
        assert "ficha de" in flag["texto"]

    def test_remover_a_carga_deixa_a_flag_indeterminada(self):
        r = simular(
            scenarios.Override(version_id="v-srx", campo="capacidade_carga_kg", remover=True)
        )
        flag = r.cenario[0].to_dict()["coluna"]["flag_de_carga"]
        assert flag["aplicavel"] is False
        assert flag["valor"] is None
        assert "não avaliada é diferente de não atingida" in flag["motivo"]

    def test_a_carga_hipotetica_cita_o_usuario_como_fonte(self):
        """A frase fala de imposto: ela **tem** de dizer que o número é hipótese."""
        r = simular(
            scenarios.Override(version_id="v-srx", campo="capacidade_carga_kg", novo_valor=1200)
        )
        flag = r.cenario[0].to_dict()["coluna"]["flag_de_carga"]
        assert flag["valor"] is True
        assert scenarios.FONTE_DA_HIPOTESE in flag["texto"]
        assert "não é dado observado" in flag["texto"]

    def test_baixar_a_carga_abaixo_do_limiar_derruba_a_flag(self):
        r = simular(
            scenarios.Override(version_id="v-srx", campo="capacidade_carga_kg", novo_valor=900)
        )
        flag = r.cenario[0].to_dict()["coluna"]["flag_de_carga"]
        assert flag["aplicavel"] is True
        assert flag["valor"] is False
        assert flag["texto"] == ""
        assert "abaixo de 1000 kg" in flag["motivo"]
