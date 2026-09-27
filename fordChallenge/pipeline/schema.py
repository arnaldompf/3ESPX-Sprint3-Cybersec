"""Schema canônico do SpecRadar — `docs/03_SCHEMA_CANONICO.md` em código.

Toda ficha, de qualquer veículo, é um `StandardSpec` com **os mesmos campos, na mesma
ordem**. Campo ausente nunca é omitido: aparece com `status` explicativo.

Regras invioláveis materializadas aqui:

* `value` é `None` sempre que `status` ∈ {`nao_disponivel`, `nao_encontrado`, `pendente`}
  (os dois vazios são estados distintos, não sinônimos de "sem valor").
* `status` ∈ {`verificado`, `divergente`} exige pelo menos uma evidência — nenhum valor
  sem evidência.
* `divergente` preserva **todos** os valores em `conflicts`; o schema não escolhe vencedor.

A validação formal é o `schema/canonical_spec.schema.json`: `StandardSpec.to_json()`
valida contra ele e levanta em caso de divergência, de modo que o JSON Schema e os
modelos Pydantic não podem se separar em silêncio.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "canonical_spec.schema.json"
SCHEMA_VERSION = "1.0"


class Status(StrEnum):
    """Estados de um campo. Os dois vazios são distintos por decisão de produto."""

    VERIFICADO = "verificado"
    NAO_VERIFICADO = "nao_verificado"  # extraído mas o quote não foi localizado no texto
    NAO_DISPONIVEL = "nao_disponivel"  # a fonte oficial afirma que o item não existe
    NAO_ENCONTRADO = "nao_encontrado"  # nenhuma fonte consultada menciona
    DIVERGENTE = "divergente"  # fontes discordam; todos os valores preservados
    PENDENTE = "pendente"  # ainda não coletado


#: Status em que `value` obrigatoriamente é `None`.
STATUS_SEM_VALOR: frozenset[Status] = frozenset(
    {Status.NAO_DISPONIVEL, Status.NAO_ENCONTRADO, Status.PENDENTE}
)
#: Status que exigem ao menos uma evidência.
STATUS_COM_EVIDENCIA: frozenset[Status] = frozenset({Status.VERIFICADO, Status.DIVERGENTE})

#: Confiança base por tier (docs/02, item 8 do fluxo de extração).
CONFIANCA_POR_TIER: dict[int, float] = {1: 0.90, 2: 0.85, 3: 0.60, 4: 0.40, 5: 0.20}

# --------------------------------------------------------------------------------------
# Grupos e campos. A ordem deste dicionário é a ordem de exibição da ficha — mudá-la
# muda a saída do produto, então ela é parte do contrato.
# --------------------------------------------------------------------------------------
GRUPOS: dict[str, tuple[str, ...]] = {
    "identificacao": (
        "marca",
        "modelo",
        "versao",
        "ano_modelo",
        "codigo_fipe",
        "carroceria",
        "segmento",
    ),
    "motorizacao": (
        "motor_descricao",
        "cilindros",
        "deslocamento_l",
        "combustivel",
        "aspiracao",
        "potencia_cv",
        "potencia_rpm",
        "torque_nm",
        "torque_rpm",
    ),
    "transmissao": ("tipo", "numero_marchas", "paddle_shifters"),
    "tracao": ("tipo_tracao", "reduzida", "bloqueio_diferencial"),
    "chassi": (
        "suspensao_dianteira",
        "suspensao_traseira",
        "amortecedores",
        "direcao",
        "freios_dianteiros",
        "freios_traseiros",
    ),
    "desempenho": (
        "aceleracao_0_100_s",
        "velocidade_maxima_kmh",
        "consumo_urbano_kml",
        "consumo_rodoviario_kml",
    ),
    "modos": ("modos_conducao", "modos_direcao", "modos_escapamento", "modos_amortecedor"),
    "exterior": (
        "farois_tipo",
        "farois_neblina",
        "rodas_aro_pol",
        "rodas_material",
        "pneus_medida",
        "pneus_tipo",
    ),
    "dimensoes": (
        "comprimento_mm",
        "largura_mm",
        "altura_mm",
        "entre_eixos_mm",
        "capacidade_carga_kg",
        "capacidade_reboque_kg",
        "tanque_l",
    ),
    "seguranca": ("adas_nome_comercial", "adas_itens", "airbags_qtd", "camera_360"),
    "comercial": (
        "preco_sugerido_brl",
        "preco_data",
        "preco_fipe_brl",
        "fipe_referencia",
        "garantia_meses",
    ),
}

#: Unidade canônica por campo. `None` = campo sem unidade (texto, booleano, lista).
UNIDADE_CANONICA: dict[str, str | None] = {
    "deslocamento_l": "l",
    "potencia_cv": "cv",
    "potencia_rpm": "rpm",
    "torque_nm": "Nm",
    "torque_rpm": "rpm",
    "aceleracao_0_100_s": "s",
    "velocidade_maxima_kmh": "km/h",
    "consumo_urbano_kml": "km/l",
    "consumo_rodoviario_kml": "km/l",
    "rodas_aro_pol": "pol",
    "comprimento_mm": "mm",
    "largura_mm": "mm",
    "altura_mm": "mm",
    "entre_eixos_mm": "mm",
    "capacidade_carga_kg": "kg",
    "capacidade_reboque_kg": "kg",
    "tanque_l": "l",
    "preco_sugerido_brl": "BRL",
    "preco_fipe_brl": "BRL",
    "garantia_meses": "meses",
}

#: Campos cujo valor canônico é uma lista de tokens (comparados como conjunto).
CAMPOS_LISTA: frozenset[str] = frozenset(
    {
        "modos_conducao",
        "modos_direcao",
        "modos_escapamento",
        "modos_amortecedor",
        "adas_itens",
    }
)

#: Campos booleanos.
CAMPOS_BOOL: frozenset[str] = frozenset(
    {"paddle_shifters", "reduzida", "bloqueio_diferencial", "camera_360", "farois_neblina"}
)


def campos_canonicos() -> tuple[str, ...]:
    """Todos os nomes de campo, na ordem da ficha."""
    return tuple(campo for campos in GRUPOS.values() for campo in campos)


def grupo_de(campo: str) -> str | None:
    """Grupo a que um campo canônico pertence (`None` se não for canônico)."""
    for grupo, campos in GRUPOS.items():
        if campo in campos:
            return grupo
    return None


def caminho_canonico(campo: str) -> str | None:
    """`"paddle_shifters"` -> `"transmissao.paddle_shifters"`."""
    grupo = grupo_de(campo)
    return f"{grupo}.{campo}" if grupo else None


TOTAL_CAMPOS = len(campos_canonicos())

#: Os itens do "Gabarito do slide da Ranger Raptor" em `docs/01_REQUISITOS_EDITAL.md` —
#: a lista que o edital usa para validar a solução. Não substitui nem encolhe `GRUPOS`
#: (que continua sendo TODOS os 54 campos, para benchmark e para quem quiser mais); serve
#: só para separar, na tela e no relatório, "o que a Ford pediu" do resto.
CAMPOS_VALIDACAO_EDITAL: tuple[str, ...] = (
    "motor_descricao",
    "potencia_cv",
    "potencia_rpm",
    "torque_nm",
    "torque_rpm",
    "numero_marchas",
    "paddle_shifters",
    "tipo_tracao",
    "amortecedores",
    "aceleracao_0_100_s",
    "modos_conducao",
    "modos_direcao",
    "modos_escapamento",
    "modos_amortecedor",
    "farois_tipo",
    "pneus_medida",
    "rodas_aro_pol",
    "preco_sugerido_brl",
)


def resumo_validacao_edital(spec: StandardSpec) -> dict[str, Any]:
    """Quantos dos campos do slide de validação a ficha comprova, e quais faltam — com o
    porquê de cada vazio, não só a contagem.

    Métrica de duas camadas: `com_valor` conta `verificado`/`divergente` (valor com
    evidência, tier 3 incluso — é o mesmo status `verificado`, só que apoiado numa fonte
    tier 3). `vazio_justificado` conta o vazio que **prova que procuramos**:
    `nao_disponivel` (fonte oficial afirma a ausência) ou `nao_encontrado` com
    `sources_checked` não vazio (nenhuma das fontes consultadas cita — é o caso dos
    recursos exclusivos de performance numa versão que não os tem, e nenhuma fonte no
    mundo publica essa ausência). `respondidos = com_valor + vazio_justificado` é o que a
    tela mostra como "respondido"; `sem_resposta` é só o campo nunca tentado
    (`nao_encontrado` sem fontes) ou extraído sem o trecho localizado (`nao_verificado`).
    """
    achados: list[str] = []
    vazios: list[dict[str, Any]] = []
    vazio_justificado = 0
    for campo in CAMPOS_VALIDACAO_EDITAL:
        caminho = caminho_canonico(campo)
        valor = spec.get(caminho) if caminho else None
        if valor is not None and valor.status in STATUS_COM_EVIDENCIA:
            achados.append(campo)
        else:
            status = valor.status if valor is not None else Status.NAO_ENCONTRADO
            fontes = list(valor.sources_checked) if valor is not None else []
            justificado = status is Status.NAO_DISPONIVEL or (
                status is Status.NAO_ENCONTRADO and bool(fontes)
            )
            if justificado:
                vazio_justificado += 1
            vazios.append(
                {
                    "campo": campo,
                    "status": status.value,
                    "vazio_justificado": justificado,
                    "sources_checked": fontes,
                }
            )
    total = len(CAMPOS_VALIDACAO_EDITAL)
    com_valor = len(achados)
    respondidos = com_valor + vazio_justificado
    return {
        "total": total,
        "achados": com_valor,  # mantido por compatibilidade; igual a com_valor
        "com_valor": com_valor,
        "vazio_justificado": vazio_justificado,
        "respondidos": respondidos,
        "sem_resposta": total - respondidos,
        "campos_achados": achados,
        "campos_vazios": vazios,
    }


# --------------------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------------------
class Evidence(BaseModel):
    """Proveniência de um valor: onde foi visto, com que palavras e quando.

    `quote` é o trecho **verbatim** da fonte. Sem ele, nenhum valor entra na ficha.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_url: str
    tier: int = Field(ge=1, le=5)
    quote: str = Field(max_length=300)
    captured_at: str
    raw_value: str | None = None
    snapshot_id: str | None = None
    page: int | None = None
    #: O que a fonte estava fazendo ao dizer este número: `declarado` (o fabricante
    #: afirma), `medido` (alguém cronometrou) ou `listado` (tabela, sem verbo).
    #:
    #: Existe porque uma **mesma página** pode trazer os dois: a matéria da Autoesporte
    #: sobre a Ranger Raptor registra os 5,8 s que a Ford declara e os 6,5 s que a revista
    #: mediu. Sem este campo, a ficha chamava isso de "as fontes divergem" — errando o
    #: fato e desperdiçando o melhor argumento que a página oferece.
    #:
    #: `None` é `desconhecido`, e é o padrão: o tipo só é preenchido quando um termo
    #: literal do trecho verbatim o sustenta (`pipeline/claim_type.py`).
    tipo_de_afirmacao: Literal["declarado", "medido", "listado"] | None = None

    @field_validator("quote")
    @classmethod
    def _quote_nao_vazio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("evidence.quote não pode ser vazio")
        return v


