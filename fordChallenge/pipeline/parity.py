"""Parity Matrix: por campo, a Ford **ganha, empata, perde ou não se sabe**.

O quarto estado é a razão de o módulo existir. Uma matriz de três estados obriga o
`nao_encontrado` do concorrente a escolher um lado, e as duas escolhas mentem: contado
como `gap`, o sistema afirma que perdemos num campo que ninguém mediu; contado como
`paridade`, afirma um empate igualmente inventado. `desconhecido` é estado de primeira
classe — e aparece na tela com a mesma proeminência dos outros três, porque "não sabemos"
é a informação que faz o analista ir buscar a fonte.

**Duas ausências diferentes, dois desconhecidos diferentes.** O módulo distingue, no
`motivo`, o campo que falta de um lado (`sem_dado_*`) do campo que **os dois lados têm** e
que o sistema não sabe ordenar (`sem_direcao_de_merito`) — motor "V6 3.0 Bi-turbo" contra
"2.8 turbodiesel" não é melhor nem pior, é outro projeto. Colapsar os dois casos num
"desconhecido" liso mandaria alguém procurar um dado que já está na tela.

**A paridade usa as tolerâncias do eval** (`pipeline/eval/compare.py`), e não um limiar
próprio: 397 cv contra 398 cv é a mesma potência para qualquer efeito comercial, e se a
régua daqui fosse diferente da que mede o acerto do pipeline, o produto exibiria "vantagem"
em cima de uma diferença que o eval trata como o mesmo número.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.eval.compare import tolerancia_de
from pipeline.ontology import canonicalizar_lista, normalize
from pipeline.schema import CAMPOS_BOOL, CAMPOS_LISTA, GRUPOS, Status

#: Os quatro estados. Vocabulário fechado: a legenda da tela é indexada por eles.
VANTAGEM = "vantagem"
PARIDADE = "paridade"
GAP = "gap"
DESCONHECIDO = "desconhecido"

ESTADOS = (VANTAGEM, PARIDADE, GAP, DESCONHECIDO)

#: Motivos de `desconhecido`. Ver o docstring: as ausências não são todas iguais.
SEM_DADO_FORD = "sem_dado_ford"
SEM_DADO_CONCORRENTE = "sem_dado_concorrente"
SEM_DADO_NOS_DOIS = "sem_dado_nos_dois"
SEM_DIRECAO_DE_MERITO = "sem_direcao_de_merito"
SEM_ORDEM_ENTRE_CONJUNTOS = "sem_ordem_entre_conjuntos"

#: Para onde é "melhor", campo por campo. **Só o que está aqui é ordenável.**
#:
#: A lista é curta de propósito: cada entrada é uma afirmação de que mais (ou menos) do
#: campo é comercialmente melhor, e essa afirmação precisa ser defensável diante do
#: cliente. `numero_marchas` não está aqui — dez marchas não são melhores que oito para
#: quem reboca, dependem do escalonamento; `deslocamento_l` também não, porque cilindrada
#: maior é vantagem de torque e desvantagem de consumo ao mesmo tempo.
MELHOR_QUANDO: dict[str, str] = {
    # motorização e desempenho: mais é melhor, menos tempo é melhor
    "potencia_cv": "maior",
    "torque_nm": "maior",
    "aceleracao_0_100_s": "menor",
    "velocidade_maxima_kmh": "maior",
    "consumo_urbano_kml": "maior",
    "consumo_rodoviario_kml": "maior",
    # carga e dimensões úteis
    "capacidade_carga_kg": "maior",
    "capacidade_reboque_kg": "maior",
    "tanque_l": "maior",
    "entre_eixos_mm": "maior",
    # comercial: preço menor é vantagem para quem compra
    "preco_sugerido_brl": "menor",
    "preco_fipe_brl": "menor",
    "garantia_meses": "maior",
    # segurança e equipamento: mais itens é melhor
    "airbags_qtd": "maior",
    "adas_itens": "maior",
    "rodas_aro_pol": "maior",
}

#: Booleanos em que **ter** é vantagem. Fora desta lista, um booleano fica sem direção.
#:
#: `paddle_shifters` está aqui, `farois_neblina` também; nenhum dos dois é polêmico. O que
#: não entra é qualquer booleano cuja ausência alguém possa preferir.
TER_E_MELHOR = frozenset(
    {
        "paddle_shifters",
        "reduzida",
        "bloqueio_diferencial",
        "camera_360",
        "farois_neblina",
    }
)

#: Campos de lista tratados como **conjunto de itens**, onde conter mais é vantagem.
#: `modos_*` entram: mais modos de condução é mais capacidade, e a contagem é o critério
#: que o próprio marketing das montadoras usa ("7 modos de condução").
LISTAS_ORDENAVEIS = frozenset(
    {"adas_itens", "modos_conducao", "modos_direcao", "modos_escapamento", "modos_amortecedor"}
)

#: Os status que significam ausência. Qualquer um deles de um lado → `desconhecido`.
STATUS_DE_AUSENCIA = frozenset(
    {Status.NAO_ENCONTRADO, Status.NAO_DISPONIVEL, Status.NAO_VERIFICADO}
)

#: Campo → grupo do schema, para o filtro por dimensão da tela.
GRUPO_DO_CAMPO: dict[str, str] = {
    campo: grupo for grupo, campos in GRUPOS.items() for campo in campos
}


@dataclass
class CelulaDeParidade:
    """Uma célula da matriz: um campo, dois valores, um estado e o motivo."""

    campo: str
    grupo: str
    estado: str
    valor_ford: Any = None
    valor_concorrente: Any = None
    unidade: str | None = None
    motivo: str = ""
    motivo_tipo: str = ""
    diferenca: float | None = None
    """Só existe em campo numérico ordenável. `None` não significa zero."""
    evidence_id_ford: str | None = None
    evidence_id_concorrente: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "campo": self.campo,
            "grupo": self.grupo,
            "estado": self.estado,
            "valor_ford": self.valor_ford,
            "valor_concorrente": self.valor_concorrente,
            "unidade": self.unidade,
            "motivo": self.motivo,
            "motivo_tipo": self.motivo_tipo,
            "diferenca": self.diferenca,
            "evidence_id_ford": self.evidence_id_ford,
            "evidence_id_concorrente": self.evidence_id_concorrente,
        }


@dataclass
class Contagem:
    """Quantas células em cada estado. `desconhecido` **também** é contado e exibido."""

    vantagem: int = 0
    paridade: int = 0
    gap: int = 0
    desconhecido: int = 0

    @property
    def total(self) -> int:
        return self.vantagem + self.paridade + self.gap + self.desconhecido

    @property
    def comparados(self) -> int:
        """As células com os dois lados conhecidos. É o denominador honesto."""
        return self.vantagem + self.paridade + self.gap

    def to_dict(self) -> dict[str, Any]:
        return {
            "vantagem": self.vantagem,
            "paridade": self.paridade,
            "gap": self.gap,
            "desconhecido": self.desconhecido,
            "total": self.total,
            "comparados": self.comparados,
        }


@dataclass
class ColunaDeParidade:
    """Um concorrente: as células, a contagem e o aviso de comparabilidade."""

    version_id: str
    rotulo: str
    celulas: list[CelulaDeParidade] = field(default_factory=list)
    contagem: Contagem = field(default_factory=Contagem)
    comparabilidade: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "rotulo": self.rotulo,
            "celulas": [c.to_dict() for c in self.celulas],
            "contagem": self.contagem.to_dict(),
            "comparabilidade": self.comparabilidade,
        }


def _e_ausencia(status: Any) -> bool:
    if status is None:
        return False
    try:
        return Status(str(status)) in STATUS_DE_AUSENCIA
    except ValueError:
        return False


def _vazio(valor: Any) -> bool:
    """`None`, texto vazio e lista vazia. `False` e `0` **não** são vazios."""
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
    return None


def _do_numero(campo: str, a: float, b: float) -> tuple[str, str]:
    """Estado e motivo de um campo numérico ordenável, com a tolerância do eval.

    O motivo diz os **dois números** e qual lado da régua é melhor, em vez de "a Ford tem
    menos". A primeira versão dizia isso, e ao lado de "Aceleração 0-100 s" a frase se lia
    como desvantagem justamente quando o estado era `vantagem`: menos tempo é mais rápido.
    Frase que contradiz o estado ao lado dela é pior que frase nenhuma.
    """
    tolerancia = tolerancia_de(campo)
    if tolerancia.bate(b, a):
        return PARIDADE, f"diferença dentro da tolerância de {tolerancia.descricao()}"
    direcao = MELHOR_QUANDO[campo]
    ford_melhor = a > b if direcao == "maior" else a < b
    regua = "quanto maior, melhor" if direcao == "maior" else "quanto menor, melhor"
    return (
        (VANTAGEM if ford_melhor else GAP),
        f"{a:g} contra {b:g} — {regua}",
    )


def _do_conjunto(campo: str, a: Any, b: Any) -> tuple[str, str, str]:
    """Estado, motivo e tipo de motivo para campos de lista.

    Contenção decide: o conjunto que contém o outro ganha. Conjuntos que se cruzam **não
    têm ordem** — "tem Baja mas não tem Lama" contra "tem Lama mas não tem Baja" não é
    vantagem nem gap, e forçar um dos dois inventaria uma hierarquia entre recursos que o
    comprador é quem estabelece.
    """
    ca = set(canonicalizar_lista(campo, [str(x) for x in a]))
    cb = set(canonicalizar_lista(campo, [str(x) for x in b]))
    if ca == cb:
        return PARIDADE, f"os mesmos {len(ca)} itens", ""
    if cb < ca:
        extras = sorted(ca - cb)
        return VANTAGEM, f"a Ford tem a mais: {', '.join(extras)}", ""
    if ca < cb:
        extras = sorted(cb - ca)
        return GAP, f"o concorrente tem a mais: {', '.join(extras)}", ""
    return (
        DESCONHECIDO,
        (
            f"conjuntos diferentes sem um conter o outro: só na Ford "
            f"{sorted(ca - cb)}, só no concorrente {sorted(cb - ca)}"
        ),
        SEM_ORDEM_ENTRE_CONJUNTOS,
    )


def comparar_campo(
    campo: str,
    *,
    valor_ford: Any,
    valor_concorrente: Any,
    status_ford: Any = None,
    status_concorrente: Any = None,
    unidade: str | None = None,
    evidence_id_ford: str | None = None,
    evidence_id_concorrente: str | None = None,
) -> CelulaDeParidade:
    """O estado de um campo. Ausência de qualquer lado → `desconhecido`, com o motivo."""
    celula = CelulaDeParidade(
        campo=campo,
        grupo=GRUPO_DO_CAMPO.get(campo, "outros"),
        estado=DESCONHECIDO,
        valor_ford=valor_ford,
        valor_concorrente=valor_concorrente,
        unidade=unidade,
        evidence_id_ford=evidence_id_ford,
        evidence_id_concorrente=evidence_id_concorrente,
    )

    falta_ford = _vazio(valor_ford) or _e_ausencia(status_ford)
    falta_conc = _vazio(valor_concorrente) or _e_ausencia(status_concorrente)
    if falta_ford or falta_conc:
        if falta_ford and falta_conc:
            celula.motivo_tipo = SEM_DADO_NOS_DOIS
            celula.motivo = "nenhum dos dois lados tem valor verificado para este campo"
        elif falta_ford:
            celula.motivo_tipo = SEM_DADO_FORD
            celula.motivo = "a versão Ford não tem valor verificado para este campo"
        else:
            celula.motivo_tipo = SEM_DADO_CONCORRENTE
            celula.motivo = "o concorrente não tem valor verificado para este campo"
        return celula

    if campo in CAMPOS_LISTA and campo in LISTAS_ORDENAVEIS:
        estado, motivo, motivo_tipo = _do_conjunto(campo, valor_ford, valor_concorrente)
        celula.estado, celula.motivo, celula.motivo_tipo = estado, motivo, motivo_tipo
        return celula

    if campo in CAMPOS_BOOL:
        if bool(valor_ford) == bool(valor_concorrente):
            celula.estado = PARIDADE
            celula.motivo = "os dois têm" if valor_ford else "nenhum dos dois tem"
            return celula
        if campo in TER_E_MELHOR:
            celula.estado = VANTAGEM if valor_ford else GAP
            celula.motivo = "só a Ford tem" if valor_ford else "só o concorrente tem"
            return celula
        celula.motivo_tipo = SEM_DIRECAO_DE_MERITO
        celula.motivo = (
            "os valores diferem, e ter este item não é necessariamente melhor: "
            "os dois estão à vista para você decidir"
        )
        return celula

    if campo in MELHOR_QUANDO:
        na, nb = _numero(valor_ford), _numero(valor_concorrente)
        if na is not None and nb is not None:
            celula.estado, celula.motivo = _do_numero(campo, na, nb)
            celula.diferenca = round(na - nb, 4)
            return celula

    # Texto, ou número em campo sem direção declarada. Igual é paridade — isso se sabe.
    if normalize(str(valor_ford)) == normalize(str(valor_concorrente)):
        celula.estado = PARIDADE
        celula.motivo = "os dois declaram o mesmo valor"
        return celula

    celula.motivo_tipo = SEM_DIRECAO_DE_MERITO
    celula.motivo = (
        "os valores diferem e este campo não tem um lado melhor definido: "
        "os dois estão à vista, com evidência"
    )
    return celula


def valores_de_spec(spec: Any) -> dict[str, dict[str, Any]]:
    """`StandardSpec` → `{campo: {valor, status, unidade, evidence_id}}`.

    **Público** por causa da WP-35: o simulador precisa de um lugar onde trocar um valor
    sem fabricar um `SpecField`. Um valor hipotético dentro de um `SpecField` teria de
    escolher entre `verificado` (que exige evidência — e inventar uma citação para um
    número que ninguém observou é o pior defeito possível neste produto) e um dos status de
    ausência (que apagaria o valor da comparação, deixando o simulador inerte sem erro
    nenhum). Neste nível, evidência é só um id: o campo simulado leva `evidence_id=None`, a
    tela não mostra citação, e a comparação acontece.
    """
    saida: dict[str, dict[str, Any]] = {}
    for caminho, campo in spec.itens():
        nome = caminho.split(".", 1)[-1]
        saida[nome] = {
            "valor": campo.value,
            "status": campo.status,
            "unidade": campo.unit,
            "evidence_id": campo.evidences[0].evidence_id if campo.evidences else None,
        }
    return saida


#: Campos que não entram na matriz: são a **identidade** do veículo, não atributos a
#: comparar. "A marca da Ford é Ford e a do concorrente é Toyota" não é um gap.
CAMPOS_FORA_DA_MATRIZ = frozenset(
    {"marca", "modelo", "versao", "codigo_fipe", "preco_data", "fipe_referencia"}
)


def montar_coluna(
    spec_ford: Any,
    spec_concorrente: Any,
    *,
    version_id: str,
    rotulo: str,
    campos: list[str] | None = None,
    grupos: list[str] | None = None,
) -> ColunaDeParidade:
    """A coluna de um concorrente contra a versão Ford, campo a campo."""
    return montar_coluna_de_valores(
        valores_de_spec(spec_ford),
        valores_de_spec(spec_concorrente),
        version_id=version_id,
        rotulo=rotulo,
        campos=campos,
        grupos=grupos,
    )


def montar_coluna_de_valores(
    ford: dict[str, dict[str, Any]],
    conc: dict[str, dict[str, Any]],
    *,
    version_id: str,
    rotulo: str,
    campos: list[str] | None = None,
    grupos: list[str] | None = None,
) -> ColunaDeParidade:
    """A mesma coluna, a partir dos mapas de `valores_de_spec`.

    É o ponto de entrada do simulador (WP-35): a matriz de um cenário sai da **mesma**
    função da matriz real, com um dos mapas alterado. Duas implementações de paridade — uma
    para o real e outra para a hipótese — divergiriam, e a divergência apareceria como
    "no cenário mudou" quando o que mudou foi o código.
    """
    nomes = campos or [c for grupo in GRUPOS.values() for c in grupo]
    if grupos:
        nomes = [c for c in nomes if GRUPO_DO_CAMPO.get(c) in set(grupos)]
    nomes = [c for c in nomes if c not in CAMPOS_FORA_DA_MATRIZ]

    coluna = ColunaDeParidade(version_id=version_id, rotulo=rotulo)
    for nome in nomes:
        a = ford.get(nome) or {}
        b = conc.get(nome) or {}
        celula = comparar_campo(
            nome,
            valor_ford=a.get("valor"),
            valor_concorrente=b.get("valor"),
            status_ford=a.get("status"),
            status_concorrente=b.get("status"),
            unidade=a.get("unidade") or b.get("unidade"),
            evidence_id_ford=a.get("evidence_id"),
            evidence_id_concorrente=b.get("evidence_id"),
        )
        coluna.celulas.append(celula)
        setattr(coluna.contagem, celula.estado, getattr(coluna.contagem, celula.estado) + 1)
    return coluna


#: A legenda dos quatro estados, em texto do produto.
#:
#: Vive aqui e não na tela porque o PDF (WP-28) e a API precisam da **mesma** frase: duas
#: legendas para os mesmos quatro estados divergiriam na primeira revisão de texto.
LEGENDA: dict[str, str] = {
    VANTAGEM: "A Ford é melhor neste campo, pelos valores verificados dos dois lados.",
    PARIDADE: "Empate: a diferença está dentro da tolerância de medição do campo.",
    GAP: "O concorrente é melhor neste campo. Aparece sempre, sem exceção.",
    DESCONHECIDO: (
        "Não sabemos: falta valor verificado de um dos lados, ou o campo não tem um lado "
        "melhor definido. Nunca é exibido como empate."
    ),
}
