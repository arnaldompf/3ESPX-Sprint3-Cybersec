"""Rotina de auditoria de permissões — `python -m seguranca.auditoria_permissoes`.

Roda todo mês (plano de segurança contínua, docs/SPRINT3 §4.7) e produz um relatório em
Markdown para o gestor revisar e assinar. O que ele levanta:

1. **a matriz de permissões vigente**, lida do código da solução (`api/app/permissions.py`):
   se alguém alterou a matriz, a diferença aparece na revisão do mês;
2. **contas por papel** e quantos administradores existem (meta: no máximo 2);
3. **contas ativas sem login há mais de N dias** (padrão 90): candidatas a desativação —
   conta parada é credencial esquecida esperando ser roubada;
4. **contas ativas que nunca fizeram login** criadas há mais de N dias;
5. **identidades de papel sem senha** (`sem-senha:auth-desligada`) que existem na base: com
   `AUTH_ENABLED=1` elas não autenticam, mas não deveriam existir em produção.

Não altera nada no banco: só lê. A decisão de desativar é humana e fica registrada no
relatório assinado.
"""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from seguranca.segredos import carregar_segredos_de_arquivo
from seguranca.solucao import preparar_importacao

MAX_ADMINS = 2


@dataclass(frozen=True)
class Conta:
    """Cópia só-leitura da linha de `users` — sem senha, sem hash."""

    email: str
    role: str
    ativo: bool
    sem_senha: bool
    criado_em: dt.datetime
    ultimo_login_em: dt.datetime | None


def gerar_relatorio(*, dias: int = 90, agora: dt.datetime | None = None) -> str:
    carregar_segredos_de_arquivo()
    preparar_importacao()
    from api.app.db import session_scope
    from api.app.models import Role, User
    from api.app.papel import SEM_SENHA
    from api.app.permissions import MATRIZ, Escopo
    from sqlmodel import select

    agora = agora or dt.datetime.now(dt.UTC).replace(tzinfo=None)
    corte = agora - dt.timedelta(days=dias)
    papeis = list(Role)
    linhas = [
        f"# Auditoria de permissões — {agora:%Y-%m-%d}",
        "",
        "## 1. Matriz de permissões vigente (lida do código)",
        "",
        "| Ação | " + " | ".join(p.value for p in papeis) + " |",
        "|---|" + "---|" * len(papeis),
    ]
    simbolo = {Escopo.TODOS: "✓", Escopo.PROPRIOS: "próprios", Escopo.NENHUM: "—"}
    for acao, escopos in MATRIZ.items():
        celulas = [simbolo[escopos.get(p, Escopo.NENHUM)] for p in papeis]
        linhas.append(f"| `{acao.value}` | " + " | ".join(celulas) + " |")

    with session_scope() as sessao:
        usuarios = [
            Conta(
                email=u.email,
                role=u.role,
                ativo=u.ativo,
                sem_senha=u.password_hash == SEM_SENHA,
                criado_em=u.criado_em,
                ultimo_login_em=u.ultimo_login_em,
            )
            for u in sessao.exec(select(User))
        ]

    ativos = [u for u in usuarios if u.ativo]
    linhas += ["", "## 2. Contas por papel", "", "| Papel | Ativas | Inativas |", "|---|---|---|"]
    for papel in papeis:
        do_papel = [u for u in usuarios if u.role == papel.value]
        linhas.append(
            f"| {papel.value} | {sum(u.ativo for u in do_papel)} | "
            f"{sum(not u.ativo for u in do_papel)} |"
        )
    admins = [u for u in ativos if u.role == Role.ADMIN.value]
    situacao = "OK" if len(admins) <= MAX_ADMINS else f"ACIMA DO LIMITE ({MAX_ADMINS})"
    linhas.append(f"\nAdministradores ativos: **{len(admins)}** — {situacao}")

    parados = [u for u in ativos if u.ultimo_login_em and u.ultimo_login_em < corte]
    nunca = [u for u in ativos if u.ultimo_login_em is None and u.criado_em < corte]
    sem_senha = [u for u in ativos if u.sem_senha]

    def tabela(titulo: str, contas: list) -> None:
        linhas.extend(["", titulo, ""])
        if not contas:
            linhas.append("Nenhuma.")
            return
        linhas.extend(["| E-mail | Papel | Último login | Decisão |", "|---|---|---|---|"])
        for u in contas:
            ultimo = f"{u.ultimo_login_em:%Y-%m-%d}" if u.ultimo_login_em else "nunca"
            linhas.append(f"| {u.email} | {u.role} | {ultimo} | ☐ manter ☐ desativar |")

    tabela(f"## 3. Contas ativas sem login há mais de {dias} dias", parados)
    tabela(f"## 4. Contas ativas que nunca logaram (criadas há mais de {dias} dias)", nunca)
    tabela("## 5. Identidades de papel sem senha (modo demonstração)", sem_senha)
    linhas += ["", "---", "Revisado por: ____________________  Data: ___/___/______", ""]
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seguranca.auditoria_permissoes")
    parser.add_argument("--dias", type=int, default=90)
    parser.add_argument("--saida", type=Path)
    args = parser.parse_args(argv)
    relatorio = gerar_relatorio(dias=args.dias)
    if args.saida:
        args.saida.write_text(relatorio, encoding="utf-8")
        print(args.saida)
    else:
        print(relatorio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
