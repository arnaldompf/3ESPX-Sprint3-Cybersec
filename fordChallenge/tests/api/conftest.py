"""Fixtures dos testes da API.

Separado de `tests/conftest.py`, que é global e não se mexe: tudo aqui é sobre montar um
app novo por cenário.

O app vem sempre de `create_app()` com o ambiente já ajustado, e o cache de
`get_settings()` é limpo antes e depois. Sem isso, o primeiro teste que constrói o app
congela a configuração para todos os outros e a suíte passa a depender da ordem em que
roda — que é o jeito mais silencioso de ter um teste que mente.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app.config import get_settings

#: Única origem liberada nos testes de CORS.
ORIGEM_PERMITIDA = "http://localhost:5173"


@pytest.fixture
def origem_permitida() -> str:
    """A origem que `ambiente_api` libera no CORS.

    Fixture e não `from .conftest import ...`: sem `__init__.py` em `tests/api/`, import
    relativo de conftest não resolve — e criar o `__init__.py` mudaria a coleção da suíte
    inteira por causa de uma constante.
    """
    return ORIGEM_PERMITIDA


@pytest.fixture
def ambiente_api(monkeypatch: pytest.MonkeyPatch, sqlite_url: str) -> Iterator[None]:
    """Ambiente determinístico: banco descartável, CORS de uma origem, sem rota de boom.

    O banco é o SQLite de `tmp_path` (fixture `sqlite_url`) e não o de dev: `/health`
    abre conexão de verdade, e um teste não tem por que criar arquivo em `data/`.
    """
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    monkeypatch.setenv("CORS_ORIGINS", ORIGEM_PERMITIDA)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.delenv("SPECRADAR_DEBUG_BOOM", raising=False)
    # O mundo **padrao** desta fase (D-204): sem autenticacao e sem limite. Escrito como
    # variavel de ambiente e nao deixado por omissao porque o pydantic-settings le o
    # `.env` da maquina — deixar o arquivo decidir faria a suite depender de quem roda.
    monkeypatch.setenv("AUTH_ENABLED", "0")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def app(ambiente_api: None) -> FastAPI:
    """App novo, montado depois de o ambiente estar no lugar."""
    from api.app.main import create_app

    return create_app()


@pytest.fixture
def cliente(app: FastAPI) -> Iterator[TestClient]:
    """Cliente que **não** re-levanta a exceção do servidor.

    Com o default (`raise_server_exceptions=True`), o `ServerErrorMiddleware` do Starlette
    envia a resposta de 500 e **depois** re-levanta a exceção; o teste morreria no `raise`
    sem nunca olhar o corpo que o cliente da API receberia.
    """
    with TestClient(app, raise_server_exceptions=False) as instancia:
        yield instancia


# ---------------------------------------------------------------- WP-05: autenticação
#: Senha de teste. Longa porque `/users` exige 12 caracteres.
SENHA_DE_TESTE = "senha-de-teste-longa"


@pytest.fixture
def ambiente_auth(ambiente_api: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Ambiente com **autenticação ligada**, `JWT_SECRET` válido e o banco migrado.

    `AUTH_ENABLED=1` aqui, e não por omissão. Desde D-204 o padrão do produto é o
    contrário — sem login, sem 401, sem 403 —, e todo teste que fala de token, papel ou
    limite está exercitando um **caminho opcional**, que continua no repositório e
    continua tendo de funcionar para quem ligar a chave.

    Por que ligar em vez de pular: teste pulado apodrece. O código de JWT, argon2, rotação
    de refresh e da matriz de permissões não saiu do projeto; se ele deixar de funcionar,
    quem ligar `AUTH_ENABLED=1` descobre em produção. O que o mundo padrão precisa provar
    — que **nada** disso é exigido — está em `test_sem_autenticacao.py`, com o app montado
    pelo `ambiente_api` normal.

    O segredo é fixo e longo (≥ 32 bytes) porque `security.segredo()` recusa segredo
    curto — e recusa de propósito: HS256 com segredo curto é força bruta viável.
    """
    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("JWT_SECRET", "segredo-de-teste-com-folga-de-32-bytes-e-mais")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "1000/minute")
    monkeypatch.setenv("RATE_LIMIT_LOGIN", "5/minute")
    get_settings.cache_clear()
    # O `Limiter` e um singleton de modulo com armazenamento em memoria — e tem de ser,
    # para o decorador da rota e o middleware contarem na MESMA conta. O efeito colateral
    # e que o contador atravessa testes: o 6o login de um teste caia como 429 no seguinte,
    # com a falha aparecendo a arquivos de distancia da causa. Zerar aqui torna a
    # independencia estrutural, e nao disciplina de quem escreve o teste (D-31 outra vez).
    from api.app.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()
    get_settings.cache_clear()


@pytest.fixture
def schema_criado(ambiente_auth: None) -> None:
    """Cria as tabelas no SQLite descartavel.

    Fixture propria, e nao dentro de `app_auth`, porque `criar_usuario` tambem precisa do
    schema — e a ordem em que o pytest resolve as fixtures de um teste nao garante que o
    app seja montado antes da fabrica de usuario. O sintoma era "no such table: users" em
    18 testes de uma vez.
    """
    from sqlmodel import SQLModel

    # O import de `models` e OBRIGATORIO antes do `create_all`: `SQLModel.metadata` so
    # conhece as tabelas cujas classes foram importadas, e `create_all` sobre metadata
    # vazio nao levanta nada — cria zero tabelas em silencio. O sintoma foi
    # "no such table: users" com a URL do banco correta nas duas pontas.
    import api.app.models  # noqa: F401
    from api.app.db import engine

    SQLModel.metadata.create_all(engine())


