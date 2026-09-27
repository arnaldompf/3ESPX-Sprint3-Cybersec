"""O teto de blocos por documento: o que separa uma extração de uma conta de telefone.

`extrair_documento` mandava **todos** os blocos de um documento ao modelo, um por chamada.
Numa página de coleta (teto de 2 MB) isso dá 27 chamadas. Medido em 13/09/2026: o
Pesquisador gastou **54 chamadas em 2 páginas** para fechar 2 dos 55 campos, R$ 1,77, e
estourou a cota diária da conta logo no primeiro dos cinco veículos.

Dois contratos aqui, e o segundo é o que faz o teto ser aceitável:

1. documento pequeno sai **exatamente** como antes — nada de regressão no eval;
2. documento grande é cortado **por relevância**, não por ordem de leitura. Numa página de
   montadora a ficha técnica está depois do menu, do banner e da galeria; cortar o fim
   jogaria fora justamente o que se foi buscar.
"""

from __future__ import annotations

import pytest

from pipeline import llm
from pipeline.extract.run import (
    MAX_BLOCOS_AO_LLM,
    MAX_CHARS_POR_BLOCO,
    Documento,
    _blocos_que_valem,
    extrair_documento,
)

#: Um campo que existe na ontologia, com termos reconhecíveis.
CAMPO = "potencia_cv"


