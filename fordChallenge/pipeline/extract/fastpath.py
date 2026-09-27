"""Fast-path por regex — extração sem LLM, com grounding automático.

`docs/12` §6.8 define a ideia: campos com unidade explícita saem por regex, e **o próprio
trecho casado é o `evidence_quote`**. Isso dá três coisas de graça: grounding automático
(o quote é, por construção, um pedaço do texto salvo), custo zero de LLM, e determinismo
total no CI. Campo resolvido aqui não vai ao modelo. A métrica é `fastpath_rate`.

Duas famílias de regra, porque as duas melhores fontes do projeto têm formas diferentes:

* **Inline** — a unidade está ao lado do número: `"Motor 3.0L V6 Bi-turbo de 397cv com
  583Nm"` (página da Ford). O regex casa o número junto da unidade.
* **Por rótulo de tabela** — a unidade está no **cabeçalho da linha**, não junto do
  valor: `"Torque (kgf.m/rpm)  42,8 / 3.400   50,9 / 2.800"` (ficha MY26 da Toyota, a
  única fonte do projeto que publica rpm). Aqui o regex inline não acha nada, porque não
  existe "kgfm" perto do "50,9".

**Regra de composição que não pode ser violada:** em documento multi-versão, o fast-path
por rótulo roda sobre as **células recortadas** pelo `version_slicer`, nunca sobre a
página inteira. Rodar na página inteira casaria `42,8` — o torque da **STD Power Pack
MT**, primeira coluna — e atribuiria à SRX Plus. Seria um valor errado *com quote válido*,
que é o pior defeito possível neste projeto: passa pelo grounding.

Três defeitos dos regexes de `docs/12` §6.8, corrigidos aqui e travados em teste:

1. `(\\d)\\s?(marchas|velocidades)` casa **um** dígito. Em "10 velocidades" ele casa
   `"0 velocidades"` e extrai `numero_marchas = 0` — errado, e com quote que **grounda**.
2. `R\\$\\s?[\\d\\.]+` é guloso e casou `"R$ 499.0002"` (engoliu o marcador de nota de
   rodapé), o que viraria R$ 4.990.002.
3. Nenhum dos regexes casa a ficha da Toyota, pelo motivo do parágrafo acima.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pipeline import units
from pipeline.ontology import (
    canonicalizar_lista,
    normalizar_rotulo,
    resolve_attribute,
    valor_conhecido,
)
from pipeline.schema import CONFIANCA_POR_TIER

#: `docs/05`: "cite ≤ 25 palavras exatamente como no texto".
MAX_PALAVRAS_QUOTE = 25


@dataclass
class Achado:
    """Um valor extraído por regex, com o trecho que o sustenta."""

    campo: str
    valor: Any
    valor_bruto: str
    quote: str
    unidade: str | None = None
    regra: str = ""
    inicio: int = 0
    fim: int = 0
    rotulo: str = ""
    notas: str = ""
    de_celula: bool = False
    """Veio de uma **celula recortada** da coluna da versao, nao do texto corrido.

    A distincao decide atribuicao: a linha `"Rodas   Aco estampado 17\" Liga leve 17\"
    Liga leve 18\""` de uma ficha percorre TODAS as versoes em colunas, entao o texto da
    linha nao e evidencia sobre uma versao especifica. A celula e.
    """

    def __post_init__(self) -> None:
        if not self.quote.strip():
            raise ValueError(f"achado de {self.campo} sem quote — valor sem evidência")


@dataclass(frozen=True)
class Regra:
    """Uma regra de fast-path: onde procurar, o que virar, e como se chama."""

    campo: str
    padrao: re.Pattern[str]
    conversor: Callable[[re.Match[str]], Any]
    nome: str
    unidade: str | None = None
    #: campos extras que o mesmo match preenche (ex.: rpm junto de potência)
    extras: tuple[tuple[str, str, str | None], ...] = ()
    """`(campo, grupo do regex, unidade)`."""


def _num(m: re.Match[str], grupo: str = "v") -> float:
    return units.parse_number_ptbr(m.group(grupo))


def _int(m: re.Match[str], grupo: str = "v") -> int:
    return round(_num(m, grupo))


def _garantia_meses(m: re.Match[str]) -> int:
    """Prazo de garantia rotulado, normalizado para meses."""
    valor = _int(m)
    unidade = (m.groupdict().get("unidade") or "meses").lower()
    return valor * 12 if unidade.startswith("ano") else valor


def _comprimento_rotulado(m: re.Match[str]) -> int:
    return units.to_mm(m.group("v"), m.groupdict().get("u") or "mm")


def _tanque_rotulado(m: re.Match[str]) -> float:
    return units.to_litros(m.group("v"), m.groupdict().get("u") or "l")


# ------------------------------------------------------------------ regras inline
REGRAS_INLINE: tuple[Regra, ...] = (
    # "250 cv @ 3.250rpm" e "600 Nm @ 1.750 rpm" — como a Ford escreve na ficha em HTML.
    #
    # Vêm ANTES das regras de valor solto, porque a primeira que casa ganha e estas duas
    # trazem o rpm de graça. Sem elas, `potencia_rpm` e `torque_rpm` da Ranger Limited
    # ficavam `nao_encontrado` com o número **na mesma frase** do valor que já estava
    # sendo lido — a regra por rótulo que tem o `extras` de rpm espera o formato
    # `"250/3250"` das tabelas de PDF, não o `"@"` das páginas.
    #
    # O separador aceita `@`, `a` e `em` ("250 cv a 3.250 rpm" é como a imprensa escreve).
    Regra(
        "potencia_cv",
        re.compile(
            r"(?P<v>\d{2,4})\s?(?:cv|CV)\b\s*(?:@|a|em)\s*(?P<rpm>[\d.]{3,6})\s?rpm",
            re.IGNORECASE,
        ),
        _int,
        "potencia_cv_com_rpm",
        "cv",
        extras=(("potencia_rpm", "rpm", "rpm"),),
    ),
    Regra(
        "torque_nm",
        re.compile(
            r"(?P<v>\d{3,4})\s?N\.?\s?m\b\s*(?:@|a|em)\s*(?P<rpm>[\d.]{3,6})\s?rpm",
            re.IGNORECASE,
        ),
        _int,
        "torque_nm_com_rpm",
        "Nm",
        extras=(("torque_rpm", "rpm", "rpm"),),
    ),
    Regra(
        "torque_nm",
        # DEFEITO CORRIGIDO: a regra em kgfm não tinha `extras` de rpm — perdia
        # `torque_rpm` mesmo quando a fonte publica os dois juntos (ex.: Webmotors,
        # "59,1 kgfm a 1400 rpm"), ao contrário do formato em Nm, que já tinha o par.
        # Precisa vir antes de `torque_kgfm_inline`: a primeira regra que casa ganha, e a
        # variante sem rpm casaria primeiro e nunca chegaria a tentar esta.
        re.compile(
            r"(?P<v>\d{1,3}(?:,\d)?)\s?(?:kgf?\.?\s?m|mkgf)\b\s*(?:@|a|em)\s*"
            r"(?P<rpm>[\d.]{3,6})\s?rpm",
            re.IGNORECASE,
        ),
        lambda m: units.to_nm(m.group("v"), "kgfm"),
        "torque_kgfm_com_rpm",
        "Nm",
        extras=(("torque_rpm", "rpm", "rpm"),),
    ),
    Regra(
        "potencia_cv",
        re.compile(r"(?P<v>\d{2,4})\s?(?:cv|CV)\b"),
        _int,
        "potencia_cv_inline",
        "cv",
    ),
    Regra(
        "potencia_cv",
        re.compile(r"(?P<v>\d{2,4})\s?hp\b", re.IGNORECASE),
        lambda m: units.to_cv(m.group("v"), "hp"),
        "potencia_hp_inline",
        "cv",
    ),
    Regra(
        "potencia_cv",
        re.compile(r"(?P<v>\d{2,4})\s?kW\b"),
        lambda m: units.to_cv(m.group("v"), "kw"),
        "potencia_kw_inline",
        "cv",
    ),
    Regra(
        "torque_nm",
        re.compile(r"(?P<v>\d{3,4})\s?N\.?\s?m\b", re.IGNORECASE),
        _int,
        "torque_nm_inline",
        "Nm",
    ),
    Regra(
        "torque_nm",
        # `docs/12` escreve `kgf?\.?m`; aqui aceita kgfm, kgf.m, kgf m, kgm e mkgf.
        re.compile(r"(?P<v>\d{1,3}(?:,\d)?)\s?(?:kgf?\.?\s?m|mkgf)\b", re.IGNORECASE),
        lambda m: units.to_nm(m.group("v"), "kgfm"),
        "torque_kgfm_inline",
        "Nm",
    ),
    Regra(
        "numero_marchas",
        # DEFEITO CORRIGIDO: `(\d)` casava "0 velocidades" em "10 velocidades".
        re.compile(r"\b(?P<v>\d{1,2})\s?(?:marchas|velocidades)\b", re.IGNORECASE),
        _int,
        "numero_marchas_inline",
    ),
    Regra(
        "pneus_medida",
        re.compile(r"(?P<v>\d{3}/\d{2}\s?R\d{2})", re.IGNORECASE),
        lambda m: units.parse_tire(m.group("v")).medida,
        "pneus_medida_inline",
    ),
    Regra(
        "preco_sugerido_brl",
        # DEFEITO CORRIGIDO: `[\d\.]+` guloso engolia o marcador de nota de rodapé,
        # transformando "R$ 499.000²" em R$ 4.990.002.
        re.compile(r"R\$\s?(?P<v>\d{1,3}(?:\.\d{3})+(?:,\d{2})?)(?!\d)"),
        lambda m: units.parse_price(m.group("v")),
        "preco_inline",
        "BRL",
    ),
    Regra(
        "aceleracao_0_100_s",
        # `s\b` sozinho não casa "5,8 segundos" (o `\b` cai entre "s" e "e"), e é assim
        # que a Ford escreve. Daí `s(?:egundos?|eg)?\b`.
        re.compile(
            r"0\s?(?:a|-|–|até|to)\s?100[^.\n]{0,60}?(?P<v>\d{1,2},\d)\s?s(?:egundos?|eg)?\b",
            re.IGNORECASE,
        ),
        _num,
        "aceleracao_inline",
        "s",
    ),
    Regra(
        "preco_sugerido_brl",
        # Caso real: a conversão HTML→markdown da página da Ford cola o marcador de nota
        # de rodapé no número e o texto salvo fica `"R$ 499.0002"`. Lido ao pé da letra
        # daria R$ 4.990.002, absurdo para uma picape. Esta regra só entra quando a
        # leitura direta é **implausível** e a leitura "número + marcador" é plausível, e
        # registra em `notas` que houve essa interpretação. O quote segue verbatim.
        re.compile(r"R\$\s?(?P<v>\d{1,3}(?:\.\d{3})+)(?P<nota>\d)(?!\d)"),
        lambda m: units.parse_price(m.group("v")),
        "preco_com_marcador_de_nota",
        "BRL",
    ),
    Regra(
        "velocidade_maxima_kmh",
        # ``100 km/h`` also appears in every 0-100 acceleration sentence. Accepting
        # any speed with a unit created a false maximum speed, backed by a valid quote.
        # Only an explicitly labelled maximum-speed value is unambiguous.
        re.compile(
            r"velocidade\s+m(?:a|\u00e1)xima\s*[:\-]?\s*(?P<v>\d{2,3})\s?km/h",
            re.IGNORECASE,
        ),
        _int,
        "velocidade_maxima_inline",
        "km/h",
    ),
    Regra(
        "airbags_qtd",
        re.compile(r"\b(?P<v>\d{1,2})\s?airbags?\b", re.IGNORECASE),
        _int,
        "airbags_inline",
    ),
    Regra(
        "rodas_aro_pol",
        re.compile(r"\baro\s?(?:de\s?)?(?P<v>1\d|2\d)\b", re.IGNORECASE),
        _int,
        "aro_inline",
        "pol",
    ),
    Regra(
        # A página da Ford escreve o aro junto do material, sem a palavra "aro":
        # "Rodas de liga leve 17”".
        "rodas_aro_pol",
        re.compile(
            r"rodas?\s+(?:de\s+)?(?:liga\s+leve|a[çc]o\s+estampado)\s+(?P<v>1\d|2\d)",
            re.IGNORECASE,
        ),
        _int,
        "aro_junto_do_material",
        "pol",
    ),
    Regra(
        # O aro também está na medida do pneu: 285/70 R17 -> 17. Mesma evidência, mesmo
        # trecho — é leitura do mesmo dado, não inferência de outra fonte.
        "rodas_aro_pol",
        re.compile(r"\d{3}/\d{2}\s?R(?P<v>\d{2})\b", re.IGNORECASE),
        _int,
        "aro_da_medida_do_pneu",
        "pol",
    ),
    Regra(
        "deslocamento_l",
        re.compile(r"\b(?P<v>\d,\d|\d\.\d)\s?(?:L\b|litros)", re.IGNORECASE),
        lambda m: round(units.parse_number_ptbr(m.group("v").replace(".", ",")), 2),
        "deslocamento_inline",
        "l",
    ),
    # A frase do PBEV/Inmetro, que é como o consumo **medido** aparece nas páginas das
    # montadoras: "percorre 9,7km/l na cidade e 10,6km/l na estrada".
    #
    # Duas regras e não uma com `extras`: o caminho de `extras` arredonda para inteiro
    # (é feito para rpm), e 10,6 km/l viraria 11. Um décimo de km/l numa comparação de
    # custo de uso vira dezenas de reais por mês.
    #
    # Quem recorta a frase da versão certa é `pipeline/connectors/pbe.py`: a mesma página
    # traz quatro dessas frases, uma por configuração, e ler a primeira daria o consumo do
    # vizinho com evidência que groundeia.
    Regra(
        "consumo_urbano_kml",
        re.compile(
            r"percorre\s+(?P<v>\d{1,2}(?:,\d)?)\s?km/l\s+na\s+cidade",
            re.IGNORECASE,
        ),
        _num,
        "consumo_urbano_pbev",
        "km/l",
    ),
    Regra(
        "consumo_rodoviario_kml",
        re.compile(
            r"(?P<v>\d{1,2}(?:,\d)?)\s?km/l\s+na\s+estrada",
            re.IGNORECASE,
        ),
        _num,
        "consumo_rodoviario_pbev",
        "km/l",
    ),
)


# ------------------------------------------------------- regras de enum e presença
#
# Campos cujo valor é uma **categoria** ou um **sim/não**, não um número com unidade.
# A ordem importa: a alternativa mais específica vem primeiro, porque "Matrix LED"
# também contém "LED" e "Full LED" também contém "LED".
@dataclass(frozen=True)
class RegraEnum:
    campo: str
    alternativas: tuple[tuple[Any, re.Pattern[str]], ...]
    """`(valor canônico, regex)`, da mais específica para a menos."""
    nome: str = ""


def _p(padrao: str) -> re.Pattern[str]:
    return re.compile(padrao, re.IGNORECASE)


REGRAS_ENUM: tuple[RegraEnum, ...] = (
    RegraEnum(
        "carroceria",
        (
            (
                "Picape",
                _p(
                    r"\bCada modo foi cuidadosamente calibrado para melhorar "
                    r"o desempenho da picape\b"
                ),
            ),
        ),
        # Descrição do próprio veículo. "Picapes" no menu ou /picapes/ no URL
        # não declara a carroceria do alvo; a identidade da página segue obrigatória.
        "carroceria_em_descricao_do_veiculo",
    ),
    RegraEnum(
        "freios_dianteiros",
        (("disco", _p(r"\bfreios? a disco nas 4 rodas\b")),),
        # Todas as quatro rodas inclui o eixo dianteiro. A frase não declara
        # ventilação e não substitui a especificação mais detalhada da traseira.
        "freios_dianteiros_disco_nas_quatro_rodas",
    ),
    RegraEnum(
        "farois_tipo",
        (
            # `\s*` e não `\s+` entre a qualidade e "led": a Ford escreve **"FullLed"**,
            # colado, na página da Ranger Limited. Com `\s+` o campo saía
            # `nao_encontrado` com "Faróis FullLed" na tela. Vale para as duas por
            # simetria — a próxima montadora que colar "MatrixLed" já está coberta.
            ("Matrix LED", _p(r"far[óo]is?\s+matrix\s*led|matrix\s*led")),
            ("Full LED", _p(r"far[óo]is?\s+full\s*led|full\s*led")),
            ("Bi-LED", _p(r"\bbi-?led\b")),
            ("LED", _p(r"far[óo]is?\s+(?:de\s+|em\s+)?led\b")),
            ("halógeno", _p(r"far[óo]is?\s+(?:de\s+|em\s+)?hal[óo]gen[oa]")),
        ),
        "farois_tipo_enum",
    ),
    RegraEnum(
        "farois_neblina",
        (
            ("LED", _p(r"far[óo]is?\s+de\s+neblina[^\n]{0,25}\bled\b")),
            ("halógeno", _p(r"far[óo]is?\s+de\s+neblina[^\n]{0,25}hal[óo]gen")),
        ),
        "farois_neblina_enum",
    ),
    RegraEnum(
        "paddle_shifters",
        (
            (
                True,
                _p(
                    r"paddle\s?shift(?:ers?)?|aletas?\s+(?:no|de)\s+volante|borboletas?\s+no\s+volante"
                ),
            ),
        ),
        "paddle_shifters_presenca",
    ),
    RegraEnum(
        "tipo",
        (
            (
                "automatica",
                _p(
                    r"c[âa]mbio\s+autom[áa]tic|transmiss[ãa]o\s+autom[áa]tic|autom[áa]tic[ao]\s+de\s+\d{1,2}\s+(?:marchas|velocidades)"
                ),
            ),
            ("automatizada", _p(r"\b(?:dct|automatizad[ao])\b")),
            ("cvt", _p(r"\bcvt\b")),
            (
                "manual",
                _p(r"c[âa]mbio\s+manual|transmiss[ãa]o\s+manual|manual\s+de\s+\d\s+velocidades"),
            ),
        ),
        "transmissao_tipo_enum",
    ),
    RegraEnum(
        "tipo_tracao",
        (
            (
                "4x4 permanente",
                _p(r"4motion|tra[çc][ãa]o\s+integral\s+permanente|4x4\s+permanente"),
            ),
            (
                # A ficha da Toyota escreve "4×2, 4×4 e 4×4 reduzida com acionamento
                # eletrônico": oferecer 4x2 **e** 4x4 com acionamento é, por definição,
                # tração sob demanda. É leitura da fonte, não inferência.
                "4x4 sob demanda",
                _p(
                    r"4x4\s+sob\s+demanda|4x4\s+seletor|part-?time\s+4x4"
                    r"|4[x×]2[^\n]{0,12}4[x×]4[^\n]{0,60}acionamento\s+eletr[ôo]nico"
                    r"|seletor\s+para\s+troca\s+de\s+tra[çc][ãa]o"
                ),
            ),
            ("4x4", _p(r"tra[çc][ãa]o[^\n]{0,20}(?:4wd|4x4|4×4)|\b4wd\b")),
            ("4x2", _p(r"tra[çc][ãa]o[^\n]{0,12}(?:4x2|4×2)")),
        ),
        "tipo_tracao_enum",
    ),
    RegraEnum(
        "pneus_tipo",
        (
            (
                "AT",
                _p(
                    r"\d{3}/\d{2}\s?R\d{2}[^\n]{0,30}\b(?:at|all[-\s]?terrain)\b|pneus?\s+all[-\s]?terrain"
                ),
            ),
            ("MT", _p(r"\d{3}/\d{2}\s?R\d{2}[^\n]{0,30}\b(?:mt|mud[-\s]?terrain)\b")),
        ),
        "pneus_tipo_enum",
    ),
    RegraEnum(
        "rodas_material",
        (
            ("liga leve", _p(r"rodas?\s+(?:de\s+)?liga\s+leve|liga\s+leve\s+\d{2}")),
            ("aço estampado", _p(r"a[çc]o\s+estampado")),
        ),
        "rodas_material_enum",
    ),
    # A **contagem** é o que se mede (`eval/compare.CAMPOS_DE_CONTAGEM`); o arranjo, que
    # vem colado em "V6", é bônus da grafia da fonte e não se exige.
    #
    # `"quatro cilindros"` está aqui por caso real: o registro de coleta da S10 diz
    # *"2.8 turbodiesel de quatro cilindros"* — a contagem estava na fonte, escrita por
    # extenso, e nenhuma das três alternativas anteriores a lia. O campo saía
    # `nao_encontrado` com a evidência na tela.
    RegraEnum(
        "cilindros",
        (
            ("V8", _p(r"\bv8\b|\b8\s+cilindros\s+em\s+v\b")),
            ("V6", _p(r"\bv6\b|\b6\s+cilindros\s+em\s+v\b")),
            ("4 em linha", _p(r"4\s+cilindros\s+em\s+linha|\bl4\b")),
            ("6", _p(r"\b(?:seis|6)\s+cilindros\b")),
            ("4", _p(r"\b(?:quatro|4)\s+cilindros\b")),
        ),
        "cilindros_enum",
    ),
    RegraEnum(
        "combustivel",
        (
            ("diesel", _p(r"\b(?:diesel|turbodiesel|turbo\s?diesel)\b")),
            ("flex", _p(r"\bflex\b")),
            ("gasolina", _p(r"\bgasolina\b")),
        ),
        "combustivel_enum",
    ),
    RegraEnum(
        "aspiracao",
        (
            ("biturbo", _p(r"\bbi-?\s?turbo\b|twin-?turbo")),
            ("turbo", _p(r"\bturbo(?:diesel|comprim\w+)?\b")),
            ("aspirado", _p(r"naturalmente\s+aspirado|\baspirado\b")),
        ),
        "aspiracao_enum",
    ),
    RegraEnum(
        "reduzida",
        (
            (
                True,
                _p(
                    r"(?:caixa\s+de\s+)?redu[çc][ãa]o\s+eletr[ôo]nica|4x4\s+reduzida|marcha\s+reduzida|\breduzida\b"
                ),
            ),
        ),
        "reduzida_presenca",
    ),
    RegraEnum(
        "bloqueio_diferencial",
        ((True, _p(r"bloqueio\s+d[oe]\s+diferencial|diferencial\s+blocante|e-?locker")),),
        "bloqueio_diferencial_presenca",
    ),
    RegraEnum(
        "camera_360",
        (
            (
                True,
                _p(
                    r"c[âa]mera\s+(?:de\s+)?360|vis[ãa]o\s+360|multi-?view\s+camera|surround\s+view"
                ),
            ),
        ),
        "camera_360_presenca",
    ),
)


def extrair_enums(
    texto: str, *, campos: set[str] | None = None, regras: tuple[RegraEnum, ...] = REGRAS_ENUM
) -> list[Achado]:
    """Categorias e presenças. A **primeira** alternativa que casa ganha o campo.

    Uma alternativa por campo, de propósito: `farois_tipo` não pode devolver
    `"Matrix LED"` **e** `"LED"` como se fossem dois valores em conflito, quando são o
    mesmo fato lido com dois graus de especificidade. A mais específica é a correta.
    """
    achados: list[Achado] = []
    for regra in regras:
        if campos and regra.campo not in campos:
            continue
        for valor, padrao in regra.alternativas:
            match = padrao.search(texto)
            if match is None:
                continue
            achados.append(
                Achado(
                    campo=regra.campo,
                    valor=valor,
                    valor_bruto=match.group(0),
                    quote=quote_da_janela(texto, match.start(), match.end()),
                    regra=regra.nome,
                    inicio=match.start(),
                    fim=match.end(),
                )
            )
            break
    return achados


#: "Assinatura em LED" é frase comum de marketing tanto para farol quanto para lanterna
#: traseira, sem nomear "farol"/"faróis" — as alternativas de `farois_tipo` em
#: `extrair_enums` exigem esse termo e por isso perdem a frase, mesmo com prova tier 1.
_ASSINATURA_LED = re.compile(r"assinatura\s+(?:em\s+)?led\b", re.IGNORECASE)
#: Alcance, em caracteres, para trás do "assinatura", onde procurar sinal de que a
#: assinatura é da lanterna traseira, não do farol.
_ALCANCE_ASSINATURA_LED = 60


def extrair_farol_por_assinatura(texto: str, *, campos: set[str] | None = None) -> list[Achado]:
    """ "Assinatura em LED" sem a palavra "farol": defeito real na página da S10.

    A frase descreve o frontal do veículo (ao lado de "frente robusta"/"capô elevado" na
    Chevrolet S10) sem nomear "farol", e a regra genérica de `farois_tipo` exige esse
    termo ao lado do LED. Aceita só quando não há "traseir"/"lanterna" nos
    :data:`_ALCANCE_ASSINATURA_LED` caracteres antes: a mesma frase também descreve
    lanterna traseira, e o schema não tem campo próprio para ela — publicar como farol
    seria inventar de qual lado do veículo a fonte falou.
    """
    if campos and "farois_tipo" not in campos:
        return []
    achados: list[Achado] = []
    for match in _ASSINATURA_LED.finditer(texto):
        antes = texto[max(0, match.start() - _ALCANCE_ASSINATURA_LED) : match.start()]
        if re.search(r"traseir|lanterna", antes, re.IGNORECASE):
            continue
        achados.append(
            Achado(
                campo="farois_tipo",
                valor="LED",
                valor_bruto=match.group(0),
                quote=quote_da_janela(texto, match.start(), match.end()),
                regra="farois_tipo_assinatura_led",
                inicio=match.start(),
                fim=match.end(),
            )
        )
    return achados


# ----------------------------------------------------- regra de texto livre rotulado
#: `rótulo → campo` para linhas de texto livre em página (não em tabela).
ROTULOS_EM_TEXTO: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        # Dois defeitos corrigidos aqui. (1) Sem `re.MULTILINE`, `^` e `$` valem para a
        # string inteira e nenhuma linha do meio do documento casa. (2) Com `\s+` depois
        # do rótulo, o regex atravessava a quebra de linha e casava
        # "Amortecedores⏎FOX Racing", devolvendo só "FOX Racing" — a página tem o rótulo
        # sozinho numa linha **e** a frase completa em outra. Com `[ \t]+`, casa a linha
        # que traz rótulo e valor juntos, que é a completa. (3) O `$` no fim exigia que a
        # linha acabasse em 160 caracteres, e a da Raptor tem 300 — sem `$`, o valor são
        # os primeiros 200 caracteres da linha, que seguem sendo trecho **contíguo** do
        # texto salvo e portanto groundáveis.
        "amortecedores",
        re.compile(r"^[ \t]*Amortecedores?[ \t]+(?P<v>[^\n]{4,200})", re.IGNORECASE | re.MULTILINE),
    ),
    (
        "motor_descricao",
        re.compile(r"^[ \t]*Motor[ \t]+(?P<v>\d[^\n]{4,120})$", re.IGNORECASE | re.MULTILINE),
    ),
    (
        "adas_nome_comercial",
        _p(r"\b(?P<v>Toyota\s+Safety\s+Sense|Safer\s+Tag|Co-?Pilot\s?360|IQ\.?Drive)\b"),
    ),
)


def extrair_rotulados(texto: str, *, campos: set[str] | None = None) -> list[Achado]:
    """Campos de texto livre que a página escreve como "Rótulo Valor" numa linha."""
    achados: list[Achado] = []
    for campo, padrao in ROTULOS_EM_TEXTO:
        if campos and campo not in campos:
            continue
        for match in padrao.finditer(texto):
            valor = match.group("v").strip(" .;•\t")
            if not valor:
                continue
            achados.append(
                Achado(
                    campo=campo,
                    valor=valor,
                    valor_bruto=match.group(0).strip(),
                    quote=quote_da_janela(texto, match.start(), match.end()),
                    regra=f"{campo}_rotulado",
                    inicio=match.start(),
                    fim=match.end(),
                )
            )
    return achados


# --------------------------------------------------- regras por rótulo de tabela
#
# `rotulo` é comparado por `normalizar_rotulo`, que remove acento, minúsculas e o que
# está entre parênteses — então "Potência (cv/rpm)" e "potencia" casam.
REGRAS_POR_ROTULO: tuple[Regra, ...] = (
    Regra(
        "potencia_cv",
        re.compile(r"^(?P<v>\d{2,4})\s?/\s?(?P<rpm>[\d.]+)$"),
        _int,
        "potencia_rotulo",
        "cv",
        extras=(("potencia_rpm", "rpm", "rpm"),),
    ),
    Regra(
        "torque_nm",
        re.compile(r"^(?P<v>\d{1,3}(?:,\d)?)\s?/\s?(?P<rpm>[\d.]+)$"),
        lambda m: units.to_nm(m.group("v"), "kgfm"),
        "torque_rotulo",
        "Nm",
        extras=(("torque_rpm", "rpm", "rpm"),),
    ),
    Regra(
        "deslocamento_l",
        re.compile(r"^(?P<v>\d{3,4})$"),
        lambda m: round(_num(m) / 1000, 1),
        "cilindrada_cm3_rotulo",
        "l",
    ),
    Regra(
        "capacidade_carga_kg",
        re.compile(r"^(?P<v>[\d.]{3,6})$"),
        _int,
        "capacidade_carga_rotulo",
        "kg",
    ),
    Regra(
        "capacidade_reboque_kg",
        re.compile(r"^(?P<v>[\d.]{3,6})$"),
        _int,
        "capacidade_reboque_rotulo",
        "kg",
    ),
    Regra(
        "garantia_meses",
        re.compile(r"^(?P<v>\d{1,3})(?:\s*(?P<unidade>mes(?:es)?|anos?))?$", re.IGNORECASE),
        _garantia_meses,
        "garantia_rotulo",
        "meses",
    ),
    Regra(
        "tanque_l",
        re.compile(r"^(?P<v>\d{2,3}(?:[.,]\d+)?)\s*(?P<u>l|litros?)?$", re.IGNORECASE),
        _tanque_rotulado,
        "tanque_rotulo",
        "l",
    ),
    *(
        regra
        for campo, nome in (
            ("comprimento_mm", "comprimento_rotulo"),
            ("largura_mm", "largura_rotulo"),
            ("altura_mm", "altura_rotulo"),
            ("entre_eixos_mm", "entre_eixos_rotulo"),
        )
        for regra in (
            Regra(
                campo,
                re.compile(
                    r"^(?P<v>\d+(?:[.,]\d+)?)\s*(?P<u>mm|cm|m|metros?)$",
                    re.IGNORECASE,
                ),
                _comprimento_rotulado,
                nome + "_com_unidade",
                "mm",
            ),
            # Unit supplied by the table label. Three-digit values are commonly cargo
            # box height (481 mm), not a vehicle dimension, and were already rejected.
            Regra(campo, re.compile(r"^(?P<v>[\d.]{4,6})$"), _int, nome, "mm"),
        )
    ),
    Regra(
        "consumo_urbano_kml",
        re.compile(r"^(?P<v>\d{1,2}(?:[.,]\d+)?)\s*km/l$", re.IGNORECASE),
        _num,
        "consumo_urbano_rotulo",
        "km/l",
    ),
    Regra(
        "consumo_rodoviario_kml",
        re.compile(r"^(?P<v>\d{1,2}(?:[.,]\d+)?)\s*km/l$", re.IGNORECASE),
        _num,
        "consumo_rodoviario_rotulo",
        "km/l",
    ),
    # O aro sai da própria medida, e por célula — não só no texto corrido.
    #
    # A regra inline `aro_da_medida_do_pneu` já deriva 18 de "265/60 R18", mas ela lê a
    # **linha** da ficha, que na Hilux é `Pneus  265/65 R17  265/65 R17  265/60 R18` —
    # uma linha, três versões. O resultado medido: `pneus_medida` vinha certo da coluna
    # (265/60 R18) e `rodas_aro_pol` vinha 17 do texto, porque nenhuma célula respondia
    # o aro e o 17 ganhava por aparecer mais vezes. Derivar o aro da célula põe os dois
    # campos na mesma coluna, que é de onde os dois vêm na fonte.
    Regra(
        "pneus_medida",
        re.compile(r"^(?P<v>\d{3}/\d{2}\s?R(?P<aro>\d{2}))$", re.IGNORECASE),
        lambda m: units.parse_tire(m.group("v")).medida,
        "pneus_rotulo",
        extras=(("rodas_aro_pol", "aro", "pol"),),
    ),
)

#: Rótulo de tabela (normalizado) → campo canônico. É o que liga a linha da ficha ao
#: schema; sem isso o valor `"5.325"` não diz se é comprimento da picape ou da caçamba.
ROTULO_PARA_CAMPO: dict[str, str] = {
    "potencia": "potencia_cv",
    "torque": "torque_nm",
    "cilindrada": "deslocamento_l",
    "capacidade de carga": "capacidade_carga_kg",
    "capacidade do tanque": "tanque_l",
    "entre eixos": "entre_eixos_mm",
    "entre-eixos": "entre_eixos_mm",
    "pneus": "pneus_medida",
    "rodas": "rodas_material",
    "transmissao": "tipo",
    "direcao": "direcao",
    "dianteira": "suspensao_dianteira",
    "traseira": "suspensao_traseira",
    "dianteiros": "freios_dianteiros",
    "traseiros": "freios_traseiros",
    "motor": "motor_descricao",
    "farois": "farois_tipo",
    "tracao": "tipo_tracao",
    "comprimento": "comprimento_mm",
    "largura": "largura_mm",
    "altura": "altura_mm",
    "largura sem espelho retrovisor": "largura_mm",
    # Como a Ford escreve na ficha em HTML da página da versão. O typo
    # "combistível" é da fonte, não nosso: o mapa registra o que está publicado.
    "comprimento do veiculo": "comprimento_mm",
    "largura do veiculo com espelhos": "largura_mm",
    "largura do veiculo": "largura_mm",
    "altura do veiculo": "altura_mm",
    "distancia entre eixos": "entre_eixos_mm",
    "tanque de combustivel": "tanque_l",
    "tanque de combistivel": "tanque_l",
    "consumo urbano": "consumo_urbano_kml",
    "consumo rodoviario": "consumo_rodoviario_kml",
    "suspensao dianteira": "suspensao_dianteira",
    "suspensao traseira": "suspensao_traseira",
    "freios dianteiros": "freios_dianteiros",
    "freios traseiros": "freios_traseiros",
}

#: Campo extra que a **mesma célula** de tabela também responde, além do campo principal
#: do rótulo — sem isso, o valor fica preso ao campo que o rótulo nomeia, mesmo estando,
#: verbatim, na célula de outro campo canônico.
#:
#: `tipo` → `numero_marchas`: a célula de "Transmissão" ("Automática de 6 velocidades
#: sequencial") preenche o tipo de câmbio, mas o número de marchas mora na mesma frase.
#: `suspensao_dianteira` → `amortecedores`: decisão do dono — quando a fonte não descreve
#: o amortecedor em si, a descrição da suspensão vale como resposta. **Só a dianteira**,
#: de propósito: mapear as duas faria `amortecedores` "divergir" entre a descrição
#: dianteira e a traseira sempre que elas diferem (o caso comum — eixo rígido atrás,
#: independente na frente) — não são fontes discordando, é o mesmo código produzindo
#: dois valores para um campo que só existe uma vez na ficha.
CAMPO_EXTRA_DA_CELULA: dict[str, str] = {
    "tipo": "numero_marchas",
    "suspensao_dianteira": "amortecedores",
}

#: Campos cujo valor é texto livre: o valor da célula vale como está, sem regex.
CAMPOS_DE_TEXTO: frozenset[str] = frozenset(
    {
        "motor_descricao",
        "suspensao_dianteira",
        "suspensao_traseira",
        "freios_dianteiros",
        "freios_traseiros",
        "direcao",
        "amortecedores",
        "rodas_material",
        "farois_tipo",
        "tipo_tracao",
        "tipo",
        "carroceria",
        "combustivel",
    }
)


# ---------------------------------------------------------------------------- quote
def quote_da_janela(
    texto: str, inicio: int, fim: int, *, max_palavras: int = MAX_PALAVRAS_QUOTE
) -> str:
    """Trecho verbatim ao redor do match: a linha, cortada em fronteira de palavra.

    O resultado é sempre um **pedaço contíguo** do texto original, então o grounding
    exato passa por construção. O corte é por palavras inteiras a partir do match, para
    caber no limite de `docs/05` sem partir palavra no meio.
    """
    inicio_linha = texto.rfind("\n", 0, inicio) + 1
    fim_linha = texto.find("\n", fim)
    if fim_linha == -1:
        fim_linha = len(texto)
    linha = texto[inicio_linha:fim_linha]
    if not linha.strip():
        return texto[inicio:fim].strip()

    palavras = linha.split()
    if len(palavras) <= max_palavras:
        return linha.strip()

    # janela centrada no match, em palavras, mantendo contiguidade
    deslocamento = inicio - inicio_linha
    antes = len(linha[:deslocamento].split())
    metade = max_palavras // 2
    comeco = max(0, antes - metade)
    trecho = " ".join(palavras[comeco : comeco + max_palavras])
    # garante que o resultado ainda é substring literal
    achado = linha.find(trecho)
    if achado == -1:
        return " ".join(palavras[:max_palavras])
    return trecho


# ------------------------------------------------------------------ extração inline
def extrair_de_texto(
    texto: str, *, campos: set[str] | None = None, regras: tuple[Regra, ...] = REGRAS_INLINE
) -> list[Achado]:
    """Aplica as regras inline sobre texto livre.

    Devolve **todos** os achados, inclusive repetições e valores divergentes do mesmo
    campo: escolher entre eles é papel da reconciliação (WP-12), que precisa ver todos
    para poder marcar `divergente`. Filtrar aqui esconderia divergência.
    """
    achados: list[Achado] = []
    for regra in regras:
        if campos and regra.campo not in campos:
            continue
        for match in regra.padrao.finditer(texto):
            try:
                valor = regra.conversor(match)
            except (ValueError, KeyError):
                continue
            achados.append(
                Achado(
                    campo=regra.campo,
                    valor=valor,
                    valor_bruto=match.group(0),
                    quote=quote_da_janela(texto, match.start(), match.end()),
                    unidade=regra.unidade,
                    regra=regra.nome,
                    inicio=match.start(),
                    fim=match.end(),
                )
            )
            for campo_extra, grupo, unidade in regra.extras:
                if campos and campo_extra not in campos:
                    continue
                try:
                    valor_extra = round(units.parse_number_ptbr(match.group(grupo)))
                except (ValueError, IndexError):
                    continue
                achados.append(
                    Achado(
                        campo=campo_extra,
                        valor=valor_extra,
                        valor_bruto=match.group(grupo),
                        quote=quote_da_janela(texto, match.start(), match.end()),
                        unidade=unidade,
                        regra=regra.nome + ":extra",
                        inicio=match.start(),
                        fim=match.end(),
                    )
                )
    return _com_notas_de_marcador(achados)


# ------------------------------------------------------- extração por rótulo de célula
def campo_do_rotulo(rotulo: str) -> str | None:
    """Rótulo de tabela → campo canônico; o mapa manual sempre tem prioridade."""
    chave = normalizar_rotulo(rotulo)
    if chave in ROTULO_PARA_CAMPO:
        return ROTULO_PARA_CAMPO[chave]
    for conhecido, campo in ROTULO_PARA_CAMPO.items():
        if chave.startswith(conhecido):
            return campo
    # A ontologia já conhece centenas de formas reais ("prazo de garantia",
    # "capacidade de reboque", ...). Repeti-las no mapa curto faria nascer uma segunda
    # fonte de verdade. Ela só entra depois do mapa manual: os rótulos de tabela que
    # exigem uma decisão específica continuam ganhando mesmo se o fuzzy discordar.
    resolvido, _score = resolve_attribute(chave)
    return resolvido


def quote_de_celula(valor: str, texto: str = "") -> str:
    """Quote **contíguo** para um valor de célula, encurtando até caber no texto salvo.

    Célula de tabela pode quebrar em várias linhas, e o valor reconstruído pela grade
    (`"Eixo rígido, molas semielípticas de duplo estágio e barra estabilizadora"`) não é
    substring literal do texto com layout — as linhas de colunas vizinhas ficam entre os
    fragmentos. Sem tratar isso, um valor **correto** era rejeitado pelo grounding.

    A solução mantém a regra intacta em vez de afrouxá-la: o quote passa a ser o maior
    **prefixo contíguo** do valor que de fato ocorre no texto (aqui, 7 das 11 palavras).
    O valor segue completo; só a citação encurta, e continua sendo trecho verbatim.
    """
    from pipeline.eval.compare import normalize_grounding

    if not texto:
        return valor
    normalizado = normalize_grounding(texto)
    if normalize_grounding(valor) in normalizado:
        return valor
    palavras = valor.split()
    for k in range(len(palavras) - 1, 2, -1):
        fragmento = " ".join(palavras[:k])
        if normalize_grounding(fragmento) in normalizado:
            return fragmento
    return valor


def extrair_de_celulas(celulas, *, campos: set[str] | None = None, texto: str = "") -> list[Achado]:
    """Aplica as regras por rótulo sobre células **já recortadas** da versão alvo.

    Exige células recortadas: ver a regra de composição no topo do módulo. O `quote` é o
    valor da célula **verbatim**, que é substring literal do `doc.md` — a concatenação
    "rótulo: valor" não seria, e o grounding falharia.
    """
    achados: list[Achado] = []
    por_campo = {}
    for regra in REGRAS_POR_ROTULO:
        por_campo.setdefault(regra.campo, []).append(regra)

    for celula in celulas:
        campo = campo_do_rotulo(celula.rotulo)
        # `CAMPO_EXTRA_DA_CELULA`: a mesma célula também responde por um segundo campo
        # canônico (ex.: "Transmissão" responde `tipo` **e** `numero_marchas`). Sem checar
        # isso antes do filtro de `campos`, uma consulta só por `numero_marchas` descartava
        # a célula na primeira linha, porque o campo *principal* do rótulo é `tipo`.
        campo_secundario = CAMPO_EXTRA_DA_CELULA.get(campo) if campo else None
        quer_principal = campo is not None and (not campos or campo in campos)
        quer_secundario = campo_secundario is not None and (
            not campos or campo_secundario in campos
        )
        if not quer_principal and not quer_secundario:
            continue
        valor_bruto = str(celula.valor).strip()
        if not valor_bruto or valor_bruto in {"-", "–", "—", "•"}:
            continue

        if quer_principal:
            if campo in CAMPOS_DE_TEXTO:
                achados.append(
                    Achado(
                        campo=campo,
                        valor=valor_bruto,
                        valor_bruto=valor_bruto,
                        quote=quote_de_celula(valor_bruto, texto),
                        regra="rotulo_texto_livre",
                        de_celula=True,
                        rotulo=celula.rotulo,
                        notas=f"linha «{celula.rotulo}» da tabela, página {celula.pagina}",
                    )
                )
            else:
                for regra in por_campo.get(campo, []):
                    match = regra.padrao.match(valor_bruto)
                    if not match:
                        continue
                    try:
                        valor = regra.conversor(match)
                    except (ValueError, KeyError):
                        continue
                    achados.append(
                        Achado(
                            campo=campo,
                            valor=valor,
                            valor_bruto=valor_bruto,
                            quote=quote_de_celula(valor_bruto, texto),
                            unidade=regra.unidade,
                            regra=regra.nome,
                            de_celula=True,
                            rotulo=celula.rotulo,
                            notas=f"linha «{celula.rotulo}» da tabela, página {celula.pagina}",
                        )
                    )
                    for campo_extra, grupo, unidade in regra.extras:
                        if campos and campo_extra not in campos:
                            continue
                        try:
                            valor_extra = round(units.parse_number_ptbr(match.group(grupo)))
                        except (ValueError, IndexError):
                            continue
                        achados.append(
                            Achado(
                                campo=campo_extra,
                                valor=valor_extra,
                                valor_bruto=valor_bruto,
                                quote=quote_de_celula(valor_bruto, texto),
                                unidade=unidade,
                                regra=regra.nome + ":extra",
                                # O derivado vem da **mesma célula** que o principal, e por
                                # isso herda a marca. Sem ela, `reconcile.preferir_celulas`
                                # não sabia que a coluna da versão já havia respondido
                                # este campo, e o valor lido do texto corrido da linha
                                # (que percorre todas as versões) competia de igual para
                                # igual com ele.
                                de_celula=True,
                                rotulo=celula.rotulo,
                                notas=f"linha «{celula.rotulo}» da tabela, página {celula.pagina}",
                            )
                        )
                    break

        if quer_secundario and campo_secundario == "numero_marchas":
            for extra in extrair_de_texto(valor_bruto, campos={"numero_marchas"}):
                achados.append(
                    Achado(
                        campo="numero_marchas",
                        valor=extra.valor,
                        valor_bruto=valor_bruto,
                        quote=quote_de_celula(valor_bruto, texto),
                        unidade=extra.unidade,
                        regra=f"{extra.regra}:celula_de_{campo}",
                        de_celula=True,
                        rotulo=celula.rotulo,
                        notas=f"marchas extraídas da célula «{celula.rotulo}» ({valor_bruto!r})",
                    )
                )
        elif quer_secundario and campo_secundario == "amortecedores":
            achados.append(
                Achado(
                    campo="amortecedores",
                    valor=valor_bruto,
                    valor_bruto=valor_bruto,
                    quote=quote_de_celula(valor_bruto, texto),
                    regra="amortecedor_via_suspensao",
                    de_celula=True,
                    rotulo=celula.rotulo,
                    notas=(
                        f"descrição da suspensão («{celula.rotulo}»), sem amortecedor "
                        "específico na fonte"
                    ),
                )
            )
    return achados


# ------------------------------------------------------------------ listas de modos
#: Modos vêm em enumeração, não em número com unidade — daí regra própria.
#:
#: O separador antes da lista (`–`, `—`, `-` ou `:`) é **obrigatório** e o preenchimento
#: antes dele é **não guloso**. Com `[^\n]{0,20}` guloso, o regex comia 20 caracteres de
#: " selecionáveis – Nor" e a lista começava em `"mal, Esportivo, ..."`: o primeiro modo
#: virava `mal`. Defeito real, travado em teste.
def _padrao_de_modos(nucleo: str) -> re.Pattern[str]:
    # O separador é opcional porque a Toyota escreve "Modos de seleção de condução Eco e
    # Power", sem travessão nem dois-pontos. Para não sair capturando a página inteira, a
    # lista capturada é **cortada** em `_corta_lista` no primeiro marcador de tabela.
    return re.compile(
        r"modos?\s+d[eo]\s+(?:sele[çc][ãa]o\s+d[eo]\s+)?(?:"
        + nucleo
        + r")\b[^\n]{0,40}?[–—\-:]?\s*(?P<lista>[^\n]{5,220})",
        re.IGNORECASE,
    )


PADROES_DE_MODOS: dict[str, re.Pattern[str]] = {
    "modos_conducao": _padrao_de_modos(r"condu[çc][ãa]o|dire[çc][ãa]o\s+do\s+ve[íi]culo|terreno"),
    "modos_direcao": _padrao_de_modos(r"dire[çc][ãa]o|volante|ester[çc]o"),
    "modos_escapamento": _padrao_de_modos(r"escapamento|escape"),
    "modos_amortecedor": _padrao_de_modos(r"amortecedor|suspens[ãa]o"),
}

#: Onde a lista acaba num texto com layout de tabela preservado: no primeiro bullet ou
#: na primeira coluna seguinte (duas ou mais casas de espaço).
_FIM_DA_LISTA = re.compile(r"\s{2,}|•")


def _corta_lista(bruto: str) -> str:
    """Corta a lista no começo da próxima coluna da tabela.

    Sem isso, "Modos de seleção de condução Eco e Power - •  •  •  •" produziria o token
    `"power_-_•_•_•_•"`. O corte mantém o trecho **contíguo**, então o quote segue
    groundável.
    """
    return _FIM_DA_LISTA.split(bruto.strip(), maxsplit=1)[0].strip(" .:-–—")


#: Um nome de modo é curto: "Normal", "Escorregadio", "Lama/Terra", "Rebocar/Transp",
#: "Rock Crawl", "Off-Road". Três palavras é o teto observado nas quatro montadoras.
MAX_PALAVRAS_DO_MODO = 3
#: E não passa de 28 caracteres. "Rebocar/Transp" tem 14; "Rock Crawl", 10.
MAX_CHARS_DO_MODO = 28
#: Quantos tokens da lista têm de ser modo **conhecido** para a lista valer. Dois: um
#: único acerto acontece por acaso dentro de qualquer parágrafo sobre modos.
MINIMO_DE_MODOS_CONHECIDOS = 2


def parece_nome_de_modo(token: str) -> bool:
    """O token pode ser o **nome** de um modo, e não uma frase sobre modos?

    O defeito que isto corrige, medido na página da Ranger Limited: a página escreve
    "6 modos de condução" e, na mesma linha, o parágrafo explicativo — *"Cada modo foi
    cuidadosamente calibrado para melhorar o desempenho da picape em qualquer terreno.
    Esses modos ajustam todos os parametros, desde a troca de marchas…"*. A regra de
    lista casava o rótulo e engolia o parágrafo, e a vírgula transformava a explicação
    numa lista de sete "modos": `["cada_modo_foi_cuidadosamente_calibrado_…",
    "desde_a_troca_de_marchas", "resposta_do_acelerador", …]`.

    Isso não ficava só feio: virava **divergência** contra a lista verdadeira, que a
    mesma página traz seis linhas abaixo. Divergência inventada gasta a confiança no
    mecanismo que existe para mostrar discordância real.
    """
    limpo = token.strip()
    return len(limpo) <= MAX_CHARS_DO_MODO and len(limpo.split()) <= MAX_PALAVRAS_DO_MODO


#: `/` **não** separa: "Lama/Terra" é **um** modo, e a ontologia já o resolve para `lama`
#: (`resolve_value`). Tratá-lo como dois tokens acrescentaria um `terra` inexistente e
#: faria a lista da Raptor ter 8 itens onde o gabarito tem 7.
_SEPARADOR = re.compile(r"\s*(?:,|;|\be\b|\+)\s*", re.IGNORECASE)

#: Vocabulário que identifica uma enumeração de itens de ADAS.
_VOCABULARIO_ADAS = (
    "alerta",
    "frenagem",
    "assistente",
    "permanencia",
    "permanência",
    "acc",
    "piloto automatico",
    "piloto automático",
    "camera",
    "câmera",
    "blis",
    "ponto cego",
    "trafego cruzado",
    "tráfego cruzado",
    "colisao",
    "colisão",
    "farol alto",
    "sensores",
    "pro trailer",
)

#: Enumeração separada por ponto-e-vírgula, com pelo menos três segmentos.
_LISTA_ADAS = re.compile(r"(?P<lista>[^\n;]{8,120}(?:;\s*[^\n;]{4,120}){2,20})")

#: Resíduo de JSON no começo de um item: `"valor_bruto": "Alerta de colisão`.
#: Os snapshots do tipo `registro_de_evidencia` são JSON, e a enumeração vive dentro de
#: um campo de string — limpar a sintaxe é higiene de parsing, não reescrita de conteúdo.
_PREFIXO_JSON = re.compile(r'^\s*"?[\w_]+"?\s*:\s*"?')


def _limpa_item_de_lista(bruto: str) -> str:
    return _PREFIXO_JSON.sub("", bruto).strip(" .;:•\t\"'")


#: Quantos itens de assistência reconhecidos uma lista precisa ter para ser uma lista
#: de ADAS. Três: um ou dois itens aparecem soltos em qualquer página de equipamento.
MINIMO_DE_ITENS_ADAS = 3


def _e_item_de_adas(item: str) -> bool:
    """O item é uma **função de assistência** que o vocabulário reconhece?

    O critério é o mesmo da régua (`docs/09` v1.1: conjuntos normalizados por
    sinônimos), e é o que separa ADAS de conforto numa lista de equipamento. Sem ele, a
    página da S10 entregava `["frenagem automática de emergência", "• alerta de ponto
    cego", "• easy entry (sensor de aproximação pela chave)", "• ar condicionado
    digital", "• carregador por indução", "encontre sua s10"]` — seis "itens de ADAS",
    três dos quais não são ADAS e um é uma chamada para ação.

    Item que a montadora nomeia de forma que o vocabulário ainda não conhece fica de
    fora. É a escolha conservadora certa aqui: a lista de ADAS vai para o argumentário do
    vendedor, e "a Ford tem X" precisa ser sobre uma função, não sobre uma frase.
    """
    return valor_conhecido("adas_itens", item)


def extrair_adas(texto: str, *, campos: set[str] | None = None) -> list[Achado]:
    """Itens de ADAS, em duas formas: enumeração com `;` e **lista em linhas**.

    Sai numa regra própria porque não é número com unidade nem categoria fechada: é uma
    lista de **funções**. Os itens ficam como a fonte escreveu; a comparação com o
    gabarito é por função (`pipeline/eval/compare.py`), com similaridade só onde o
    vocabulário não tem opinião.

    A forma em linhas existe por caso real: a página da Ranger Limited lista os itens de
    segurança um por linha, sem separador nenhum, e o campo ficava `nao_encontrado` com
    a seção SEGURANÇA inteira na tela.
    """
    if campos and "adas_itens" not in campos:
        return []
    achados: list[Achado] = []

    for match in _LISTA_ADAS.finditer(texto):
        bruto = match.group("lista")
        baixa = bruto.lower()
        if sum(1 for v in _VOCABULARIO_ADAS if v in baixa) < MINIMO_DE_ITENS_ADAS:
            continue
        itens = [_limpa_item_de_lista(p) for p in bruto.split(";")]
        itens = [i for i in itens if len(i) > 3 and _e_item_de_adas(i)]
        if len(itens) < MINIMO_DE_ITENS_ADAS:
            continue
        achados.append(
            Achado(
                campo="adas_itens",
                valor=itens,
                valor_bruto=bruto.strip(),
                quote=quote_da_janela(texto, match.start(), match.end()),
                regra="adas_itens_enumeracao",
            )
        )

    achados += _adas_em_linhas(texto)
    # a lista mais longa é a mais completa; as demais são recortes dela
    achados.sort(key=lambda a: -len(a.valor))
    return achados[:1]


def _adas_em_linhas(texto: str) -> list[Achado]:
    """Itens de ADAS escritos **um por linha**, como nas seções de equipamento.

    A citação é o **trecho contíguo** que vai da primeira à última linha do bloco — não
    a concatenação dos itens, que não seria substring do texto salvo e reprovaria no
    grounding. Linha que não é ADAS interrompe o bloco: dois blocos separados por
    "INTERIOR" são duas listas, e a maior ganha.
    """
    linhas = texto.splitlines(keepends=True)
    inicios: list[int] = []
    posicao = 0
    for linha in linhas:
        inicios.append(posicao)
        posicao += len(linha)

    achados: list[Achado] = []
    bloco: list[int] = []

    def fecha() -> None:
        if len(bloco) < MINIMO_DE_ITENS_ADAS:
            bloco.clear()
            return
        primeiro, ultimo = bloco[0], bloco[-1]
        trecho = texto[inicios[primeiro] : inicios[ultimo] + len(linhas[ultimo])].strip()
        achados.append(
            Achado(
                campo="adas_itens",
                valor=[_limpa_item_de_lista(linhas[i]) for i in bloco],
                valor_bruto=trecho,
                quote=trecho,
                regra="adas_itens_em_linhas",
            )
        )
        bloco.clear()

    for i, linha in enumerate(linhas):
        item = _limpa_item_de_lista(linha)
        if item and len(item) > 3 and _e_item_de_adas(item):
            bloco.append(i)
        elif linha.strip():
            # Linha com conteúdo que não é ADAS fecha o bloco; linha vazia não, porque
            # `page.md` separa cada item por linha vazia.
            fecha()
    fecha()
    return achados


# ------------------------------------------------- aceleração por proximidade
#: A âncora: como as fontes brasileiras nomeiam a medida.
_ANCORA_0_100 = re.compile(r"0\s*(?:a|-|–|—|até|to)\s*100(?:\s*km/h)?", re.IGNORECASE)
#: Um valor em segundos. `s\b` sozinho não casa "5,8 segundos" (o `\b` cai entre "s" e
#: "e"), e é assim que a Ford escreve — daí `s(?:egundos?|eg)?\b`.
_VALOR_EM_SEGUNDOS = re.compile(
    r"(?<![\d,.])(?P<v>\d{1,2},\d)\s?s(?:egundos?|eg)?\b", re.IGNORECASE
)
#: Alcance da proximidade, em caracteres, para cada lado da âncora.
ALCANCE_DA_ACELERACAO = 300
#: Faixa plausível de 0–100 km/h para uma picape. Fora dela o número não é aceleração:
#: 2,5 s não existe no segmento e 40 s seria outra medida.
FAIXA_DE_ACELERACAO = (3.0, 30.0)


def extrair_aceleracao_por_proximidade(
    texto: str, *, campos: set[str] | None = None
) -> list[Achado]:
    """Valor em segundos **perto** de uma menção a "0 a 100", com o trecho do valor.

    Por que a regra inline não bastava, e o caso é a cena 4 da demonstração. O registro
    de coleta da Raptor traz os **dois** valores, um em cada entrada:

        "trecho": "A Ford declara que a Ranger Raptor vai de 0 a 100 km/h em 5,8 segundos"
        "trecho": "No teste da Autoesporte, a picape cumpriu a marca em 6,5 s"

    A regra `aceleracao_inline` exige "0 a 100" e o valor na **mesma** frase, e por isso
    lia o 5,8 e não lia o 6,5 — a segunda frase diz "a marca", que é o 0–100 nomeado
    antes. Resultado: a divergência 5,8 × 6,5, que é o exemplo mais didático do produto,
    simplesmente não aparecia, e o `ONBOARDING.md` registrava "não sai desta base".

    A regra: valor em segundos a até :data:`ALCANCE_DA_ACELERACAO` caracteres de uma
    âncora `0 a 100`, **sem quebra de parágrafo no meio** (linha vazia encerra o
    assunto). Medido no registro da Raptor: o 6,5 mais próximo está a **162**
    caracteres da âncora; o seguinte, a 459, fica de fora.

    **O grounding não é afrouxado em nada.** A citação é `quote_da_janela` em volta do
    **valor** — um pedaço contíguo do texto salvo, como qualquer outra citação do
    projeto. O que muda é o que a regra aceita ler, não o que ela precisa provar.
    """
    if campos and "aceleracao_0_100_s" not in campos:
        return []
    ancoras = [(m.start(), m.end()) for m in _ANCORA_0_100.finditer(texto)]
    if not ancoras:
        return []

    achados: list[Achado] = []
    vistos: set[tuple[float, int]] = set()
    for match in _VALOR_EM_SEGUNDOS.finditer(texto):
        try:
            valor = units.parse_number_ptbr(match.group("v"))
        except ValueError:
            continue
        if not FAIXA_DE_ACELERACAO[0] <= valor <= FAIXA_DE_ACELERACAO[1]:
            continue
        for inicio, fim in ancoras:
            if match.start() >= fim:
                distancia, entre = match.start() - fim, texto[fim : match.start()]
            elif match.end() <= inicio:
                distancia, entre = inicio - match.end(), texto[match.end() : inicio]
            else:  # pragma: no cover - âncora e valor sobrepostos
                distancia, entre = 0, ""
            if distancia > ALCANCE_DA_ACELERACAO or _QUEBRA_DE_PARAGRAFO.search(entre):
                continue
            chave = (valor, match.start())
            if chave in vistos:
                break
            vistos.add(chave)
            achados.append(
                Achado(
                    campo="aceleracao_0_100_s",
                    valor=valor,
                    valor_bruto=match.group(0).strip(),
                    quote=quote_da_janela(texto, match.start(), match.end()),
                    unidade="s",
                    regra="aceleracao_por_proximidade",
                    inicio=match.start(),
                    fim=match.end(),
                    notas=f'a {distancia} caracteres de "{texto[inicio:fim].strip()}"',
                )
            )
            break
    return _melhor_quote_por_valor(achados)


# --------------------------------------------------- potência sem cv (imagem na fonte)
#: Ancorado no rótulo, não solto: rodar em `REGRAS_INLINE` casaria o rpm do torque, que
#: aparece antes na mesma ficha ("kgfm a NNNN rpm"). `[^\n]*?` é preguiçoso e para na
#: primeira ocorrência de "a <dígitos> rpm" na mesma linha — o caso real é o CarrosNaWeb,
#: que renderiza o valor em cv como imagem (`campoImagem/imgValorN.asp`) e só o rpm é
#: texto: "Potência máxima [imagem] cv a 6250 rpm".
_POTENCIA_RPM_SEM_CV = re.compile(
    r"Pot[êe]ncia m[áa]xima[^\n]*?\ba\s*(?P<rpm>[\d.]{3,6})\s*rpm", re.IGNORECASE
)


def extrair_potencia_rpm_sem_cv(texto: str, *, campos: set[str] | None = None) -> list[Achado]:
    """`potencia_rpm` quando o cv da mesma ficha é imagem, não texto. Nunca infere cv."""
    if campos and "potencia_rpm" not in campos:
        return []
    achados: list[Achado] = []
    for match in _POTENCIA_RPM_SEM_CV.finditer(texto):
        achados.append(
            Achado(
                campo="potencia_rpm",
                valor=round(float(match.group("rpm").replace(".", ""))),
                valor_bruto=match.group("rpm"),
                quote=quote_da_janela(texto, match.start(), match.end()),
                unidade="rpm",
                regra="potencia_rpm_sem_cv",
                inicio=match.start(),
                fim=match.end(),
                notas="cv renderizado como imagem na fonte; só o rpm é texto.",
            )
        )
    return achados


# ------------------------------------------------- aceleração 0-100 pelo rótulo da ficha
#: Rótulo explícito da própria ficha: "Aceleração 0-100 km/h  | 12 s  |". Existe porque
#: `extrair_aceleracao_por_proximidade` exige segundos com casa decimal (`\d{1,2},\d`), e
#: fichas como a do CarrosNaWeb publicam segundos inteiros ("12 s", sem vírgula).
_ACELERACAO_0_100_ROTULO = re.compile(
    r"Acelera[çc][ãa]o\s+0-?100\s*km/h[^\n]*?(?P<v>\d{1,2}(?:,\d)?)\s?s\b", re.IGNORECASE
)


def extrair_aceleracao_0_100_rotulo(texto: str, *, campos: set[str] | None = None) -> list[Achado]:
    """`aceleracao_0_100_s` ancorado no rótulo "Aceleração 0-100 km/h", inteiro ou decimal."""
    if campos and "aceleracao_0_100_s" not in campos:
        return []
    achados: list[Achado] = []
    for match in _ACELERACAO_0_100_ROTULO.finditer(texto):
        bruto = match.group("v")
        achados.append(
            Achado(
                campo="aceleracao_0_100_s",
                valor=float(bruto.replace(",", ".")),
                valor_bruto=bruto,
                quote=quote_da_janela(texto, match.start(), match.end()),
                unidade="s",
                regra="aceleracao_0_100_rotulo",
                inicio=match.start(),
                fim=match.end(),
            )
        )
    return achados


def _melhor_quote_por_valor(achados: list[Achado]) -> list[Achado]:
    """Um achado por valor: o de citação mais longa.

    Defeito real: o registro de evidência da Raptor escreve o mesmo número em três
    linhas do JSON — `valor_bruto` ("5,8 segundos (declarado pela Ford)"),
    `valor_normalizado` ("5,8 s") e `trecho` ("A Ford declara que... 5,8 segundos") —, e
    as três estão a alcance da âncora "0 a 100". Sem escolher, quem ficava era a última
    lida, e às vezes era a citação pobre: `claim_type` não achava "declara" nem
    "medi/teste" nela, e a tela perdia o rótulo declarado/medido que a Autoesporte
    de fato sustenta. A mais longa é a mais informativa, e aqui é também a que carrega
    o termo que prova o tipo da afirmação.
    """
    melhores: dict[float, Achado] = {}
    for achado in achados:
        atual = melhores.get(achado.valor)
        if atual is None or len(achado.quote) > len(atual.quote):
            melhores[achado.valor] = achado
    return list(melhores.values())


#: Linha vazia: fim do assunto. Uma âncora não alcança o parágrafo seguinte.
_QUEBRA_DE_PARAGRAFO = re.compile(r"\n\s*\n")


def _continuar_apos_quebra_de_linha(texto: str, bruto: str, fim: int) -> tuple[str, int]:
    """Segue para a linha seguinte quando o PDF quebrou a lista no meio de um termo.

    Defeito real na ficha da Raptor: "...Escorregadio, Lama/\\nTerra, Areia, Baja, Rock
    Crawl" — a lista capturada não cruza `\\n`, então parava em "Lama/" e devolvia 4 dos
    7 modos, fabricando divergência contra a página do site, que traz os 7. O gatilho é
    estreito de propósito: só quando a linha capturada termina em `/` (um composto
    partido pela quebra, como "Lama/Terra") e a linha seguinte não está em branco — uma
    linha vazia é fim de parágrafo, não continuação.
    """
    if not bruto.rstrip().endswith("/"):
        return bruto, fim
    if fim >= len(texto) or texto[fim] != "\n":
        return bruto, fim
    fim_da_continuacao = texto.find("\n", fim + 1)
    if fim_da_continuacao == -1:
        fim_da_continuacao = len(texto)
    continuacao = texto[fim + 1 : fim_da_continuacao]
    if not continuacao.strip():
        return bruto, fim
    return bruto + continuacao, fim_da_continuacao


def extrair_modos(texto: str, *, campos: set[str] | None = None) -> list[Achado]:
    """Extrai listas de modos, canonicalizando os tokens pela ontologia."""
    achados: list[Achado] = []
    for campo, padrao in PADROES_DE_MODOS.items():
        if campos and campo not in campos:
            continue
        for match in padrao.finditer(texto):
            lista_bruta, fim = _continuar_apos_quebra_de_linha(
                texto, match.group("lista"), match.end()
            )
            bruto = _corta_lista(lista_bruta)
            tokens = [
                t for t in _SEPARADOR.split(bruto) if t and len(t) > 1 and parece_nome_de_modo(t)
            ]
            lista = canonicalizar_lista(campo, tokens)
            if len(lista) < 2:
                continue
            # Ao menos dois tokens têm de ser **modos que a ontologia conhece**. Sem
            # isto, "resposta do acelerador, controle de tração, estabilidade" —
            # três trechos do parágrafo que explica os modos, todos curtos o bastante
            # para passar por `parece_nome_de_modo` — virava uma lista de modos e
            # divergia da lista verdadeira da mesma página.
            if sum(1 for t in tokens if valor_conhecido(campo, t)) < MINIMO_DE_MODOS_CONHECIDOS:
                continue
            achados.append(
                Achado(
                    campo=campo,
                    valor=lista,
                    valor_bruto=bruto,
                    quote=quote_da_janela(texto, match.start(), fim),
                    regra=f"{campo}_lista",
                    inicio=match.start(),
                    fim=fim,
                )
            )
    return achados


# ------------------------------------------------------------------------- fachada
#: Frases que **negam** o que vem depois. Uma regra que casa dentro do escopo de uma
#: negação está lendo a coisa negada como se fosse afirmada.
#:
#: O defeito real: o registro de coleta da Amarok diz *"Não foram encontrados 'modos de
#: volante', 'modos de direção' ou 'steering modes'"* — a maneira como o coletor humano
#: anotou uma **ausência**. A regra de lista de modos casou as palavras dentro da negação
#: e produziu `modos_direcao = ['modos_de_direcao_ou_steering_modes', ...]`. A ficha
#: passaria a afirmar modos de direção citando, como evidência, a frase que diz que eles
#: não existem.
#:
#: Só entram formas **explícitas**. "sem" ficou de fora de propósito: "sem parar", "sem
#: custo adicional" e "freio sem servo" apareceriam como negação e derrubariam valores
#: legítimos. Negar demais custa campo verdadeiro; a lista prefere errar para menos.
_NEGACAO = re.compile(
    r"n[ãa]o\s+(?:foram|foi|s[ãa]o|h[áa]|existe[m]?|possui|possuem|tem|t[êe]m|oferece|"
    r"disponibiliza|encontrad[oa]s?|consta[m]?|informa|declara|menciona|aplic[áa]vel|"
    r"dispon[íi]vel)"
    r"|nenhum[ao]?\b|inexistente|n[ãa]o\s+se\s+aplica",
    re.IGNORECASE,
)
#: Alcance da negação, em caracteres. Uma negação some ao fim da frase: o ponto e o
#: ponto-e-vírgula cortam o alcance antes disso.
ALCANCE_DA_NEGACAO = 80
#: Pontuação que encerra o escopo de uma negação.
_FIM_DA_FRASE = re.compile(r"[.;]\s|\n")


def sob_negacao(texto: str, inicio: int) -> str:
    """A negação que domina a posição `inicio`, ou `""` se não houver.

    Olha os `ALCANCE_DA_NEGACAO` caracteres anteriores e para na última pontuação de fim
    de frase: uma negação da frase anterior não alcança esta.
    """
    janela = texto[max(0, inicio - ALCANCE_DA_NEGACAO) : inicio]
    cortes = list(_FIM_DA_FRASE.finditer(janela))
    if cortes:
        janela = janela[cortes[-1].end() :]
    achado = _NEGACAO.search(janela)
    return achado.group(0) if achado else ""


def sem_os_negados(achados: list[Achado], texto: str) -> tuple[list[Achado], list[str]]:
    """Remove os achados que caem dentro do escopo de uma negação.

    Devolve `(mantidos, descartados_nomeados)`. O descarte é **nomeado** porque uma
    ausência silenciosa aqui esconderia o motivo de um campo ter ficado vazio.

    O resultado certo é não afirmar **nada** — nem valor, nem `nao_disponivel`. A frase
    negada aqui é anotação de quem coletou ("não encontrei"), não declaração da montadora
    ("esta versão não tem"): a primeira é `nao_encontrado`, a segunda é `nao_disponivel`,
    e confundi-las inverteria o sentido do vazio.
    """
    mantidos: list[Achado] = []
    descartados: list[str] = []
    for achado in achados:
        negacao = sob_negacao(texto, achado.inicio)
        if negacao:
            descartados.append(
                f"{achado.campo}: descartado — o trecho está sob negação "
                f"({negacao.strip()!r}), então a fonte nega o valor em vez de afirmá-lo"
            )
            continue
        mantidos.append(achado)
    return mantidos, descartados


@dataclass
class ResultadoFastpath:
    achados: list[Achado] = field(default_factory=list)
    campos_alvo: tuple[str, ...] = ()
    descartados: list[str] = field(default_factory=list)
    """Achados removidos por guarda, com o motivo. Visível para nao ser silencioso."""

    @property
    def campos_resolvidos(self) -> set[str]:
        return {a.campo for a in self.achados}

    @property
    def fastpath_rate(self) -> float | None:
        """Fração dos campos-alvo resolvidos sem LLM. `None` se não houver alvo."""
        if not self.campos_alvo:
            return None
        return len(self.campos_resolvidos & set(self.campos_alvo)) / len(self.campos_alvo)

    @property
    def campos_para_o_llm(self) -> list[str]:
        """O que o fast-path não resolveu — é o que vai ao modelo."""
        return sorted(set(self.campos_alvo) - self.campos_resolvidos)

    def por_campo(self, campo: str) -> list[Achado]:
        return [a for a in self.achados if a.campo == campo]

    def confianca_de(self, campo: str, tier: int) -> float:
        """Confiança do campo: base do tier, sem bônus — o fast-path não reconcilia."""
        return CONFIANCA_POR_TIER.get(tier, 0.2) if self.por_campo(campo) else 0.0


# ------------------------------------------- ficha em pares "rótulo / valor"
#: Quantas linhas depois do rótulo o valor pode estar. Duas: `page.md` separa blocos
#: com linha vazia, e um rótulo seguido de duas linhas vazias já não é um par.
DISTANCIA_MAXIMA_DO_VALOR = 2

#: Linhas que nunca são valor de nada — são rótulo de outra coisa, ou ruído de página.
_NAO_E_VALOR = re.compile(r"^(?:\*\*|#|---|\||$)")

#: Duas ou mais casas de espaço entre dois não-espaços: a assinatura de **coluna**.
_COLUNAS_NA_LINHA = re.compile(r"\S(?: {3,}|\t+)\S")
#: Acima desta fração de linhas com colunas, o texto é ficha de PDF com layout, e o par
#: rótulo/valor em linhas alternadas **não** se aplica.
FRACAO_DE_LAYOUT_TABULAR = 0.05
#: Abaixo deste número de linhas não se julga o layout: 4 linhas não dizem nada.
LINHAS_PARA_JULGAR_LAYOUT = 20


def tem_layout_de_tabela(texto: str) -> bool:
    """O texto é ficha com layout de colunas preservado (PDF), e não HTML linearizado?

    A pergunta importa porque o par "rótulo numa linha, valor na seguinte" é um padrão
    de **HTML** (lista de definições linearizada). Em PDF com layout, rótulo e valor
    ficam na **mesma** linha, separados por espaços — e a linha percorre todas as
    versões. Aplicar a regra de pares ali produziu, na ficha da Hilux:

        TRANSMISSÃO                          <- título de seção, não rótulo
        16V Turbo*  3.400        2.800       <- linha de outra seção

    e `transmissao.tipo` virou `"16v_turbo*_3.400_3.400"`, com `tracao.tipo_tracao`
    recebendo a linha inteira `"4×2, 4×4 e 4×4 reduzida…"` em vez da coluna da SRX Plus.
    Nesses documentos quem responde é o recorte de coluna (`version_slicer`), que é
    melhor: ele sabe **qual** coluna é da versão.

    O critério é medido, não estimado. Nas 24 fontes salvas do projeto, os cinco PDFs
    ficam entre 10,3% e 51,4% de linhas com colunas; todas as 19 fontes de HTML,
    registro, FIPE e PBE ficam em **0,000**. O limiar de 5% separa os dois grupos com
    folga de duas vezes.
    """
    linhas = [linha for linha in texto.splitlines() if linha.strip()]
    if len(linhas) < LINHAS_PARA_JULGAR_LAYOUT:
        return False
    com_colunas = sum(1 for linha in linhas if _COLUNAS_NA_LINHA.search(linha))
    return com_colunas / len(linhas) > FRACAO_DE_LAYOUT_TABULAR


def pares_de_rotulo(texto: str) -> list[tuple[str, str, str]]:
    """`[(rótulo, valor, trecho literal)]` da ficha escrita em linhas separadas.

    As montadoras publicam a ficha técnica em HTML como uma **lista de definições**:
    o rótulo numa linha, o valor na seguinte. Convertido para texto, isso vira

        Potência
        250 cv @ 3.250rpm

        Torque
        600 Nm @ 1.750 rpm

    e nenhuma regra que espera "Rótulo Valor" na **mesma** linha encontra nada. O
    resultado medido em 10/09/2026, na página da Ranger Limited: `motor_descricao`,
    `capacidade_carga_kg`, `comprimento_mm`, `largura_mm`, `altura_mm`,
    `entre_eixos_mm` e `tanque_l` ficavam `nao_encontrado` — e os sete estão na página,
    escritos exatamente assim. Pior: `motor_descricao` era então respondido pelo
    **comparador de versões**, que traz o motor das doze versões, e a Limited saía com
    motor 2.0 (o da XL) por maioria de ocorrências.

    O rótulo é reconhecido pelo mesmo mapa fechado das tabelas de PDF
    (:data:`ROTULO_PARA_CAMPO`), e o `trecho` devolvido é o par **literal** — é ele que
    vai como citação, e é substring exata do texto salvo.
    """
    if tem_layout_de_tabela(texto):
        return []
    linhas = texto.splitlines(keepends=True)
    inicios: list[int] = []
    posicao = 0
    for linha in linhas:
        inicios.append(posicao)
        posicao += len(linha)

    achados: list[tuple[str, str, str]] = []
    for i, linha in enumerate(linhas):
        rotulo = linha.strip()
        # Rótulo **exato**, e não por prefixo como nas células de PDF. Numa lista de
        # equipamentos, "Faróis FullLed" e "Direção elétrica" são itens da lista, não
        # rótulos de ficha — e o casamento por prefixo os aceitava, colando neles a
        # linha seguinte: `farois_tipo = "INTERIOR"` (o título da seção seguinte) e
        # `direcao = "Freio a disco nas 4 rodas"`. Numa tabela de PDF o rótulo vem da
        # grade e o prefixo é seguro; num texto corrido, não.
        if not rotulo or len(rotulo) > 60:
            continue
        if normalizar_rotulo(rotulo) not in ROTULO_PARA_CAMPO:
            continue
        for salto in range(1, DISTANCIA_MAXIMA_DO_VALOR + 1):
            if i + salto >= len(linhas):
                break
            valor = linhas[i + salto].strip()
            if not valor:
                continue
            if _NAO_E_VALOR.match(valor) or normalizar_rotulo(valor) in ROTULO_PARA_CAMPO:
                break
            trecho = texto[inicios[i] : inicios[i + salto] + len(linhas[i + salto])].strip()
            achados.append((rotulo, valor, trecho))
            break
    return achados


#: PDF usa dois ou mais espaços; `html_para_texto` preserva células como tabulação.
#: Não use `\s{2,}`: ele também atravessa quebras de linha e pode remontar um par que
#: nunca existiu na fonte.
_SEPARADOR_DE_COLUNA = re.compile(r"(?:\t+| {2,})")

#: Um valor numérico sozinho: "715", "1.005", "5,8". Unidade colada fica de fora — quem lê
#: valor com unidade é a regra inline, e ela roda depois, restrita ao campo do rótulo.
_SO_NUMERO = re.compile(r"^[\d.,]+$")


def pares_em_linha(texto: str) -> list[tuple[str, str, str]]:
    """`[(rótulo, valor, trecho literal)]` da ficha de PDF em colunas, **com uma versão só**.

    **O vão que esta função fecha.** Um avaliador olhou a ficha da Ranger Raptor em
    12/09/2026 e viu *Dimensões e capacidades 0 de 7* — tudo `nao_encontrado`. Os valores
    estavam no PDF oficial já salvo, escritos assim:

        Capacidade de carga (kg)                        715
        Tanque de combustível (L)                        77
        Comprimento do veículo (mm)                    5381

    e os seis rótulos já estavam em :data:`ROTULO_PARA_CAMPO`. Eles se perdiam entre os
    dois mecanismos de extração, e o vão era silencioso:

    * o **recorte por coluna** (`version_slicer`) exige uma grade (`tables.json`) ao lado
      do documento, e só um snapshot do repositório tem uma;
    * o **par rótulo/valor** (:func:`pares_de_rotulo`) desiste de propósito quando o texto
      tem layout de colunas — e com razão, porque ali a linha costuma percorrer todas as
      versões, e ler a primeira coluna daria à Hilux SRX Plus o número da STD.

    O terceiro caso é este: layout de colunas com **uma versão só**, em que rótulo e valor
    estão na mesma linha e não há ambiguidade nenhuma.

    **A guarda que faz isso ser seguro, e que não é opcional.** A linha é quebrada em
    colunas por dois-ou-mais espaços; achado o rótulo, contam-se os valores numéricos
    **depois dele até o fim da linha**. Exatamente um → é o valor. Dois ou mais → **abstém**,
    porque a linha percorre versões e escolher uma delas é a inferência que o produto
    proíbe. Na ficha multiversão da Hilux, "Capacidade de carga" tem quatro números na
    mesma linha; ali esta função não responde nada, e quem responde é o recorte de coluna,
    que sabe **qual** coluna é da versão.

    O risco que a abstenção cobre é o pior tipo: um valor de outra versão entraria com
    evidência que groundeia perfeitamente, e **nenhuma métrica do eval o pegaria**, porque
    dimensões não estão no gabarito.

    O `trecho` devolvido é a fatia **literal** do texto, do início do rótulo ao fim do
    valor — substring exata, que passa pelo grounding no caminho `exato`.
    """
    achados: list[tuple[str, str, str]] = []
    posicao = 0
    for linha in texto.splitlines(keepends=True):
        inicio_da_linha = posicao
        posicao += len(linha)
        colunas = [c for c in _SEPARADOR_DE_COLUNA.split(linha.strip()) if c]
        if len(colunas) < 2:
            continue

        for indice, coluna in enumerate(colunas[:-1]):
            campo = campo_do_rotulo(coluna)
            if campo is None:
                continue
            depois = colunas[indice + 1 :]
            numeros = [c for c in depois if _SO_NUMERO.match(c)]
            # A guarda. Duas linhas, e são elas que impedem a Hilux de herdar o número da
            # STD com uma citação impecável.
            if len(numeros) != 1:
                continue
            valor = numeros[0]
            if depois[0] != valor:
                # O valor tem de estar **colado** ao rótulo: com outra coisa no meio, o
                # par "rótulo … valor" é coincidência de linha, não leitura de ficha.
                continue

            # A fatia literal, localizada no texto original e não remontada das colunas.
            corte_rotulo = linha.find(coluna)
            corte_valor = linha.find(valor, corte_rotulo + len(coluna))
            if corte_rotulo < 0 or corte_valor < 0:
                continue
            trecho = linha[corte_rotulo : corte_valor + len(valor)]
            assert texto[inicio_da_linha + corte_rotulo :].startswith(trecho)
            achados.append((coluna, valor, trecho))
    return achados


def pares_com_dois_pontos(texto: str) -> list[tuple[str, str, str]]:
    """Read literal ``label: value`` lines from HTML/article text.

    Many public vehicle pages use paragraphs instead of a semantic table. Requiring
    the value on the next line discarded dimensions and consumption that were already
    explicit in the saved source. The closed label map remains the safety gate.
    """
    pares: list[tuple[str, str, str]] = []
    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha or len(linha) > 500 or ":" not in linha:
            continue
        rotulo, valor = (parte.strip() for parte in linha.split(":", 1))
        # Colon syntax is common in JSON and prose. Unlike a real table cell, it only
        # uses the exact closed map; fuzzy ontology here turned ``"tier": ...`` into
        # transmission ``tipo`` in a saved evidence record.
        if (
            not rotulo
            or not valor
            or rotulo.startswith(('"', "'", "{"))
            or valor in {"[", "{", "[]", "{}"}
            or normalizar_rotulo(rotulo) not in ROTULO_PARA_CAMPO
        ):
            continue
        pares.append((rotulo, valor, linha))
    return pares


def extrair_de_pares(texto: str, *, campos: set[str] | None = None) -> list[Achado]:
    """Achados da ficha em pares rótulo/valor. Ver :func:`pares_de_rotulo`.

    Duas propriedades que fazem isto ser seguro num texto de página inteira:

    * **o valor só pode responder o campo do próprio rótulo.** As regras rodam com
      `campos={campo do rótulo}`, sobre o **valor** e não sobre a página. "80" abaixo de
      "Tanque de combustível (L)" é tanque; "80" em qualquer outro lugar da página não é
      lido por esta função;
    * **`de_celula=True`.** O nome vem da coluna de tabela, e a semântica é a mesma que
      importa para a reconciliação: valor colado ao seu rótulo, não pescado do texto
      corrido. `reconcile.preferir_celulas` e `preferir_especifico_da_versao` tratam os
      dois pelo mesmo critério, que é o certo — nos dois casos a alternativa é uma linha
      que percorre várias versões.
    """
    achados: list[Achado] = []
    # Ficha de PDF em colunas cai em `pares_em_linha`, que lê rótulo e valor na MESMA
    # linha e se abstém quando há mais de um valor. Antes deste desvio, `pares_de_rotulo`
    # devolvia lista vazia nesses documentos e as dimensões da Raptor ficavam 0 de 7.
    em_colunas = tem_layout_de_tabela(texto)
    pares = pares_em_linha(texto) if em_colunas else pares_de_rotulo(texto)
    if not em_colunas:
        pares += pares_com_dois_pontos(texto)
    for rotulo, valor, trecho in pares:
        campo = campo_do_rotulo(rotulo)
        if campo is None or (campos and campo not in campos):
            continue
        if campo in CAMPOS_DE_TEXTO:
            achados.append(
                Achado(
                    campo=campo,
                    valor=valor,
                    valor_bruto=valor,
                    quote=trecho,
                    regra="par_de_rotulo_texto",
                    de_celula=True,
                    rotulo=rotulo,
                    notas=f"ficha em pares: «{rotulo}» / «{valor}»",
                )
            )
            continue
        # Duas passadas, e as duas são necessárias:
        #
        # * as **regras por rótulo** casam o valor **puro** (`"1023"` sob "Capacidade de
        #   carga (kg)", `"5370"` sob "Comprimento do veículo (mm)"). São elas que sabem
        #   que um número sozinho é o valor daquele campo — nenhuma regra inline lê
        #   `"1023"` isolado, e não deveria;
        # * as **regras inline** casam o valor com unidade colada (`"250 cv @ 3.250rpm"`
        #   sob "Potência"), que é como a Ford escreve na página e nenhuma regra por
        #   rótulo (ancorada em `^\d+/\d+$`) reconhece.
        #
        # A primeira que responder ganha; as duas restritas ao campo do rótulo.
        derivados = [
            a for a in _por_regra_de_rotulo(valor, campo) if not campos or a.campo in campos
        ] or list(extrair_de_texto(valor, campos={campo}))
        for achado in derivados:
            achados.append(
                Achado(
                    campo=achado.campo,
                    valor=achado.valor,
                    valor_bruto=valor,
                    quote=trecho,
                    unidade=achado.unidade,
                    regra=f"par_de_rotulo:{achado.regra}",
                    de_celula=True,
                    rotulo=rotulo,
                    notas=f"ficha em pares: «{rotulo}» / «{valor}»",
                )
            )
    return achados


def _por_regra_de_rotulo(valor: str, campo: str) -> list[Achado]:
    """As `REGRAS_POR_ROTULO` do campo, aplicadas ao valor puro. Extras incluídos."""
    achados: list[Achado] = []
    for regra in REGRAS_POR_ROTULO:
        if regra.campo != campo:
            continue
        match = regra.padrao.match(valor)
        if not match:
            continue
        try:
            convertido = regra.conversor(match)
        except (ValueError, KeyError):
            continue
        achados.append(
            Achado(
                campo=campo,
                valor=convertido,
                valor_bruto=valor,
                quote=valor,
                unidade=regra.unidade,
                regra=regra.nome,
            )
        )
        for campo_extra, grupo, unidade in regra.extras:
            try:
                extra = round(units.parse_number_ptbr(match.group(grupo)))
            except (ValueError, IndexError):
                continue
            achados.append(
                Achado(
                    campo=campo_extra,
                    valor=extra,
                    valor_bruto=valor,
                    quote=valor,
                    unidade=unidade,
                    regra=regra.nome + ":extra",
                )
            )
        break
    return achados


def extrair(
    texto: str = "",
    *,
    celulas=(),
    campos: set[str] | None = None,
) -> ResultadoFastpath:
    """Fast-path completo: inline + modos sobre `texto`, por rótulo sobre `celulas`."""
    achados: list[Achado] = []
    if texto:
        achados += extrair_de_texto(texto, campos=campos)
        achados += extrair_modos(texto, campos=campos)
        achados += extrair_enums(texto, campos=campos)
        achados += extrair_farol_por_assinatura(texto, campos=campos)
        achados += extrair_rotulados(texto, campos=campos)
        achados += extrair_de_pares(texto, campos=campos)
        achados += extrair_aceleracao_por_proximidade(texto, campos=campos)
        achados += extrair_aceleracao_0_100_rotulo(texto, campos=campos)
        achados += extrair_potencia_rpm_sem_cv(texto, campos=campos)
        achados += extrair_adas(texto, campos=campos)
    if celulas:
        achados += extrair_de_celulas(celulas, campos=campos, texto=texto)
    # A guarda de negacao vale para TODAS as regras, e por isso mora no funil: qualquer
    # regra que case dentro de "nao foram encontrados ..." estaria lendo a coisa negada
    # como afirmada, e isso nao e propriedade de uma regra so.
    descartados: list[str] = []
    if texto:
        achados, descartados = sem_os_negados(achados, texto)
    return ResultadoFastpath(
        achados,
        tuple(sorted(campos)) if campos else (),
        descartados=descartados,
    )


#: Acima disto, um preço de picape é implausível — o gatilho para a leitura
#: "número + marcador de nota de rodapé" (ver a regra `preco_com_marcador_de_nota`).
PRECO_IMPLAUSIVEL_BRL = 2_000_000


def _com_notas_de_marcador(achados: list[Achado]) -> list[Achado]:
    """Descarta a leitura de preço implausível quando existe a plausível para o mesmo trecho.

    O texto salvo da Ford tem `"R$ 499.0002"`. As duas regras de preço concorrem: a
    estrita não casa nada, a de marcador devolve 499.000. Quando as duas casam o mesmo
    trecho, fica a plausível — e a nota registra a interpretação, para que ninguém
    descubra depois que houve uma.
    """
    resultado: list[Achado] = []
    for achado in achados:
        if achado.regra == "preco_com_marcador_de_nota":
            if isinstance(achado.valor, (int, float)) and achado.valor > PRECO_IMPLAUSIVEL_BRL:
                continue
            achado.notas = (
                "o número vinha com um dígito colado (marcador de nota de rodapé da "
                "página); lido como preço + marcador porque a leitura direta daria um "
                "valor implausível. Trecho preservado verbatim."
            )
        resultado.append(achado)
    return resultado
