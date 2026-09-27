"""Faixas de referência por campo: a régua que transforma um valor em nota 0–10.

Uma nota só existe contra uma faixa. "397 cv" não é 10 nem 5 — é 10 **entre as picapes
médias que conhecemos** e seria modesto entre superesportivos. Por isso a faixa é dado
versionado, não constante no código: ela muda quando o mercado muda, e uma nota calculada
sob outra faixa não é comparável com a de hoje.

**Recalcular é comando explícito** (`specradar fit recompute-ranges`), e a spec pede isso
por um motivo forte: se a faixa fosse recalculada a cada consulta, a nota de um veículo
mudaria porque **outro** veículo entrou na base — o vendedor veria o número cair sem nada
ter mudado no carro dele. Faixa versionada, com data e com a origem de cada mínimo e
máximo, é o que torna a nota reproduzível.

**De onde vem a semente:** dos valores do `gabarito_v1.json` e, quando houver, das fichas
já persistidas no banco. Nada é inventado — cada faixa registra `de_onde` e quantos valores
a formaram. Faixa com **um** valor só é marcada `insuficiente` e o campo cai para uma nota
neutra em vez de sair 0 ou 10 por acidente de amostra.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parents[2]
ARQUIVO = Path(__file__).resolve().parent / "scoring_ranges.yaml"
GABARITO = RAIZ / "gabarito" / "gabarito_v1.json"

#: Mínimo de valores distintos para uma faixa ser usável.
#:
#: Dois. Com um valor só não há faixa — há um ponto, e qualquer veículo cairia em 0 ou 10
#: dependendo do lado. O campo então recebe nota neutra e a resposta diz por quê.
MINIMO_DE_AMOSTRAS = 2

#: A nota de um campo cuja faixa é insuficiente. Meio da escala, e **declarado**: é a única
#: nota que não afirma nem vantagem nem desvantagem.
NOTA_NEUTRA = 5.0


@dataclass
class Faixa:
    """A faixa de um campo, com a procedência à vista."""

    campo: str
    minimo: float
    maximo: float
    amostras: int
    de_onde: str = ""
    insuficiente: bool = False

    @property
    def amplitude(self) -> float:
        return self.maximo - self.minimo

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimo": self.minimo,
            "maximo": self.maximo,
            "amostras": self.amostras,
            "de_onde": self.de_onde,
            "insuficiente": self.insuficiente,
        }


@dataclass
class Faixas:
    versao: str
    por_campo: dict[str, Faixa] = field(default_factory=dict)

    def de(self, campo: str) -> Faixa | None:
        return self.por_campo.get(campo)

    def to_dict(self) -> dict[str, Any]:
        return {
            "versao": self.versao,
            "faixas": {campo: f.to_dict() for campo, f in sorted(self.por_campo.items())},
        }


def _numero(valor: Any) -> float | None:
    """Número, ou `None`. Booleano **não** é número aqui."""
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int | float):
        return float(valor)
    if isinstance(valor, str):
        from pipeline.units import parse_number_ptbr

        try:
            return parse_number_ptbr(valor)
        except ValueError:
            return None
    return None


def campos_numericos() -> list[str]:
    """Os campos numéricos declarados em `dimensions.yaml`. A tabela manda, não uma lista."""
    from pipeline.fit import dimensions

    config = dimensions.carregar()
    return [
        campo.campo
        for dimensao in config.dimensoes.values()
        for campo in dimensao.campos
        if campo.tipo == "numerico"
    ]


def valores_do_gabarito(campos: list[str]) -> dict[str, list[float]]:
    """Os valores esperados do gabarito, campo por campo.

    Só entra o que tem `status` de valor: um `nao_encontrado` com `esperado: null` não
    forma faixa, e incluí-lo como zero criaria um mínimo falso que puxaria toda nota.
    """
    if not GABARITO.exists():
        return {}
    dados = json.loads(GABARITO.read_text(encoding="utf-8"))
    coletado: dict[str, list[float]] = {campo: [] for campo in campos}
    for veiculo in dados.get("veiculos", []):
        for campo, bloco in (veiculo.get("atributos") or {}).items():
            if campo not in coletado or not isinstance(bloco, dict):
                continue
            numero = _numero(bloco.get("esperado"))
            if numero is not None:
                coletado[campo].append(numero)
    return coletado


def valores_do_banco(campos: list[str]) -> dict[str, list[float]]:
    """Os valores já persistidos. Sem banco, devolve vazio — não levanta.

    Recalcular faixa é operação de manutenção; ela não pode depender de o banco estar de pé.
    """
    coletado: dict[str, list[float]] = {campo: [] for campo in campos}
    try:
        from sqlmodel import Session, select

        from api.app.db import engine
        from api.app.models import SpecValue

        with Session(engine()) as sessao:
            linhas = sessao.exec(
                select(SpecValue).where(SpecValue.field.in_(campos))  # type: ignore[attr-defined]
            ).all()
            for linha in linhas:
                numero = _numero(linha.value_json)
                if numero is not None:
                    coletado.setdefault(linha.field, []).append(numero)
    except Exception:  # pragma: no cover - sem banco no ambiente
        return {campo: [] for campo in campos}
    return coletado


def calcular(*, incluir_banco: bool = True) -> Faixas:
    """Monta as faixas a partir do gabarito e (opcionalmente) do banco."""
    campos = campos_numericos()
    do_gabarito = valores_do_gabarito(campos)
    do_banco = valores_do_banco(campos) if incluir_banco else {}

    faixas = Faixas(versao=dt.date.today().isoformat())
    for campo in campos:
        gab = do_gabarito.get(campo, [])
        ban = do_banco.get(campo, [])
        todos = [*gab, *ban]
        distintos = sorted(set(todos))
        origens = []
        if gab:
            origens.append(f"gabarito ({len(gab)})")
        if ban:
            origens.append(f"banco ({len(ban)})")

        if not distintos:
            # Sem nenhum valor: a faixa existe declarada como vazia, para o motor poder
            # dizer "campo sem faixa" em vez de dividir por zero em silêncio.
            faixas.por_campo[campo] = Faixa(
                campo=campo,
                minimo=0.0,
                maximo=0.0,
                amostras=0,
                de_onde="nenhum valor observado",
                insuficiente=True,
            )
            continue

        faixas.por_campo[campo] = Faixa(
            campo=campo,
            minimo=min(distintos),
            maximo=max(distintos),
            amostras=len(distintos),
            de_onde=" + ".join(origens) or "sem origem registrada",
            insuficiente=len(distintos) < MINIMO_DE_AMOSTRAS,
        )
    return faixas


CABECALHO = """\
# Faixas de referência por campo — a régua que transforma valor em nota 0–10.
#
# GERADO por `specradar fit recompute-ranges`. Não edite à mão: o comando registra a
# procedência de cada faixa (`de_onde`, `amostras`) e a data em `versao`, e uma edição
# manual quebraria a correspondência entre a nota exibida e os dados que a formaram.
#
# `insuficiente: true` significa **um valor só ou nenhum**. O campo então recebe nota
# neutra (5,0) e a resposta diz o motivo, em vez de sair 0 ou 10 por acidente de amostra.
#
# Recalcular é comando explícito de propósito: se a faixa mudasse a cada consulta, a nota
# de um veículo cairia porque OUTRO veículo entrou na base — o vendedor veria o número
# mudar sem nada ter mudado no carro dele.
"""


def escrever(faixas: Faixas, destino: Path | None = None) -> Path:
    caminho = destino or ARQUIVO
    corpo = yaml.safe_dump(faixas.to_dict(), allow_unicode=True, sort_keys=False)
    caminho.write_text(CABECALHO + corpo, encoding="utf-8", newline="\n")
    return caminho


def carregar(caminho: Path | None = None) -> Faixas:
    """Lê o YAML. Arquivo ausente devolve faixas vazias — e o motor diz isso na resposta."""
    origem = caminho or ARQUIVO
    if not origem.exists():
        return Faixas(versao="sem faixas")
    dados = yaml.safe_load(origem.read_text(encoding="utf-8")) or {}
    faixas = Faixas(versao=str(dados.get("versao", "sem versao")))
    for campo, bruto in (dados.get("faixas") or {}).items():
        faixas.por_campo[campo] = Faixa(
            campo=campo,
            minimo=float(bruto.get("minimo", 0.0)),
            maximo=float(bruto.get("maximo", 0.0)),
            amostras=int(bruto.get("amostras", 0)),
            de_onde=str(bruto.get("de_onde", "")),
            insuficiente=bool(bruto.get("insuficiente", False)),
        )
    return faixas


def main(*, incluir_banco: bool = True) -> int:
    """`specradar fit recompute-ranges`. Devolve 0 em sucesso."""
    faixas = calcular(incluir_banco=incluir_banco)
    caminho = escrever(faixas)
    usaveis = sum(1 for f in faixas.por_campo.values() if not f.insuficiente)
    print(f"faixas: {len(faixas.por_campo)} campo(s), {usaveis} com faixa usavel")
    for campo, faixa in sorted(faixas.por_campo.items()):
        marca = "" if not faixa.insuficiente else "  <- insuficiente, nota neutra"
        print(
            f"  {campo:24} {faixa.minimo:>10,.2f} .. {faixa.maximo:>10,.2f}  "
            f"({faixa.amostras} valor(es), {faixa.de_onde}){marca}"
        )
    print(f"escrito: {caminho.relative_to(RAIZ)}")
    return 0
