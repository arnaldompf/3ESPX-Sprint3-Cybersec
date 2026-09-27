"""WP-11 / docs/09 — os dois vazios nunca se colapsam.

`nao_disponivel` ("a fonte oficial afirma que não existe") e `nao_encontrado` ("nenhuma
fonte consultada menciona") são estados **diferentes**, e é uma das quatro regras que o
produto vende. Colapsá-los transformaria "a Ford diz que não tem" em "não achei" — e
essas duas frases levam um vendedor a fazer coisas opostas na frente do cliente.
"""

from __future__ import annotations

import pytest

from pipeline.eval.gabarito import carregar_gabarito
from pipeline.eval.mapping import STATUS_GABARITO_PARA_CANONICO, status_compativel
from pipeline.normalize import normalizar_campo, parece_ausencia
from pipeline.schema import STATUS_SEM_VALOR, SpecField, Status
from pipeline.status import Observacao, decidir


@pytest.fixture(scope="module")
def gab():
    return carregar_gabarito()


# ------------------------------------------------------------ estados distintos
def test_os_seis_status_existem_e_sao_distintos():
    assert len(set(Status)) == 6
    assert Status.NAO_DISPONIVEL is not Status.NAO_ENCONTRADO


def test_os_tres_status_vazios_exigem_valor_nulo():
    for status in STATUS_SEM_VALOR:
        with pytest.raises(ValueError, match="value=None"):
            SpecField(value="algo", status=status)
        assert SpecField(value=None, status=status).value is None


def test_nao_disponivel_vem_de_afirmacao_da_fonte_oficial():
    d = decidir(
        "camera_360",
        [
            Observacao(
                campo="camera_360",
                valor=None,
                quote="—",
                tier=1,
                source_id="pdf",
                url="https://media.toyota.com.br/x.pdf",
                ausencia_declarada=True,
            )
        ],
        textos={"pdf": "Câmera 360 graus    —"},
    )
    assert d.status is Status.NAO_DISPONIVEL
    assert "oficial" in (d.spec.notes or "")


def test_nao_encontrado_lista_as_fontes_consultadas():
    """ "Não encontrei" sem dizer onde procurei não é informação."""
    d = decidir(
        "capacidade_reboque_kg",
        [],
        textos={},
        sources_checked=[
            "https://www.ford.com.br/picapes/ranger-raptor/",
            "https://www.tabelafipebrasil.com/",
        ],
    )
    assert d.status is Status.NAO_ENCONTRADO
    assert len(d.spec.sources_checked) == 2
    assert all(u.startswith("http") for u in d.spec.sources_checked)


def test_nao_verificado_e_um_terceiro_estado():
    """Havia valor, mas o trecho não confere: não é nenhum dos dois vazios."""
    d = decidir(
        "potencia_cv",
        [
            Observacao(
                campo="potencia_cv",
                valor=500,
                quote="Potencia 500cv",
                tier=1,
                source_id="s",
                url="https://x",
            )
        ],
        textos={"s": "Potencia 397cv"},
    )
    assert d.status is Status.NAO_VERIFICADO
    assert d.status not in {Status.NAO_DISPONIVEL, Status.NAO_ENCONTRADO}
    assert d.spec.value is None


# --------------------------------------------------------- marcas de ausência
@pytest.mark.parametrize("marca", ["-", "–", "—", "não disponível", "não oferecido", "n/d"])
def test_a_fonte_oficial_marca_ausencia_de_varias_formas(marca):
    assert parece_ausencia(marca)
    assert normalizar_campo("camera_360", marca).ausencia_declarada


@pytest.mark.parametrize("nao_e_ausencia", ["", "   ", "•", "sim", "opcional"])
def test_o_que_nao_e_afirmacao_de_ausencia(nao_e_ausencia):
    """Célula vazia é "não sei"; `•` é presença; "opcional" é outra coisa."""
    assert not parece_ausencia(nao_e_ausencia) or nao_e_ausencia.strip() in {"-", "–", "—"}


# ------------------------------------------------------------- regra do eval
def test_eval_aceita_nao_encontrado_virando_nao_disponivel_mas_nunca_valor():
    """`docs/09`: `nao_encontrado` → `nao_encontrado`/`nao_disponivel`, nunca valor."""
    assert status_compativel("nao_encontrado", "nao_encontrado")
    assert status_compativel("nao_encontrado", "nao_disponivel")
    assert not status_compativel("nao_encontrado", "verificado")
    assert not status_compativel("nao_encontrado", "divergente")


def test_nao_disponivel_do_gabarito_exige_nao_disponivel_do_pipeline():
    """O caminho inverso é mais estrito: afirmação de ausência não se satisfaz com silêncio."""
    assert STATUS_GABARITO_PARA_CANONICO["nao_disponivel"] == ("nao_disponivel",)
    assert not status_compativel("nao_disponivel", "nao_encontrado")


# ---------------------------------------------------- contra o gabarito real
def test_os_rpm_da_raptor_agora_tem_fonte_publica_tier_3(gab):
    """Fase 2 do plano 18/18 (CarrosNaWeb, 2026-09-15): os dois rpm que só o slide
    interno afirmava agora têm ficha pública real. `potencia_rpm` diverge do slide
    (6250 vs 5650); `torque_rpm` concorda (3500 = 3500)."""
    raptor = gab.por_id("ford_ranger_raptor_2026")
    potencia = raptor.por_caminho("motorizacao.potencia_rpm")
    torque = raptor.por_caminho("motorizacao.torque_rpm")
    assert potencia.status == "divergente"
    assert potencia.valor == 6250
    assert potencia.slide_ford == 5650
    assert torque.status == "verificado_tier3"
    assert torque.valor == 3500
    assert torque.slide_ford == 3500
    for campo in (potencia, torque):
        assert campo.fontes and "carrosnaweb" in campo.fontes[0]


def test_hilux_tem_campos_pendentes_e_isso_nao_e_vazio(gab):
    """`pendente_coleta` é um quarto estado: ainda não foi buscado."""
    hilux = gab.por_id("toyota_hilux_srx_plus_at_2026")
    pendentes = [c for c in hilux.campos if c.status == "pendente_coleta"]
    assert len(pendentes) >= 2
    for campo in pendentes:
        assert campo.valor is None
        assert not campo.avalia_valor, "pendente_coleta não conta como erro do pipeline"


def test_gabarito_nao_confunde_os_dois_vazios(gab):
    """Nenhum campo do gabarito está marcado como os dois ao mesmo tempo."""
    for veiculo in gab.veiculos:
        for campo in veiculo.campos:
            if campo.status in {"nao_encontrado", "nao_disponivel"}:
                assert campo.valor is None, f"{veiculo.id}/{campo.origem}"
