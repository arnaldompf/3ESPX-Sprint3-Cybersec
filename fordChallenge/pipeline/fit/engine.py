"""O motor de aderência: perfil → pesos → notas → dimensões → `aderencia_total`.

**A regra que molda o módulo inteiro é "nunca penalizar dado faltante em silêncio"**
(`docs/12` §6.2, e é nota da spec). Ela tem três consequências que estão no código:

* um campo `nao_encontrado` num veículo **sai do cálculo dos dois**. Se saísse só do lado
  que não tem, o outro ganharia a dimensão por ter sido melhor coletado — o sistema
  premiaria a própria cobertura em vez de medir o carro;
* dimensão com menos da metade dos campos comparáveis é marcada `insuficiente` e
  **excluída do total**, com aviso. Diluí-la no total transformaria falta de dado em nota
  baixa, que é a mentira mais fácil de produzir aqui;
* toda dimensão devolve `campos_usados` e `campos_sem_dado`, com nome. Um "8,4" sem a
  decomposição não é auditável, e o vendedor vai defender aquele número na frente do
  cliente.

**A nota depende da faixa** (`ranges.py`): 397 cv é 10 entre picapes médias e seria modesto
entre superesportivos. Campo com faixa insuficiente recebe nota neutra (5,0) **e o motivo**,
em vez de 0 ou 10 por acidente de amostra.

O rótulo obrigatório de `docs/12` §6.2 acompanha toda saída, e o teste garante que ele não
some: "aderência 8,4" se lê como nota de qualidade, e não é — é o quanto o veículo atende ao
perfil digitado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pipeline.fit import dimensions, ranges
from pipeline.ontology import normalize


class PerfilInvalido(ValueError):
    """O perfil não fecha. A API traduz para 422 com a mensagem."""


class PrecoDeCombustivel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diesel: float | None = Field(default=None, ge=0)
    gasolina: float | None = Field(default=None, ge=0)


class NeedsProfile(BaseModel):
    """O perfil **anônimo** de necessidades. `docs/12` §6.2.

    Anônimo é requisito, não descuido: não há nome, CPF nem telefone aqui, e o modelo
    proíbe campo extra (`extra="forbid"`) justamente para um cliente não conseguir mandar
    dado pessoal junto e ele acabar gravado numa comparação.
    """

    model_config = ConfigDict(extra="forbid")

    uso: list[str] = Field(default_factory=list)
    prioridades_rank: list[str] = Field(default_factory=list)
    pesos_override: dict[str, float] | None = None
    faixa_preco_brl: tuple[float, float] | None = None
    km_mes: float | None = Field(default=None, ge=0)
    combustivel_preco: PrecoDeCombustivel = Field(default_factory=PrecoDeCombustivel)

    @field_validator("uso")
    @classmethod
    def _uso_conhecido(cls, valor: list[str]) -> list[str]:
        validos = set(dimensions.carregar().usos)
        desconhecidos = [u for u in valor if u not in validos]
        if desconhecidos:
            raise ValueError(
                f"uso desconhecido: {', '.join(desconhecidos)}. "
                f"Válidos: {', '.join(sorted(validos))}."
            )
        return valor

    @field_validator("prioridades_rank")
    @classmethod
    def _prioridades_conhecidas(cls, valor: list[str]) -> list[str]:
        validas = set(dimensions.carregar().dimensoes)
        desconhecidas = [p for p in valor if p not in validas]
        if desconhecidas:
            raise ValueError(
                f"prioridade desconhecida: {', '.join(desconhecidas)}. "
                f"Válidas: {', '.join(sorted(validas))}."
            )
        if len(set(valor)) != len(valor):
            raise ValueError("há prioridade repetida no ranking")
        return valor

    @model_validator(mode="after")
    def _override_fecha_em_100(self) -> NeedsProfile:
        if self.pesos_override is None:
            return self
        validas = set(dimensions.carregar().dimensoes)
        desconhecidas = [p for p in self.pesos_override if p not in validas]
        if desconhecidas:
            raise ValueError(f"peso para dimensão desconhecida: {', '.join(desconhecidas)}")
        soma = round(sum(self.pesos_override.values()), 6)
        if soma != 100:
            # 422, e com o número: "os pesos somam 93" é acionável, "pesos inválidos" não.
            raise ValueError(f"`pesos_override` soma {soma:g}, e precisa somar 100")
        return self


def pesos_de(perfil: NeedsProfile, *, config: dimensions.Config | None = None) -> dict[str, float]:
    """Os pesos por dimensão. Override ganha do ranking; fora do top 5, peso zero.

    Toda dimensão aparece no resultado, inclusive com zero. A tela **exibe os pesos**
    (`docs/12` §6.2), e uma dimensão ausente do dicionário seria indistinguível de uma com
    peso zero — o cliente não veria que "off-road" foi considerado e ficou de fora.
    """
    cfg = config or dimensions.carregar()
    pesos = dict.fromkeys(cfg.dimensoes, 0.0)

    if perfil.pesos_override is not None:
        for nome, peso in perfil.pesos_override.items():
            pesos[nome] = float(peso)
        return pesos

    for posicao, nome in enumerate(perfil.prioridades_rank):
        if posicao < len(cfg.pesos_por_rank):
            pesos[nome] = float(cfg.pesos_por_rank[posicao])
    return pesos


# --------------------------------------------------------------------------- notas
#: Teto de itens para a nota de contagem.
#:
#: Sete, que é o número de modos de condução da Raptor — o máximo observado nesta base. A
#: normalização é `min(itens, TETO) / TETO * 10`, então um oitavo modo não daria nota 11.
TETO_DE_CONTAGEM = 7

MOTIVO_SEM_FAIXA = "faixa de referência insuficiente (menos de dois valores observados)"
MOTIVO_SEM_VALOR = "sem valor verificado neste veículo"
MOTIVO_SEM_ORDEM = "valor fora da ordem declarada para o campo"


@dataclass
class NotaDeCampo:
    """A nota de um campo num veículo, com o valor que a produziu."""

    campo: str
    nota: float | None
    valor: Any = None
    motivo: str = ""

    @property
    def tem_nota(self) -> bool:
        return self.nota is not None

    def to_dict(self) -> dict[str, Any]:
        return {"campo": self.campo, "nota": self.nota, "valor": self.valor, "motivo": self.motivo}


def _escala_linear(valor: float, faixa: ranges.Faixa, direcao: str) -> float:
    """Valor → 0–10 dentro da faixa, com a direção. Fora da faixa, satura em 0 ou 10.

    Saturar é deliberado: um valor acima do máximo observado é o melhor que conhecemos, e
    extrapolar a escala daria nota 12 — número que a tela não sabe desenhar e que afirma
    mais do que a faixa sustenta.
    """
    if faixa.amplitude == 0:
        return ranges.NOTA_NEUTRA
    posicao = (valor - faixa.minimo) / faixa.amplitude
    posicao = max(0.0, min(1.0, posicao))
    if direcao == "menor":
        posicao = 1.0 - posicao
    return round(posicao * 10, 2)


def _numero(valor: Any) -> float | None:
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


def _chave_ordinal(campo: str, valor: Any) -> str:
    """A forma comparável de um valor ordinal: ontologia + normalização.

    `resolve_value` traduz `"matrix"` para a canônica `"Matrix LED"`, e a normalização
    tira acento e caixa. Assim o slug do YAML e o texto da ficha chegam ao mesmo lugar.
    """
    from pipeline.ontology import resolve_value

    canonico = resolve_value(campo, str(valor)) or str(valor)
    return normalize(canonico).replace(" ", "_")


def nota_de_campo(
    campo: dimensions.CampoDaDimensao, valor: Any, *, faixas: ranges.Faixas
) -> NotaDeCampo:
    """A nota de um campo, pelo tipo declarado em `dimensions.yaml`."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return NotaDeCampo(campo.campo, None, valor, MOTIVO_SEM_VALOR)
    if isinstance(valor, list | tuple) and len(valor) == 0 and campo.tipo != "contagem":
        return NotaDeCampo(campo.campo, None, valor, MOTIVO_SEM_VALOR)

    if campo.tipo == "booleano":
        return NotaDeCampo(campo.campo, 10.0 if bool(valor) else 0.0, valor)

    if campo.tipo == "contagem":
        itens = valor if isinstance(valor, list | tuple) else [valor]
        quantos = min(len(itens), TETO_DE_CONTAGEM)
        return NotaDeCampo(
            campo.campo,
            round(quantos / TETO_DE_CONTAGEM * 10, 2),
            list(itens),
            f"{len(itens)} item(ns), teto de {TETO_DE_CONTAGEM}",
        )

    if campo.tipo == "ordinal":
        # A comparação passa pela ontologia dos dois lados. O `dimensions.yaml` escreve a
        # ordem em slug (`matrix`, `full_led`), e a ficha guarda a forma canônica de
        # exibição que a ontologia define (`"Matrix LED"`). Comparar as duas cruas fazia
        # **todo** valor real cair em "fora da ordem" e receber nota neutra — a escala
        # ordinal inteira ficava inerte, sem nenhum erro aparecer.
        alvo = _chave_ordinal(campo.campo, valor)
        ordem = [_chave_ordinal(campo.campo, o) for o in campo.ordem]
        if alvo not in ordem:
            # Valor fora da ordem não vira zero: zero afirmaria "o pior da escala", e o que
            # se sabe é que não reconhecemos o valor. Nota neutra, com o motivo.
            return NotaDeCampo(campo.campo, ranges.NOTA_NEUTRA, valor, MOTIVO_SEM_ORDEM)
        posicao = ordem.index(alvo)
        divisor = max(1, len(ordem) - 1)
        return NotaDeCampo(campo.campo, round(posicao / divisor * 10, 2), valor)

    if campo.tipo == "presenca_de_termo":
        texto = normalize(str(valor))
        achados = [t for t in campo.termos if normalize(t) in texto]
        return NotaDeCampo(
            campo.campo,
            10.0 if achados else 0.0,
            valor,
            f"termos encontrados: {', '.join(achados)}" if achados else "nenhum termo da lista",
        )

    numero = _numero(valor)
    if numero is None:
        return NotaDeCampo(campo.campo, None, valor, "valor não numérico em campo numérico")
    faixa = faixas.de(campo.campo)
    if faixa is None or faixa.insuficiente:
        return NotaDeCampo(campo.campo, ranges.NOTA_NEUTRA, valor, MOTIVO_SEM_FAIXA)
    return NotaDeCampo(
        campo.campo,
        _escala_linear(numero, faixa, campo.direcao or "maior"),
        valor,
        f"faixa {faixa.minimo:g}..{faixa.maximo:g} ({faixa.de_onde})",
    )


