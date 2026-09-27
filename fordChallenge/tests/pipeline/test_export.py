"""A exportação: o arquivo tem de continuar honesto longe da tela que o gerou.

O que estes testes guardam são as quatro promessas que se perdem primeiro numa exportação:

1. **célula sem valor não fica em branco** — em planilha, vazio é lido como zero, como
   "não se aplica" e como erro de exportação, e as três leituras são falsas;
2. **toda célula com valor leva a fonte e a data** — sem elas, o número é indistinguível
   de um que alguém digitou;
3. **as ressalvas viajam com o arquivo** — se a comparabilidade ficar só na tela, a
   primeira cópia já perde o que impede a leitura errada, e é a cópia que circula;
4. **o esquema do Parquet não muda** com o número de concorrentes — tabela cujo esquema
   muda não se carrega em warehouse.
"""

from __future__ import annotations

import pytest

from pipeline.export import arquivos
from pipeline.export import tabela as tab


def _tabela(**extra) -> tab.Tabela:
    colunas = [
        tab.Coluna(version_id="ford1", rotulo="Ford Ranger Limited", e_referencia=True),
        tab.Coluna(
            version_id="hilux1",
            rotulo="Toyota Hilux SRX Plus",
            comparabilidade="5/6 critérios atendidos",
        ),
    ]
    linhas = [
        tab.Linha(
            campo="potencia_cv",
            grupo="motorização",
            rotulo="Potência",
            celulas=(
                tab.Celula(
                    valor=250,
                    unidade="cv",
                    status="verificado",
                    fonte_url="https://www.ford.com.br/ranger/",
                    fonte_data="2026-09-01",
                    trecho="250 cv de potência",
                    etiqueta="FATO",
                ),
                tab.Celula(
                    valor=204,
                    unidade="cv",
                    status="verificado",
                    situacao="ganhamos",
                    fonte_url="https://www.toyota.com.br/hilux/",
                    fonte_data="2026-09-02",
                    trecho="204 cv",
                    etiqueta="FATO",
                ),
            ),
        ),
        tab.Linha(
            campo="paddle_shifters",
            grupo="transmissão",
            rotulo="Paddle shifters",
            celulas=(
                tab.Celula(valor=None, status="nao_encontrado"),
                tab.Celula(valor=True, status="verificado", situacao="perdemos"),
            ),
        ),
    ]
    dados = {
        "titulo": "Benchmark — Ford Ranger Limited",
        "gerada_em": "2026-09-13T09:00:00Z",
        "colunas": colunas,
        "linhas": linhas,
        "ressalvas": ["A Fiat Toro é de categoria diferente e entra marcada."],
        "versao_dos_criterios": "2026-09-09",
    }
    dados.update(extra)
    return tab.Tabela(**dados)


class TestCelulaSemValor:
    @pytest.mark.parametrize(
        ("status", "trecho"),
        [
            ("nao_encontrado", "não encontrado"),
            ("nao_disponivel", "não existe"),
            ("nao_verificado", "sem evidência"),
            ("divergente", "divergem"),
        ],
    )
    def test_o_motivo_vai_escrito_na_celula(self, status, trecho):
        assert trecho in tab.Celula(valor=None, status=status).texto

    def test_status_desconhecido_ainda_diz_alguma_coisa(self):
        assert tab.Celula(valor=None, status="inventado").texto == tab.SEM_DADO

    def test_nunca_devolve_string_vazia(self):
        for status in ("", "nao_encontrado", "verificado"):
            assert tab.Celula(valor=None, status=status).texto.strip()

    def test_zero_e_falso_sao_valor_e_nao_ausencia(self):
        """`0 kg` de carga é um dado; `False` em paddle shifters também."""
        assert tab.Celula(valor=0, unidade="kg", status="verificado").texto == "0 kg"
        assert tab.Celula(valor=False, status="verificado").texto == "não"