@pytest.fixture
def criar_usuario(schema_criado: None):
    """Fábrica de usuário direto no banco, sem passar pela API."""
    from api.app.db import session_scope
    from api.app.models import Role, User
    from api.app.security import hash_de_senha

    criados: list[str] = []

    def fabrica(
        email: str = "analista@suno.example.com",
        role: Role | str = "analista",
        *,
        senha: str = SENHA_DE_TESTE,
        ativo: bool = True,
    ) -> User:
        with session_scope() as sessao:
            usuario = User(
                email=email,
                nome=email.split("@")[0],
                password_hash=hash_de_senha(senha),
                role=str(role),
                ativo=ativo,
            )
            sessao.add(usuario)
            sessao.commit()
            sessao.refresh(usuario)
            criados.append(usuario.id)
            # `expunge` antes de a sessao fechar: sem isso o objeto volta ligado a uma
            # sessao morta e o primeiro `usuario.id` do teste levanta
            # `DetachedInstanceError`. Com o expunge, os atributos ja carregados
            # continuam legiveis e nada mais e buscado no banco.
            sessao.expunge(usuario)
            return usuario

    return fabrica


@pytest.fixture
def app_auth(schema_criado: None) -> FastAPI:
    """App com o schema criado, para as rotas que gravam."""
    from api.app.main import create_app

    return create_app()


@pytest.fixture
def cliente_auth(app_auth: FastAPI) -> Iterator[TestClient]:
    with TestClient(app_auth, raise_server_exceptions=False) as instancia:
        yield instancia


@pytest.fixture
def logar(cliente_auth: TestClient):
    """Faz login e devolve o header `Authorization` pronto."""

    def acao(email: str, senha: str = SENHA_DE_TESTE) -> dict[str, str]:
        resposta = cliente_auth.post("/api/v1/auth/login", json={"email": email, "senha": senha})
        assert resposta.status_code == 200, resposta.text
        return {"Authorization": f"Bearer {resposta.json()['access_token']}"}

    return acao


# ------------------------------------------------------------------- WP-06: catalogo
@pytest.fixture
def catalogo(schema_criado: None):
    """Semeia um catálogo mínimo e devolve os ids.

    Dois veículos de marcas diferentes, um deles com `spec_values` gravados — é o que
    permite exercitar `/specs`, `/comparisons` e o filtro `attributes` sem depender do
    pipeline ter rodado.
    """
    from api.app.db import session_scope
    from api.app.models import Brand, Evidence, SpecValue, VehicleModel, Version

    with session_scope() as sessao:
        ford = Brand(nome="Ford")
        toyota = Brand(nome="Toyota")
        sessao.add(ford)
        sessao.add(toyota)
        sessao.flush()

        ranger = VehicleModel(brand_id=ford.id, nome="Ranger")
        hilux = VehicleModel(brand_id=toyota.id, nome="Hilux")
        sessao.add(ranger)
        sessao.add(hilux)
        sessao.flush()

        raptor = Version(
            model_id=ranger.id,
            nome_exato="Raptor 3.0 V6 Bi-turbo 4WD AT",
            ano_modelo=2026,
            codigo_fipe="003506-8",
            in_lineup=True,
            lineup_checked_at=dt.datetime(2026, 9, 1),
        )
        srx = Version(
            model_id=hilux.id,
            nome_exato="SRX Plus AT (Cabine Dupla)",
            ano_modelo=2026,
            in_lineup=True,
            lineup_checked_at=dt.datetime(2026, 9, 1),
        )
        # Versão sem checagem de linha: o filtro `lineup=current` tem de excluí-la e
        # **contá-la**, em vez de afirmar que está na linha com base em nada.
        antiga = Version(model_id=hilux.id, nome_exato="GR-Sport", ano_modelo=2024, in_lineup=False)
        for v in (raptor, srx, antiga):
            sessao.add(v)
        sessao.flush()

        evidencia = Evidence(
            source_url="https://www.ford.com.br/picapes/ranger-raptor/",
            tier=1,
            quote="Potência 397cv",
            captured_at=dt.datetime(2026, 9, 1),
            raw_value="397 cv",
        )
        sessao.add(evidencia)
        sessao.flush()
        sessao.add(
            SpecValue(
                version_id=raptor.id,
                field="potencia_cv",
                value_json=397,
                unit="cv",
                status="verificado",
                confidence=0.95,
                evidence_id=evidencia.id,
            )
        )
        sessao.add(
            SpecValue(
                version_id=raptor.id,
                field="torque_nm",
                value_json=583,
                unit="Nm",
                status="verificado",
                confidence=0.9,
                evidence_id=evidencia.id,
            )
        )
        sessao.commit()
        dados = {
            "brand_ford": ford.id,
            "brand_toyota": toyota.id,
            "model_ranger": ranger.id,
            "model_hilux": hilux.id,
            "raptor": raptor.id,
            "srx": srx.id,
            "antiga": antiga.id,
            "evidencia": evidencia.id,
        }
    return dados
