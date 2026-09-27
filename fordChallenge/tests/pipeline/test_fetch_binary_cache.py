"""Originais HTTP sobrevivem ao cache sem recodificação de texto para bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from pipeline import snapshots
from pipeline.fetch import http

URL = "https://fabricante.test/ficha"


@pytest.fixture(autouse=True)
def cache_isolado(monkeypatch, tmp_path):
    espera_original = http._espera_o_limite
    http.zerar_contadores()
    monkeypatch.setenv("REPLAY_MODE", "0")
    monkeypatch.setattr(http, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(http, "permitido_por_robots", lambda _url: True)
    monkeypatch.setattr(http, "_espera_o_limite", lambda _url: None)

    def rede_nao_dublada(*_args, **_kwargs):
        raise AssertionError("teste de cache não pode acessar rede real")

    monkeypatch.setattr(httpx, "get", rede_nao_dublada)
    yield espera_original
    http.zerar_contadores()


def resposta_dublada(monkeypatch, conteudo: bytes, content_type: str = "application/pdf"):
    chamadas = []

    def get(url, **_kwargs):
        chamadas.append(url)
        return httpx.Response(
            200,
            content=conteudo,
            headers={"Content-Type": content_type, "ETag": '"edicao-7"'},
            request=httpx.Request("GET", url + "/final"),
        )

    monkeypatch.setattr(httpx, "get", get)
    return chamadas


def escrever_legado(url=URL, **substituicoes):
    texto = "<html>Potência 250 cv</html>"
    dados = {
        "url": url,
        "url_final": url,
        "http_status": 200,
        "captured_at": "2026-09-14",
        "texto": texto,
        "sha256": hashlib.sha256(texto.encode()).hexdigest(),
    }
    dados.update(substituicoes)
    if "texto" in substituicoes and "sha256" not in substituicoes:
        dados["sha256"] = hashlib.sha256(dados["texto"].encode()).hexdigest()
    arquivo = http.caminho_de_cache(url)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return arquivo


@pytest.mark.parametrize(
    ("conteudo", "content_type", "mime_type"),
    [
        (b"%PDF-1.7\n" + bytes(range(256)) + b"\n%%EOF", "application/pdf", "application/pdf"),
        (bytes(range(256)), "application/octet-stream", "application/octet-stream"),
        (b"<html>Pot\xeancia: 250 cv</html>", "text/html; charset=iso-8859-1", "text/html"),
        (b"", "application/octet-stream", "application/octet-stream"),
    ],
    ids=["pdf-binary", "arbitrary", "html-latin1", "empty"],
)
def test_roundtrip_preserva_bytes_headers_mime_e_dois_hashes(
    monkeypatch, conteudo, content_type, mime_type
):
    chamadas = resposta_dublada(monkeypatch, conteudo, content_type)
    primeiro = http.fetch(URL)
    segundo = http.fetch(URL)

    assert segundo.conteudo == conteudo == primeiro.conteudo
    assert segundo.headers == primeiro.headers
    assert segundo.headers["content-type"] == content_type
    assert segundo.headers["etag"] == '"edicao-7"'
    assert primeiro.mime_type == segundo.mime_type == mime_type
    assert primeiro.sha256_binario == segundo.sha256_binario == hashlib.sha256(conteudo).hexdigest()
    assert primeiro.sha256 == segundo.sha256 == hashlib.sha256(primeiro.texto.encode()).hexdigest()
    assert segundo.texto == primeiro.texto
    assert segundo.url_final == primeiro.url_final == URL + "/final"
    assert segundo.captured_at == primeiro.captured_at
    assert segundo.http_status == 200
    assert segundo.status == http.STATUS_CACHE and segundo.de_cache
    assert chamadas == [URL]


def test_blob_e_enderecado_por_hash_e_compartilhado_entre_urls(monkeypatch):
    original = b"%PDF-1.7\n\x80\xff\x00\n%%EOF"
    resposta_dublada(monkeypatch, original)
    primeiro = http.fetch(URL)
    segundo = http.fetch(URL + "-espelho")
    blob = http.caminho_de_blob_cache(hashlib.sha256(original).hexdigest())

    assert blob.read_bytes() == original
    assert blob.stem == primeiro.sha256_binario == segundo.sha256_binario
    assert list((http.CACHE_DIR / "blobs").rglob("*.bin")) == [blob]
    assert http.caminho_de_cache(URL) != http.caminho_de_cache(URL + "-espelho")


@pytest.mark.parametrize(
    "dano", ["ausente", "bytes", "tamanho", "texto", "hash_textual", "hash_binario", "mime"]
)
def test_cache_integro_e_obrigatorio_para_um_hit(monkeypatch, dano):
    resposta_dublada(monkeypatch, b"%PDF-1.7\n\xff\x80\n%%EOF")
    primeiro = http.fetch(URL)
    arquivo = http.caminho_de_cache(URL)
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    blob = http.caminho_de_blob_cache(primeiro.sha256_binario)
    if dano == "ausente":
        blob.unlink()
    elif dano == "bytes":
        # O tamanho continua correto: o hash precisa detectar a adulteração.
        blob.write_bytes(primeiro.conteudo[:-1] + b"X")
    elif dano == "tamanho":
        dados["tamanho_binario"] += 1
    elif dano == "texto":
        dados["texto"] = "texto adulterado"
    elif dano == "hash_textual":
        dados["sha256"] = "0" * 64
    elif dano == "hash_binario":
        dados["sha256_binario"] = "../../arquivo-externo"
    elif dano == "mime":
        dados["mime_type"] = "text/html"
    arquivo.write_text(json.dumps(dados), encoding="utf-8")

    assert http._le_cache(URL) is None


def test_blob_corrompido_e_reposto_por_nova_resposta_sem_recodificacao(monkeypatch):
    original = b"%PDF-1.7\n\x81\x82\xff\n%%EOF"
    chamadas = resposta_dublada(monkeypatch, original)
    primeiro = http.fetch(URL)
    http.caminho_de_blob_cache(primeiro.sha256_binario).write_bytes(b"corrompido")

    segundo = http.fetch(URL)
    terceiro = http.fetch(URL)

    assert segundo.status == http.STATUS_OK
    assert terceiro.status == http.STATUS_CACHE
    assert segundo.conteudo == terceiro.conteudo == original
    assert chamadas == [URL, URL]


@pytest.mark.parametrize("com_headers", [True, False])
def test_html_legado_continua_textual_sem_fabricar_original(com_headers):
    if com_headers:
        escrever_legado(headers={"Content-Type": "text/html; charset=utf-8", "ETag": "v1"})
    else:
        escrever_legado()
    resultado = http.fetch(URL)

    assert resultado.status == http.STATUS_CACHE
    assert resultado.texto == "<html>Potência 250 cv</html>"
    assert resultado.conteudo == b""
    assert resultado.sha256_binario == ""
    assert resultado.mime_type == ("text/html" if com_headers else "")
    if com_headers:
        assert resultado.headers["etag"] == "v1"
    else:
        assert resultado.headers == {}


@pytest.mark.parametrize(
    ("url", "metadados"),
    [
        (URL + ".PDF?download=1", {}),
        (URL, {"url_final": URL + ".pdf"}),
        (URL, {"headers": {"Content-Type": "application/pdf"}}),
        (URL, {"mime_type": "application/pdf"}),
        (URL, {"texto": "%PDF-1.7\ntexto já danificado"}),
    ],
)
def test_pdf_legado_sem_blob_exige_nova_coleta(url, metadados):
    escrever_legado(url, **metadados)
    assert http._le_cache(url) is None


@pytest.mark.parametrize("metadados", [[], None, {"texto": 123}, {"cache_version": 999}])
def test_manifesto_invalido_e_miss_em_vez_de_excecao(metadados):
    arquivo = http.caminho_de_cache(URL)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(metadados), encoding="utf-8")
    assert http._le_cache(URL) is None


def test_manifesto_de_outra_url_nao_vira_hit():
    escrever_legado(url_final=URL + "/redirecionado", url="https://outra.test/ficha")
    origem = http.caminho_de_cache("https://outra.test/ficha")
    destino = http.caminho_de_cache(URL)
    destino.write_bytes(origem.read_bytes())
    assert http._le_cache(URL) is None


def test_falha_atomica_de_manifesto_preserva_cache_anterior(monkeypatch):
    original = b"%PDF-1.7\noriginal\n%%EOF"
    resposta_dublada(monkeypatch, original)
    http.fetch(URL)
    manifesto = http.caminho_de_cache(URL)
    antes = manifesto.read_bytes()
    substituir = http.os.replace

    def falhar_manifesto(origem, destino):
        if Path(destino) == manifesto:
            raise OSError("falha de disco simulada")
        return substituir(origem, destino)

    monkeypatch.setattr(http.os, "replace", falhar_manifesto)
    with pytest.raises(OSError, match="falha de disco simulada"):
        http._grava_cache(
            http.Resultado(url=URL, status=http.STATUS_OK, texto="novo", conteudo=b"novo")
        )

    assert manifesto.read_bytes() == antes
    assert http._le_cache(URL).conteudo == original
    assert not list(http.CACHE_DIR.rglob("*.tmp"))


def test_falha_atomica_de_blob_nao_publica_manifesto_parcial(monkeypatch):
    def falhar_substituicao(*_args):
        raise OSError("falha no blob")

    monkeypatch.setattr(http.os, "replace", falhar_substituicao)
    with pytest.raises(OSError, match="falha no blob"):
        http._grava_cache(
            http.Resultado(url=URL, status=http.STATUS_OK, texto="PDF", conteudo=b"%PDF-1.7")
        )

    assert not http.caminho_de_cache(URL).exists()
    assert not list(http.CACHE_DIR.rglob("*.tmp"))
    assert not list(http.CACHE_DIR.rglob("*.bin"))


@pytest.mark.parametrize(
    ("rps", "crawl_delay", "espera"), [("1000", None, 1.0), ("0.25", None, 4.0), ("1000", 7, 7.0)]
)
def test_limite_nunca_supera_uma_requisicao_por_segundo(
    monkeypatch, cache_isolado, rps, crawl_delay, espera
):
    pausas = []
    monkeypatch.setenv("FETCH_RATE_LIMIT_RPS", rps)
    monkeypatch.setattr(http.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(http.deadline, "sleep", pausas.append)
    monkeypatch.setattr(http, "crawl_delay", lambda _url: crawl_delay)
    http._ultimo_acesso["fabricante.test"] = 100.0

    cache_isolado(URL)

    assert pausas == [espera]


def test_cache_miss_respeita_prazo_total_antes_de_acessar_rede():
    with http.deadline.budget(0), pytest.raises(TimeoutError, match="orçamento total"):
        http.fetch(URL)


@pytest.mark.parametrize("estado_original", ["integro", "corrompido", "ausente"])
def test_replay_recupera_so_original_verificado_do_snapshot(monkeypatch, tmp_path, estado_original):
    original = b"%PDF-1.7\n\x80\xff\x00\n%%EOF"
    texto = "Potência: 250 cv"
    raiz = tmp_path / "snapshots"
    escrito = snapshots.escrever_snapshot(
        version_id="v1",
        url_final=URL,
        texto=texto,
        tier=1,
        tipo="pdf_oficial",
        bruto=original,
        extras={"headers": {"Content-Type": "application/pdf", "ETag": "edicao-1"}},
        raiz=raiz,
    )
    bruto = escrito.caminho / "raw.pdf"
    if estado_original == "corrompido":
        bruto.write_bytes(original[:-1] + b"X")
    elif estado_original == "ausente":
        bruto.unlink()
    monkeypatch.setenv("REPLAY_MODE", "1")
    monkeypatch.setattr(http, "snapshot_de_url", lambda url: snapshots.snapshot_de_url(url, [raiz]))

    resultado = http.fetch(URL)

    assert resultado.status == http.STATUS_REPLAY and resultado.de_replay
    assert resultado.texto == texto
    assert resultado.sha256 == hashlib.sha256(texto.encode()).hexdigest()
    assert resultado.headers == {"content-type": "application/pdf", "etag": "edicao-1"}
    if estado_original == "integro":
        assert resultado.conteudo == original
        assert resultado.sha256_binario == hashlib.sha256(original).hexdigest()
        assert resultado.mime_type == "application/pdf"
    else:
        assert resultado.conteudo == b""
        assert resultado.sha256_binario == resultado.mime_type == ""
    assert not http.CACHE_DIR.exists()
