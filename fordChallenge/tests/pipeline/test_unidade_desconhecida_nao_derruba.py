"""Uma unidade que ninguém previu não pode derrubar a coleta inteira.

**Isto nasceu de uma rodada real**, em 13/09/2026: o Pesquisador rodando com modelo de
verdade sobre a página do Mitsubishi Triton parou com

    UnidadeDesconhecida: unidade de comprimento desconhecida: 'metros'

depois de 456 segundos e 29 chamadas de LLM. Não foi um campo que ficou vazio — foi a
**pesquisa inteira** que morreu, e os outros 54 campos, já lidos e pagos, foram junto.

A causa é de duas linhas e de dois níveis:

1. `UnidadeDesconhecida` e `NaoNormalizavel` são **irmãs** (as duas herdam de `ValueError`),
   e `pipeline/reconcile.py` só captura a segunda. A primeira passa reto;
2. `to_mm` não conhecia `"metros"` — embora `to_litros` já aceitasse `"litros"` por
   extenso. O modelo escreve a unidade como ela aparece no texto, e no texto está por
   extenso.

O item 2 sozinho consertaria o sintoma desta noite e deixaria o próximo em pé. O item 1 é
o que vale: **campo que não normaliza vira campo sem valor, com motivo — nunca uma
exceção que atravessa o pipeline.**
"""

from __future__ import annotations

import pytest

from pipeline import units
from pipeline.normalize import NaoNormalizavel, normalizar_campo


class TestUnidadePorExtenso:
    """O modelo escreve a unidade como está no texto, e no texto ela vem por extenso."""

    @pytest.mark.parametrize(
        ("valor", "unidade", "esperado"),
        [
            ("5,32", "metros", 5320),
            ("5.32", "metro", 5320),
            ("532", "centimetros", 5320),
            ("532", "centímetros", 5320),
            ("5320", "milimetros", 5320),
            ("17", "polegadas", 432),
        ],
    )
    def test_comprimento_por_extenso(self, valor, unidade, esperado):
        assert units.to_mm(valor, unidade) == esperado

    @pytest.mark.parametrize(
        ("valor", "unidade", "esperado"),
        [
            ("2,4", "litro", 2.4),
            ("2400", "mililitros", 2.4),
        ],
    )
    def test_volume_por_extenso(self, valor, unidade, esperado):
        assert units.to_litros(valor, unidade) == esperado


class TestNaoDerruba:
    """O portão que importa: unidade que ninguém previu vira campo recusado, não queda."""

    def test_unidade_de_verdade_desconhecida_vira_NaoNormalizavel(self):
        """`"côvados"` continua desconhecido — e tem de continuar. O que muda é o **tipo**
        da falha: a que o chamador já sabe tratar."""
        with pytest.raises(NaoNormalizavel) as erro:
            normalizar_campo("comprimento_mm", "5320", unidade="côvados")
        assert "côvados" in str(erro.value)

    @pytest.mark.parametrize(
        ("campo", "unidade"),
        [
            ("comprimento_mm", "côvados"),
            ("tanque_l", "arrobas"),
            ("potencia_cv", "cavalos-vapor-métricos-imaginários"),
            ("torque_nm", "libras-pé-por-segundo"),
        ],
    )
    def test_toda_dimensao_recusa_pelo_mesmo_tipo(self, campo, unidade):
        """Quatro dimensões, quatro `raise` diferentes em `units.py`, um tipo só na
        fronteira. O chamador não pode precisar conhecer a lista."""
        with pytest.raises(NaoNormalizavel):
            normalizar_campo(campo, "10", unidade=unidade)

    def test_a_reconciliacao_recusa_o_campo_e_segue_com_os_outros(self):
        """O caso da Triton, reduzido: dois candidatos, um com unidade impossível.

        O bom tem de chegar na outra ponta. Antes desta correção, os dois morriam."""
        from pipeline.extract.run import Candidato
        from pipeline.reconcile import agrupar

        candidatos = [
            Candidato(
                campo="comprimento_mm",
                valor="5320",
                valor_bruto="5320",
                unidade="côvados",
                quote="5320 côvados de comprimento",
                origem="llm:teste",
                source_id="s1",
                tier=1,
            ),
            Candidato(
                campo="potencia_cv",
                valor="204",
                valor_bruto="204",
                unidade="cv",
                quote="204 cv de potência",
                origem="llm:teste",
                source_id="s1",
                tier=1,
            ),
        ]
        por_campo, recusados = agrupar(candidatos)

        assert "potencia_cv" in por_campo, "o campo bom tem de sobreviver ao campo ruim"
        assert "comprimento_mm" not in por_campo
        assert any("comprimento_mm" in r for r in recusados)
        assert any("côvados" in r for r in recusados)
