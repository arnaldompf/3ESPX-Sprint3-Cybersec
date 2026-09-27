"""Prazo monotônico compartilhado por coleta, parser, busca e modelo."""

import time
from contextlib import contextmanager
from contextvars import ContextVar

_expires = ContextVar("research_deadline", default=None)


def remaining() -> float | None:
    end = _expires.get()
    return None if end is None else max(0.0, end - time.monotonic())


def timeout(default: float) -> float:
    left = remaining()
    if left is not None and left <= 0:
        raise TimeoutError("orçamento total de pesquisa esgotado")
    return default if left is None else min(default, left)


def sleep(seconds: float) -> None:
    left = remaining()
    if left is not None and seconds >= left:
        raise TimeoutError("espera excederia o orçamento total da pesquisa")
    time.sleep(seconds)


@contextmanager
def budget(seconds: float):
    old = remaining()
    token = _expires.set(
        time.monotonic() + min(seconds, old) if old is not None else time.monotonic() + seconds
    )
    try:
        yield
    finally:
        _expires.reset(token)


@contextmanager
def locked(lock):
    """Esperar outro job também consome o prazo; sempre libera o trinco adquirido."""
    left = remaining()
    acquired = lock.acquire() if left is None else lock.acquire(timeout=left)
    if not acquired:
        raise TimeoutError("prazo esgotado aguardando o provedor")
    try:
        yield
    finally:
        lock.release()
