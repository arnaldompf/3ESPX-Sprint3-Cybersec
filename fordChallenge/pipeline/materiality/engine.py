"""O Materiality Engine: **isto importa?**, respondido por regra somável.

A pergunta que este módulo responde é a que o Radar não respondia: um alerta dizia "o preço
mudou de 348.790 para 329.990", e o analista tinha de decidir sozinho se aquilo merecia a
manhã dele. Com trinta alertas por semana, "decidir sozinho" vira "olhar os três primeiros".

**Como funciona, e por que assim.** Cada regra de `rules.yaml` que dispara soma o seu peso;
a soma cai numa das quatro faixas. Três propriedades vêm dessa escolha:

* **`rules_fired` acompanha a nota, sempre.** "Materialidade ALTA" sozinho é um oráculo;
  "ALTA porque `price_band_entry` (40) + `magnitude_alta` (45)" é uma afirmação que alguém
  pode contestar. O `to_dict()` nunca devolve a faixa sem a lista;
* **peso negativo existe.** `par_nao_comparavel` **subtrai**: uma mudança na Raptor a
  gasolina não muda a conversa de quem compara picapes diesel de trabalho, e tratá-la como
  material encheria a fila com alertas que ninguém vai acionar;
* **os pesos são hipótese declarada.** Não há estudo atrás dos números, e o arquivo diz
  isso na primeira linha. O que o produto promete é que a régua está à vista, não que ela
  está certa.

`RUIDO` **não** é "ignorar": é "não interromper ninguém". O alerta continua na lista,
colapsado — sai da fila de prioridade, não do sistema.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ARQUIVO = Path(__file__).resolve().parent / "rules.yaml"

#: As quatro faixas, da mais forte para a mais fraca. A ordem é a da avaliação.
ALTA = "ALTA"
MEDIA = "MEDIA"
BAIXA = "BAIXA"
RUIDO = "RUIDO"
FAIXAS = (ALTA, MEDIA, BAIXA, RUIDO)

#: Os tipos de regra que o motor sabe avaliar. Tipo desconhecido no YAML **levanta**:
#: uma regra que o motor ignora em silêncio é uma linha de configuração que mente.
TIPOS = (
    "delta_percentual",
    "entrada_na_faixa",
    "saida_da_faixa",
    "gap_desfavoravel",
    "parity_flip",
    "dimensao_afetada",
    "par_nao_comparavel",
    "sem_equivalente",
)


class RegraInvalida(ValueError):
    """O `rules.yaml` declara algo que o motor não sabe avaliar."""


@dataclass(frozen=True)
class Regra:
    id: str
    peso: float
    tipo: str
    descricao: str = ""
    minimo_pct: float | None = None
    maximo_pct: float | None = None
    faixa_pct: float | None = None
    minimo_brl: float | None = None
    para: str | None = None
    dimensoes: tuple[str, ...] = ()
    veta: bool = False
    """Regra que **decide** em vez de somar: disparou, a faixa é `RUIDO`.

    Existe por um caso concreto: uma variação de 0,55% no preço FIPE somava +20 do peso da
    dimensão e virava `BAIXA`, ressuscitando o alerta que a regra de ruído existe para
    silenciar. Somar não resolve — o limiar de 1% é uma afirmação sobre o que **não**
    importa, e afirmação assim tem de vencer a aritmética.
    """


@dataclass(frozen=True)
class Faixa:
    nome: str
    minimo: float
    significado: str


@dataclass
class Config:
    versao: str
    faixas: tuple[Faixa, ...]
    regras: tuple[Regra, ...]

    def faixa_de(self, pontos: float) -> Faixa:
        """A faixa da pontuação. Sempre devolve uma: `RUIDO` tem mínimo zero."""
        for faixa in self.faixas:
            if pontos >= faixa.minimo:
                return faixa
        return self.faixas[-1]


@functools.lru_cache(maxsize=2)
def carregar(caminho: str | None = None) -> Config:
    """Lê e valida `rules.yaml`. Em cache: o arquivo não muda em execução."""
    origem = Path(caminho) if caminho else ARQUIVO
    dados: dict[str, Any] = yaml.safe_load(origem.read_text(encoding="utf-8")) or {}

    faixas = [
        Faixa(
            nome=str(nome),
            minimo=float(bloco.get("minimo", 0)),
            significado=" ".join(str(bloco.get("significado", "")).split()),
        )
        for nome, bloco in (dados.get("faixas") or {}).items()
    ]
    if not faixas:
        raise RegraInvalida("nenhuma faixa declarada: sem faixa não há materialidade")
    faltando = {f.nome for f in faixas} ^ set(FAIXAS)
    if faltando:
        raise RegraInvalida(
            f"as faixas do YAML não são as quatro de `docs/13` §3: diferença em {faltando}"
        )
    faixas.sort(key=lambda f: -f.minimo)
    if not any(f.significado for f in faixas):
        raise RegraInvalida("faixa sem `significado` não diz a quem lê o que fazer")

    regras: list[Regra] = []
    for bruto in dados.get("regras", []):
        tipo = str(bruto.get("tipo", ""))
        if tipo not in TIPOS:
            raise RegraInvalida(
                f"regra {bruto.get('id')!r}: tipo {tipo!r} desconhecido. Uma regra que o "
                f"motor ignora em silêncio é configuração que mente. Conhecidos: "
                f"{', '.join(sorted(TIPOS))}"
            )
        if not str(bruto.get("descricao", "")).strip():
            raise RegraInvalida(f"regra {bruto.get('id')!r} sem descrição: não é auditável")
        regras.append(
            Regra(
                id=str(bruto["id"]),
                peso=float(bruto.get("peso", 0)),
                tipo=tipo,
                descricao=" ".join(str(bruto.get("descricao", "")).split()),
                minimo_pct=_opcional_float(bruto.get("minimo_pct")),
                maximo_pct=_opcional_float(bruto.get("maximo_pct")),
                faixa_pct=_opcional_float(bruto.get("faixa_pct")),
                minimo_brl=_opcional_float(bruto.get("minimo_brl")),
                para=(str(bruto["para"]) if bruto.get("para") else None),
                dimensoes=tuple(str(d) for d in bruto.get("dimensoes", ())),
                veta=bool(bruto.get("veta", False)),
            )
        )
    if not regras:
        raise RegraInvalida("nenhuma regra declarada")

    return Config(
        versao=str(dados.get("versao", "sem versao")),
        faixas=tuple(faixas),
        regras=tuple(regras),
    )


def _opcional_float(valor: Any) -> float | None:
    return None if valor is None else float(valor)


# --------------------------------------------------------------------------- entrada
@dataclass
class Contexto:
    """Tudo o que as regras precisam saber, num objeto explícito.

    Nada é buscado aqui dentro: quem monta o contexto é o serviço da API
    (`api/app/services/materiality_service.py`), e o motor fica testável com dicionários.
    """

    campo: str = ""
    antes: Any = None
    depois: Any = None
    delta_pct: float | None = None
    gap_antes: float | None = None
    gap_depois: float | None = None
    dimensoes_afetadas: tuple[str, ...] = ()
    preco_ford_comparavel: float | None = None
    tem_equivalente: bool = True
    par_comparavel: bool = True
    parity_flips: tuple[dict[str, Any], ...] = ()
    is_simulated: bool = False


@dataclass
class RegraDisparada:
    """Uma regra que somou, com o peso e a razão. É o que a tela mostra no "Por quê?"."""

    id: str
    peso: float
    descricao: str
    detalhe: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "peso": self.peso,
            "descricao": self.descricao,
            "detalhe": self.detalhe,
        }


@dataclass
class Materialidade:
    """A saída: faixa, pontuação, regras que dispararam e o que elas significam."""

    faixa: str = RUIDO
    pontos: float = 0.0
    significado: str = ""
    rules_fired: list[RegraDisparada] = field(default_factory=list)
    parity_flips: list[dict[str, Any]] = field(default_factory=list)
    priority_rank: int = 0
    versao_das_regras: str = ""
    is_simulated: bool = False
    nota_de_hipotese: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "materiality": self.faixa,
            "pontos": self.pontos,
            "significado": self.significado,
            # A faixa **nunca** viaja sem as regras. Ver o docstring do módulo.
            "rules_fired": [r.to_dict() for r in self.rules_fired],
            "parity_flips": list(self.parity_flips),
            "priority_rank": self.priority_rank,
            "versao_das_regras": self.versao_das_regras,
            "is_simulated": self.is_simulated,
            "nota_de_hipotese": self.nota_de_hipotese,
        }


#: O que a cadeia diz quando o alerta é de demonstração. `docs/13` §2.
NOTA_DE_HIPOTESE = (
    "SIMULAÇÃO — este alerta é dado de demonstração, e a cadeia abaixo é uma hipótese: "
    "as regras são as mesmas, os valores não vêm de coleta real."
)

#: A nota dos pesos, repetida na resposta. Quem lê a nota tem de ler a ressalva.
#:
#: O caminho do arquivo de regras saiu da frase em 12/09/2026: `pipeline/materiality/
#: rules.yaml` não diz nada a quem vende picape, e o que a ressalva precisa dizer é que os
#: pesos são escolha declarada — e ajustável — e não uma lei da natureza.
NOTA_DOS_PESOS = "Os pesos são uma escolha declarada desta versão, e podem ser ajustados."


def _dentro_da_faixa(valor: float | None, referencia: float | None, faixa_pct: float) -> bool:
    """`valor` está a menos de `faixa_pct`% de `referencia`?"""
    if valor is None or referencia is None or referencia == 0:
        return False
    return abs(valor - referencia) / abs(referencia) * 100 <= faixa_pct


def _numero(valor: Any) -> float | None:
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int | float):
        return float(valor)
    return None


def _avaliar_regra(regra: Regra, ctx: Contexto) -> RegraDisparada | None:
    """Uma regra contra o contexto. `None` quando não dispara."""
    if regra.tipo == "delta_percentual":
        pct = abs(ctx.delta_pct) if ctx.delta_pct is not None else None
        if pct is None:
            return None
        if regra.minimo_pct is not None and pct < regra.minimo_pct:
            return None
        if regra.maximo_pct is not None and pct >= regra.maximo_pct:
            return None
        return RegraDisparada(regra.id, regra.peso, regra.descricao, f"|Δ| de {pct:.2f}%")

    if regra.tipo in {"entrada_na_faixa", "saida_da_faixa"}:
        faixa = regra.faixa_pct or 5.0
        antes = _numero(ctx.antes)
        depois = _numero(ctx.depois)
        referencia = ctx.preco_ford_comparavel
        if referencia is None or antes is None or depois is None:
            return None
        estava = _dentro_da_faixa(antes, referencia, faixa)
        esta = _dentro_da_faixa(depois, referencia, faixa)
        entrou = (not estava) and esta
        saiu = estava and (not esta)
        if regra.tipo == "entrada_na_faixa" and entrou:
            return RegraDisparada(
                regra.id,
                regra.peso,
                regra.descricao,
                f"entrou na faixa de ±{faixa:g}% de R$ {referencia:,.0f}".replace(",", "."),
            )
        if regra.tipo == "saida_da_faixa" and saiu:
            return RegraDisparada(
                regra.id,
                regra.peso,
                regra.descricao,
                f"saiu da faixa de ±{faixa:g}% de R$ {referencia:,.0f}".replace(",", "."),
            )
        return None

    if regra.tipo == "gap_desfavoravel":
        antes, depois = ctx.gap_antes, ctx.gap_depois
        if antes is None or depois is None:
            return None
        # Gap positivo = Ford mais cara (`pipeline/radar/impact.py`). Piorar é aumentar.
        piora = depois - antes
        if piora < (regra.minimo_brl or 0):
            return None
        return RegraDisparada(
            regra.id,
            regra.peso,
            regra.descricao,
            f"o gap piorou em R$ {piora:,.0f}".replace(",", "."),
        )

    if regra.tipo == "parity_flip":
        casados = [f for f in ctx.parity_flips if f.get("depois") == regra.para]
        if not casados:
            return None
        campos = ", ".join(str(f.get("campo")) for f in casados)
        return RegraDisparada(
            regra.id, regra.peso, regra.descricao, f"{len(casados)} campo(s): {campos}"
        )

    if regra.tipo == "dimensao_afetada":
        comuns = [d for d in ctx.dimensoes_afetadas if d in regra.dimensoes]
        if not comuns:
            return None
        return RegraDisparada(
            regra.id, regra.peso, regra.descricao, f"dimensões: {', '.join(comuns)}"
        )

    if regra.tipo == "par_nao_comparavel":
        if ctx.par_comparavel:
            return None
        return RegraDisparada(
            regra.id, regra.peso, regra.descricao, "o par não passa nos critérios"
        )

    if regra.tipo == "sem_equivalente":
        if ctx.tem_equivalente:
            return None
        return RegraDisparada(
            regra.id, regra.peso, regra.descricao, "nenhuma versão Ford equivalente cadastrada"
        )

    return None  # pragma: no cover - `carregar` já rejeita tipo desconhecido


def avaliar(ctx: Contexto, *, config: Config | None = None) -> Materialidade:
    """Aplica as regras e devolve a materialidade **com** as regras que dispararam."""
    cfg = config or carregar()

    disparadas: list[RegraDisparada] = []
    vetou = False
    for regra in cfg.regras:
        resultado = _avaliar_regra(regra, ctx)
        if resultado is None:
            continue
        disparadas.append(resultado)
        vetou = vetou or regra.veta

    pontos = round(sum(r.peso for r in disparadas), 2)
    # Pontuação negativa existe (o par não comparável subtrai) e cai em `RUIDO`, que é o
    # comportamento certo: não interromper ninguém por uma mudança que não muda a conversa.
    faixa = cfg.faixa_de(max(0.0, pontos))
    if vetou:
        # O veto decide. Ver o docstring de `Regra.veta`.
        faixa = next(f for f in cfg.faixas if f.nome == RUIDO)

    return Materialidade(
        faixa=faixa.nome,
        pontos=pontos,
        significado=faixa.significado,
        rules_fired=disparadas,
        parity_flips=list(ctx.parity_flips),
        priority_rank=rank_de(faixa.nome, pontos),
        versao_das_regras=cfg.versao,
        is_simulated=ctx.is_simulated,
        nota_de_hipotese=NOTA_DE_HIPOTESE if ctx.is_simulated else NOTA_DOS_PESOS,
    )


#: Base do rank por faixa. Menor é mais urgente — a fila ordena crescente.
#:
#: Os degraus de 1000 deixam a pontuação desempatar **dentro** da faixa sem nunca cruzar a
#: fronteira: um `MEDIA` de 59 pontos não passa na frente de um `ALTA` de 60.
BASE_DO_RANK = {ALTA: 0, MEDIA: 1000, BAIXA: 2000, RUIDO: 3000}


def rank_de(faixa: str, pontos: float) -> int:
    """A posição na fila. Menor primeiro; dentro da faixa, mais pontos primeiro."""
    return BASE_DO_RANK.get(faixa, 3000) + max(0, 999 - round(pontos))