#: Diferença relativa que satura a escala quando a nota sai do **par**. Ver
#: :func:`notas_do_par`.
#:
#: Trinta por cento, e é escolha de produto declarada — não medida. Entre duas picapes do
#: mesmo segmento, 30% de diferença em consumo, carga ou preço é gap decisivo; 3% é
#: variação de medição e de configuração. A escala proporcional evita o absurdo de dar
#: 10 e 0 a 9,7 contra 9,6 km/l.
DIFERENCA_QUE_SATURA = 0.30

MOTIVO_PAR = (
    "faixa formada pelos dois veículos comparados (o segmento não tem valores suficientes); "
    "a nota é relativa a este par, não ao mercado"
)
MOTIVO_PAR_EMPATE = "os dois valores são praticamente iguais; nota neutra para os dois"


def notas_do_par(
    campo: dimensions.CampoDaDimensao,
    valor_ford: Any,
    valor_concorrente: Any,
    *,
    faixas: ranges.Faixas,
) -> tuple[NotaDeCampo, NotaDeCampo]:
    """As notas dos dois veículos num campo, **cientes um do outro**.

    Existe por um defeito que a primeira versão tinha: campo numérico cuja faixa de
    segmento é insuficiente recebia nota neutra (5,0) nos dois lados. Só que quando os
    **dois** veículos têm valor — 9,7 contra 7,2 km/l — a ordem é conhecida, e devolver
    5,0 para ambos **descarta informação que existe**. Era o mesmo erro que o produto
    combate na matriz de paridade: transformar "sabemos" em "não sabemos".

    Quando a faixa do segmento serve, ela manda: a nota fica comparável entre consultas.
    Quando não serve, o par vira a régua e a nota diz isso no `motivo` — a proporção usa
    a diferença relativa, então uma diferença pequena dá notas próximas em vez de 10 e 0.
    """
    nota_f = nota_de_campo(campo, valor_ford, faixas=faixas)
    nota_c = nota_de_campo(campo, valor_concorrente, faixas=faixas)

    if campo.tipo != "numerico":
        return nota_f, nota_c
    # Só entra quando os dois têm valor e a faixa do segmento não serviu.
    if not (nota_f.tem_nota and nota_c.tem_nota):
        return nota_f, nota_c
    faixa = faixas.de(campo.campo)
    if faixa is not None and not faixa.insuficiente:
        return nota_f, nota_c

    a, b = _numero(valor_ford), _numero(valor_concorrente)
    if a is None or b is None:
        return nota_f, nota_c

    maior = max(abs(a), abs(b))
    if maior == 0:
        return nota_f, nota_c
    diferenca = abs(a - b) / maior
    if diferenca == 0:
        return (
            NotaDeCampo(campo.campo, ranges.NOTA_NEUTRA, valor_ford, MOTIVO_PAR_EMPATE),
            NotaDeCampo(campo.campo, ranges.NOTA_NEUTRA, valor_concorrente, MOTIVO_PAR_EMPATE),
        )

    amplitude = 5 * min(1.0, diferenca / DIFERENCA_QUE_SATURA)
    ford_melhor = (a > b) if (campo.direcao or "maior") == "maior" else (a < b)
    nota_melhor = round(ranges.NOTA_NEUTRA + amplitude, 2)
    nota_pior = round(ranges.NOTA_NEUTRA - amplitude, 2)
    motivo = f"{MOTIVO_PAR}; diferença de {diferenca:.0%}"
    return (
        NotaDeCampo(campo.campo, nota_melhor if ford_melhor else nota_pior, valor_ford, motivo),
        NotaDeCampo(
            campo.campo, nota_pior if ford_melhor else nota_melhor, valor_concorrente, motivo
        ),
    )


