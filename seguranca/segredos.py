"""Segredos lidos de arquivo, no padrão `VAR_FILE` (Docker/Kubernetes secrets).

A solução lê segredos só de variável de ambiente (`JWT_SECRET`, `DATABASE_URL`, ...).
Variável de ambiente vaza com facilidade: aparece em `docker inspect`, em `/proc/<pid>/environ`
e em dump de crash. Com secrets montados em arquivo (`/run/secrets/...`, permissão 0400),
o valor só existe dentro do contêiner que precisa dele.

Esta função roda **antes** de a configuração da solução ser lida: para cada segredo
conhecido, se `VAR_FILE` existe e `VAR` não, o conteúdo do arquivo vira `VAR` no processo.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Segredos que a solução e esta camada leem do ambiente.
SEGREDOS_CONHECIDOS = (
    "DATABASE_URL",
    "JWT_SECRET",
    "ADMIN_PASSWORD",
    "LLM_API_KEY",
    "LLM_API_KEY_ALT",
    "SEARCH_API_KEY",
    "TAVILY_API_KEY",
    "METRICS_TOKEN",
    "SPECRADAR_DATA_KEY",
    "LOG_PSEUDONIMO_KEY",
)


def carregar_segredos_de_arquivo(ambiente: dict[str, str] | None = None) -> list[str]:
    """Preenche `VAR` a partir de `VAR_FILE`. Devolve os nomes carregados (nunca os valores).

    Variável já definida **não** é sobrescrita: quem definiu explicitamente sabe o que fez.
    """
    alvo = os.environ if ambiente is None else ambiente
    carregados: list[str] = []
    for nome in SEGREDOS_CONHECIDOS:
        arquivo = alvo.get(f"{nome}_FILE", "").strip()
        if not arquivo or alvo.get(nome):
            continue
        alvo[nome] = Path(arquivo).read_text(encoding="utf-8").strip()
        carregados.append(nome)
    return carregados
