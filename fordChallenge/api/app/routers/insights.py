"""`/insights/knowledge-health`, `/insights/coverage` e `/insights/divergences` (WP-33).

**Permissão: analista, gestor e admin — não o vendedor.** `exige(Acao.VER_INSIGHTS)` daria
acesso ao vendedor com escopo `PROPRIOS`, e aqui não há nada "próprio" a filtrar: o painel
mostra tier de fonte, fonte bloqueada e divergência com material interno da Ford, que
`docs/12` §6.6 classifica como informação interna que **não** pode aparecer ao cliente — e
a tela do vendedor está virada para o cliente. Por isso a guarda é por papel, e não pela
ação. Está registrado em `DECISOES_NOITE.md`.

O que estas rotas devolvem, e o que elas **não** devolvem: nenhum número aqui é
probabilidade de a ficha estar certa. Todo indicador sai com `texto_fixo` ao lado
("indicador operacional do MVP, não probabilidade de verdade") e com o **denominador**, e
o status vem com o **nome da regra** que o decidiu. Um "89% de confiança" seria estatística
sem estudo por trás.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import select

from api.app.deps import SessaoDep, UsuarioDep, exige, exige_papel
from api.app.errors import ProblemaHTTP
from api.app.models import Role, SpecValue, Version
from api.app.permissions import Acao, Escopo, escopo_de
from api.app.services import knowledge_health, winloss
from pipeline import health

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/insights", tags=["insights"])

SOMENTE_INTERNO = Depends(exige_papel(Role.ANALISTA, Role.GESTOR, Role.ADMIN))


# --------------------------------------------------------------------------- saídas
class CampoComProblemaOut(BaseModel):
    campo: str
    motivo: str
    detalhe: str = ""


class IndicadorOut(BaseModel):
    """Número **com** denominador. `fracao` é `None` quando o denominador é zero."""

    valor: int
    de: int
    fracao: float | None = None
    campos: list[CampoComProblemaOut] = []


class SaudeOut(BaseModel):
    version_id: str
    rotulo: str
    verificados: IndicadorOut
    desatualizados: IndicadorOut
    conflitos: IndicadorOut
    nao_confirmados: IndicadorOut
    fontes_bloqueadas: IndicadorOut
    ultima_atualizacao: str | None = None
    status: str
    regra_do_status: str
    explicacao_do_status: str
    limiar_de_dias: int
    texto_fixo: str
    regras: list[dict[str, str]]
    """Todas as regras, na ordem em que são testadas — para a tela poder abrir "por quê?"."""


class CoberturaOut(BaseModel):
    marca: str
    versoes_mapeadas: int
    versoes_com_ficha: int
    campos_com_fonte_oficial: IndicadorOut
    nao_encontrados: IndicadorOut
    divergencias: IndicadorOut
    por_campo: dict[str, IndicadorOut]


class ValorDivergenteOut(BaseModel):
    valor: Any = None
    origem: str
    tier: int | None = None


class DivergenciaOut(BaseModel):
    escopo: str
    version_id: str | None = None
    rotulo: str = ""
    campo: str | None = None
    valores: list[ValorDivergenteOut]
    gap: float | None = None
    detectado_em: str | None = None


REGRAS_PARA_A_TELA = [
    {"nome": r.nome, "status": r.status, "explicacao": r.explicacao}
    for r in health.REGRAS_DO_STATUS
]


# --------------------------------------------------------------------------- rotas
@router.get(
    "/knowledge-health",
    response_model=SaudeOut,
    summary="Saúde do conhecimento de uma versão, com a regra que decidiu o status",
    dependencies=[SOMENTE_INTERNO],
)
def saude_do_conhecimento(
    sessao: SessaoDep,
    version_id: str = Query(..., description="A versão a avaliar"),
    limiar_de_dias: int | None = Query(
        None,
        ge=1,
        le=3650,
        description=(
            "Sobrepõe o `HEALTH_STALE_DAYS` do ambiente. Serve para o gestor perguntar "
            "'e se eu exigisse reconferência a cada 7 dias?' sem mexer em config."
        ),
    ),
) -> SaudeOut:
    """Versão sem ficha devolve `INSUFICIENTE` com o motivo, **não** 404.

    A pergunta "esta versão tem informação boa?" tem resposta útil mesmo quando ninguém
    extraiu nada: "nenhum campo foi coletado" é o que faz alguém rodar a extração. Um 404
    ali obrigaria a tela a adivinhar a diferença entre "versão inexistente" e "versão sem
    ficha", que são coisas diferentes.
    """
    if sessao.get(Version, version_id) is None:
        raise ProblemaHTTP(404, f"Versão {version_id!r} não existe.")

    saude = knowledge_health.saude_da_versao(sessao, version_id, limiar_de_dias=limiar_de_dias)
    log.info(
        "insights.saude",
        version_id=version_id,
        status=saude.status,
        regra=saude.regra_do_status,
    )
    return SaudeOut(**saude.to_dict(), regras=REGRAS_PARA_A_TELA)


@router.get(
    "/coverage",
    response_model=list[CoberturaOut],
    summary="Cobertura por montadora, com os denominadores",
    dependencies=[SOMENTE_INTERNO],
)
def cobertura_por_montadora(sessao: SessaoDep) -> list[CoberturaOut]:
    """Quantas versões mapeadas, quantas com ficha, e o que falta em cada uma.

    Os dois números (`versoes_mapeadas` e `versoes_com_ficha`) aparecem lado a lado porque
    a diferença entre eles **é** a informação: "8 versões da S10 mapeadas, 1 com ficha" diz
    o tamanho do trabalho que falta; uma porcentagem esconderia isso.
    """
    return [CoberturaOut(**c.to_dict()) for c in knowledge_health.cobertura(sessao)]


@router.get(
    "/divergences",
    response_model=list[DivergenciaOut],
    summary="Divergências com os dois valores, as fontes e o gap",
    dependencies=[SOMENTE_INTERNO],
)
def listar_divergencias(
    sessao: SessaoDep,
    scope: str = Query(
        knowledge_health.OFICIAL_VS_IMPRENSA,
        description="`official_vs_press` ou `internal_vs_public`",
    ),
) -> list[DivergenciaOut]:
    """As duas visões de divergência, cada uma com os **dois** valores à vista.

    Nunca um "valor escolhido": expor a discordância é o produto, e um vencedor silencioso
    seria a única forma de perder a informação toda.
    """
    if scope not in knowledge_health.ESCOPOS:
        raise ProblemaHTTP(
            422,
            f"Escopo {scope!r} não existe. Válidos: {', '.join(knowledge_health.ESCOPOS)}.",
        )
    linhas = knowledge_health.divergencias(sessao, escopo=scope)
    return [DivergenciaOut(**linha) for linha in linhas]


@router.get(
    "/knowledge-health/versions",
    response_model=list[SaudeOut],
    summary="A saúde de todas as versões que já têm ficha",
    dependencies=[SOMENTE_INTERNO],
)
def saude_de_todas(sessao: SessaoDep) -> list[SaudeOut]:
    """O painel da tela Saúde: um cartão por versão com ficha.

    Só versões **com** ficha entram. As 19 do catálogo sem extração nenhuma sairiam todas
    `INSUFICIENTE` com o mesmo motivo, e 19 cartões idênticos empurrariam para fora da tela
    os poucos que dizem algo. O que falta coletar é a pergunta de `/coverage`, que responde
    com `versoes_mapeadas` contra `versoes_com_ficha`.
    """
    ids = sessao.exec(select(SpecValue.version_id).distinct()).all()
    saidas = [
        SaudeOut(
            **knowledge_health.saude_da_versao(sessao, version_id).to_dict(),
            regras=REGRAS_PARA_A_TELA,
        )
        for version_id in ids
    ]
    # Pior primeiro: o painel serve para achar o que precisa de atenção.
    ordem = {health.INSUFICIENTE: 0, health.REVISAR: 1, health.OK: 2}
    saidas.sort(key=lambda s: (ordem.get(s.status, 3), s.rotulo))
    return saidas


# ------------------------------------------------------------------ win/loss (WP-27)
@router.get(
    "/competitors",
    summary="Win/Loss por concorrente, com o n sempre à vista",
    dependencies=[Depends(exige(Acao.VER_INSIGHTS))],
)
def insights_por_concorrente(
    sessao: SessaoDep,
    usuario: UsuarioDep,
    ford_version: str | None = Query(None, description="Filtra pela versão Ford comparada"),
    since: dt.datetime | None = Query(None, description="Só sessões a partir desta data"),
) -> dict[str, Any]:
    """Por concorrente: n, desfechos, top motivos de perda e atributos decisivos.

    **Percentual só com n ≥ 20** (`docs/12` §6.5). Abaixo disso vêm contagens e um aviso
    dizendo por quê — "67% de perda" sobre três sessões parece estatística e é ruído.

    O vendedor vê **as próprias** sessões (escopo `proprios`): a taxa de fechamento de um
    colega não é informação dele. Ao contrário da Saúde do Conhecimento [D-103], aqui ele
    **entra** — o que ele vê é o resultado do próprio trabalho, não dado interno da Ford.
    """
    escopo = escopo_de(usuario.role, Acao.VER_INSIGHTS)
    resultado = winloss.painel(
        sessao,
        ford_version=ford_version,
        since=since,
        vendedor_id=usuario.id if escopo is Escopo.PROPRIOS else None,
    )
    return {
        **resultado.to_dict(),
        "escopo": escopo.value,
        # A tela precisa saber que está vendo um recorte, senão o vendedor lê o número
        # dele como se fosse o da concessionária.
        "aviso_de_escopo": (
            "você está vendo apenas as sessões que registrou" if escopo is Escopo.PROPRIOS else ""
        ),
    }


@router.get(
    "/summary",
    summary="Resumo geral das sessões, real e simulado separados",
    dependencies=[SOMENTE_INTERNO],
)
def resumo_de_insights(
    sessao: SessaoDep,
    usuario: UsuarioDep,
    since: dt.datetime | None = Query(None),
) -> dict[str, Any]:
    """Os totais. Real e simulado em blocos separados, cada um com o seu `n`.

    **Esta rota não é do vendedor**, e o contraste com `/competitors` é deliberado: lá ele
    vê o próprio recorte (escopo `proprios`, com o aviso), aqui o número é o da
    concessionária inteira — a taxa de fechamento agregada é conversa de gestor com
    analista. É o critério de aceite da WP-28 ("vendedor recebe 403 em
    `/insights/summary`"), e ele resolve a leitura ambígua de `docs/12` §6.5, que dá ao
    vendedor "só as próprias" sem dizer o que fazer com o agregado.
    """
    escopo = escopo_de(usuario.role, Acao.VER_INSIGHTS)
    dados = winloss.resumo(
        sessao,
        since=since,
        vendedor_id=usuario.id if escopo is Escopo.PROPRIOS else None,
    )
    return {**dados, "escopo": escopo.value}
