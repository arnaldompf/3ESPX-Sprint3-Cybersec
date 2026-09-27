# syntax=docker/dockerfile:1.7
#
# Imagem endurecida do SpecRadar (API + worker). Build a partir da RAIZ do repositório:
#
#   docker build -f infra/Dockerfile -t specradar .
#
# Diferenças em relação a fordChallenge/infra/Dockerfile (o original da solução):
#
#   | Risco no original                               | Aqui                                         |
#   |-------------------------------------------------|----------------------------------------------|
#   | `uv:latest` — base mutável, build não reproduz  | versões fixadas (Dependabot atualiza)        |
#   | estágio único: uv e cache de build em produção  | multi-stage: runtime só com venv + código    |
#   | código pertencente ao usuário da aplicação      | código de root, só leitura para o processo   |
#   | sem build do front (/app responde 404)          | estágio Node compila o web app               |
#   | source maps do front publicados                 | `*.map` removidos (não expõe o fonte)        |
#   | sem HEALTHCHECK                                 | HEALTHCHECK no /api/v1/health                |
#   | `uvicorn api.app.main:app` (sem controles)      | `seguranca.app_segura:app` (trava, rate      |
#   |                                                 | limit verificado, eventos, métricas, SSRF)   |
#   | pacotes do SO como vieram na base               | `apt-get upgrade` aplica correções de CVE    |

# ---------------------------------------------------------------- 1. front-end (React/Vite)
FROM node:22.12-alpine3.21 AS web
WORKDIR /src/web
COPY fordChallenge/web/package.json fordChallenge/web/package-lock.json ./
# --ignore-scripts: script de pós-instalação de dependência é vetor clássico de supply chain.
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY fordChallenge/web/ ./
RUN npm run build && find dist -name '*.map' -delete

# ---------------------------------------------------------------- 2. dependências Python
FROM python:3.12.8-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY fordChallenge/pyproject.toml fordChallenge/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra postgres
COPY fordChallenge/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra postgres

# ---------------------------------------------------------------- 3. runtime
FROM python:3.12.8-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="specradar" \
      org.opencontainers.image.description="SpecRadar - Ford Challenge (imagem endurecida)" \
      org.opencontainers.image.source="https://github.com/arnaldompf/3ESPX-Sprint3-Cybersec"

# Correções de segurança do SO e nada além delas; lista do apt apagada na mesma camada.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin specradar

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    SPECRADAR_SOLUCAO_DIR=/app \
    APP_ENV=producao \
    # Só o proxy (Caddy) pode declarar o IP do cliente via X-Forwarded-For; sem isso,
    # qualquer um forjaria o cabeçalho e escaparia do rate limit por IP.
    FORWARDED_ALLOW_IPS=172.30.0.10

WORKDIR /app
# Código e venv pertencem a root: o processo (uid 10001) lê e executa, mas não altera.
COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app
COPY --from=web /src/web/dist /app/web/dist
COPY seguranca/ /app/seguranca/
# Só os diretórios de dado são graváveis pelo processo.
RUN mkdir -p /app/data /app/reports \
    && chown specradar:specradar /app/data /app/reports

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"]

# --no-access-log: o access log do uvicorn é texto puro e traz o IP em claro. A solução já
# registra cada requisição em JSON (`http.request`), e a camada de segurança, a origem
# pseudonimizada. Medido ao subir a stack: sem a flag, o IP vazava para o Loki.
CMD ["uvicorn", "seguranca.app_segura:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--no-server-header", "--no-date-header", "--no-access-log"]
