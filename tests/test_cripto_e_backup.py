"""Criptografia local (AES-256-GCM) e o ciclo de backup cifrado → verificação → restauração."""

from __future__ import annotations

import sqlite3
import stat

import pytest

from seguranca import backup
from seguranca.cripto_local import (
    ChaveAusente,
    DadoCorrompido,
    cifrar,
    cifrar_arquivo,
    decifrar,
    decifrar_arquivo,
    gerar_chave,
)


@pytest.fixture
def chave(monkeypatch):
    valor = gerar_chave()
    monkeypatch.setenv("SPECRADAR_DATA_KEY", valor)
    monkeypatch.delenv("SPECRADAR_DATA_KEY_ANTIGAS", raising=False)
    return valor


def test_ida_e_volta(chave):
    blob = cifrar(b"e-mail: vendedor@concessionaria.com.br", aad="exportacao")

    assert b"vendedor" not in blob
    assert decifrar(blob, aad="exportacao") == b"e-mail: vendedor@concessionaria.com.br"


def test_mesma_entrada_gera_cifrados_diferentes(chave):
    assert cifrar(b"x", aad="a") != cifrar(b"x", aad="a")  # nonce novo a cada vez


def test_um_byte_alterado_e_detectado(chave):
    blob = bytearray(cifrar(b"dado", aad="a"))
    blob[-1] ^= 0x01

    with pytest.raises(DadoCorrompido):
        decifrar(bytes(blob), aad="a")


def test_aad_amarra_o_proposito(chave):
    with pytest.raises(DadoCorrompido):
        decifrar(cifrar(b"dado", aad="backup"), aad="exportacao")


def test_rotacao_de_chave(chave, monkeypatch):
    antigo = cifrar(b"de antes da rotacao", aad="a")
    monkeypatch.setenv("SPECRADAR_DATA_KEY", gerar_chave())

    with pytest.raises(DadoCorrompido):
        decifrar(antigo, aad="a")

    monkeypatch.setenv("SPECRADAR_DATA_KEY_ANTIGAS", chave)
    assert decifrar(antigo, aad="a") == b"de antes da rotacao"


def test_sem_chave_nao_cifra(monkeypatch):
    monkeypatch.delenv("SPECRADAR_DATA_KEY", raising=False)
    monkeypatch.delenv("SPECRADAR_DATA_KEY_FILE", raising=False)

    with pytest.raises(ChaveAusente):
        cifrar(b"x", aad="a")


def test_chave_por_arquivo_docker_secret(monkeypatch, tmp_path):
    segredo = tmp_path / "data_key"
    segredo.write_text(gerar_chave())
    monkeypatch.delenv("SPECRADAR_DATA_KEY", raising=False)
    monkeypatch.setenv("SPECRADAR_DATA_KEY_FILE", str(segredo))

    assert decifrar(cifrar(b"ok", aad="a"), aad="a") == b"ok"


def test_arquivo_cifrado_fica_so_para_o_dono(chave, tmp_path):
    origem = tmp_path / "relatorio.csv"
    origem.write_text("modelo;preco\nRanger;300000\n")

    cifrado = cifrar_arquivo(origem)
    origem.unlink()

    assert stat.S_IMODE(cifrado.stat().st_mode) == 0o600
    assert decifrar_arquivo(cifrado).read_text().startswith("modelo;preco")


def _banco(caminho) -> str:
    conexao = sqlite3.connect(caminho)
    conexao.execute("create table users (email text)")
    conexao.execute("insert into users values ('gestor@specradar.example.com')")
    conexao.commit()
    conexao.close()
    return f"sqlite:///{caminho}"


def test_backup_verifica_e_restaura(chave, tmp_path):
    url = _banco(tmp_path / "producao.db")

    arquivo = backup.criar(url, tmp_path / "backups")
    manifesto = backup.verificar(arquivo)
    assert manifesto["algoritmo"] == "AES-256-GCM"
    assert b"gestor@" not in arquivo.read_bytes()

    restaurado = tmp_path / "restaurado.db"
    backup.restaurar(arquivo, f"sqlite:///{restaurado}")
    linhas = sqlite3.connect(restaurado).execute("select email from users").fetchall()
    assert linhas == [("gestor@specradar.example.com",)]


def test_backup_adulterado_nao_restaura(chave, tmp_path):
    arquivo = backup.criar(_banco(tmp_path / "p.db"), tmp_path / "backups")
    conteudo = bytearray(arquivo.read_bytes())
    conteudo[40] ^= 0xFF
    arquivo.write_bytes(bytes(conteudo))

    with pytest.raises(DadoCorrompido):
        backup.verificar(arquivo)


def test_retencao_mantem_os_mais_novos(chave, tmp_path):
    destino = tmp_path / "backups"
    destino.mkdir()
    for dia in ("20260901", "20260902", "20260903"):
        (destino / f"specradar-{dia}T000000Z.srbak").write_bytes(b"x")
        (destino / f"specradar-{dia}T000000Z.json").write_text("{}")

    removidos = backup.aplicar_retencao(destino, manter=2)

    assert [r.name for r in removidos] == ["specradar-20260901T000000Z.srbak"]
    assert not (destino / "specradar-20260901T000000Z.json").exists()