def encher(marca: str, tamanho: int = MAX_CHARS_POR_BLOCO) -> str:
    """Um bloco do tamanho máximo, com uma marca reconhecível dentro."""
    recheio = "lorem ipsum dolor sit amet. " * (tamanho // 28 + 1)
    return (marca + " ") + recheio[: tamanho - len(marca) - 1]


class TestDocumentoPequeno:
    def test_cabe_no_teto_e_sai_na_ordem_original(self):
        """Documento pequeno tem de sair **idêntico** ao de antes: mesmos blocos, mesma
        ordem. É o que garante que o eval não se mexe com esta mudança."""
        from pipeline.parse.html import dividir_em_blocos

        texto = encher("um", 1000) + "\n\n" + encher("dois", 1000)
        blocos, pulados = _blocos_que_valem(texto, [CAMPO])
        assert pulados == 0
        assert blocos == dividir_em_blocos(texto, max_chars=MAX_CHARS_POR_BLOCO)

    def test_nenhum_bloco_e_pulado_abaixo_do_teto(self):
        texto = "\n\n".join(encher(f"b{i}", 5000) for i in range(MAX_BLOCOS_AO_LLM))
        _, pulados = _blocos_que_valem(texto, [CAMPO])
        assert pulados == 0


class TestDocumentoGrande:
    def test_o_teto_corta(self):
        texto = "\n\n".join(encher(f"b{i}") for i in range(MAX_BLOCOS_AO_LLM + 5))
        blocos, pulados = _blocos_que_valem(texto, [CAMPO])
        assert len(blocos) == MAX_BLOCOS_AO_LLM
        assert pulados >= 1

    def test_o_bloco_que_fala_do_campo_sobrevive_mesmo_no_fim(self):
        """**O contrato que importa.** O bloco relevante é o **último** de uma pilha bem
        maior que o teto. Cortar por ordem de leitura o descartaria."""
        ruido = [encher(f"b{i}") for i in range(MAX_BLOCOS_AO_LLM * 2)]
        agulha = encher("Potência máxima cv e cavalos de potência do motor")
        texto = "\n\n".join([*ruido, agulha])

        blocos, pulados = _blocos_que_valem(texto, [CAMPO])
        assert pulados > 0
        assert any("Potência máxima" in b for b in blocos), (
            "o bloco que menciona o campo que falta foi descartado"
        )

    def test_sem_campo_faltando_nao_quebra(self):
        texto = "\n\n".join(encher(f"b{i}") for i in range(MAX_BLOCOS_AO_LLM + 2))
        blocos, pulados = _blocos_que_valem(texto, [])
        assert len(blocos) == MAX_BLOCOS_AO_LLM
        assert pulados > 0


class TestOAvisoSai:
    def test_o_documento_cortado_diz_quantos_blocos_ficaram_de_fora(self, monkeypatch):
        """Silêncio aqui seria o pior desfecho: um campo `nao_encontrado` porque o bloco
        dele não foi lido é indistinguível de um campo que a fonte não tem."""
        monkeypatch.setenv("LLM_FAKE", "1")
        texto = "\n\n".join(encher(f"b{i}") for i in range(MAX_BLOCOS_AO_LLM + 3))
        doc = Documento(texto=texto, source_id="grande", tier=1)

        resultado = extrair_documento(doc, {CAMPO}, marca="Ford", modelo_veiculo="Ranger")
        avisos = " ".join(resultado.avisos)
        assert "não foram ao modelo" in avisos
        assert "nao_encontrado" in avisos

    def test_documento_pequeno_nao_produz_o_aviso(self, monkeypatch):
        monkeypatch.setenv("LLM_FAKE", "1")
        doc = Documento(texto=encher("curto", 2000), source_id="pequeno", tier=1)
        resultado = extrair_documento(doc, {CAMPO}, marca="Ford", modelo_veiculo="Ranger")
        assert not any("não foram ao modelo" in a for a in resultado.avisos)


@pytest.mark.parametrize("valor,esperado", [("3", 3), ("", 8), ("0", 1), ("lixo", 8)])
def test_o_teto_e_configuravel_e_nunca_zero(monkeypatch, valor: str, esperado: int):
    """`LLM_MAX_BLOCOS=0` desligaria o LLM sem dizer; o piso de 1 evita isso."""
    import importlib

    monkeypatch.setenv("LLM_MAX_BLOCOS", valor)
    import pipeline.extract.run as alvo

    if valor == "lixo":
        # Valor ilegível não pode derrubar o import: o teto volta ao padrão.
        monkeypatch.setenv("LLM_MAX_BLOCOS", "")
    importlib.reload(alvo)
    # A variável local existe para o ruff: `alvo.MAX_BLOCOS_AO_LLM == esperado` é lido como
    # condição de Yoda (SIM300) por causa do nome em maiúsculas do lado esquerdo, e a
    # correção automática sugerida — inverter — deixaria a asserção pior de ler.
    teto = alvo.MAX_BLOCOS_AO_LLM
    assert teto == esperado
    monkeypatch.delenv("LLM_MAX_BLOCOS", raising=False)
    importlib.reload(alvo)


class TestOsBotoesDoPesquisador:
    """`max_blocos=1` e `escalonar=False`: um documento, **uma** chamada, e ponto.

    O Pesquisador paga cada chamada de um teto de quatro por pesquisa (medido em
    13/09/2026: ~30 s por extração com o raciocínio desligado). Um documento de cinco
    blocos que virasse cinco chamadas gastaria a cota inteira numa página só.
    """

    @pytest.fixture
    def kimi_dublada(self, monkeypatch):
        monkeypatch.setenv("LLM_FAKE", "0")
        monkeypatch.setenv("LLM_PROVIDER", "kimi")
        monkeypatch.setenv("LLM_MODEL", "kimi-k2.6")
        monkeypatch.setenv("LLM_API_KEY", "placeholder-de-teste")
        monkeypatch.setenv("LLM_MIN_INTERVAL_S", "0")
        monkeypatch.setattr(llm, "_ultima_chamada", 0.0, raising=False)
        monkeypatch.setattr(llm.time, "sleep", lambda s: None)
        vistos: list[dict] = []

        def falso(**kwargs):
            vistos.append(kwargs)
            # Nenhum campo respondido: é o que faria `deve_escalar` pedir a 2a passada.
            return {
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            }

        monkeypatch.setattr(llm, "_completion_padrao", lambda: falso)
        return vistos

    def test_max_blocos_1_manda_um_bloco_so(self, kimi_dublada):
        texto = "\n\n".join(encher(f"b{i}") for i in range(5))
        doc = Documento(texto=texto, source_id="grande", tier=1)
        resultado = extrair_documento(
            doc, {CAMPO}, marca="Ford", modelo_veiculo="Ranger", max_blocos=1, escalonar=False
        )
        assert len(kimi_dublada) == 1
        assert any("4 bloco(s)" in a and "o teto é 1" in a for a in resultado.avisos)

    def test_escalonar_False_nao_faz_a_segunda_passada(self, kimi_dublada):
        doc = Documento(texto=encher("curto", 2000), source_id="pequeno", tier=1)
        extrair_documento(doc, {CAMPO}, marca="Ford", modelo_veiculo="Ranger", escalonar=False)
        assert len(kimi_dublada) == 1

    def test_o_padrao_continua_escalonando(self, kimi_dublada):
        """O eval depende deste comportamento; ele não muda por causa do Pesquisador."""
        doc = Documento(texto=encher("curto", 2000), source_id="pequeno", tier=1)
        extrair_documento(doc, {CAMPO}, marca="Ford", modelo_veiculo="Ranger")
        assert len(kimi_dublada) == 2
