"""Fetcher HTTP educado: robots.txt, 1 req/s por domínio, cache por dia, replay.

As quatro regras de `docs/02` ADR-7 e `docs/05` (Fontes e tiers) viraram código aqui, e
nenhuma delas é opcional:

1. **robots.txt honrado** — consultado antes de qualquer requisição à rota. Proibido
   devolve `Resultado(status="blocked_by_robots")` **sem** fazer a requisição.
2. **≤ 1 req/s por domínio**, contado em processo, com `FETCH_RATE_LIMIT_RPS` ajustável.
3. **User-agent identificado** de `SPECRADAR_USER_AGENT`, com contato.
4. **403/429/CAPTCHA → `blocked`**, e para aí. Nunca troca de UA, nunca rotação de IP,
   nunca retentativa em cascata. Bloqueio é um estado do dado, não um obstáculo a vencer.

Mais duas propriedades que a demo exige:

* **cache por (URL, dia)** em `data/cache/` — duas chamadas no mesmo dia fazem **uma**
  requisição;
* **`REPLAY_MODE=1` corta a rede** — todo fetch resolve para o snapshot salvo, e a
  ausência de snapshot levanta `SnapshotMissing` em vez de sair para a internet.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import urllib.robotparser
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from pipeline import deadline
from pipeline.snapshots import SnapshotMissing, conteudo_original, normalizar_url, snapshot_de_url

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data" / "cache"
CACHE_VERSION = 2

TIMEOUT_PADRAO = 30.0
#: `docs/05`: "retry 2x com backoff". Vale para erro **transitório**, nunca para bloqueio.
TENTATIVAS = 2
BACKOFF_S = 2.0

#: Estados possíveis de um fetch. Cada um é um estado do dado, não um erro de programa.
STATUS_OK = "ok"
STATUS_CACHE = "cache"
STATUS_REPLAY = "replay"
STATUS_BLOQUEADO_ROBOTS = "blocked_by_robots"
STATUS_BLOQUEADO = "blocked"
STATUS_ERRO = "erro"

_ultimo_acesso: dict[str, float] = {}
_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
#: contador de requisições de rede efetivamente feitas — o teste de cache lê daqui
_requisicoes: dict[str, int] = {"total": 0}


class RedeProibidaEmReplay(RuntimeError):
    """Tentativa de acessar a rede com `REPLAY_MODE=1`."""


@dataclass
class Resultado:
    """O que voltou de um fetch, com o motivo sempre explícito."""

    url: str
    status: str
    texto: str = ""
    conteudo: bytes = b""
    http_status: int | None = None
    url_final: str = ""
    motivo: str = ""
    de_cache: bool = False
    de_replay: bool = False
    captured_at: str = ""
    sha256: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    #: O hash textual acima continua sendo SHA-256 de texto codificado em UTF-8.
    sha256_binario: str = ""
    mime_type: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {STATUS_OK, STATUS_CACHE, STATUS_REPLAY}

    @property
    def bloqueado(self) -> bool:
        return self.status in {STATUS_BLOQUEADO, STATUS_BLOQUEADO_ROBOTS}


# ------------------------------------------------------------------------ ambiente
def modo_replay() -> bool:
    return os.environ.get("REPLAY_MODE", "").strip() in {"1", "true", "True"}


def user_agent() -> str:
    return os.environ.get(
        "SPECRADAR_USER_AGENT", "SpecRadar/0.1 (FIAP Challenge Ford; contato: nao-informado)"
    )


def requisicoes_feitas() -> int:
    """Quantas requisições de rede saíram deste processo (o cache tem de manter em 1)."""
    return _requisicoes["total"]


def zerar_contadores() -> None:
    """Reinicia contador, limitador e cache de robots — usado entre testes."""
    _requisicoes["total"] = 0
    _ultimo_acesso.clear()
    _robots_cache.clear()


# -------------------------------------------------------------------------- robots
def _robots(dominio: str, esquema: str) -> urllib.robotparser.RobotFileParser | None:
    if dominio in _robots_cache:
        return _robots_cache[dominio]
    parser = urllib.robotparser.RobotFileParser()
    try:
        _requisicoes["total"] += 1
        resposta = httpx.get(
            f"{esquema}://{dominio}/robots.txt",
            timeout=deadline.timeout(10.0),
            headers={"User-Agent": user_agent()},
        )
        if resposta.status_code >= 400:
            # Sem robots.txt legível o padrão do RFC 9309 é permitir.
            _robots_cache[dominio] = None
            return None
        parser.parse(resposta.text.splitlines())
    except httpx.HTTPError:
        _robots_cache[dominio] = None
        return None
    _robots_cache[dominio] = parser
    return parser


def permitido_por_robots(url: str) -> bool:
    partes = urlparse(url)
    parser = _robots(partes.netloc, partes.scheme or "https")
    return True if parser is None else parser.can_fetch(user_agent(), url)


def crawl_delay(url: str) -> float | None:
    """`Crawl-delay` do robots.txt, quando o domínio declara um."""
    partes = urlparse(url)
    parser = _robots(partes.netloc, partes.scheme or "https")
    if parser is None:
        return None
    valor = parser.crawl_delay(user_agent())
    return float(valor) if valor is not None else None


# ---------------------------------------------------------------------- rate limit
def _espera_o_limite(url: str) -> None:
    dominio = urlparse(url).netloc
    rps = float(os.environ.get("FETCH_RATE_LIMIT_RPS", "1") or 1)
    intervalo = 1.0 / min(1.0, max(0.01, rps))
    # Domínio que pede mais devagar manda: respeitar Crawl-delay é parte de ser educado.
    declarado = crawl_delay(url)
    if declarado:
        intervalo = max(intervalo, declarado)
    anterior = _ultimo_acesso.get(dominio)
    if anterior is not None:
        falta = intervalo - (time.monotonic() - anterior)
        if falta > 0:
            deadline.sleep(falta)
    _ultimo_acesso[dominio] = time.monotonic()


# --------------------------------------------------------------------------- cache
def caminho_de_cache(url: str, dia: str | None = None) -> Path:
    """Cache por **(URL, dia)**: a mesma página no mesmo dia é uma requisição só."""
    dia = dia or datetime.now(UTC).strftime("%Y-%m-%d")
    chave = hashlib.sha256(normalizar_url(url).encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / dia / f"{chave}.json"


def _e_sha256(valor: object) -> bool:
    return (
        isinstance(valor, str) and len(valor) == 64 and all(c in "0123456789abcdef" for c in valor)
    )


def caminho_de_blob_cache(sha256_binario: str) -> Path:
    """Original HTTP, compartilhado entre URLs e dias, endereçado por hash completo."""
    if not _e_sha256(sha256_binario):
        raise ValueError("SHA-256 binário inválido")
    return CACHE_DIR / "blobs" / sha256_binario[:2] / f"{sha256_binario}.bin"


def _headers_normalizados(valor: object) -> dict[str, str] | None:
    if not isinstance(valor, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in valor.items()
    ):
        return None
    return {k.lower(): v for k, v in valor.items()}


def _mime_type(content_type: str) -> str:
    return content_type.partition(";")[0].strip().lower()


def _legado_pdf(url: str, url_final: str, texto: str, mime_type: str) -> bool:
    return (
        mime_type in {"application/pdf", "application/x-pdf"}
        or any(urlparse(u).path.lower().endswith(".pdf") for u in (url, url_final))
        or texto.lstrip().startswith("%PDF-")
    )


def _le_cache(url: str) -> Resultado | None:
    """Só usa o cache novo se texto e original passarem na verificação de integridade.

    O formato antigo permite reaproveitar HTML textual. PDF antigo não possui os bytes
    verificáveis e exige nova coleta; recodificar o texto não recupera o documento.
    """
    arquivo = caminho_de_cache(url)
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        if not isinstance(dados, dict):
            return None
        versao = dados.get("cache_version", 1)
        if type(versao) is not int or versao not in {1, CACHE_VERSION}:
            return None
        texto = dados.get("texto")
        url_gravada = dados.get("url")
        url_final = dados.get("url_final", url)
        captured_at = dados.get("captured_at", "")
        if not all(isinstance(v, str) for v in (texto, url_gravada, url_final, captured_at)):
            return None
        if normalizar_url(url_gravada) != normalizar_url(url):
            return None
        http_status = dados.get("http_status")
        if http_status is not None and type(http_status) is not int:
            return None
        headers = _headers_normalizados(dados.get("headers", {}))
        if headers is None:
            return None
        mime_type = dados.get("mime_type", _mime_type(headers.get("content-type", "")))
        if not isinstance(mime_type, str) or mime_type != _mime_type(mime_type):
            return None
        if "content-type" in headers and mime_type != _mime_type(headers["content-type"]):
            return None
        sha256 = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        sha256_gravado = dados.get("sha256", "")
        if not isinstance(sha256_gravado, str) or (sha256_gravado and sha256_gravado != sha256):
            return None
        conteudo = b""
        sha256_binario = ""
        if versao == CACHE_VERSION:
            sha256_binario = dados.get("sha256_binario")
            tamanho = dados.get("tamanho_binario")
            if (
                sha256_gravado != sha256
                or not _e_sha256(sha256_binario)
                or type(tamanho) is not int
                or tamanho < 0
                or "headers" not in dados
                or "mime_type" not in dados
            ):
                return None
            conteudo = caminho_de_blob_cache(sha256_binario).read_bytes()
            if len(conteudo) != tamanho or hashlib.sha256(conteudo).hexdigest() != sha256_binario:
                return None
        elif _legado_pdf(url_gravada, url_final, texto, mime_type):
            return None
    except (OSError, UnicodeError, ValueError):
        return None
    return Resultado(
        url=url,
        status=STATUS_CACHE,
        texto=texto,
        conteudo=conteudo,
        http_status=http_status,
        url_final=url_final,
        de_cache=True,
        captured_at=captured_at,
        sha256=sha256,
        sha256_binario=sha256_binario,
        headers=headers,
        mime_type=mime_type,
        motivo=f"cache de {arquivo.parent.name}",
    )


def _escreve_atomico(arquivo: Path, conteudo: bytes) -> None:
    """Troca o arquivo só após escrever e sincronizar um temporário no mesmo diretório."""
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=arquivo.parent, prefix=f".{arquivo.name}.", suffix=".tmp", delete=False
        ) as saida:
            temporario = Path(saida.name)
            saida.write(conteudo)
            saida.flush()
            os.fsync(saida.fileno())
        os.replace(temporario, arquivo)
    finally:
        if temporario is not None:
            with suppress(FileNotFoundError):
                temporario.unlink()


def _grava_cache(resultado: Resultado) -> None:
    """Publica primeiro o original íntegro e depois o manifesto diário que o referencia."""
    resultado.sha256 = hashlib.sha256(resultado.texto.encode("utf-8")).hexdigest()
    resultado.sha256_binario = hashlib.sha256(resultado.conteudo).hexdigest()
    resultado.headers = _headers_normalizados(resultado.headers) or {}
    resultado.mime_type = _mime_type(resultado.headers.get("content-type", resultado.mime_type))
    manifesto = json.dumps(
        {
            "cache_version": CACHE_VERSION,
            "url": resultado.url,
            "url_final": resultado.url_final,
            "http_status": resultado.http_status,
            "captured_at": resultado.captured_at,
            "sha256": resultado.sha256,
            "sha256_binario": resultado.sha256_binario,
            "tamanho_binario": len(resultado.conteudo),
            "headers": resultado.headers,
            "mime_type": resultado.mime_type,
            "texto": resultado.texto,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    # Regravar o mesmo endereço também recupera um blob corrompido; não basta existir.
    _escreve_atomico(caminho_de_blob_cache(resultado.sha256_binario), resultado.conteudo)
    _escreve_atomico(caminho_de_cache(resultado.url), manifesto)


# ------------------------------------------------------------------------ anti-bot
_MARCAS_ANTIBOT = (
    "captcha",
    "are you a human",
    "cf-challenge",
    "cf-browser-verification",
    "verifique que voce e humano",
    "verifique que você é humano",
    "access denied",
    "request unsuccessful",
)


def parece_antibot(texto: str) -> bool:
    trecho = texto[:4000].lower()
    return any(m in trecho for m in _MARCAS_ANTIBOT)


# ---------------------------------------------------------------------------- fetch
def fetch(
    url: str,
    *,
    timeout: float = TIMEOUT_PADRAO,
    usar_cache: bool = True,
    tentativas: int = TENTATIVAS,
) -> Resultado:
    """Busca uma URL seguindo todas as regras. Nunca levanta por bloqueio — devolve status.

    Em `REPLAY_MODE=1`, resolve para o snapshot salvo; sem snapshot, levanta
    :class:`~pipeline.snapshots.SnapshotMissing`. É a única exceção que sai daqui, e ela
    existe justamente para **não** cair na rede.
    """
    if modo_replay():
        snap = snapshot_de_url(url)  # levanta SnapshotMissing de propósito
        conteudo, sha256_binario, mime_type = conteudo_original(snap)
        return Resultado(
            url=url,
            status=STATUS_REPLAY,
            texto=snap.texto,
            conteudo=conteudo,
            url_final=snap.url or url,
            http_status=snap.meta.get("http_status"),
            de_replay=True,
            captured_at=snap.captured_at,
            sha256=snap.meta.get("sha256", ""),
            sha256_binario=sha256_binario,
            mime_type=mime_type,
            headers=_headers_normalizados(snap.meta.get("headers", {})) or {},
            motivo=f"replay do snapshot {snap.source_id}",
        )

    if usar_cache:
        do_cache = _le_cache(url)
        if do_cache is not None:
            return do_cache

    if not permitido_por_robots(url):
        # Nenhuma requisição à rota é feita. Este é o ponto onde a regra vira comportamento.
        return Resultado(
            url=url,
            status=STATUS_BLOQUEADO_ROBOTS,
            motivo=f"robots.txt de {urlparse(url).netloc} proíbe esta rota para {user_agent()}",
        )

    ultimo_erro = ""
    for tentativa in range(1, max(tentativas, 1) + 1):
        _espera_o_limite(url)
        try:
            _requisicoes["total"] += 1
            resposta = httpx.get(
                url,
                timeout=deadline.timeout(timeout),
                follow_redirects=True,
                headers={"User-Agent": user_agent(), "Accept-Language": "pt-BR,pt;q=0.9"},
            )
        except httpx.HTTPError as exc:
            ultimo_erro = f"{type(exc).__name__}: {exc}"
            if tentativa < tentativas:
                deadline.sleep(BACKOFF_S * tentativa)
                continue
            return Resultado(url=url, status=STATUS_ERRO, motivo=ultimo_erro)

        # Bloqueio não se tenta de novo: repetir é pedir para ser bloqueado de novo.
        if resposta.status_code in {401, 403, 429}:
            return Resultado(
                url=url,
                status=STATUS_BLOQUEADO,
                http_status=resposta.status_code,
                url_final=str(resposta.url),
                motivo=(
                    f"HTTP {resposta.status_code}: a borda do site recusa cliente HTTP. "
                    "Sem troca de user-agent e sem rotação — bloqueio vira status."
                ),
            )
        if resposta.status_code >= 500:
            ultimo_erro = f"HTTP {resposta.status_code}"
            if tentativa < tentativas:
                deadline.sleep(BACKOFF_S * tentativa)
                continue
            return Resultado(
                url=url,
                status=STATUS_ERRO,
                http_status=resposta.status_code,
                motivo=ultimo_erro,
            )
        if resposta.status_code >= 400:
            return Resultado(
                url=url,
                status=STATUS_ERRO,
                http_status=resposta.status_code,
                url_final=str(resposta.url),
                motivo=f"HTTP {resposta.status_code}",
            )

        texto = resposta.text
        if parece_antibot(texto):
            return Resultado(
                url=url,
                status=STATUS_BLOQUEADO,
                http_status=resposta.status_code,
                url_final=str(resposta.url),
                motivo="página de verificação anti-bot; nenhuma tentativa de contornar",
            )

        resultado = Resultado(
            url=url,
            status=STATUS_OK,
            texto=texto,
            conteudo=resposta.content,
            http_status=resposta.status_code,
            url_final=str(resposta.url),
            captured_at=datetime.now(UTC).strftime("%Y-%m-%d"),
            sha256=hashlib.sha256(texto.encode("utf-8")).hexdigest(),
            sha256_binario=hashlib.sha256(resposta.content).hexdigest(),
            mime_type=_mime_type(resposta.headers.get("content-type", "")),
            headers={k.lower(): v for k, v in resposta.headers.items()},
            motivo=f"HTTP {resposta.status_code} em {tentativa} tentativa(s)",
        )
        if usar_cache:
            _grava_cache(resultado)
        return resultado

    return Resultado(url=url, status=STATUS_ERRO, motivo=ultimo_erro or "falha desconhecida")


def get_text(url: str, **kw) -> str:
    """Texto de uma URL. Levanta em bloqueio — para quem prefere exceção a status."""
    resultado = fetch(url, **kw)
    if not resultado.ok:
        raise RuntimeError(f"fetch de {url} falhou ({resultado.status}): {resultado.motivo}")
    return resultado.texto


__all__ = [
    "CACHE_DIR",
    "STATUS_BLOQUEADO",
    "STATUS_BLOQUEADO_ROBOTS",
    "STATUS_CACHE",
    "STATUS_ERRO",
    "STATUS_OK",
    "STATUS_REPLAY",
    "RedeProibidaEmReplay",
    "Resultado",
    "SnapshotMissing",
    "caminho_de_blob_cache",
    "caminho_de_cache",
    "crawl_delay",
    "fetch",
    "get_text",
    "modo_replay",
    "parece_antibot",
    "permitido_por_robots",
    "requisicoes_feitas",
    "user_agent",
    "zerar_contadores",
]