def _marcar_piso_da_faixa(avaliada: DimensaoAvaliada, regua: ranges.Faixas) -> None:
    """Nota perto de zero é **posição na amostra**, e a tela tem de dizer isso.

    `_escala_linear` satura em 0 no piso da faixa, e saturar é decisão declarada e certa —
    extrapolar daria nota 12. O problema não é o número: é a **leitura**. Um 0,1 ao lado de
    um 10,0 comunica "este carro não tem desempenho nenhum", e o carro do parecer tem
    204 cv. Ele é o menor dos **quatro** veículos da amostra, o que é uma frase bem
    diferente.

    `docs/12` §3 proíbe exagerar sobre o concorrente com a mesma força com que proíbe
    esconder onde ele vence, e o projeto já resolve esse tipo de coisa do mesmo jeito em
    toda tela: **nomeando a régua e o denominador**, em vez de mexer no número.

    Achado em 12/09/2026, investigando o item 7 de um parecer de uso — cujo diagnóstico
    original (o dado faltante estaria zerando a dimensão) se mostrou **falso**: a regra do
    dado faltante funciona, e há teste provando. O que o avaliador viu foi isto.
    """
    LIMITE = 1.0  # abaixo de 1,0 de 10 a leitura "não tem o atributo" já é inevitável

    for lado, nota in (
        ("ford", avaliada.nota_ford),
        ("concorrente", avaliada.nota_concorrente),
    ):
        if nota is None or nota >= LIMITE:
            continue
        avaliada.nota_no_piso.append(lado)

    if not avaliada.nota_no_piso:
        return

    # A frase cita a faixa do campo que puxou a nota para baixo — o de menor nota entre os
    # usados —, porque uma ressalva genérica não é conferível.
    detalhe = (
        avaliada.detalhe_concorrente
        if "concorrente" in avaliada.nota_no_piso
        else avaliada.detalhe_ford
    )
    piores = sorted((n for n in detalhe if n.nota is not None), key=lambda n: n.nota or 0)
    if not piores:
        return
    pior = piores[0]
    faixa = regua.de(pior.campo)
    if faixa is None:
        return

    quem = " e ".join(
        "a Ford" if lado == "ford" else "a concorrente" for lado in avaliada.nota_no_piso
    )
    avaliada.aviso_da_escala = (
        f"a nota é posição na faixa observada, não ausência do item: em "
        f"{pior.campo.replace('_', ' ')}, {quem} está no menor valor entre os "
        f"{faixa.amostras} veículos comparados (de {faixa.minimo:g} a {faixa.maximo:g})."
    )


