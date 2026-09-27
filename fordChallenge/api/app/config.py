"""Configuração da API: uma leitura do ambiente, num lugar só.

Até a WP-03 cada módulo lia `os.environ` por conta própria — `db.py` documentou a dívida
e ela vence aqui. O ganho não é estilo: com dois leitores da mesma variável, cada um com
seu default, o banco que o Alembic migra pode não ser o que a API abre, e a falha aparece
como "a tabela não existe" horas depois.

Nenhum default abaixo é segredo, e isso é deliberado: `jwt_secret` nasce vazio para que a
WP-05 falhe alto na ausência da variável, em vez de assinar token com um valor que está no
repositório público. Segredo só em `.env` (CLAUDE.md).
"""

from __future__ import annotations

import importlib.metadata
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

#: Banco de dev quando ninguém define `DATABASE_URL` (esta máquina não tem Docker, D-05).
URL_PADRAO_BANCO = "sqlite:///./data/dev.db"


class Settings(BaseSettings):
    """Variáveis de ambiente do SpecRadar, validadas e com tipo.

    `extra="ignore"` porque o `.env` é compartilhado com o pipeline e o worker
    (`ANTHROPIC_API_KEY`, `SNAPSHOT_DIR`, `BIGQUERY_DATASET`, ...): a API não precisa
    conhecer todas as chaves do projeto para poder subir, e uma chave nova de outra trilha
    não pode derrubar a API na inicialização.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = URL_PADRAO_BANCO

    #: **Autenticação ligada?** Padrão `False` nesta fase do projeto (D-204).
    #:
    #: Com ela desligada a API não pede token em rota nenhuma, não devolve 401 nem 403, e
    #: o papel de quem chama vem do cabeçalho `X-Role` — que serve só para **filtrar** o
    #: que é por papel (o vendedor vê as próprias sessões de showroom), nunca para negar.
    #: Quem decide o que mostrar é a tela.
    #:
    #: O código de JWT, argon2 e da matriz de permissões continua no repositório, testado,
    #: atrás desta variável: `AUTH_ENABLED=1` devolve login, RBAC e os 401/403 de
    #: `docs/04` sem tocar em mais nada. O que muda é o **padrão**, e o padrão desta fase
    #: é a ferramenta abrir direto na Consulta.
    auth_enabled: bool = False
    #: O papel de quem chama sem mandar `X-Role`. `admin` porque, com autenticação
    #: desligada, o default tem de ser "não filtra nada": quem abre o `/docs` e dispara
    #: uma rota à mão não deveria receber um recorte silencioso. A tela sempre manda o
    #: cabeçalho.
    papel_padrao: str = "admin"
    #: **Limite de requisições ligado?** Padrão `False` nesta fase (D-206). Desligado, os
    #: middlewares do slowapi não são sequer registrados — o limite sai do caminho de
    #: execução em vez de virar um contador com teto alto.
    rate_limit_enabled: bool = False

    jwt_secret: str = ""
    jwt_access_ttl_min: int = 30
    jwt_refresh_ttl_days: int = 7
    # Texto e não `list[str]`: em campo de lista o pydantic-settings tenta interpretar o
    # valor como JSON, e o `.env` do projeto usa `a,b` separado por vírgula. Quem consome
    # usa `origens_cors`, que já entrega a lista limpa.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_default: str = "60/minute"
    rate_limit_login: str = "5/minute"
    log_level: str = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    replay_mode: bool = False
    llm_fake: bool = False
    #: E-mail do administrador, quando alguém quiser um. **Não é obrigatório** (D-204):
    #: sem autenticação não há login a fazer, e os quatro papéis existem como identidade
    #: de atribuição (quem registrou a sessão de showroom), não como credencial.
    admin_email: str = ""
    #: Só é lida com `AUTH_ENABLED=1`, e mesmo então é opcional: o `seed` só cria o
    #: administrador com senha se ela existir. Vazia é o padrão e não quebra nada.
    admin_password: str = ""
    specradar_user_agent: str = "SpecRadar/0.1 (defina SPECRADAR_USER_AGENT no .env)"
    #: Dias a partir dos quais uma evidencia conta como **desatualizada** na Saude do
    #: Conhecimento (WP-33). Trinta dias e o intervalo em que preco de tabela e linha
    #: vigente mudam no mercado brasileiro; abaixo disso o indicador acusaria o normal.
    #: Fica em config porque a spec pede ("N em config") e porque e a alavanca que o
    #: gestor mexe quando decide com que frequencia quer reconferir.
    health_stale_days: int = 30

    @property
    def origens_cors(self) -> tuple[str, ...]:
        """Origens liberadas no CORS. `*` é descartado, nunca repassado.

        docs/04 e docs/08 exigem CORS restrito às origens configuradas. Além da regra: com
        `allow_credentials=True` o navegador rejeita `*` de qualquer forma, então repassá-lo
        entregaria uma API que *parece* aberta e não funciona — pior do que negar.
        """
        origens = (parte.strip() for parte in self.cors_origins.split(","))
        return tuple(origem for origem in origens if origem and origem != "*")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Configuração do processo, lida uma vez.

    Cacheada porque a resposta não muda durante a vida do processo de API. Quem troca
    variável no meio da execução (testes, Alembic, seed) chama `Settings()` direto ou
    `get_settings.cache_clear()` — ver `api.app.db.database_url`.
    """
    return Settings()


def descrever_banco(url: str) -> dict[str, str]:
    """Dialeto e nome do banco a partir da URL — nunca usuário, senha ou host.

    `/health` é público (docs/04) e uma DSN de Postgres carrega credencial no próprio
    texto. O que sai daqui responde "qual banco?" sem responder "como entrar nele?".
    """
    esquema, _, resto = url.partition("://")
    # `postgresql+psycopg` -> `postgresql`: o driver é detalhe de instalação, não de banco.
    dialeto = esquema.split("+", 1)[0].strip() or "desconhecido"
    nome = resto.rsplit("/", 1)[-1].split("?", 1)[0] if resto else ""
    if not nome and dialeto == "sqlite":
        nome = ":memory:"
    return {"dialeto": dialeto, "nome": nome or "desconhecido"}


@lru_cache(maxsize=1)
def versao_do_pacote() -> str:
    """Versão do `pyproject.toml`, via metadados do pacote instalado.

    Não repetida em código de propósito: um número escrito aqui divergiria do
    `pyproject.toml` no primeiro bump e a API passaria a mentir a própria versão.
    """
    try:
        return importlib.metadata.version("specradar")
    except importlib.metadata.PackageNotFoundError:
        # Clone sem `uv sync`. Marcador explícito é melhor que um número inventado.
        return "0.0.0+nao-instalado"
