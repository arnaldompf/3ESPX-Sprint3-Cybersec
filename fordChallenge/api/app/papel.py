"""Quem está olhando, quando não há login — o papel vem do cabeçalho `X-Role` (D-204).

Nesta fase do projeto a API não autentica ninguém (`AUTH_ENABLED=false`, o padrão). O
papel deixou de ser uma credencial e passou a ser **um recorte de leitura**: a tela guarda
o papel escolhido no navegador e o manda em `X-Role`; a API o usa para filtrar o que é por
papel — o vendedor vê as sessões de showroom que ele registrou, não as do colega — e para
carimbar quem registrou o quê.

O que este módulo **não** faz, e é deliberado:

* **não nega nada.** Papel desconhecido, ausente ou escrito errado não vira 403: vira o
  papel padrão. Negar aqui seria autenticação com outro nome, e a decisão do que mostrar é
  da tela (`web/src/lib/permissoes.ts`), que tem a mesma matriz de `docs/12` §6.6;
* **não confia no cabeçalho para nada que precise de confiança.** Ele é auto-declarado —
  qualquer cliente escreve o que quiser. É aceitável exatamente porque, sem autenticação,
  não há nada a proteger: a mesma base, as mesmas rotas, o mesmo dado. Quando
  `AUTH_ENABLED=1` o papel volta a sair do token assinado e este módulo sai do caminho.

A identidade de cada papel é **uma linha em `users`**, e não um objeto solto em memória,
porque `showroom_sessions.vendedor_id` é chave estrangeira: sem linha no banco, registrar
uma venda gravaria um id que não existe. A linha nasce sem senha utilizável — não há login
para fazer com ela.
"""

from __future__ import annotations

from fastapi import Request
from sqlmodel import Session, select

from api.app.config import get_settings
from api.app.db import session_scope
from api.app.models import Role, User

#: O cabeçalho que a tela manda em toda chamada. Não é padrão de nenhuma RFC; é contrato
#: deste projeto, e está em `docs/04`.
CABECALHO_PAPEL = "X-Role"

#: Domínio das quatro identidades de papel. É o mesmo que a base de demonstração já usava,
#: de propósito: uma base montada antes desta mudança reaproveita as linhas que tem, em vez
#: de ganhar quatro usuários duplicados.
DOMINIO_DOS_PAPEIS = "specradar.example.com"

#: O que fica em `password_hash` das identidades de papel. Não é um hash e não pode virar
#: um: `senha_confere` recusa qualquer coisa que não seja argon2, então nenhuma senha entra
#: por aqui nem por acidente. Existe porque a coluna é obrigatória.
SEM_SENHA = "sem-senha:auth-desligada"

#: Nome exibido de cada papel, para `/auth/me` ter o que mostrar na barra lateral.
NOME_DO_PAPEL: dict[str, str] = {
    Role.VENDEDOR.value: "Vendedor",
    Role.ANALISTA.value: "Analista",
    Role.GESTOR.value: "Gestor",
    Role.ADMIN.value: "Admin",
}


def papel_padrao() -> str:
    """O papel de quem não manda cabeçalho. Valor inválido no `.env` cai em `admin`."""
    bruto = (get_settings().papel_padrao or "").strip().lower()
    try:
        return Role(bruto).value
    except ValueError:
        return Role.ADMIN.value


def papel_do_pedido(request: Request) -> str:
    """O papel declarado em `X-Role`, canonizado. Desconhecido vira o padrão.

    >>> # X-Role: Gestor  ->  "gestor"
    >>> # X-Role: sindico  ->  papel_padrao()
    """
    bruto = (request.headers.get(CABECALHO_PAPEL) or "").strip().lower()
    if not bruto:
        return papel_padrao()
    try:
        return Role(bruto).value
    except ValueError:
        return papel_padrao()


def email_do_papel(papel: str) -> str:
    """O endereço convencional da identidade daquele papel.

    O `admin` respeita `ADMIN_EMAIL` quando ele existe, para não criar um segundo
    administrador ao lado do que o `seed` já criou numa base antiga.
    """
    if papel == Role.ADMIN.value:
        do_env = (get_settings().admin_email or "").strip()
        if do_env:
            return do_env
    return f"{papel}@{DOMINIO_DOS_PAPEIS}"


def _procurar(sessao: Session, papel: str) -> User | None:
    """A identidade do papel: primeiro pelo e-mail convencional, depois por papel.

    A ordem importa. Numa base com mais de um usuário do mesmo papel, "o primeiro que
    aparecer" daria uma identidade que muda conforme a ordem de inserção — e a taxa de
    fechamento por vendedor deixaria de significar algo.
    """
    achado = sessao.exec(select(User).where(User.email == email_do_papel(papel))).first()
    if achado is not None and achado.ativo:
        return achado
    return sessao.exec(
        select(User).where(User.role == papel, User.ativo == True)  # noqa: E712 - SQL
    ).first()


def _criar(papel: str) -> None:
    """Cria a identidade do papel numa transação **própria**.

    Fora da sessão do request de propósito: `get_session` não faz commit (quem escreve
    decide quando), então criar ali deixaria a linha sem gravar num GET — e a identidade
    seria recriada e descartada a cada leitura. Numa transação própria ela nasce uma vez
    e a chave estrangeira de `showroom_sessions` passa a ter a quem apontar.
    """
    with session_scope() as propria:
        if _procurar(propria, papel) is not None:
            return
        propria.add(
            User(
                email=email_do_papel(papel),
                nome=NOME_DO_PAPEL.get(papel, papel.capitalize()),
                password_hash=SEM_SENHA,
                role=papel,
            )
        )


def usuario_do_papel(sessao: Session, papel: str) -> User:
    """A linha de `users` daquele papel, criando-a na primeira vez.

    Idempotente e barata: depois da primeira chamada de cada papel é uma leitura por
    índice único.
    """
    achado = _procurar(sessao, papel)
    if achado is not None:
        return achado
    _criar(papel)
    sessao.expire_all()
    achado = _procurar(sessao, papel)
    if achado is not None:
        return achado
    # Corrida perdida com outro processo, ou banco somente-leitura. Devolver um objeto
    # solto é melhor que derrubar a requisição: a leitura funciona, e a escrita que
    # dependeria do id falha com a mensagem do banco, não com um 500 daqui.
    return User(
        email=email_do_papel(papel),
        nome=NOME_DO_PAPEL.get(papel, papel.capitalize()),
        password_hash=SEM_SENHA,
        role=papel,
    )


def garantir_identidades(sessao: Session) -> list[str]:
    """Cria as quatro identidades de papel que faltarem. Devolve os papéis criados.

    Chamada pelo `seed` e pelo preparador da base: com as quatro já no banco, nenhuma
    requisição precisa criar nada, e o caminho de leitura fica sendo só leitura.
    """
    criados: list[str] = []
    for papel in (Role.VENDEDOR, Role.ANALISTA, Role.GESTOR, Role.ADMIN):
        if _procurar(sessao, papel.value) is not None:
            continue
        sessao.add(
            User(
                email=email_do_papel(papel.value),
                nome=NOME_DO_PAPEL[papel.value],
                password_hash=SEM_SENHA,
                role=papel.value,
            )
        )
        criados.append(papel.value)
    if criados:
        sessao.flush()
    return criados
