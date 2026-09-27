"""WP-08 — fetcher educado, cache, snapshots e replay.

Os quatro critérios de aceite da spec, com a rede sempre sob controle: o único teste que
sai para a internet é marcado `live` e fica fora do CI.

O teste de replay bloqueia o **socket** de propósito. "Não faz requisição" verificado por
mock é uma promessa sobre o mock; com o socket morto, é uma promessa sobre o processo.
"""

from __future__ import annotations

import json
import socket

import httpx
import pytest

from pipeline.fetch import browser, http, pdf
from pipeline.snapshots import (
    SnapshotMissing,
    escrever_snapshot,
    indexar_por_url,
    normalizar_url,
    snapshot_de_url,
    snapshots_por_url,
    todos_os_snapshots_de_url,
)
from pipeline.store import FIXTURES

RAPTOR = "https://www.ford.com.br/picapes/ranger-raptor/raptor-4wd-at/"
HILUX_PDF = "https://media.toyota.com.br/d400f124-b3ac-4d73-a885-5d6828812f11.pdf"


@pytest.fixture(autouse=True)
def _limpa_estado(monkeypatch, tmp_path):
    """Cada teste começa com contador, limitador e cache zerados."""
    http.zerar_contadores()
    monkeypatch.setattr(http, "CACHE_DIR", tmp_path / "cache")
    # sem espera real de 1 s entre requisições nos testes
    monkeypatch.setenv("FETCH_RATE_LIMIT_RPS", "1000")
    yield
    http.zerar_contadores()


@pytest.fixture
def sem_replay(monkeypatch):
    monkeypatch.setenv("REPLAY_MODE", "0")


@pytest.fixture
def sem_socket(monkeypatch):
    """Mata a criação de socket: nada neste processo consegue falar com a rede."""

    def proibido(*_a, **_k):
        raise AssertionError("houve tentativa de acesso à rede")

    monkeypatch.setattr(socket, "socket", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)


def _resposta(texto: str, status: int = 200, url: str = RAPTOR) -> httpx.Response:
    return httpx.Response(status, text=texto, request=httpx.Request("GET", url))


# ------------------------------------------------------- 1. robots.txt proíbe a rota
def test_robots_proibido_nao_faz_requisicao_a_rota(monkeypatch, sem_replay):
    """Critério de aceite: `blocked_by_robots` **sem** requisição à rota."""
    chamadas: list[str] = []

    def fake_get(url, **_kw):
        chamadas.append(url)
        if url.endswith("/robots.txt"):
            return _resposta("User-agent: *\nDisallow: /picapes/", url=url)
        raise AssertionError(f"não deveria ter buscado {url}")

    monkeypatch.setattr(httpx, "get", fake_get)
    resultado = http.fetch(RAPTOR)

    assert resultado.status == http.STATUS_BLOQUEADO_ROBOTS
    assert resultado.bloqueado
    assert not resultado.ok
    assert "robots.txt" in resultado.motivo
    assert chamadas == [f"https://{'www.ford.com.br'}/robots.txt"]


def test_robots_permite_e_a_pagina_e_buscada(monkeypatch, sem_replay):
    def fake_get(url, **_kw):
        if url.endswith("/robots.txt"):
            return _resposta("User-agent: *\nAllow: /", url=url)
        return _resposta("Potencia 397cv", url=url)

    monkeypatch.setattr(httpx, "get", fake_get)
    resultado = http.fetch(RAPTOR)
    assert resultado.status == http.STATUS_OK
    assert "397" in resultado.texto
    assert resultado.sha256


def test_robots_ausente_nao_bloqueia(monkeypatch, sem_replay):
    """RFC 9309: sem robots.txt legível, o padrão é permitir."""

    def fake_get(url, **_kw):
        if url.endswith("/robots.txt"):
            return _resposta("", status=404, url=url)
        return _resposta("ok", url=url)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert http.fetch(RAPTOR).status == http.STATUS_OK


def test_crawl_delay_do_dominio_e_respeitado(monkeypatch, sem_replay):
    def fake_get(url, **_kw):
        if url.endswith("/robots.txt"):
            return _resposta("User-agent: *\nCrawl-delay: 7", url=url)
        return _resposta("ok", url=url)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert http.crawl_delay(RAPTOR) == 7.0


