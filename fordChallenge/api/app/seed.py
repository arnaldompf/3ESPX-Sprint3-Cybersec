"""Seed do banco: catálogo das quatro marcas, ontologia e as identidades de papel.

Chamado por `specradar seed` (`pipeline/cli.py`). **Idempotente por consulta**, não por
`ON CONFLICT`: cada linha é procurada antes de ser inserida. Custa uma query a mais e
roda igual no Postgres e no SQLite, que é o que importa aqui.

De onde vem cada coisa, e por quê:

* **catálogo** — de `gabarito/gabarito_v1.json`. Repetir os nomes exatos, o `ano_modelo`
  e o `codigo_fipe` neste arquivo criaria uma segunda cópia da verdade-terra, que
  divergiria da primeira no dia em que o gabarito fosse corrigido. O gabarito é a fonte;
  o seed só copia.
* **sinônimos** — de `pipeline.ontology.carregar()`, os de **campo** e os de **valor**.
  Carregar direto o JSON aqui repetiria a normalização de termos que a ontologia já faz.
* **papéis** — as quatro identidades (`vendedor`, `analista`, `gestor`, `admin`), sem
  senha. Com `AUTH_ENABLED=false` (D-204) elas não são credenciais: são a linha de
  `users` a que a sessão de showroom aponta e o nome que a barra lateral mostra.
* **admin com senha** — de `ADMIN_EMAIL`/`ADMIN_PASSWORD` do ambiente, com hash argon2, e
  **só** se as duas existirem. Serve a quem ligar `AUTH_ENABLED=1`; sem login, senha não é
  usada por ninguém. Senha embutida em código continua proibida, e um default do tipo
  "admin/admin" continua sendo pior do que não ter admin.

Duas ausências deliberadas: o seed **não** insere `spec_values` (valor sem evidência é
proibido; quem preenche a ficha é o pipeline) e **não** cria sessões de showroom
simuladas (`--simulated-sessions` é da WP-27).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from sqlmodel import Session, select

from api.app.db import database_url, session_scope
from api.app.models import Role, Synonym, SynonymType, User
from api.app.papel import SEM_SENHA, garantir_identidades
from api.app.repositories import brands, versions
from pipeline.version_names import nome_canonico_de_versao

RAIZ = Path(__file__).resolve().parents[2]
GABARITO = RAIZ / "gabarito" / "gabarito_v1.json"


def _data_de_referencia(texto: str | None) -> dt.datetime | None:
    """`"2026-09-02"` -> datetime UTC. Data ilegível vira `None`, nunca "hoje".

    Preencher `lineup_checked_at` com a hora do seed seria afirmar que a linha vigente foi
    conferida agora — não foi; foi conferida na data que o gabarito registra.
    """
    if not texto:
        return None
    try:
        return dt.datetime.fromisoformat(texto).replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def _semear_catalogo(sessao: Session) -> dict[str, int]:
    """Marcas, modelos e versões a partir do gabarito.

    O nome da versão entra **canônico** (`pipeline.version_names`), e não como está escrito
    no gabarito. O gabarito descreve a mesma S10 de dois jeitos — `"High Country"` na
    versão-alvo e `"S10 High Country"` na linha vigente —, e copiar os dois literalmente
    criava duas linhas em `versions` para um carro só: a com ficha e uma vazia que os
    seletores ofereciam primeiro, por ordem alfabética. O gabarito continua sendo a fonte e
    não é reescrito; quem normaliza é o catálogo, que é onde o nome vira rótulo de tela.
    """
    if not GABARITO.exists():
        raise FileNotFoundError(
            f"{GABARITO} não existe; o seed do catálogo lê os nomes exatos de lá "
            "(veja gabarito/README.md)"
        )
    dados: dict[str, Any] = json.loads(GABARITO.read_text(encoding="utf-8"))
    conferido_em = _data_de_referencia(dados.get("gerado_em"))

    marcas: set[str] = set()
    modelos: set[tuple[str, str]] = set()
    # Conjuntos, não contadores: o mesmo modelo (Hilux) e a mesma versão aparecem em mais
    # de um veículo do gabarito, e um contador de chamadas relataria mais linhas do que o
    # banco tem — número inflado é número errado, mesmo em log de seed.
    versoes: set[str] = set()
    for veiculo in dados.get("veiculos", []):
        marca = brands.upsert(sessao, nome=veiculo["marca"])
        modelo = brands.upsert_modelo(sessao, brand_id=marca.id, nome=veiculo["modelo"])
        marcas.add(marca.nome)
        modelos.add((marca.nome, modelo.nome))

        # A versão-alvo do gabarito entra com o código FIPE. O caso negativo
        # (`resultado_esperado.status == versao_inexistente`) fica de fora de propósito:
        # gravá-la como versão faria o resolvedor do WP-07 encontrar no banco justamente
        # a versão que ele tem de reportar como fora de linha.
        if not veiculo.get("resultado_esperado"):
            alvo = versions.upsert(
                sessao,
                model_id=modelo.id,
                nome_exato=nome_canonico_de_versao(modelo.nome, veiculo["versao"]),
                ano_modelo=int(veiculo["ano_modelo"]),
                codigo_fipe=veiculo.get("codigo_fipe"),
                in_lineup=True,
                lineup_checked_at=conferido_em,
            )
            versoes.add(alvo.id)

        for item in veiculo.get("linha_vigente", []):
            em_linha = versions.upsert(
                sessao,
                model_id=modelo.id,
                nome_exato=nome_canonico_de_versao(modelo.nome, item["nome_exato"]),
                ano_modelo=int(item.get("ano_modelo") or veiculo["ano_modelo"]),
                in_lineup=True,
                lineup_checked_at=conferido_em,
            )
            versoes.add(em_linha.id)

    return {"marcas": len(marcas), "modelos": len(modelos), "versoes": len(versoes)}


def _semear_sinonimos(sessao: Session) -> dict[str, int]:
    """Sinônimos de campo e de valor da semente do WP-01."""
    from pipeline.ontology import carregar

    onto = carregar()
    existentes = {
        (s.termo, s.campo_canonico, s.tipo, s.marca) for s in sessao.exec(select(Synonym))
    }
    novos: list[Synonym] = []

    def registrar(sinonimo: Synonym) -> None:
        chave = (
            sinonimo.termo,
            sinonimo.campo_canonico,
            sinonimo.tipo,
            sinonimo.marca,
        )
        if chave in existentes:
            return
        existentes.add(chave)
        novos.append(sinonimo)

    de_campo = 0
    for entrada in onto.campos:
        for termo in entrada.termos:
            registrar(
                Synonym(
                    termo=termo,
                    campo_canonico=entrada.campo_canonico,
                    marca=entrada.marca,
                    tipo=SynonymType.CAMPO.value,
                )
            )
            de_campo += 1

    de_valor = 0
    for campo, mapa in onto.valores.items():
        for termo, canonico in mapa.items():
            registrar(
                Synonym(
                    termo=termo,
                    campo_canonico=campo,
                    valor_canonico=canonico,
                    tipo=SynonymType.VALOR.value,
                )
            )
            de_valor += 1

    for sinonimo in novos:
        sessao.add(sinonimo)
    sessao.flush()
    return {"campo": de_campo, "valor": de_valor, "inseridos": len(novos)}


def _semear_papeis(sessao: Session) -> str:
    """Cria as quatro identidades de papel. Devolve a linha de log.

    Com `AUTH_ENABLED=false` (D-204) elas não são credenciais: são a linha de `users` a
    que `showroom_sessions.vendedor_id` aponta e o nome que a barra lateral mostra.
    Nascem sem senha utilizável, e é isso que as torna inofensivas — não há login a fazer
    com elas. Criá-las aqui é o que mantém o caminho de leitura da API sendo só leitura.
    """
    criados = garantir_identidades(sessao)
    if not criados:
        return "papeis: os quatro ja existiam"
    return f"papeis: criado(s) {', '.join(criados)} (sem senha; a entrada nao pede login)"


def _semear_admin(sessao: Session) -> str:
    """Cria o admin **com senha** a partir do ambiente, quando alguém pede um.

    Só faz sentido com `AUTH_ENABLED=1`: sem login, senha não é usada por ninguém. Sem as
    duas variáveis o usuário não é criado e o seed diz isso — e isso deixou de ser um
    aviso, porque a identidade `admin` já vem de `_semear_papeis`.
    """
    email = (os.environ.get("ADMIN_EMAIL") or "").strip()
    senha = os.environ.get("ADMIN_PASSWORD") or ""
    if not email or not senha:
        return "admin com senha: nao criado (nao e necessario com AUTH_ENABLED=false)"

    existente = sessao.exec(select(User).where(User.email == email)).first()
    if existente is not None and existente.password_hash != SEM_SENHA:
        # Não re-hasheia: o hash argon2 muda a cada chamada (salt novo) e reescrevê-lo a
        # cada seed poluiria a auditoria sem nenhum ganho.
        return f"admin: ja existia ({email})"

    if existente is not None:
        # **A identidade de papel, promovida a administrador de verdade.**
        #
        # `_semear_papeis` roda antes e cria as quatro identidades sem senha utilizável.
        # `email_do_papel("admin")` devolve `ADMIN_EMAIL` quando ele existe — de propósito,
        # para não haver dois administradores —, então numa máquina com `ADMIN_EMAIL` e
        # `ADMIN_PASSWORD` definidos o admin já estava lá, **com `SEM_SENHA`**, e este
        # bloco dizia "já existia" e ia embora.
        #
        # O resultado era o pior tipo de falha: com `AUTH_ENABLED=1`, o login do
        # administrador nunca funcionaria, e o `seed` teria dito que deu tudo certo. O
        # teste que pega isso é `@pytest.mark.slow`, fora do `verify-quick` — foi por isso
        # que durou (medido em 13/09/2026).
        existente.password_hash = PasswordHasher().hash(senha)
        existente.role = Role.ADMIN.value
        sessao.add(existente)
        return f"admin: identidade de papel promovida a admin com senha ({email})"

    sessao.add(
        User(
            email=email,
            nome=os.environ.get("ADMIN_NOME") or "Administrador",
            password_hash=PasswordHasher().hash(senha),
            role=Role.ADMIN.value,
            ativo=True,
        )
    )
    sessao.flush()
    return f"admin: criado ({email})"


#: Um par da semente: (concorrente, contraparte Ford ou `None`, critério). Cada trio de
#: texto é (marca, modelo, nome exato) — o mesmo trio que o resolvedor casa.
ParDeEquivalencia = tuple[tuple[str, str, str], tuple[str, str, str] | None, str]

#: A semente de `equivalents`, **literal de `docs/12` §6.1**.
#:
#: Cada par é (concorrente, contraparte Ford, critério). A contraparte é procurada por
#: **nome exato** no catálogo; par cuja contraparte não existe fica pendente e o seed diz
#: qual e por quê — criar uma linha em `versions` para uma Ranger diesel que o gabarito
#: não descreve inventaria o nome de uma versão, e o resolvedor (WP-07) passaria a
#: encontrar no banco uma versão sem nenhuma evidência atrás.
#:
#: `None` na contraparte é **afirmação**, não lacuna: a Raptor não tem par entre as
#: picapes diesel de trabalho, e a tabela precisa poder dizer isso — é o que faz o impacto
#: exibir "sem equivalente" em vez de gap zero.
SEMENTE_DE_EQUIVALENCIA: tuple[ParDeEquivalencia, ...] = (
    (
        ("Toyota", "Hilux", "SRX Plus AT"),
        ("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT"),
        "picape diesel de topo, mesma faixa de preco e uso",
    ),
    (
        ("Chevrolet", "S10", "High Country"),
        ("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT"),
        "picape diesel de topo, mesma faixa de preco e uso",
    ),
    (
        ("Volkswagen", "Amarok", "V6 Extreme"),
        ("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT"),
        "V6 diesel contra V6 diesel",
    ),
    (
        ("Ford", "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT"),
        None,
        "sem par direto: picape de desempenho a gasolina, fora da comparacao de trabalho",
    ),
)


def _versao_por_nome(sessao: Session, marca: str, modelo: str, nome: str) -> str | None:
    """O `versions.id` pelo trio exato, ou `None`. Sem fuzzy: ver `pipeline/persist.py`."""
    from api.app.models import Brand, VehicleModel, Version

    linha = sessao.exec(
        select(Version)
        .join(VehicleModel, VehicleModel.id == Version.model_id)
        .join(Brand, Brand.id == VehicleModel.brand_id)
        .where(Brand.nome == marca, VehicleModel.nome == modelo, Version.nome_exato == nome)
    ).first()
    return linha.id if linha is not None else None


def _semear_equivalencias(sessao: Session) -> dict[str, Any]:
    """Cadastra os pares de `docs/12` §6.1 que o catálogo consegue expressar.

    O que **não** acontece aqui: nenhum par é inventado para o gap ter um número. Sem a
    contraparte Ford no catálogo, o impacto do alerta sai com `motivo_sem_gap` e a tela
    mostra o motivo — que é honesto, e é o comportamento testado.
    """
    from api.app.models import Equivalent

    inseridos = 0
    pendentes: list[str] = []
    for concorrente, ford, nota in SEMENTE_DE_EQUIVALENCIA:
        id_concorrente = _versao_por_nome(sessao, *concorrente)
        if id_concorrente is None:
            pendentes.append(f"{' '.join(concorrente)}: versao do concorrente nao esta no catalogo")
            continue

        id_ford: str | None = None
        if ford is not None:
            id_ford = _versao_por_nome(sessao, *ford)
            if id_ford is None:
                # Pendente, nao silencioso: o gestor cadastra por `POST /equivalents`
                # quando a versao entrar no catalogo, e o seed volta a preencher sozinho.
                pendentes.append(
                    f"{' '.join(concorrente)} <-> {' '.join(ford)}: "
                    "a contraparte Ford nao esta no catalogo do gabarito"
                )
                continue

        existente = sessao.exec(
            select(Equivalent).where(Equivalent.competitor_version_id == id_concorrente)
        ).first()
        if existente is not None:
            continue

        sessao.add(
            Equivalent(
                competitor_version_id=id_concorrente,
                ford_version_id=id_ford,
                nota=nota,
            )
        )
        inseridos += 1

    sessao.flush()
    return {"inseridos": inseridos, "pendentes": pendentes}


#: A referência interna da demo: o deck comercial da Raptor, no formato que o gestor sobe.
#:
#: Fica ao lado do próprio slide (`tests/fixtures/slide/`) e não em `gabarito/` porque é a
#: **transcrição linha a linha** daquele arquivo, não verdade-terra: o gabarito diz o que a
#: Ford publica; este CSV diz o que o deck do time comercial afirma. Confundir os dois
#: colocaria o erro do slide dentro da referência de acerto do eval.
CSV_DA_REFERENCIA_INTERNA = RAIZ / "tests" / "fixtures" / "slide" / "ford_ranger_raptor_2026.csv"


def _semear_referencia_interna(sessao: Session) -> dict[str, Any]:
    """Planta as linhas de `internal_references` do deck da Raptor (`docs/12` §6.1).

    **Não gera alerta aqui**, e a razão é a ordem dos fatos: no fim do seed não existe
    nenhuma ficha pública (o seed não grava `spec_values`), então "divergência" não teria
    contra o que ser medida. Quem compara é `specradar refresh`, depois da extração — e é
    lá que o alerta nasce com as duas evidências.
    """
    from api.app.models import InternalReference
    from pipeline.radar import internal

    if not CSV_DA_REFERENCIA_INTERNA.exists():
        return {"linhas": 0, "recusadas": ["arquivo do deck nao encontrado"]}

    texto = CSV_DA_REFERENCIA_INTERNA.read_text(encoding="utf-8")
    resultado = internal.importar(texto)
    documento = CSV_DA_REFERENCIA_INTERNA.name

    gravadas = 0
    recusadas = list(resultado.recusadas)
    for linha in resultado.linhas:
        version_id = _versao_por_nome(sessao, "Ford", "Ranger", linha.versao)
        if version_id is None:
            recusadas.append(f"versao {linha.versao!r} nao esta no catalogo")
            continue
        existente = sessao.exec(
            select(InternalReference).where(
                InternalReference.version_id == version_id,
                InternalReference.field == linha.campo,
            )
        ).first()
        if existente is not None:
            continue
        sessao.add(
            InternalReference(
                version_id=version_id,
                field=linha.campo,
                value_json=linha.valor,
                raw_value=linha.raw_value[:300],
                documento=documento,
            )
        )
        gravadas += 1

    sessao.flush()
    return {"linhas": gravadas, "recusadas": recusadas}


#: A distribuição das sessões de demonstração. **Declarada aqui, não "descoberta".**
#:
#: `docs/12` §6.5 exige que a distribuição esteja no script, e a razão é direta: um painel
#: de win/loss numa demo mostra percentuais, e percentual sobre dado inventado tem de ser
#: rastreável até a linha que o inventou. Estes números **não** são medição de mercado —
#: são um cenário plausível para a tela ter o que desenhar, e toda linha gerada sai com
#: `is_simulated=true` e o rótulo SIMULAÇÃO.
DISTRIBUICAO_DE_SESSOES = {
    "desfecho": {"fechou": 0.45, "perdeu": 0.40, "em_andamento": 0.15},
    # Os motivos de perda, com peso. Preço na frente porque é o que a spec usa como
    # exemplo em §6.5, não porque alguém mediu.
    "motivos": {
        "preco": 0.30,
        "consumo": 0.20,
        "capacidade": 0.15,
        "prazo_entrega": 0.10,
        "financiamento": 0.10,
        "marca_confianca": 0.08,
        "outro": 0.07,
    },
    "atributo_decisivo": {
        "preco_sugerido_brl": 0.30,
        "consumo_urbano_kml": 0.25,
        "capacidade_carga_kg": 0.20,
        "potencia_cv": 0.15,
        "garantia_meses": 0.10,
    },
    "uso": {"rural_carga": 0.40, "familia": 0.25, "frota": 0.20, "off_road": 0.10, "cidade": 0.05},
}

#: Semente do gerador. **Fixa**: a demo tem de mostrar o mesmo painel duas vezes seguidas,
#: e um número que muda a cada `seed` faria alguém acreditar que o dado é vivo.
SEMENTE_ALEATORIA = 42


def _sorteio(rng: Any, pesos: dict[str, float]) -> str:
    chaves = list(pesos)
    return rng.choices(chaves, weights=[pesos[k] for k in chaves], k=1)[0]


def semear_sessoes_simuladas(quantidade: int) -> int:
    """Cria sessões de showroom **simuladas**, com a distribuição de cima.

    Todas com `is_simulated=True`. O painel de insights as separa das reais e as rotula
    SIMULAÇÃO (`api/app/services/winloss.py`) — nunca há média das duas populações.
    """
    import datetime as dt
    import random

    from sqlmodel import select

    from api.app.models import Brand, ShowroomSession, VehicleModel, Version

    # `random` e nao `secrets`: o ponto aqui e ser REPRODUTIVEL, o contrario do que um
    # gerador criptografico oferece. Nada nesta funcao protege nada — ela pinta um cenario
    # de demonstracao, e a demo tem de mostrar o mesmo painel duas vezes seguidas.
    rng = random.Random(SEMENTE_ALEATORIA)  # noqa: S311
    criadas = 0
    agora = dt.datetime.now(dt.UTC).replace(tzinfo=None)

    with session_scope() as sessao:
        fords = sessao.exec(
            select(Version)
            .join(VehicleModel, VehicleModel.id == Version.model_id)
            .join(Brand, Brand.id == VehicleModel.brand_id)
            .where(Brand.nome == "Ford")
        ).all()
        outros = sessao.exec(
            select(Version)
            .join(VehicleModel, VehicleModel.id == Version.model_id)
            .join(Brand, Brand.id == VehicleModel.brand_id)
            .where(Brand.nome != "Ford")
        ).all()
        if not fords or not outros:
            print("seed: sem catalogo para semear sessoes; rode `specradar seed` antes")
            return 0

        # Concorrentes COM FICHA primeiro. Espalhar 60 sessoes pelas 19 versoes do catalogo
        # daria n de 6 a 10 por concorrente, e a regra do n >= 20 (docs/12 §6.5) esconderia
        # todo percentual no painel por concorrente — a demo mostraria a regra funcionando e
        # nao a tela. Concentrar nas versoes que temos ficha tambem e mais realista: o
        # vendedor compara contra o que o sistema conhece.
        from api.app.models import SpecValue

        com_ficha = set(sessao.exec(select(SpecValue.version_id).distinct()).all())
        candidatos = [v for v in outros if v.id in com_ficha] or list(outros)

        for indice in range(quantidade):
            ford = fords[indice % len(fords)]
            concorrente = candidatos[rng.randrange(len(candidatos))]
            desfecho = _sorteio(rng, DISTRIBUICAO_DE_SESSOES["desfecho"])
            motivos = (
                [_sorteio(rng, DISTRIBUICAO_DE_SESSOES["motivos"])] if desfecho == "perdeu" else []
            )
            sessao.add(
                ShowroomSession(
                    dealer_id=f"demo-{(indice % 3) + 1}",
                    vendedor_id=None,
                    ford_version_id=ford.id,
                    competitor_version_ids=[concorrente.id],
                    needs_profile_json={
                        "uso": [_sorteio(rng, DISTRIBUICAO_DE_SESSOES["uso"])],
                        "prioridades_rank": ["economia", "capacidade", "seguranca"],
                    },
                    comparison_id=f"{ford.id}:{concorrente.id}",
                    outcome=desfecho,
                    motivos=motivos,
                    atributo_decisivo=_sorteio(rng, DISTRIBUICAO_DE_SESSOES["atributo_decisivo"]),
                    is_simulated=True,
                    # Espalhadas nos últimos 60 dias, para o filtro `?since=` ter efeito.
                    created_at=agora - dt.timedelta(days=indice % 60, hours=indice % 24),
                )
            )
            criadas += 1
        sessao.commit()

    print(
        f"seed: {criadas} sessao(oes) SIMULADA(s) — todas com is_simulated=true, "
        f"distribuicao declarada em DISTRIBUICAO_DE_SESSOES"
    )
    return criadas


def main(simulated_sessions: int = 0) -> int:
    """Popula o banco apontado por `DATABASE_URL`. Devolve 0 em sucesso.

    Assinatura fixada por `pipeline/cli.py` (`_cmd_seed`).
    """

    print(f"seed: banco = {database_url()}")
    with session_scope() as sessao:
        catalogo = _semear_catalogo(sessao)
        sinonimos = _semear_sinonimos(sessao)
        equivalencias = _semear_equivalencias(sessao)
        referencia = _semear_referencia_interna(sessao)
        linha_papeis = _semear_papeis(sessao)
        linha_admin = _semear_admin(sessao)

    print(
        "seed: catalogo = {marcas} marcas, {modelos} modelos, {versoes} versoes".format(**catalogo)
    )
    print(
        "seed: sinonimos = {campo} de campo + {valor} de valor "
        "({inseridos} novos nesta rodada)".format(**sinonimos)
    )
    print(
        "seed: equivalencias = {inseridos} par(es) cadastrado(s), {pendencias} pendente(s)".format(
            inseridos=equivalencias["inseridos"], pendencias=len(equivalencias["pendentes"])
        )
    )
    for pendencia in equivalencias["pendentes"]:
        print(f"    pendente: {pendencia}")
    print(
        "seed: referencia interna = {linhas} linha(s) do deck da Raptor (tier interno; "
        "nao entra na ficha)".format(linhas=referencia["linhas"])
    )
    for recusada in referencia["recusadas"]:
        print(f"    recusada: {recusada}")
    print(f"seed: {linha_papeis}")
    print(f"seed: {linha_admin}")

    # Depois do catalogo: as sessoes apontam para `versions`.
    if simulated_sessions > 0:
        semear_sessoes_simuladas(simulated_sessions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
