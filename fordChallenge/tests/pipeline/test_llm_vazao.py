"""O portão de vazão do provedor real: uma chamada de cada vez, com intervalo e retentativa.

Escrito em 12/09/2026, quando a conta Kimi (Moonshot AI) desta máquina entrou no `.env`.
Ela é **Tier0**: concorrência 1, 3 requisições por minuto, 500 mil tokens por minuto,
1,5 milhão por dia. Sem portão, a segunda chamada de qualquer extração toma 429 e a ficha
sai vazia com o motivo errado — "o provedor barrou" aparece na tela como "a fonte não diz".

O caso que separa este arquivo de um retry comum: **a Moonshot devolve conta sem saldo
também como 429**, com `exceeded_current_quota_error`. Esperar não resolve saldo. Tratar os
dois iguais faria o pipeline dormir minutos por campo para receber a mesma resposta — e foi
exatamente o que esta conta respondeu na noite em que o portão foi escrito.

Nenhum teste aqui toca a rede: o `completion` é substituído e `time.sleep` é observado.
"""

from __future__ import annotations

import pytest

from pipeline import llm

CHAVE_PLACEHOLDER = "placeholder-de-teste-sem-valor-real"


@pytest.fixture
def kimi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ambiente do provedor real, sem rede: Kimi, chave de mentira, modo fake desligado."""
    monkeypatch.setenv("LLM_FAKE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_MODEL", "kimi-k2.6")
    monkeypatch.setenv("LLM_API_KEY", CHAVE_PLACEHOLDER)
    monkeypatch.setenv("LLM_API_BASE", "https://api.moonshot.ai/v1")
    # O relógio do portão é de módulo: sem zerar, um teste herda a última chamada do
    # anterior e o intervalo medido aqui vira o resto do intervalo de lá.
    monkeypatch.setattr(llm, "_ultima_chamada", 0.0, raising=False)


def _resposta(conteudo: str = '{"potencia_cv": {"value": 397}}') -> dict:
    return {
        "choices": [{"message": {"content": conteudo}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
    }


def _instalar(monkeypatch: pytest.MonkeyPatch, respostas: list) -> list[dict]:
    """Substitui o `completion` real por uma fila de respostas. Devolve os argumentos vistos."""
    vistos: list[dict] = []
    fila = list(respostas)

    def falso(**kwargs):
        vistos.append(kwargs)
        proxima = fila.pop(0) if fila else _resposta()
        if isinstance(proxima, Exception):
            raise proxima
        return proxima

    monkeypatch.setattr(llm, "_completion_padrao", lambda: falso)
    return vistos


def _observar_sono(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Troca `time.sleep` por um registrador. O teste mede intenção, não relógio."""
    dormidas: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: dormidas.append(s))
    return dormidas


# --------------------------------------------------------------------- endereço
class TestEnderecoDaApi:
    def test_o_api_base_viaja_na_chamada(self, kimi, monkeypatch):
        """Sem isto, a chave global bate no endereço da China e volta erro de autenticação."""
        vistos = _instalar(monkeypatch, [_resposta()])
        _observar_sono(monkeypatch)
        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert resposta.ok, resposta.motivo
        assert vistos[0]["api_base"] == "https://api.moonshot.ai/v1"
        assert vistos[0]["model"] == "moonshot/kimi-k2.6"

    def test_sem_api_base_o_argumento_nao_e_mandado(self, kimi, monkeypatch):
        """Vazio significa "o default do LiteLLM", e mandar vazio quebraria a rota dele."""
        monkeypatch.delenv("LLM_API_BASE")
        vistos = _instalar(monkeypatch, [_resposta()])
        _observar_sono(monkeypatch)
        llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert "api_base" not in vistos[0]

    def test_a_chave_nunca_aparece_no_motivo(self, kimi, monkeypatch):
        _instalar(monkeypatch, [RuntimeError(f"falhou com a chave {CHAVE_PLACEHOLDER}")])
        _observar_sono(monkeypatch)
        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert CHAVE_PLACEHOLDER not in resposta.motivo
        assert "***" in resposta.motivo


