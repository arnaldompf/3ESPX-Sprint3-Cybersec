"""Impacto comercial de um alerta — por **regra**, nunca por LLM.

`docs/12` §6.1 pede: `impact = {delta, delta_pct, gap_antes, gap_depois,
dimensoes_afetadas[]}`. A razão de ser regra e não modelo de linguagem está na própria
natureza do número: *"o gap de preço era R$ 30 mil e virou R$ 42 mil"* é uma subtração, e
uma subtração que um modelo pode errar não deveria passar por um modelo. Regra também é
auditável — quem discordar do impacto pode conferir a conta.

Três cuidados que fazem a diferença entre um número útil e um número enganoso:

* **`delta_pct` sobre zero não existe.** Preço que era `null` e virou R$ 348.790 não subiu
  "infinito por cento": subiu de "não sabíamos" para um valor. O campo sai `None` com o
  motivo, em vez de um número que parece medição;

* **sem equivalente cadastrado não há gap.** A Raptor não tem par entre as picapes diesel
  de trabalho (`docs/12` §6.1), e inventar um par para poder exibir um gap seria comparar
  coisas que o gestor decidiu que não se comparam. `gap_antes`/`gap_depois` saem `None` e
  `motivo_sem_gap` diz por quê;

* **direção é do ponto de vista da Ford.** O preço do concorrente **caindo** é ruim para a
  Ford, e é isso que a reação sugerida precisa saber. `direcao` já sai traduzida
  (`favorece_ford` / `desfavorece_ford` / `neutro`), porque deixar cada tela interpretar o
  sinal do delta produziria interpretações diferentes na mesma empresa.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: Campos cuja mudança tem leitura comercial direta de preço.
CAMPOS_DE_PRECO = frozenset({"preco_sugerido_brl", "preco_fipe_brl"})

#: Quanto o valor precisa mudar, em porcentagem, para o alerta ser **material**.
#: Meio por cento no preço de uma picape é ~R$ 1.700 — abaixo disso é arredondamento de
#: tabela, e alerta que dispara por arredondamento treina o usuário a ignorar alertas.
LIMIAR_DE_MATERIALIDADE_PCT = 0.5

#: As dimensões do Need Engine (WP-26) que um campo alimenta. Enquanto a WP-26 não
#: existe, este mapa é o que permite dizer **quais** dimensões a mudança afeta — e é
#: informação de produto, não palpite: vem de `docs/12` §6.2.
DIMENSOES_POR_CAMPO: dict[str, tuple[str, ...]] = {
    "preco_sugerido_brl": ("preco",),
    "preco_fipe_brl": ("preco", "revenda"),
    # Os nomes canonicos sao `urbano`/`rodoviario` (`pipeline/schema.py`), e nao
    # `cidade`/`estrada`: com os nomes errados, uma mudanca de consumo saia com
    # `dimensoes_afetadas` VAZIA — sem erro nenhum, so sem efeito.
    "consumo_urbano_kml": ("custo_de_uso",),
    "consumo_rodoviario_kml": ("custo_de_uso",),
    "capacidade_carga_kg": ("carga",),
    "capacidade_reboque_kg": ("carga",),
    "potencia_cv": ("desempenho",),
    "torque_nm": ("desempenho", "carga"),
    "aceleracao_0_100_s": ("desempenho",),
    "tipo_tracao": ("off_road",),
    "reduzida": ("off_road",),
    "bloqueio_diferencial": ("off_road",),
    "adas_itens": ("seguranca",),
    "airbags_qtd": ("seguranca",),
    "garantia_meses": ("custo_de_uso",),
}

Direcao = str  # "favorece_ford" | "desfavorece_ford" | "neutro"


@dataclass
class Impacto:
    """O impacto comercial de uma mudança, com a conta à vista."""

    delta: float | None = None
    delta_pct: float | None = None
    gap_antes: float | None = None
    gap_depois: float | None = None
    dimensoes_afetadas: list[str] = field(default_factory=list)
    direcao: Direcao = "neutro"
    material: bool = False
    """A mudança passa do limiar de materialidade? Abaixo dele é ruído de tabela."""
    motivo_sem_delta: str = ""
    motivo_sem_gap: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _numero(valor: Any) -> float | None:
    """O valor como número, ou `None`. Booleano **não** é número aqui."""
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int | float):
        return float(valor)
    if isinstance(valor, str):
        limpo = valor.replace(".", "").replace(",", ".").strip()
        try:
            return float(limpo)
        except ValueError:
            return None
    return None


def _direcao_do_preco(delta: float, *, e_do_concorrente: bool) -> Direcao:
    """Preço do concorrente subindo favorece a Ford; caindo, desfavorece.

    Para um veículo Ford é o contrário — e é por isso que a função pergunta de quem é o
    preço em vez de olhar só o sinal. Um alerta que dissesse "favorece a Ford" quando o
    preço da própria Ranger subiu seria pior que nenhum alerta.
    """
    if abs(delta) < 1e-9:
        return "neutro"
    if e_do_concorrente:
        return "favorece_ford" if delta > 0 else "desfavorece_ford"
    return "desfavorece_ford" if delta > 0 else "favorece_ford"


def calcular(
    *,
    campo: str | None,
    antes: Any,
    depois: Any,
    preco_ford: float | None = None,
    preco_ford_equivalente_id: str | None = None,
    e_do_concorrente: bool = True,
) -> Impacto:
    """O impacto de uma mudança de valor.

    `preco_ford` é o preço da versão Ford equivalente **hoje**; sem ele não há gap, e o
    resultado diz isso em vez de omitir.
    """
    impacto = Impacto(dimensoes_afetadas=list(DIMENSOES_POR_CAMPO.get(campo or "", ())))

    n_antes, n_depois = _numero(antes), _numero(depois)

    if n_antes is None or n_depois is None:
        # Não é falha: campo de texto ou lista muda de verdade e não tem delta. O que
        # seria falha é exibir "0" e deixar quem lê achar que nada mudou.
        impacto.motivo_sem_delta = (
            "a mudança não é numérica (ou um dos lados não tinha valor); "
            "delta e percentual não se aplicam"
        )
        # Mudança em campo não numérico ainda é material: "Off-Road" → "Baja" importa.
        impacto.material = antes != depois
        return impacto

    impacto.delta = round(n_depois - n_antes, 4)

    if abs(n_antes) < 1e-9:
        # Divisão por zero disfarçada: "subiu infinito por cento" não é informação.
        impacto.motivo_sem_delta = (
            "o valor anterior era zero ou ausente; percentual de variação não existe"
        )
        impacto.material = True
    else:
        impacto.delta_pct = round(100.0 * (n_depois - n_antes) / abs(n_antes), 2)
        impacto.material = abs(impacto.delta_pct) >= LIMIAR_DE_MATERIALIDADE_PCT

    if campo in CAMPOS_DE_PRECO:
        impacto.direcao = _direcao_do_preco(impacto.delta, e_do_concorrente=e_do_concorrente)

        if preco_ford is None:
            impacto.motivo_sem_gap = (
                "sem equivalente Ford cadastrado com preço, não há gap a calcular. "
                "Cadastre em /equivalents ou aceite que esta versão não tem par direto."
                if preco_ford_equivalente_id is None
                else "o equivalente Ford está cadastrado, mas sem preço coletado"
            )
        else:
            # Gap positivo = a Ford está MAIS CARA que o concorrente. É a leitura que o
            # vendedor precisa: quanto ele tem de justificar.
            impacto.gap_antes = round(preco_ford - n_antes, 2)
            impacto.gap_depois = round(preco_ford - n_depois, 2)

    return impacto
