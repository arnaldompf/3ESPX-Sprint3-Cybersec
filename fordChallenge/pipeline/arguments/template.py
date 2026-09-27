"""O argumentário por template: **3 pontos Ford + 1 ponto do concorrente**, com evidência.

Determinístico, sem LLM, sem rede. É o caminho padrão — e a razão é operacional: um
argumentário que só funciona com modelo é um argumentário que falha exatamente na hora em
que o vendedor precisa dele, com o cliente na frente e a rede do showroom oscilando.

**O quarto ponto não é concessão, é o produto.** `docs/12` §3 diz que onde o concorrente
ganha fica sempre visível, e aqui isso tem uma razão comercial além da ética: o cliente
**já sabe** que a outra picape é melhor em alguma coisa, e um vendedor que não menciona
aquilo perde a credibilidade de tudo o que disse antes. O ponto de atenção é o que faz os
três primeiros valerem.

**Cada frase carrega os `evidence_id` que a sustentam** (`fonte_por_ponto`). Sem isso o
argumento é uma alegação bem escrita, que é o que este produto existe para não produzir.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

#: Quantos pontos a favor. Três, como `docs/12` §6.4 pede.
#:
#: O número tem razão de venda: a pessoa retém três coisas de uma conversa, e um
#: argumentário de dez pontos é um em que nenhum é lembrado. Se houver menos de três
#: dimensões vencedoras, a resposta traz menos pontos **e diz por quê** — repetir dimensão
#: para chegar a três seria inflar a lista.
PONTOS_A_FAVOR = 3

#: Como cada frase é montada. `docs/12` §6.4, com o formato literal.
FRASE_A_FAVOR = (
    "Para quem prioriza {dimensao}: a {ford} tem {campo} de {valor_ford} contra "
    "{valor_concorrente} da {concorrente} ({fonte}, {data})."
)
FRASE_DE_ATENCAO = (
    "Onde a {concorrente} leva vantagem: {campo} — {valor_concorrente} contra "
    "{valor_ford} da {ford} ({fonte}, {data})."
)

#: Campo de LISTA fala a **contagem**, com três exemplos. Nunca a lista inteira.
#:
#: Até 12/09/2026 o argumento de `adas_itens` saía com os catorze termos dos dois lados
#: numa frase só — "tem adas itens de assistente de permanência em faixa, assistente
#: autônomo de frenagem, alerta de colisão, … contra Pre-crash System (PCS) com frenagem
#: automática (carros, pedestres, ciclistas), Lane Departure Alert (LDA), …". Ninguém fala
#: isso em pé, com o cliente ao lado, e era justamente esse o uso.
#:
#: E havia um erro de conteúdo junto do de forma: a **nota que gerou este ponto é de
#: contagem** (`fit/dimensions.yaml` declara `adas_itens` como `tipo: contagem`, e o motor
#: pontua `len/teto`). A frase enumerava o que a nota não mede e **omitia o número que ela
#: mede**. A contagem também é a única parte que o verificador sustenta: `verify.py` já
#: aceita `len(valor)` como número achado na célula.
FRASE_A_FAVOR_LISTA = (
    "Para quem prioriza {dimensao}: a {ford} traz {n_ford} {substantivo}, entre eles "
    "{exemplos_ford}; a {concorrente} traz {n_concorrente} ({fonte}, {data})."
)
FRASE_DE_ATENCAO_LISTA = (
    "Onde a {concorrente} leva vantagem: {n_concorrente} {substantivo}, entre eles "
    "{exemplos_concorrente}; a {ford} traz {n_ford} ({fonte}, {data})."
)

#: Como cada campo de lista se chama numa frase falada. Fora daqui, "itens".
SUBSTANTIVO_DE_LISTA: dict[str, str] = {
    "adas_itens": "itens de assistência à condução",
    "modos_conducao": "modos de condução",
    "modos_direcao": "modos de direção",
    "modos_escapamento": "modos de escapamento",
    "modos_amortecedor": "modos de amortecedor",
}

#: Três exemplos. O número é o mesmo do argumentário inteiro, e pela mesma razão.
LIMITE_DE_EXEMPLOS = 3

#: O aviso quando não há três dimensões vencedoras com dado comparável.
MOTIVO_POUCOS_PONTOS = (
    "menos de {alvo} dimensões com vantagem e dado comparável dos dois lados; "
    "repetir dimensão para completar a lista seria inflar o argumentário"
)

#: O aviso quando o concorrente não vence em nada comparável.
MOTIVO_SEM_ATENCAO = (
    "nenhuma dimensão com dado comparável em que o concorrente leve vantagem. Isto não "
    "significa que ele não tenha nenhuma: significa que, entre os campos verificados dos "
    "dois lados, não apareceu"
)


@dataclass
class Ponto:
    """Um argumento, com a conta e a procedência."""

    dimensao: str
    rotulo_da_dimensao: str
    peso: float
    campo: str
    valor_ford: Any
    valor_concorrente: Any
    unidade: str | None
    texto: str
    fonte_por_ponto: list[str] = field(default_factory=list)
    """Os `evidence_id` das duas pontas. Frase sem isto é alegação bem escrita."""
    a_favor: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensao": self.dimensao,
            "rotulo_da_dimensao": self.rotulo_da_dimensao,
            "peso": self.peso,
            "campo": self.campo,
            "valor_ford": self.valor_ford,
            "valor_concorrente": self.valor_concorrente,
            "unidade": self.unidade,
            "texto": self.texto,
            "fonte_por_ponto": list(self.fonte_por_ponto),
            "a_favor": self.a_favor,
        }


@dataclass
class Argumentario:
    """A saída: os pontos, o de atenção, e de onde cada coisa veio."""

    pontos: list[Ponto] = field(default_factory=list)
    ponto_forte_concorrente: Ponto | None = None
    gerado_por: str = "template"
    aprovado: bool = False
    aprovado_por: str = ""
    avisos: list[str] = field(default_factory=list)
    texto_travado: str = ""
    """Texto que o gestor travou para este par, quando houver. Ver `docs/12` §6.4."""

    @property
    def fonte_por_ponto(self) -> list[list[str]]:
        return [p.fonte_por_ponto for p in self.pontos]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pontos": [p.to_dict() for p in self.pontos],
            "ponto_forte_concorrente": (
                self.ponto_forte_concorrente.to_dict() if self.ponto_forte_concorrente else None
            ),
            "fonte_por_ponto": self.fonte_por_ponto,
            "gerado_por": self.gerado_por,
            "aprovado": self.aprovado,
            "aprovado_por": self.aprovado_por,
            "avisos": list(self.avisos),
            "texto_travado": self.texto_travado,
        }


def _formatar(valor: Any, unidade: str | None) -> str:
    """Valor como se lê numa frase. Sem inventar precisão que o dado não tem."""
    if valor is None:
        return "sem valor"
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, list | tuple):
        return ", ".join(str(v).replace("_", " ") for v in valor)
    if isinstance(valor, float):
        texto = f"{valor:.10g}".replace(".", ",")
    elif isinstance(valor, int):
        texto = f"{valor:,}".replace(",", ".")
    else:
        texto = str(valor)
    return f"{texto} {unidade}" if unidade else texto


def _exemplos(valor: Any, quantos: int = LIMITE_DE_EXEMPLOS) -> str:
    """Os primeiros itens, com "e" antes do último.

    Sem reticências e sem "entre outros" no fim: a frase já começa com "entre eles", que é
    o que avisa que a lista não está inteira. Dizer duas vezes soa a desculpa.
    """
    itens = [str(v).replace("_", " ").strip() for v in valor if str(v).strip()][:quantos]
    if not itens:
        return ""
    if len(itens) == 1:
        return itens[0]
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def _e_lista(celula: Any) -> bool:
    """Os DOIS lados são lista? Só então a frase de contagem faz sentido."""
    return isinstance(celula.valor_ford, list | tuple) and isinstance(
        celula.valor_concorrente, list | tuple
    )


def _data_legivel(iso: str) -> str:
    if not iso:
        return "data não registrada"
    try:
        return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        return iso


@dataclass
class CampoDaCelula:
    """Um campo como a comparação o conhece: valor, unidade, fonte e data dos dois lados."""

    campo: str
    valor_ford: Any = None
    valor_concorrente: Any = None
    unidade: str | None = None
    evidence_id_ford: str | None = None
    evidence_id_concorrente: str | None = None
    fonte_ford: str = ""
    fonte_concorrente: str = ""
    data_ford: str = ""
    data_concorrente: str = ""


def _campo_mais_forte(
    dimensao: dict[str, Any], celulas: dict[str, CampoDaCelula], *, a_favor: bool
) -> CampoDaCelula | None:
    """O campo que melhor sustenta a dimensão: a maior diferença de nota entre os lados.

    Escolher o campo de maior diferença não é retórica — é o que dá ao vendedor a frase
    mais **defensável**. Um campo em que a vantagem é de 2% seria verdade e não seria
    argumento; o cliente compara os dois números e conclui que dá no mesmo.
    """
    melhor: CampoDaCelula | None = None
    melhor_delta = 0.0
    for indice, nota_ford in enumerate(dimensao.get("detalhe_ford", [])):
        detalhe_conc = dimensao.get("detalhe_concorrente", [])
        if indice >= len(detalhe_conc):
            continue
        nota_conc = detalhe_conc[indice]
        campo = nota_ford.get("campo")
        if campo not in celulas:
            continue
        nf = nota_ford.get("nota")
        nc = nota_conc.get("nota")
        if nf is None or nc is None:
            continue
        delta = (nf - nc) if a_favor else (nc - nf)
        if delta > melhor_delta:
            melhor_delta = delta
            melhor = celulas[campo]
    return melhor


def montar(
    aderencia: dict[str, Any],
    celulas: dict[str, CampoDaCelula],
    *,
    rotulo_ford: str,
    rotulo_concorrente: str,
    alvo_de_pontos: int = PONTOS_A_FAVOR,
) -> Argumentario:
    """Monta o argumentário a partir do bloco `fit` e das células da comparação.

    `aderencia` é o `to_dict()` de `pipeline/fit/engine.Aderencia`. As dimensões vencedoras
    entram **ordenadas por peso**: o argumento mais importante é o da dimensão que o
    cliente disse que mais importa, não o de maior diferença absoluta.
    """
    resultado = Argumentario()

    por_id = {d["dimensao"]: d for d in aderencia.get("dimensoes", [])}
    vence_ford = aderencia.get("vence_em", {}).get("ford", [])
    vence_conc = aderencia.get("vence_em", {}).get("concorrente", [])

    # Ordem por peso: a dimensão que o cliente priorizou vem primeiro.
    candidatas = sorted(
        (por_id[d] for d in vence_ford if d in por_id),
        key=lambda d: (-float(d.get("peso") or 0), d["dimensao"]),
    )

    for dimensao in candidatas:
        if len(resultado.pontos) >= alvo_de_pontos:
            break
        celula = _campo_mais_forte(dimensao, celulas, a_favor=True)
        if celula is None:
            continue
        resultado.pontos.append(
            Ponto(
                dimensao=dimensao["dimensao"],
                rotulo_da_dimensao=dimensao.get("rotulo") or dimensao["dimensao"],
                peso=float(dimensao.get("peso") or 0),
                campo=celula.campo,
                valor_ford=celula.valor_ford,
                valor_concorrente=celula.valor_concorrente,
                unidade=celula.unidade,
                texto=(
                    FRASE_A_FAVOR_LISTA.format(
                        dimensao=dimensao.get("rotulo") or dimensao["dimensao"],
                        ford=rotulo_ford,
                        concorrente=rotulo_concorrente,
                        substantivo=SUBSTANTIVO_DE_LISTA.get(celula.campo, "itens"),
                        n_ford=len(celula.valor_ford),
                        n_concorrente=len(celula.valor_concorrente),
                        exemplos_ford=_exemplos(celula.valor_ford),
                        fonte=celula.fonte_ford or "fonte não registrada",
                        data=_data_legivel(celula.data_ford),
                    )
                    if _e_lista(celula)
                    else FRASE_A_FAVOR.format(
                        dimensao=dimensao.get("rotulo") or dimensao["dimensao"],
                        ford=rotulo_ford,
                        campo=celula.campo.replace("_", " "),
                        valor_ford=_formatar(celula.valor_ford, celula.unidade),
                        valor_concorrente=_formatar(celula.valor_concorrente, celula.unidade),
                        concorrente=rotulo_concorrente,
                        fonte=celula.fonte_ford or "fonte não registrada",
                        data=_data_legivel(celula.data_ford),
                    )
                ),
                fonte_por_ponto=[
                    e for e in (celula.evidence_id_ford, celula.evidence_id_concorrente) if e
                ],
                a_favor=True,
            )
        )

    if len(resultado.pontos) < alvo_de_pontos:
        resultado.avisos.append(MOTIVO_POUCOS_PONTOS.format(alvo=alvo_de_pontos))

    # O ponto de atenção: a dimensão de maior peso em que o concorrente leva vantagem.
    for dimensao in sorted(
        (por_id[d] for d in vence_conc if d in por_id),
        key=lambda d: (-float(d.get("peso") or 0), d["dimensao"]),
    ):
        celula = _campo_mais_forte(dimensao, celulas, a_favor=False)
        if celula is None:
            continue
        resultado.ponto_forte_concorrente = Ponto(
            dimensao=dimensao["dimensao"],
            rotulo_da_dimensao=dimensao.get("rotulo") or dimensao["dimensao"],
            peso=float(dimensao.get("peso") or 0),
            campo=celula.campo,
            valor_ford=celula.valor_ford,
            valor_concorrente=celula.valor_concorrente,
            unidade=celula.unidade,
            texto=(
                FRASE_DE_ATENCAO_LISTA.format(
                    concorrente=rotulo_concorrente,
                    ford=rotulo_ford,
                    substantivo=SUBSTANTIVO_DE_LISTA.get(celula.campo, "itens"),
                    n_ford=len(celula.valor_ford),
                    n_concorrente=len(celula.valor_concorrente),
                    exemplos_concorrente=_exemplos(celula.valor_concorrente),
                    fonte=celula.fonte_concorrente or "fonte não registrada",
                    data=_data_legivel(celula.data_concorrente),
                )
                if _e_lista(celula)
                else FRASE_DE_ATENCAO.format(
                    concorrente=rotulo_concorrente,
                    campo=celula.campo.replace("_", " "),
                    valor_concorrente=_formatar(celula.valor_concorrente, celula.unidade),
                    valor_ford=_formatar(celula.valor_ford, celula.unidade),
                    ford=rotulo_ford,
                    fonte=celula.fonte_concorrente or "fonte não registrada",
                    data=_data_legivel(celula.data_concorrente),
                )
            ),
            fonte_por_ponto=[
                e for e in (celula.evidence_id_concorrente, celula.evidence_id_ford) if e
            ],
            a_favor=False,
        )
        break

    if resultado.ponto_forte_concorrente is None:
        resultado.avisos.append(MOTIVO_SEM_ATENCAO)

    return resultado
