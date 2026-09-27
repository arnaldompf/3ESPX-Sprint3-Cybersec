"""Configuração global da suíte.

Garante que `uv run pytest` sozinho comporte-se como `python scripts/task.py test`:
`.env` carregado, `REPLAY_MODE=1` e `LLM_FAKE=1` ligados, `DATABASE_URL` apontando para
um SQLite de teste quando ninguém definiu.

`REPLAY_MODE` e `LLM_FAKE` são ligados **antes** de qualquer import de `pipeline` para
que nenhum teste consiga tocar a rede ou um provedor de LLM real — é regra do projeto,
não conveniência.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _carrega_dotenv() -> None:
    arquivo = ROOT / ".env"
    if not arquivo.exists():
        return
    for bruto in arquivo.read_text(encoding="utf-8").splitlines():
        linha = bruto.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


#: Todo nome de variável que o `pipeline.llm` aceita como chave de provedor.
#:
#: Escrito à mão, e não importado de `pipeline.llm`, porque este bloco roda **antes** de
#: qualquer import de `pipeline` — que é justamente o que dá a garantia. Um nome novo lá
#: precisa de um nome novo aqui, e há teste que confere isso
#: (`tests/pipeline/test_llm_provider.py`).
CHAVES_DE_PROVEDOR = (
    "LLM_API_KEY",
    "LLM_API_KEY_ALT",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY",
    "MOONSHOT_API_KEY",
    "KIMI_API_KEY",
)


#: A **regra**, além da lista, e o motivo de haver as duas.
#:
#: A lista acima já falhou duas vezes pelo mesmo mecanismo: alguém acrescenta uma variável
#: de credencial em `pipeline/llm.py` e a lista fica para trás. Em 12/09/2026 foi
#: `LLM_API_KEY` (o `.env` desta máquina passou a trazê-la e um teste fez chamada real à
#: Moonshot); em 13/09/2026 foi `LLM_API_KEY_ALT`, recém-criada — o `.env` a trouxe, os
#: testes de vazão viram `tem_alternativa()` verdadeira, o fallback disparou, e o valor da
#: chave **saiu na mensagem de falha do pytest**.
#:
#: Uma lista guarda o que alguém lembrou de escrever; a regra guarda o que ninguém pensou.
#: As duas juntas, porque a regra não cobre nome fora de padrão (`MOONSHOT_TOKEN`) e a
#: lista não cobre nome que ainda não existe.
def _e_nome_de_credencial(nome: str) -> bool:
    """`True` para variável que guarda credencial **de provedor externo**.

    O escopo é esse e não mais. A primeira versão desta regra também pegava `_SECRET` e
    `_TOKEN`, e com isso apagou o `JWT_SECRET` que o próprio `conftest` define três linhas
    acima — o seed do admin parou de rodar. `JWT_SECRET` e `ADMIN_PASSWORD` são segredos
    **nossos, de teste**, e a suíte precisa deles; o que não pode viver aqui é credencial
    que faz uma chamada sair desta máquina.
    """
    maiusculo = nome.upper()
    return maiusculo in CHAVES_DE_PROVEDOR or "_API_KEY" in maiusculo


def _desarma_provedor_real() -> None:
    """Tira do ambiente **toda** credencial de LLM antes do primeiro import de `pipeline`.

    A garantia da docstring deste módulo ("nenhum teste consegue tocar um provedor de LLM
    real") estava furada, e o furo foi medido em 12/09/2026: o `.env` desta máquina passou
    a trazer `LLM_PROVIDER=moonshot` e `LLM_API_KEY`, o `_carrega_dotenv` acima os
    carrega, e `test_sem_chave_e_sem_fake_nao_chama_nada` — que liga `LLM_FAKE=0` e apaga
    só `ANTHROPIC_API_KEY` — **fez uma chamada de rede de verdade** à Moonshot. O teste
    falhou por sorte (a conta respondeu erro de saldo); tivesse respondido 200, teria
    passado gastando token e escondendo o furo.

    `LLM_FAKE=1` sozinho não basta: qualquer teste pode desligá-lo, e alguns desligam de
    propósito. Sem chave no ambiente, desligar o modo fake deixa de ser perigoso — o
    provedor diz "chave ausente" e não chama nada, que é exatamente o comportamento sob
    teste. Quem precisa de uma chave usa `monkeypatch.setenv` com o placeholder do
    próprio teste, e aí ela vale só ali.
    """
    for nome in [n for n in os.environ if _e_nome_de_credencial(n)]:
        os.environ.pop(nome, None)
    for nome in CHAVES_DE_PROVEDOR:
        os.environ.pop(nome, None)
    # Provedor e modelo também saem: o default histórico do projeto é a Anthropic, e um
    # `LLM_PROVIDER` de máquina mudaria o texto do motivo que os testes conferem.
    os.environ["LLM_PROVIDER"] = "anthropic"
    os.environ.pop("LLM_MODEL", None)
    # **E a IA alternativa inteira.** Não basta tirar a chave dela: `LLM_PROVIDER_ALT`
    # sozinho já muda o caminho que os testes de vazão exercitam — com a alternativa
    # configurada, uma falha de saldo deixa de ser o fim da chamada e vira a segunda
    # tentativa, e três testes que contavam chamadas passaram a ver duas.
    for nome in (
        "LLM_PROVIDER_ALT",
        "LLM_MODEL_ALT",
        "LLM_API_BASE_ALT",
        "LLM_MIN_INTERVAL_S_ALT",
        "LLM_API_BASE",
        "LLM_MIN_INTERVAL_S",
        # O teto de gasto e o raciocínio são configuração da máquina, não do teste: um
        # `.env` com `LLM_TETO_USD=2` faria a suíte recusar chamadas dubladas.
        "LLM_TETO_USD",
        "LLM_RACIOCINIO",
    ):
        os.environ.pop(nome, None)
    # O livro-razão dos testes é descartável. Sem isto, um teste com `cliente` dublado
    # somaria centavos imaginários ao gasto real da máquina em `data/llm-gasto.json`.
    os.environ["LLM_LIVRO_RAZAO"] = str(ROOT / ".tmp" / "llm-gasto-testes.json")


_carrega_dotenv()
os.environ["REPLAY_MODE"] = "1"
os.environ["LLM_FAKE"] = "1"
# **O leitor de PDF dos testes é fixado no `pdfplumber`.**
#
# Ele também é o padrão de produção quando instalado: no PDF oficial de 10 páginas medido em
# 14/09/2026, entregou as mesmas 6 tabelas e os mesmos valores-alvo em 2,9 s, contra 153,6 s do
# Docling. O Docling continua como fallback de OCR e pode ser forçado no teste dedicado.
#
# E custa relógio: com o Docling ativo a suíte do pipeline foi de 45 s para **9 minutos**,
# carregando modelo de visão para reler o mesmo PDF a cada teste.
#
# Quem quiser medir o Docling usa `PDF_MOTOR=docling` no comando ou o teste slow dedicado.
os.environ.setdefault("PDF_MOTOR", "pdfplumber")
_desarma_provedor_real()
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test.db")
os.environ.setdefault("JWT_SECRET", "teste-nao-e-segredo-de-producao-0123456789abcdef")
os.environ.setdefault("ADMIN_EMAIL", "admin@specradar.local")
os.environ.setdefault("ADMIN_PASSWORD", "teste-admin")
os.environ.setdefault("SPECRADAR_USER_AGENT", "SpecRadar/0.1 (testes; contato: ci@example.com)")
(ROOT / "data").mkdir(exist_ok=True)
# --basetemp=.tmp/pytest (pyproject) exige que o pai exista antes do primeiro teste.
(ROOT / ".tmp").mkdir(exist_ok=True)


@pytest.fixture(autouse=True)
def _restaura_modo_determinista():
    """Devolve `REPLAY_MODE=1`, `LLM_FAKE=1` e o provedor desarmado ao fim de **cada** teste.

    Existe por bug real: um teste marcado `live` fazia `os.environ["REPLAY_MODE"]="0"`
    direto, e os 20 testes de resolvedor que rodavam depois dele quebravam — verify verde
    isolado, suíte vermelha junto, sintoma a dez arquivos de distância da causa.

    O desarme do provedor entrou aqui em 12/09/2026, e por uma causa que **nenhum teste
    escreveu**: `tests/pipeline/test_fetch.py` chama `browser.disponivel()`, que faz
    `import crawl4ai`, e o Crawl4AI roda `load_dotenv()` no próprio import. O `.env` desta
    máquina volta inteiro para o ambiente — `LLM_PROVIDER=moonshot` e `LLM_API_KEY`
    incluídos — e dali em diante qualquer teste que ligue `LLM_FAKE=0` tem uma chave de
    verdade na mão. O desarme do topo do arquivo, sozinho, não alcança isso: ele roda uma
    vez, e o import acontece no meio da suíte.

    A garantia passa a ser estrutural, não disciplina de quem escreve o teste: quem
    precisa de `REPLAY_MODE=0` durante o teste continua podendo desligar; o que não pode
    mais é o desligamento **vazar** para o teste seguinte.
    """
    yield
    os.environ["REPLAY_MODE"] = "1"
    os.environ["LLM_FAKE"] = "1"
    _desarma_provedor_real()


@pytest.fixture(scope="session")
def raiz() -> Path:
    """Raiz do repositório."""
    return ROOT


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    """URL de um SQLite descartável, um por teste."""
    return f"sqlite:///{(tmp_path / 'teste.db').as_posix()}"
