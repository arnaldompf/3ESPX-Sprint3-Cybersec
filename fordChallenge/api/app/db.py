"""Engine e sessões do SpecRadar.

A URL do banco vem de `api.app.config.Settings` (WP-04), que é a única fonte do formato e
do default; nada aqui lê `os.environ` por conta própria.

O default é SQLite porque esta máquina não tem Docker (DECISOES_NOITE.md D-05). Postgres 16
segue sendo o alvo de produção, então nada aqui pode ser exclusivo de um dos dois bancos:
`check_same_thread` e a criação do diretório do arquivo só se aplicam ao SQLite e ficam
atrás de um `if`.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from api.app.config import URL_PADRAO_BANCO, Settings

#: Nome público deste módulo desde a WP-03; o valor mora em `config.py`, como default do
#: campo `database_url` de `Settings`.
URL_PADRAO = URL_PADRAO_BANCO


def database_url() -> str:
    """URL do banco, resolvida **agora**, a partir do ambiente.

    Passa por `Settings` mas de propósito **não** pelo `get_settings()` cacheado: Alembic,
    o seed e os testes trocam `DATABASE_URL` no meio do processo, e uma configuração
    congelada no primeiro import faria a migração e a sessão apontarem para bancos
    diferentes — a falha mais chata de diagnosticar que existe. O custo é validar um punhado
    de campos por chamada; `engine()` continua cacheado, então nenhuma conexão extra é
    aberta por causa disto.
    """
    return Settings().database_url


def _e_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def criar_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Cria um engine novo para `url` (ou para a do ambiente).

    Cada chamada devolve um engine próprio — é o que os testes querem, um banco
    descartável por teste. Para o processo de longa duração (API, worker) use
    :func:`engine`, que reaproveita.
    """
    alvo = url or database_url()
    kwargs: dict[str, object] = {"echo": echo}
    if _e_sqlite(alvo):
        # O SQLite abre a conexão presa à thread que a criou; o FastAPI atende em
        # threads de um pool. Sem isto, qualquer request fora da thread de origem quebra.
        kwargs["connect_args"] = {"check_same_thread": False}
        arquivo = alvo.replace("sqlite:///", "", 1)
        if arquivo and arquivo != ":memory:":
            Path(arquivo).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return create_engine(alvo, **kwargs)  # type: ignore[arg-type]


@lru_cache(maxsize=8)
def _engine_cacheado(url: str) -> Engine:
    """O cache de verdade, com a URL **já resolvida** como chave."""
    return criar_engine(url)


def engine(url: str | None = None) -> Engine:
    """Engine compartilhado, um por URL (cacheado: pool de conexões só faz sentido reusado).

    A URL é resolvida **antes** de virar chave de cache, e isso não é detalhe: com
    `@lru_cache` direto na função, `engine()` cacheava sob a chave `None` e
    `engine(database_url())` sob a string — duas entradas para o **mesmo banco**, e a de
    `None` presa para sempre à primeira URL que o processo viu.

    Em produção a URL nunca muda e o defeito é invisível. Nos testes ele apareceu com
    força: `create_all(engine())` criava as tabelas no banco de um teste anterior (já
    apagado com o `tmp_path`) enquanto a API falava com o banco certo, e 18 testes
    quebravam com "no such table: users" apontando para um problema que não era o deles.
    """
    return _engine_cacheado(url or database_url())


def get_session() -> Generator[Session, None, None]:
    """Dependência do FastAPI: uma sessão por request, fechada ao fim.

    Não faz commit: quem escreve decide quando confirmar. Assim um handler que só lê
    nunca abre transação de escrita por acidente.
    """
    with Session(engine(database_url())) as sessao:
        yield sessao


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    """Sessão para scripts (seed, worker): commit no sucesso, rollback no erro.

    Diferente de :func:`get_session` de propósito — um script que morre no meio não pode
    deixar meia carga gravada.
    """
    motor = criar_engine(url)
    sessao = Session(motor)
    try:
        yield sessao
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()
        # Script termina; sem o dispose o arquivo do SQLite fica com handle aberto no
        # Windows e um `downgrade base` seguinte falha ao remover o banco.
        motor.dispose()
