"""O comparador de configurações de IA: a coluna de referência tem de ser a de verdade.

O risco aqui é específico e já se materializou duas vezes no projeto. A fixture de LLM é
indexada por `hash(modelo, campos, prompt)`, e as gravadas trazem o modelo histórico (a
Anthropic). Basta o `.env` da máquina trazer outro `LLM_MODEL` para que **nenhuma fixture
case** — e o pipeline segue com os campos vazios, sem um erro sequer.

O sintoma é o pior possível: o número muda e nada reclama. `make eval` publica 104/109, o
comparador publicaria 102/109, e os dois diriam ter medido a mesma coisa.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

import eval_modelos  # noqa: E402

from pipeline import llm  # noqa: E402


@pytest.fixture
def env_sujo(monkeypatch: pytest.MonkeyPatch):
    """O ambiente de uma máquina de desenvolvimento: provedor e chave da Moonshot."""
    monkeypatch.setenv("LLM_PROVIDER", "moonshot")
    monkeypatch.setenv("LLM_MODEL", "kimi-k2.6")
    monkeypatch.setenv("LLM_API_KEY", "sk-" + "x" * 40)
    monkeypatch.setenv("LLM_API_BASE", "https://api.moonshot.ai/v1")
    monkeypatch.setenv("LLM_FAKE", "0")


class TestAColunaDeReferencia:
    def test_fixture_usa_o_modelo_com_que_as_fixtures_foram_gravadas(self, env_sujo):
        """**A regressão de 13/09/2026.**

        A primeira versão de `configurar("fixture")` escrevia `LLM_FAKE=1` à mão e deixava
        `LLM_MODEL=kimi-k2.6` de pé. A chave da fixture mudava, nada casava, e a coluna de
        referência media 102/109 em vez de 104/109 — silenciosamente.
        """
        with eval_modelos.configurar("fixture"):
            assert llm.modo_fake() is True
            assert llm.provedor_atual() == "anthropic"
            assert llm.modelo_pequeno() == llm.PROVEDORES["anthropic"].modelo_pequeno
            assert os.environ.get("REPLAY_MODE") == "1"

    def test_fixture_nao_deixa_credencial_viva(self, env_sujo):
        """Com `LLM_FAKE=1` a chave não seria usada — mas um comando que desligue o modo
        fake no meio não deve encontrar credencial de verdade pendurada."""
        with eval_modelos.configurar("fixture"):
            assert llm.chave_do_provedor() == ""

    def test_a_coleta_fica_em_replay_nos_tres_modos(self, env_sujo, monkeypatch):
        """A variável sob teste é **quem lê o documento**, e só ela. Com a coleta ao vivo,
        a diferença entre duas colunas misturaria "o modelo leu melhor" com "a internet
        respondeu diferente", e nenhuma das duas ficaria sabida."""
        monkeypatch.setenv("LLM_PROVIDER_ALT", "gemini")
        monkeypatch.setenv("LLM_MODEL_ALT", "gemini-3.6-flash")
        monkeypatch.setenv("LLM_API_KEY_ALT", "AIza" + "z" * 35)
        for modo in ("fixture", "principal", "alternativa"):
            with eval_modelos.configurar(modo):
                assert os.environ.get("REPLAY_MODE") == "1", modo


class TestOsOutrosModos:
    def test_principal_usa_o_provedor_do_env(self, env_sujo):
        with eval_modelos.configurar("principal"):
            assert llm.modo_fake() is False
            assert llm.provedor_atual() == "kimi"
            assert llm.modelo_pequeno() == "kimi-k2.6"

    def test_alternativa_troca_provedor_e_modelo(self, env_sujo, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER_ALT", "gemini")
        monkeypatch.setenv("LLM_MODEL_ALT", "gemini-3.6-flash")
        monkeypatch.setenv("LLM_API_KEY_ALT", "AIza" + "z" * 35)
        with eval_modelos.configurar("alternativa"):
            assert llm.provedor_atual() == "gemini"
            assert llm.modelo_pequeno() == "gemini-3.6-flash"

    def test_alternativa_sem_configuracao_diz_isso_em_vez_de_medir_errado(self, env_sujo):
        """Cair silenciosamente para o provedor principal faria a coluna "alternativa"
        medir o principal — dois números iguais, e ninguém saberia por quê."""
        with (
            pytest.raises(RuntimeError, match="alternativa"),
            eval_modelos.configurar("alternativa"),
        ):
            pass

    def test_modo_desconhecido_levanta(self):
        with pytest.raises(ValueError, match="modo desconhecido"), eval_modelos.configurar("chute"):
            pass
