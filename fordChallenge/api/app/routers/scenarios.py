"""`POST /scenarios` — o simulador do "e se…?" (WP-35).

**Permissão: `consultar_fichas`**, a mesma de `/parity`, e por isso mesmo inclui o
vendedor: "e se a Hilux baixar 5%?" é a pergunta que o cliente faz **no showroom**, e a
resposta honesta ("aí ela passa a ser mais barata que a Ranger neste ponto") vale mais que
um silêncio. O que o vendedor não vê continua filtrado na apresentação, não no acesso.

**A rota não escreve nada.** Não é promessa: a montagem lê `spec_values`, o cálculo
acontece em `pipeline/scenarios.py` (que não importa `sqlmodel` nem `api.app`) e a resposta
é serializada. Não há `add`, `commit` nem `merge` neste módulo, e o teste da API confere a
contagem de `spec_values` antes e depois.

O `is_simulation=true` viaja no topo **e em cada painel de cenário**: a tela mostra os dois
lados juntos, e um aviso só no cabeçalho deixaria o painel hipotético sem etiqueta assim
que alguém rolasse a página — ou recortasse a imagem para um slide.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from api.app.deps import SessaoDep, exige
from api.app.errors import ProblemaHTTP
from api.app.models import Brand, VehicleModel, Version
from api.app.permissions import Acao
from api.app.services import scenario_service
from pipeline import scenarios
from pipeline.fit.engine import NeedsProfile
from pipeline.schema import campos_canonicos

log = structlog.get_logger(__name__)
router = APIRouter(tags=["simulador"])

#: Teto de versões por cenário. Cada uma custa uma ficha montada do banco, e a tela
#: compara "Realidade × Cenário" lado a lado — mais de seis colunas não cabem em nenhuma.
MAXIMO_DE_VERSOES = 6

#: Teto de overrides. Um cenário com dezenas de hipóteses não é mais um cenário: é outra
#: ficha técnica, e ninguém consegue ler o que causou o quê.
MAXIMO_DE_OVERRIDES = 10


class OverrideIn(BaseModel):
    """Uma hipótese. **Exatamente uma** das três formas — ver `pipeline/scenarios.py`."""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    campo: str
    delta_pct: float | None = None
    novo_valor: Any = None
    remover: bool = False


class CenarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version_ids: list[str] = Field(min_length=2)
    """As versões em jogo: uma Ford e ao menos um concorrente."""
    overrides: list[OverrideIn] = Field(default_factory=list)
    needs_profile: NeedsProfile | None = None
    """Sem perfil não há aderência, e a resposta **diz** isso em vez de omitir o bloco."""
    grupos: list[str] | None = None


@router.post(
    "/scenarios",
    summary='Simulador "e se…?": recalcula paridade, aderência e materialidade',
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
def simular(corpo: CenarioIn, sessao: SessaoDep) -> dict[str, Any]:
    """Clona o estado atual **em memória**, aplica os overrides e devolve os dois lados.

    Erros de override viram 422 com o motivo por extenso: "delta_pct 900% fora da faixa"
    é acionável, "cenário inválido" não.
    """
    if len(corpo.base_version_ids) > MAXIMO_DE_VERSOES:
        raise ProblemaHTTP(
            422,
            f"{len(corpo.base_version_ids)} versões no cenário; o máximo é "
            f"{MAXIMO_DE_VERSOES}. Cada versão custa uma ficha montada do banco.",
        )
    if len(corpo.overrides) > MAXIMO_DE_OVERRIDES:
        raise ProblemaHTTP(
            422,
            f"{len(corpo.overrides)} overrides; o máximo é {MAXIMO_DE_OVERRIDES}. Um "
            "cenário com dezenas de hipóteses não deixa ninguém ler o que causou o quê.",
        )

    versoes: list[Version] = []
    for version_id in corpo.base_version_ids:
        linha = sessao.get(Version, version_id)
        if linha is None:
            raise ProblemaHTTP(404, f"Versão {version_id!r} não existe.")
        versoes.append(linha)

    fords = [v for v in versoes if _marca_de(sessao, v) == "Ford"]
    concorrentes = [v for v in versoes if _marca_de(sessao, v) != "Ford"]
    if len(fords) != 1:
        raise ProblemaHTTP(
            422,
            f"o cenário precisa de exatamente uma versão Ford como referência (recebi "
            f"{len(fords)}). A comparação é sempre 'a Ford contra os outros'.",
        )
    if not concorrentes:
        raise ProblemaHTTP(422, "o cenário precisa de ao menos um concorrente além da versão Ford.")

    try:
        overrides = [
            scenarios.Override(
                version_id=o.version_id,
                campo=o.campo,
                delta_pct=o.delta_pct,
                novo_valor=o.novo_valor,
                remover=o.remover,
            )
            for o in corpo.overrides
        ]
        resultado = scenario_service.simular(
            sessao,
            ford=fords[0],
            concorrentes=concorrentes,
            overrides=overrides,
            perfil=corpo.needs_profile,
            grupos=corpo.grupos,
        )
    except scenarios.OverrideInvalido as erro:
        raise ProblemaHTTP(422, str(erro)) from erro

    log.info(
        "cenario_simulado",
        versoes=len(versoes),
        overrides=len(overrides),
        com_perfil=corpo.needs_profile is not None,
    )
    return resultado


def _marca_de(sessao: Session, version: Version) -> str:
    modelo = sessao.get(VehicleModel, version.model_id)
    if modelo is None:
        return ""
    marca = sessao.get(Brand, modelo.brand_id)
    return marca.nome if marca else ""


@router.get(
    "/scenarios/fields",
    summary="Campos que o simulador aceita alterar, com a forma de cada um",
    dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))],
)
def campos_do_simulador() -> dict[str, Any]:
    """O vocabulário do simulador, para a tela não adivinhar o que pode alterar.

    Sem esta rota a tela precisaria de uma lista de campos própria — e ela envelheceria em
    silêncio no dia em que o schema mudasse, oferecendo um slider para um campo que a API
    recusa.
    """
    # Filtrado pelo schema: um campo que saiu da ficha não pode continuar aparecendo
    # como slider na tela — ela ofereceria um controle que a API recusa.
    canonicos = set(campos_canonicos())
    numericos = sorted(c for c in _CAMPOS_NUMERICOS if c in canonicos)
    return {
        "delta_pct": {
            "campos": numericos,
            "minimo": -scenarios.DELTA_MAXIMO_PCT,
            "maximo": scenarios.DELTA_MAXIMO_PCT,
            "descricao": (
                "variação percentual sobre o valor atual; só em campo numérico com valor"
            ),
        },
        "novo_valor": {"descricao": "valor absoluto, em qualquer campo canônico"},
        "remover": {
            "descricao": (
                "o item deixa de existir na versão. O campo sai da comparação como "
                "`desconhecido`, nunca como empate."
            )
        },
        "rotulo": scenarios.ROTULO,
        "origem_dos_numeros": scenarios.ORIGEM,
        "maximo_de_overrides": MAXIMO_DE_OVERRIDES,
    }


#: Os campos em que um slider percentual faz sentido. Curto de propósito: `delta_pct` em
#: `airbags_qtd` daria "6,3 airbags", que é número que não existe no mundo.
_CAMPOS_NUMERICOS = (
    "preco_sugerido_brl",
    "preco_fipe_brl",
    "potencia_cv",
    "torque_nm",
    "capacidade_carga_kg",
    "capacidade_reboque_kg",
    "consumo_urbano_kml",
    "consumo_rodoviario_kml",
    "garantia_meses",
    "tanque_l",
)
