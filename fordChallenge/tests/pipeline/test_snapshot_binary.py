"""O original e sua identidade sobrevivem a snapshots e replay."""

import json

import pytest

from pipeline import snapshots
from pipeline.store import Snapshot

RAW = b"%PDF-1.7\n\xff\x00\n%%EOF"


@pytest.fixture
def write(monkeypatch, tmp_path):
    monkeypatch.setenv("REPLAY_MODE", "0")
    monkeypatch.setattr(snapshots, "agora_iso", lambda: "2026-09-15T01-00-00Z")

    def create(raw=RAW, extras=None):
        return snapshots.escrever_snapshot(
            version_id="ranger",
            url_final="https://www.ford.com.br/ficha.pdf",
            texto="same extracted text",
            tier=1,
            tipo="pdf_oficial",
            bruto=raw,
            raiz=tmp_path,
            extras=extras,
        )

    return create


def snapshot(written):
    meta = json.loads((written.caminho / "meta.json").read_text(encoding="utf-8"))
    return Snapshot("ranger", "source", "2026-09-15", written.caminho, meta)


def test_snapshot_preserves_binary_hash_separately(write):
    snap = snapshot(write())
    assert snap.meta["sha256"] == snapshots.sha256_de("same extracted text")
    assert snap.meta["sha256_binario"] == snapshots.sha256_de(RAW)
    assert snapshots.conteudo_original(snap) == (
        RAW,
        snapshots.sha256_de(RAW),
        "application/pdf",
    )


def test_different_original_same_text_never_overwrites(write):
    first = write()
    second = write(RAW + b"\nnew edition")
    assert first.caminho != second.caminho
    assert (first.caminho / "raw.pdf").read_bytes() == RAW


def test_corrupt_original_is_not_returned(write):
    snap = snapshot(write())
    (snap.caminho / "raw.pdf").write_bytes(b"%PDF corrupted")
    assert snapshots.conteudo_original(snap) == (b"", "", "")


def test_raw_path_cannot_escape_snapshot(write, tmp_path):
    snap = snapshot(write())
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(RAW)
    snap.meta["raw_path"] = str(outside.resolve())
    assert snapshots.conteudo_original(snap) == (b"", "", "")


def test_extras_cannot_override_original_integrity(write):
    snap = snapshot(write(extras={"sha256_binario": "wrong", "raw_path": "../wrong.pdf"}))
    assert snap.meta["sha256_binario"] == snapshots.sha256_de(RAW)
    assert snap.meta["raw_path"] == "raw.pdf"
