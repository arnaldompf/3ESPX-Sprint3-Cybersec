"""Escrita e indexação de snapshots — o que torna a coleta auditável e a demo repetível.

`pipeline/store.py` (WP-02) lê a árvore de snapshots **por versão**, que é o que o eval
precisa. Este módulo acrescenta as duas coisas que a coleta precisa:

* **escrever** um snapshot completo (texto, bruto, print, `meta.json` com sha256);
* **encontrar** um snapshot **pela URL**, que é como o fetcher pergunta em replay.

Layout (o mesmo que as fixtures usam, `docs/05`):

    <raiz>/<version_id>/<captured_at>/<source_id>/
        page.md     HTML convertido       raw.html   o original
        doc.md      PDF convertido        full.png   print de página inteira
        meta.json   url final, tier, tipo, status, sha256, captured_at

O `meta.json` é o que faz o snapshot valer como evidência: sem URL final, data e sha256,
o texto salvo é só um arquivo. `ADR-4` de `docs/02` chama isso de "barato, auditável, e
permite modo replay para demo e testes" — as três propriedades vêm do mesmo lugar.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from pipeline.store import (
    ARQUIVOS_DE_TEXTO,
    FIXTURES,
    Snapshot,
    modo_replay,
    raiz_de_snapshots,
)

ROOT = Path(__file__).resolve().parent.parent


class SnapshotMissing(FileNotFoundError):
    """Não há snapshot salvo para esta URL.

    Em `REPLAY_MODE=1` esta exceção é o **comportamento correto**: cair para a rede
    quando falta um snapshot destruiria o determinismo da demo e do CI.
    """

    def __init__(self, url: str, raizes: list[Path] | None = None) -> None:
        locais = ", ".join(str(r) for r in (raizes or [])) or "nenhuma raiz consultada"
        super().__init__(
            f"sem snapshot para {url} (procurado em: {locais}). "
            "Em REPLAY_MODE=1 isso não cai para a rede de propósito."
        )
        self.url = url


# ------------------------------------------------------------------ URL normalizada
def normalizar_url(url: str) -> str:
    """Chave estável de URL: sem esquema, sem `www.`, sem barra final, sem fragmento.

    Duas grafias da mesma página não podem virar dois snapshots — e não podem fazer o
    replay dizer "não encontrei" por causa de uma barra.
    """
    partes = urlparse(url.strip())
    host = (partes.netloc or "").lower().removeprefix("www.")
    caminho = re.sub(r"/+$", "", partes.path or "")
    return urlunparse(("", host, caminho, "", partes.query, "")).lstrip("/") or host


def sha256_de(texto: str | bytes) -> str:
    dados = texto.encode("utf-8") if isinstance(texto, str) else texto
    return hashlib.sha256(dados).hexdigest()


def agora_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def hoje() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


# ------------------------------------------------------------------------- índice
def raizes_de_busca() -> list[Path]:
    """Onde procurar snapshots, na ordem de preferência.

    Em replay, as fixtures vêm primeiro (determinismo) e `data/snapshots` depois, para
    que uma coleta local recente também sirva de replay. Fora de replay, só `data/`.
    """
    data = ROOT / os.environ.get("SNAPSHOT_DIR", "data/snapshots")
    if modo_replay():
        return [FIXTURES, data]
    return [data]


def _prioridade(snap: Snapshot) -> tuple:
    """Chave de escolha entre snapshots da **mesma** URL, do melhor para o pior.

    Mais de um snapshot pode compartilhar a URL: a página oficial da Hilux e o registro
    de evidência derivado dela apontam para o mesmo endereço. Sem desempate explícito, a
    escolha caía na ordem de varredura do disco e `texto_de_url` devolvia o **registro**
    em vez da **página** — proveniência trocada em silêncio, que é exatamente o que este
    projeto não pode fazer.

    Ordem: coleta mais recente · captura de página antes de registro · tier melhor ·
    texto maior (uma página inteira é mais útil que um recorte).
    """
    return (
        snap.captured_at,
        not snap.e_registro_de_evidencia,
        -snap.tier,
        len(snap.texto),
    )


def snapshots_por_url(raizes: list[Path] | None = None) -> dict[str, list[Snapshot]]:
    """`{url normalizada: [snapshots, do melhor para o pior]}`.

    Varre a árvore inteira. Não é cacheado de propósito: o fetcher escreve snapshots
    durante a execução, e um índice velho faria ele achar que a página que acabou de
    salvar não existe.
    """
    achados: dict[str, list[Snapshot]] = {}
    for raiz in raizes or raizes_de_busca():
        if not raiz.is_dir():
            continue
        for meta_json in raiz.rglob("meta.json"):
            try:
                meta = json.loads(meta_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            url = meta.get("url_final") or meta.get("url")
            if not url:
                continue
            pasta = meta_json.parent
            achados.setdefault(normalizar_url(url), []).append(
                Snapshot(
                    version_id=meta.get("version_id", ""),
                    source_id=meta.get("source_id", pasta.name),
                    captured_at=meta.get("captured_at", pasta.parent.name),
                    caminho=pasta,
                    meta=meta,
                )
            )
    for lista in achados.values():
        lista.sort(key=_prioridade, reverse=True)
    return achados


def indexar_por_url(raizes: list[Path] | None = None) -> dict[str, Snapshot]:
    """`{url normalizada: melhor snapshot}` — ver :func:`_prioridade`."""
    return {chave: lista[0] for chave, lista in snapshots_por_url(raizes).items() if lista}


def snapshot_de_url(url: str, raizes: list[Path] | None = None) -> Snapshot:
    """Melhor snapshot de uma URL. Levanta :class:`SnapshotMissing` se não houver."""
    alvos = raizes or raizes_de_busca()
    lista = snapshots_por_url(alvos).get(normalizar_url(url)) or []
    if not lista:
        raise SnapshotMissing(url, alvos)
    return lista[0]


def todos_os_snapshots_de_url(url: str, raizes: list[Path] | None = None) -> list[Snapshot]:
    """Todos os snapshots da URL, do melhor para o pior. Lista vazia se não houver."""
    return snapshots_por_url(raizes).get(normalizar_url(url)) or []


def texto_de_url(url: str, raizes: list[Path] | None = None) -> str:
    return snapshot_de_url(url, raizes).texto


def tem_snapshot(url: str, raizes: list[Path] | None = None) -> bool:
    try:
        snapshot_de_url(url, raizes)
    except SnapshotMissing:
        return False
    return True


def conteudo_original(snap: Snapshot) -> tuple[bytes, str, str]:
    """Original contido no snapshot e com hash conferido; ausente não vira texto."""
    name = snap.meta.get("raw_path")
    if not isinstance(name, str) or not name:
        return b"", "", ""
    directory = snap.caminho.resolve()
    file = (directory / name).resolve()
    if not file.is_relative_to(directory) or not file.is_file():
        return b"", "", ""
    try:
        data = file.read_bytes()
    except OSError:
        return b"", "", ""
    digest = sha256_de(data)
    expected = snap.meta.get("sha256_binario")
    if expected and expected != digest:
        return b"", "", ""
    mime = snap.meta.get("mime_type", "")
    if data.startswith(b"%PDF"):
        mime = "application/pdf"
    elif not mime:
        mime = "text/html" if file.suffix == ".html" else "application/octet-stream"
    return data, digest, mime


# ------------------------------------------------------------------------- escrita
@dataclass
class SnapshotEscrito:
    """O que foi gravado, para o chamador registrar em `snapshots` e em `evidences`."""

    version_id: str
    source_id: str
    captured_at: str
    caminho: Path
    text_path: str
    sha256: str
    url_final: str
    tier: int
    tipo: str
    status: str
    bytes_texto: int

    def to_meta(self) -> dict:
        return {
            "source_id": self.source_id,
            "version_id": self.version_id,
            "url_final": self.url_final,
            "tier": self.tier,
            "tipo": self.tipo,
            "status": self.status,
            "captured_at": self.captured_at,
            "text_path": self.text_path,
            "sha256": self.sha256,
            "bytes": self.bytes_texto,
        }


def _slug_source(url: str, tipo: str) -> str:
    base = normalizar_url(url)
    base = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")[:60] or "fonte"
    return f"{base}__{tipo}"[:80]


def escrever_snapshot(
    *,
    version_id: str,
    url_final: str,
    texto: str,
    tier: int,
    tipo: str,
    status: str = "consultada",
    source_id: str | None = None,
    formato: str | None = None,
    bruto: bytes | str | None = None,
    screenshot: bytes | None = None,
    http_status: int | None = None,
    extras: dict | None = None,
    raiz: Path | None = None,
    captured_at: str | None = None,
) -> SnapshotEscrito:
    """Grava um snapshot completo e devolve o registro.

    `formato` default: `doc.md` para PDF, `page.md` para o resto — é o que `store.py`
    procura, na ordem de :data:`pipeline.store.ARQUIVOS_DE_TEXTO`.
    """
    if modo_replay():
        raise RuntimeError(
            "escrever_snapshot em REPLAY_MODE=1: replay é somente leitura. "
            "Se a intenção é coletar, desligue REPLAY_MODE."
        )
    destino_raiz = raiz or (ROOT / os.environ.get("SNAPSHOT_DIR", "data/snapshots"))
    ts = agora_iso()
    sid = source_id or _slug_source(url_final, tipo)
    nome_texto = formato or ("doc.md" if tipo.startswith("pdf") else "page.md")
    if nome_texto not in ARQUIVOS_DE_TEXTO:
        raise ValueError(
            f"formato {nome_texto!r} não é lido por store.py; use um de {ARQUIVOS_DE_TEXTO}"
        )

    # O slug legível é truncado: URLs longas de versões vizinhas podem ser iguais.
    # URL completa + conteúdo separam capturas simultâneas e preservam as anteriores.
    raw_bytes = bruto.encode("utf-8") if isinstance(bruto, str) else bruto
    raw_hash = sha256_de(raw_bytes) if raw_bytes is not None else ""
    identity = sha256_de(url_final + "\n" + texto + "\n" + raw_hash)[:24]
    pasta = destino_raiz / version_id / ts / f"{sid}__{identity}"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome_texto).write_text(texto, encoding="utf-8", newline="\n")
    if bruto is not None:
        alvo = pasta / ("raw.pdf" if tipo.startswith("pdf") else "raw.html")
        if isinstance(bruto, str):
            alvo.write_text(bruto, encoding="utf-8", newline="\n")
        else:
            alvo.write_bytes(bruto)
    if screenshot is not None:
        (pasta / "full.png").write_bytes(screenshot)

    registro = SnapshotEscrito(
        version_id=version_id,
        source_id=sid,
        captured_at=captured_at or hoje(),
        caminho=pasta,
        text_path=nome_texto,
        sha256=sha256_de(texto),
        url_final=url_final,
        tier=tier,
        tipo=tipo,
        status=status,
        bytes_texto=len(texto.encode("utf-8")),
    )
    meta = registro.to_meta()
    if http_status is not None:
        meta["http_status"] = http_status
    if screenshot is not None:
        meta["screenshot_path"] = "full.png"
    meta.update(extras or {})
    # Metadados adicionais não podem substituir os hashes calculados dos originais.
    meta["sha256"] = registro.sha256
    if raw_bytes is not None:
        meta["raw_path"] = "raw.pdf" if tipo.startswith("pdf") else "raw.html"
        meta["sha256_binario"] = raw_hash
        meta["bytes_original"] = len(raw_bytes)
        meta["mime_type"] = "application/pdf" if tipo.startswith("pdf") else "text/html"
    (pasta / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return registro


def registrar_no_banco(escrito: SnapshotEscrito) -> str | None:
    """Registra o snapshot na tabela `snapshots`, se a camada de dados existir.

    Import tardio e falha silenciosa por decisão: o fetcher tem de funcionar em teste de
    unidade e em coleta avulsa sem banco nenhum. Quem precisa de garantia confere o retorno.
    """
    try:
        from api.app.db import session_scope
        from api.app.models import Snapshot as SnapshotRow
    except ImportError:  # pragma: no cover - ambiente sem a WP-03
        return None
    with session_scope() as sessao:
        linha = SnapshotRow(
            version_id=escrito.version_id or None,
            url=escrito.url_final,
            captured_at=datetime.now(UTC),
            raw_path=str(escrito.caminho),
            text_path=str(escrito.caminho / escrito.text_path),
            sha256=escrito.sha256,
        )
        sessao.add(linha)
        sessao.flush()
        return linha.id


def raiz_efetiva() -> Path:
    """Atalho de diagnóstico: a raiz que o modo atual usaria para ler."""
    return raiz_de_snapshots()
