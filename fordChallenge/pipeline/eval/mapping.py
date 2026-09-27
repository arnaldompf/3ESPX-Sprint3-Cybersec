"""Mapa entre os atributos do gabarito e os campos canônicos da ficha.

O gabarito foi escrito por humanos a partir de 4 execuções do Manus, e por isso agrupa
coisas que o schema canônico separa: `motor` é um objeto com quatro subcampos,
`rodas_pneus` tem cinco, `farois` tem três. Sem este mapa, o eval compararia peras com
laranjas — e como o eval é o oráculo de todo o projeto, um mapa errado envenena todas
as métricas de todas as WPs.

Regras do mapa:

* Atributo **escalar** do gabarito → um campo canônico.
* Atributo **objeto** → um campo canônico por subcampo. Subcampo que o schema canônico
  não tem (`marca_pneu`, `nivelamento`, `valvulas`, `descricao_oficial`, `extra`) é
  registrado em :data:`SUBCAMPOS_NAO_AVALIADOS`: existe no gabarito, **não** entra na
  contagem de exatidão, e aparece no relatório para ninguém achar que foi esquecido.
* `docs/09`: "subcampo `None` no gabarito = não avaliar".

Nada aqui inventa valor: o mapa só diz *onde* comparar.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.schema import grupo_de

#: Atributo escalar do gabarito -> campo canônico.
ESCALARES: dict[str, str] = {
    "potencia_cv": "potencia_cv",
    "potencia_rpm": "potencia_rpm",
    "torque_nm": "torque_nm",
    "torque_rpm": "torque_rpm",
    "aceleracao_0_100_s": "aceleracao_0_100_s",
    "modos_conducao": "modos_conducao",
    "modos_direcao": "modos_direcao",
    "modos_escapamento": "modos_escapamento",
    "modos_amortecedor": "modos_amortecedor",
    "preco_sugerido_brl": "preco_sugerido_brl",
    "preco_fipe_brl": "preco_fipe_brl",
    # v1.1: o consumo medido pelo PBE/Inmetro entra na medida. Só a Ranger Limited o
    # traz no gabarito por enquanto — os outros quatro têm o dado coletado (tabela PBEV
    # 2026) e a promoção depende de conferência humana, que é o que `docs/09` exige.
    "consumo_urbano_kml": "consumo_urbano_kml",
    "consumo_rodoviario_kml": "consumo_rodoviario_kml",
}

#: Atributo objeto do gabarito -> {subcampo do gabarito: campo canônico}.
OBJETOS: dict[str, dict[str, str]] = {
    "motor": {
        "deslocamento_l": "deslocamento_l",
        "cilindros": "cilindros",
        "combustivel": "combustivel",
        "aspiracao": "aspiracao",
    },
    "transmissao": {
        "tipo": "tipo",
        "numero_marchas": "numero_marchas",
        "paddle_shifters": "paddle_shifters",
    },
    "tracao": {
        "tipo": "tipo_tracao",
    },
    "farois": {
        "tipo": "farois_tipo",
        "neblina": "farois_neblina",
    },
    "rodas_pneus": {
        "aro_pol": "rodas_aro_pol",
        "material": "rodas_material",
        "pneus": "pneus_medida",
        "tipo_pneu": "pneus_tipo",
    },
    "pacote_adas": {
        "nome_comercial": "adas_nome_comercial",
        "itens": "adas_itens",
    },
    # `amortecedores` aparece nos dois formatos no gabarito: string ("FOX Racing 2.5
    # Live Valve", na Raptor) e objeto com suspensões (nos concorrentes).
    "amortecedores": {
        "amortecedores": "amortecedores",
        "suspensao_dianteira": "suspensao_dianteira",
        "suspensao_traseira": "suspensao_traseira",
    },
}

#: Atributo objeto que **também** aceita valor escalar; o escalar vai para este campo.
ESCALAR_ALTERNATIVO: dict[str, str] = {
    "amortecedores": "amortecedores",
    "tracao": "tipo_tracao",
    "farois": "farois_tipo",
}

#: Subcampos do gabarito sem campo canônico correspondente. Não são avaliados, e o
#: relatório do eval os lista para que a ausência seja explícita, nunca silenciosa.
SUBCAMPOS_NAO_AVALIADOS: frozenset[str] = frozenset(
    {
        "motor.valvulas",
        "tracao.descricao",
        "farois.nivelamento",
        "farois.extra",
        "rodas_pneus.marca_pneu",
        "rodas_pneus.descricao_oficial",
        "amortecedores.descricao_oficial",
    }
)

#: Fallback descritivo: `{atributo: (subcampo_de_origem, subcampo_canonico)}`.
#:
#: Caso real da S10: `amortecedores` vem `{"amortecedores": null, "descricao_oficial":
#: "suspensão com calibração refinada"}` com `status=verificado` — a fonte oficial **diz**
#: algo sobre a suspensão, só não nomeia o amortecedor. Como `docs/03` tipa
#: `chassi.amortecedores` como texto livre, a descrição oficial *é* o valor do campo
#: quando o subcampo específico está vazio. Sem esta regra, o eval trataria um
#: `verificado` legítimo como gabarito incoerente.
#:
#: Note que `rodas_pneus.descricao_oficial` **não** entra aqui: lá o humano registrou
#: `status=nao_encontrado` porque aro e medida realmente não foram informados — a frase
#: de marketing não vira valor de `rodas_aro_pol`.
FALLBACK_DESCRITIVO: dict[str, tuple[str, str]] = {
    "amortecedores": ("descricao_oficial", "amortecedores"),
}

#: Metadados do atributo do gabarito que descrevem outro campo canônico.
#: `preco_sugerido_brl.data` -> `preco_data`; `preco_fipe_brl.referencia` -> `fipe_referencia`.
METADADOS_COMO_CAMPO: dict[str, dict[str, str]] = {
    "preco_sugerido_brl": {"data": "preco_data"},
    "preco_fipe_brl": {"referencia": "fipe_referencia"},
}

#: Status do gabarito -> status do schema canônico que o pipeline pode devolver.
#: `verificado_tier3` é `verificado` com confiança <= 0,60 (docs/05, reconciliação).
#: `pendente_coleta` NÃO é erro do pipeline: o gabarito ainda não tem o valor.
STATUS_GABARITO_PARA_CANONICO: dict[str, tuple[str, ...]] = {
    "verificado": ("verificado",),
    "verificado_tier3": ("verificado",),
    "divergente": ("divergente",),
    # a fonte oficial afirmar ausência e nenhuma fonte citar são estados diferentes,
    # mas do ponto de vista do gabarito um `nao_encontrado` pode legitimamente virar
    # `nao_disponivel` quando o pipeline acha a afirmação de ausência (docs/09).
    "nao_encontrado": ("nao_encontrado", "nao_disponivel"),
    "nao_disponivel": ("nao_disponivel",),
    "pendente_coleta": ("verificado", "nao_encontrado", "nao_disponivel", "pendente"),
}

#: Status do gabarito que não contam para exatidão de valor (docs/09 e gabarito/README).
STATUS_SEM_AVALIACAO_DE_VALOR: frozenset[str] = frozenset({"pendente_coleta"})

#: Status do gabarito com valor esperado — só esses entram em `field_accuracy`.
STATUS_COM_VALOR: frozenset[str] = frozenset({"verificado", "verificado_tier3", "divergente"})


@dataclass(frozen=True)
class Alvo:
    """Um ponto de comparação: de onde no gabarito, para onde na ficha."""

    atributo: str
    """Nome do atributo no gabarito (ex.: `motor`)."""
    subcampo: str | None
    """Subcampo dentro de `esperado`, quando o atributo é objeto (ex.: `cilindros`)."""
    campo: str
    """Campo canônico (ex.: `cilindros`)."""

    @property
    def origem(self) -> str:
        return f"{self.atributo}.{self.subcampo}" if self.subcampo else self.atributo

    @property
    def caminho(self) -> str:
        grupo = grupo_de(self.campo)
        return f"{grupo}.{self.campo}" if grupo else f"extras.{self.campo}"


def alvos_do_atributo(nome: str, esperado: object) -> list[Alvo]:
    """Alvos de comparação de um atributo do gabarito, dado o formato do `esperado`.

    Um objeto rende um alvo por subcampo mapeado; um escalar rende um alvo só. O formato
    é decidido pelo dado, não pelo nome, porque `amortecedores` vem das duas formas.
    """
    if nome in ESCALARES:
        return [Alvo(nome, None, ESCALARES[nome])]

    mapa = OBJETOS.get(nome)
    if mapa is None:
        return []

    if isinstance(esperado, dict):
        alvos = [Alvo(nome, sub, campo) for sub, campo in mapa.items() if sub in esperado]
        for sub in esperado:
            if sub not in mapa and f"{nome}.{sub}" not in SUBCAMPOS_NAO_AVALIADOS:
                raise KeyError(
                    f"subcampo desconhecido no gabarito: {nome}.{sub}. "
                    "Acrescente ao mapa ou a SUBCAMPOS_NAO_AVALIADOS — "
                    "campo do gabarito não pode ser ignorado em silêncio."
                )
        return alvos

    # escalar (ou None) em atributo que também aceita objeto
    campo = ESCALAR_ALTERNATIVO.get(nome)
    return [Alvo(nome, None, campo)] if campo else []


def valor_do_alvo(alvo: Alvo, esperado: object) -> object:
    """Valor esperado de um alvo, aplicando o fallback descritivo quando cabe."""
    if alvo.subcampo is None or not isinstance(esperado, dict):
        return esperado
    valor = esperado.get(alvo.subcampo)
    if valor is None:
        fallback = FALLBACK_DESCRITIVO.get(alvo.atributo)
        if fallback and fallback[1] == alvo.subcampo:
            return esperado.get(fallback[0])
    return valor


def valores_avaliaveis(nome: str, esperado: object) -> list[object]:
    """Valores do `esperado` que o eval de fato compara.

    Subcampo puramente descritivo não conta como "valor esperado", **exceto** quando é o
    fallback de um campo canônico de texto livre (ver :data:`FALLBACK_DESCRITIVO`).
    """
    if not isinstance(esperado, dict):
        return [esperado]
    fallback = FALLBACK_DESCRITIVO.get(nome)
    origem_fallback = fallback[0] if fallback else None
    return [
        v
        for sub, v in esperado.items()
        if sub == origem_fallback or f"{nome}.{sub}" not in SUBCAMPOS_NAO_AVALIADOS
    ]


def campos_de_metadado(nome: str, atributo: dict) -> list[tuple[str, object]]:
    """`(campo_canonico, valor)` para metadados que são campo na ficha (data, referência)."""
    saida: list[tuple[str, object]] = []
    for chave, campo in METADADOS_COMO_CAMPO.get(nome, {}).items():
        if chave in atributo and atributo[chave] is not None:
            saida.append((campo, atributo[chave]))
    return saida


def status_compativel(status_gabarito: str, status_pipeline: str) -> bool:
    """O status do pipeline é aceitável para o status do gabarito?"""
    aceitos = STATUS_GABARITO_PARA_CANONICO.get(status_gabarito)
    if aceitos is None:
        raise KeyError(f"status de gabarito desconhecido: {status_gabarito!r}")
    return status_pipeline in aceitos


def validar_mapa() -> None:
    """Todo campo citado no mapa tem de existir no schema canônico.

    Chamado por teste. Se `docs/03` mudar, o mapa quebra alto em vez de comparar campo
    inexistente e reportar 0% de exatidão sem explicar por quê.
    """
    citados = set(ESCALARES.values()) | set(ESCALAR_ALTERNATIVO.values())
    for mapa in OBJETOS.values():
        citados |= set(mapa.values())
    for mapa in METADADOS_COMO_CAMPO.values():
        citados |= set(mapa.values())
    desconhecidos = sorted(c for c in citados if grupo_de(c) is None)
    if desconhecidos:
        raise AssertionError(f"campos do mapa que não existem no schema: {desconhecidos}")
