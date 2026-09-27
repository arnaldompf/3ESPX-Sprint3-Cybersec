"""Original alterado entre coleta e publicação bloqueia a transação."""

from types import SimpleNamespace

from pipeline.research.persistir import persistir_pesquisa
from pipeline.research.run import Fonte
from pipeline.snapshots import sha256_de


def test_changed_original_rejected_before_database_access(tmp_path):
    original = tmp_path / "original.pdf"
    original.write_bytes(b"%PDF changed")
    fonte = Fonte(
        "https://ford.com.br/ficha.pdf",
        1,
        "oficial",
        "acervo",
        raw_path=str(original),
        sha256_binario=sha256_de(b"%PDF previous"),
    )
    result = persistir_pesquisa(
        None,
        SimpleNamespace(fontes=[fonte]),
        run_id="test",
        marca="Ford",
        modelo="Ranger",
        versao="Limited",
        ano_modelo=2027,
    )
    assert result.version_id is None
    assert result.erros == [f"original com integridade inválida: {fonte.url}"]
