"""Leitura da árvore de snapshots — o substrato do modo replay.

Um snapshot é uma pasta com o texto salvo da fonte e um `meta.json`:

    <raiz>/<version_id>/<captured_at>/<source_id>/
        page.md | doc.md    texto salvo (HTML convertido ou PDF convertido)
        raw.html            opcional, o original
        full.png            opcional, o print
        meta.json           url final, tier, tipo, status, sha256, captured_at
    <raiz>/<version_id>/fontes.json
        todas as fontes consultadas, inclusive as de status `bloqueada`

Duas raízes usam o mesmo formato: `data/snapshots/` (coleta real, WP-08) e
`tests/fixtures/snapshots/` (replay determinístico do eval e dos testes). A escolha vem
de `REPLAY_MODE`: com `REPLAY_MODE=1` **nada** é buscado na rede — é o que torna a demo
e o CI reprodutíveis, e é regra do projeto, não otimização.

Este módulo só lê. Quem escreve é a WP-08.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "snapshots"

#: Nomes de arquivo de texto, na ordem de preferência.
ARQUIVOS_DE_TEXTO = ("doc.md", "page.md", "text.md", "raw.txt")


def modo_replay() -> bool:
    return os.environ.get("REPLAY_MODE", "").strip() in {"1", "true", "True"}


def raiz_de_snapshots() -> Path:
    """Raiz efetiva: fixtures em replay, `data/snapshots` (ou `SNAPSHOT_DIR`) fora dele."""
    if modo_replay():
        return FIXTURES
    return ROOT / os.environ.get("SNAPSHOT_DIR", "data/snapshots")


@dataclass(frozen=True)
class Snapshot:
    """Um texto salvo de uma fonte, com a proveniência que o acompanha."""

    version_id: str
    source_id: str
    captured_at: str
    caminho: Path
    meta: dict

    @cached_property
    def texto(self) -> str:
        for nome in ARQUIVOS_DE_TEXTO:
            arquivo = self.caminho / nome
            if arquivo.exists():
                return arquivo.read_text(encoding="utf-8", errors="replace")
        return ""

    @property
    def url(self) -> str:
        return self.meta.get("url_final") or self.meta.get("url") or ""

    @property
    def tier(self) -> int:
        return int(self.meta.get("tier", 5))

    @property
    def tipo(self) -> str:
        return self.meta.get("tipo", "desconhecido")

    @property
    def status(self) -> str:
        return self.meta.get("status", "consultada")

    @property
    def e_registro_de_evidencia(self) -> bool:
        """Snapshot que guarda o trecho registrado, não a captura da página.

        Fica explícito porque tratar registro como captura oficial seria mentir sobre a
        proveniência. Vale como texto para grounding; não vale como print de página.
        """
        return self.tipo == "registro_de_evidencia"


@dataclass(frozen=True)
class FonteConsultada:
    """Uma fonte da lista de consultadas, com ou sem texto salvo.

    Fonte `bloqueada` (CAPTCHA, 403) aparece aqui com esse status: é o que sustenta
    `nao_encontrado` honesto ("nenhuma fonte consultada menciona; fontes listadas") em
    vez de silêncio.
    """

    source_id: str
    url: str
    tier: int
    tipo: str
    status: str
    tem_texto_salvo: bool
    nota: str = ""


def _le_json(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def snapshots_de(version_id: str, raiz: Path | None = None) -> list[Snapshot]:
    """Todos os snapshots de uma versão, do tier melhor para o pior.

    Ordena por tier e, dentro do tier, coloca captura de página antes de registro de
    evidência: a reconciliação deve preferir a fonte primária quando as duas existem.
    """
    base = (raiz or raiz_de_snapshots()) / version_id
    if not base.is_dir():
        return []
    encontrados: list[Snapshot] = []
    for pasta_ts in sorted(p for p in base.iterdir() if p.is_dir()):
        for pasta_fonte in sorted(p for p in pasta_ts.iterdir() if p.is_dir()):
            meta = _le_json(pasta_fonte / "meta.json")
            encontrados.append(
                Snapshot(
                    version_id=version_id,
                    source_id=meta.get("source_id", pasta_fonte.name),
                    captured_at=meta.get("captured_at", pasta_ts.name),
                    caminho=pasta_fonte,
                    meta=meta,
                )
            )
    encontrados.sort(key=lambda s: (s.tier, s.e_registro_de_evidencia, s.source_id))
    return encontrados


def fontes_de(version_id: str, raiz: Path | None = None) -> list[FonteConsultada]:
    """Lista de fontes consultadas de uma versão, incluindo as bloqueadas."""
    arquivo = (raiz or raiz_de_snapshots()) / version_id / "fontes.json"
    dados = _le_json(arquivo)
    return [
        FonteConsultada(
            source_id=f.get("source_id", ""),
            url=f.get("url", ""),
            tier=int(f.get("tier", 5)),
            tipo=f.get("tipo", "desconhecido"),
            status=f.get("status", "consultada"),
            tem_texto_salvo=bool(f.get("tem_texto_salvo")),
            nota=f.get("nota", ""),
        )
        for f in dados.get("fontes", [])
    ]


def textos_de(version_id: str, raiz: Path | None = None) -> dict[str, str]:
    """`{source_id: texto salvo}` — o que o grounding usa."""
    return {s.source_id: s.texto for s in snapshots_de(version_id, raiz)}


def versoes_disponiveis(raiz: Path | None = None) -> list[str]:
    base = raiz or raiz_de_snapshots()
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())
