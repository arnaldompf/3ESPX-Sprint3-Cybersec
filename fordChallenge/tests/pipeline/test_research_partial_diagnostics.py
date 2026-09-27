from pipeline.parse.pdf import DocumentoPdf
from pipeline.research.diagnostics import diagnose
from pipeline.research.planner import Alvo
from pipeline.research.run import Fonte
from pipeline.schema import empty_spec


def test_partial_pdf_is_not_reported_as_document_without_information():
    text = "Ford Ranger Limited 3.0 V6 ano-modelo 2027 Brasil"
    source = Fonte(
        "https://ford.com.br/ficha.pdf",
        1,
        "oficial",
        "q",
        texto=text,
        baixada=True,
        parse_status="partial",
        documento_pdf=DocumentoPdf(
            markdown=text,
            paginas=[text, ""],
            tabelas=[],
            motor="pdfplumber",
            status="partial",
            diagnosticos=[{"pagina": 2, "status": "needs_ocr"}],
        ),
    )
    result = diagnose(
        empty_spec(),
        Alvo("Ford", "Ranger", "Limited 3.0 V6", 2027),
        [source],
        [],
        set(),
        "rodadas",
        2,
    )
    assert result[0]["etapa_em_que_parou"] == "leitura_parcial_pdf"
    assert result[0]["documentos_com_leitura_pendente"][0]["paginas"] == [
        {"pagina": 2, "status": "needs_ocr"}
    ]


def test_unread_blocks_are_exposed_without_claiming_field_is_present():
    text = "Ford Ranger Limited 3.0 V6 ano-modelo 2027 Brasil"
    source = Fonte("https://ford.com.br/ficha", 1, "oficial", "q", texto=text, baixada=True)
    result = diagnose(
        empty_spec(),
        Alvo("Ford", "Ranger", "Limited 3.0 V6", 2027),
        [source],
        [],
        set(),
        "rodadas",
        2,
        leituras={source.source_id: {"pendentes": 3, "total": 4, "concluidos": 1}},
    )
    assert result[0]["etapa_em_que_parou"] == "blocos_ainda_nao_lidos"
    pending = result[0]["documentos_com_leitura_pendente"][0]
    assert pending["blocos_pendentes"] == 3
    assert pending["campo_presente_confirmado"] is False
