"""O mapa de segmentos: contra quem cada modelo Ford briga.

**Por que o mapa é tão pequeno de propósito.** Ele tem um segmento — picape média — e um
modelo. Preencher os outros de memória seria o erro mais caro possível neste módulo: um
segmento errado escolhe os concorrentes errados, e o erro **não aparece como erro**.
Aparece como uma matriz de paridade impecável comparando carros que ninguém compara. Por
isso, modelo fora do mapa cai para o Pesquisador — que busca, cita a fonte e **propõe**,
para um humano confirmar.

**A distinção entre lista escrita e lista proposta atravessa toda a tela.** Uma vem de
`segments.yaml`, com data e autor; a outra vem de uma busca em fonte T3 de hoje. Não têm o
mesmo peso, e apresentá-las iguais seria a mesma mentira de método que a etiqueta
FATO/INFERÊNCIA existe para impedir.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pipeline.ontology import normalize

#: O arquivo, ao lado do módulo — mesma convenção de `pipeline/comparables.yaml`.
ARQUIVO = Path(__file__).resolve().parent / "segments.yaml"


class SegmentoDesconhecido(LookupError):
    """O modelo Ford não está no mapa. **Não é erro** — é o gatilho do Pesquisador.

    Existe como exceção nomeada, e não como `None`, porque os dois desfechos exigem telas
    diferentes: lista escrita mostra os concorrentes; lista desconhecida mostra o painel de
    descoberta com as fontes. Um `None` silencioso faria o segundo caso parecer o primeiro
    com zero concorrentes.
    """


@dataclass(frozen=True)
class Concorrente:
    """Um modelo concorrente. **Modelo**, não versão — a versão é escolhida pela régua."""

    marca: str
    modelo: str
    categoria_diferente: bool = False
    """Entra na conversa do showroom, mas não é do mesmo segmento.

    A Toro é o caso: monobloco, porte menor, e ainda assim o cliente que pergunta por
    Ranger pergunta por Toro no mesmo dia. Entra **marcada**; sem a marca, ela "ganharia"
    em preço por ser um carro de outra categoria."""
    motivo: str = ""
    """Por que está marcada. Obrigatório quando `categoria_diferente` — marca sem motivo
    é o sistema opinando."""

    @property
    def rotulo(self) -> str:
        return f"{self.marca} {self.modelo}".strip()


@dataclass(frozen=True)
class Segmento:
    """Um segmento e os modelos que competem nele."""

    id: str
    rotulo: str
    descricao: str = ""
    concorrentes: tuple[Concorrente, ...] = ()

    @property
    def do_mesmo_segmento(self) -> tuple[Concorrente, ...]:
        return tuple(c for c in self.concorrentes if not c.categoria_diferente)

    @property
    def de_categoria_diferente(self) -> tuple[Concorrente, ...]:
        return tuple(c for c in self.concorrentes if c.categoria_diferente)


@dataclass(frozen=True)
class Mapa:
    """O arquivo inteiro, já validado."""

    versao: str
    segmentos: dict[str, Segmento] = field(default_factory=dict)
    modelos_ford: dict[str, str] = field(default_factory=dict)
    """`modelo normalizado -> id do segmento`."""


def _concorrente_de(bruto: dict[str, Any], *, segmento: str) -> Concorrente:
    marca = str(bruto.get("marca") or "").strip()
    modelo = str(bruto.get("modelo") or "").strip()
    if not marca or not modelo:
        raise ValueError(f"{segmento}: concorrente sem marca ou modelo: {bruto!r}")
    diferente = bool(bruto.get("categoria_diferente"))
    motivo = str(bruto.get("motivo") or "").strip()
    if diferente and not motivo:
        # Marca sem motivo é o sistema opinando: a tela exibiria "categoria diferente" sem
        # ter o que responder a "por quê?". O mesmo contrato do `aviso` da comparabilidade.
        raise ValueError(
            f"{segmento}: {marca} {modelo} marcado como categoria diferente sem motivo"
        )
    return Concorrente(marca=marca, modelo=modelo, categoria_diferente=diferente, motivo=motivo)


@functools.lru_cache(maxsize=1)
def carregar(caminho: Path | None = None) -> Mapa:
    """Lê e valida `segments.yaml`. Em teste, `carregar.cache_clear()`."""
    dados = yaml.safe_load((caminho or ARQUIVO).read_text(encoding="utf-8")) or {}

    segmentos: dict[str, Segmento] = {}
    for sid, bruto in (dados.get("segmentos") or {}).items():
        segmentos[str(sid)] = Segmento(
            id=str(sid),
            rotulo=str(bruto.get("rotulo") or sid),
            descricao=str(bruto.get("descricao") or "").strip(),
            concorrentes=tuple(
                _concorrente_de(c, segmento=str(sid)) for c in (bruto.get("concorrentes") or [])
            ),
        )

    modelos: dict[str, str] = {}
    for modelo, sid in (dados.get("modelos_ford") or {}).items():
        if str(sid) not in segmentos:
            raise ValueError(f"modelo {modelo!r} aponta para segmento inexistente {sid!r}")
        modelos[normalize(str(modelo))] = str(sid)

    return Mapa(versao=str(dados.get("versao") or ""), segmentos=segmentos, modelos_ford=modelos)


def segmento_de(modelo: str, *, mapa: Mapa | None = None) -> Segmento:
    """O segmento de um modelo Ford. Levanta :class:`SegmentoDesconhecido` fora do mapa."""
    m = mapa or carregar()
    sid = m.modelos_ford.get(normalize(modelo))
    if sid is None:
        raise SegmentoDesconhecido(modelo)
    return m.segmentos[sid]


def concorrentes_de(modelo: str, *, mapa: Mapa | None = None) -> tuple[Concorrente, ...]:
    """Os modelos que competem com este modelo Ford, na ordem do arquivo.

    Os de categoria diferente vêm **por último**, e marcados. A ordem é informação: quem
    lê a lista de cima para baixo tem de encontrar primeiro quem briga de verdade.
    """
    seg = segmento_de(modelo, mapa=mapa)
    return seg.do_mesmo_segmento + seg.de_categoria_diferente


def consulta_de_descoberta(marca: str, modelo: str) -> str:
    """A busca que o Pesquisador faz quando o modelo não está no mapa.

    Uma frase, e em português: quem escreve sobre concorrência de picape no Brasil escreve
    em português, e a fonte que responde isso é imprensa especializada — tier 3. É a única
    parte deste módulo que produz informação de tier baixo, e a tela tem de dizer isso.
    """
    alvo = " ".join(p for p in (marca.strip(), modelo.strip()) if p)
    return f"concorrentes da {alvo}" if alvo else "concorrentes"
