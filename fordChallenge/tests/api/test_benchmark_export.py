"""`POST /benchmark/export` — a comparação sai da tela em arquivo.

O que estes testes guardam é a promessa que se perde primeiro numa exportação: **o arquivo
tem de continuar honesto longe da tela que o gerou.** Fonte e data na linha, motivo escrito
onde não há valor, ressalva de comparabilidade dentro do arquivo, e o formato que não pôde
ser gerado dito com o nome — nunca um arquivo de zero byte.

E a recusa que não é técnica: **o SpecRadar não carrega no BigQuery sozinho.** Ele entrega
o Parquet, o DDL e o comando. Enviar dado para fora do ambiente onde ele foi produzido é
decisão de quem responde pelo dado.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.app.models import Role

EXPORT = "/api/v1/benchmark/export"


@pytest.fixture
def com_benchmark(monkeypatch: pytest.MonkeyPatch, schema_criado: None) -> Iterator[TestClient]:
    monkeypatch.setenv("BENCHMARK_ENABLED", "1")
    from api.app.main import create_app

    with TestClient(create_app()) as cliente:
        yield cliente


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


@pytest.fixture
def par(schema_criado: None) -> dict[str, str]:
    """Uma Ranger com potência provada e uma Hilux com potência menor.

    A Ranger também tem um campo **sem** valor, porque a célula vazia é metade do que
    esta exportação promete.
    """
    from api.app.db import session_scope
    from api.app.models import Brand, Evidence, SpecValue, VehicleModel, Version

    with session_scope() as sessao:
        ford, toyota = Brand(nome="Ford"), Brand(nome="Toyota")
        sessao.add(ford)
        sessao.add(toyota)
        sessao.flush()
        m_ranger = VehicleModel(brand_id=ford.id, nome="Ranger", segmento="picape média")
        m_hilux = VehicleModel(brand_id=toyota.id, nome="Hilux", segmento="picape média")
        sessao.add(m_ranger)
        sessao.add(m_hilux)
        sessao.flush()
        ranger = Version(model_id=m_ranger.id, nome_exato="Limited", ano_modelo=2026)
        hilux = Version(model_id=m_hilux.id, nome_exato="SRX Plus AT", ano_modelo=2026)
        sessao.add(ranger)
        sessao.add(hilux)
        sessao.flush()

        for versao, potencia, url in (
            (ranger, 250, "https://www.ford.com.br/ranger/"),
            (hilux, 204, "https://www.toyota.com.br/hilux/"),
        ):
            evidencia = Evidence(
                source_url=url,
                tier=1,
                quote=f"{potencia} cv de potência",
                captured_at=dt.datetime(2026, 9, 1),
                raw_value=f"{potencia} cv",
            )
            sessao.add(evidencia)
            sessao.flush()
            sessao.add(
                SpecValue(
                    version_id=versao.id,
                    field="potencia_cv",
                    value_json=potencia,
                    unit="cv",
                    status="verificado",
                    confidence=0.95,
                    evidence_id=evidencia.id,
                )
            )
        return {"ranger": ranger.id, "hilux": hilux.id}


def _exportar(cliente, headers, par: dict[str, str]):
    return cliente.post(
        EXPORT,
        json={"ford_version": par["ranger"], "competitors": [par["hilux"]]},
        headers=headers,
    )


class TestOsArquivos:
    def test_gera_os_seis_arquivos(self, com_benchmark, par, analista):
        corpo = _exportar(com_benchmark, analista, par).json()
        nomes = sorted(a["nome"] for a in corpo["arquivos"])
        # O documento é `benchmark.pdf` ou `benchmark.html`: sem motor de PDF, ele desce
        # um degrau **com o motivo dentro**, em vez de gravar um `.pdf` truncado.
        documento = next(n for n in nomes if n.startswith("benchmark."))
        assert documento in {"benchmark.pdf", "benchmark.html"}
        assert sorted(n for n in nomes if n != documento) == [
            "LEIA-ME.md",
            "bigquery.sql",
            "matriz.csv",
            "matriz.parquet",
            "matriz.xlsx",
        ]
        assert [r["formato"] for r in corpo["recusados"]] in ([], ["pdf"])

    def test_o_pdf_traz_a_matriz_as_fontes_e_as_ressalvas(self, com_benchmark, par, analista):
        """A lista de fontes é a metade do documento que justifica a outra: uma tabela de
        paridade sem URL e sem data é indistinguível de um slide."""
        from pipeline.export import pdf as gerador
        from pipeline.export import tabela as tab

        t = tab.Tabela(titulo="t", gerada_em="2026-09-13T09:00:00Z")
        html = gerador.montar_html(t)
        assert html.index("Matriz de paridade") < html.index("Fontes") < html.index("Ressalvas")

    def test_nenhum_arquivo_sai_com_zero_byte(self, com_benchmark, par, analista):
        corpo = _exportar(com_benchmark, analista, par).json()
        for arquivo in corpo["arquivos"]:
            assert arquivo["bytes"] > 0, arquivo["nome"]

    def test_a_mesma_comparacao_no_mesmo_dia_reusa_a_pasta(self, com_benchmark, par, analista):
        """Exportar duas vezes não enche o disco com cópias idênticas."""
        primeira = _exportar(com_benchmark, analista, par).json()["pasta"]
        segunda = _exportar(com_benchmark, analista, par).json()["pasta"]
        assert primeira == segunda

    def test_o_denominador_honesto_viaja_na_resposta(self, com_benchmark, par, analista):
        corpo = _exportar(com_benchmark, analista, par).json()
        assert corpo["campos"] > corpo["campos_com_valor"] > 0


class TestOConteudoDoCSV:
    @pytest.fixture
    def texto(self, com_benchmark, par, analista) -> str:
        corpo = _exportar(com_benchmark, analista, par).json()
        url = next(a["url"] for a in corpo["arquivos"] if a["nome"] == "matriz.csv")
        return com_benchmark.get(url, headers=analista).content.decode("utf-8")

    def test_a_fonte_e_a_data_estao_na_linha(self, texto):
        """O arquivo não tem gaveta: o que a pessoa clicaria para ver tem de estar na linha."""
        assert "https://www.ford.com.br/ranger/" in texto
        assert "2026-09-01" in texto

    def test_a_data_e_a_da_captura_e_nao_a_de_hoje(self, texto):
        hoje = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
        linha = next(linha for linha in texto.splitlines() if "potencia" in linha)
        assert "2026-09-01" in linha
        if hoje != "2026-09-01":
            assert hoje not in linha

    def test_celula_sem_valor_traz_o_motivo(self, texto):
        assert "não encontrado em nenhuma fonte" in texto

    def test_a_situacao_diz_ganhamos_por_extenso(self, texto):
        """Num CSV aberto seis meses depois não há legenda ao lado: vai a palavra."""
        assert "ganhamos" in texto

    def test_as_ressalvas_estao_no_arquivo(self, texto):
        assert "ressalvas" in texto

    def test_o_cabecalho_nomeia_os_dois_veiculos(self, texto):
        cabecalho = next(linha for linha in texto.splitlines() if linha.startswith("campo;"))
        colunas = next(csv.reader(io.StringIO(cabecalho), delimiter=";"))
        assert any("Ford Ranger Limited" in c for c in colunas)
        assert any("Toyota Hilux SRX Plus AT" in c for c in colunas)


class TestAStackFord:
    def test_o_ddl_vem_pronto(self, com_benchmark, par, analista):
        corpo = _exportar(com_benchmark, analista, par).json()
        url = next(a["url"] for a in corpo["arquivos"] if a["nome"] == "bigquery.sql")
        sql = com_benchmark.get(url, headers=analista).content.decode("utf-8")
        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "PARTITION BY DATE(gerado_em)" in sql

    def test_o_leia_me_diz_que_a_ferramenta_nao_carrega_sozinha(self, com_benchmark, par, analista):
        """Enviar dado para fora do ambiente onde ele foi produzido é decisão de quem
        responde pelo dado, não do processo que o gerou."""
        corpo = _exportar(com_benchmark, analista, par).json()
        url = next(a["url"] for a in corpo["arquivos"] if a["nome"] == "LEIA-ME.md")
        texto = com_benchmark.get(url, headers=analista).content.decode("utf-8")
        assert "não executa esse carregamento sozinho" in texto
        assert "bq load" in texto
        assert "não envia dado para fora" in corpo["carregamento_no_bigquery"]

    def test_o_parquet_abre_e_tem_o_esquema_fixo(self, com_benchmark, par, analista):
        import pandas as pd

        from pipeline.export import COLUNAS_DO_PARQUET

        corpo = _exportar(com_benchmark, analista, par).json()
        url = next(a["url"] for a in corpo["arquivos"] if a["nome"] == "matriz.parquet")
        dados = com_benchmark.get(url, headers=analista).content
        quadro = pd.read_parquet(io.BytesIO(dados))
        assert list(quadro.columns) == list(COLUNAS_DO_PARQUET)
        assert quadro["e_referencia"].sum() == corpo["campos"], "uma linha por campo na Ford"


class TestAsRecusas:
    def test_nome_de_arquivo_invalido_e_422(self, com_benchmark, par, analista):
        """A rota lê caminho vindo da URL, e `../../.env` é o primeiro teste que se faz."""
        corpo = _exportar(com_benchmark, analista, par).json()
        resposta = com_benchmark.get(
            f"/api/v1/benchmark/export/{corpo['pasta']}/..%2F..%2F.env", headers=analista
        )
        assert resposta.status_code in {404, 422}

    def test_arquivo_inexistente_e_404(self, com_benchmark, par, analista):
        corpo = _exportar(com_benchmark, analista, par).json()
        resposta = com_benchmark.get(
            f"/api/v1/benchmark/export/{corpo['pasta']}/nao-existe.csv", headers=analista
        )
        assert resposta.status_code == 404

    def test_sem_concorrente_e_422(self, com_benchmark, par, analista):
        resposta = com_benchmark.post(
            EXPORT,
            json={"ford_version": par["ranger"], "competitors": []},
            headers=analista,
        )
        assert resposta.status_code == 422

    def test_a_referencia_nao_pode_ser_concorrente_de_si_mesma(self, com_benchmark, par, analista):
        resposta = com_benchmark.post(
            EXPORT,
            json={"ford_version": par["ranger"], "competitors": [par["ranger"]]},
            headers=analista,
        )
        assert resposta.status_code == 422

    def test_campo_desconhecido_no_corpo_e_recusado(self, com_benchmark, par, analista):
        """`extra="forbid"`: campo novo é rejeitado até ser declarado."""
        resposta = com_benchmark.post(
            EXPORT,
            json={
                "ford_version": par["ranger"],
                "competitors": [par["hilux"]],
                "carregar_no_bigquery": True,
            },
            headers=analista,
        )
        assert resposta.status_code == 422
