"""D-204 — o mundo **padrão**: a API não pede credencial, e o papel vem de `X-Role`.

Substitui `test_demo_mode.py`. O modo demonstração existia para a apresentação não parar
numa tela de login; agora não há tela de login, não há `/auth/demo-login` e não há senha em
lugar nenhum. O que estes testes cercam é a invariante nova, e ela tem três metades:

* **nenhuma rota exige token** e nenhuma responde 401, 403 ou 429;
* **`X-Role` filtra, e não nega** — o vendedor entra em `/insights/competitors` e recebe
  o próprio recorte, não uma recusa;
* **o caminho de login não existe** enquanto `AUTH_ENABLED` for falso, nem no
  `/openapi.json`. O que não está montado não pode ser chamado nem descoberto.

O caminho com autenticação **ligada** continua testado, em `test_auth.py`, `test_rbac.py`
e `test_ratelimit.py`, pela fixture `ambiente_auth`.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from api.app.models import Role
from api.app.papel import CABECALHO_PAPEL, SEM_SENHA, email_do_papel


@pytest.fixture
def cliente_sem_auth(schema_criado_sem_auth: None) -> TestClient:
    from api.app.main import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture
def schema_criado_sem_auth(ambiente_api: None) -> None:
    """As tabelas no SQLite descartável, com o ambiente padrão (sem autenticação)."""
    from sqlmodel import SQLModel

    import api.app.models  # noqa: F401
    from api.app.db import engine

    SQLModel.metadata.create_all(engine())


#: Rotas de leitura que antes exigiam token. Uma por roteador, para o teste cobrir a
#: montagem inteira e não só uma família de rotas.
ROTAS_DE_LEITURA = [
    "/api/v1/vehicles",
    "/api/v1/alerts",
    "/api/v1/events",
    "/api/v1/dimensions",
    "/api/v1/scenarios/fields",
    "/api/v1/insights/coverage",
    "/api/v1/insights/knowledge-health/versions",
    "/api/v1/insights/competitors",
    "/api/v1/insights/summary",
    "/api/v1/showroom-sessions",
    "/api/v1/sources",
    "/api/v1/users",
    "/api/v1/auth/me",
]


@pytest.mark.parametrize("rota", ROTAS_DE_LEITURA)
def test_nenhuma_rota_pede_credencial(cliente_sem_auth: TestClient, rota: str):
    """Sem `Authorization` e sem `X-Role`: nada de 401, nada de 403."""
    resposta = cliente_sem_auth.get(rota)
    assert resposta.status_code not in (401, 403, 429), (rota, resposta.status_code, resposta.text)


@pytest.mark.parametrize("papel", [p.value for p in Role])
@pytest.mark.parametrize("rota", ROTAS_DE_LEITURA)
def test_nenhum_papel_recebe_recusa(cliente_sem_auth: TestClient, rota: str, papel: str):
    """Os quatro papéis alcançam todas as rotas. O recorte é de conteúdo, não de acesso."""
    resposta = cliente_sem_auth.get(rota, headers={CABECALHO_PAPEL: papel})
    assert resposta.status_code not in (401, 403, 429), (
        rota,
        papel,
        resposta.status_code,
        resposta.text,
    )


def test_o_papel_vem_do_cabecalho(cliente_sem_auth: TestClient):
    for papel in (p.value for p in Role):
        corpo = cliente_sem_auth.get("/api/v1/auth/me", headers={CABECALHO_PAPEL: papel}).json()
        assert corpo["role"] == papel
        assert corpo["email"] == email_do_papel(papel)


def test_papel_desconhecido_nao_derruba_nem_nega(cliente_sem_auth: TestClient):
    """Papel escrito errado vira o padrão. Negar aqui seria autenticação com outro nome."""
    resposta = cliente_sem_auth.get("/api/v1/auth/me", headers={CABECALHO_PAPEL: "sindico"})
    assert resposta.status_code == 200
    assert resposta.json()["role"] == "admin"


def test_sem_cabecalho_nada_e_filtrado(cliente_sem_auth: TestClient):
    """Quem chama à mão pelo `/docs` recebe a visão completa, não um recorte silencioso."""
    assert cliente_sem_auth.get("/api/v1/auth/me").json()["role"] == "admin"


def test_as_identidades_de_papel_nascem_sem_senha_utilizavel(cliente_sem_auth: TestClient):
    """A linha de `users` existe para a chave estrangeira, não para entrar com ela."""
    from sqlmodel import select

    from api.app.db import session_scope
    from api.app.models import User
    from api.app.security import senha_confere

    cliente_sem_auth.get("/api/v1/auth/me", headers={CABECALHO_PAPEL: "vendedor"})
    with session_scope() as sessao:
        usuario = sessao.exec(select(User).where(User.role == "vendedor")).first()
        assert usuario is not None
        assert usuario.password_hash == SEM_SENHA
        # Não é hash de nada: nenhuma senha entra por aqui, nem por acidente.
        assert senha_confere("", usuario.password_hash) is False
        assert senha_confere(SEM_SENHA, usuario.password_hash) is False


def test_nao_existe_caminho_de_login(cliente_sem_auth: TestClient):
    """Login, refresh, logout e a entrada sem senha do modo demonstração: nenhum existe."""
    for caminho in ("/auth/login", "/auth/refresh", "/auth/logout", "/auth/demo-login"):
        assert cliente_sem_auth.post(f"/api/v1{caminho}", json={}).status_code == 404, caminho

    esquema = cliente_sem_auth.get("/openapi.json").json()
    caminhos = set(esquema["paths"])
    assert "/api/v1/auth/me" in caminhos
    for caminho in ("/auth/login", "/auth/refresh", "/auth/logout", "/auth/demo-login"):
        assert f"/api/v1{caminho}" not in caminhos, caminho


def test_health_publica_que_a_porta_esta_aberta(cliente_sem_auth: TestClient):
    """Quem administra a máquina descobre pelo `/health`, sem ler o `.env`."""
    corpo = cliente_sem_auth.get("/api/v1/health").json()
    assert corpo["auth_enabled"] is False
    assert "demo_mode" not in corpo


def test_o_limite_de_requisicoes_esta_fora_do_caminho(cliente_sem_auth: TestClient):
    """Cem chamadas seguidas, nenhum 429. O limite não é alto: ele não está na pilha."""
    for _ in range(100):
        assert cliente_sem_auth.get("/api/v1/vehicles").status_code == 200


def test_o_vendedor_ve_as_proprias_sessoes_e_nao_uma_recusa(cliente_sem_auth: TestClient):
    """O recorte por papel continua valendo: é isto que `X-Role` serve para fazer.

    Duas sessões de showroom, uma de cada vendedor. Com `X-Role: vendedor` o painel conta
    **uma**; com `X-Role: gestor`, duas. Nenhum dos dois recebe 403.
    """
    from sqlmodel import select

    from api.app.db import session_scope
    from api.app.models import Brand, ShowroomSession, User, VehicleModel, Version

    # A identidade do vendedor nasce na primeira chamada; a sessão dele aponta para ela.
    cliente_sem_auth.get("/api/v1/auth/me", headers={CABECALHO_PAPEL: "vendedor"})
    with session_scope() as sessao:
        vendedor = sessao.exec(select(User).where(User.role == "vendedor")).one()
        marca = Brand(nome="Ford")
        sessao.add(marca)
        sessao.flush()
        modelo = VehicleModel(brand_id=marca.id, nome="Ranger")
        sessao.add(modelo)
        sessao.flush()
        versao = Version(model_id=modelo.id, nome_exato="Limited", ano_modelo=2026)
        concorrente = Version(model_id=modelo.id, nome_exato="XLS", ano_modelo=2026)
        sessao.add(versao)
        sessao.add(concorrente)
        sessao.flush()
        outro = User(
            email="outro@exemplo.test", nome="Outro", password_hash=SEM_SENHA, role="vendedor"
        )
        sessao.add(outro)
        sessao.flush()
        for dono in (vendedor.id, outro.id):
            sessao.add(
                ShowroomSession(
                    vendedor_id=dono,
                    ford_version_id=versao.id,
                    competitor_version_ids=[concorrente.id],
                    outcome="fechou",
                    created_at=dt.datetime(2026, 9, 1),
                )
            )

    def sessoes(papel: str) -> int:
        resposta = cliente_sem_auth.get(
            "/api/v1/showroom-sessions", headers={CABECALHO_PAPEL: papel}
        )
        assert resposta.status_code == 200, resposta.text
        return len(resposta.json())

    assert sessoes("vendedor") == 1
    assert sessoes("gestor") == 2
