"""`/resolutions`, `/attributes`, `/evidences`, `/snapshots` e `/comparisons`.

Os recursos menores de `docs/04`, juntos porque cada um é uma rota ou duas e espalhá-los
em seis arquivos de vinte linhas não ajudaria ninguém a achá-los.

Duas decisões de contrato valem destaque:

As rotas de `/alerts` sairam daqui na WP-25: elas ganharam impacto, reacao por papel
e as duas evidencias, e vivem em `api/app/routers/radar.py`.

* **`/attributes/resolve` devolve `extra_slug` quando não reconhece o termo**, e não 404.
  "Não temos campo canônico para isto" é resposta útil: o atributo vai para `extras` e é
  extraído com as mesmas regras de status. Um 404 faria o cliente descartar a pergunta;
* **`/evidences/{id}` e `/snapshots/{id}` exigem `ver_evidencias_brutas`**, que o vendedor
  não tem (`docs/12` §6.6). O vendedor vê fonte e data na ficha — o que ele mostra ao
  cliente. O texto bruto capturado é material de auditoria, e é onde apareceriam trechos
  de página que ninguém revisou para exibição.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from api.app.deps import SessaoDep, exige
from api.app.errors import ProblemaHTTP
from api.app.models import Evidence, Snapshot, Version
from api.app.permissions import Acao
from api.app.services import fit_service, spec_assembler
from pipeline import ontology, resolver
from pipeline.fit.engine import NeedsProfile
from pipeline.schema import GRUPOS, UNIDADE_CANONICA, caminho_canonico

router = APIRouter(tags=["dominio"])


# ------------------------------------------------------------------- resoluções
class ResolucaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marca: str = Field(min_length=1, max_length=80)
    modelo: str = Field(min_length=1, max_length=80)
    versao: str = Field(min_length=1, max_length=160)


class ResolucaoOut(BaseModel):
    status: str
    matched_version: str | None = None
    alternatives: list[str] = []
    score: float = 0.0
    mensagem: str = ""
    fipe_last_year: int | None = None
    sources: list[str] = []
    bloqueadas: list[str] = []
    pendencias: list[str] = []


@router.post(
    "/resolutions",
    response_model=ResolucaoOut,
    summary="Passo 0: resolve marca+modelo+versão contra a linha vigente",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
async def resolver_versao(corpo: ResolucaoIn) -> ResolucaoOut:
    """Chama `pipeline.resolver`. **200 também para `versao_inexistente`.**

    Não é erro do cliente: ele perguntou certo e a resposta é que a versão saiu de linha.
    Um 404 aqui faria a tela mostrar "não encontrado" onde o produto tem algo muito melhor
    a dizer — "saiu de linha; a atual é a SRX Plus".
    """
    r = resolver.resolve(corpo.marca, corpo.modelo, corpo.versao)
    return ResolucaoOut(
        status=r.status,
        matched_version=r.matched_version,
        alternatives=list(r.alternatives),
        score=round(r.score, 2),
        mensagem=r.mensagem,
        fipe_last_year=r.fipe_last_year,
        sources=list(r.sources),
        bloqueadas=list(r.bloqueadas),
        pendencias=list(r.pendencias),
    )


# --------------------------------------------------------------------- atributos
class AtributoOut(BaseModel):
    campo: str
    caminho: str
    grupo: str
    unidade: str | None = None


class ResolverAtributoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=200)
    marca: str | None = None


class AtributoResolvidoOut(BaseModel):
    canonical: str | None = None
    caminho: str | None = None
    extra_slug: str | None = None
    score: float


@router.get(
    "/attributes",
    response_model=list[AtributoOut],
    summary="Os campos canônicos da ficha",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
async def listar_atributos() -> list[AtributoOut]:
    return [
        AtributoOut(
            campo=campo,
            caminho=f"{grupo}.{campo}",
            grupo=grupo,
            unidade=UNIDADE_CANONICA.get(campo),
        )
        for grupo, campos in GRUPOS.items()
        for campo in campos
    ]


@router.post(
    "/attributes/resolve",
    response_model=AtributoResolvidoOut,
    summary="Texto livre → campo canônico (ou slug de extra)",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
async def resolver_atributo(corpo: ResolverAtributoIn) -> AtributoResolvidoOut:
    """`{"text": "cavalos"}` → `potencia_cv`. Sem match, devolve `extra_slug`.

    Devolver `extra_slug` em vez de 404 é o que mantém a pergunta do usuário viva: o
    atributo desconhecido vira campo de `extras` e é extraído com as mesmas regras de
    status e grounding. Nada do que se perguntou é descartado.
    """
    campo, score = ontology.resolve_attribute(corpo.text, marca=corpo.marca)
    if campo:
        return AtributoResolvidoOut(
            canonical=campo,
            caminho=caminho_canonico(campo),
            score=round(score, 2),
        )
    # `extras.<slug>` e a forma que `pipeline/normalize.resolver_atributo` usa.
    return AtributoResolvidoOut(
        extra_slug=f"extras.{ontology.slugify(corpo.text)}", score=round(score, 2)
    )


# ------------------------------------------------------------ evidências e snapshots
class EvidenciaOut(BaseModel):
    id: str
    source_url: str
    tier: int
    quote: str
    offset: int | None = None
    captured_at: str
    raw_value: str | None = None
    page: int | None = None
    snapshot_id: str | None = None


class SnapshotOut(BaseModel):
    id: str
    source_id: str | None = None
    url: str
    http_status: int | None = None
    captured_at: str
    sha256: str | None = None
    text_url: str | None = None
    bytes_texto: int | None = None


@router.get(
    "/evidences/{evidence_id}",
    response_model=EvidenciaOut,
    summary="Uma evidência (auditoria)",
    dependencies=[Depends(exige(Acao.VER_EVIDENCIAS_BRUTAS))],
)
async def obter_evidencia(evidence_id: str, sessao: SessaoDep) -> EvidenciaOut:
    linha = sessao.get(Evidence, evidence_id)
    if linha is None:
        raise ProblemaHTTP(404, f"Evidência {evidence_id} não existe.")
    return EvidenciaOut(
        id=linha.id,
        source_url=linha.source_url,
        tier=linha.tier,
        quote=linha.quote,
        offset=linha.offset,
        captured_at=linha.captured_at.isoformat(),
        raw_value=linha.raw_value,
        page=linha.page,
        snapshot_id=linha.snapshot_id,
    )


@router.get(
    "/snapshots/{snapshot_id}",
    response_model=SnapshotOut,
    summary="Metadados de um snapshot (auditoria)",
    dependencies=[Depends(exige(Acao.VER_EVIDENCIAS_BRUTAS))],
)
async def obter_snapshot(snapshot_id: str, sessao: SessaoDep) -> SnapshotOut:
    """Metadados e o **caminho** do texto, não o texto.

    Uma página salva tem centenas de KB; devolvê-la inline faria a rota de auditoria ser
    a mais pesada da API. `text_url` aponta para o arquivo.
    """
    linha = sessao.get(Snapshot, snapshot_id)
    if linha is None:
        raise ProblemaHTTP(404, f"Snapshot {snapshot_id} não existe.")
    return SnapshotOut(
        id=linha.id,
        source_id=linha.source_id,
        url=linha.url,
        http_status=linha.http_status,
        captured_at=linha.captured_at.isoformat(),
        sha256=linha.sha256,
        text_url=linha.text_path,
        bytes_texto=linha.bytes_texto if hasattr(linha, "bytes_texto") else None,
    )


# ------------------------------------------------------------------- comparações
class ComparacaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_vehicle_id: str
    competitor_ids: list[str] = Field(min_length=1, max_length=6)
    attributes: list[str] | None = None
    needs_profile: NeedsProfile | None = None
    """WP-26, **opcional**: sem ele a resposta é a matriz simples do v1."""
    consumo_informado_kml: dict[str, float] | None = None
    """`{version_id: km/l}` para o vendedor suprir o consumo que nenhuma fonte tem."""


@router.post(
    "/comparisons",
    summary="Matriz de comparação: cells[i][j] é um SpecField com `diff`",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
async def comparar(corpo: ComparacaoIn, sessao: SessaoDep) -> dict:
    """`diff=true` quando os valores diferem **ou um lado está vazio**.

    O "ou" é a parte que importa: "o concorrente tem e nós não sabemos" é tão acionável
    quanto uma diferença numérica, e tratar vazio como igual esconderia justamente a
    lacuna que o vendedor precisa conhecer antes da conversa.
    """
    for vid in [corpo.base_vehicle_id, *corpo.competitor_ids]:
        if sessao.get(Version, vid) is None:
            raise ProblemaHTTP(404, f"Veículo {vid} não existe.")
    if corpo.base_vehicle_id in corpo.competitor_ids:
        raise ProblemaHTTP(422, "O veículo base não pode estar entre os concorrentes.")

    resposta = spec_assembler.matriz_de_comparacao(
        sessao,
        base_version_id=corpo.base_vehicle_id,
        concorrentes=corpo.competitor_ids,
        attributes=corpo.attributes,
    )

    # `needs_profile` é opcional, e a ausência dele **não** muda a matriz: quem só quer a
    # ficha lado a lado continua recebendo exatamente o que recebia no v1. O bloco `fit`
    # entra ao lado, sem substituir nada.
    if corpo.needs_profile is not None:
        resposta["fit"] = fit_service.montar(
            sessao,
            base_version_id=corpo.base_vehicle_id,
            concorrentes=corpo.competitor_ids,
            perfil=corpo.needs_profile,
            consumo_informado=corpo.consumo_informado_kml or {},
        )
    return resposta


@router.get(
    "/dimensions",
    summary="As dimensões do Need Engine, com os campos de cada uma",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
async def listar_dimensoes() -> dict:
    """A tabela de `pipeline/fit/dimensions.yaml`, como a tela a desenha.

    Vem da API e não de uma constante no front-end para haver **uma** tabela: um segundo
    mapa campo → dimensão no TypeScript divergiria do primeiro na primeira mudança, e a
    tela passaria a explicar a nota por uma regra que o back-end não usou.
    """
    return fit_service.dimensoes_para_a_tela()