class TestOCSV:
    def test_o_cabecalho_tem_fonte_e_data_por_veiculo(self):
        cabecalho = _tabela().cabecalho()
        assert "Ford Ranger Limited · fonte" in cabecalho
        assert "Toyota Hilux SRX Plus · data" in cabecalho

    def test_a_fonte_e_a_data_chegam_na_linha(self):
        texto = tab.para_csv(_tabela())
        assert "https://www.ford.com.br/ranger/" in texto
        assert "2026-09-01" in texto

    def test_as_ressalvas_viajam_no_rodape(self):
        """Se a ressalva ficar só na tela, a primeira cópia perde o que impede a leitura
        errada — e é a cópia que circula."""
        texto = tab.para_csv(_tabela())
        assert "ressalvas" in texto
        assert "categoria diferente" in texto

    def test_a_versao_dos_criterios_esta_no_arquivo(self):
        assert "2026-09-09" in tab.para_csv(_tabela())

    def test_tem_bom_para_o_excel_em_portugues(self):
        """Sem o BOM, "não disponível" abre como "nÃ£o disponÃ­vel" e a planilha inteira
        parece corrompida."""
        assert tab.para_csv(_tabela()).startswith("﻿")

    def test_a_celula_sem_valor_nao_sai_vazia_no_arquivo(self):
        texto = tab.para_csv(_tabela())
        assert "não encontrado em nenhuma fonte" in texto
        assert ";;" not in texto.split("ressalvas")[0].split("\r\n")[6], "célula vazia no meio"


class TestContagem:
    def test_campos_com_valor_conta_a_linha_e_nao_a_celula(self):
        assert _tabela().campos_com_valor == 2

    def test_linha_sem_nenhum_valor_nao_conta(self):
        vazia = tab.Linha(
            campo="x",
            grupo="y",
            rotulo="X",
            celulas=(tab.Celula(status="nao_encontrado"), tab.Celula(status="nao_encontrado")),
        )
        t = _tabela(linhas=[vazia])
        assert t.campos_com_valor == 0


class TestFormatoLongo:
    def test_uma_linha_por_veiculo_e_campo(self):
        assert len(arquivos.linhas_longas(_tabela())) == 4

    def test_o_esquema_nao_muda_com_o_numero_de_concorrentes(self):
        """Tabela cujo esquema muda a cada exportação não se carrega em warehouse: cada
        comparação exigiria uma migração."""
        uma = arquivos.linhas_longas(_tabela())
        t = _tabela()
        t.colunas.append(tab.Coluna(version_id="s10", rotulo="Chevrolet S10"))
        for linha in list(t.linhas):
            t.linhas[t.linhas.index(linha)] = tab.Linha(
                campo=linha.campo,
                grupo=linha.grupo,
                rotulo=linha.rotulo,
                celulas=(*linha.celulas, tab.Celula(valor=1, status="verificado")),
            )
        tres = arquivos.linhas_longas(t)
        assert set(uma[0]) == set(tres[0]) == set(arquivos.COLUNAS_DO_PARQUET)
        assert len(tres) == 6

    def test_a_referencia_esta_marcada(self):
        longas = arquivos.linhas_longas(_tabela())
        assert [linha["e_referencia"] for linha in longas[:2]] == [True, False]


class TestDDL:
    def test_o_ddl_cobre_todas_as_colunas_do_parquet(self):
        ddl = arquivos.ddl_do_bigquery()
        for coluna in arquivos.COLUNAS_DO_PARQUET:
            assert coluna in ddl, f"{coluna} fora do DDL"

    def test_valor_e_string_e_nao_numero(self):
        """A mesma coluna guarda 397, "sim", "2,8" e "não encontrado em nenhuma fonte".
        Tipar como número obrigaria a jogar fora as três últimas."""
        assert arquivos.TIPOS_DO_BIGQUERY["valor"] == "STRING"

    def test_particiona_por_data_e_agrupa_por_campo(self):
        ddl = arquivos.ddl_do_bigquery()
        assert "PARTITION BY DATE(gerado_em)" in ddl
        assert "CLUSTER BY campo" in ddl

    def test_o_dataset_e_configuravel(self):
        assert "`ford_bi.paridade`" in arquivos.ddl_do_bigquery(
            dataset="ford_bi", tabela_nome="paridade"
        )


class TestDependenciaQueFalta:
    def test_diz_o_que_instalar_em_vez_de_estourar(self, monkeypatch):
        """Planilha de zero byte só se descobre quebrada na frente de outra pessoa."""
        import builtins

        original = builtins.__import__

        def sem_openpyxl(nome, *args, **kwargs):
            if nome == "openpyxl":
                raise ModuleNotFoundError(nome)
            return original(nome, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", sem_openpyxl)
        with pytest.raises(arquivos.FormatoIndisponivel, match="uv sync --extra export"):
            arquivos.para_xlsx(_tabela(), __import__("pathlib").Path("x.xlsx"))
