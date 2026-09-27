"""Quem é cada domínio para a pesquisa — lido de `fontes.yaml`, não escrito no código.

**Por que sair do código.** A lista de imprensa vivia numa tupla em `classify.py`, e ela
respondia a uma pergunta só: "este domínio é conhecido?". Duas perguntas ficaram sem
resposta, e as duas custaram caro na primeira pesquisa ao vivo da S10:

* **o que esta página é?** — `icarros.com.br/catalogo/...` é uma ficha em tabela, que o
  fast-path lê inteira por regra; `kbb.com.br` é matéria, e rende cinco campos. Tratar as
  duas como "imprensa" faz a coleta gastar página na que rende menos;
* **ela abre?** — `quatrorodas` e `carrosnaweb` só respondem ao navegador. Sem saber disso
  antes, a pesquisa gasta uma das doze páginas para receber 403 e seguir em frente.

Cada linha do YAML saiu de medição (`scripts/research/sondar_fontes.py`), com a data e o
número de campos que o site rendeu **sem chamar o modelo**. Domínio reprovado fica escrito
com o motivo: a lista existe tanto para dizer onde procurar quanto para não repetir busca
que já se provou vazia.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ARQUIVO = Path(__file__).with_name("fontes.yaml")

#: Os tipos que a pesquisa sabe tratar. `ficha` é o que ela procura; `imprensa` é o que ela
#: aceita quando a ficha não aparece.
TIPOS = ("oficial", "registro", "ficha", "imprensa")

#: A ordem de preferência dentro do mesmo tier. Ficha antes de imprensa porque a página de
#: ficha é de **uma** versão (não precisa recorte) e se lê por regra, sem custo de modelo.
PESO_DO_TIPO = {"oficial": 0, "registro": 1, "ficha": 2, "imprensa": 3}


class FontesInvalidas(ValueError):
    """O YAML não descreve os domínios como a pesquisa precisa."""


@dataclass(frozen=True)
class Fonte:
    """Um domínio conhecido, e o que a sondagem mediu nele."""

    dominio: str
    tier: int
    tipo: str
    navegador: bool = False
    campos_medidos: int | None = None
    nota: str = ""

    @property
    def peso(self) -> int:
        return PESO_DO_TIPO.get(self.tipo, len(PESO_DO_TIPO))


@dataclass(frozen=True)
class Mapa:
    """O arquivo inteiro, já validado."""

    versao: str
    fontes: tuple[Fonte, ...]
    reprovados: dict[str, str]

    def decidir(self, dominio: str) -> tuple[Fonte | None, str]:
        """O que o mapa diz sobre este domínio: `(fonte, motivo_da_reprovacao)`.

        **O mais específico decide, aprovado ou reprovado** — e é essa a regra, não a
        ordem do arquivo. `uol.com.br` está aprovado como imprensa e `motor1.uol.com.br`
        está reprovado (403 nas duas provas da sondagem, inclusive com navegador). Olhar
        só os aprovados fazia o motor1 entrar pela porta do guarda-chuva.
        """
        alvo = (dominio or "").strip().lower()
        if not alvo:
            return None, ""

        def casa(registrado: str) -> bool:
            return alvo == registrado or alvo.endswith("." + registrado)

        aprovadas = [f for f in self.fontes if casa(f.dominio)]
        reprovados = [(d, m) for d, m in self.reprovados.items() if casa(d)]
        melhor_aprovada = max(aprovadas, key=lambda f: len(f.dominio), default=None)
        melhor_reprovado = max(reprovados, key=lambda par: len(par[0]), default=None)

        if melhor_reprovado and (
            melhor_aprovada is None or len(melhor_reprovado[0]) > len(melhor_aprovada.dominio)
        ):
            return None, melhor_reprovado[1]
        return melhor_aprovada, ""

    def de(self, dominio: str) -> Fonte | None:
        """A fonte que cobre este domínio, quando ela não está reprovada."""
        return self.decidir(dominio)[0]

    def do_tipo(self, *tipos: str) -> tuple[Fonte, ...]:
        return tuple(f for f in self.fontes if f.tipo in tipos)


def _erro(mensagem: str) -> None:
    raise FontesInvalidas(mensagem)


def _ler_fonte(bruto: Any, posicao: int) -> Fonte:
    if not isinstance(bruto, dict):
        _erro(f"domínio {posicao}: cada item de `dominios` é um mapa")
    dominio = str(bruto.get("dominio") or "").strip().lower()
    if not dominio:
        _erro(f"domínio {posicao}: sem `dominio`")
    try:
        tier = int(bruto["tier"])
    except (KeyError, TypeError, ValueError):
        _erro(f"{dominio}: `tier` ausente ou não é número")
    if not 1 <= tier <= 5:
        _erro(f"{dominio}: tier {tier} fora de 1–5 (a escala de `docs/03`)")
    tipo = str(bruto.get("tipo") or "").strip().lower()
    if tipo not in TIPOS:
        _erro(f"{dominio}: tipo {tipo!r} desconhecido; aceitos: {', '.join(TIPOS)}")
    medidos = bruto.get("campos_medidos")
    return Fonte(
        dominio=dominio,
        tier=tier,
        tipo=tipo,
        navegador=bool(bruto.get("navegador", False)),
        campos_medidos=int(medidos) if medidos is not None else None,
        nota=str(bruto.get("nota") or "").strip(),
    )


@functools.cache
def carregar(caminho: Path | None = None) -> Mapa:
    """Lê e valida `fontes.yaml`. Em cache: o arquivo não muda durante uma pesquisa."""
    import yaml

    alvo = caminho or ARQUIVO
    try:
        dados = yaml.safe_load(alvo.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise FontesInvalidas(f"não deu para ler {alvo}: {exc}") from exc
    if not isinstance(dados, dict):
        _erro(f"{alvo}: o arquivo tem de ser um mapa")

    brutos = dados.get("dominios") or []
    if not brutos:
        _erro(f"{alvo}: nenhum domínio declarado")
    fontes = tuple(_ler_fonte(b, i) for i, b in enumerate(brutos))

    vistos: set[str] = set()
    for f in fontes:
        if f.dominio in vistos:
            _erro(f"{f.dominio}: declarado duas vezes")
        vistos.add(f.dominio)

    reprovados: dict[str, str] = {}
    for bruto in dados.get("reprovados") or []:
        if not isinstance(bruto, dict) or not bruto.get("dominio"):
            _erro("cada item de `reprovados` é um mapa com `dominio`")
        dominio = str(bruto["dominio"]).strip().lower()
        motivo = str(bruto.get("motivo") or "").strip()
        if not motivo:
            _erro(f"{dominio}: reprovado sem motivo escrito")
        if dominio in vistos:
            _erro(f"{dominio}: está em `dominios` e em `reprovados`")
        reprovados[dominio] = motivo

    return Mapa(versao=str(dados.get("versao") or ""), fontes=fontes, reprovados=reprovados)


def fonte_de(dominio: str) -> Fonte | None:
    return carregar().de(dominio)


def dominios_de_ficha() -> list[str]:
    """Os domínios que a busca restrita deve varrer primeiro: ficha antes de imprensa."""
    mapa = carregar()
    ordenadas = sorted(
        mapa.do_tipo("ficha", "imprensa"),
        key=lambda f: (f.peso, -(f.campos_medidos or 0), f.dominio),
    )
    return [f.dominio for f in ordenadas]


def exige_navegador(dominio: str) -> bool:
    fonte = fonte_de(dominio)
    return bool(fonte and fonte.navegador)


def motivo_da_reprovacao(dominio: str) -> str:
    """Por que este domínio não entra — vazio quando ele não foi reprovado."""
    return carregar().decidir(dominio)[1]


__all__ = [
    "ARQUIVO",
    "PESO_DO_TIPO",
    "TIPOS",
    "Fonte",
    "FontesInvalidas",
    "Mapa",
    "carregar",
    "dominios_de_ficha",
    "exige_navegador",
    "fonte_de",
    "motivo_da_reprovacao",
]
