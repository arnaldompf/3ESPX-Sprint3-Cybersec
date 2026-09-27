"""O comando de extração ao vivo: a conta que ele reporta e o que ele não deixa vazar.

`scripts/extrair_ao_vivo.py` é o único lugar do projeto que liga `LLM_FAKE=0`. Ele grava
`reports/extracao_ao_vivo.json`, que é versionado, e por isso duas coisas precisam de
teste: que o relatório **distingue tentativa de resposta** (uma conta sem saldo produz oito
tentativas e zero token, e um relatório que dissesse só "8 chamadas" pareceria sucesso) e
que ele **não carrega identificador de credencial** — a Moonshot devolve o id da conta e o
id da chave dentro da própria mensagem de erro.

Nada aqui chama o provedor: os testes são sobre as funções de contabilidade e de limpeza.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from pipeline.llm import Uso

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def comando():
    """O script carregado como módulo. Ele não é pacote; é um comando."""
    caminho = RAIZ / "scripts" / "extrair_ao_vivo.py"
    spec = importlib.util.spec_from_file_location("extrair_ao_vivo", caminho)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class TestAConta:
    def test_tentativa_recusada_conta_como_tentativa_e_nao_como_resposta(self, comando):
        """O caso da conta sem saldo: oito idas ao provedor, zero token, custo zero."""
        recusadas = [Uso("kimi-k2.6") for _ in range(8)]
        conta = comando.somar(recusadas)
        assert conta["tentativas"] == 8
        assert conta["respondidas"] == 0
        assert conta["tokens_entrada"] == 0
        assert conta["custo_brl"] == 0.0
        # `None`, e não `False`: dizer "o custo não é estimativa" sobre zero chamada seria
        # afirmar alguma coisa sobre nada.
        assert conta["custo_e_estimativa"] is None

    def test_chamada_respondida_soma_tokens_e_custo(self, comando):
        conta = comando.somar(
            [
                Uso("kimi-k2.6", tokens_entrada=1000, tokens_saida=200),
                Uso("kimi-k2.6", tokens_entrada=500, tokens_saida=100),
            ]
        )
        assert conta["tentativas"] == 2
        assert conta["respondidas"] == 2
        assert conta["tokens_entrada"] == 1500
        assert conta["tokens_saida"] == 300
        assert conta["custo_brl"] > 0
        assert conta["custo_e_estimativa"] is True

    def test_fixture_nao_entra_na_conta(self, comando):
        """`LLM_FAKE=1` custa zero **de verdade**, e não pode aparecer como chamada real."""
        conta = comando.somar([Uso("kimi-k2.6", de_fixture=True)])
        assert conta["tentativas"] == 0
        assert conta["custo_brl"] == 0.0

    def test_custo_informado_pelo_provedor_nao_e_estimativa(self, comando):
        conta = comando.somar(
            [Uso("kimi-k2.6", tokens_entrada=10, tokens_saida=5, custo_usd_informado=0.001)]
        )
        assert conta["custo_e_estimativa"] is False


class TestOQueNaoVaiParaOArquivo:
    def test_id_de_conta_e_de_chave_saem_mascarados(self, comando):
        bruto = (
            "RateLimitError: MoonshotException - Your account "
            "org-f60cda277e254ab4bf6b837b49ce7487 <ak-fckfg44ezmsi11cyodci> is suspended "
            "due to insufficient balance"
        )
        limpo = comando.sem_identificadores(bruto)
        assert "org-***" in limpo
        assert "ak-***" in limpo
        assert "f60cda277e" not in limpo
        assert "fckfg44" not in limpo
        # E o motivo continua legível, que é o ponto de guardar o texto.
        assert "insufficient balance" in limpo

    def test_texto_sem_identificador_passa_intacto(self, comando):
        bruto = "bloco 1/1: resposta não é JSON válido: Expecting value"
        assert comando.sem_identificadores(bruto) == bruto

    def test_o_filtro_de_avisos_pega_o_motivo_do_provedor(self, comando):
        """O motivo real não contém a palavra "LLM"; um filtro ingênuo devolveria vazio."""
        aviso = (
            "bloco 1/1: RateLimitError: litellm.RateLimitError: MoonshotException - "
            "Your account is suspended"
        )
        assert any(marca in aviso for marca in comando.MARCAS_DE_AVISO_DE_LLM)


def test_os_cinco_veiculos_sao_os_do_gabarito(comando):
    """A lista do comando não pode divergir dos snapshots que existem."""
    from pipeline.store import versoes_disponiveis

    disponiveis = set(versoes_disponiveis())
    if not disponiveis:  # pragma: no cover - clone sem fixtures
        pytest.skip("nenhum snapshot nesta máquina")
    faltando = [v[0] for v in comando.VEICULOS if v[0] not in disponiveis]
    assert not faltando, f"sem snapshot: {faltando}"