class Conflict(BaseModel):
    """Um dos valores de um campo `divergente`, com a evidência que o sustenta."""

    model_config = ConfigDict(extra="forbid")

    value: Any
    evidence: Evidence
    notes: str | None = None


class SpecField(BaseModel):
    """Envelope de um campo: valor + status + confiança + proveniência."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    value: Any = None
    unit: str | None = None
    status: Status = Status.NAO_ENCONTRADO
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidences: list[Evidence] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    sources_checked: list[str] = Field(default_factory=list)
    notes: str | None = None
    #: De onde veio o valor, quando **não** foi extraído de uma fonte externa.
    #:
    #: Hoje só `"catalogo"`: marca, modelo, versão, ano-modelo e código FIPE são a
    #: identidade da versão consultada, e estão no nosso banco porque alguém a cadastrou —
    #: não porque um extrator os leu numa página. Dizer isso em vez de "não encontrado"
    #: é mais honesto nos dois sentidos: o valor existe, e a prova dele é de outra espécie.
    origem: str | None = None

    @model_validator(mode="after")
    def _coerencia_valor_status(self) -> SpecField:
        if self.status in STATUS_SEM_VALOR and self.value is not None:
            raise ValueError(
                f"status={self.status.value} exige value=None "
                f"(recebido {self.value!r}); os dois vazios não carregam valor"
            )
        if self.status in STATUS_COM_EVIDENCIA and not self.evidences:
            raise ValueError(
                f"status={self.status.value} exige ao menos uma evidência "
                "(nenhum valor sem evidência)"
            )
        if self.status is Status.DIVERGENTE and len(self.conflicts) < 1:
            raise ValueError(
                "status=divergente exige os valores concorrentes em conflicts "
                "(o sistema não escolhe em silêncio)"
            )
        return self

    # -- construtores curtos, usados pelo pipeline e pelos testes --------------------
    @classmethod
    def vazio(cls, status: Status = Status.NAO_ENCONTRADO, **kw: Any) -> SpecField:
        return cls(value=None, status=status, confidence=0.0, **kw)

    @classmethod
    def verificado(
        cls,
        value: Any,
        evidencia: Evidence,
        *,
        unit: str | None = None,
        confidence: float | None = None,
        **kw: Any,
    ) -> SpecField:
        return cls(
            value=value,
            unit=unit,
            status=Status.VERIFICADO,
            confidence=(
                confidence
                if confidence is not None
                else CONFIANCA_POR_TIER.get(evidencia.tier, 0.2)
            ),
            evidences=[evidencia],
            **kw,
        )


class VersionResolution(BaseModel):
    """Resultado do Passo 0 (resolvedor de versão) — `docs/05`."""

    model_config = ConfigDict(extra="forbid")

    status: str = "encontrada"  # encontrada | versao_inexistente | ambigua
    matched_version: str | None = None
    alternatives: list[str] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def _status_valido(cls, v: str) -> str:
        validos = {"encontrada", "versao_inexistente", "ambigua"}
        if v not in validos:
            raise ValueError(f"version_resolution.status inválido: {v}")
        return v


class SpecMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: str
    job_id: str
    version_resolution: VersionResolution = Field(default_factory=VersionResolution)
    sources_checked: list[str] = Field(default_factory=list)


class StandardSpec(BaseModel):
    """A ficha padronizada. Mesmos campos, mesma ordem, sempre."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    identificacao: dict[str, SpecField]
    motorizacao: dict[str, SpecField]
    transmissao: dict[str, SpecField]
    tracao: dict[str, SpecField]
    chassi: dict[str, SpecField]
    desempenho: dict[str, SpecField]
    modos: dict[str, SpecField]
    exterior: dict[str, SpecField]
    dimensoes: dict[str, SpecField]
    seguranca: dict[str, SpecField]
    comercial: dict[str, SpecField]
    extras: dict[str, SpecField] = Field(default_factory=dict)
    meta: SpecMeta

    # -- acesso por caminho ---------------------------------------------------------
    def get(self, caminho: str) -> SpecField | None:
        """`spec.get("motorizacao.potencia_cv")` ou `spec.get("potencia_cv")`."""
        if "." in caminho:
            grupo, campo = caminho.split(".", 1)
            return getattr(self, grupo, {}).get(campo) if hasattr(self, grupo) else None
        grupo = grupo_de(caminho)
        if grupo:
            return getattr(self, grupo).get(caminho)
        return self.extras.get(caminho)

    def set(self, caminho: str, campo: SpecField) -> None:
        if "." in caminho:
            grupo, nome = caminho.split(".", 1)
        else:
            nome = caminho
            grupo = grupo_de(nome) or "extras"
        getattr(self, grupo)[nome] = campo

    def itens(self) -> Iterable[tuple[str, SpecField]]:
        """Todos os campos como (caminho, SpecField), na ordem da ficha; extras ao fim."""
        for grupo, campos in GRUPOS.items():
            bloco = getattr(self, grupo)
            for campo in campos:
                if campo in bloco:
                    yield f"{grupo}.{campo}", bloco[campo]
        for nome, campo in self.extras.items():
            yield f"extras.{nome}", campo

    # -- serialização e validação ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)

    def to_json(self, *, validar: bool = True, indent: int | None = None) -> str:
        """Serializa e valida contra `schema/canonical_spec.schema.json`.

        Levanta `jsonschema.ValidationError` se a ficha não for válida — é de propósito:
        uma ficha inválida não pode sair do pipeline.
        """
        dados = self.to_dict()
        if validar:
            validar_contra_schema(dados)
        return json.dumps(dados, ensure_ascii=False, indent=indent)


