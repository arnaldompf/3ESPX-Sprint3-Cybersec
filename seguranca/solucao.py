"""Onde está o código da solução, e como importá-lo sem alterá-lo.

No repositório da entrega a solução fica em `fordChallenge/`. Na imagem de contêiner
(`infra/Dockerfile`) ela é copiada para `/app`, ao lado deste pacote. A variável
`SPECRADAR_SOLUCAO_DIR` cobre os dois casos sem `if` espalhado pelo código.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ_DA_ENTREGA = Path(__file__).resolve().parents[1]


def diretorio_da_solucao() -> Path:
    """`SPECRADAR_SOLUCAO_DIR` quando definida; senão `<raiz>/fordChallenge`."""
    definido = os.environ.get("SPECRADAR_SOLUCAO_DIR", "").strip()
    return Path(definido) if definido else RAIZ_DA_ENTREGA / "fordChallenge"


def preparar_importacao() -> Path:
    """Põe a solução no `sys.path` (uma vez) e devolve o diretório dela."""
    diretorio = diretorio_da_solucao()
    if not (diretorio / "api" / "app" / "main.py").exists():
        raise RuntimeError(
            f"Solução SpecRadar não encontrada em {diretorio}. "
            "Defina SPECRADAR_SOLUCAO_DIR apontando para a pasta que contém `api/`."
        )
    caminho = str(diretorio)
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
    return diretorio
