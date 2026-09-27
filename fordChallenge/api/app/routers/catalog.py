"""`/brands`, `/brands/{id}/models`, `/models/{id}/versions` — o catálogo.

`?lineup=current` merece explicação. `versions.in_lineup` diz se a versão está na linha
vigente, e `lineup_checked_at` diz **quando** isso foi conferido. Os dois andam juntos na
resposta porque o primeiro sem o segundo é uma afirmação sem validade: "a GR-Sport saiu de
linha" só vale sabendo se a checagem é de ontem ou de março.

Quando o filtro é `current` e a versão nunca foi conferida, ela **não** entra — e a
resposta diz quantas ficaram de fora por isso. Incluí-la afirmaria "está na linha" com
base em nada; excluí-la em silêncio faria parecer que a linha é menor do que é.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import select

from api.app.deps import SessaoDep, exige
from api.app.errors import ProblemaHTTP
from api.app.models import Brand, SpecValue, VehicleModel, Version
from api.app.permissions import Acao
from pipeline import sugestao as sug

router = APIRouter(tags=["catalogo"], dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))])


class MarcaOut(BaseModel):
    id: str
    nome: str


class ModeloOut(BaseModel):
    id: str
    brand_id: str
    nome: str
    segmento: str | None = None


class VersaoOut(BaseModel):
    id: str
    model_id: str
    nome_exato: str
    ano_modelo: int
    codigo_fipe: str | None = None
    in_lineup: bool
    lineup_checked_at: str | None = None


class ListaDeVersoes(BaseModel):
    """A lista, e o que o filtro deixou de fora — omissão nunca é silenciosa."""

    versions: list[VersaoOut]
    total: int
    filtro: str | None = None
    sem_checagem_de_linha: int = 0
    """Versões excluídas por nunca terem tido a linha vigente conferida."""


def _iso(valor: dt.datetime | None) -> str | None:
    return valor.isoformat() if isinstance(valor, dt.datetime) else None


@router.get("/brands", response_model=list[MarcaOut], summary="Lista marcas")
async def listar_marcas(sessao: SessaoDep) -> list[MarcaOut]:
    linhas = sessao.exec(select(Brand).order_by(Brand.nome)).all()
    return [MarcaOut(id=b.id, nome=b.nome) for b in linhas]


@router.get(
    "/brands/{brand_id}/models",
    response_model=list[ModeloOut],
    summary="Modelos de uma marca",
)
async def listar_modelos(brand_id: str, sessao: SessaoDep) -> list[ModeloOut]:
    if sessao.get(Brand, brand_id) is None:
        raise ProblemaHTTP(404, f"Marca {brand_id} não existe.")
    linhas = sessao.exec(
        select(VehicleModel).where(VehicleModel.brand_id == brand_id).order_by(VehicleModel.nome)
    ).all()
    return [
        ModeloOut(id=m.id, brand_id=m.brand_id, nome=m.nome, segmento=m.segmento) for m in linhas
    ]


@router.get(
    "/models/{model_id}/versions",
    response_model=ListaDeVersoes,
    summary="Versões de um modelo",
)
async def listar_versoes(
    model_id: str,
    sessao: SessaoDep,
    lineup: Literal["current", "all"] | None = Query(
        default=None,
        description="`current` devolve só a linha vigente **conferida**; sem o filtro, tudo.",
    ),
) -> ListaDeVersoes:
    if sessao.get(VehicleModel, model_id) is None:
        raise ProblemaHTTP(404, f"Modelo {model_id} não existe.")

    linhas = sessao.exec(
        select(Version)
        .where(Version.model_id == model_id)
        .order_by(Version.ano_modelo.desc(), Version.nome_exato)
    ).all()

    sem_checagem = 0
    if lineup == "current":
        elegiveis = []
        for v in linhas:
            if v.lineup_checked_at is None:
                # Nunca conferida: fora, e contada. Incluir afirmaria "está na linha" com
                # base em nada.
                sem_checagem += 1
                continue
            if v.in_lineup:
                elegiveis.append(v)
        linhas = elegiveis

    return ListaDeVersoes(
        versions=[
            VersaoOut(
                id=v.id,
                model_id=v.model_id,
                nome_exato=v.nome_exato,
                ano_modelo=v.ano_modelo,
                codigo_fipe=v.codigo_fipe,
                in_lineup=v.in_lineup,
                lineup_checked_at=_iso(v.lineup_checked_at),
            )
            for v in linhas
        ],
        total=len(linhas),
        filtro=lineup,
        sem_checagem_de_linha=sem_checagem,
    )


# --------------------------------------------------------------------------------------
# A caixa única: texto solto -> versão do catálogo
# --------------------------------------------------------------------------------------
class AnoOut(BaseModel):
    """Um ano-modelo de uma versão, e se há ficha salva dele."""

    ano_modelo: int
    version_id: str
    codigo_fipe: str | None = None
    in_lineup: bool = False
    tem_ficha: bool = False


class SugestaoOut(BaseModel):
    marca: str
    modelo: str
    versao: str
    texto: str
    """`"Chevrolet S10 High Country"` — o que a tela mostra na linha da sugestão."""
    score: float
    cobertura: float
    ano: AnoOut | None = None
    """O ano-modelo escolhido: o pedido, se houver ficha dele; senão o mais recente que tem."""
    anos: list[AnoOut] = []
    """Todos os anos desta versão. O seletor *"outro ano"* só oferece os de `tem_ficha`."""
    ano_pedido_sem_ficha: int | None = None
    """A pessoa nomeou um ano do qual não temos cópia. Gatilho do *"pesquisar agora?"*."""


class AlvoDePesquisaOut(BaseModel):
    """O que mandar ao Pesquisador: marca, modelo e versão separados."""

    marca: str
    modelo: str
    versao: str
    de_onde: str = "texto"
    """`catalogo` = marca e modelo vieram de um quase-acerto; `texto` = a frase foi
    partida por posição, e é chute. A tela usa isto para pedir confirmação, ou não."""


class SugestoesOut(BaseModel):
    """A melhor, as outras, e — quando não há melhor — por quê."""

    consulta: str
    ano_pedido: int | None = None
    melhor: SugestaoOut | None = None
    outras: list[SugestaoOut] = []
    empatadas: list[SugestaoOut] = []
    total: int = 0
    ambigua: bool = False
    vazia: bool = True
    """Nenhuma versão passou do limiar. O caminho da tela aqui é o Pesquisador."""
    desempate: str = "regra"
    """`regra` (rapidfuzz, reproduzível) ou `ia` (um empate desfeito pelo modelo)."""
    motivo: str = ""
    para_pesquisar: AlvoDePesquisaOut | None = None
    """O trio que o Pesquisador aceita, montado a partir da frase digitada.

    Vem **sempre**, e não só quando `vazia`: quem digita um carro que o catálogo tem
    também pode querer pesquisar de novo, e a tela não devia ter de remontar o trio."""


def _ano_out(a: sug.AnoDisponivel) -> AnoOut:
    return AnoOut(
        ano_modelo=a.ano_modelo,
        version_id=a.version_id,
        codigo_fipe=a.codigo_fipe,
        in_lineup=a.in_lineup,
        tem_ficha=a.tem_ficha,
    )


def _sugestao_out(s: sug.Sugestao) -> SugestaoOut:
    return SugestaoOut(
        marca=s.linha.marca,
        modelo=s.linha.modelo,
        versao=s.linha.versao,
        texto=s.linha.texto,
        score=round(s.score, 1),
        cobertura=round(s.cobertura, 3),
        ano=_ano_out(s.ano_escolhido) if s.ano_escolhido else None,
        anos=[_ano_out(a) for a in s.linha.anos],
        ano_pedido_sem_ficha=s.ano_pedido_sem_ficha,
    )


def linhas_do_catalogo(sessao) -> list[sug.Linha]:
    """O catálogo agrupado por versão, com os anos e o que tem ficha.

    Uma consulta por tabela, não uma por versão: o catálogo é pequeno hoje (dezenas de
    linhas), e a caixa de busca dispara a cada tecla. Um N+1 aqui não apareceria na
    demonstração e apareceria em produção, que é o pior momento para descobrir.
    """
    linhas = sessao.exec(
        select(Version, VehicleModel, Brand)
        .join(VehicleModel, VehicleModel.id == Version.model_id)
        .join(Brand, Brand.id == VehicleModel.brand_id)
    ).all()
    # `exec` com uma coluna só devolve escalares, não tuplas de um elemento.
    com_ficha = set(sessao.exec(select(SpecValue.version_id).distinct()).all())

    from pipeline.version_names import nome_canonico_de_versao

    # Um alias comprovado não pode reaparecer como segunda versão na conversa. Bancos
    # antigos podem ainda ter as duas linhas até a migração de dados rodar; por isso a
    # leitura também agrupa pela chave canônica e, no mesmo ano, prefere a linha com ficha.
    agrupadas: dict[
        tuple[str, str, str], dict[int, tuple[sug.AnoDisponivel, tuple[bool, bool, bool, str]]]
    ] = {}
    for versao, modelo, marca in linhas:
        nome = nome_canonico_de_versao(modelo.nome, versao.nome_exato)
        chave = (marca.nome, modelo.nome, nome)
        ano = sug.AnoDisponivel(
            ano_modelo=versao.ano_modelo,
            version_id=versao.id,
            codigo_fipe=versao.codigo_fipe,
            in_lineup=versao.in_lineup,
            tem_ficha=versao.id in com_ficha,
        )
        prioridade = (
            ano.tem_ficha,
            bool(ano.codigo_fipe),
            ano.in_lineup,
            str(versao.lineup_checked_at or ""),
        )
        por_ano = agrupadas.setdefault(chave, {})
        atual = por_ano.get(versao.ano_modelo)
        if atual is None or prioridade > atual[1]:
            por_ano[versao.ano_modelo] = (ano, prioridade)
    return [
        sug.Linha(
            marca=marca,
            modelo=modelo,
            versao=nome,
            anos=tuple(sorted((item[0] for item in anos.values()), key=lambda a: -a.ano_modelo)),
        )
        for (marca, modelo, nome), anos in agrupadas.items()
    ]


@router.get(
    "/catalog/suggest",
    response_model=SugestoesOut,
    summary="Sugere versões a partir de texto livre",
)
async def sugerir_versoes(
    sessao: SessaoDep,
    q: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description='O que a pessoa digitou: `"S10 High"`, `"hilux srx"`, `"raptor 2025"`.',
    ),
    limite: int = Query(default=sug.LIMITE_PADRAO, ge=1, le=20),
    desempatar_com_ia: bool = Query(
        default=False,
        description=(
            "No empate, gasta **uma** chamada de LLM para escolher. Sem chave, ou com "
            "`LLM_FAKE=1`, o empate fica de pé e a resposta diz isso em `motivo`."
        ),
    ),
) -> SugestoesOut:
    resultado = sug.sugerir(q, linhas_do_catalogo(sessao), limite=limite)
    if desempatar_com_ia:
        resultado = sug.desempatar(resultado)
    return SugestoesOut(
        consulta=resultado.consulta,
        ano_pedido=resultado.ano_pedido,
        melhor=_sugestao_out(resultado.melhor) if resultado.melhor else None,
        outras=[_sugestao_out(s) for s in resultado.outras],
        empatadas=[_sugestao_out(s) for s in resultado.empatadas],
        total=resultado.total,
        ambigua=resultado.ambigua,
        vazia=resultado.vazia,
        desempate=resultado.desempate,
        motivo=resultado.motivo,
        para_pesquisar=AlvoDePesquisaOut(**vars(sug.alvo_de_pesquisa(resultado))),
    )
