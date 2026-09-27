"""Comparable Set: **este par de versões pode ser comparado?**, com a régua à vista.

O problema que este módulo resolve é o da `docs/12` §2.3: a Ranger Raptor é uma picape de
desempenho a gasolina de R$ 499 mil, e um produtor rural que compra por consumo, carga e
preço não a coloca ao lado de uma Hilux SRX Plus. Um sistema que comparasse as duas em
silêncio produziria uma tabela **correta e inútil** — cada número certo, e a conclusão
("a Hilux é melhor") respondendo a uma pergunta que ninguém fez.

Três decisões moldam o módulo:

* **os critérios vivem em `comparables.yaml`**, versionados por data. O gestor discorda de
  um critério lendo o arquivo, e a discordância vira uma linha alterada — não um pedido de
  mudança de software. A `versao` do arquivo viaja na resposta, para que nenhuma
  comparação exibida hoje seja confundida com uma feita sob outra régua;
* **o resultado é `k/n`, nunca porcentagem.** "5 de 6 critérios" e "82% comparável" não
  são a mesma afirmação: a segunda esconde o denominador, e o denominador é a informação.
  É a mesma regra dos denominadores visíveis do eval;
* **critério sem dado não conta no denominador.** Se nenhum dos dois lados declara o
  segmento, o critério entra em `sem_dados` e `n` diminui — em vez de virar um "não
  atendido" que culparia o par pela ausência da fonte, ou um "atendido" que afirmaria uma
  igualdade que ninguém verificou. Os dois vazios do produto, aplicados à comparação.

O combustível é **eliminatório à parte** (`combustivel_eliminatorio` no YAML): um par pode
bater cinco critérios e continuar incomparável se um for diesel e o outro gasolina.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pipeline.ontology import normalize

#: O arquivo de critérios, ao lado do módulo (mesma convenção de `synonyms_seed.json`).
ARQUIVO = Path(__file__).resolve().parent / "comparables.yaml"

#: Os estados de um critério. `sem_dados` é de primeira classe, como `desconhecido` na
#: matriz de paridade: não saber é diferente de não atender.
ATENDIDO = "atendido"
NAO_ATENDIDO = "nao_atendido"
SEM_DADOS = "sem_dados"


class CriterioInvalido(ValueError):
    """O YAML declara um tipo de critério que o módulo não sabe avaliar."""


@dataclass(frozen=True)
class Criterio:
    """Um critério, como o YAML o declara."""

    id: str
    rotulo: str
    campo: str
    tipo: str
    descricao: str = ""
    campo_alternativo: str | None = None
    tolerancia: float | None = None


@dataclass(frozen=True)
class Config:
    versao: str
    minimo_atendidos: int
    combustivel_eliminatorio: bool
    criterios: tuple[Criterio, ...]
    finalidade_por_versao: dict[str, tuple[str, ...]]


@functools.lru_cache(maxsize=1)
def carregar(caminho: str | None = None) -> Config:
    """Lê e valida `comparables.yaml`. Em cache: o arquivo não muda em tempo de execução."""
    origem = Path(caminho) if caminho else ARQUIVO
    dados: dict[str, Any] = yaml.safe_load(origem.read_text(encoding="utf-8"))

    criterios: list[Criterio] = []
    for bruto in dados.get("criterios", []):
        tipo = str(bruto.get("tipo", ""))
        if tipo not in _AVALIADORES:
            raise CriterioInvalido(
                f"criterio {bruto.get('id')!r}: tipo {tipo!r} desconhecido "
                f"(conhecidos: {', '.join(sorted(_AVALIADORES))})"
            )
        criterios.append(
            Criterio(
                id=str(bruto["id"]),
                rotulo=str(bruto.get("rotulo") or bruto["id"]),
                campo=str(bruto["campo"]),
                tipo=tipo,
                descricao=" ".join(str(bruto.get("descricao", "")).split()),
                campo_alternativo=(
                    str(bruto["campo_alternativo"]) if bruto.get("campo_alternativo") else None
                ),
                tolerancia=(
                    float(bruto["tolerancia"]) if bruto.get("tolerancia") is not None else None
                ),
            )
        )

    finalidades = {
        str(nome): tuple(str(t) for t in tags)
        for nome, tags in (dados.get("finalidade_por_versao") or {}).items()
    }
    return Config(
        versao=str(dados.get("versao", "sem versao")),
        minimo_atendidos=int(dados.get("minimo_atendidos", 4)),
        combustivel_eliminatorio=bool(dados.get("combustivel_eliminatorio", True)),
        criterios=tuple(criterios),
        finalidade_por_versao=finalidades,
    )


@dataclass
class ResultadoCriterio:
    """Um critério avaliado, com os dois valores que o decidiram."""

    id: str
    rotulo: str
    estado: str
    valor_ford: Any = None
    valor_concorrente: Any = None
    motivo: str = ""

    @property
    def atendido(self) -> bool:
        return self.estado == ATENDIDO

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rotulo": self.rotulo,
            "estado": self.estado,
            "valor_ford": self.valor_ford,
            "valor_concorrente": self.valor_concorrente,
            "motivo": self.motivo,
        }


@dataclass
class Comparabilidade:
    """A resposta: quantos critérios de quantos, quais faltaram, e se dá para comparar."""

    comparavel: bool
    criterios_atendidos: int
    criterios_avaliaveis: int
    """O `n` do `k/n`. Menor que o total quando algum critério não tem dado."""
    total_de_criterios: int
    nao_atendidos: list[str] = field(default_factory=list)
    sem_dados: list[str] = field(default_factory=list)
    detalhes: list[ResultadoCriterio] = field(default_factory=list)
    aviso: str = ""
    """Vazio quando comparável. Preenchido, a UI e o PDF são **obrigados** a exibi-lo."""
    versao_dos_criterios: str = ""

    @property
    def resumo(self) -> str:
        """`"4/6 critérios atendidos"`. Nunca porcentagem."""
        return f"{self.criterios_atendidos}/{self.criterios_avaliaveis} critérios atendidos"

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparavel": self.comparavel,
            "criterios_atendidos": self.criterios_atendidos,
            "criterios_avaliaveis": self.criterios_avaliaveis,
            "total_de_criterios": self.total_de_criterios,
            "resumo": self.resumo,
            "nao_atendidos": list(self.nao_atendidos),
            "sem_dados": list(self.sem_dados),
            "detalhes": [d.to_dict() for d in self.detalhes],
            "aviso": self.aviso,
            "versao_dos_criterios": self.versao_dos_criterios,
        }


def _vazio(valor: Any) -> bool:
    """`None`, texto vazio e lista vazia são ausência. `0` e `False` **não** são."""
    if valor is None:
        return True
    if isinstance(valor, str):
        return not valor.strip()
    if isinstance(valor, list | tuple | set):
        return len(valor) == 0
    return False


def _numero(valor: Any) -> float | None:
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int | float):
        return float(valor)
    try:
        from pipeline.units import parse_number_ptbr

        return parse_number_ptbr(str(valor))
    except (ValueError, TypeError):
        return None


def _avaliar_igualdade(criterio: Criterio, a: Any, b: Any) -> ResultadoCriterio:
    """Igualdade após normalização (acento, caixa, separador)."""
    if _vazio(a) or _vazio(b):
        return _sem_dados(criterio, a, b)
    igual = normalize(str(a)) == normalize(str(b))
    return ResultadoCriterio(
        id=criterio.id,
        rotulo=criterio.rotulo,
        estado=ATENDIDO if igual else NAO_ATENDIDO,
        valor_ford=a,
        valor_concorrente=b,
        motivo="" if igual else f"{a} contra {b}",
    )


def _avaliar_faixa_relativa(criterio: Criterio, a: Any, b: Any) -> ResultadoCriterio:
    """Dentro de ±tolerância **sobre o valor da Ford**, que é a referência da comparação."""
    na, nb = _numero(a), _numero(b)
    if na is None or nb is None or na == 0:
        return _sem_dados(criterio, a, b)
    tolerancia = criterio.tolerancia if criterio.tolerancia is not None else 0.20
    desvio = abs(nb - na) / abs(na)
    dentro = desvio <= tolerancia
    return ResultadoCriterio(
        id=criterio.id,
        rotulo=criterio.rotulo,
        estado=ATENDIDO if dentro else NAO_ATENDIDO,
        valor_ford=na,
        valor_concorrente=nb,
        motivo=(
            f"diferença de {desvio * 100:.0f}% (limite ±{tolerancia * 100:.0f}%)"
            if not dentro
            else f"diferença de {desvio * 100:.0f}%"
        ),
    )


def _avaliar_intersecao(criterio: Criterio, a: Any, b: Any) -> ResultadoCriterio:
    """Ao menos uma etiqueta em comum."""
    if _vazio(a) or _vazio(b):
        return _sem_dados(criterio, a, b)
    la = {normalize(str(x)) for x in (a if isinstance(a, list | tuple | set) else [a])}
    lb = {normalize(str(x)) for x in (b if isinstance(b, list | tuple | set) else [b])}
    comuns = sorted(la & lb)
    return ResultadoCriterio(
        id=criterio.id,
        rotulo=criterio.rotulo,
        estado=ATENDIDO if comuns else NAO_ATENDIDO,
        valor_ford=sorted(la),
        valor_concorrente=sorted(lb),
        motivo=(
            f"em comum: {', '.join(comuns)}"
            if comuns
            else f"nada em comum entre {sorted(la)} e {sorted(lb)}"
        ),
    )


def _sem_dados(criterio: Criterio, a: Any, b: Any) -> ResultadoCriterio:
    """Qual dos dois lados falta, dito com nome.

    "Não foi possível avaliar" mandaria a pessoa procurar nos dois lugares.
    """
    faltando = []
    if _vazio(a):
        faltando.append("na versão Ford")
    if _vazio(b):
        faltando.append("no concorrente")
    return ResultadoCriterio(
        id=criterio.id,
        rotulo=criterio.rotulo,
        estado=SEM_DADOS,
        valor_ford=a,
        valor_concorrente=b,
        motivo=f"sem valor {' e '.join(faltando)}",
    )


_AVALIADORES = {
    "igualdade": _avaliar_igualdade,
    "faixa_relativa": _avaliar_faixa_relativa,
    "intersecao": _avaliar_intersecao,
}


def finalidade_de(versao: str, *, config: Config | None = None) -> tuple[str, ...]:
    """As etiquetas de uso da versão, ou vazio quando ninguém as declarou.

    Vazio é **ausência declarada**: o critério de finalidade entra como `sem_dados` e o
    denominador cai à vista. Inferir a finalidade a partir da ficha (por exemplo, "tem
    muita potência, logo é de desempenho") seria transformar um julgamento comercial em
    um palpite do sistema, e o par passaria a ser reprovado por uma opinião não assinada.
    """
    cfg = config or carregar()
    exato = cfg.finalidade_por_versao.get(versao)
    if exato is not None:
        return exato
    alvo = normalize(versao)
    for nome, tags in cfg.finalidade_por_versao.items():
        if normalize(nome) == alvo:
            return tags
    return ()


def _valor(atributos: dict[str, Any], criterio: Criterio) -> Any:
    """O valor do critério, com o campo alternativo declarado no YAML como reserva."""
    valor = atributos.get(criterio.campo)
    if _vazio(valor) and criterio.campo_alternativo:
        valor = atributos.get(criterio.campo_alternativo)
    return valor


def avaliar(
    ford: dict[str, Any],
    concorrente: dict[str, Any],
    *,
    config: Config | None = None,
) -> Comparabilidade:
    """Avalia o par. `ford` e `concorrente` são mapas campo canônico → valor.

    A finalidade entra pelos mapas como o campo `finalidade` (uma lista de etiquetas);
    :func:`atributos_de_spec` a preenche a partir do YAML.
    """
    cfg = config or carregar()

    detalhes: list[ResultadoCriterio] = []
    for criterio in cfg.criterios:
        avaliador = _AVALIADORES[criterio.tipo]
        detalhes.append(avaliador(criterio, _valor(ford, criterio), _valor(concorrente, criterio)))

    atendidos = [d for d in detalhes if d.estado == ATENDIDO]
    nao_atendidos = [d for d in detalhes if d.estado == NAO_ATENDIDO]
    sem_dados = [d for d in detalhes if d.estado == SEM_DADOS]
    avaliaveis = len(atendidos) + len(nao_atendidos)

    combustivel = next((d for d in detalhes if d.id == "combustivel"), None)
    barrado_por_combustivel = (
        cfg.combustivel_eliminatorio
        and combustivel is not None
        and combustivel.estado == NAO_ATENDIDO
    )

    comparavel = len(atendidos) >= cfg.minimo_atendidos and not barrado_por_combustivel

    aviso = ""
    if not comparavel:
        partes = [
            f"Par não comparável pelos critérios de {cfg.versao}: "
            f"{len(atendidos)}/{avaliaveis} atendidos (mínimo {cfg.minimo_atendidos})."
        ]
        if nao_atendidos:
            partes.append("Não atendidos: " + ", ".join(d.rotulo for d in nao_atendidos) + ".")
        if barrado_por_combustivel:
            partes.append(
                "Combustível diferente é eliminatório: diesel e gasolina não competem pelo "
                "mesmo comprador."
            )
        if sem_dados:
            partes.append(
                "Sem dados para: " + ", ".join(d.rotulo for d in sem_dados) + " "
                "(não contam no denominador)."
            )
        partes.append("A comparação abaixo continua válida campo a campo, com esta ressalva.")
        aviso = " ".join(partes)

    return Comparabilidade(
        comparavel=comparavel,
        criterios_atendidos=len(atendidos),
        criterios_avaliaveis=avaliaveis,
        total_de_criterios=len(cfg.criterios),
        nao_atendidos=[d.rotulo for d in nao_atendidos],
        sem_dados=[d.rotulo for d in sem_dados],
        detalhes=detalhes,
        aviso=aviso,
        versao_dos_criterios=cfg.versao,
    )


def atributos_de_spec(spec: Any, *, versao: str | None = None) -> dict[str, Any]:
    """Extrai de um `StandardSpec` o mapa que :func:`avaliar` consome.

    Campo com status de ausência entra como `None`: um valor `nao_encontrado` não pode
    virar o texto "nao_encontrado" e ser comparado por igualdade com o do outro lado —
    dois desconhecimentos casariam e o critério apareceria como **atendido**.
    """
    from pipeline.schema import Status

    atributos: dict[str, Any] = {}
    for caminho, campo in spec.itens():
        nome = caminho.split(".", 1)[-1]
        if campo.status in {Status.NAO_ENCONTRADO, Status.NAO_DISPONIVEL, Status.NAO_VERIFICADO}:
            atributos[nome] = None
        else:
            atributos[nome] = campo.value

    nome_da_versao = versao or str(atributos.get("versao") or "")
    atributos["finalidade"] = list(finalidade_de(nome_da_versao))
    return atributos


#: A flag de negócio de `docs/13` §3, com o texto **fixo**.
#:
#: O texto é literal e não pode ser parafraseado: ele afirma o que o dado mostra
#: ("capacidade ≥ 1.000 kg", com fonte) e **não** afirma enquadramento fiscal, que depende
#: de legislação, do CNPJ do comprador e do uso — coisas que este sistema não sabe. Uma
#: versão "mais útil" do texto ("logo, isento de IPI") seria orientação tributária dada por
#: um extrator de ficha técnica.
LIMIAR_DE_CARGA_KG = 1000
TEXTO_DA_FLAG_DE_CARGA = (
    "Capacidade de carga ≥ 1.000 kg ({fonte}). Critério comumente associado à "
    "classificação como veículo de carga; confirmar enquadramento fiscal com a Ford."
)
#: A etiqueta da flag. É **INFERÊNCIA**: o número é fato, a leitura de negócio não é.
ETIQUETA_DA_FLAG_DE_CARGA = "INFERENCIA"


@dataclass
class FlagDeCarga:
    """A flag dos 1.000 kg: verdadeira, falsa ou **indeterminada**, nunca falsa por omissão."""

    aplicavel: bool
    """Falso quando não há valor de carga: aí não há flag nenhuma a exibir."""
    valor: bool | None = None
    capacidade_kg: float | None = None
    texto: str = ""
    etiqueta: str = ETIQUETA_DA_FLAG_DE_CARGA
    motivo: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "aplicavel": self.aplicavel,
            "valor": self.valor,
            "capacidade_kg": self.capacidade_kg,
            "texto": self.texto,
            "etiqueta": self.etiqueta,
            "motivo": self.motivo,
        }


def flag_de_carga(capacidade_kg: Any, *, fonte: str = "fonte não informada") -> FlagDeCarga:
    """Avalia a regra dos 1.000 kg sobre um valor de `capacidade_carga_kg`.

    Sem valor, a flag é **indeterminada** e não `False`: dizer "não atinge 1.000 kg" sobre
    uma picape cuja carga ninguém encontrou é afirmar um fato a partir de uma ausência.
    """
    numero = _numero(capacidade_kg)
    if numero is None:
        return FlagDeCarga(
            aplicavel=False,
            motivo=(
                "sem valor de capacidade de carga: a regra dos 1.000 kg não é avaliável, "
                "e não avaliada é diferente de não atingida"
            ),
        )
    atinge = numero >= LIMIAR_DE_CARGA_KG
    return FlagDeCarga(
        aplicavel=True,
        valor=atinge,
        capacidade_kg=numero,
        texto=TEXTO_DA_FLAG_DE_CARGA.format(fonte=fonte) if atinge else "",
        motivo=(
            f"{numero:g} kg ≥ {LIMIAR_DE_CARGA_KG} kg"
            if atinge
            else f"{numero:g} kg abaixo de {LIMIAR_DE_CARGA_KG} kg"
        ),
    )
