"""WP-32 — Comparable Set: **este par pode ser comparado?**, com a régua à vista.

O critério de aceite que dá nome ao módulo é `Raptor × Hilux SRX Plus → comparavel=false`,
com "combustível" e "finalidade" entre os não atendidos. Ele existe porque a comparação
silenciosa produz uma tabela **correta e inútil** (`docs/12` §2.3): cada número certo, e a
conclusão respondendo a uma pergunta que o comprador não fez.

O resto dos testes cerca as três formas de a régua mentir: porcentagem em vez de `k/n`,
critério sem dado contado como atendido (ou como falha), e finalidade inferida da ficha em
vez de declarada por quem decide.
"""

from __future__ import annotations

import pytest

from pipeline import comparables
from pipeline.comparables import ATENDIDO, NAO_ATENDIDO, SEM_DADOS

RAPTOR = {
    "segmento": "picape media",
    "carroceria": "cabine dupla",
    "combustivel": "gasolina",
    "tipo_tracao": "4x4",
    "tipo": "automatica",
    "preco_sugerido_brl": 499000,
    "finalidade": ["desempenho"],
}

SRX_PLUS = {
    "segmento": "picape media",
    "carroceria": "cabine dupla",
    "combustivel": "diesel",
    "tipo_tracao": "4x4",
    "tipo": "automatica",
    "preco_sugerido_brl": 348790,
    "finalidade": ["trabalho", "lazer"],
}

#: A Ranger diesel de topo. **Hipótese declarada**, não linha do catálogo: o gabarito v1
#: não descreve essa versão (o v1.1 que a spec cita não existe neste repo), e inventá-la em
#: `versions` faria o resolvedor encontrar no banco uma versão sem evidência atrás. Aqui os
#: atributos entram à mão porque o que está sob teste é a **régua**, não a extração.
RANGER_DIESEL_TOPO = {
    "segmento": "picape media",
    "carroceria": "cabine dupla",
    "combustivel": "diesel",
    "tipo_tracao": "4x4",
    "tipo": "automatica",
    "preco_sugerido_brl": 380000,
    "finalidade": ["trabalho", "lazer"],
}


class TestCriteriosDeAceite:
    def test_raptor_x_srx_plus_nao_e_comparavel(self):
        """Critério: `comparavel=false`, com combustível e finalidade não atendidos."""
        resultado = comparables.avaliar(RAPTOR, SRX_PLUS)
        assert resultado.comparavel is False
        assert "combustível" in resultado.nao_atendidos
        assert "finalidade" in resultado.nao_atendidos

    def test_o_aviso_e_obrigatorio_e_explica(self):
        """Sem aviso, a tela mostraria a tabela como se o par fosse legítimo."""
        resultado = comparables.avaliar(RAPTOR, SRX_PLUS)
        assert resultado.aviso
        assert "não comparável" in resultado.aviso
        assert "combustível" in resultado.aviso
        # E diz que a comparação campo a campo continua valendo: o aviso é ressalva, não
        # censura — esconder a tabela tiraria informação de quem sabe o que está fazendo.
        assert "continua válida" in resultado.aviso

    def test_ranger_diesel_x_srx_plus_atende_ao_menos_4(self):
        """Critério: o par legítimo do showroom passa de 4 critérios."""
        resultado = comparables.avaliar(RANGER_DIESEL_TOPO, SRX_PLUS)
        assert resultado.criterios_atendidos >= 4
        assert resultado.comparavel is True
        assert resultado.aviso == ""

    def test_par_comparavel_nao_tem_aviso(self):
        assert comparables.avaliar(RANGER_DIESEL_TOPO, RANGER_DIESEL_TOPO).aviso == ""