# ------------------------------------------------------------------- 2. cache por dia
def test_segunda_chamada_no_mesmo_dia_vem_do_cache(monkeypatch, sem_replay):
    """Critério de aceite: duas chamadas, **uma** requisição de página."""
    paginas: list[str] = []

    def fake_get(url, **_kw):
        if url.endswith("/robots.txt"):
            return _resposta("User-agent: *\nAllow: /", url=url)
        paginas.append(url)
        return _resposta("Potencia 397cv", url=url)

    monkeypatch.setattr(httpx, "get", fake_get)

    primeira = http.fetch(RAPTOR)
    segunda = http.fetch(RAPTOR)

    assert primeira.status == http.STATUS_OK
    assert segunda.status == http.STATUS_CACHE
    assert segunda.de_cache
    assert segunda.texto == primeira.texto
    assert len(paginas) == 1, f"a página foi buscada {len(paginas)} vezes"


def test_cache_e_por_url_normalizada(monkeypatch, sem_replay):
    """Barra final e `www.` não podem virar duas entradas de cache."""
    assert http.caminho_de_cache(RAPTOR) == http.caminho_de_cache(
        "http://ford.com.br/picapes/ranger-raptor/raptor-4wd-at"
    )


def test_usar_cache_false_refaz_a_requisicao(monkeypatch, sem_replay):
    paginas: list[str] = []

    def fake_get(url, **_kw):
        if url.endswith("/robots.txt"):
            return _resposta("User-agent: *\nAllow: /", url=url)
        paginas.append(url)
        return _resposta("ok", url=url)

    monkeypatch.setattr(httpx, "get", fake_get)
    http.fetch(RAPTOR)
    http.fetch(RAPTOR, usar_cache=False)
    assert len(paginas) == 2


# ------------------------------------------------------- 3. replay sem rede nenhuma
def test_replay_resolve_por_snapshot_sem_socket(sem_socket):
    """Critério de aceite: em replay, o fetch nunca toca a rede."""
    resultado = http.fetch(RAPTOR)
    assert resultado.status == http.STATUS_REPLAY
    assert resultado.de_replay
    assert "397" in resultado.texto
    assert resultado.captured_at == "2026-09-01"


def test_replay_sem_snapshot_levanta_em_vez_de_ir_a_rede(sem_socket):
    """Critério de aceite: `SnapshotMissing`, **nunca** acesso à rede."""
    with pytest.raises(SnapshotMissing) as exc:
        http.fetch("https://exemplo.test/pagina-que-nao-existe")
    assert "sem snapshot" in str(exc.value)
    assert "não cai para a rede" in str(exc.value)


def test_escrever_snapshot_e_proibido_em_replay():
    """Replay é somente leitura: escrever ali contaminaria a régua."""
    with pytest.raises(RuntimeError, match="somente leitura"):
        escrever_snapshot(
            version_id="x", url_final="https://exemplo.test/a", texto="t", tier=1, tipo="pagina"
        )


def test_pdf_em_replay_devolve_o_texto_do_snapshot(sem_socket):
    texto, baixado = pdf.texto_do_pdf(HILUX_PDF)
    assert baixado.de_replay
    assert baixado.ok
    assert "204 / 3.400" in texto, "a linha de tabela do PDF tem de vir inteira"


# ------------------------------------------------------------------- 4. bloqueios
@pytest.mark.parametrize("codigo", [401, 403, 429])
def test_403_e_afins_viram_blocked_sem_retentativa(monkeypatch, sem_replay, codigo):
    """Bloqueio não se tenta de novo, e não se troca de user-agent."""
    paginas: list[str] = []

    def fake_get(url, **_kw):
        if url.endswith("/robots.txt"):
            return _resposta("User-agent: *\nAllow: /", url=url)
        paginas.append(url)
        return _resposta("nope", status=codigo, url=url)

    monkeypatch.setattr(httpx, "get", fake_get)
    resultado = http.fetch(RAPTOR)

    assert resultado.status == http.STATUS_BLOQUEADO
    assert resultado.http_status == codigo
    assert len(paginas) == 1, "bloqueio não se repete"
    assert "sem troca de user-agent" in resultado.motivo.lower()


