"""WP-28 — o relatório para o cliente: `POST /comparisons/{par}/pdf` e `/reports/{arquivo}`.

Dois critérios de aceite vivem aqui: o documento **contém a seção "Onde a {concorrente}
leva vantagem"** e a **lista de fontes com datas**; e **nenhum texto contém "confiança",
"tier" ou "LLM"**.

O terceiro ponto que os testes guardam não está na spec e é o que impede um vazamento
silencioso: o arquivo é servido por rota **autenticada**, com o nome validado contra
travessia de diretório. O link do relatório vai para o WhatsApp de quem recebeu.
"""

from __future__ import annotations

import datetime as dt
import io
import re

import pytest

from api.app.models import Role
from pipeline.report import html as gerador
from pipeline.report import render

#: O extra `pdfgen` pode nao estar instalado (é opcional, por decisão de disco: D-12). Os
#: testes que exigem um PDF de verdade pulam nesse caso, e os de conteúdo continuam
#: valendo sobre o documento que for entregue — HTML ou PDF.
try:  # pragma: no cover - depende do ambiente
    import xhtml2pdf  # noqa: F401

    TEM_MOTOR_DE_PDF = True
except Exception:  # pragma: no cover - depende do ambiente
    TEM_MOTOR_DE_PDF = False

exige_motor_de_pdf = pytest.mark.skipif(
    not TEM_MOTOR_DE_PDF,
    reason="o extra `pdfgen` (xhtml2pdf) não está instalado neste ambiente",
)


@pytest.fixture
def vendedor(criar_usuario, logar):
    criar_usuario("vendedor@suno.example.com", Role.VENDEDOR)
    return logar("vendedor@suno.example.com")


@pytest.fixture
def gestor(criar_usuario, logar):
    criar_usuario("gestor@suno.example.com", Role.GESTOR)
    return logar("gestor@suno.example.com")


@pytest.fixture
def fichas(catalogo):
    from api.app.db import session_scope
    from api.app.models import Evidence, SpecValue

    with session_scope() as sessao:
        ford_ev = Evidence(
            source_url="https://www.ford.com.br/ranger-raptor",
            tier=1,
            quote="Potência 397 cv",
            captured_at=dt.datetime(2026, 9, 1),
        )
        conc_ev = Evidence(
            source_url="https://www.toyota.com.br/hilux",
            tier=1,
            quote="204 cv",
            captured_at=dt.datetime(2026, 9, 2),
        )
        sessao.add(ford_ev)
        sessao.add(conc_ev)
        sessao.flush()
        for version_id, evidencia, linhas in (
            (
                catalogo["raptor"],
                ford_ev,
                [
                    ("potencia_cv", 397, "cv"),
                    ("torque_nm", 583, "Nm"),
                    ("capacidade_carga_kg", 620, "kg"),
                    ("capacidade_reboque_kg", 2500, "kg"),
                    ("combustivel", "gasolina", None),
                    ("consumo_urbano_kml", 7.2, "km/l"),
                ],
            ),
            (
                catalogo["srx"],
                conc_ev,
                [
                    ("potencia_cv", 204, "cv"),
                    ("torque_nm", 500, "Nm"),
                    ("capacidade_carga_kg", 1005, "kg"),
                    ("capacidade_reboque_kg", 3500, "kg"),
                    ("combustivel", "diesel", None),
                    ("consumo_urbano_kml", 9.7, "km/l"),
                ],
            ),
        ):
            for campo, valor, unidade in linhas:
                sessao.add(
                    SpecValue(
                        version_id=version_id,
                        field=campo,
                        value_json=valor,
                        unit=unidade,
                        status="verificado",
                        confidence=0.95,
                        evidence_id=evidencia.id,
                    )
                )
        sessao.commit()
    return catalogo


