"""A matriz da tela e a do servidor são **a mesma tabela**, e este teste não deixa divergir.

Desde D-204 a decisão de "esta tela é do analista" é aplicada no cliente
(`web/src/lib/permissoes.ts`), porque a API não recusa mais nada com `AUTH_ENABLED=false`.
Duas cópias da mesma tabela é o desenho, e duas cópias divergem: alguém acrescenta um papel
a uma ação em `docs/12` §6.6, atualiza o Python, e a tela continua escondendo a tela de
quem agora pode entrar — sem erro, sem teste vermelho, sem ninguém perceber até a
apresentação.

O teste lê o TypeScript como **texto**, e isso é deliberado: rodar o TypeScript daqui
exigiria Node no caminho do pytest, e o que precisa ser conferido é justamente o literal
que a pessoa edita. Se o formato do literal mudar, este teste falha alto em vez de passar
lendo nada — é o que `test_o_teste_enxerga_a_matriz` garante.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from api.app.models import Role
from api.app.permissions import MATRIZ, Acao, Escopo

ARQUIVO_DA_TELA = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "permissoes.ts"


def _matriz_da_tela() -> dict[str, dict[str, str]]:
    """O literal `MATRIZ` de `permissoes.ts`, lido como dado."""
    texto = ARQUIVO_DA_TELA.read_text(encoding="utf-8")
    inicio = texto.index("export const MATRIZ")
    corpo = texto[texto.index("{", inicio) : texto.index("\n}", inicio) + 2]
    # De objeto TypeScript para JSON: chaves sem aspas, aspas simples, vírgula final.
    como_json = re.sub(r"(\w+):", r'"\1":', corpo)
    como_json = como_json.replace("'", '"')
    como_json = re.sub(r",(\s*[}\]])", r"\1", como_json)
    return json.loads(como_json)


def test_o_teste_enxerga_a_matriz():
    """Antes de comparar, provar que a leitura funciona. Teste que lê vazio passa sempre."""
    lida = _matriz_da_tela()
    assert len(lida) == len(list(Acao)), lida
    assert lida["gerir_usuarios"] == {"admin": "todos"}


@pytest.mark.parametrize("acao", sorted(Acao), ids=lambda a: a.value)
def test_cada_acao_tem_os_mesmos_papeis_e_os_mesmos_escopos(acao: Acao):
    da_tela = _matriz_da_tela().get(acao.value, {})
    do_servidor = {papel.value: escopo.value for papel, escopo in MATRIZ[acao].items()}
    assert da_tela == do_servidor, (
        f"{acao.value}: a tela diz {da_tela} e o servidor diz {do_servidor}. "
        f"As duas transcrevem docs/12 §6.6 — corrija a que estiver errada."
    )


def test_nenhum_papel_inventado_na_tela():
    """Papel que não existe em `Role` não pode aparecer na tela (erro de digitação)."""
    papeis_reais = {papel.value for papel in Role}
    for acao, linha in _matriz_da_tela().items():
        desconhecidos = set(linha) - papeis_reais
        assert not desconhecidos, f"{acao}: papel desconhecido {sorted(desconhecidos)}"


def test_nenhum_escopo_inventado_na_tela():
    escopos_reais = {escopo.value for escopo in Escopo}
    for acao, linha in _matriz_da_tela().items():
        desconhecidos = set(linha.values()) - escopos_reais
        assert not desconhecidos, f"{acao}: escopo desconhecido {sorted(desconhecidos)}"
