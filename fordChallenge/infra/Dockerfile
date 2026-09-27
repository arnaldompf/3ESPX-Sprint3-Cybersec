# Imagem unica para a API e o worker: o mesmo codigo, comandos diferentes.
#
# Duas imagens dariam a chance de a API e o worker rodarem versoes diferentes do pipeline
# — e ai a ficha que a API le nao e a ficha que o worker escreveu. Uma imagem, um `command`
# por servico.
#
# NAO FOI CONSTRUIDA NESTA MAQUINA: o daemon do Docker nao esta de pe
# (DECISOES_NOITE.md D-05), entao este arquivo e o do compose sao artefato de melhor
# esforco, escritos a partir do que o projeto de fato precisa para rodar. Quem tiver
# Docker confere com `docker compose -f infra/docker-compose.yml build`.

FROM python:3.11-slim AS base

# `uv` do binario oficial: mais rapido que instalar por pip e sem depender do indice.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Dependencias antes do codigo: a camada so e reconstruida quando o lock muda, e nao a
# cada alteracao de arquivo Python.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra postgres

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --extra postgres

# Usuario sem privilegio: o processo nao precisa de root, e um container de API que roda
# como root transforma qualquer escapada em escapada com poder.
RUN useradd --create-home --uid 10001 specradar \
    && mkdir -p /app/data /app/reports \
    && chown -R specradar:specradar /app/data /app/reports
USER specradar

EXPOSE 8000

# O default e a API; o compose sobrescreve no servico do worker.
CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
