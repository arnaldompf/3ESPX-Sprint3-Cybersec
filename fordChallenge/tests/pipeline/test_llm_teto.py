"""O modelo sob orçamento: teto de gasto, livro-razão, aviso de espera e raciocínio desligado.

Escrito em 13/09/2026, quando a Pesquisa passou a usar o modelo de verdade numa conversa.
Quatro garantias, nenhuma delas um pedido no prompt:

* **o teto de gasto recusa antes de chamar.** `LLM_TETO_USD` é global à máquina: quando o
  livro-razão passa dele, nenhuma chamada sai — nem para a IA alternativa, que gastaria de
  outra conta o que a regra quer impedir;
* **o livro-razão soma o que aconteceu de verdade.** Fixture não entra; chamada real entra
  com o custo que o provedor informou ou a estimativa da tabela;
* **quem espera avisa.** A trilha da pesquisa precisa saber quando o trinco de vazão dorme,
  para a tela dizer "aguardando 21 s pela cota" em vez de parecer travada;
* **a Kimi não raciocina por padrão.** Medido no spike da WP-42: pedindo 900 tokens, o
  `kimi-k2.6` gastou 899 pensando e não escreveu nada; com `thinking: disabled` na API a
  mesma pergunta voltou em 1 s. `LLM_RACIOCINIO=1` religa.

Nenhum teste toca a rede: o `completion` é substituído e `time.sleep` é observado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import llm

CHAVE = "placeholder-de-teste-sem-valor-real"


@pytest.fixture
def kimi(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Kimi sem rede, livro-razão isolado num arquivo descartável."""
    monkeypatch.setenv("LLM_FAKE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_MODEL", "kimi-k2.6")
    monkeypatch.setenv("LLM_API_KEY", CHAVE)
    monkeypatch.setenv("LLM_API_BASE", "https://api.moonshot.ai/v1")
    monkeypatch.setenv("LLM_MIN_INTERVAL_S", "0")
    monkeypatch.delenv("LLM_TETO_USD", raising=False)
    monkeypatch.delenv("LLM_RACIOCINIO", raising=False)
    livro = tmp_path / "llm-gasto.json"
    monkeypatch.setenv("LLM_LIVRO_RAZAO", str(livro))
    monkeypatch.setattr(llm, "_ultima_chamada", 0.0, raising=False)
    return livro


def _resposta(tokens_saida: int = 30) -> dict:
    return {
        "choices": [{"message": {"content": '{"potencia_cv": {"value": 397}}'}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": tokens_saida},
    }


def _instalar(monkeypatch: pytest.MonkeyPatch, respostas: list) -> list[dict]:
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
    dormidas: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: dormidas.append(s))
    return dormidas


# ----------------------------------------------------------------- livro-razão
class TestOLivroRazao:
    def test_chamada_real_entra_no_livro_com_o_custo(self, kimi: Path, monkeypatch):
        _instalar(monkeypatch, [_resposta(tokens_saida=1000)])
        _observar_sono(monkeypatch)
        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert resposta.ok, resposta.motivo

        gasto = llm.gasto_da_rodada()
        assert gasto["chamadas"] == 1
        # 1000 tokens de entrada e 1000 de saída na tabela da Kimi (0,95 + 4,00 por milhão).
        assert gasto["usd"] == pytest.approx(resposta.uso.custo_usd)
        assert gasto["usd"] > 0
        assert kimi.exists()
        assert json.loads(kimi.read_text(encoding="utf-8"))["chamadas"] == 1

    def test_fixture_nao_entra_no_livro(self, kimi: Path, monkeypatch):
        monkeypatch.setenv("LLM_FAKE", "1")
        llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert llm.gasto_da_rodada()["chamadas"] == 0
        assert not kimi.exists()

    def test_sem_livro_o_gasto_e_zero_e_nao_levanta(self, kimi: Path):
        assert llm.gasto_da_rodada() == {"desde": "", "usd": 0.0, "chamadas": 0}


# ----------------------------------------------------------------------- teto
class TestOTetoDeGasto:
    def test_teto_atingido_recusa_ANTES_de_chamar(self, kimi: Path, monkeypatch):
        kimi.write_text(json.dumps({"desde": "2026-09-13", "usd": 2.5, "chamadas": 9}))
        monkeypatch.setenv("LLM_TETO_USD", "2")
        vistos = _instalar(monkeypatch, [_resposta()])
        _observar_sono(monkeypatch)

        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])

        assert vistos == [], "com o teto batido, nenhuma chamada pode sair"
        assert not resposta.ok
        assert resposta.teto_atingido
        assert "teto" in resposta.motivo.lower() and "US$" in resposta.motivo

    def test_o_teto_e_global_e_a_alternativa_NAO_entra(self, kimi: Path, monkeypatch):
        kimi.write_text(json.dumps({"desde": "2026-09-13", "usd": 2.5, "chamadas": 9}))
        monkeypatch.setenv("LLM_TETO_USD", "2")
        monkeypatch.setenv("LLM_PROVIDER_ALT", "gemini")
        monkeypatch.setenv("LLM_MODEL_ALT", "gemini-3.1-flash-lite")
        monkeypatch.setenv("LLM_API_KEY_ALT", CHAVE)
        vistos = _instalar(monkeypatch, [_resposta(), _resposta()])
        _observar_sono(monkeypatch)

        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])

        assert vistos == []
        assert resposta.teto_atingido
        assert "nem para a IA alternativa" in resposta.motivo

    def test_abaixo_do_teto_a_chamada_sai(self, kimi: Path, monkeypatch):
        kimi.write_text(json.dumps({"desde": "2026-09-13", "usd": 0.5, "chamadas": 2}))
        monkeypatch.setenv("LLM_TETO_USD", "2")
        vistos = _instalar(monkeypatch, [_resposta()])
        _observar_sono(monkeypatch)
        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert resposta.ok and len(vistos) == 1

    def test_teto_vazio_e_sem_teto(self, kimi: Path, monkeypatch):
        monkeypatch.setenv("LLM_TETO_USD", "")
        assert llm.teto_usd() is None
        monkeypatch.setenv("LLM_TETO_USD", "abc")
        assert llm.teto_usd() is None


