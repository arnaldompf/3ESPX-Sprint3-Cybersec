"""Proteção contra SSRF nas requisições de saída do pipeline (OWASP API7:2023).

**O risco, medido na solução:** o Pesquisador (`pipeline/research`) baixa URLs que vêm de
resultados de busca e de links descobertos em páginas de terceiros. O download fica em
`pipeline/fetch/http.py::fetch`, que chama `httpx.get(url, follow_redirects=True)` sem
conferir para onde o nome resolve. Uma página maliciosa indexada pelo buscador pode apontar
(ou redirecionar) para `http://169.254.169.254/` (metadados de nuvem, com credenciais),
`http://127.0.0.1:5432` ou `http://db:5432` (rede interna), e o worker faria a requisição
de dentro da infraestrutura.

**A correção:** antes de cada requisição **e a cada salto de redirecionamento**, o destino
é resolvido e todos os IPs têm de ser globais (nem privado, nem loopback, nem link-local,
nem reservado, nem multicast). Esquema só `http`/`https`, porta só 80/443, sem credencial
na URL. Bloqueio vira `DestinoProibido`, que é um `httpx.HTTPError`: o laço de tentativas
do `fetch` já trata esse tipo e devolve um resultado com status de erro, sem derrubar o job.

**Como entra sem alterar a solução:** `proteger_pipeline()` troca o nome `httpx` **dentro**
do módulo `pipeline.fetch.http` por `HttpxSeguro`, que delega tudo ao `httpx` real e só
intercepta `get`. Nenhum outro módulo é afetado.

**Risco residual (documentado):** entre a resolução de DNS aqui e a conexão do `httpx`
existe uma janela (DNS rebinding). A defesa em profundidade é de rede: em produção o worker
fica numa rede de saída que não alcança `backend` nem metadados (`infra/docker-compose.yml`).
O coletor por navegador (`pipeline/fetch/browser.py`, Playwright) não passa por aqui e
depende só dessa camada de rede.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
import structlog

from seguranca.metricas import REGISTRO

_log = structlog.get_logger("specradar.seguranca.ssrf")

ESQUEMAS_PERMITIDOS = frozenset({"http", "https"})
PORTAS_PERMITIDAS = frozenset({80, 443})
MAX_REDIRECIONAMENTOS = 5

Resolvedor = Callable[[str, int], list[str]]


class DestinoProibido(httpx.HTTPError):
    """URL cujo destino não pode ser acessado pelo pipeline."""


def _resolver_dns(host: str, porta: int) -> list[str]:
    infos = socket.getaddrinfo(host, porta, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def _ip_publico(endereco: str) -> bool:
    ip = ipaddress.ip_address(endereco.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _bloquear(motivo: str, url: str, **detalhes: object) -> DestinoProibido:
    """Registra a tentativa (log + métrica) e devolve a exceção a levantar.

    Todo bloqueio por política é evento de segurança: esquema, credencial na URL, porta e IP
    interno. Host que não resolve **não** passa por aqui — é falha de rede, não ataque.
    """
    REGISTRO.incrementar("specradar_eventos_seguranca_total", tipo="ssrf_bloqueado")
    _log.warning("seguranca.ssrf_bloqueado", motivo=motivo, url=url[:200], **detalhes)
    return DestinoProibido(motivo)


def validar_destino(url: str, *, resolver: Resolvedor = _resolver_dns) -> None:
    """Levanta `DestinoProibido` se a URL não puder ser acessada. Silêncio = permitido."""
    partes = urlsplit(url)
    esquema = (partes.scheme or "").lower()
    if esquema not in ESQUEMAS_PERMITIDOS:
        raise _bloquear(f"esquema {esquema!r} não permitido", url)
    if partes.username or partes.password:
        raise _bloquear("credencial embutida na URL não é permitida", url)
    host = partes.hostname
    if not host:
        raise DestinoProibido("URL sem host")
    porta = partes.port or (443 if esquema == "https" else 80)
    if porta not in PORTAS_PERMITIDAS:
        raise _bloquear(f"porta {porta} não permitida", url, host=host)
    try:
        enderecos = resolver(host, porta)
    except (socket.gaierror, UnicodeError) as exc:
        raise DestinoProibido(f"host {host!r} não resolve") from exc
    if not enderecos:
        raise DestinoProibido(f"host {host!r} sem endereço")
    internos = [e for e in enderecos if not _ip_publico(e)]
    if internos:
        raise _bloquear(
            f"host {host!r} resolve para endereço interno", url, host=host, enderecos=internos
        )


class HttpxSeguro:
    """Substituto do módulo `httpx` dentro de `pipeline.fetch.http`.

    Só `get` muda: valida o destino e usa um cliente cujo gancho de requisição valida de
    novo **cada salto** de redirecionamento. Qualquer outro atributo (`HTTPError`,
    `TimeoutException`, ...) é o do `httpx` real.
    """

    def __init__(
        self,
        *,
        resolver: Resolvedor = _resolver_dns,
        transporte: httpx.BaseTransport | None = None,
    ) -> None:
        self._resolver = resolver
        self._transporte = transporte  # só os testes trocam; produção usa o padrão

    def __getattr__(self, nome: str):
        return getattr(httpx, nome)

    def get(self, url, *, timeout=None, follow_redirects=False, headers=None, **kwargs):
        validar_destino(str(url), resolver=self._resolver)

        def conferir_salto(requisicao: httpx.Request) -> None:
            validar_destino(str(requisicao.url), resolver=self._resolver)

        with httpx.Client(
            timeout=timeout if timeout is not None else httpx.Timeout(30.0),
            follow_redirects=follow_redirects,
            max_redirects=MAX_REDIRECIONAMENTOS,
            headers=headers,
            event_hooks={"request": [conferir_salto]},
            transport=self._transporte,
        ) as cliente:
            return cliente.get(url, **kwargs)


def proteger_pipeline() -> None:
    """Liga a proteção no coletor HTTP do pipeline. Idempotente."""
    from seguranca.solucao import preparar_importacao

    preparar_importacao()
    from pipeline.fetch import http as coletor

    if not isinstance(coletor.httpx, HttpxSeguro):
        coletor.httpx = HttpxSeguro()
