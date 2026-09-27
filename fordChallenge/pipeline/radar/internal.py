"""Referência interna da montadora (tier 0) e a divergência que ela revela.

É o **Fogo Amigo** com o dado do cliente: o gestor sobe a planilha que o time comercial
usa, e o sistema compara com a fonte pública. Quando divergem, o alerta nasce — e foi
exatamente isso que o slide da Raptor mostrou, dizendo "Baja" onde a ficha da Ford diz
"Off-Road".

**Sobre o "tier 0" de `docs/12` §6.1 — leia antes de comparar tiers.** No resto do
projeto o tier é uma ordenação onde **menor é mais forte**: 1 é a montadora, 2 é a FIPE,
3 é imprensa, 5 é fórum. Um "tier 0" nessa escala seria a fonte **mais** autoritativa —
o oposto do que o produto precisa, porque o material interno é justamente o que costuma
estar desatualizado. `docs/12` usa "T0" como **nome** da origem interna, não como posição
na ordenação, e é assim que este módulo o trata.

Por isso a referência interna vive na **própria tabela** (`internal_references`), e não em
`spec_values`: enquanto ela não entra na fila que o `status.py` ordena por tier, o 0 não
pode inverter nada. O dia em que alguém gravar uma linha interna em `spec_values` com
`tier=0`, o slide passa a vencer o site oficial e o "Fogo Amigo" se transforma no
contrário dele — confirmar o erro do deck com ar de autoridade. Há teste amarrando isso.

Para a extração, o mesmo slide entra como documento de **tier 4** (`pipeline/run.py`,
`TIER_REFERENCIA_INTERNA`), que é a posição correta na ordenação: abaixo de oficial, FIPE
e imprensa. Os dois números convivem porque respondem a perguntas diferentes — "de onde
veio" e "quanto vale contra as outras fontes".

**A comparação usa a mesma função do eval** (`pipeline.eval.compare.comparar_valor`). Se
usasse `!=`, `397` e `397.0` gerariam um alerta de divergência que não existe — e alerta
falso é o jeito mais rápido de fazer alguém parar de ler alertas.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any

from pipeline.eval.compare import comparar_valor
from pipeline.normalize import NaoNormalizavel, normalizar_campo
from pipeline.schema import GRUPOS

#: O rótulo da origem interna, na numeração de `docs/12` §6.1. **Não é uma posição na
#: ordenação de tiers** — ver o docstring do módulo. Nunca compare este valor com o tier
#: de uma fonte pública; para "quanto vale contra as outras fontes", o número é o
#: `TIER_REFERENCIA_INTERNA = 4` de `pipeline/run.py`.
TIER_INTERNO = 0
#: `source_type` gravado na evidência, para a origem nunca virar adivinhação.
SOURCE_TYPE = "interno"

#: As colunas que o CSV/JSON precisa ter (`docs/12` §6.1).
COLUNAS = ("versao", "campo", "valor")


class ReferenciaInvalida(ValueError):
    """Arquivo que não dá para importar, com o motivo em português."""


@dataclass
class LinhaDeReferencia:
    """Uma linha do arquivo, já normalizada."""

    versao: str
    campo: str
    valor: Any
    raw_value: str
    conversao: str = ""


@dataclass
class ResultadoDaImportacao:
    """O que entrou, o que ficou de fora, e **por quê** em cada caso."""

    linhas: list[LinhaDeReferencia] = field(default_factory=list)
    recusadas: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.linhas)


def _campos_canonicos() -> set[str]:
    return {campo for campos in GRUPOS.values() for campo in campos}


def _ler_csv(texto: str) -> list[dict[str, str]]:
    # `Sniffer` porque planilha exportada do Excel brasileiro usa `;` e a de fora usa `,`.
    # Errar o separador leria a linha inteira como uma coluna só, e o erro seria "coluna
    # `campo` ausente" — mensagem que não ajuda quem exportou do Excel.
    amostra = texto[:2048]
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=",;\t")
    except csv.Error:
        dialeto = csv.excel
    leitor = csv.DictReader(io.StringIO(texto), dialect=dialeto)
    return [{(k or "").strip().lower(): (v or "") for k, v in linha.items()} for linha in leitor]


def _ler_json(texto: str) -> list[dict[str, Any]]:
    dados = json.loads(texto)
    if isinstance(dados, dict):
        # Aceita `{"linhas": [...]}` além da lista pura: é a forma que sai de export de
        # ferramenta, e recusá-la só faria o gestor editar o arquivo à mão.
        dados = dados.get("linhas") or dados.get("referencias") or []
    if not isinstance(dados, list):
        raise ReferenciaInvalida("o JSON precisa ser uma lista de {versao, campo, valor}")
    return [{str(k).strip().lower(): v for k, v in item.items()} for item in dados]


def importar(texto: str, *, formato: str = "auto") -> ResultadoDaImportacao:
    """Lê o CSV/JSON do gestor e normaliza cada linha.

    Linha com campo fora do schema canônico é **recusada com o nome do campo**, não
    silenciada: o gestor precisa saber que aquela linha da planilha não entrou, e qual.
    """
    texto = texto.strip()
    if not texto:
        raise ReferenciaInvalida("arquivo vazio")

    if formato == "auto":
        formato = "json" if texto[0] in "[{" else "csv"

    try:
        brutas = _ler_json(texto) if formato == "json" else _ler_csv(texto)
    except json.JSONDecodeError as exc:
        raise ReferenciaInvalida(f"JSON inválido: {exc}") from exc

    if not brutas:
        raise ReferenciaInvalida("nenhuma linha encontrada no arquivo")

    faltando = [c for c in COLUNAS if c not in brutas[0]]
    if faltando:
        raise ReferenciaInvalida(
            f"colunas obrigatórias ausentes: {', '.join(faltando)}. "
            f"O arquivo precisa de {', '.join(COLUNAS)}."
        )

    canonicos = _campos_canonicos()
    resultado = ResultadoDaImportacao()

    for numero, bruta in enumerate(brutas, start=2):  # 2: a linha 1 é o cabeçalho
        versao = str(bruta.get("versao") or "").strip()
        campo = str(bruta.get("campo") or "").strip().split(".")[-1]
        valor = bruta.get("valor")

        if not versao or not campo:
            resultado.recusadas.append(f"linha {numero}: versão ou campo em branco")
            continue
        if campo not in canonicos:
            resultado.recusadas.append(
                f"linha {numero}: campo {campo!r} não existe no schema canônico"
            )
            continue

        try:
            normalizado = normalizar_campo(campo, valor)
        except NaoNormalizavel as exc:
            resultado.recusadas.append(f"linha {numero}: {exc}")
            continue

        resultado.linhas.append(
            LinhaDeReferencia(
                versao=versao,
                campo=campo,
                valor=normalizado.valor,
                raw_value=str(valor) if valor is not None else "",
                conversao=normalizado.conversao,
            )
        )

    return resultado


@dataclass
class Divergencia:
    """Um campo em que a referência interna e a fonte pública discordam."""

    campo: str
    valor_interno: Any
    valor_publico: Any
    raw_interno: str = ""
    documento: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "campo": self.campo,
            "valor_interno": self.valor_interno,
            "valor_publico": self.valor_publico,
            "raw_interno": self.raw_interno,
            "documento": self.documento,
        }


def comparar_com_publico(
    internos: dict[str, Any],
    publicos: dict[str, Any],
    *,
    documento: str = "",
    raws: dict[str, str] | None = None,
) -> list[Divergencia]:
    """As divergências entre a referência interna e a ficha pública.

    Campo que a fonte pública **não** tem não gera divergência: não há discordância entre
    um valor e uma ausência. Isso é `nao_encontrado` na ficha pública, e a tela já explica
    — transformar em alerta produziria uma enxurrada de "divergências" que são só lacunas
    de coleta.
    """
    achadas: list[Divergencia] = []
    raws = raws or {}
    for campo, valor_interno in internos.items():
        if campo not in publicos:
            continue
        valor_publico = publicos[campo]
        if valor_publico is None:
            continue
        # A MESMA função do eval: com `!=`, 397 e 397.0 gerariam divergência inexistente.
        if comparar_valor(campo, valor_interno, valor_publico).igual:
            continue
        achadas.append(
            Divergencia(
                campo=campo,
                valor_interno=valor_interno,
                valor_publico=valor_publico,
                raw_interno=raws.get(campo, ""),
                documento=documento,
            )
        )
    return achadas
