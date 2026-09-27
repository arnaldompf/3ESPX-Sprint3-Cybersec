"""Identidade de uma coluna não herda motor/ano nem conflito da coluna vizinha."""

from dataclasses import replace

import pytest

from pipeline.extract.run import Documento, extrair_documento
from pipeline.parse.version_slicer import Celula

VERSAO = "Limited 3.0 V6 Diesel 4WD AT"


def document(*, year="2027", engine="3.0 V6 Diesel", transmission="automático", traction="4WD"):
    rows = [
        ("Motor", engine),
        ("Câmbio", transmission),
        ("Tração", traction),
        ("Potência", "250 cv"),
    ]
    title = "Ford Ranger Brasil" + (f" ano-modelo {year}" if year else "")
    text = title + "\nVersões | XL 2.0 Diesel 4x2 MT | Limited\n"
    text += "Câmbio: manual | automático\nTração: 4x2 | 4WD\nMotor: 2.0 Diesel | " + engine
    text += "\nPotência: 170 cv | 250 cv\n"
    return Documento(
        texto=text,
        source_id="catalogo",
        url="https://www.ford.com.br/ranger.pdf",
        tier=1,
        multiversao=True,
        celulas=tuple(
            Celula(label, value, 2, (2,), ("Limited",), pagina=1, linha=i)
            for i, (label, value) in enumerate(rows)
        ),
    )


def extract(doc):
    return extrair_documento(
        doc,
        {"potencia_cv"},
        marca="Ford",
        modelo_veiculo="Ranger",
        versao=VERSAO,
        ano_modelo=2027,
        permitir_llm=False,
    )


def test_coluna_at_4wd_nao_herda_contradicao_manual_4x2_da_vizinha():
    result = extract(document())
    assert [c.valor for c in result.candidatos] == [250]
    assert all(c.de_celula for c in result.candidatos)


@pytest.mark.parametrize(
    "kwargs", [{"engine": "2.0 Diesel"}, {"transmission": "manual"}, {"traction": "4x2"}]
)
def test_mecanica_incompativel_da_propria_coluna_continua_rejeitada(kwargs):
    doc = document(**kwargs)
    doc.texto += "\nXLT 3.0 V6 Diesel 4WD AT, motor 3.0 V6 Diesel."
    assert not extract(doc).candidatos


@pytest.mark.parametrize("year", ["", "2026"])
def test_ano_ausente_ou_errado_nao_e_completado_pelo_alvo(year):
    assert not extract(document(year=year)).candidatos


def test_ano_presente_apenas_na_coluna_vizinha_nao_comprova_alvo():
    doc = document(year="")
    doc.texto = doc.texto.replace("XL 2.0 Diesel 4x2 MT", "XL 2.0 Diesel 4x2 MT ano-modelo 2027")
    assert not extract(doc).candidatos


def test_ano_modelo_da_coluna_prevalece_sobre_o_cabecalho_geral():
    doc = document()
    doc.celulas = tuple(
        replace(c, versoes_cobertas=("Limited ano-modelo 2026",)) for c in doc.celulas
    )
    doc.texto = doc.texto.replace("| Limited", "| Limited ano-modelo 2026")
    assert not extract(doc).candidatos


def test_cabecalho_da_celula_nao_pode_inventar_ano_ausente_no_documento():
    doc = document(year="")
    doc.celulas = tuple(
        replace(c, versoes_cobertas=("Limited ano-modelo 2027",)) for c in doc.celulas
    )
    assert not extract(doc).candidatos


def test_ano_documental_da_coluna_pode_identificar_modelo_sem_cabecalho_global():
    doc = document(year="")
    doc.celulas = tuple(
        replace(c, versoes_cobertas=("Limited ano-modelo 2027",)) for c in doc.celulas
    )
    doc.texto = doc.texto.replace("| Limited", "| Limited ano-modelo 2027")
    assert [c.valor for c in extract(doc).candidatos] == [250]


def test_data_de_captura_com_nome_do_modelo_nao_e_ano_modelo():
    doc = document(year="")
    doc.texto = "Captura Ranger: 2027-09-14\n" + doc.texto
    assert not extract(doc).candidatos


def test_url_sem_o_nome_do_modelo_nao_rejeita_a_coluna():
    """Defeito real: a Hilux é hospedada em `media.toyota.com.br/<uuid>.pdf`, uma URL sem
    "hilux". A coluna recortada (rótulo: valor) nunca repete o nome do modelo — por
    desenho, `_identidade_tabular` já ignora esse "ausente" porque marca/modelo foram
    comprovados no documento inteiro. Mas quando o ano-modelo já vem no cabeçalho da
    própria coluna (como na Hilux real: "SRX Plus AT" + MY na versão coberta), a segunda
    passagem com prefixo — que reintroduziria o nome do modelo — nunca roda, e sem a URL
    ajudar, `identity.assess` escala para o motivo mais forte `modelo_nao_comprovado`, que
    não estava na lista ignorada: a coluna certa era rejeitada por um sinal que nunca
    deveria valer aqui.
    """
    doc = document()
    doc.url = "https://media.example.com/d400f124-b3ac-4d73-a885-5d6828812f11.pdf"
    # Ano-modelo já no cabeçalho da coluna: a segunda passagem (que reintroduziria
    # "Ranger" via o prefixo do título) não é necessária, igual à Hilux real.
    doc.celulas = tuple(
        replace(c, versoes_cobertas=("Limited ano-modelo 2027",)) for c in doc.celulas
    )
    doc.texto = doc.texto.replace("| Limited", "| Limited ano-modelo 2027")
    assert [c.valor for c in extract(doc).candidatos] == [250]


def test_celula_compartilhada_nao_herda_motor_do_cabecalho_vizinho():
    doc = document(engine="2.0 Diesel")
    doc.celulas = tuple(
        replace(c, versoes_cobertas=("XLT 3.0 V6 Diesel", "Limited"), alcance=(1, 2))
        for c in doc.celulas
    )
    assert not extract(doc).candidatos


def test_fonte_de_outro_mercado_continua_incompativel():
    doc = document()
    doc.texto = "Market: Argentina\n" + doc.texto
    assert not extract(doc).candidatos