# --------------------------------------------------------------------------- dimensões
@dataclass
class DimensaoAvaliada:
    """Uma dimensão: peso, as duas notas, e **o que entrou e o que faltou**."""

    id: str
    rotulo: str
    peso: float
    nota_ford: float | None = None
    nota_concorrente: float | None = None
    campos_usados: list[str] = field(default_factory=list)
    campos_sem_dado: list[dict[str, str]] = field(default_factory=list)
    insuficiente: bool = False
    aviso: str = ""
    #: Quais lados ficaram no **piso da faixa observada** (`"ford"` e/ou `"concorrente"`).
    #:
    #: Uma nota perto de zero aqui não quer dizer "este carro não tem o atributo": quer
    #: dizer "é o menor valor entre os poucos veículos da amostra". A distinção é o produto:
    #: `docs/12` §3 proíbe exagerar sobre o concorrente tanto quanto proíbe escondê-lo.
    nota_no_piso: list[str] = field(default_factory=list)
    #: A frase que explica a régua quando alguém ficou no piso. `None` quando ninguém ficou.
    aviso_da_escala: str | None = None
    detalhe_ford: list[NotaDeCampo] = field(default_factory=list)
    detalhe_concorrente: list[NotaDeCampo] = field(default_factory=list)

    @property
    def cobertura(self) -> float | None:
        total = len(self.campos_usados) + len(self.campos_sem_dado)
        return (len(self.campos_usados) / total) if total else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensao": self.id,
            "rotulo": self.rotulo,
            "peso": self.peso,
            "nota_ford": self.nota_ford,
            "nota_concorrente": self.nota_concorrente,
            "campos_usados": list(self.campos_usados),
            "campos_sem_dado": list(self.campos_sem_dado),
            "cobertura": self.cobertura,
            "insuficiente": self.insuficiente,
            "aviso": self.aviso,
            "nota_no_piso": list(self.nota_no_piso),
            "aviso_da_escala": self.aviso_da_escala,
            "detalhe_ford": [n.to_dict() for n in self.detalhe_ford],
            "detalhe_concorrente": [n.to_dict() for n in self.detalhe_concorrente],
        }


