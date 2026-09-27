"""A matriz de permissões de `docs/12` §6.6 — **por ação**, não por hierarquia.

`specs/WP-05.md` fala em `require_role(...)` "com hierarquia", e `docs/12` §6.6 diz, com
essas palavras, que a matriz **"substitui a hierarquia linear do v1"**. Segui a matriz, e
não é preferência: a matriz **não é linear**, então a hierarquia não a expressa.

    | Ação                          | vendedor | analista | gestor | admin |
    | Criar sessão de showroom      |    ✓     |    —     |   ✓    |   ✓   |
    | Criar extrações, ver alertas  |    —     |    ✓     |   ✓    |   ✓   |

O `vendedor` pode abrir sessão de showroom e o `analista` **não**. Com
`vendedor < analista < gestor < admin`, qualquer regra que libere o vendedor libera o
analista — e o analista passaria a poder registrar venda. Papel não é nível de acesso;
é função. Por isso a autorização pergunta *"este papel pode esta ação?"*, e nunca
*"este papel é alto o bastante?"*.

`ver_insights` é o caso interessante: o vendedor vê **só os próprios**. Isso não é um
booleano, então a matriz guarda o escopo (`PROPRIOS`) e quem consulta decide o filtro —
tratar "só os meus" como "pode ver" vazaria a sessão de um vendedor para o outro.
"""

from __future__ import annotations

from enum import StrEnum

from api.app.models import Role


class Acao(StrEnum):
    """As ações que a matriz de `docs/12` §6.6 nomeia. Uma linha da tabela cada."""

    CONSULTAR_FICHAS = "consultar_fichas"
    CRIAR_SESSAO_SHOWROOM = "criar_sessao_showroom"
    CRIAR_EXTRACOES = "criar_extracoes"
    VER_ALERTAS = "ver_alertas"
    VER_EVIDENCIAS_BRUTAS = "ver_evidencias_brutas"
    VER_INSIGHTS = "ver_insights"
    APROVAR_ARGUMENTOS = "aprovar_argumentos"
    GERIR_REFERENCIA_INTERNA = "gerir_referencia_interna"
    GERIR_EQUIVALENCIAS = "gerir_equivalencias"
    PUBLICAR = "publicar"
    GERIR_USUARIOS = "gerir_usuarios"
    GERIR_FONTES = "gerir_fontes"


class Escopo(StrEnum):
    """Quanto de uma ação o papel alcança."""

    NENHUM = "nenhum"
    PROPRIOS = "proprios"
    """Só os registros criados pelo próprio usuário (o vendedor em `ver_insights`)."""
    TODOS = "todos"


#: A matriz, transcrita de `docs/12` §6.6. Ação → papel → escopo.
#: Papel ausente numa ação significa `NENHUM`: negar por omissão é o único default seguro.
MATRIZ: dict[Acao, dict[Role, Escopo]] = {
    Acao.CONSULTAR_FICHAS: {
        Role.VENDEDOR: Escopo.TODOS,
        Role.ANALISTA: Escopo.TODOS,
        Role.GESTOR: Escopo.TODOS,
        Role.ADMIN: Escopo.TODOS,
    },
    Acao.CRIAR_SESSAO_SHOWROOM: {
        Role.VENDEDOR: Escopo.TODOS,
        Role.GESTOR: Escopo.TODOS,
        Role.ADMIN: Escopo.TODOS,
    },
    Acao.CRIAR_EXTRACOES: {
        Role.ANALISTA: Escopo.TODOS,
        Role.GESTOR: Escopo.TODOS,
        Role.ADMIN: Escopo.TODOS,
    },
    Acao.VER_ALERTAS: {
        Role.ANALISTA: Escopo.TODOS,
        Role.GESTOR: Escopo.TODOS,
        Role.ADMIN: Escopo.TODOS,
    },
    Acao.VER_EVIDENCIAS_BRUTAS: {
        Role.ANALISTA: Escopo.TODOS,
        Role.GESTOR: Escopo.TODOS,
        Role.ADMIN: Escopo.TODOS,
    },
    Acao.VER_INSIGHTS: {
        Role.VENDEDOR: Escopo.PROPRIOS,
        Role.ANALISTA: Escopo.TODOS,
        Role.GESTOR: Escopo.TODOS,
        Role.ADMIN: Escopo.TODOS,
    },
    Acao.APROVAR_ARGUMENTOS: {Role.GESTOR: Escopo.TODOS, Role.ADMIN: Escopo.TODOS},
    Acao.GERIR_REFERENCIA_INTERNA: {Role.GESTOR: Escopo.TODOS, Role.ADMIN: Escopo.TODOS},
    Acao.GERIR_EQUIVALENCIAS: {Role.GESTOR: Escopo.TODOS, Role.ADMIN: Escopo.TODOS},
    Acao.PUBLICAR: {Role.GESTOR: Escopo.TODOS, Role.ADMIN: Escopo.TODOS},
    Acao.GERIR_USUARIOS: {Role.ADMIN: Escopo.TODOS},
    Acao.GERIR_FONTES: {Role.ADMIN: Escopo.TODOS},
}


def escopo_de(papel: str | Role, acao: Acao) -> Escopo:
    """O alcance deste papel nesta ação. Papel desconhecido → `NENHUM`.

    Papel desconhecido virando `NENHUM` é a política: um papel novo no banco (migração
    pela metade, alteração à mão) não pode ganhar acesso por acidente.
    """
    try:
        role = Role(str(papel))
    except ValueError:
        return Escopo.NENHUM
    return MATRIZ.get(acao, {}).get(role, Escopo.NENHUM)


def pode(papel: str | Role, acao: Acao) -> bool:
    """Este papel alcança esta ação de alguma forma?

    Cuidado ao usar em rota de listagem: `PROPRIOS` também devolve `True` aqui, e quem
    lista tem de aplicar o filtro. Para saber *quanto*, use `escopo_de`.
    """
    return escopo_de(papel, acao) is not Escopo.NENHUM


def papeis_com(acao: Acao) -> tuple[Role, ...]:
    """Quem alcança a ação — útil em mensagem de erro e na documentação da rota."""
    return tuple(
        papel for papel, escopo in MATRIZ.get(acao, {}).items() if escopo is not Escopo.NENHUM
    )