# --------------------------------------------------------------------- espera
class TestOAvisoDeEspera:
    def test_quem_escuta_recebe_a_espera_antes_de_dormir(self, kimi: Path, monkeypatch):
        import time

        monkeypatch.setenv("LLM_MIN_INTERVAL_S", "21")
        monkeypatch.setattr(llm, "_ultima_chamada", time.monotonic(), raising=False)
        _instalar(monkeypatch, [_resposta()])
        dormidas = _observar_sono(monkeypatch)
        avisos: list[tuple[float, str]] = []

        with llm.avisando_espera(lambda s, motivo: avisos.append((s, motivo))):
            llm.extrair_json(prompt="x", campos=["potencia_cv"])

        assert avisos, "a espera aconteceu e ninguém foi avisado"
        segundos, motivo = avisos[0]
        assert 0 < segundos <= 21
        assert motivo == "intervalo mínimo"
        assert dormidas and dormidas[0] == pytest.approx(segundos, abs=0.5)

    def test_sem_espera_ninguem_e_avisado(self, kimi: Path, monkeypatch):
        _instalar(monkeypatch, [_resposta()])
        _observar_sono(monkeypatch)
        avisos: list = []
        with llm.avisando_espera(lambda s, m: avisos.append((s, m))):
            llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert avisos == []

    def test_o_429_tambem_avisa(self, kimi: Path, monkeypatch):
        _instalar(monkeypatch, [RuntimeError("429 rate limit exceeded"), _resposta()])
        _observar_sono(monkeypatch)
        avisos: list = []
        with llm.avisando_espera(lambda s, m: avisos.append((s, m))):
            resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert resposta.ok
        assert any(m == "429" for _, m in avisos)

    def test_ouvinte_que_levanta_nao_derruba_a_chamada(self, kimi: Path, monkeypatch):
        import time

        monkeypatch.setenv("LLM_MIN_INTERVAL_S", "21")
        monkeypatch.setattr(llm, "_ultima_chamada", time.monotonic(), raising=False)
        _instalar(monkeypatch, [_resposta()])
        _observar_sono(monkeypatch)

        def explode(*_):
            raise RuntimeError("ouvinte quebrado")

        with llm.avisando_espera(explode):
            resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert resposta.ok


# ---------------------------------------------------------------- raciocínio
class TestORaciocinio:
    def test_a_kimi_vai_sem_raciocinio_por_padrao(self, kimi: Path, monkeypatch):
        vistos = _instalar(monkeypatch, [_resposta()])
        _observar_sono(monkeypatch)
        llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert vistos[0]["extra_body"] == {"thinking": {"type": "disabled"}}

    def test_LLM_RACIOCINIO_religa(self, kimi: Path, monkeypatch):
        monkeypatch.setenv("LLM_RACIOCINIO", "1")
        vistos = _instalar(monkeypatch, [_resposta()])
        _observar_sono(monkeypatch)
        llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert "extra_body" not in vistos[0]

    def test_provedor_sem_a_opcao_nao_recebe_extra_body(self, kimi: Path, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("LLM_MODEL", "claude-haiku-4-5-20251001")
        monkeypatch.delenv("LLM_API_BASE")
        vistos = _instalar(monkeypatch, [_resposta()])
        _observar_sono(monkeypatch)
        llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert "extra_body" not in vistos[0]


# ------------------------------------------------------------------ sem saldo
class TestSemSaldo:
    def test_conta_sem_saldo_vira_bandeira_estruturada(self, kimi: Path, monkeypatch):
        _instalar(monkeypatch, [RuntimeError("429 exceeded_current_quota_error: no balance")])
        _observar_sono(monkeypatch)
        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert not resposta.ok
        assert resposta.sem_saldo
        assert llm.e_conta_sem_saldo(resposta.motivo)

    def test_falha_comum_nao_e_sem_saldo(self, kimi: Path, monkeypatch):
        _instalar(monkeypatch, [RuntimeError("connection reset")])
        _observar_sono(monkeypatch)
        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert not resposta.ok and not resposta.sem_saldo

    def test_a_medicao_conta_sem_saldo_e_teto(self, kimi: Path, monkeypatch):
        _instalar(monkeypatch, [RuntimeError("insufficient balance")])
        _observar_sono(monkeypatch)
        with llm.medindo() as m:
            llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert m.sem_saldo == 1
        kimi.write_text(json.dumps({"desde": "2026-09-13", "usd": 9.0, "chamadas": 1}))
        monkeypatch.setenv("LLM_TETO_USD", "2")
        with llm.medindo() as m2:
            llm.extrair_json(prompt="x", campos=["potencia_cv"])
        assert m2.teto_atingido == 1
