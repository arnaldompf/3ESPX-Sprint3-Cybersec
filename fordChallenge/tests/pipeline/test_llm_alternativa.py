"""A IA alternativa: o caminho que só roda quando o primeiro provedor falha.

É o código mais fácil de escrever errado e mais difícil de notar errado, porque só executa
no dia em que a conta principal acaba — que, nesta máquina, foi 12/09/2026. Os testes aqui
existem para que esse dia não seja a estreia.

Nenhuma chamada sai para a rede: `cliente=` é um dublê com a assinatura de
`litellm.completion`, e é a mesma costura que o resto da suíte usa.
"""

from __future__ import annotations

import json
import os
from typing import Any, ClassVar

import pytest

from pipeline import llm

CHAVE_FALSA_PRINCIPAL = "sk-" + "p" * 40
CHAVE_FALSA_ALTERNATIVA = "AIza" + "a" * 35


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch: pytest.MonkeyPatch):
    """Sem herdar o `.env` da máquina: o teste descreve a configuração que exercita."""
    for principal, alternativo in llm.PARES_ALTERNATIVOS:
        monkeypatch.delenv(principal, raising=False)
        monkeypatch.delenv(alternativo, raising=False)
    for nome in ("LLM_MODEL_SMALL", "LLM_MODEL_LARGE", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("LLM_FAKE", "0")


def configurar(monkeypatch: pytest.MonkeyPatch, *, com_alternativa: bool) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_MODEL", "kimi-k2.6")
    monkeypatch.setenv("LLM_API_KEY", CHAVE_FALSA_PRINCIPAL)
    monkeypatch.setenv("LLM_API_BASE", "https://api.moonshot.ai/v1")
    if com_alternativa:
        monkeypatch.setenv("LLM_PROVIDER_ALT", "gemini")
        monkeypatch.setenv("LLM_MODEL_ALT", "gemini-2.5-flash")
        monkeypatch.setenv("LLM_API_KEY_ALT", CHAVE_FALSA_ALTERNATIVA)


def resposta_boa(conteudo: dict[str, Any]) -> Any:
    """Um objeto com a forma que `_interpretar` espera do LiteLLM."""

    class _Mensagem:
        content = json.dumps(conteudo, ensure_ascii=False)

    class _Escolha:
        message = _Mensagem()

    class _Uso:
        prompt_tokens = 10
        completion_tokens = 5
        completion_tokens_details = None

    class _Resposta:
        choices: ClassVar = [_Escolha()]
        usage = _Uso()
        finish_reason = "stop"

    return _Resposta()


class Dubl:
    """Chamável que registra os modelos pedidos e responde conforme o roteiro."""

    def __init__(self, *roteiro: Any):
        self.roteiro = list(roteiro)
        self.pedidos: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.pedidos.append(kwargs)
        acao = self.roteiro.pop(0) if self.roteiro else resposta_boa({})
        if isinstance(acao, Exception):
            raise acao
        return acao

    @property
    def modelos(self) -> list[str]:
        return [p["model"] for p in self.pedidos]


class TestQuandoCai:
    def test_conta_sem_saldo_cai_para_a_alternativa(self, monkeypatch):
        """**O caso de 12/09/2026**: a Moonshot devolveu conta suspensa como 429."""
        configurar(monkeypatch, com_alternativa=True)
        dublê = Dubl(
            RuntimeError("429 exceeded_current_quota_error"),
            resposta_boa({"potencia_cv": 397}),
        )
        r = llm.extrair_json(prompt="p", campos=["potencia_cv"], cliente=dublê)

        assert r.ok, r.motivo
        assert r.dados == {"potencia_cv": 397}
        assert dublê.modelos == ["moonshot/kimi-k2.6", "gemini/gemini-2.5-flash"]
        assert "IA alternativa" in r.motivo
        assert "quota" in r.motivo, "o motivo do primeiro fracasso tem de viajar junto"

    def test_o_uso_diz_qual_conta_pagou(self, monkeypatch):
        """Um relatório de custo que não diz de qual conta saiu o gasto manda conferir o
        extrato errado."""
        configurar(monkeypatch, com_alternativa=True)
        dublê = Dubl(RuntimeError("timeout"), resposta_boa({"x": 1}))
        r = llm.extrair_json(prompt="p", campos=["x"], cliente=dublê)

        assert r.uso is not None
        assert r.uso.provedor == "gemini"
        assert r.uso.modelo == "gemini-2.5-flash"
        assert r.uso.to_dict()["provedor"] == "gemini"

    @pytest.mark.parametrize(
        "erro",
        [
            "429 rate limit exceeded",
            "insufficient balance",
            "Request timed out",
            "503 Service Unavailable",
            "Connection error",
        ],
    )
    def test_falhas_de_provedor_acionam_a_alternativa(self, monkeypatch, erro: str):
        configurar(monkeypatch, com_alternativa=True)
        dublê = Dubl(RuntimeError(erro), resposta_boa({"x": 1}))
        assert llm.extrair_json(prompt="p", campos=["x"], cliente=dublê).ok
        assert len(dublê.pedidos) == 2


class TestQuandoNaoCai:
    def test_sem_alternativa_configurada_falha_e_diz_por_que(self, monkeypatch):
        configurar(monkeypatch, com_alternativa=False)
        dublê = Dubl(RuntimeError("429 exceeded_current_quota_error"))
        r = llm.extrair_json(prompt="p", campos=["x"], cliente=dublê)

        assert r.ok is False
        assert len(dublê.pedidos) == 1
        assert "IA alternativa" not in r.motivo

    def test_json_invalido_nao_gasta_a_segunda_conta(self, monkeypatch):
        """Resposta malformada é problema do pedido, não do provedor. Cair aqui pagaria
        duas vezes pelo mesmo erro — e esconderia que o prompt é que está ruim."""
        configurar(monkeypatch, com_alternativa=True)

        class _M:
            content = "isto não é JSON"

        class _E:
            message = _M()

        class _R:
            choices: ClassVar = [_E()]
            usage = None

        dublê = Dubl(_R())
        r = llm.extrair_json(prompt="p", campos=["x"], cliente=dublê)
        assert r.ok is False
        assert len(dublê.pedidos) == 1, "não podia ter chamado a alternativa"

    def test_chave_principal_ausente_nao_e_mascarado_pela_alternativa(self, monkeypatch):
        """Erro de **configuração nossa** tem de aparecer. Se a conta alternativa pagar a
        conta em silêncio, o defeito só surge quando as duas acabarem."""
        configurar(monkeypatch, com_alternativa=True)
        monkeypatch.delenv("LLM_API_KEY")
        dublê = Dubl(resposta_boa({"x": 1}))
        r = llm.extrair_json(prompt="p", campos=["x"], cliente=dublê)

        assert r.ok is False
        assert dublê.pedidos == []
        assert "LLM_API_KEY" in r.motivo

    def test_alternativa_sem_chave_nao_conta_como_alternativa(self, monkeypatch):
        configurar(monkeypatch, com_alternativa=True)
        monkeypatch.delenv("LLM_API_KEY_ALT")
        assert llm.tem_alternativa() is False


class TestOContexto:
    def test_troca_e_devolve_o_ambiente(self, monkeypatch):
        configurar(monkeypatch, com_alternativa=True)
        with llm.como_alternativa():
            assert llm.provedor_atual() == "gemini"
            assert llm.modelo_pequeno() == "gemini-2.5-flash"
            assert llm.chave_do_provedor() == CHAVE_FALSA_ALTERNATIVA
        assert llm.provedor_atual() == "kimi"
        assert llm.modelo_pequeno() == "kimi-k2.6"
        assert llm.chave_do_provedor() == CHAVE_FALSA_PRINCIPAL

    def test_devolve_o_ambiente_mesmo_com_excecao(self, monkeypatch):
        configurar(monkeypatch, com_alternativa=True)
        with pytest.raises(ValueError), llm.como_alternativa():
            raise ValueError("boom")
        assert llm.provedor_atual() == "kimi"

    def test_dentro_do_contexto_nao_ha_alternativa(self, monkeypatch):
        """A guarda contra recursão infinita: a alternativa não cai para si mesma."""
        configurar(monkeypatch, com_alternativa=True)
        with llm.como_alternativa():
            assert llm.tem_alternativa() is False

    def test_a_alternativa_nao_herda_o_modelo_do_principal(self, monkeypatch):
        """Herdar `LLM_MODEL=kimi-k2.6` numa chamada ao Gemini pediria um modelo que não
        existe lá — e o erro diria "modelo não encontrado" em vez de "não configurada"."""
        configurar(monkeypatch, com_alternativa=True)
        monkeypatch.delenv("LLM_MODEL_ALT")
        with llm.como_alternativa():
            assert llm.modelo_pequeno() == ""

    def test_a_alternativa_que_tambem_falha_devolve_o_fracasso(self, monkeypatch):
        configurar(monkeypatch, com_alternativa=True)
        dublê = Dubl(RuntimeError("429 quota"), RuntimeError("503 Service Unavailable"))
        r = llm.extrair_json(prompt="p", campos=["x"], cliente=dublê)

        assert r.ok is False
        assert len(dublê.pedidos) == 2, "duas contas, duas tentativas, e para por aí"
        assert "IA alternativa" in r.motivo


class TestOAmbienteProtegido:
    """**O defeito mais perigoso desta noite**, e o que ele quase custou.

    `import litellm` chama `load_dotenv()` por conta própria: lê o `.env` do diretório e
    injeta tudo em `os.environ`, no meio de uma chamada, sem ninguém pedir.

    `como_alternativa()` apaga `LLM_API_BASE` ao entrar — justamente para a chamada ao
    Gemini não herdar o endereço da Moonshot, que é do provedor principal. O import, logo
    depois, trazia o valor **de volta do arquivo**, e a chamada ao Gemini saía para
    `https://api.moonshot.ai/v1/models/gemini-3.6-flash:generateContent`. A URL foi
    capturada em 13/09/2026; o erro que voltava era `url.not_found`, em chinês, e parecia
    nome de modelo errado.

    O que torna isso grave não é o erro — é **quando** ele aparece: o caminho da IA
    alternativa só roda no dia em que a principal falha. O plano B teria estreado quebrado.
    """

    def test_o_bloco_nao_consegue_criar_variavel_nossa(self, monkeypatch):
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        with llm.ambiente_protegido():
            os.environ["LLM_API_BASE"] = "https://api.moonshot.ai/v1"
        assert "LLM_API_BASE" not in os.environ

    def test_o_bloco_nao_consegue_trocar_variavel_nossa(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "gemini-3.6-flash")
        with llm.ambiente_protegido():
            os.environ["LLM_MODEL"] = "kimi-k2.6"
        assert os.environ["LLM_MODEL"] == "gemini-3.6-flash"

    def test_o_que_e_da_biblioteca_fica(self, monkeypatch):
        """A proteção é sobre a **nossa** configuração. Uma biblioteca tem direito de
        configurar a si mesma, e apagar `LITELLM_*` quebraria o que ela acabou de ajustar."""
        monkeypatch.delenv("LITELLM_ALGUMA_COISA", raising=False)
        with llm.ambiente_protegido():
            os.environ["LITELLM_ALGUMA_COISA"] = "1"
        assert os.environ.get("LITELLM_ALGUMA_COISA") == "1"
        monkeypatch.delenv("LITELLM_ALGUMA_COISA", raising=False)

    def test_protege_mesmo_com_excecao(self, monkeypatch):
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        with pytest.raises(ValueError), llm.ambiente_protegido():
            os.environ["LLM_API_BASE"] = "https://errado"
            raise ValueError("boom")
        assert "LLM_API_BASE" not in os.environ

    def test_a_alternativa_sobrevive_a_um_dotenv_no_meio(self, monkeypatch):
        """O cenário inteiro, encenado: dentro de `como_alternativa`, algo recarrega o
        `.env`. O endereço do provedor principal **não** pode reaparecer."""
        configurar(monkeypatch, com_alternativa=True)

        def recarrega_o_dotenv(**kwargs):
            os.environ["LLM_API_BASE"] = "https://api.moonshot.ai/v1"
            return resposta_boa({"ok": True})

        with llm.como_alternativa():
            assert llm.api_base() == "", "a alternativa não declara endereço"
            with llm.ambiente_protegido():
                recarrega_o_dotenv()
            assert llm.api_base() == "", "o .env trouxe o endereço da Moonshot de volta"