def texto_do_documento(resposta) -> str:
    """O texto do documento **entregue**, seja ele PDF ou HTML.

    As asserções de conteúdo valem sobre o arquivo que chega ao cliente, não sobre o HTML
    intermediário: é a única checagem que pega uma seção que o motor de PDF deixou cair.
    O texto do PDF sai pelo `pypdf` (dependência de base do projeto) e passa por um
    aperto de espaços em branco, porque o motor quebra linha no meio da frase.
    """
    if resposta.headers["content-type"].startswith("application/pdf"):
        from pypdf import PdfReader

        leitor = PdfReader(io.BytesIO(resposta.content))
        bruto = " ".join(pagina.extract_text() or "" for pagina in leitor.pages)
        return re.sub(r"\s+", " ", bruto)
    return resposta.text


def par(catalogo) -> str:
    return f"{catalogo['raptor']}:{catalogo['srx']}"


def gerar_relatorio(cliente, headers, catalogo, **corpo):
    """Pede o relatório e roda o worker uma vez — o mesmo caminho da demo."""
    from api.app.db import session_scope
    from api.app.models import Job
    from pipeline.worker import executar_job

    resposta = cliente.post(f"/api/v1/comparisons/{par(catalogo)}/pdf", headers=headers, json=corpo)
    assert resposta.status_code == 202, resposta.text
    job_id = resposta.json()["job_id"]

    with session_scope() as sessao:
        job = sessao.get(Job, job_id)
        assert job is not None
        executar_job(sessao, job)

    return job_id


class TestOFluxoAssincrono:
    def test_devolve_202_com_location(self, cliente_auth, fichas, vendedor):
        """Segurar a requisição enquanto monta duas fichas é timeout no meio da venda."""
        resposta = cliente_auth.post(
            f"/api/v1/comparisons/{par(fichas)}/pdf", headers=vendedor, json={}
        )
        assert resposta.status_code == 202
        assert resposta.headers["Location"].endswith(resposta.json()["job_id"])
        assert resposta.json()["status"] == "pendente"

    def test_o_job_concluido_aponta_para_o_arquivo(self, cliente_auth, fichas, vendedor):
        job_id = gerar_relatorio(cliente_auth, vendedor, fichas)
        corpo = cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=vendedor).json()
        assert corpo["status"] == "concluido"
        assert corpo["result_url"].startswith("/api/v1/reports/")

    def test_par_invalido_e_422(self, cliente_auth, fichas, vendedor):
        resposta = cliente_auth.post(
            "/api/v1/comparisons/sem-separador/pdf", headers=vendedor, json={}
        )
        assert resposta.status_code == 422

    def test_versao_inexistente_e_404(self, cliente_auth, fichas, vendedor):
        resposta = cliente_auth.post(
            f"/api/v1/comparisons/{fichas['raptor']}:nao-existe/pdf", headers=vendedor, json={}
        )
        assert resposta.status_code == 404

    def test_o_corpo_nao_aceita_contato_do_cliente(self, cliente_auth, fichas, vendedor):
        """Nenhum contato do cliente é armazenado (`specs/WP-28.md`)."""
        resposta = cliente_auth.post(
            f"/api/v1/comparisons/{par(fichas)}/pdf",
            headers=vendedor,
            json={"email_do_cliente": "cliente@exemplo.com"},
        )
        assert resposta.status_code == 422


