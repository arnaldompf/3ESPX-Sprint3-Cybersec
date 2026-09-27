"""Parser pesado cancelável. Saída JSON, executado somente com prazo explícito."""

import contextlib
import json
import sys
from dataclasses import asdict


def main():
    from pipeline.parse.pdf import parse_pdf

    data = sys.stdin.buffer.read()
    with contextlib.redirect_stdout(sys.stderr):
        if "--pbe" in sys.argv:
            from pipeline.connectors.pbe import linhas_da_tabela

            payload = {"linhas": linhas_da_tabela(data)}
        else:
            payload = asdict(parse_pdf(data))
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))


if __name__ == "__main__":
    main()