@lru_cache(maxsize=1)
def json_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validar_contra_schema(dados: dict[str, Any]) -> None:
    """Valida um dict de ficha contra o JSON Schema canônico."""
    import jsonschema

    jsonschema.validate(instance=dados, schema=json_schema())


def empty_spec(
    *,
    job_id: str = "",
    generated_at: str | None = None,
    status: Status = Status.NAO_ENCONTRADO,
    sources_checked: list[str] | None = None,
) -> StandardSpec:
    """Ficha completa com todos os campos presentes e nenhum valor.

    O default é `nao_encontrado`: "nenhuma fonte consultada menciona". Esse é o ponto de
    partida honesto — o pipeline só promove um campo quando encontra evidência.
    """
    blocos: dict[str, Any] = {}
    for grupo, campos in GRUPOS.items():
        blocos[grupo] = {
            campo: SpecField.vazio(
                status,
                unit=UNIDADE_CANONICA.get(campo),
                sources_checked=list(sources_checked or []),
            )
            for campo in campos
        }
    return StandardSpec(
        schema_version=SCHEMA_VERSION,
        **blocos,
        extras={},
        meta=SpecMeta(
            generated_at=generated_at or dt.datetime.now(dt.UTC).isoformat(),
            job_id=job_id,
            version_resolution=VersionResolution(),
            sources_checked=list(sources_checked or []),
        ),
    )
