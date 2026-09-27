"""A evidência gravada aponta para o snapshot, e carrega a data da coleta.

O defeito medido em 11/09/2026 (QA-BUG-03 e QA-BUG-04), com a base da demo recém-montada:

* **todas** as 152 linhas de `evidences` tinham `snapshot_id` nulo, embora 150 delas
  tivessem uma linha em `snapshots` com exatamente a mesma URL. `spec_assembler.montar`
  monta `sources_checked` a partir de `evidence.snapshot_id`, então o contador
  **"Fontes consultadas"** do topo da ficha marcava **0** nas cinco fichas — ao lado de
  "30 campos com valor" e de trinta botões "ver evidência" que abrem com URL e citação;
* `evidences.captured_at` caía no padrão da coluna, que é a hora da **gravação**. A gaveta
  de evidência dizia "Coletado em: 11/09/2026" para uma página salva em **01/09/2026** — e
  o elo 5 do "Por quê?" mostrava as duas datas lado a lado, a errada por cima da certa.

A causa é a mesma nas duas: `pipeline/persist.py` montava `EvidenceRow` sem esses dois
campos. O `snapshot_id` que a evidência carrega é o identificador da **fixture**, não a
chave da tabela `snapshots`; a ligação que existe é a URL.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from pipeline.persist import indice_de_snapshots


@pytest.fixture
def sessao(tmp_path: Path):
    from api.app.models import Snapshot, Source  # noqa: F401  (registra as tabelas)

    motor = create_engine(f"sqlite:///{(tmp_path / 'snap.db').as_posix()}")
    SQLModel.metadata.create_all(motor)
    with Session(motor) as s:
        yield s


def _snapshot(s: Session, url: str, captured_at: dt.datetime, sha: str) -> str:
    from sqlmodel import select

    from api.app.models import Snapshot, Source, SourceStatus

    # `sources.url` é única: duas capturas da mesma página compartilham a fonte.
    fonte = s.exec(select(Source).where(Source.url == url)).first()
    if fonte is None:
        fonte = Source(
            url=url,
            tipo="html",
            tier=1,
            dominio="exemplo.com.br",
            robots_ok=True,
            status=SourceStatus.ATIVA.value,
            ultima_checagem_em=captured_at,
        )
        s.add(fonte)
        s.flush()
    linha = Snapshot(
        source_id=fonte.id,
        version_id=None,
        url=url,
        captured_at=captured_at,
        text_path="/nada",
        sha256=sha,
    )
    s.add(linha)
    s.flush()
    return linha.id


URL = "https://www.ford.com.br/picapes/ranger-raptor/raptor-4wd-at/"


def test_a_url_da_evidencia_encontra_o_snapshot(sessao: Session) -> None:
    capturado = dt.datetime(2026, 9, 1)
    esperado = _snapshot(sessao, URL, capturado, "a" * 64)

    indice = indice_de_snapshots(sessao, [URL])

    assert indice[URL] == (esperado, capturado)


def test_url_sem_snapshot_nao_inventa_ligacao(sessao: Session) -> None:
    _snapshot(sessao, URL, dt.datetime(2026, 9, 1), "a" * 64)

    indice = indice_de_snapshots(sessao, [URL, "https://outra.example.com/ficha"])

    assert "https://outra.example.com/ficha" not in indice


def test_duas_capturas_da_mesma_url_usam_a_mais_recente(sessao: Session) -> None:
    """A tabela guarda uma linha por `(url, captured_at)`: a auditoria pergunta 'o que
    esta URL dizia naquele dia'. A ficha mostra o estado **de agora**, então a evidência
    aponta para a captura mais nova."""
    _snapshot(sessao, URL, dt.datetime(2026, 9, 1), "a" * 64)
    nova = _snapshot(sessao, URL, dt.datetime(2026, 9, 10), "b" * 64)

    indice = indice_de_snapshots(sessao, [URL])

    assert indice[URL] == (nova, dt.datetime(2026, 9, 10))


def test_sem_urls_nao_consulta_o_banco(sessao: Session) -> None:
    assert indice_de_snapshots(sessao, []) == {}


def test_captura_mais_recente_de_outra_versao_nao_substitui_prova(sessao: Session) -> None:
    from api.app.models import Snapshot

    earlier = dt.datetime(2026, 9, 1)
    own = _snapshot(sessao, URL, earlier, "a" * 64)
    other = _snapshot(sessao, URL, dt.datetime(2026, 9, 10), "b" * 64)
    sessao.get(Snapshot, own).version_id = "limited"
    sessao.get(Snapshot, other).version_id = "xlt"
    sessao.flush()

    assert indice_de_snapshots(sessao, [URL], version_id="limited") == {URL: (own, earlier)}
    assert indice_de_snapshots(sessao, [URL], version_id="raptor") == {}
