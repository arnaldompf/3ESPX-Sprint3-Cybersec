"""Backup cifrado do banco, verificação de integridade e restauração.

Rotina de backup e recuperação do plano de segurança contínua (docs/SPRINT3 §4.3.4):

* **criar**: copia o banco (SQLite pela API de backup online; Postgres por `pg_dump -Fc`),
  cifra com AES-256-GCM (`seguranca.cripto_local`, AAD `backup`) e grava ao lado um
  manifesto JSON com data, origem, id da chave e SHA-256 do arquivo cifrado. A cópia em
  claro só existe num diretório temporário e é apagada no fim;
* **verificar**: confere o SHA-256 do manifesto **e** decifra (a tag GCM prova que nada
  foi alterado). É o que o job agendado roda todo dia: backup que não se verifica não é
  backup;
* **restaurar**: decifra e devolve o banco (arquivo SQLite ou `pg_restore`);
* **retenção**: `--manter N` apaga os backups mais antigos além dos N mais novos.

A senha do Postgres **não** vai na linha de comando do `pg_dump` (apareceria no `ps` de
qualquer usuário da máquina): vai em `PGPASSWORD`, só no ambiente do subprocesso.

Uso::

    python -m seguranca.backup criar      --banco "$DATABASE_URL" --destino backups/ --manter 14
    python -m seguranca.backup verificar  backups/specradar-20261001T030000Z.srbak
    python -m seguranca.backup restaurar  backups/specradar-....srbak --banco sqlite:///restaurado.db
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from seguranca.cripto_local import (
    ChaveAusente,
    DadoCorrompido,
    chaves_do_ambiente,
    cifrar,
    decifrar,
    id_da_chave,
)

EXTENSAO = ".srbak"
AAD = "backup"


def _caminho_sqlite(url: str) -> Path:
    return Path(url.split("sqlite:///", 1)[1])


def _ambiente_pg(url: str) -> tuple[list[str], dict[str, str]]:
    """Argumentos de conexão sem senha + ambiente com `PGPASSWORD`."""
    partes = urlsplit(url.replace("postgresql+psycopg://", "postgresql://"))
    args = [
        "--host", partes.hostname or "localhost",
        "--port", str(partes.port or 5432),
        "--username", unquote(partes.username or ""),
        "--dbname", partes.path.lstrip("/"),
    ]  # fmt: skip
    ambiente = {**os.environ, "PGPASSWORD": unquote(partes.password or "")}
    return args, ambiente


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _dump(url: str, destino: Path) -> str:
    if url.startswith("sqlite"):
        origem = sqlite3.connect(_caminho_sqlite(url))
        copia = sqlite3.connect(destino)
        with copia:
            origem.backup(copia)
        origem.close()
        copia.close()
        return "sqlite"
    if url.startswith("postgresql"):
        args, ambiente = _ambiente_pg(url)
        subprocess.run(
            ["pg_dump", "--format=custom", "--no-owner", "--file", str(destino), *args],
            check=True,
            env=ambiente,
        )
        return "postgresql"
    raise ValueError("banco não suportado: use sqlite:/// ou postgresql://")


def criar(url: str, destino_dir: Path, *, manter: int | None = None) -> Path:
    destino_dir.mkdir(parents=True, exist_ok=True)
    chave = chaves_do_ambiente()[0]
    carimbo = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    arquivo = destino_dir / f"specradar-{carimbo}{EXTENSAO}"
    with tempfile.TemporaryDirectory(prefix="specradar-backup-") as tmp:
        claro = Path(tmp) / "dump"
        origem = _dump(url, claro)
        arquivo.write_bytes(cifrar(claro.read_bytes(), aad=AAD, chave=chave))
    os.chmod(arquivo, 0o600)
    manifesto = {
        "arquivo": arquivo.name,
        "criado_em": carimbo,
        "origem": origem,
        "algoritmo": "AES-256-GCM",
        "id_da_chave": id_da_chave(chave).hex(),
        "sha256_cifrado": _sha256(arquivo),
        "bytes": arquivo.stat().st_size,
    }
    arquivo.with_suffix(".json").write_text(json.dumps(manifesto, indent=2), encoding="utf-8")
    if manter:
        aplicar_retencao(destino_dir, manter)
    return arquivo


def verificar(arquivo: Path) -> dict:
    manifesto = json.loads(arquivo.with_suffix(".json").read_text(encoding="utf-8"))
    if _sha256(arquivo) != manifesto["sha256_cifrado"]:
        raise DadoCorrompido("SHA-256 não confere com o manifesto")
    decifrar(arquivo.read_bytes(), aad=AAD)  # a tag GCM prova a integridade do conteúdo
    return manifesto


def restaurar(arquivo: Path, url: str) -> None:
    manifesto = verificar(arquivo)
    dados = decifrar(arquivo.read_bytes(), aad=AAD)
    if manifesto["origem"] == "sqlite":
        alvo = _caminho_sqlite(url)
        alvo.write_bytes(dados)
        os.chmod(alvo, 0o600)
        return
    with tempfile.TemporaryDirectory(prefix="specradar-restore-") as tmp:
        dump = Path(tmp) / "dump"
        dump.write_bytes(dados)
        args, ambiente = _ambiente_pg(url)
        subprocess.run(
            ["pg_restore", "--clean", "--if-exists", "--no-owner", *args, str(dump)],
            check=True,
            env=ambiente,
        )


def aplicar_retencao(destino_dir: Path, manter: int) -> list[Path]:
    backups = sorted(destino_dir.glob(f"specradar-*{EXTENSAO}"), reverse=True)
    removidos = backups[manter:]
    for velho in removidos:
        velho.unlink()
        velho.with_suffix(".json").unlink(missing_ok=True)
    return removidos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seguranca.backup")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("criar")
    p.add_argument("--banco", default=os.environ.get("DATABASE_URL", ""))
    p.add_argument("--destino", type=Path, default=Path("backups"))
    p.add_argument("--manter", type=int)
    p = sub.add_parser("verificar")
    p.add_argument("arquivo", type=Path)
    p = sub.add_parser("restaurar")
    p.add_argument("arquivo", type=Path)
    p.add_argument("--banco", required=True)
    args = parser.parse_args(argv)
    try:
        if args.comando == "criar":
            print(criar(args.banco, args.destino, manter=args.manter))
        elif args.comando == "verificar":
            print(json.dumps(verificar(args.arquivo), indent=2))
        else:
            restaurar(args.arquivo, args.banco)
            print("restaurado")
    except (ChaveAusente, DadoCorrompido, ValueError, subprocess.CalledProcessError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
