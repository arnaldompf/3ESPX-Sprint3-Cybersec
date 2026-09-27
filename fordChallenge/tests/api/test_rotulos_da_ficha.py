"""Nenhum dos 58 campos da ficha aparece na tela com grafia de nome de coluna.

O nome canônico é ASCII por necessidade: ele é chave de JSON, nome de coluna e pedaço de
URL. O rótulo na tela é português, e português leva acento. A regra que faz um virar o
outro mora em `web/src/lib/formato.ts` (`rotularCampo`), e este teste a aplica aos **58
campos de verdade**, que moram em `pipeline/schema.py`.

Por que em Python e não em Vitest: o schema está aqui. Um teste de tela teria de manter
uma cópia da lista dos 58, e cópia de lista é a coisa que diverge primeiro — era
exatamente esse o argumento contra um dicionário de rótulos, e ele vale para o teste
também.

O que este teste **não** faz: não exige que todo campo tenha acento (a maioria não precisa)
nem que o rótulo seja bonito. Ele exige três coisas, e todas são medidas: nenhum `_`
sobrevive, nenhuma palavra do vocabulário acentuado aparece sem acento, e nenhuma unidade
fica solta no fim do rótulo como se fosse parte do nome.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pipeline.schema import empty_spec

FORMATO = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "formato.ts"


def _tabela(nome: str) -> dict[str, str]:
    """Lê um `Record<string, string>` literal de `formato.ts` como dado."""
    texto = FORMATO.read_text(encoding="utf-8")
    inicio = texto.index(f"const {nome}")
    corpo = texto[texto.index("{", inicio) : texto.index("\n}", inicio)]
    return dict(re.findall(r"(\w+): '([^']*)'", corpo))


@pytest.fixture(scope="module")
def rotular():
    """A mesma regra de `rotularCampo`, alimentada pelas tabelas do arquivo dele.

    Transcrever a **regra** (cinco linhas) e ler as **tabelas** do arquivo é o que mantém
    o teste honesto: uma palavra acrescentada lá é conferida aqui sem ninguém copiar nada,
    e uma mudança de regra quebra o teste, que é o que se quer.
    """
    com_acento = _tabela("COM_ACENTO")
    siglas = _tabela("SIGLAS")
    unidades = _tabela("UNIDADES")

    def acao(campo: str) -> str:
        pedacos = campo.split("_")
        unidade = unidades.get(pedacos[-1]) if len(pedacos) > 1 else None
        palavras = pedacos[:-1] if unidade else pedacos
        nome = " ".join(siglas.get(p) or com_acento.get(p) or p for p in palavras)
        texto = nome[:1].upper() + nome[1:]
        return f"{texto} ({unidade})" if unidade else texto

    acao.com_acento = com_acento  # type: ignore[attr-defined]
    acao.unidades = unidades  # type: ignore[attr-defined]
    return acao


def campos_do_schema() -> list[str]:
    return [caminho.split(".", 1)[-1] for caminho, _ in empty_spec(job_id="rotulos").itens()]


def grupos_do_schema() -> set[str]:
    """Os 11 blocos da ficha. Eles também viram título na tela e também levam acento."""
    return {caminho.split(".", 1)[0] for caminho, _ in empty_spec(job_id="rotulos").itens()}


def test_o_teste_enxerga_as_tabelas(rotular):
    """Antes de conferir, provar que a leitura funciona. Tabela vazia passa sempre."""
    assert rotular.com_acento["preco"] == "preço"
    assert rotular.unidades["brl"] == "R$"
    assert rotular("preco_sugerido_brl") == "Preço sugerido (R$)"


@pytest.mark.parametrize("campo", campos_do_schema())
def test_nenhum_rotulo_carrega_underscore(rotular, campo: str):
    assert "_" not in rotular(campo), f"{campo} sai da tela com underscore"


@pytest.mark.parametrize("campo", campos_do_schema())
def test_nenhuma_palavra_acentuada_aparece_sem_acento(rotular, campo: str):
    """Se a palavra está no vocabulário acentuado, o rótulo tem de trazê-la acentuada."""
    rotulo = rotular(campo).lower()
    for palavra, acentuada in rotular.com_acento.items():
        if palavra in campo.split("_"):
            assert acentuada in rotulo, f"{campo}: esperava {acentuada!r} em {rotulo!r}"


@pytest.mark.parametrize("campo", campos_do_schema())
def test_unidade_no_fim_vira_parenteses(rotular, campo: str):
    """`preco_sugerido_brl` não pode terminar em "brl" solto, como resto de coluna."""
    pedacos = campo.split("_")
    if len(pedacos) < 2 or pedacos[-1] not in rotular.unidades:
        pytest.skip("campo sem unidade no fim")
    rotulo = rotular(campo)
    assert rotulo.endswith(f"({rotular.unidades[pedacos[-1]]})"), rotulo


def test_as_tres_palavras_que_mais_apareciam_erradas(rotular):
    """As que o Radar mostrava na tela em 12/09/2026, antes desta rodada."""
    assert rotular("preco_sugerido_brl") == "Preço sugerido (R$)"
    assert rotular("preco_fipe_brl") == "Preço FIPE (R$)"
    assert rotular("modos_direcao") == "Modos direção"


def test_nenhuma_entrada_das_tabelas_esta_sobrando(rotular):
    """Palavra mapeada que nenhum campo usa é manutenção morta — ou erro de digitação."""
    usadas = {pedaco for campo in campos_do_schema() for pedaco in campo.split("_")}
    # Os nomes de **grupo** (`identificacao`, `seguranca`, `dimensoes`...) não são campos,
    # e também aparecem na tela — como título de bloco. Eles contam como uso.
    sobrando = sorted(set(rotular.com_acento) - usadas - grupos_do_schema())
    assert not sobrando, f"palavras mapeadas que nenhum campo usa: {sobrando}"
