"""O nome canônico de uma versão, e a chave que funde duplicatas.

Os dois defeitos que motivaram este módulo apareceram na tela, não no banco:

* **"Chevrolet S10 S10 High Country"** — o rótulo é `marca + modelo + nome_exato`, e o
  `nome_exato` do catálogo repetia o modelo;
* **duas linhas para o mesmo veículo** — `"High Country"` (sem ficha) e
  `"S10 High Country"` (com 58 campos), `"SRX Plus AT"` (com ficha) e
  `"SRX Plus AT (Cabine Dupla)"` (sem). Nos seletores viravam duas opções, e a que o
  usuário escolhia primeiro era, por ordem alfabética, justamente a vazia.

A regra tem de ser **estreita**: fundir demais apaga versão que existe de verdade. Por
isso só duas coisas saem do nome — o modelo repetido no começo e o qualificador de
carroceria que é o **padrão do segmento** (cabine dupla numa picape de topo). "Cabine
Simples" fica, porque distingue.
"""

from __future__ import annotations

import pytest

from pipeline.version_names import chave_de_versao, nome_canonico_de_versao


@pytest.mark.parametrize(
    ("modelo", "nome", "esperado"),
    [
        # O caso que aparecia na tela.
        ("S10", "S10 High Country", "High Country"),
        ("S10", "High Country", "High Country"),
        # O prefixo sai em qualquer caixa e com ou sem acento.
        ("Hilux", "HILUX SRX AT", "SRX AT"),
        ("Hilux", "SRX AT", "SRX AT"),
        # Qualificador de carroceria que é o padrão do segmento: sai.
        ("Hilux", "SRX Plus AT (Cabine Dupla)", "SRX Plus AT"),
        ("Hilux", "SRX Plus AT (cabine dupla)", "SRX Plus AT"),
        ("Ranger", "Limited 3.0 V6 Diesel 4WD AT (CD)", "Limited 3.0 V6 Diesel 4WD AT"),
        # Qualificador que DISTINGUE: fica.
        ("S10", "S10 Cabine Simples", "Cabine Simples"),
        ("Hilux", "SRX Plus AT (Cabine Simples)", "SRX Plus AT (Cabine Simples)"),
        # Nomes que já estão canônicos não mudam.
        ("Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT", "Raptor 3.0 V6 Bi-turbo 4WD AT"),
        # Alias comprovado pela própria página Ford: o título curto e o corpo completo
        # descrevem a mesma Raptor 2026 (fixture ford_site_versao/page.md).
        ("Ranger", "Raptor 4WD AT", "Raptor 3.0 V6 Bi-turbo 4WD AT"),
        ("Amarok", "V6 Extreme", "V6 Extreme"),
        ("S10", "Trail Boss", "Trail Boss"),
        # Espaços repetidos colapsam.
        ("S10", "  S10   LTZ ", "LTZ"),
    ],
)
def test_nome_canonico(modelo: str, nome: str, esperado: str) -> None:
    assert nome_canonico_de_versao(modelo, nome) == esperado


def test_nome_que_e_so_o_modelo_nao_vira_vazio() -> None:
    """Versão chamada como o modelo continua existindo.

    Devolver `""` faria a migração gravar uma versão sem nome — um registro que nenhuma
    tela consegue mostrar e nenhum resolvedor consegue casar. Apagar o nome é pior do que
    repetir o modelo.
    """
    assert nome_canonico_de_versao("S10", "S10") == "S10"
    assert nome_canonico_de_versao("Hilux", "(Cabine Dupla)") == "(Cabine Dupla)"


def test_prefixo_so_sai_quando_e_token_inteiro() -> None:
    """`S10` não pode ser arrancado de `S10X` nem do meio do nome."""
    assert nome_canonico_de_versao("S10", "S10X Sport") == "S10X Sport"
    assert nome_canonico_de_versao("Ranger", "Raptor Ranger Edition") == "Raptor Ranger Edition"


def test_chave_funde_as_duas_duplicatas_do_catalogo() -> None:
    """A chave é o que decide o que é a mesma versão."""
    assert chave_de_versao("S10", "S10 High Country") == chave_de_versao("S10", "High Country")
    assert chave_de_versao("Hilux", "SRX Plus AT (Cabine Dupla)") == chave_de_versao(
        "Hilux", "SRX Plus AT"
    )


def test_chave_so_funde_alias_comprovado_e_preserva_versoes_diferentes() -> None:
    """O alias explícito não abre uma regra larga de subconjunto de tokens."""
    assert chave_de_versao("Hilux", "SRX AT") != chave_de_versao("Hilux", "SRX Plus AT")
    assert chave_de_versao("S10", "S10 WT AT") != chave_de_versao("S10", "S10 WT MT")
    # Este é um alias explícito e documentado, não uma regra de subconjunto de tokens.
    assert chave_de_versao("Ranger", "Raptor 4WD AT") == chave_de_versao(
        "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT"
    )
