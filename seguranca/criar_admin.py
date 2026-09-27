"""Cria o primeiro administrador — `python -m seguranca.criar_admin --email <e-mail>`.

A senha **não** vem por argumento (apareceria no histórico do shell e no `ps`): vem de
`ADMIN_PASSWORD` ou `ADMIN_PASSWORD_FILE` (Docker secret gerado por `infra/gerar_segredos.sh`).
Idempotente: se o e-mail já existe, não faz nada. Grava a criação no `audit_log`.
"""

from __future__ import annotations

import argparse
import os
import sys

from seguranca.segredos import carregar_segredos_de_arquivo
from seguranca.solucao import preparar_importacao


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seguranca.criar_admin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--nome", default="Administrador")
    args = parser.parse_args(argv)

    carregar_segredos_de_arquivo()
    senha = os.environ.get("ADMIN_PASSWORD", "")
    if len(senha) < 12:
        print("erro: defina ADMIN_PASSWORD(_FILE) com pelo menos 12 caracteres", file=sys.stderr)
        return 1

    preparar_importacao()
    from api.app.db import session_scope
    from api.app.models import AuditLog, Role, User
    from api.app.security import hash_de_senha
    from sqlmodel import select

    with session_scope() as sessao:
        if sessao.exec(select(User).where(User.email == args.email)).first():
            print(f"{args.email} já existe; nada a fazer")
            return 0
        usuario = User(
            email=args.email,
            nome=args.nome,
            password_hash=hash_de_senha(senha),
            role=Role.ADMIN.value,
        )
        sessao.add(usuario)
        sessao.flush()
        sessao.add(
            AuditLog(
                user_id=usuario.id,
                ator_email="criar_admin (linha de comando)",
                acao="usuario_criado",
                alvo_tipo="user",
                alvo_id=usuario.id,
                detalhe={"role": Role.ADMIN.value},
            )
        )
    print(f"administrador {args.email} criado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