class TestARegua:
    def test_o_resumo_e_k_de_n_e_nunca_porcentagem(self):
        """`docs/13` §3: "critérios atendidos 5/6", nunca "82% comparável"."""
        resumo = comparables.avaliar(RAPTOR, SRX_PLUS).resumo
        assert "/" in resumo
        assert "%" not in resumo

    def test_a_versao_dos_criterios_viaja_na_resposta(self):
        """Comparação exibida hoje não pode ser confundida com outra régua."""
        resultado = comparables.avaliar(RAPTOR, SRX_PLUS)
        assert resultado.versao_dos_criterios == comparables.carregar().versao
        assert resultado.versao_dos_criterios in resultado.aviso

    def test_combustivel_diferente_barra_mesmo_com_muitos_criterios_atendidos(self):
        """Eliminatório à parte: cinco atendidos não salvam gasolina contra diesel."""
        gasolina = dict(SRX_PLUS, combustivel="gasolina", finalidade=["trabalho", "lazer"])
        resultado = comparables.avaliar(gasolina, SRX_PLUS)
        assert resultado.criterios_atendidos >= comparables.carregar().minimo_atendidos
        assert resultado.comparavel is False
        assert "eliminatório" in resultado.aviso

    def test_faixa_de_preco_usa_a_ford_como_referencia(self):
        """±20% **sobre o preço da Ford**, que é a referência da comparação."""
        caro = dict(SRX_PLUS, preco_sugerido_brl=380000 * 1.19)
        assert _estado(comparables.avaliar(RANGER_DIESEL_TOPO, caro), "faixa_de_preco") == ATENDIDO
        fora = dict(SRX_PLUS, preco_sugerido_brl=380000 * 1.21)
        assert (
            _estado(comparables.avaliar(RANGER_DIESEL_TOPO, fora), "faixa_de_preco") == NAO_ATENDIDO
        )

    def test_o_preco_da_fipe_entra_quando_falta_o_oficial(self):
        """O campo alternativo está declarado no YAML, não escondido no código."""
        sem_oficial = {k: v for k, v in SRX_PLUS.items() if k != "preco_sugerido_brl"}
        sem_oficial["preco_fipe_brl"] = 372000
        resultado = comparables.avaliar(RANGER_DIESEL_TOPO, sem_oficial)
        assert _estado(resultado, "faixa_de_preco") == ATENDIDO

    def test_normaliza_acento_e_caixa_antes_de_comparar(self):
        """ "Cabine Dupla" e "cabine dupla" são a mesma carroceria."""
        outro = dict(SRX_PLUS, carroceria="Cabine Dupla", segmento="Picape Média")
        assert _estado(comparables.avaliar(SRX_PLUS, outro), "carroceria") == ATENDIDO
        assert _estado(comparables.avaliar(SRX_PLUS, outro), "segmento") == ATENDIDO


class TestSemDadosNaoContaNoDenominador:
    def test_criterio_sem_dado_sai_do_n(self):
        """O denominador cai à vista, em vez de o par ser culpado pela fonte faltante."""
        sem_segmento = {k: v for k, v in SRX_PLUS.items() if k != "segmento"}
        resultado = comparables.avaliar(RANGER_DIESEL_TOPO, sem_segmento)
        assert "segmento" in resultado.sem_dados
        assert resultado.criterios_avaliaveis == resultado.total_de_criterios - 1
        assert resultado.criterios_atendidos + len(resultado.nao_atendidos) == (
            resultado.criterios_avaliaveis
        )

    def test_sem_dado_NAO_e_atendido(self):
        """O erro tentador: dois desconhecimentos "iguais" viram um critério atendido."""
        vazio_dos_dois = {"finalidade": []}
        resultado = comparables.avaliar(vazio_dos_dois, vazio_dos_dois)
        assert resultado.criterios_atendidos == 0
        assert resultado.criterios_avaliaveis == 0
        assert resultado.comparavel is False

    def test_sem_dado_NAO_e_nao_atendido(self):
        sem_segmento = {k: v for k, v in SRX_PLUS.items() if k != "segmento"}
        resultado = comparables.avaliar(RANGER_DIESEL_TOPO, sem_segmento)
        assert "segmento" not in resultado.nao_atendidos

    def test_o_motivo_diz_de_qual_lado_falta(self):
        """ "Não foi possível avaliar" mandaria procurar nos dois lugares."""
        sem_segmento = {k: v for k, v in SRX_PLUS.items() if k != "segmento"}
        detalhe = _detalhe(comparables.avaliar(RANGER_DIESEL_TOPO, sem_segmento), "segmento")
        assert detalhe.estado == SEM_DADOS
        assert "no concorrente" in detalhe.motivo
        assert "na versão Ford" not in detalhe.motivo

    def test_zero_e_false_nao_sao_ausencia(self):
        """`0` num campo de preço é um valor absurdo, mas **é** um valor declarado."""
        assert comparables._vazio(0) is False
        assert comparables._vazio(False) is False
        assert comparables._vazio("") is True
        assert comparables._vazio([]) is True


class TestFinalidade:
    def test_vem_do_arquivo_e_nao_da_ficha(self):
        assert comparables.finalidade_de("Raptor 3.0 V6 Bi-turbo 4WD AT") == ("desempenho",)
        assert "trabalho" in comparables.finalidade_de("SRX Plus AT")

    def test_versao_nao_declarada_fica_sem_finalidade(self):
        """Vazio é ausência declarada: o critério entra como sem dados.

        Inferir a finalidade da ficha ("tem muita potência, logo é de desempenho") faria o
        par ser reprovado por uma opinião que ninguém assinou.
        """
        assert comparables.finalidade_de("Picape Que Nao Existe") == ()

    def test_casa_por_nome_normalizado(self):
        assert comparables.finalidade_de("srx plus at") == comparables.finalidade_de("SRX Plus AT")

    def test_a_etiqueta_lazer_nao_esta_em_tudo(self):
        """A regressão que este teste tranca.

        A primeira lista dava `lazer` à Raptor **e** à SRX Plus. As duas passavam a ter algo
        em comum e o critério que existe exatamente para separar esse par virava decoração.
        """
        raptor = set(comparables.finalidade_de("Raptor 3.0 V6 Bi-turbo 4WD AT"))
        srx = set(comparables.finalidade_de("SRX Plus AT"))
        assert not (raptor & srx)