@dataclass
class Aderencia:
    """A saída do motor. `rotulo` é obrigatório e vai em toda resposta."""

    aderencia_ford: float | None = None
    aderencia_concorrente: float | None = None
    pesos: dict[str, float] = field(default_factory=dict)
    dimensoes: list[DimensaoAvaliada] = field(default_factory=list)
    vence_em: dict[str, list[str]] = field(default_factory=lambda: {"ford": [], "concorrente": []})
    peso_considerado: float = 0.0
    """Soma dos pesos das dimensões que entraram. Menor que 100 quando alguma é insuficiente."""
    avisos: list[str] = field(default_factory=list)
    rotulo: str = ""
    versao_das_dimensoes: str = ""
    versao_das_faixas: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "aderencia_ford": self.aderencia_ford,
            "aderencia_concorrente": self.aderencia_concorrente,
            "pesos": dict(self.pesos),
            "dimensoes": [d.to_dict() for d in self.dimensoes],
            "vence_em": {k: list(v) for k, v in self.vence_em.items()},
            "peso_considerado": self.peso_considerado,
            "avisos": list(self.avisos),
            "rotulo": self.rotulo,
            "versao_das_dimensoes": self.versao_das_dimensoes,
            "versao_das_faixas": self.versao_das_faixas,
        }


def _sem_valor(nota: NotaDeCampo) -> bool:
    return not nota.tem_nota


