"""O worker do pipeline com a proteção de SSRF ligada — `python -m seguranca.worker_seguro`.

Mesmo worker de `fordChallenge/pipeline/cli.py worker`; a única diferença é que o coletor
HTTP passa por `seguranca.ssrf` antes de sair para a rede, e os logs saem no mesmo JSON da
API (o worker da solução usa o formato de console do structlog, que o Loki não indexa por
evento).
"""

from __future__ import annotations

import os
import sys

from seguranca.segredos import carregar_segredos_de_arquivo
from seguranca.ssrf import proteger_pipeline


def main() -> int:
    carregar_segredos_de_arquivo()
    proteger_pipeline()
    from api.app.middleware import configurar_logs
    from pipeline.cli import main as cli

    configurar_logs(os.environ.get("LOG_LEVEL", "INFO"))

    return cli(["worker", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