class TestOConteudoDoDocumento:
    def test_criterio_de_aceite_tem_a_secao_do_concorrente_e_as_fontes(
        self, cliente_auth, fichas, vendedor
    ):
        """Critério: contém "Onde a {concorrente} leva vantagem" e as fontes com datas."""
        job_id = gerar_relatorio(
            cliente_auth,
            vendedor,
            fichas,
            needs_profile={"prioridades_rank": ["desempenho", "capacidade", "economia"]},
        )
        arquivo = cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=vendedor).json()["result_url"]
        documento = texto_do_documento(cliente_auth.get(arquivo, headers=vendedor))

        assert "Onde a Toyota Hilux SRX Plus AT (Cabine Dupla) leva vantagem" in documento
        assert "Fontes consultadas" in documento
        assert "https://www.ford.com.br/ranger-raptor" in documento
        assert "https://www.toyota.com.br/hilux" in documento
        # As datas de cada fonte, e são **diferentes** entre as duas.
        assert "01/09/2026" in documento
        assert "02/09/2026" in documento

    def test_criterio_de_aceite_nenhum_termo_interno_no_documento(
        self, cliente_auth, fichas, vendedor
    ):
        """Critério: nenhum texto contém "confiança", "tier" ou "LLM"."""
        job_id = gerar_relatorio(cliente_auth, vendedor, fichas)
        arquivo = cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=vendedor).json()["result_url"]
        documento = texto_do_documento(cliente_auth.get(arquivo, headers=vendedor))
        assert gerador.termos_internos_no_texto(documento) == []
        for proibido in ("tier", "confiança", "LLM", "prompt", "token"):
            assert proibido.lower() not in documento.lower()

    def test_o_rodape_de_ressalvas_esta_no_documento(self, cliente_auth, fichas, vendedor):
        job_id = gerar_relatorio(cliente_auth, vendedor, fichas)
        arquivo = cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=vendedor).json()["result_url"]
        documento = texto_do_documento(cliente_auth.get(arquivo, headers=vendedor))
        assert "não é proposta comercial" in documento
        assert "confirme na concessionária" in documento

    def test_o_documento_traz_a_ficha_comparada_com_os_dois_valores(
        self, cliente_auth, fichas, vendedor
    ):
        job_id = gerar_relatorio(
            cliente_auth,
            vendedor,
            fichas,
            needs_profile={"prioridades_rank": ["desempenho"]},
        )
        arquivo = cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=vendedor).json()["result_url"]
        documento = texto_do_documento(cliente_auth.get(arquivo, headers=vendedor))
        assert "Ficha comparada" in documento
        assert "397 cv" in documento
        assert "204 cv" in documento

    def test_o_documento_diz_o_que_a_estimativa_de_custo_nao_inclui(
        self, cliente_auth, fichas, vendedor
    ):
        job_id = gerar_relatorio(
            cliente_auth,
            vendedor,
            fichas,
            needs_profile={
                "prioridades_rank": ["economia"],
                "km_mes": 2500,
                "combustivel_preco": {"diesel": 6.20, "gasolina": 6.00},
            },
        )
        arquivo = cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=vendedor).json()["result_url"]
        documento = texto_do_documento(cliente_auth.get(arquivo, headers=vendedor))
        assert "Custo estimado de combustível" in documento
        assert "Não inclui seguro, manutenção ou depreciação" in documento


class TestOArquivoServido:
    def test_sem_credencial_da_401(self, cliente_auth, fichas, vendedor):
        """O link vive no WhatsApp de quem recebeu; sem autenticação, seria vazamento."""
        job_id = gerar_relatorio(cliente_auth, vendedor, fichas)
        arquivo = cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=vendedor).json()["result_url"]
        assert cliente_auth.get(arquivo).status_code == 401

    @pytest.mark.parametrize(
        "nome",
        [
            "../../.env",
            "..%2f..%2f.env",
            "relatorio.txt",
            "relatorio",
            "relatorio.pdf.exe",
        ],
    )
    def test_nome_fora_do_padrao_e_recusado(self, cliente_auth, fichas, vendedor, nome):
        resposta = cliente_auth.get(f"/api/v1/reports/{nome}", headers=vendedor)
        assert resposta.status_code in {404, 422}
        assert resposta.status_code != 200

    def test_arquivo_inexistente_diz_como_gerar(self, cliente_auth, fichas, vendedor):
        resposta = cliente_auth.get("/api/v1/reports/relatorio-nao-existe.html", headers=vendedor)
        assert resposta.status_code == 404
        assert "gerado por um job" in resposta.json()["detail"]