class TestConfiguracao:
    def test_o_yaml_declara_os_sete_criterios_com_descricao(self):
        cfg = comparables.carregar()
        assert len(cfg.criterios) == 7
        assert all(c.descricao for c in cfg.criterios), "critério sem descrição não é auditável"
        assert {c.id for c in cfg.criterios} == {
            "segmento",
            "carroceria",
            "combustivel",
            "tracao",
            "transmissao",
            "faixa_de_preco",
            "finalidade",
        }

    def test_tipo_de_criterio_desconhecido_levanta_com_a_lista(self, tmp_path):
        """Falhar alto: um critério que o módulo não sabe avaliar sumiria da conta."""
        arquivo = tmp_path / "c.yaml"
        arquivo.write_text(
            "versao: teste\ncriterios:\n  - id: x\n    campo: y\n    tipo: adivinhacao\n",
            encoding="utf-8",
        )
        comparables.carregar.cache_clear()
        with pytest.raises(comparables.CriterioInvalido, match="adivinhacao"):
            comparables.carregar(str(arquivo))
        comparables.carregar.cache_clear()

    def test_o_campo_de_transmissao_e_o_nome_canonico_do_schema(self):
        """`tipo`, não `transmissao_tipo`: o grupo não faz parte do nome (`docs/03`)."""
        from pipeline.schema import GRUPOS

        criterio = next(c for c in comparables.carregar().criterios if c.id == "transmissao")
        assert criterio.campo in GRUPOS["transmissao"]


class TestAtributosDeSpec:
    def test_status_de_ausencia_vira_None_e_nao_o_texto_do_status(self):
        """O erro que este teste impede.

        Um campo `nao_encontrado` cujo valor virasse o texto "nao_encontrado" casaria por
        igualdade com o do outro lado, e o critério apareceria **atendido** — dois
        desconhecimentos afirmando uma igualdade.
        """
        from pipeline.schema import Status, empty_spec

        spec = empty_spec(status=Status.NAO_ENCONTRADO)
        atributos = comparables.atributos_de_spec(spec, versao="SRX Plus AT")
        assert atributos["segmento"] is None
        assert atributos["combustivel"] is None
        assert atributos["finalidade"] == ["trabalho", "lazer"]

    def test_ficha_vazia_dos_dois_lados_nao_e_comparavel(self):
        from pipeline.schema import empty_spec

        vazia = comparables.atributos_de_spec(empty_spec(), versao="")
        resultado = comparables.avaliar(vazia, vazia)
        assert resultado.comparavel is False
        assert resultado.criterios_avaliaveis == 0


class TestFlagDe1000kg:
    def test_criterio_de_aceite_1005_kg_liga_a_flag_com_o_texto_fixo(self):
        flag = comparables.flag_de_carga(1005, fonte="PDF oficial Hilux, pág. 3")
        assert flag.valor is True
        assert flag.etiqueta == "INFERENCIA"
        assert flag.texto == (
            "Capacidade de carga ≥ 1.000 kg (PDF oficial Hilux, pág. 3). Critério "
            "comumente associado à classificação como veículo de carga; confirmar "
            "enquadramento fiscal com a Ford."
        )

    def test_o_texto_nao_afirma_enquadramento_fiscal_nem_cita_imposto(self):
        """A regra inviolável aqui: o número é fato, a consequência fiscal não é nossa.

        Depende de legislação, do CNPJ do comprador e do uso — coisas que um extrator de
        ficha técnica não sabe. "Logo, isento de IPI" seria orientação tributária.
        """
        texto = comparables.TEXTO_DA_FLAG_DE_CARGA.lower()
        for proibido in ("ipi", "icms", "imposto", "isento", "alíquota", "aliquota", "%"):
            assert proibido not in texto
        assert "confirmar enquadramento fiscal com a ford" in texto

    def test_abaixo_do_limiar_a_flag_e_falsa_e_sem_texto(self):
        flag = comparables.flag_de_carga(620)
        assert flag.aplicavel is True
        assert flag.valor is False
        assert flag.texto == ""
        assert "abaixo" in flag.motivo

    def test_exatamente_1000_kg_atinge(self):
        assert comparables.flag_de_carga(1000).valor is True

    def test_sem_valor_a_flag_e_INDETERMINADA_e_nao_falsa(self):
        """Dizer "não atinge 1.000 kg" sem o dado é afirmar fato a partir de ausência."""
        flag = comparables.flag_de_carga(None)
        assert flag.aplicavel is False
        assert flag.valor is None
        assert "não é avaliável" in flag.motivo

    def test_le_numero_escrito_em_portugues(self):
        assert comparables.flag_de_carga("1.005 kg").valor is True


def _detalhe(resultado, criterio_id):
    return next(d for d in resultado.detalhes if d.id == criterio_id)


def _estado(resultado, criterio_id):
    return _detalhe(resultado, criterio_id).estado