def test_pagina_de_captcha_vira_blocked(monkeypatch, sem_replay):
    def fake_get(url, **_kw):
        if url.endswith("/robots.txt"):
            return _resposta("User-agent: *\nAllow: /", url=url)
        return _resposta("<html>Please solve the CAPTCHA to continue</html>", url=url)

    monkeypatch.setattr(httpx, "get", fake_get)
    resultado = http.fetch(RAPTOR)
    assert resultado.status == http.STATUS_BLOQUEADO
    assert "anti-bot" in resultado.motivo


def test_erro_transitorio_tenta_de_novo(monkeypatch, sem_replay):
    """500 é transitório: `docs/05` manda 2 tentativas com backoff."""
    monkeypatch.setattr(http, "BACKOFF_S", 0.0)
    paginas: list[str] = []

    def fake_get(url, **_kw):
        if url.endswith("/robots.txt"):
            return _resposta("User-agent: *\nAllow: /", url=url)
        paginas.append(url)
        if len(paginas) == 1:
            return _resposta("erro", status=503, url=url)
        return _resposta("Potencia 397cv", url=url)

    monkeypatch.setattr(httpx, "get", fake_get)
    resultado = http.fetch(RAPTOR)
    assert resultado.status == http.STATUS_OK
    assert len(paginas) == 2


def test_user_agent_vem_do_ambiente_e_e_identificado(monkeypatch):
    monkeypatch.setenv("SPECRADAR_USER_AGENT", "SpecRadar/9.9 (teste; contato: x@y.z)")
    assert http.user_agent() == "SpecRadar/9.9 (teste; contato: x@y.z)"
    monkeypatch.delenv("SPECRADAR_USER_AGENT")
    assert "SpecRadar" in http.user_agent()
    assert "contato" in http.user_agent()


# ------------------------------------------------------------------ snapshots
def test_normalizar_url_colapsa_grafias():
    for variante in (
        "https://www.ford.com.br/picapes/ranger-raptor/raptor-4wd-at/",
        "http://ford.com.br/picapes/ranger-raptor/raptor-4wd-at",
        "https://FORD.com.br/picapes/ranger-raptor/raptor-4wd-at/#specs",
    ):
        assert normalizar_url(variante) == "ford.com.br/picapes/ranger-raptor/raptor-4wd-at"


def test_indice_por_url_cobre_as_fixtures():
    indice = indexar_por_url([FIXTURES])
    assert len(indice) >= 8
    assert "ford.com.br/picapes/ranger-raptor/raptor-4wd-at" in indice
    assert "media.toyota.com.br/d400f124-b3ac-4d73-a885-5d6828812f11.pdf" in indice


def test_pagina_oficial_ganha_do_registro_de_evidencia():
    """Regressão: o índice devolvia o registro em vez da página.

    A página oficial da Hilux e o registro de evidência derivado dela apontam para a
    **mesma** URL. Sem desempate explícito a escolha caía na ordem de varredura do disco,
    e `texto_de_url` trocava a proveniência em silêncio.
    """
    url = "https://www.toyota.com.br/modelos/hilux-cabine-dupla"
    todos = todos_os_snapshots_de_url(url, [FIXTURES])
    assert len(todos) >= 2, "o caso só existe quando há mais de um snapshot para a URL"
    melhor = snapshot_de_url(url, [FIXTURES])
    assert melhor.tipo == "pagina_oficial"
    assert not melhor.e_registro_de_evidencia


def test_snapshots_por_url_ordena_do_melhor_para_o_pior():
    grupos = snapshots_por_url([FIXTURES])
    for lista in grupos.values():
        registros = [s.e_registro_de_evidencia for s in lista]
        # nenhum registro de evidência antes de uma captura de página da mesma data
        datas = [s.captured_at for s in lista]
        if len(set(datas)) == 1:
            assert registros == sorted(registros)