def avaliar(
    atributos_ford: dict[str, Any],
    atributos_concorrente: dict[str, Any],
    perfil: NeedsProfile,
    *,
    config: dimensions.Config | None = None,
    faixas: ranges.Faixas | None = None,
) -> Aderencia:
    """Calcula a aderência dos dois veículos ao perfil.

    Os dois mapas são campo canônico → valor, com `None` onde o campo é
    `nao_encontrado`/`nao_disponivel`/`nao_verificado` (é o que
    `pipeline/comparables.atributos_de_spec` produz).
    """
    cfg = config or dimensions.carregar()
    regua = faixas if faixas is not None else ranges.carregar()
    pesos = pesos_de(perfil, config=cfg)

    resultado = Aderencia(
        pesos=pesos,
        rotulo=cfg.rotulo_obrigatorio,
        versao_das_dimensoes=cfg.versao,
        versao_das_faixas=regua.versao,
    )

    for nome, dimensao in cfg.dimensoes.items():
        avaliada = DimensaoAvaliada(id=nome, rotulo=dimensao.rotulo, peso=pesos.get(nome, 0.0))

        notas_ford: list[NotaDeCampo] = []
        notas_conc: list[NotaDeCampo] = []
        for campo in dimensao.campos:
            nota_f, nota_c = notas_do_par(
                campo,
                atributos_ford.get(campo.campo),
                atributos_concorrente.get(campo.campo),
                faixas=regua,
            )

            # O coração da regra: falta de um lado tira o campo dos DOIS.
            if _sem_valor(nota_f) or _sem_valor(nota_c):
                qual = []
                if _sem_valor(nota_f):
                    qual.append("Ford")
                if _sem_valor(nota_c):
                    qual.append("concorrente")
                avaliada.campos_sem_dado.append(
                    {
                        "campo": campo.campo,
                        "motivo": f"sem valor verificado: {' e '.join(qual)}",
                    }
                )
                continue

            avaliada.campos_usados.append(campo.campo)
            notas_ford.append(nota_f)
            notas_conc.append(nota_c)

        avaliada.detalhe_ford = notas_ford
        avaliada.detalhe_concorrente = notas_conc

        if notas_ford:
            avaliada.nota_ford = round(sum(n.nota or 0 for n in notas_ford) / len(notas_ford), 2)
            avaliada.nota_concorrente = round(
                sum(n.nota or 0 for n in notas_conc) / len(notas_conc), 2
            )

        _marcar_piso_da_faixa(avaliada, regua)

        cobertura = avaliada.cobertura
        if cobertura is None or cobertura < cfg.cobertura_minima:
            avaliada.insuficiente = True
            # Sem underscore e sem asterisco: esta frase aparece na tela do **vendedor**,
            # no Showroom, e no documento do cliente. Saía com "dimensão **excluída do
            # total**" — asterisco de Markdown que a tela não interpreta — e com os nomes
            # de coluna do banco ("bloqueio_diferencial, pneus_tipo") (QA-BUG-13).
            faltando = (
                ", ".join(str(c["campo"]).replace("_", " ") for c in avaliada.campos_sem_dado)
                or "todos"
            )
            avaliada.aviso = (
                f"cobertura de {len(avaliada.campos_usados)} de "
                f"{len(avaliada.campos_usados) + len(avaliada.campos_sem_dado)} campos, abaixo do "
                f"mínimo de {cfg.cobertura_minima:.0%}: dimensão excluída do total. "
                f"Sem dado comparável em: {faltando}."
            )
            if avaliada.peso > 0:
                resultado.avisos.append(
                    f"{dimensao.rotulo} tinha peso {avaliada.peso:g}% e ficou fora do total "
                    f"por falta de dado comparável"
                )

        resultado.dimensoes.append(avaliada)

    # O total só soma as dimensões que entraram, e o denominador é o peso considerado — não
    # 100. Dividir por 100 diluiria a nota pelo peso das dimensões excluídas, transformando
    # falta de dado em nota baixa: é exatamente a penalização silenciosa que a regra proíbe.
    consideradas = [
        d
        for d in resultado.dimensoes
        if not d.insuficiente and d.peso > 0 and d.nota_ford is not None
    ]
    resultado.peso_considerado = round(sum(d.peso for d in consideradas), 4)

    if resultado.peso_considerado > 0:
        resultado.aderencia_ford = round(
            sum((d.nota_ford or 0) * d.peso for d in consideradas) / resultado.peso_considerado, 1
        )
        resultado.aderencia_concorrente = round(
            sum((d.nota_concorrente or 0) * d.peso for d in consideradas)
            / resultado.peso_considerado,
            1,
        )
        if resultado.peso_considerado < 100:
            resultado.avisos.append(
                f"a aderência foi calculada sobre {resultado.peso_considerado:g}% do peso do "
                "perfil; o resto ficou fora por falta de dado comparável"
            )
    else:
        resultado.avisos.append(
            "nenhuma dimensão com peso teve dado comparável suficiente: não há aderência a "
            "calcular, e um zero aqui seria invenção"
        )

    # `vence_em` inclui **só** dimensão com dado comparável. Uma dimensão insuficiente não
    # é vitória de ninguém, e listá-la daria ao vendedor um argumento sem base.
    for d in resultado.dimensoes:
        if d.insuficiente or d.nota_ford is None or d.nota_concorrente is None:
            continue
        if d.nota_ford > d.nota_concorrente:
            resultado.vence_em["ford"].append(d.id)
        elif d.nota_concorrente > d.nota_ford:
            resultado.vence_em["concorrente"].append(d.id)

    return resultado