class TestORenderizador:
    def test_declara_o_formato_e_o_motivo(self, cliente_auth, fichas, vendedor):
        """Nesta máquina o WeasyPrint não renderiza, e o job **diz** isso.

        Um PDF de zero byte com status "concluído" seria pior que a ausência: alguém abriria
        o link na frente do cliente. O formato e o motivo ficam no payload do job.
        """
        from api.app.db import session_scope
        from api.app.models import Job

        job_id = gerar_relatorio(cliente_auth, vendedor, fichas)
        with session_scope() as sessao:
            job = sessao.get(Job, job_id)
            assert job is not None
            payload = job.payload or {}

        assert payload["formato"] in {"pdf", "html"}
        assert payload["bytes"] > 500
        if payload["formato"] == "html":
            assert "WeasyPrint" in payload["motivo_do_formato"]
            assert "GTK" in payload["motivo_do_formato"]

    def test_a_lista_de_fontes_nao_imprime_nome_de_campo_do_banco(self):
        """QA-BUG-10: a seção "Fontes consultadas" saía com `adas_itens, airbags_qtd, …`.

        O documento vai para o cliente por WhatsApp. A tabela comparada acima já
        humaniza o nome do campo ("Capacidade carga kg"); a lista de fontes era a única
        parte que imprimia o nome cru do banco, com underscore. Medido em 11/09/2026 no
        PDF gerado pela tela: `adas_itens, adas_nome_comercial, airbags_qtd, altura_mm,
        aspiracao, bloqueio_diferencial, camera_360, capacidade_carga_kg, …`.
        """
        relatorio = gerador.Relatorio(
            rotulo_ford="Ford",
            rotulo_concorrente="Concorrente",
            gerado_em="2026-09-11T12:00:00",
            fontes=[
                gerador.Fonte(
                    url="https://www.ford.com.br/ranger",
                    data="2026-09-01",
                    campos=["adas_itens", "capacidade_carga_kg", "preco_fipe_brl"],
                )
            ],
        )
        html = gerador.montar(relatorio)

        assert "adas_itens" not in html
        assert "capacidade_carga_kg" not in html
        assert "preco_fipe_brl" not in html
        assert "Adas itens" in html
        assert "Capacidade carga kg" in html
        # A URL tem underscore legítimo e não pode ser mexida.
        assert "https://www.ford.com.br/ranger" in html

    def test_o_gerador_de_html_e_deterministico(self):
        """O mesmo relatório duas vezes dá o mesmo documento, byte a byte."""
        relatorio = gerador.Relatorio(
            rotulo_ford="Ford",
            rotulo_concorrente="Concorrente",
            gerado_em="2026-09-09T12:00:00",
            linhas=[gerador.LinhaDeComparacao("potencia_cv", "Potência", "397 cv", "204 cv")],
        )
        assert gerador.montar(relatorio) == gerador.montar(relatorio)

    def test_o_html_escapa_o_que_vem_da_fonte(self):
        """O texto vem de páginas de terceiros: `<script>` numa citação não pode virar script."""
        relatorio = gerador.Relatorio(
            rotulo_ford="Ford <script>alert(1)</script>",
            rotulo_concorrente="Concorrente",
            pontos=["Ponto com <img src=x onerror=alert(1)>"],
        )
        documento = gerador.montar(relatorio)
        assert "<script>alert(1)</script>" not in documento
        assert "&lt;script&gt;" in documento
        assert "onerror=alert(1)>" not in documento

    def test_sem_ponto_do_concorrente_a_secao_nao_aparece_vazia(self):
        relatorio = gerador.Relatorio(rotulo_ford="Ford", rotulo_concorrente="Concorrente")
        documento = gerador.montar(relatorio)
        assert "leva vantagem" not in documento

    def test_o_aviso_de_comparabilidade_vem_ANTES_da_tabela(self):
        """Depois dela, o leitor já formou a conclusão que o aviso deveria qualificar."""
        relatorio = gerador.Relatorio(
            rotulo_ford="Ford",
            rotulo_concorrente="Concorrente",
            aviso_de_comparabilidade="Par não comparável: combustível diferente.",
            linhas=[gerador.LinhaDeComparacao("potencia_cv", "Potência", "397", "204")],
        )
        documento = gerador.montar(relatorio)
        assert documento.index("não comparável") < documento.index("Ficha comparada")


