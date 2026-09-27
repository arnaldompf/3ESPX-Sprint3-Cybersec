"""Criptografia local de dados em repouso: AES-256-GCM com chave fora do repositório.

**O que fica em disco na solução e por que cifrar:** o SpecRadar grava em `data/` o banco
de desenvolvimento, uploads de documentos, exportações (CSV/PDF/XLSX) e cópias das fontes;
em produção, os backups do Postgres. Banco e backup carregam e-mail e nome dos usuários e o
`audit_log`, que são dado pessoal (LGPD). Um disco, um volume ou um bucket de backup que
vaza não pode entregar esses dados legíveis.

**Escolhas:**

* **AES-256-GCM** (AEAD): cifra e autentica. Qualquer byte alterado no arquivo cifrado
  faz a decifragem falhar — integridade de graça, sem HMAC separado;
* **nonce de 96 bits aleatório por mensagem** (`os.urandom`), nunca reaproveitado;
* **dados associados (AAD)** amarram o texto cifrado ao seu propósito: um backup cifrado
  com `aad="backup"` não decifra como se fosse `aad="exportacao"`;
* **identificador da chave no cabeçalho** (8 bytes do SHA-256 da chave): permite rotação.
  A chave nova cifra; as antigas (em `SPECRADAR_DATA_KEY_ANTIGAS`) ainda decifram;
* **a chave vem do ambiente ou de arquivo** (`SPECRADAR_DATA_KEY` / `_FILE`), 32 bytes em
  base64 url-safe. Nunca no repositório (gitleaks bloqueia no CI).

Formato do arquivo: ``SRENC1`` (6 bytes) | id da chave (8) | nonce (12) | cifrado+tag.

Uso pela linha de comando::

    python -m seguranca.cripto_local gerar-chave
    python -m seguranca.cripto_local cifrar   data/exports/relatorio.csv
    python -m seguranca.cripto_local decifrar data/exports/relatorio.csv.srenc
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from seguranca.segredos import carregar_segredos_de_arquivo

MAGICO = b"SRENC1"
TAMANHO_ID = 8
TAMANHO_NONCE = 12
EXTENSAO = ".srenc"


class ChaveAusente(RuntimeError):
    """`SPECRADAR_DATA_KEY` não definida ou inválida."""


class DadoCorrompido(ValueError):
    """Arquivo adulterado, truncado, de outro propósito (AAD) ou de chave desconhecida."""


def gerar_chave() -> str:
    """Chave nova de 256 bits, em base64 url-safe, pronta para o `.env`/secret."""
    return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode()


def _decodificar(chave_b64: str) -> bytes:
    try:
        chave = base64.urlsafe_b64decode(chave_b64.strip().encode())
    except (ValueError, TypeError) as exc:
        raise ChaveAusente("chave não é base64 válido") from exc
    if len(chave) != 32:
        raise ChaveAusente(f"chave tem {len(chave)} bytes; AES-256 exige 32")
    return chave


def id_da_chave(chave: bytes) -> bytes:
    return hashlib.sha256(chave).digest()[:TAMANHO_ID]


def chaves_do_ambiente() -> tuple[bytes, list[bytes]]:
    """(chave atual, [chaves antigas aceitas só para decifrar])."""
    carregar_segredos_de_arquivo()
    atual = os.environ.get("SPECRADAR_DATA_KEY", "")
    if not atual:
        raise ChaveAusente(
            "defina SPECRADAR_DATA_KEY (gere com `python -m seguranca.cripto_local gerar-chave`)"
        )
    antigas = [
        _decodificar(c) for c in os.environ.get("SPECRADAR_DATA_KEY_ANTIGAS", "").split(",") if c
    ]
    return _decodificar(atual), antigas


def cifrar(dados: bytes, *, aad: str, chave: bytes | None = None) -> bytes:
    chave = chave or chaves_do_ambiente()[0]
    nonce = os.urandom(TAMANHO_NONCE)
    cifrado = AESGCM(chave).encrypt(nonce, dados, aad.encode())
    return MAGICO + id_da_chave(chave) + nonce + cifrado


def decifrar(blob: bytes, *, aad: str, chaves: list[bytes] | None = None) -> bytes:
    if chaves is None:
        atual, antigas = chaves_do_ambiente()
        chaves = [atual, *antigas]
    if len(blob) < len(MAGICO) + TAMANHO_ID + TAMANHO_NONCE + 16 or not blob.startswith(MAGICO):
        raise DadoCorrompido("não é um arquivo cifrado pelo SpecRadar")
    inicio = len(MAGICO)
    ident = blob[inicio : inicio + TAMANHO_ID]
    nonce = blob[inicio + TAMANHO_ID : inicio + TAMANHO_ID + TAMANHO_NONCE]
    cifrado = blob[inicio + TAMANHO_ID + TAMANHO_NONCE :]
    chave = next((c for c in chaves if id_da_chave(c) == ident), None)
    if chave is None:
        raise DadoCorrompido("cifrado com uma chave que não está configurada")
    try:
        return AESGCM(chave).decrypt(nonce, cifrado, aad.encode())
    except InvalidTag as exc:
        raise DadoCorrompido("autenticação falhou: arquivo alterado ou AAD errado") from exc


def cifrar_arquivo(origem: Path, destino: Path | None = None, *, aad: str = "arquivo") -> Path:
    destino = destino or origem.with_name(origem.name + EXTENSAO)
    destino.write_bytes(cifrar(origem.read_bytes(), aad=aad))
    os.chmod(destino, 0o600)
    return destino


def decifrar_arquivo(origem: Path, destino: Path | None = None, *, aad: str = "arquivo") -> Path:
    if destino is None:
        destino = origem.with_name(origem.name.removesuffix(EXTENSAO))
    destino.write_bytes(decifrar(origem.read_bytes(), aad=aad))
    os.chmod(destino, 0o600)
    return destino


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seguranca.cripto_local")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("gerar-chave", help="imprime uma chave AES-256 nova")
    for nome in ("cifrar", "decifrar"):
        p = sub.add_parser(nome)
        p.add_argument("arquivo", type=Path)
        p.add_argument("--saida", type=Path)
        p.add_argument("--aad", default="arquivo")
    args = parser.parse_args(argv)

    if args.comando == "gerar-chave":
        print(gerar_chave())
        return 0
    try:
        if args.comando == "cifrar":
            saida = cifrar_arquivo(args.arquivo, args.saida, aad=args.aad)
        else:
            saida = decifrar_arquivo(args.arquivo, args.saida, aad=args.aad)
    except (ChaveAusente, DadoCorrompido) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    print(saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
