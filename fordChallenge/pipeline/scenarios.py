"""O simulador: **"e se a Hilux baixar 5%?"**, respondido sem virar dado.

Três coisas separam este módulo de "um comparador com campo editável":

* **a hipótese nunca ganha evidência.** O valor simulado entra pelo mapa de
  `parity.valores_de_spec`, onde evidência é só um id — e o id do campo alterado vira
  `None`. Um `SpecField` com valor hipotético teria de escolher entre `verificado` (que
  exige citação: inventar uma para um número que ninguém observou é o pior defeito
  possível neste produto) e um status de ausência (que apagaria o valor da comparação e
  deixaria o simulador **inerte sem erro nenhum**);
* **a hipótese não vaza para a realidade.** O mapa de entrada é copiado, e os dois painéis
  — "Realidade" e "Cenário" — saem das **mesmas** funções de `parity.py`, `fit/engine.py` e
  `materiality/engine.py`. Uma segunda implementação de paridade "para cenários" divergiria,
  e a divergência apareceria como "no cenário mudou" quando o que mudou foi o código;
* **a origem do número é dita.** `ORIGEM` é literal e vai em todo override aplicado. A nota
  da spec é explícita: se perguntarem de onde veio o −5%, a resposta é "do usuário".

Não há sessão, `commit`, nem import de `api.app` aqui — o critério de aceite "nenhum
registro novo em `spec_values`" é garantido por **construção**, não por disciplina.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from pipeline import comparables, parity
from pipeline.fit import engine as fit
from pipeline.materiality import engine as materiality
from pipeline.radar.impact import DIMENSOES_POR_CAMPO
from pipeline.schema import Status, campos_canonicos

#: O rótulo, literal. `docs/13` §2 exige etiqueta em toda informação exibida, e este texto
#: é o da SIMULAÇÃO: some da resposta só nos painéis de realidade, que são FATO.
ROTULO = "SIMULAÇÃO — não é dado observado"

#: De onde veio o número. A nota da spec: "se perguntarem 'de onde veio o −5%': 'do usuário'".
ORIGEM = "hipótese informada pelo usuário"

#: Limite do `delta_pct`. A tela oferece −10%…+10%; a API recusa 900% em vez de aceitar em
#: silêncio um cenário que ninguém quis pedir.
DELTA_MAXIMO_PCT = 50.0

#: Campos em que arredondar para inteiro é o certo: centavo em tabela de preço é ruído de
#: apresentação, e "R$ 398.999,9997" na tela faria o usuário duvidar da conta toda.
CAMPOS_INTEIROS = frozenset(
    {"preco_sugerido_brl", "preco_fipe_brl", "capacidade_carga_kg", "capacidade_reboque_kg"}
)


class OverrideInvalido(ValueError):
    """O override pedido não pode ser aplicado, e a mensagem diz por quê."""


@dataclass(frozen=True)
class Override:
    """Uma hipótese do usuário: um campo de uma versão, de uma das três formas.

    **Exatamente uma** das três: `delta_pct` (variação percentual), `novo_valor` (valor
    absoluto) ou `remover` (o item deixa de existir na versão). Aceitar duas de uma vez
    exigiria uma ordem de precedência que ninguém pediu, e a resposta pareceria válida.
    """

    version_id: str
    campo: str
    delta_pct: float | None = None
    novo_valor: Any = None
    remover: bool = False

    def __post_init__(self) -> None:
        formas = [self.delta_pct is not None, self.novo_valor is not None, bool(self.remover)]
        if sum(formas) != 1:
            raise OverrideInvalido(
                f"override de {self.campo!r}: informe exatamente um entre `delta_pct`, "
                "`novo_valor` e `remover`"
            )
        if self.campo not in set(campos_canonicos()):
            raise OverrideInvalido(
                f"{self.campo!r} não é campo canônico do schema. Um override não cria "
                "campo: inventaria um atributo que a ficha não tem."
            )
        if self.delta_pct is not None and abs(self.delta_pct) > DELTA_MAXIMO_PCT:
            raise OverrideInvalido(
                f"delta_pct {self.delta_pct:g}% fora da faixa: use um valor entre "
                f"-{DELTA_MAXIMO_PCT:g}% e +{DELTA_MAXIMO_PCT:g}%"
            )


@dataclass
class OverrideAplicado:
    """O que o override fez, com o antes e o depois. É o que a tela cita."""

    version_id: str
    campo: str
    antes: Any
    depois: Any
    descricao: str
    origem: str = ORIGEM

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "campo": self.campo,
            "antes": self.antes,
            "depois": self.depois,
            "descricao": self.descricao,
            "origem": self.origem,
        }


@dataclass
class Lado:
    """Uma versão no cenário: id, rótulo e o mapa de `parity.valores_de_spec`."""

    version_id: str
    rotulo: str
    valores: dict[str, dict[str, Any]]

    def atributos(self) -> dict[str, Any]:
        """Mapa campo → valor para o `fit`, com ausência virando `None`.

        Mesma regra de `comparables.atributos_de_spec`: um `nao_encontrado` não pode virar
        o texto "nao_encontrado" e casar por igualdade com o do outro lado.
        """
        ausencias = {Status.NAO_ENCONTRADO, Status.NAO_DISPONIVEL, Status.NAO_VERIFICADO}
        saida: dict[str, Any] = {}
        for campo, celula in self.valores.items():
            status = str(celula.get("status") or "")
            saida[campo] = None if status in {s.value for s in ausencias} else celula.get("valor")
        return saida


#: A fonte que a flag dos 1.000 kg cita quando o número é hipótese.
#:
#: O texto fixo da flag fala de **enquadramento fiscal**, e por isso a fonte não pode
#: sair em branco nem herdar a URL da evidência real: quem lê tem de ver, na própria
#: frase, que o número veio de um cenário e não da ficha.
FONTE_DA_HIPOTESE = "hipótese do usuário no simulador (não é dado observado)"


@dataclass
class Painel:
    """Um lado do "Realidade × Cenário": a coluna de paridade e a aderência."""

    version_id: str
    rotulo: str
    coluna: parity.ColunaDeParidade
    valores: dict[str, dict[str, Any]] = field(default_factory=dict)
    aderencia: fit.Aderencia | None = None
    is_simulation: bool = False

    def flag_de_carga(self) -> dict[str, Any]:
        """A regra dos 1.000 kg sobre **este** painel.

        Recalculada por painel de propósito: um cenário que remove a capacidade de carga
        tem de deixar a flag **indeterminada** — "não avaliada" é diferente de "não
        atingida", e a diferença importa numa frase que fala de enquadramento fiscal.
        """
        celula = self.valores.get("capacidade_carga_kg") or {}
        fonte = (
            FONTE_DA_HIPOTESE
            if (self.is_simulation and celula.get("evidence_id") is None)
            else f"ficha de {self.rotulo}"
        )
        return comparables.flag_de_carga(celula.get("valor"), fonte=fonte).to_dict()

    def to_dict(self) -> dict[str, Any]:
        coluna = self.coluna.to_dict()
        coluna["flag_de_carga"] = self.flag_de_carga()
        return {
            "version_id": self.version_id,
            "rotulo": self.rotulo,
            "coluna": coluna,
            "aderencia": self.aderencia.to_dict() if self.aderencia else None,
            "is_simulation": self.is_simulation,
            # O rótulo viaja **no painel**, não só no topo: a tela mostra os dois lado a
            # lado, e uma faixa única no cabeçalho deixaria o painel do cenário sem aviso
            # quando alguém rolasse a página ou recortasse a imagem.
            "rotulo_simulacao": ROTULO if self.is_simulation else "",
        }


@dataclass
class MudancaDeParidade:
    campo: str
    antes: str
    depois: str
    motivo_antes: str = ""
    motivo_depois: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "campo": self.campo,
            "antes": self.antes,
            "depois": self.depois,
            "motivo_antes": self.motivo_antes,
            "motivo_depois": self.motivo_depois,
        }


@dataclass
class Diff:
    """O que mudaria, por concorrente. Vazio é resposta: nada mudaria."""

    version_id: str
    rotulo: str
    paridade: list[MudancaDeParidade] = field(default_factory=list)
    aderencia: list[dict[str, Any]] = field(default_factory=list)
    materialidade: dict[str, Any] | None = None
    motivo_sem_materialidade: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "rotulo": self.rotulo,
            "paridade": [m.to_dict() for m in self.paridade],
            "aderencia": list(self.aderencia),
            "materialidade": self.materialidade,
            "motivo_sem_materialidade": self.motivo_sem_materialidade,
        }


@dataclass
class Simulacao:
    """A resposta: realidade, cenário e o que mudaria entre os dois."""

    atual: list[Painel] = field(default_factory=list)
    cenario: list[Painel] = field(default_factory=list)
    diffs: list[Diff] = field(default_factory=list)
    overrides_aplicados: list[OverrideAplicado] = field(default_factory=list)
    is_simulation: bool = True
    rotulo: str = ROTULO
    motivo_sem_aderencia: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_simulation": self.is_simulation,
            "rotulo": self.rotulo,
            "atual": [p.to_dict() for p in self.atual],
            "cenario": [p.to_dict() for p in self.cenario],
            "diffs": [d.to_dict() for d in self.diffs],
            "overrides_aplicados": [o.to_dict() for o in self.overrides_aplicados],
            "motivo_sem_aderencia": self.motivo_sem_aderencia,
            "origem_dos_numeros": ORIGEM,
        }


# --------------------------------------------------------------------- aplicar override
MOTIVO_SEM_MATERIALIDADE = (
    "nenhum override neste concorrente: sem mudança hipotética não há materialidade a "
    "avaliar, e o cenário é igual à realidade"
)
MOTIVO_SEM_PERFIL = (
    "aderência não recalculada: nenhum perfil de necessidades foi informado. Sem as "
    "prioridades do cliente não há pesos, e uma nota sem pesos seria um número inventado."
)


def _numero(valor: Any) -> float | None:
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int | float):
        return float(valor)
    return None


def _descricao_de(override: Override, antes: Any, depois: Any) -> str:
    if override.remover:
        return f"hipótese: o item {override.campo} **não existe** nesta versão (hoje: {antes!r})"
    if override.delta_pct is not None:
        sinal = "−" if override.delta_pct < 0 else "+"
        return (
            f"hipótese: {override.campo} {sinal}{abs(override.delta_pct):g}% "
            f"({antes!r} → {depois!r})"
        )
    return f"hipótese: {override.campo} = {depois!r} (hoje: {antes!r})"


def aplicar(valores: dict[str, dict[str, Any]], override: Override) -> OverrideAplicado:
    """Aplica **em `valores`** (que já deve ser uma cópia) e devolve o registro.

    O campo alterado perde o `evidence_id`: a citação que sustentava o valor real não
    sustenta a hipótese. É o que impede a tela de exibir prova ao lado de um número que
    ninguém observou.
    """
    celula = valores.get(override.campo)
    if celula is None:
        # Campo canônico que a ficha não tem valor: o override cria a célula, porque "e se
        # a Hilux passar a ter bloqueio de diferencial?" é uma pergunta legítima.
        celula = {"valor": None, "status": Status.NAO_ENCONTRADO.value, "unidade": None}
        valores[override.campo] = celula

    antes = celula.get("valor")

    if override.remover:
        depois = None
        # `nao_disponivel` é "a fonte oficial afirma que o item não existe" — que é
        # exatamente a hipótese. E aí o campo sai da comparação: sem valor de um lado, o
        # estado é `desconhecido`, nunca empate.
        celula["status"] = Status.NAO_DISPONIVEL.value
    elif override.delta_pct is not None:
        base = _numero(antes)
        if base is None:
            raise OverrideInvalido(
                f"{override.campo} não é número neste veículo (valor atual: {antes!r}); "
                "variação percentual não se aplica. Use `novo_valor`."
            )
        bruto = base * (1 + override.delta_pct / 100.0)
        depois = round(bruto) if override.campo in CAMPOS_INTEIROS else round(bruto, 4)
        celula["status"] = Status.VERIFICADO.value
    else:
        depois = override.novo_valor
        celula["status"] = Status.VERIFICADO.value

    celula["valor"] = depois
    # A hipótese não herda a prova do valor real.
    celula["evidence_id"] = None

    return OverrideAplicado(
        version_id=override.version_id,
        campo=override.campo,
        antes=antes,
        depois=depois,
        descricao=_descricao_de(override, antes, depois),
    )


# ------------------------------------------------------------------------------ simular
def _diff_de_paridade(
    antes: parity.ColunaDeParidade, depois: parity.ColunaDeParidade
) -> list[MudancaDeParidade]:
    por_campo = {c.campo: c for c in antes.celulas}
    mudancas: list[MudancaDeParidade] = []
    for celula in depois.celulas:
        anterior = por_campo.get(celula.campo)
        if anterior is None or anterior.estado == celula.estado:
            continue
        mudancas.append(
            MudancaDeParidade(
                campo=celula.campo,
                antes=anterior.estado,
                depois=celula.estado,
                motivo_antes=anterior.motivo,
                motivo_depois=celula.motivo,
            )
        )
    return mudancas


def _diff_de_aderencia(
    antes: fit.Aderencia | None, depois: fit.Aderencia | None
) -> list[dict[str, Any]]:
    if antes is None or depois is None:
        return []
    por_id = {d.id: d for d in antes.dimensoes}
    saida: list[dict[str, Any]] = []
    for dimensao in depois.dimensoes:
        anterior = por_id.get(dimensao.id)
        if anterior is None:
            continue
        if (anterior.nota_concorrente, anterior.nota_ford) == (
            dimensao.nota_concorrente,
            dimensao.nota_ford,
        ):
            continue
        saida.append(
            {
                "dimensao": dimensao.id,
                "rotulo": dimensao.rotulo,
                "peso": dimensao.peso,
                "antes": {
                    "ford": anterior.nota_ford,
                    "concorrente": anterior.nota_concorrente,
                },
                "depois": {"ford": dimensao.nota_ford, "concorrente": dimensao.nota_concorrente},
            }
        )
    return saida


def _materialidade_do_cenario(
    aplicados: list[OverrideAplicado],
    mudancas: list[MudancaDeParidade],
    *,
    preco_ford: float | None,
) -> dict[str, Any] | None:
    """A materialidade da hipótese, pelo **mesmo** motor da WP-34.

    Um segundo cálculo de "isto importa?" para cenários diria coisas diferentes do Radar
    sobre a mesma mudança — e a pergunta do simulador é justamente "se isso acontecer, o
    Radar vai me acordar?".
    """
    if not aplicados:
        return None

    # O override mais forte é o que define o contexto: com dois campos alterados, avaliar
    # a soma exigiria uma régua de composição que não existe. Escolhemos o de maior |Δ%| e
    # dizemos qual foi — em vez de somar percentuais de grandezas diferentes.
    def magnitude(a: OverrideAplicado) -> float:
        antes, depois = _numero(a.antes), _numero(a.depois)
        if antes is None or depois is None or abs(antes) < 1e-9:
            return 0.0
        return abs(100.0 * (depois - antes) / abs(antes))

    principal = max(aplicados, key=magnitude)
    antes, depois = _numero(principal.antes), _numero(principal.depois)
    delta_pct: float | None = None
    if antes is not None and depois is not None and abs(antes) > 1e-9:
        delta_pct = round(100.0 * (depois - antes) / abs(antes), 2)

    contexto = materiality.Contexto(
        campo=principal.campo,
        antes=principal.antes,
        depois=principal.depois,
        delta_pct=delta_pct,
        dimensoes_afetadas=tuple(DIMENSOES_POR_CAMPO.get(principal.campo, ())),
        preco_ford_comparavel=preco_ford,
        parity_flips=tuple(
            {"campo": m.campo, "antes": m.antes, "depois": m.depois, "motivo": m.motivo_depois}
            for m in mudancas
        ),
        # SEMPRE simulado: é hipótese do usuário, e a cadeia tem de dizer isso.
        is_simulated=True,
    )
    saida = materiality.avaliar(contexto).to_dict()
    saida["campo_avaliado"] = principal.campo
    saida["motivo_do_campo"] = (
        "o override de maior variação percentual define o contexto; somar percentuais de "
        "grandezas diferentes não teria significado"
    )
    return saida


def simular(
    *,
    ford: Lado,
    concorrentes: list[Lado],
    overrides: list[Override],
    perfil: fit.NeedsProfile | None = None,
    campos: list[str] | None = None,
    grupos: list[str] | None = None,
) -> Simulacao:
    """Monta "Realidade × Cenário" e o diff entre os dois. **Nada é gravado.**"""
    ids = {ford.version_id, *(c.version_id for c in concorrentes)}
    for override in overrides:
        if override.version_id not in ids:
            raise OverrideInvalido(
                f"a versão {override.version_id!r} não está no cenário: só é possível "
                f"simular sobre as versões pedidas em `base_version_ids` ({sorted(ids)})"
            )

    # As cópias: a realidade não pode ser contaminada pela hipótese.
    ford_cenario = Lado(
        version_id=ford.version_id, rotulo=ford.rotulo, valores=copy.deepcopy(ford.valores)
    )
    concorrentes_cenario = [
        Lado(version_id=c.version_id, rotulo=c.rotulo, valores=copy.deepcopy(c.valores))
        for c in concorrentes
    ]
    por_id = {c.version_id: c for c in concorrentes_cenario}

    aplicados: list[OverrideAplicado] = []
    for override in overrides:
        alvo = (
            ford_cenario if override.version_id == ford.version_id else por_id[override.version_id]
        )
        aplicados.append(aplicar(alvo.valores, override))

    resultado = Simulacao(overrides_aplicados=aplicados)
    if perfil is None:
        resultado.motivo_sem_aderencia = MOTIVO_SEM_PERFIL

    atributos_ford_atual = ford.atributos()
    atributos_ford_cenario = ford_cenario.atributos()
    preco_ford = _numero(atributos_ford_atual.get("preco_sugerido_brl"))

    for atual, futuro in zip(concorrentes, concorrentes_cenario, strict=True):
        coluna_atual = parity.montar_coluna_de_valores(
            ford.valores,
            atual.valores,
            version_id=atual.version_id,
            rotulo=atual.rotulo,
            campos=campos,
            grupos=grupos,
        )
        coluna_cenario = parity.montar_coluna_de_valores(
            ford_cenario.valores,
            futuro.valores,
            version_id=futuro.version_id,
            rotulo=futuro.rotulo,
            campos=campos,
            grupos=grupos,
        )

        aderencia_atual = aderencia_cenario = None
        if perfil is not None:
            aderencia_atual = fit.avaliar(atributos_ford_atual, atual.atributos(), perfil)
            aderencia_cenario = fit.avaliar(atributos_ford_cenario, futuro.atributos(), perfil)

        resultado.atual.append(
            Painel(
                version_id=atual.version_id,
                rotulo=atual.rotulo,
                coluna=coluna_atual,
                valores=atual.valores,
                aderencia=aderencia_atual,
                is_simulation=False,
            )
        )
        resultado.cenario.append(
            Painel(
                version_id=futuro.version_id,
                rotulo=futuro.rotulo,
                coluna=coluna_cenario,
                valores=futuro.valores,
                aderencia=aderencia_cenario,
                is_simulation=True,
            )
        )

        mudancas = _diff_de_paridade(coluna_atual, coluna_cenario)
        deste = [a for a in aplicados if a.version_id in {futuro.version_id, ford.version_id}]
        diff = Diff(
            version_id=futuro.version_id,
            rotulo=futuro.rotulo,
            paridade=mudancas,
            aderencia=_diff_de_aderencia(aderencia_atual, aderencia_cenario),
            materialidade=_materialidade_do_cenario(deste, mudancas, preco_ford=preco_ford),
        )
        if diff.materialidade is None:
            diff.motivo_sem_materialidade = MOTIVO_SEM_MATERIALIDADE
        resultado.diffs.append(diff)

    return resultado