def _relatorio_completo() -> gerador.Relatorio:
    """Um relatório com **todas** as seções que o gerador sabe produzir."""
    return gerador.Relatorio(
        rotulo_ford="Ford Ranger Raptor 3.0 V6 Bi-Turbo (Cabine Dupla)",
        rotulo_concorrente="Toyota Hilux SRX Plus AT (Cabine Dupla)",
        gerado_em="2026-09-09T12:00:00",
        aderencia_ford="3,8 de 10",
        aderencia_concorrente="7,8 de 10",
        rotulo_da_aderencia="Aderência ao perfil informado — não é um ranking de qualidade",
        linhas=[
            gerador.LinhaDeComparacao(
                "potencia_cv", "Potência", "397 cv", "204 cv", quem_leva="ford"
            ),
            gerador.LinhaDeComparacao(
                "capacidade_carga_kg",
                "Capacidade de carga",
                "620 kg",
                "1.005 kg",
                quem_leva="concorrente",
            ),
        ],
        pontos=["Para quem prioriza desempenho: 397 cv contra 204 cv (site oficial)."],
        ponto_do_concorrente="Onde a Hilux leva vantagem: 1.005 kg contra 620 kg.",
        custo_ford="R$ 1.875,00 por mês",
        custo_concorrente="R$ 1.534,65 por mês",
        diferenca_anual="Diferença estimada de R$ 4.084,20 por ano.",
        fontes=[
            gerador.Fonte("https://www.ford.com.br/ranger-raptor", "2026-09-01", ["potencia_cv"]),
            gerador.Fonte("https://www.toyota.com.br/hilux", "2026-09-02", ["carga_kg"]),
        ],
        aviso_de_comparabilidade="Par não comparável: combustível diferente.",
    )


class TestOPdfDeVerdade:
    """O botão entrega um `.pdf` — arquivo que começa com `%PDF-`, não HTML renomeado."""

    @exige_motor_de_pdf
    def test_o_arquivo_entregue_comeca_com_os_bytes_de_pdf(self, cliente_auth, fichas, vendedor):
        job_id = gerar_relatorio(cliente_auth, vendedor, fichas)
        arquivo = cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=vendedor).json()["result_url"]
        assert arquivo.endswith(".pdf"), arquivo

        resposta = cliente_auth.get(arquivo, headers=vendedor)
        assert resposta.status_code == 200
        assert resposta.headers["content-type"] == "application/pdf"
        assert resposta.content[:5] == b"%PDF-", resposta.content[:32]
        assert len(resposta.content) > 1000

    @exige_motor_de_pdf
    def test_o_pdf_mantem_todo_o_conteudo_obrigatorio(self, cliente_auth, fichas, vendedor):
        """Simplificar o CSS para o motor de reserva não pode simplificar o documento."""
        job_id = gerar_relatorio(
            cliente_auth,
            vendedor,
            fichas,
            needs_profile={
                "prioridades_rank": ["desempenho", "capacidade", "economia"],
                "km_mes": 2500,
                "combustivel_preco": {"diesel": 6.20, "gasolina": 6.00},
            },
        )
        arquivo = cliente_auth.get(f"/api/v1/jobs/{job_id}", headers=vendedor).json()["result_url"]
        resposta = cliente_auth.get(arquivo, headers=vendedor)
        assert resposta.content[:5] == b"%PDF-"
        texto = texto_do_documento(resposta)

        for obrigatorio in (
            "Comparativo técnico",
            "Onde a Toyota Hilux SRX Plus AT (Cabine Dupla) leva vantagem",
            "Fontes consultadas",
            "https://www.ford.com.br/ranger-raptor",
            "https://www.toyota.com.br/hilux",
            "01/09/2026",
            "02/09/2026",
            "Ficha comparada",
            "397 cv",
            "204 cv",
            "Custo estimado de combustível",
            "Aderência ao perfil informado",
            "não é proposta comercial",
            "confirme na concessionária",
        ):
            assert obrigatorio in texto, f"o PDF perdeu {obrigatorio!r}"
        assert gerador.termos_internos_no_texto(texto) == []

    @exige_motor_de_pdf
    def test_o_payload_do_job_diz_qual_motor_gerou(self, cliente_auth, fichas, vendedor):
        """Proveniência do arquivo não é adivinhação: o motor usado fica registrado."""
        from api.app.db import session_scope
        from api.app.models import Job

        job_id = gerar_relatorio(cliente_auth, vendedor, fichas)
        with session_scope() as sessao:
            job = sessao.get(Job, job_id)
            assert job is not None
            payload = job.payload or {}

        assert payload["formato"] == "pdf"
        assert payload["motor"] in render.MOTORES
        assert payload["renderizador"].startswith(payload["motor"])
        assert payload["arquivo"].endswith(".pdf")


