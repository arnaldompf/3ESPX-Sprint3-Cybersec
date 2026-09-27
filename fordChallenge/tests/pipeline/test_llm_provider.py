"""O provedor de LLM depois da troca para LiteLLM (multi-provedor por variável de ambiente).

Três coisas são testadas aqui, e as três são regra do projeto, não preferência:

1. **`LLM_FAKE=1` não sai para a rede** — e, mais forte que isso, nem *importa* o
   `litellm`. O teste roda num subprocesso com o `socket` sabotado: se qualquer camada
   tentar abrir conexão, o processo morre e o teste falha.
2. **O identificador de modelo** que vai ao LiteLLM é montado a partir de `LLM_PROVIDER`
   + `LLM_MODEL` para os cinco provedores previstos. Dá para testar sem chave nenhuma,
   com o cliente dublado, olhando os parâmetros da chamada.
3. **A precedência das variáveis** — as novas ganham, as antigas continuam servindo.

Nenhum teste aqui usa chave de verdade. Os valores de "chave" são placeholders, e um dos
testes verifica justamente que eles **não** aparecem em `motivo` nem em `to_dict()`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from pipeline import llm

CHAVE_PLACEHOLDER = "placeholder-de-teste-sem-valor-real"


def _subprocesso(codigo: str, raiz, **extra_env) -> subprocess.CompletedProcess:
    ambiente = dict(os.environ)
    ambiente.update({"PYTHONPATH": str(raiz), "PYTHONIOENCODING": "utf-8"})
    ambiente.update(extra_env)
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", codigo],
        cwd=str(raiz),
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=300,
    )


# ------------------------------------------------------- 1. LLM_FAKE=1 não sai da caixa
CODIGO_SEM_REDE = textwrap.dedent(
    """
    import socket, sys

    def _proibido(*a, **k):
        raise AssertionError("REDE PROIBIDA sob LLM_FAKE=1")

    socket.socket = _proibido
    socket.create_connection = _proibido
    socket.getaddrinfo = _proibido

    from pipeline import llm

    assert llm.modo_fake() is True
    r = llm.extrair_json(prompt="pergunta que ninguem gravou jamais", campos=["potencia_cv"])
    assert not r.ok, r.motivo
    assert r.dados == {}
    assert r.uso.de_fixture is True
    assert r.uso.custo_brl == 0.0
    print("SEM_REDE")

    vazados = sorted(m for m in sys.modules if m.split(".")[0] == "litellm")
    assert not vazados, vazados
    print("SEM_IMPORT_DE_LITELLM")
    """
)


def test_llm_fake_nao_sai_para_a_rede_nem_importa_litellm(raiz):
    """Com `LLM_FAKE=1` não há socket e não há `import litellm`.

    O import importa: o `litellm` busca o mapa de preços na internet ao ser importado se
    `LITELLM_LOCAL_MODEL_COST_MAP` não estiver ligado. Import preguiçoso é o que garante
    que o CI continue offline por construção, e não por sorte de configuração.
    """
    proc = _subprocesso(
        CODIGO_SEM_REDE,
        raiz,
        LLM_FAKE="1",
        LLM_PROVIDER="openai",
        LLM_MODEL="gpt-4o-mini",
        LLM_API_KEY=CHAVE_PLACEHOLDER,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "SEM_REDE" in proc.stdout
    assert "SEM_IMPORT_DE_LITELLM" in proc.stdout


def test_llm_fake_nao_toca_no_cliente_injetado(monkeypatch):
    """Nem com o cliente na mão: sob `LLM_FAKE=1` a chamada não acontece."""
    monkeypatch.setenv("LLM_FAKE", "1")

    def cliente_que_explode(**kw):
        raise AssertionError("nenhuma chamada deveria acontecer sob LLM_FAKE=1")

    resposta = llm.extrair_json(
        prompt="pergunta que ninguem gravou jamais",
        campos=["potencia_cv"],
        cliente=cliente_que_explode,
    )
    assert not resposta.ok
    assert resposta.dados == {}


# ---------------------------------------------------- 2. identificador de modelo
#: (`LLM_PROVIDER`, `LLM_MODEL`, identificador que o LiteLLM tem de receber).
#: Os prefixos são os do LiteLLM, não os nossos: `kimi` é da Moonshot AI, e o LiteLLM
#: chama esse provedor de `moonshot`.
CINCO_PROVEDORES = [
    ("anthropic", "claude-haiku-4-5-20251001", "anthropic/claude-haiku-4-5-20251001"),
    ("openai", "gpt-4o-mini", "openai/gpt-4o-mini"),
    ("gemini", "gemini-2.5-flash", "gemini/gemini-2.5-flash"),
    ("deepseek", "deepseek-chat", "deepseek/deepseek-chat"),
    ("kimi", "kimi-k2-0905-preview", "moonshot/kimi-k2-0905-preview"),
]


class ClienteDublado:
    """Registra os parâmetros da chamada e devolve uma resposta na forma do OpenAI."""

    def __init__(self, conteudo: str = '{"potencia_cv": null}'):
        self.chamadas: list[dict] = []
        self.conteudo = conteudo

    def __call__(self, **kw):
        self.chamadas.append(kw)
        return {
            "choices": [{"message": {"content": self.conteudo}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            "model": kw.get("model", ""),
        }

    @property
    def ultima(self) -> dict:
        assert self.chamadas, "o cliente nunca foi chamado"
        return self.chamadas[-1]


@pytest.mark.parametrize(("provedor", "modelo", "esperado"), CINCO_PROVEDORES)
def test_identificador_de_modelo_dos_cinco_provedores(provedor, modelo, esperado, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", provedor)
    monkeypatch.setenv("LLM_MODEL", modelo)
    assert llm.identificador_litellm(modelo) == esperado


@pytest.mark.parametrize(("provedor", "modelo", "esperado"), CINCO_PROVEDORES)
def test_chamada_dublada_manda_o_modelo_e_a_chave_certos(provedor, modelo, esperado, monkeypatch):
    """Sem chave de verdade e sem rede: o cliente é dublado e conferimos os parâmetros."""
    monkeypatch.setenv("LLM_FAKE", "0")
    monkeypatch.setenv("LLM_PROVIDER", provedor)
    monkeypatch.setenv("LLM_MODEL", modelo)
    monkeypatch.setenv("LLM_API_KEY", CHAVE_PLACEHOLDER)
    monkeypatch.setattr(llm, "_suporta_json_object", lambda _id: False)

    cliente = ClienteDublado('{"potencia_cv": {"value": 397, "evidence_quote": "397 cv"}}')
    resposta = llm.extrair_json(
        prompt="qual a potencia?",
        campos=["potencia_cv"],
        sistema="responda em JSON",
        max_tokens=512,
        cliente=cliente,
    )

    assert resposta.ok, resposta.motivo
    assert resposta.dados["potencia_cv"]["value"] == 397
    assert cliente.ultima["model"] == esperado
    assert cliente.ultima["max_tokens"] == 512
    assert cliente.ultima["api_key"] == CHAVE_PLACEHOLDER
    assert cliente.ultima["messages"][0] == {"role": "system", "content": "responda em JSON"}
    assert cliente.ultima["messages"][-1] == {"role": "user", "content": "qual a potencia?"}
    # o `Uso` guarda o modelo NU: é ele a chave da tabela de preço e a identidade da fixture
    assert resposta.uso.modelo == modelo
    assert resposta.uso.tokens_entrada == 11
    assert resposta.uso.tokens_saida == 7


def test_json_object_entra_so_quando_o_provedor_suporta(monkeypatch):
    monkeypatch.setenv("LLM_FAKE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_API_KEY", CHAVE_PLACEHOLDER)

    monkeypatch.setattr(llm, "_suporta_json_object", lambda _id: True)
    com = ClienteDublado()
    llm.extrair_json(prompt="x", campos=["potencia_cv"], cliente=com)
    assert com.ultima["response_format"] == {"type": "json_object"}

    monkeypatch.setattr(llm, "_suporta_json_object", lambda _id: False)
    sem = ClienteDublado()
    llm.extrair_json(prompt="x", campos=["potencia_cv"], cliente=sem)
    assert "response_format" not in sem.ultima


def test_modelo_com_barra_passa_intacto(monkeypatch):
    """Quem escreve `LLM_MODEL` com prefixo manda; não prefixamos duas vezes."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert (
        llm.identificador_litellm("openrouter/moonshotai/kimi-k2")
        == "openrouter/moonshotai/kimi-k2"
    )