# --------------------------------------------------------------------- intervalo
class TestIntervaloMinimo:
    def test_o_provedor_kimi_pede_21_segundos(self, kimi):
        assert llm.intervalo_minimo() == 21.0

    def test_a_variavel_de_ambiente_ganha_do_provedor(self, kimi, monkeypatch):
        monkeypatch.setenv("LLM_MIN_INTERVAL_S", "3")
        assert llm.intervalo_minimo() == 3.0

    def test_valor_ilegivel_cai_no_do_provedor(self, kimi, monkeypatch):
        """`LLM_MIN_INTERVAL_S=rapido` não pode virar "sem intervalo" em silêncio."""
        monkeypatch.setenv("LLM_MIN_INTERVAL_S", "rapido")
        assert llm.intervalo_minimo() == 21.0

    def test_provedor_sem_limite_nao_espera(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        assert llm.intervalo_minimo() == 0.0

    def test_a_segunda_chamada_espera_o_intervalo(self, kimi, monkeypatch):
        """Duas chamadas seguidas: a segunda dorme o que falta dos 21 s."""
        _instalar(monkeypatch, [_resposta(), _resposta()])
        dormidas = _observar_sono(monkeypatch)
        llm.extrair_json(prompt="a", campos=["potencia_cv"])
        llm.extrair_json(prompt="b", campos=["potencia_cv"])
        # A primeira não espera (o relógio começa zerado); a segunda espera quase tudo.
        assert len(dormidas) == 1
        assert 19.0 < dormidas[0] <= 21.0

    def test_o_dublê_de_teste_nao_passa_pelo_portao(self, kimi, monkeypatch):
        """Com `cliente` injetado não há provedor, e dormir 21 s viraria suíte de espera."""
        dormidas = _observar_sono(monkeypatch)
        llm.extrair_json(prompt="x", campos=["potencia_cv"], cliente=lambda **k: _resposta())
        llm.extrair_json(prompt="y", campos=["potencia_cv"], cliente=lambda **k: _resposta())
        assert dormidas == []


# ------------------------------------------------------------------- retentativa
class TestRetentativa:
    def test_429_de_pressa_e_reapresentado(self, kimi, monkeypatch):
        erro = RuntimeError("litellm.RateLimitError: 429 rate limit exceeded")
        _instalar(monkeypatch, [erro, erro, _resposta()])
        _observar_sono(monkeypatch)
        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert resposta.ok, resposta.motivo
        assert resposta.dados["potencia_cv"]["value"] == 397

    def test_a_espera_cresce_a_cada_reapresentacao(self, kimi, monkeypatch):
        """A espera **extra** de cada 429 cresce: 1x, 2x, 3x o intervalo.

        Se o provedor disse "rápido demais" respeitando 21 s, 21 s está curto para esta
        conta, e repetir o mesmo intervalo só gastaria as tentativas restantes. O teste
        olha a espera de recuo (`sleep(intervalo * tentativa)`) e não a do intervalo
        mínimo, que é fixa por construção.
        """
        erro = RuntimeError("litellm.RateLimitError: 429 rate limit exceeded")
        _instalar(monkeypatch, [erro, erro, erro, _resposta()])
        dormidas = _observar_sono(monkeypatch)
        llm.extrair_json(prompt="x", campos=["potencia_cv"])
        recuos = [s for s in dormidas if s > 21.0]
        assert recuos == [42.0, 63.0], dormidas

    def test_desiste_depois_do_teto_e_diz_por_que(self, kimi, monkeypatch):
        erro = RuntimeError("litellm.RateLimitError: 429 rate limit exceeded")
        vistos = _instalar(monkeypatch, [erro] * 10)
        _observar_sono(monkeypatch)
        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert not resposta.ok
        assert "429" in resposta.motivo
        assert len(vistos) == llm.TENTATIVAS_EM_429

    def test_conta_sem_saldo_volta_na_hora(self, kimi, monkeypatch):
        """**O caso que importa.** Saldo não se resolve esperando.

        A Moonshot devolve conta suspensa como 429, o mesmo código de "rápido demais".
        Reapresentar gastaria minutos por campo para receber a mesma resposta — medido na
        conta desta máquina em 12/09/2026.
        """
        erro = RuntimeError(
            "litellm.RateLimitError: MoonshotException - Your account org-x is suspended "
            "due to insufficient balance, please recharge your account"
        )
        vistos = _instalar(monkeypatch, [erro] * 10)
        _observar_sono(monkeypatch)
        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert not resposta.ok
        assert len(vistos) == 1, "uma tentativa só: esperar não resolve saldo"
        assert "insufficient balance" in resposta.motivo

    def test_erro_que_nao_e_limite_nao_e_reapresentado(self, kimi, monkeypatch):
        """Modelo inexistente, JSON quebrado, rede caída: repetir não melhora nenhum."""
        vistos = _instalar(monkeypatch, [RuntimeError("NotFoundError: model not found")] * 5)
        _observar_sono(monkeypatch)
        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert not resposta.ok
        assert len(vistos) == 1


# ------------------------------------------------------------------ concorrência
def test_uma_chamada_de_cada_vez(kimi, monkeypatch):
    """Concorrência 1: duas threads não entram no provedor ao mesmo tempo.

    Tier0 recusa a segunda chamada simultânea mesmo respeitando o intervalo. O trinco é de
    módulo porque a cota é da conta, e a conta é do processo.
    """
    import threading

    dentro = []
    pico = []

    def falso(**kwargs):
        dentro.append(1)
        pico.append(len(dentro))
        dentro.pop()
        return _resposta()

    monkeypatch.setattr(llm, "_completion_padrao", lambda: falso)
    monkeypatch.setenv("LLM_MIN_INTERVAL_S", "0")
    _observar_sono(monkeypatch)

    fios = [
        threading.Thread(target=llm.extrair_json, kwargs={"prompt": f"p{i}", "campos": ["x"]})
        for i in range(6)
    ]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join(timeout=30)
    assert max(pico) == 1


# ------------------------------------------------------------------------ custo
def test_o_kimi_tem_preco_na_tabela_de_estimativa():
    """Sem preço, o eval reportaria custo zero para uma chamada que custou dinheiro."""
    uso = llm.Uso("kimi-k2.6", tokens_entrada=1_000_000, tokens_saida=1_000_000)
    assert uso.custo_usd > 0
    assert uso.to_dict()["custo_e_estimativa"] is True