class TestAOrdemDosMotores:
    """WeasyPrint primeiro, xhtml2pdf de reserva, HTML por último — declarado e visível."""

    def test_a_ordem_e_declarada_no_codigo(self):
        assert render.MOTORES == ("weasyprint", "xhtml2pdf")

    def test_o_diagnostico_diz_motor_por_motor_se_da_e_por_que_nao(self):
        diagnostico = render.motores_de_pdf()
        assert [m.nome for m in diagnostico] == list(render.MOTORES)
        for motor in diagnostico:
            # Nunca um "não dá" sem o motivo por escrito.
            assert motor.disponivel or motor.motivo, motor

    @exige_motor_de_pdf
    def test_o_reserva_gera_pdf_e_registra_que_e_reserva(self, tmp_path):
        documento = gerador.montar(_relatorio_completo())
        resultado = render.renderizar(
            documento, "reserva", diretorio=tmp_path, motores=("xhtml2pdf",)
        )
        assert resultado.formato == "pdf"
        assert resultado.motor == "xhtml2pdf"
        assert resultado.caminho.read_bytes()[:5] == b"%PDF-"
        assert resultado.bytes_gerados == resultado.caminho.stat().st_size

    def test_sem_motor_nenhum_sai_html_com_o_motivo_por_escrito(self, tmp_path):
        documento = gerador.montar(_relatorio_completo())
        resultado = render.renderizar(documento, "sem-motor", diretorio=tmp_path, motores=())
        assert resultado.formato == "html"
        assert resultado.motor == "html"
        for esperado in ("WeasyPrint", "GTK", "xhtml2pdf", "pdfgen"):
            assert esperado in resultado.motivo, resultado.motivo

    def test_motor_que_nao_existe_nao_estoura_e_diz_o_motivo(self, tmp_path):
        documento = gerador.montar(_relatorio_completo())
        resultado = render.renderizar(
            documento, "inexistente", diretorio=tmp_path, motores=("motor-de-mentira",)
        )
        assert resultado.formato == "html"
        assert "motor-de-mentira" in resultado.motivo

    def test_o_resultado_leva_o_motor_para_os_metadados(self, tmp_path):
        documento = gerador.montar(_relatorio_completo())
        resultado = render.renderizar(documento, "metadados", diretorio=tmp_path, motores=())
        assert resultado.to_dict()["motor"] == "html"
        assert resultado.to_dict()["renderizador"] == resultado.renderizador


class TestOCssDoMotorDeReserva:
    """Simplifica o CSS, nunca o conteúdo."""

    def test_trocar_o_css_nao_mexe_em_uma_linha_do_conteudo(self):
        documento = gerador.montar(_relatorio_completo())
        simples = gerador.com_css(documento, gerador.CSS_XHTML2PDF)

        assert gerador.CSS_XHTML2PDF in simples
        assert gerador.CSS not in simples

        def sem_estilo(texto: str) -> str:
            return re.sub(r"<style>.*?</style>", "<style/>", texto, flags=re.DOTALL)

        assert sem_estilo(documento) == sem_estilo(simples)

    def test_o_css_de_reserva_nao_usa_o_que_o_motor_nao_entende(self):
        """xhtml2pdf ignora (com aviso) o que não implementa; melhor não pedir."""
        for proibido in (
            "flex",
            "grid",
            "var(",
            "word-break",
            "border-collapse",
            "font-variant-numeric",
            "@media",
        ):
            assert proibido not in gerador.CSS_XHTML2PDF, proibido

    def test_a_geracao_recusa_recurso_externo(self):
        """Nada de rede na geração: nem fonte, nem imagem de fora."""
        with pytest.raises(ValueError, match="recurso externo"):
            render.recusar_recurso_externo("https://fonts.googleapis.com/css?family=X", "")
