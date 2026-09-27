"""`/comparables` e `/parity` — o Comparable Set e a Matriz de Paridade (WP-32).

**Permissão: `consultar_fichas`**, que inclui o vendedor. É deliberado: a matriz de
paridade é justamente a tela de que o vendedor precisa no showroom, e o que o modo showroom
esconde dele (tier, confiança, dado interno) é filtrado na apresentação — não no acesso.

Duas coisas que estas rotas fazem e que uma versão "mais simples" não faria:

* **o aviso de comparabilidade viaja junto da matriz**, no mesmo objeto. Se ele viesse de
  outra chamada, uma tela poderia desenhar a tabela antes de a segunda resposta chegar — e
  a comparação apareceria por um instante sem a ressalva. Numa demo, esse instante é a
  tela que fica no vídeo;
* **`desconhecido` é contado e devolvido**, com o `motivo_tipo`. A tentação é filtrar as
  células desconhecidas para a tabela "ficar limpa"; seria esconder exatamente a lacuna
  que o analista precisa fechar antes da reunião.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import select

from api.app.deps import SessaoDep, exige
from api.app.errors import ProblemaHTTP
from api.app.models import Brand, VehicleModel, Version
from api.app.permissions import Acao
from api.app.services import spec_assembler
from pipeline import comparables, parity

log = structlog.get_logger(__name__)
router = APIRouter(tags=["paridade"])

#: Teto de concorrentes por chamada. Cada um custa uma ficha montada do banco; sem teto,
#: uma URL com trinta ids viraria trinta montagens numa requisição só.
MAXIMO_DE_CONCORRENTES = 6


# --------------------------------------------------------------------------- saídas
class CriterioOut(BaseModel):
    id: str
    rotulo: str
    estado: str
    valor_ford: Any = None
    valor_concorrente: Any = None
    motivo: str = ""


class ComparabilidadeOut(BaseModel):
    """`k/n` e os nomes. Nunca porcentagem — ver `pipeline/comparables.py`."""

    version_id: str
    rotulo: str
    comparavel: bool
    criterios_atendidos: int
    criterios_avaliaveis: int
    total_de_criterios: int
    resumo: str
    nao_atendidos: list[str]
    sem_dados: list[str]
    detalhes: list[CriterioOut]
    aviso: str
    versao_dos_criterios: str


class FlagDeCargaOut(BaseModel):
    aplicavel: bool
    valor: bool | None = None
    capacidade_kg: float | None = None
    texto: str = ""
    etiqueta: str = comparables.ETIQUETA_DA_FLAG_DE_CARGA
    motivo: str = ""


class CandidatoOut(BaseModel):
    """Uma versão Ford candidata a comparar com o concorrente pedido."""

    version_id: str
    rotulo: str
    comparabilidade: ComparabilidadeOut


class CelulaOut(BaseModel):
    campo: str
    grupo: str
    estado: str
    valor_ford: Any = None
    valor_concorrente: Any = None
    unidade: str | None = None
    motivo: str = ""
    motivo_tipo: str = ""
    diferenca: float | None = None
    evidence_id_ford: str | None = None
    evidence_id_concorrente: str | None = None


class ContagemOut(BaseModel):
    vantagem: int
    paridade: int
    gap: int
    desconhecido: int
    total: int
    comparados: int


class ColunaOut(BaseModel):
    version_id: str
    rotulo: str
    celulas: list[CelulaOut]
    contagem: ContagemOut
    comparabilidade: ComparabilidadeOut
    flag_de_carga: FlagDeCargaOut


class ParidadeOut(BaseModel):
    ford_version: str
    ford_rotulo: str
    colunas: list[ColunaOut]
    legenda: dict[str, str]
    flag_de_carga_ford: FlagDeCargaOut
    versao_dos_criterios: str


# --------------------------------------------------------------------------- ajudantes
def _versao(sessao, version_id: str) -> Version:
    linha = sessao.get(Version, version_id)
    if linha is None:
        raise ProblemaHTTP(404, f"Versão {version_id!r} não existe.")
    return linha


def _rotulo(sessao, version: Version) -> str:
    modelo = sessao.get(VehicleModel, version.model_id)
    marca = sessao.get(Brand, modelo.brand_id) if modelo else None
    partes = [p for p in (marca.nome if marca else "", modelo.nome if modelo else "") if p]
    return " ".join([*partes, version.nome_exato]).strip()


def _e_da_ford(sessao, version: Version) -> bool:
    modelo = sessao.get(VehicleModel, version.model_id)
    marca = sessao.get(Brand, modelo.brand_id) if modelo else None
    return bool(marca and marca.nome.strip().lower() == "ford")


def _comparabilidade_out(
    resultado: comparables.Comparabilidade, *, version_id: str, rotulo: str
) -> ComparabilidadeOut:
    dados = resultado.to_dict()
    return ComparabilidadeOut(version_id=version_id, rotulo=rotulo, **dados)


def _flag_de_carga(spec, rotulo: str) -> FlagDeCargaOut:
    """A flag dos 1.000 kg, com a **fonte** que o texto fixo exige.

    Sem a URL da evidência o texto ficaria "(fonte não informada)", que é honesto mas
    inútil: a frase existe para alguém poder conferir o número antes de falar de
    enquadramento fiscal com a Ford.
    """
    campo = spec.get("dimensoes.capacidade_carga_kg")
    if campo is None:
        return FlagDeCargaOut(**comparables.flag_de_carga(None).to_dict())
    fonte = campo.evidences[0].source_url if campo.evidences else f"ficha de {rotulo}"
    return FlagDeCargaOut(**comparables.flag_de_carga(campo.value, fonte=fonte).to_dict())


def _atributos(sessao, version: Version, spec) -> dict[str, Any]:
    return comparables.atributos_de_spec(spec, versao=version.nome_exato)


def _avaliar_par(sessao, ford: Version, concorrente: Version, spec_ford, spec_conc):
    return comparables.avaliar(
        _atributos(sessao, ford, spec_ford),
        _atributos(sessao, concorrente, spec_conc),
    )


# --------------------------------------------------------------------------- rotas
@router.get(
    "/comparables",
    response_model=list[CandidatoOut],
    summary="Versões Ford candidatas a comparar com a versão pedida",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
def listar_comparaveis(
    sessao: SessaoDep,
    version_id: str = Query(..., description="A versão (normalmente do concorrente)"),
    incluir_nao_comparaveis: bool = Query(
        True,
        description=(
            "Manter na lista os pares reprovados, com o aviso. Desligar esconde o par "
            "que o usuário talvez queira comparar mesmo assim."
        ),
    ),
) -> list[CandidatoOut]:
    """As versões Ford em linha, **ordenadas por critérios atendidos**.

    O par reprovado continua na lista por padrão, com o aviso: `docs/12` §3 diz que o
    produto não esconde informação de quem sabe o que está fazendo — esconder o par
    Raptor × Hilux tiraria do analista a possibilidade de comparar as duas de propósito,
    que é uma pergunta legítima (é o critério da própria Ford na cena de validação).
    """
    alvo = _versao(sessao, version_id)
    spec_alvo = spec_assembler.montar(sessao, alvo.id)

    fords = sessao.exec(
        select(Version)
        .join(VehicleModel, VehicleModel.id == Version.model_id)
        .join(Brand, Brand.id == VehicleModel.brand_id)
        .where(Brand.nome == "Ford", Version.id != alvo.id)
    ).all()

    candidatos: list[CandidatoOut] = []
    for ford in fords:
        spec_ford = spec_assembler.montar(sessao, ford.id)
        resultado = _avaliar_par(sessao, ford, alvo, spec_ford, spec_alvo)
        if not incluir_nao_comparaveis and not resultado.comparavel:
            continue
        candidatos.append(
            CandidatoOut(
                version_id=ford.id,
                rotulo=_rotulo(sessao, ford),
                comparabilidade=_comparabilidade_out(
                    resultado, version_id=ford.id, rotulo=_rotulo(sessao, ford)
                ),
            )
        )

    # Mais critérios atendidos primeiro; empate resolvido pelo rótulo, para a ordem ser
    # estável entre chamadas (lista que muda de ordem sozinha parece dado mudando).
    candidatos.sort(
        key=lambda c: (
            -c.comparabilidade.criterios_atendidos,
            not c.comparabilidade.comparavel,
            c.rotulo,
        )
    )
    return candidatos


@router.get(
    "/parity",
    response_model=ParidadeOut,
    summary="Matriz de paridade: por campo, vantagem, paridade, gap ou desconhecido",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
def matriz_de_paridade(
    sessao: SessaoDep,
    ford_version: str = Query(..., description="A versão Ford de referência"),
    competitors: str = Query(
        ..., description="Ids das versões concorrentes, separados por vírgula"
    ),
    grupos: str | None = Query(
        None, description="Filtro por dimensão do schema (ex.: motorizacao,desempenho)"
    ),
) -> ParidadeOut:
    """A matriz, com o aviso de comparabilidade **dentro** de cada coluna.

    A versão de referência não precisa ser da Ford para a conta funcionar, e a rota não
    exige que seja: comparar dois concorrentes entre si é pergunta legítima de analista. O
    nome do parâmetro segue o contrato da spec, e o rótulo devolvido diz de quem é a
    ficha da esquerda.
    """
    referencia = _versao(sessao, ford_version)
    ids = [i.strip() for i in competitors.split(",") if i.strip()]
    if not ids:
        raise ProblemaHTTP(422, "Informe ao menos um concorrente em `competitors`.")
    if len(ids) > MAXIMO_DE_CONCORRENTES:
        raise ProblemaHTTP(
            422,
            f"Máximo de {MAXIMO_DE_CONCORRENTES} concorrentes por chamada; "
            f"{len(ids)} foram pedidos.",
        )
    if referencia.id in ids:
        raise ProblemaHTTP(422, "A versão de referência não pode estar entre os concorrentes.")

    lista_de_grupos = [g.strip() for g in grupos.split(",")] if grupos else None
    if lista_de_grupos:
        desconhecidos = sorted(set(lista_de_grupos) - set(parity.GRUPO_DO_CAMPO.values()))
        if desconhecidos:
            raise ProblemaHTTP(
                422,
                f"Dimensão inexistente: {', '.join(desconhecidos)}. "
                f"Válidas: {', '.join(sorted(set(parity.GRUPO_DO_CAMPO.values())))}.",
            )

    spec_ref = spec_assembler.montar(sessao, referencia.id)
    rotulo_ref = _rotulo(sessao, referencia)

    colunas: list[ColunaOut] = []
    for version_id in ids:
        concorrente = _versao(sessao, version_id)
        spec_conc = spec_assembler.montar(sessao, concorrente.id)
        rotulo = _rotulo(sessao, concorrente)

        coluna = parity.montar_coluna(
            spec_ref,
            spec_conc,
            version_id=concorrente.id,
            rotulo=rotulo,
            grupos=lista_de_grupos,
        )
        resultado = _avaliar_par(sessao, referencia, concorrente, spec_ref, spec_conc)
        colunas.append(
            ColunaOut(
                version_id=concorrente.id,
                rotulo=rotulo,
                celulas=[CelulaOut(**c.to_dict()) for c in coluna.celulas],
                contagem=ContagemOut(**coluna.contagem.to_dict()),
                comparabilidade=_comparabilidade_out(
                    resultado, version_id=concorrente.id, rotulo=rotulo
                ),
                flag_de_carga=_flag_de_carga(spec_conc, rotulo),
            )
        )

    log.info(
        "paridade.montada",
        referencia=referencia.id,
        concorrentes=len(colunas),
        e_da_ford=_e_da_ford(sessao, referencia),
    )
    return ParidadeOut(
        ford_version=referencia.id,
        ford_rotulo=rotulo_ref,
        colunas=colunas,
        legenda=dict(parity.LEGENDA),
        flag_de_carga_ford=_flag_de_carga(spec_ref, rotulo_ref),
        versao_dos_criterios=comparables.carregar().versao,
    )
