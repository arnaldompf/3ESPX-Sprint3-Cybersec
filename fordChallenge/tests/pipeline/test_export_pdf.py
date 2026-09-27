"""O PDF do benchmark: a matriz, as fontes e as ressalvas — nessa ordem.

A lista de fontes é a metade do documento que justifica a outra: uma tabela de paridade
num PDF, sem as URLs e sem as datas, é indistinguível de um slide.
"""

from __future__ import annotations

from pipeline.export import pdf
from pipeline.export import tabela as tab


def _tabela() -> tab.Tabela:
    return tab.Tabela(
        titulo="Benchmark — Ford Ranger Limited",
        gerada_em="2026-09-13T09:00:00Z",
        versao_dos_criterios="2026-09-09",
        colunas=[
            tab.Coluna(version_id="f", rotulo="Ford Ranger Limited", e_referencia=True),
            tab.Coluna(
                version_id="h",
                rotulo="Toyota Hilux SRX Plus",
                comparabilidade="5/6 critérios atendidos",
                aviso="",
            ),
        ],
        linhas=[
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
                    ),
                    tab.Celula(
                        valor=204,
                        unidade="cv",
                        status="verificado",
                        situacao="ganhamos",
                        fonte_url="https://www.toyota.com.br/hilux/",
                        fonte_data="2026-09-02",
                    ),
                ),
            ),
            tab.Linha(
                campo="torque_nm",
                grupo="motorização",
                rotulo="Torque",
                celulas=(
                    tab.Celula(
                        valor=600,
                        unidade="Nm",
                        status="verificado",
                        fonte_url="https://www.ford.com.br/ranger/",
                        fonte_data="2026-09-01",
                    ),
                    tab.Celula(status="nao_encontrado", situacao="não sabemos"),
                ),
            ),
        ],
        ressalvas=["A Fiat Toro é de categoria diferente e entra marcada."],
    )


class TestAsFontes:
    def test_agrupa_por_endereco_em_vez_de_repetir(self):
        """Ninguém abre a mesma página duas vezes para conferir dois campos."""
        fontes = pdf.fontes_agrupadas(_tabela())
        assert len(fontes) == 2
        ford = next(f for f in fontes if "ford" in f[0])
        assert ford[2] == ["Potência", "Torque"]

    def test_a_data_anda_junto_do_endereco(self):
        """Fonte sem data não é conferível: é só um endereço."""
        for url, data, _ in pdf.fontes_agrupadas(_tabela()):
            assert url and data

    def test_celula_sem_fonte_nao_inventa_entrada(self):
        fontes = pdf.fontes_agrupadas(_tabela())
        assert all(url for url, _, _ in fontes)


class TestODocumento:
    def test_tem_as_tres_secoes_na_ordem(self):
        html = pdf.montar_html(_tabela())
        assert html.index("Matriz de paridade") < html.index("Fontes") < html.index("Ressalvas")

    def test_a_celula_sem_valor_traz_o_motivo(self):
        assert "não encontrado em nenhuma fonte" in pdf.montar_html(_tabela())

    def test_o_denominador_esta_no_cabecalho(self):
        assert "2 de 2 campos com valor" in pdf.montar_html(_tabela())

    def test_a_versao_dos_criterios_aparece(self):
        assert "2026-09-09" in pdf.montar_html(_tabela())

    def test_o_rodape_explica_os_dois_vazios(self):
        html = pdf.montar_html(_tabela())
        assert "não encontrado" in html and "não disponível" in html

    def test_sem_ressalva_diz_que_nao_ha_em_vez_de_omitir(self):
        t = _tabela()
        t.ressalvas = []
        assert "Nenhuma ressalva registrada" in pdf.montar_html(t)

    def test_sem_fonte_nenhuma_diz_isso_em_vez_de_sumir_com_a_secao(self):
        """Omitir a seção faria o documento parecer uma tabela sem procedência."""
        t = _tabela()
        t.linhas = [tab.Linha(campo="x", grupo="y", rotulo="X", celulas=(tab.Celula(valor=1),) * 2)]
        assert "Nenhum campo desta comparação tem fonte registrada" in pdf.montar_html(t)

    def test_o_html_escapa_o_que_vem_de_fora(self):
        t = _tabela()
        t.titulo = "<script>alerta()</script>"
        html = pdf.montar_html(t)
        assert "<script>alerta" not in html
        assert "&lt;script&gt;" in html


class TestGeracao:
    def test_grava_o_arquivo(self, tmp_path):
        resultado = pdf.gerar(_tabela(), nome="benchmark-teste", diretorio=tmp_path)
        assert resultado.caminho.exists()
        assert resultado.bytes_gerados > 0
        assert resultado.formato in {"pdf", "html"}
