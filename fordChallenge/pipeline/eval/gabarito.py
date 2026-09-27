"""Carregador do gabarito — a verdade-terra do eval.

`gabarito/gabarito_v1.json` é **somente leitura** para o código: só um humano promove
`pendente_coleta` → `verificado`, editando `build_gabarito.py` com URL e trecho
(`docs/09`). Este módulo lê, valida a forma e expõe objetos tipados; ele nunca escreve.

O que a validação pega, e por que importa: um atributo com `status=nao_encontrado` e
`esperado` não nulo seria uma verdade-terra que exige alucinação. Se isso aparecer no
gabarito, o carregador levanta em vez de silenciosamente aceitar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from pipeline.eval.mapping import (
    OBJETOS,
    STATUS_COM_VALOR,
    STATUS_GABARITO_PARA_CANONICO,
    Alvo,
    alvos_do_atributo,
    campos_de_metadado,
    valor_do_alvo,
    valores_avaliaveis,
)

ROOT = Path(__file__).resolve().parent.parent.parent
GABARITO_PADRAO = ROOT / "gabarito" / "gabarito_v1.json"

#: Status do gabarito em que `esperado` obrigatoriamente é nulo.
_STATUS_SEM_ESPERADO = frozenset({"nao_encontrado", "nao_disponivel", "pendente_coleta"})


@dataclass(frozen=True)
class ExpectedField:
    """Um alvo de comparação já resolvido: campo canônico, valor esperado e status."""

    atributo: str
    origem: str
    campo: str
    caminho: str
    status: str
    valor: Any
    tier: int | None
    fontes: tuple[str, ...]
    trecho: str | None
    nota: str | None
    sinonimos: dict[str, str]
    divergencias: tuple[dict[str, Any], ...]
    slide_ford: Any = None
    tem_slide: bool = False
    subcampo: str | None = None
    valor_bruto: str | None = None
    conversao: str | None = None

    @property
    def avalia_valor(self) -> bool:
        """Só status com valor esperado entram em `field_accuracy`."""
        return self.status in STATUS_COM_VALOR and self.valor is not None

    @property
    def avalia_status(self) -> bool:
        """`docs/09`: "subcampo `None` no gabarito = não avaliar aquele subcampo".

        Caso real: `pacote_adas` da Raptor é `verificado`, mas
        `pacote_adas.nome_comercial` é `None` — a nota do gabarito diz "Ford não usa nome
        comercial na ficha BR". Exigir `verificado` de `adas_nome_comercial` seria exigir
        que o pipeline inventasse um nome. O subcampo vazio simplesmente sai da conta.
        """
        subcampo_vazio = self.subcampo is not None and self.valor is None
        return not (subcampo_vazio and self.status in STATUS_COM_VALOR)

    @property
    def tem_divergencia_registrada(self) -> bool:
        """O gabarito registrou mais de um valor para este campo, em qualquer status.

        Não é o mesmo que `status == "divergente"`: a aceleração da Raptor é
        `verificado_tier3` com 5,8 s da fonte oficial **e** 6,5 s medidos pela imprensa.
        O sistema tem de expor os dois (docs/13 §7, cena 4) mesmo sem marcar divergência.
        """
        return bool(self.divergencias)

    @property
    def valores_esperados(self) -> tuple[Any, ...]:
        """Todos os valores que o gabarito registra — o pipeline deve expor todos."""
        if not self.divergencias:
            return (self.valor,)
        extras = tuple(d["valor"] for d in self.divergencias if d.get("valor") is not None)
        return (self.valor, *extras)


@dataclass(frozen=True)
class ResolucaoEsperada:
    """`resultado_esperado` do caso negativo do resolvedor (Hilux GR-Sport)."""

    status: str
    mensagem_contem: tuple[str, ...]
    sugestao_equivalente: str | None
    ultimo_ano_fipe: int | None
    fontes: tuple[str, ...]


@dataclass
class Vehicle:
    """Um veículo do gabarito, com os alvos de comparação já resolvidos."""

    id: str
    marca: str
    modelo: str
    versao: str
    ano_modelo: int
    codigo_fipe: str
    papel: str
    origem: str
    linha_vigente: tuple[dict[str, Any], ...]
    campos: tuple[ExpectedField, ...]
    resultado_esperado: ResolucaoEsperada | None = None
    nao_avaliados: tuple[str, ...] = ()

    @property
    def e_caso_negativo(self) -> bool:
        return self.resultado_esperado is not None

    @property
    def nomes_da_linha_vigente(self) -> tuple[str, ...]:
        return tuple(v.get("nome_exato", "") for v in self.linha_vigente)

    def por_caminho(self, caminho: str) -> ExpectedField | None:
        for campo in self.campos:
            if campo.caminho == caminho:
                return campo
        return None

    @property
    def campos_com_slide(self) -> tuple[ExpectedField, ...]:
        """Campos que o slide interno da Ford cita — base do teste de Fogo Amigo."""
        return tuple(c for c in self.campos if c.tem_slide)

    @property
    def campos_divergentes(self) -> tuple[ExpectedField, ...]:
        """Campos em que o gabarito registra mais de um valor, ou status `divergente`."""
        return tuple(
            c for c in self.campos if c.status == "divergente" or c.tem_divergencia_registrada
        )

    @property
    def campos_ausentes_em_fonte_publica(self) -> tuple[ExpectedField, ...]:
        """Campos que o slide cita mas nenhuma fonte pública confirma.

        São os dois rpm da Raptor: o slide interno traz 5.650 e 3.500, a ficha pública
        não traz nenhum. `docs/09` conta isso junto das divergências (4/4).
        """
        return tuple(
            c
            for c in self.campos
            if c.tem_slide and c.slide_ford is not None and c.status == "nao_encontrado"
        )


@dataclass
class Gabarito:
    versao: str
    gerado_em: str
    descricao: str
    status_possiveis: dict[str, str]
    regras_eval: dict[str, str]
    veiculos: tuple[Vehicle, ...]
    caminho: Path = field(default=GABARITO_PADRAO)

    def por_id(self, vid: str) -> Vehicle:
        for v in self.veiculos:
            if v.id == vid:
                return v
        raise KeyError(f"veículo {vid!r} não está no gabarito")

    @property
    def veiculos_com_atributos(self) -> tuple[Vehicle, ...]:
        return tuple(v for v in self.veiculos if v.campos)


def _campo_de_alvo(alvo: Alvo, atributo: dict[str, Any], esperado_bruto: Any) -> ExpectedField:
    valor = valor_do_alvo(alvo, esperado_bruto)
    return ExpectedField(
        atributo=alvo.atributo,
        origem=alvo.origem,
        campo=alvo.campo,
        caminho=alvo.caminho,
        status=atributo["status"],
        valor=valor,
        tier=atributo.get("tier"),
        fontes=tuple(atributo.get("fontes") or ()),
        trecho=atributo.get("trecho"),
        nota=atributo.get("nota"),
        sinonimos=dict(atributo.get("sinonimos") or {}),
        divergencias=tuple(atributo.get("divergencias") or ()),
        slide_ford=atributo.get("slide_ford"),
        tem_slide="slide_ford" in atributo,
        subcampo=alvo.subcampo,
        valor_bruto=atributo.get("valor_bruto"),
        conversao=atributo.get("conversao"),
    )


def _valida_atributo(vid: str, nome: str, atributo: dict[str, Any]) -> None:
    status = atributo.get("status")
    if status not in STATUS_GABARITO_PARA_CANONICO:
        raise ValueError(f"{vid}/{nome}: status desconhecido {status!r}")
    esperado = atributo.get("esperado")
    avaliaveis = valores_avaliaveis(nome, esperado)
    if status in _STATUS_SEM_ESPERADO and any(v is not None for v in avaliaveis):
        raise ValueError(
            f"{vid}/{nome}: status={status} com esperado={esperado!r}. "
            "Verdade-terra vazia não pode exigir valor."
        )
    if status in STATUS_COM_VALOR and all(v is None for v in avaliaveis):
        raise ValueError(f"{vid}/{nome}: status={status} exige `esperado` não nulo")
    if status in STATUS_COM_VALOR and not atributo.get("fontes"):
        raise ValueError(f"{vid}/{nome}: status={status} exige `fontes`")
    if status == "divergente" and not atributo.get("nota"):
        raise ValueError(
            f"{vid}/{nome}: divergente precisa de `nota` explicando os valores concorrentes"
        )


def carregar_gabarito(caminho: str | Path | None = None) -> Gabarito:
    """Lê e valida o gabarito. Levanta em qualquer incoerência de verdade-terra."""
    caminho = Path(caminho or GABARITO_PADRAO)
    dados = json.loads(caminho.read_text(encoding="utf-8"))

    veiculos: list[Vehicle] = []
    for bruto in dados["veiculos"]:
        campos: list[ExpectedField] = []
        nao_avaliados: list[str] = []
        atributos: dict[str, Any] = bruto.get("atributos") or {}
        for nome, atributo in atributos.items():
            _valida_atributo(bruto["id"], nome, atributo)
            esperado = atributo.get("esperado")
            alvos = alvos_do_atributo(nome, esperado)
            if not alvos:
                nao_avaliados.append(nome)
                continue
            campos.extend(_campo_de_alvo(a, atributo, esperado) for a in alvos)
            # data do preço e referência FIPE são campos canônicos escondidos em metadado
            for campo_extra, valor in campos_de_metadado(nome, atributo):
                campos.append(
                    _campo_de_alvo(
                        Alvo(nome, None, campo_extra),
                        {**atributo, "status": "verificado"}
                        if atributo["status"] in STATUS_COM_VALOR
                        else atributo,
                        valor,
                    )
                )
            if isinstance(esperado, dict):
                mapeados = set(OBJETOS.get(nome, {}))
                nao_avaliados.extend(f"{nome}.{sub}" for sub in esperado if sub not in mapeados)

        resultado = bruto.get("resultado_esperado")
        veiculos.append(
            Vehicle(
                id=bruto["id"],
                marca=bruto["marca"],
                modelo=bruto["modelo"],
                versao=bruto["versao"],
                ano_modelo=bruto["ano_modelo"],
                codigo_fipe=bruto.get("codigo_fipe", ""),
                papel=bruto.get("papel", ""),
                origem=bruto.get("origem", ""),
                linha_vigente=tuple(bruto.get("linha_vigente") or ()),
                campos=tuple(campos),
                resultado_esperado=(
                    ResolucaoEsperada(
                        status=resultado["status"],
                        mensagem_contem=tuple(resultado.get("mensagem_contem") or ()),
                        sugestao_equivalente=resultado.get("sugestao_equivalente"),
                        ultimo_ano_fipe=resultado.get("ultimo_ano_fipe"),
                        fontes=tuple(resultado.get("fontes") or ()),
                    )
                    if resultado
                    else None
                ),
                nao_avaliados=tuple(nao_avaliados),
            )
        )

    return Gabarito(
        versao=dados["versao"],
        gerado_em=dados["gerado_em"],
        descricao=dados.get("descricao", ""),
        status_possiveis=dados.get("status_possiveis", {}),
        regras_eval=dados.get("regras_eval", {}),
        veiculos=tuple(veiculos),
        caminho=caminho,
    )


@lru_cache(maxsize=4)
def gabarito(caminho: str | None = None) -> Gabarito:
    """Versão cacheada de :func:`carregar_gabarito`."""
    return carregar_gabarito(caminho)