def test_escrever_snapshot_grava_texto_bruto_print_e_meta(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_MODE", "0")
    escrito = escrever_snapshot(
        version_id="teste_versao",
        url_final="https://exemplo.test/pagina",
        texto="Potencia 397cv",
        tier=1,
        tipo="pagina_oficial",
        bruto="<html>Potencia 397cv</html>",
        screenshot=b"\x89PNG fake",
        http_status=200,
        raiz=tmp_path,
    )
    assert (escrito.caminho / "page.md").read_text(encoding="utf-8") == "Potencia 397cv"
    assert (escrito.caminho / "raw.html").exists()
    assert (escrito.caminho / "full.png").read_bytes() == b"\x89PNG fake"
    meta = json.loads((escrito.caminho / "meta.json").read_text(encoding="utf-8"))
    assert meta["url_final"] == "https://exemplo.test/pagina"
    assert meta["sha256"] == escrito.sha256
    assert meta["tier"] == 1
    assert meta["screenshot_path"] == "full.png"
    # e o snapshot recém-escrito já é encontrável pela URL
    achado = snapshot_de_url("https://exemplo.test/pagina", [tmp_path])
    assert achado.texto == "Potencia 397cv"


def test_escrever_snapshot_rejeita_formato_que_ninguem_le(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_MODE", "0")
    with pytest.raises(ValueError, match=r"não é lido por store.py"):
        escrever_snapshot(
            version_id="v",
            url_final="https://exemplo.test/a",
            texto="t",
            tier=1,
            tipo="pagina_oficial",
            formato="conteudo.txt",
            raiz=tmp_path,
        )


def test_pdf_usa_doc_md_por_padrao(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_MODE", "0")
    escrito = escrever_snapshot(
        version_id="v",
        url_final="https://exemplo.test/ficha.pdf",
        texto="tabela",
        tier=1,
        tipo="pdf_oficial",
        bruto=b"%PDF-1.4 fake",
        raiz=tmp_path,
    )
    assert escrito.text_path == "doc.md"
    assert (escrito.caminho / "raw.pdf").exists()


# --------------------------------------------------------------------- navegador
def test_navegador_sem_extra_instalado_explica_o_que_falta(monkeypatch):
    monkeypatch.setenv("REPLAY_MODE", "0")
    if browser.disponivel():
        pytest.skip("extra `collect` instalado; este teste cobre a ausência dele")
    resultado = browser.fetch_browser("https://exemplo.test/x")
    assert not resultado.ok
    assert "crawl4ai-setup" in resultado.motivo
    assert "REPLAY_MODE" in resultado.motivo


def test_navegador_em_replay_manda_usar_o_snapshot():
    resultado = browser.fetch_browser(RAPTOR)
    assert not resultado.ok
    assert "REPLAY_MODE" in resultado.motivo


def test_seletores_de_cookie_cobrem_o_onetrust():
    """OneTrust é o banner usado pelas montadoras BR; sem fechá-lo o print sai tampado."""
    assert any("onetrust" in s.lower() for s in browser.SELETORES_DE_COOKIE)


# ------------------------------------------------------------------------- ao vivo
@pytest.mark.live
@pytest.mark.slow
def test_coleta_ao_vivo_da_raptor(monkeypatch):
    """Critério de aceite 4 — fora do CI (`-m "not live"`).

    Na noite de 08/09 este teste **não** podia passar com o fetcher HTTP: ford.com.br
    responde 403 a cliente HTTP simples, com robots.txt permitindo a rota. Com o extra
    `collect` instalado, o caminho é o navegador.
    """
    monkeypatch.setenv("REPLAY_MODE", "0")
    if browser.disponivel():
        pelo_navegador = browser.fetch_browser(RAPTOR)
        if pelo_navegador.status == http.STATUS_BLOQUEADO:
            pytest.skip(f"fonte bloqueada mesmo com navegador: {pelo_navegador.motivo}")
        assert pelo_navegador.ok, pelo_navegador.motivo
        assert "397" in pelo_navegador.markdown
        assert pelo_navegador.screenshot, "full.png tem de existir"
        return

    por_http = http.fetch(RAPTOR, usar_cache=False)
    if por_http.bloqueado:
        pytest.skip(
            f"fonte bloqueada ({por_http.http_status}) e o extra `collect` não está "
            f"instalado: {por_http.motivo}"
        )
    assert "397" in por_http.texto
