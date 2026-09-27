"""Rotina de auditoria de permissões: matriz vigente, admins e contas paradas."""

from __future__ import annotations

import datetime as dt

from api.app.db import engine, session_scope
from api.app.models import User
from sqlmodel import SQLModel

from seguranca.auditoria_permissoes import gerar_relatorio

AGORA = dt.datetime(2026, 10, 1)


def _conta(email: str, role: str, ultimo_login: dt.datetime | None, ativo: bool = True) -> User:
    return User(
        email=email,
        nome=email.split("@")[0],
        password_hash="argon2-de-mentira",
        role=role,
        ativo=ativo,
        criado_em=dt.datetime(2026, 1, 1),
        ultimo_login_em=ultimo_login,
    )


def test_relatorio_aponta_contas_paradas_e_excesso_de_admins():
    SQLModel.metadata.drop_all(engine())
    SQLModel.metadata.create_all(engine())
    with session_scope() as sessao:
        sessao.add_all(
            [
                _conta("a1@x.com", "admin", AGORA - dt.timedelta(days=1)),
                _conta("a2@x.com", "admin", AGORA - dt.timedelta(days=2)),
                _conta("a3@x.com", "admin", AGORA - dt.timedelta(days=3)),
                _conta("parado@x.com", "analista", AGORA - dt.timedelta(days=120)),
                _conta("nunca@x.com", "vendedor", None),
                _conta("desligado@x.com", "gestor", AGORA - dt.timedelta(days=200), ativo=False),
            ]
        )

    relatorio = gerar_relatorio(dias=90, agora=AGORA)

    assert "| `gerir_usuarios` | — | — | — | ✓ |" in relatorio  # matriz lida do código
    assert "Administradores ativos: **3** — ACIMA DO LIMITE (2)" in relatorio
    assert "| parado@x.com | analista | 2026-06-03 |" in relatorio
    assert "| nunca@x.com | vendedor | nunca |" in relatorio
    assert "desligado@x.com" not in relatorio  # conta inativa já está resolvida
    assert "argon2" not in relatorio  # o relatório nunca carrega hash
