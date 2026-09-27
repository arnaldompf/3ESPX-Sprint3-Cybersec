"""Em replay, `snapshots` ganha linha — e é isso que faz o elo 5 mostrar a prova.

O buraco que estes testes fecham. O elo 5 do "Por quê?" mostra `sha256` e data de captura
lendo a tabela `snapshots` (`materiality_service._snapshots_de`). Em replay o texto vem de
fixture e **ninguém escrevia a linha**: `pipeline/snapshots.py:registrar_no_banco` só é
chamada na coleta ao vivo, que em replay é justamente o que não acontece.

Resultado, na demonstração: a cadeia do Fogo Amigo abria com *"nenhum snapshot gravado
para as URLs desta evidência"*. A mensagem era honesta e a ausência era desnecessária — o
`meta.json` de cada fixture **tem** o sha256 e a data, calculados por
`scripts/build_fixtures.py`.

Os testes guardam quatro coisas: a linha existe, o hash é o da fixture (não um inventado
na hora), rodar duas vezes não duplica, e a cadeia do "Por quê?" de fato exibe.
"""

from __future__ import annotations

import json

import pytest

RAPTOR = ("Ford", "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT")


@pytest.fixture
def base_semeada(schema_criado, monkeypatch):
    """Catálogo real do gabarito + a ficha da Raptor persistida, em replay."""
    monkeypatch.setenv("REPLAY_MODE", "1")
    monkeypatch.setenv("LLM_FAKE", "1")

    from api.app import seed
    from pipeline import run

    seed.main()
    contexto: list = []
    run.run(*RAPTOR, persistir=True, contexto=contexto)
    return contexto[0]


def _snapshots():
    from sqlmodel import select

    from api.app.db import session_scope
    from api.app.models import Snapshot

    with session_scope() as sessao:
        return [
            {
                "url": linha.url,
                "sha256": linha.sha256,
                "captured_at": linha.captured_at,
                "text_path": linha.text_path,
            }
            for linha in sessao.exec(select(Snapshot)).all()
        ]


def test_replay_grava_linha_de_snapshot_para_cada_fonte_com_hash(base_semeada):
    """Critério: em replay há linha em `snapshots`, e ela tem hash e data."""
    linhas = _snapshots()
    assert linhas, "replay tem de gravar snapshot; era isso que faltava para o elo 5"
    for linha in linhas:
        assert linha["sha256"], "snapshot sem sha256 é registro sem a informação que ele carrega"
        assert len(linha["sha256"]) == 64
        assert linha["captured_at"] is not None
        assert linha["text_path"], "o caminho do texto salvo permite reconferir no disco"


def test_o_hash_gravado_e_o_da_fixture_e_nao_um_inventado_na_hora(base_semeada):
    """O hash tem de vir do `meta.json`. Recalculá-lo aqui seria hash do nosso arquivo.

    A comparação é contra o **conjunto** de hashes declarados para a URL, e não contra um
    só: duas fixturas da Raptor compartilham a URL da página da versão — a captura
    (`ford_site_versao`) e o registro da coleta (`registro_evidencias_raptor`) — com
    textos e hashes diferentes. A tabela dedupa por `(url, captured_at)`, então grava uma;
    qual das duas é decisão da ordenação de `snapshots_de`, e prender o teste a uma delas
    seria prender-se a essa ordem.
    """
    from pipeline.store import FIXTURES, snapshots_de

    por_url: dict[str, set[str]] = {}
    for snap in snapshots_de("ford_ranger_raptor_2026", FIXTURES):
        if snap.url and snap.meta.get("sha256"):
            por_url.setdefault(snap.url, set()).add(snap.meta["sha256"])
    assert por_url, "a fixture precisa declarar sha256 no meta.json"

    conferidos = 0
    for linha in _snapshots():
        if linha["url"] in por_url:
            assert linha["sha256"] in por_url[linha["url"]], (
                f"o hash gravado para {linha['url']} não é nenhum dos declarados na fixture"
            )
            conferidos += 1
    assert conferidos, "nenhuma linha gravada corresponde a uma fixture da Raptor"


def test_rodar_duas_vezes_nao_duplica_a_linha(base_semeada, monkeypatch):
    """Dedupe por `(url, captured_at)` — o índice que a tabela tem e a pergunta da auditoria."""
    monkeypatch.setenv("REPLAY_MODE", "1")
    monkeypatch.setenv("LLM_FAKE", "1")
    antes = len(_snapshots())

    from pipeline import run

    contexto: list = []
    run.run(*RAPTOR, persistir=True, contexto=contexto)
    assert contexto[0].persistencia.snapshots == 0, "a segunda rodada não grava de novo"
    assert len(_snapshots()) == antes


def test_a_cadeia_do_porque_mostra_sha256_e_data_em_replay(base_semeada, monkeypatch):
    """Ponta a ponta: o elo 5 do Fogo Amigo deixa de dizer "nenhum snapshot gravado"."""
    monkeypatch.setenv("REPLAY_MODE", "1")
    monkeypatch.setenv("LLM_FAKE", "1")

    from sqlmodel import select

    from api.app.db import session_scope
    from api.app.models import Alert
    from api.app.services import materiality_service
    from pipeline import refresh

    refresh.main(watchlist=True)

    with session_scope() as sessao:
        alertas = sessao.exec(
            select(Alert).where(Alert.type == "referencia_interna_divergente")
        ).all()
        assert alertas, "o Fogo Amigo tem de produzir alerta nesta base"

        com_snapshot = 0
        for alerta in alertas:
            cadeia = materiality_service.trace(sessao, alerta)
            if not cadeia["snapshots"]:
                continue
            com_snapshot += 1
            (snap,) = cadeia["snapshots"][:1]
            assert snap["sha256"] and len(snap["sha256"]) == 64
            assert snap["captured_at"]
            # E o lado da evidência é o declarado, não o índice na lista (D-156).
            for evidencia in cadeia["evidencias"]:
                assert evidencia["lado"] in {"antes", "depois"}

        assert com_snapshot, (
            "nenhum alerta do Fogo Amigo trouxe snapshot: o elo 5 voltaria a dizer "
            "'nenhum snapshot gravado', que é o defeito que este teste guarda"
        )


def test_o_resultado_da_gravacao_conta_os_snapshots(base_semeada):
    """Gravação que não se conta é gravação que ninguém confere."""
    gravacao = base_semeada.persistencia
    assert gravacao.snapshots > 0
    assert "snapshots" in json.dumps(gravacao.to_dict())
