"""O tipo da afirmação: declarado × medido × listado.

O defeito que originou este módulo (12/09/2026): a ficha da Ranger Raptor mostra 5,8 s e
6,5 s para a aceleração 0–100 e escrevia "As fontes divergem" — mas **a fonte é uma só**.
A mesma matéria da Autoesporte traz o número declarado pela Ford e o cronometrado pela
revista. Não são duas fontes discordando; é uma fonte registrando duas coisas diferentes.
"""

from __future__ import annotations

import pytest

from pipeline import claim_type


class TestClassificar:
    @pytest.mark.parametrize(
        "texto",
        [
            "A Ford declara que a Ranger Raptor vai de 0 a 100 km/h em 5,8 segundos",
            "5,8 segundos (declarado pela Ford)",
            "segundo a fabricante, 583 Nm",
            "o número da ficha técnica",
            "a marca promete 397 cv",
        ],
    )
    def test_declarado(self, texto: str):
        tipo, termo = claim_type.classificar(texto)
        assert tipo == "declarado", texto
        assert termo, "o termo que disparou tem de viajar junto"

    @pytest.mark.parametrize(
        "texto",
        [
            "6,5 s (teste Autoesporte)",
            "medimos 6,5 segundos na pista",
            "no teste, o carro fez 6,5 s",
            "a revista cronometrou 6,5 segundos",
            "a Autoesporte apurou 6,5 s",
        ],
    )
    def test_medido(self, texto: str):
        tipo, termo = claim_type.classificar(texto)
        assert tipo == "medido", texto
        assert termo

    @pytest.mark.parametrize(
        "texto",
        [
            "0-100 km/h: 5,8 s",
            "Potência 397cv",
            "Capacidade de carga 620 kg",
            "",
        ],
    )
    def test_sem_termo_e_desconhecido_nunca_um_chute(self, texto: str):
        """`None` é `desconhecido`, estado de primeira classe.

        Rotular por padrão inventaria exatamente onde o produto promete não inventar.
        """
        assert claim_type.classificar(texto) == (None, "")

    def test_medido_ganha_de_declarado_na_mesma_frase(self):
        """ "A Ford declara 5,8 s; medimos 6,5 s" tem os dois termos.

        Quem mede publica a medição; quem repete o declarado raramente diz "medimos". O
        mais específico vence.
        """
        tipo, _ = claim_type.classificar("A Ford declara 5,8 s, mas medimos 6,5 s")
        assert tipo == "medido"

    def test_o_raw_value_manda_mais_que_o_quote(self):
        """O `raw_value` é a forma curta ao lado do número; o `quote` é a frase inteira."""
        tipo, termo = claim_type.classificar(
            "A Ford declara que a Raptor vai de 0 a 100 em 5,8 s",
            raw_value="6,5 s (teste Autoesporte)",
        )
        assert tipo == "medido"
        assert "Autoesporte" in termo

    def test_o_termo_nao_arrasta_a_frase_inteira(self):
        _, termo = claim_type.classificar("6,5 s (teste Autoesporte), o melhor do segmento")
        assert termo == "teste Autoesporte"
        assert "melhor" not in termo

    def test_o_caso_real_do_gabarito(self):
        """Os dois quotes que o pipeline extrai hoje da fixture da Raptor."""
        assert (
            claim_type.classificar(
                "A Ford declara que a Ranger Raptor vai de 0 a 100 km/h em 5,8 segundos",
                raw_value="5,8 segundos (declarado pela Ford)",
            )[0]
            == "declarado"
        )
        assert (
            claim_type.classificar(
                "A Autoesporte cronometrou 6,5 s", raw_value="6,5 s (teste Autoesporte)"
            )[0]
            == "medido"
        )