def test_provedor_desconhecido_nao_chama_e_diz_o_porque(monkeypatch):
    monkeypatch.setenv("LLM_FAKE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "provedor-que-nao-existe")
    monkeypatch.setenv("LLM_MODEL", "algum-modelo")
    monkeypatch.setenv("LLM_API_KEY", CHAVE_PLACEHOLDER)
    cliente = ClienteDublado()
    resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"], cliente=cliente)
    assert not resposta.ok
    assert "provedor-que-nao-existe" in resposta.motivo
    assert sorted(llm.PROVEDORES)[0] in resposta.motivo, "a mensagem lista o que é aceito"
    assert cliente.chamadas == []


def test_provedor_sem_modelo_padrao_exige_LLM_MODEL(monkeypatch):
    """Não inventamos nome de modelo para provedor nenhum. Falta `LLM_MODEL`: diz e para."""
    monkeypatch.setenv("LLM_FAKE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_MODEL_SMALL", raising=False)
    monkeypatch.setenv("LLM_API_KEY", CHAVE_PLACEHOLDER)
    cliente = ClienteDublado()
    resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"], cliente=cliente)
    assert not resposta.ok
    assert "LLM_MODEL" in resposta.motivo
    assert cliente.chamadas == []


def test_a_chave_nunca_aparece_na_mensagem_nem_no_uso(monkeypatch):
    monkeypatch.setenv("LLM_FAKE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_API_KEY", CHAVE_PLACEHOLDER)
    monkeypatch.setattr(llm, "_suporta_json_object", lambda _id: False)

    def cliente_que_falha(**kw):
        raise RuntimeError(f"401 unauthorized para api_key={kw.get('api_key')}")

    resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"], cliente=cliente_que_falha)
    assert not resposta.ok
    assert CHAVE_PLACEHOLDER not in resposta.motivo
    assert "***" in resposta.motivo, "o valor sai, o formato do erro fica"
    assert CHAVE_PLACEHOLDER not in str(resposta.uso.to_dict())


def test_resposta_cercada_de_crase_ainda_vira_json(monkeypatch):
    """Provedor que devolve ```json ... ``` continua sendo lido (regra antiga, mantida)."""
    monkeypatch.setenv("LLM_FAKE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("LLM_API_KEY", CHAVE_PLACEHOLDER)
    monkeypatch.setattr(llm, "_suporta_json_object", lambda _id: False)
    cliente = ClienteDublado('```json\n{"potencia_cv": {"value": 1}}\n```')
    resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"], cliente=cliente)
    assert resposta.ok, resposta.motivo
    assert resposta.dados["potencia_cv"]["value"] == 1


# ---------------------------------------------------------------- 3. precedência
class TestPrecedenciaDeVariaveis:
    """`LLM_*` novas ganham; `LLM_MODEL_SMALL/LARGE` e `ANTHROPIC_API_KEY` seguem valendo."""

    def _limpa(self, monkeypatch):
        for nome in (
            "LLM_PROVIDER",
            "LLM_MODEL",
            "LLM_API_KEY",
            "LLM_MODEL_SMALL",
            "LLM_MODEL_LARGE",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "MOONSHOT_API_KEY",
        ):
            monkeypatch.delenv(nome, raising=False)

    def test_sem_nada_o_provedor_e_anthropic(self, monkeypatch):
        self._limpa(monkeypatch)
        assert llm.provedor_atual() == "anthropic"
        assert llm.modelo_pequeno() == "claude-haiku-4-5-20251001"
        assert llm.modelo_grande() == "claude-sonnet-5"

    def test_variaveis_antigas_de_modelo_continuam_servindo(self, monkeypatch):
        self._limpa(monkeypatch)
        monkeypatch.setenv("LLM_MODEL_SMALL", "modelo-pequeno-legado")
        monkeypatch.setenv("LLM_MODEL_LARGE", "modelo-grande-legado")
        assert llm.modelo_pequeno() == "modelo-pequeno-legado"
        assert llm.modelo_grande() == "modelo-grande-legado"

    def test_LLM_MODEL_ganha_das_antigas(self, monkeypatch):
        self._limpa(monkeypatch)
        monkeypatch.setenv("LLM_MODEL_SMALL", "modelo-pequeno-legado")
        monkeypatch.setenv("LLM_MODEL_LARGE", "modelo-grande-legado")
        monkeypatch.setenv("LLM_MODEL", "modelo-novo")
        assert llm.modelo_pequeno() == "modelo-novo"
        assert llm.modelo_grande() == "modelo-novo"

    def test_ANTHROPIC_API_KEY_continua_servindo(self, monkeypatch):
        self._limpa(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", CHAVE_PLACEHOLDER)
        assert llm.tem_chave() is True
        assert llm.chave_do_provedor() == CHAVE_PLACEHOLDER

    def test_LLM_API_KEY_ganha_da_chave_nativa(self, monkeypatch):
        self._limpa(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-nativa-legada")
        monkeypatch.setenv("LLM_API_KEY", CHAVE_PLACEHOLDER)
        assert llm.chave_do_provedor() == CHAVE_PLACEHOLDER

    def test_chave_nativa_do_provedor_escolhido(self, monkeypatch):
        self._limpa(monkeypatch)
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-outro-provedor")
        assert llm.tem_chave() is False, "chave da Anthropic não serve para a OpenAI"
        monkeypatch.setenv("OPENAI_API_KEY", CHAVE_PLACEHOLDER)
        assert llm.tem_chave() is True
        assert llm.chave_do_provedor() == CHAVE_PLACEHOLDER

    def test_sem_chave_e_sem_fake_a_mensagem_nomeia_as_variaveis(self, monkeypatch):
        self._limpa(monkeypatch)
        monkeypatch.setenv("LLM_FAKE", "0")
        monkeypatch.setenv("LLM_PROVIDER", "kimi")
        monkeypatch.setenv("LLM_MODEL", "kimi-k2-0905-preview")
        cliente = ClienteDublado()
        resposta = llm.extrair_json(prompt="x", campos=["potencia_cv"], cliente=cliente)
        assert not resposta.ok
        assert "LLM_API_KEY" in resposta.motivo
        assert "MOONSHOT_API_KEY" in resposta.motivo
        assert cliente.chamadas == []

    def test_alias_de_provedor(self, monkeypatch):
        self._limpa(monkeypatch)
        for alias, canonico in (
            ("moonshot", "kimi"),
            ("google", "gemini"),
            ("Anthropic", "anthropic"),
            ("  openai  ", "openai"),
        ):
            monkeypatch.setenv("LLM_PROVIDER", alias)
            assert llm.provedor_atual() == canonico


# --------------------------------------------------------------- custo e tokens
def test_custo_informado_pelo_litellm_vence_a_tabela_estimada():
    """Quando o LiteLLM sabe o custo real da chamada, o `Uso` usa esse número."""
    uso = llm.Uso("modelo-sem-tabela", tokens_entrada=1000, tokens_saida=100)
    assert uso.custo_usd == 0.0, "modelo fora da tabela: estimativa é zero, e é declarada"
    informado = llm.Uso(
        "modelo-sem-tabela", tokens_entrada=1000, tokens_saida=100, custo_usd_informado=0.002
    )
    assert informado.custo_usd == pytest.approx(0.002)
    assert informado.to_dict()["custo_e_estimativa"] is False
    de_fixture = llm.Uso("qualquer", custo_usd_informado=0.002, de_fixture=True)
    assert de_fixture.custo_usd == 0.0, "fixture custa zero de verdade"


# ------------------------------------------------------- o litellm de verdade existe
CODIGO_PROVEDORES = textwrap.dedent(
    """
    import os
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    import litellm
    from pipeline import llm

    conhecidos = {getattr(p, "value", p) for p in (getattr(litellm, "provider_list", None) or [])}
    faltando = [s for s, p in llm.PROVEDORES.items() if p.litellm not in conhecidos]
    assert not faltando, faltando
    print("PROVEDORES_CONFEREM")
    """
)


@pytest.mark.slow
def test_os_prefixos_sao_provedores_reais_do_litellm(raiz):
    """Os prefixos que montamos são provedores do LiteLLM, não invenção nossa.

    Roda em subprocesso de propósito: importar o `litellm` dentro do processo do pytest
    contaminaria os outros ~1.4k testes (logging, asyncio, mapa de preços) e é justamente
    o import que o resto da suíte não deve fazer.
    """
    proc = _subprocesso(CODIGO_PROVEDORES, raiz, LITELLM_LOCAL_MODEL_COST_MAP="True")
    if "ModuleNotFoundError" in proc.stderr and "litellm" in proc.stderr:
        pytest.skip("litellm não instalado neste ambiente")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "PROVEDORES_CONFEREM" in proc.stdout


# ------------------------------------------- 5. a suite nao pode ter chave no ambiente
def test_nenhuma_chave_de_provedor_sobrevive_ao_conftest():
    """Durante a suíte, **nenhuma** variável de chave está definida.

    A garantia é do `tests/conftest.py`, e ela existe porque falhou uma vez: com
    `LLM_PROVIDER=moonshot` e `LLM_API_KEY` no `.env` desta máquina, um teste que liga
    `LLM_FAKE=0` fez uma chamada de rede de verdade. Este teste é o alarme: se alguém
    acrescentar um provedor com nome de chave novo em `pipeline/llm.py` e esquecer de
    listá-lo no `conftest`, ele acende aqui, e não numa fatura.
    """
    from tests.conftest import CHAVES_DE_PROVEDOR

    esperadas = {"LLM_API_KEY", *(env for p in llm.PROVEDORES.values() for env in p.envs)}
    faltando = sorted(esperadas - set(CHAVES_DE_PROVEDOR))
    assert not faltando, f"conftest.CHAVES_DE_PROVEDOR não cobre: {faltando}"

    definidas = sorted(nome for nome in CHAVES_DE_PROVEDOR if os.environ.get(nome))
    assert not definidas, f"chave de provedor viva durante a suíte: {definidas}"


# ------------------------------------ 6. o replay nao pode depender do .env de quem roda
def test_o_replay_do_task_fixa_o_provedor_das_fixtures(monkeypatch):
    """`make eval` e `make test` medem o mesmo, em qualquer maquina.

    **Defeito medido em 12/09/2026.** A fixture de LLM e indexada por
    `hash(modelo, campos, prompt)`, e as gravadas trazem o modelo historico do projeto (a
    Anthropic). Com `LLM_MODEL=kimi-k2.6` no `.env` desta maquina, a chave muda, nenhuma
    fixture casa, e o pipeline segue com os campos vazios **sem um erro sequer**: o eval
    caia de 104/109 para 102/109 e o grounding, de 107/107 para 105/105.

    O sintoma era o pior possivel: `pytest` (que desarma o provedor no `conftest`) dava um
    numero, `make eval` dava outro, e os dois diziam ter rodado a mesma coisa.
    """
    import importlib.util

    caminho = raiz_do_projeto() / "scripts" / "task.py"
    spec = importlib.util.spec_from_file_location("task_para_teste", caminho)
    assert spec and spec.loader
    task = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(task)

    monkeypatch.setenv("LLM_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_MODEL", "kimi-k2.6")
    monkeypatch.setenv("LLM_API_KEY", CHAVE_PLACEHOLDER)
    task.replay_env()

    assert os.environ["REPLAY_MODE"] == "1"
    assert os.environ["LLM_FAKE"] == "1"
    assert llm.provedor_atual() == "anthropic"
    assert llm.modelo_pequeno() == "claude-haiku-4-5-20251001"
    assert not llm.tem_chave(), "nenhuma credencial de verdade sobrevive ao modo replay"


def test_as_duas_listas_de_chave_cobrem_o_mesmo(monkeypatch):
    """`scripts/task.py` e `tests/conftest.py` guardam a mesma lista, e ela tem de bater.

    Duas copias divergem; esta e a guarda. Um provedor novo em `pipeline/llm.py` precisa
    entrar nas duas, e o teste diz qual esta faltando.
    """
    import importlib.util

    from tests.conftest import CHAVES_DE_PROVEDOR as DO_CONFTEST

    caminho = raiz_do_projeto() / "scripts" / "task.py"
    spec = importlib.util.spec_from_file_location("task_para_lista", caminho)
    assert spec and spec.loader
    task = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(task)

    esperadas = {"LLM_API_KEY", *(env for p in llm.PROVEDORES.values() for env in p.envs)}
    assert set(task.CHAVES_DE_PROVEDOR) == set(DO_CONFTEST)
    assert esperadas <= set(task.CHAVES_DE_PROVEDOR)


def raiz_do_projeto():
    from pathlib import Path

    return Path(__file__).resolve().parents[2]
