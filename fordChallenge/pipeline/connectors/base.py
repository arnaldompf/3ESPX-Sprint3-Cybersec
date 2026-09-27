"""Interface dos conectores de linha vigente (Passo 0 do pipeline).

Todo conector responde às mesmas duas perguntas, e só a essas:

* `lineup(modelo)` — quais versões a marca oferece **hoje**?
* `sources(versao)` — de onde tirar os atributos dessa versão?

Por que isso é um passo separado, antes de qualquer extração: a lição 4 do gabarito é que
**versões saem de linha**. A Hilux GR-Sport não existe na linha 2026, e um sistema que
extrai atributos sem checar isso primeiro entrega uma ficha bonita de um carro que a
montadora não vende mais.

Em `REPLAY_MODE=1` o conector lê `tests/fixtures/lineups/<marca>/<modelo>/lineup.md`.
Ao vivo, busca a página da marca — respeitando robots.txt e 1 req/s (`_http.py`, que a
WP-08 substitui pelo fetcher definitivo). Fonte bloqueada vira status, nunca truque.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LINEUPS = ROOT / "tests" / "fixtures" / "lineups"


class FonteBloqueada(RuntimeError):
    """A fonte respondeu 403/CAPTCHA. Vira status; ninguém tenta contornar."""


class LinhaVigenteIndisponivel(RuntimeError):
    """Não há linha vigente para responder — em replay, falta a fixture."""


@dataclass(frozen=True)
class VersionInfo:
    """Uma versão da linha vigente, como a marca a nomeia."""

    nome_exato: str
    ano_modelo: int | None = None
    preco_a_partir_brl: int | None = None
    url: str = ""
    marca: str = ""
    modelo: str = ""

    def __str__(self) -> str:  # pragma: no cover - conveniência
        return self.nome_exato


@dataclass(frozen=True)
class SourceRef:
    """Uma fonte a consultar para os atributos de uma versão."""

    url: str
    tipo: str
    tier: int
    nota: str = ""


@dataclass
class ResultadoLinha:
    """Linha vigente + proveniência + o que não deu para coletar."""

    versoes: list[VersionInfo] = field(default_factory=list)
    url: str = ""
    captured_at: str = ""
    origem: str = ""
    nota: str = ""
    bloqueadas: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ normalização
_SEM_ACENTO = str.maketrans(
    "áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ",
    "aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN",
)

#: Tokens que não distinguem versão e por isso saem antes do match (`docs/05`, Passo 0).
TOKENS_IGNORADOS: frozenset[str] = frozenset(
    {"at", "mt", "4x4", "4x2", "4wd", "2wd", "awd", "automatico", "automatica", "manual"}
)


def normalizar_versao(texto: str) -> str:
    """Minúsculas, sem acento, sem os tokens que não distinguem versão.

    >>> normalizar_versao("SRX Plus AT")
    'srx plus'
    >>> normalizar_versao("Raptor 3.0 V6 Bi-turbo 4WD AT")
    'raptor 3.0 v6 bi turbo'
    """
    t = str(texto).translate(_SEM_ACENTO).lower()
    t = t.replace("×", "x").replace("–", "-").replace("—", "-")
    t = re.sub(r"[^\w\s.]+", " ", t)
    tokens = [tok for tok in t.split() if tok not in TOKENS_IGNORADOS]
    return " ".join(tokens).strip()


def slug(texto: str) -> str:
    return str(texto).translate(_SEM_ACENTO).lower().replace(" ", "-")


# --------------------------------------------------------------- leitura do lineup.md
_LINHA_TABELA = re.compile(
    r"^\|\s*(?P<nome>[^|]+?)\s*\|\s*(?P<ano>[^|]*?)\s*\|\s*(?P<preco>[^|]*?)\s*\|\s*(?P<url>[^|]*?)\s*\|\s*$"
)


def parse_lineup_md(texto: str, *, marca: str = "", modelo: str = "") -> ResultadoLinha:
    """Lê o formato de `tests/fixtures/lineups/<marca>/<modelo>/lineup.md`.

    O arquivo é gerado por `scripts/build_fixtures.py` e traz, no cabeçalho, a URL, a data
    e **de qual fonte bruta cada linha foi derivada** — a proveniência viaja com o dado.
    """
    resultado = ResultadoLinha()
    versoes: list[VersionInfo] = []
    for linha in texto.splitlines():
        bruto = linha.strip()
        if bruto.startswith("**URL:**"):
            resultado.url = bruto.removeprefix("**URL:**").strip()
        elif bruto.startswith("**Coletado em:**"):
            resultado.captured_at = bruto.removeprefix("**Coletado em:**").strip()
        elif bruto.startswith("**Derivado de:**"):
            resultado.origem = bruto.removeprefix("**Derivado de:**").strip()
        elif bruto.startswith("> **Atenção:**"):
            resultado.nota = bruto.removeprefix("> **Atenção:**").strip()
        achado = _LINHA_TABELA.match(bruto)
        if not achado:
            continue
        nome = achado.group("nome")
        if nome in {"nome_exato"} or set(nome) <= {"-", ":"}:
            continue
        ano = achado.group("ano").strip()
        preco = achado.group("preco").strip()
        versoes.append(
            VersionInfo(
                nome_exato=nome,
                ano_modelo=int(ano) if ano.isdigit() else None,
                preco_a_partir_brl=int(preco) if preco.isdigit() else None,
                url=achado.group("url").strip(),
                marca=marca,
                modelo=modelo,
            )
        )
    resultado.versoes = versoes
    return resultado


def modo_replay() -> bool:
    return os.environ.get("REPLAY_MODE", "").strip() in {"1", "true", "True"}


# ------------------------------------------------------------------------- conector
class Connector(ABC):
    """Base dos conectores por marca."""

    marca: str = ""
    dominio: str = ""
    #: modelos que este conector sabe atender (minúsculas, sem acento)
    modelos: tuple[str, ...] = ()
    #: tier das fontes que ele indica
    tier: int = 1

    # -- linha vigente -------------------------------------------------------------
    def lineup(self, modelo: str) -> ResultadoLinha:
        """Linha vigente do modelo. Em replay, lê a fixture; ao vivo, a página da marca."""
        if modo_replay():
            return self.lineup_replay(modelo)
        return self.lineup_live(modelo)

    def lineup_replay(self, modelo: str) -> ResultadoLinha:
        arquivo = LINEUPS / slug(self.marca) / slug(modelo) / "lineup.md"
        if not arquivo.exists():
            raise LinhaVigenteIndisponivel(
                f"sem fixture de linha vigente para {self.marca} {modelo} "
                f"(esperada em {arquivo.relative_to(ROOT)}); "
                "rode `python scripts/build_fixtures.py`"
            )
        return parse_lineup_md(arquivo.read_text(encoding="utf-8"), marca=self.marca, modelo=modelo)

    @abstractmethod
    def lineup_live(self, modelo: str) -> ResultadoLinha:
        """Coleta a linha vigente na página da marca (só fora de `REPLAY_MODE`)."""

    # -- fontes de atributos -------------------------------------------------------
    @abstractmethod
    def sources(self, versao: VersionInfo) -> list[SourceRef]:
        """Fontes a consultar para os atributos desta versão, do melhor tier ao pior."""

    def atende(self, modelo: str) -> bool:
        alvo = normalizar_versao(modelo)
        return any(
            alvo == normalizar_versao(m) or alvo in normalizar_versao(m) for m in self.modelos
        )
