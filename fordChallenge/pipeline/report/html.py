"""O documento que vai para o cliente. **HTML, determinístico, sem PII.**

Este é o único artefato do produto que sai da mão da Ford e vai para a mão de outra pessoa,
e isso muda três coisas em relação às telas internas:

* **nada de mecânica interna.** Nem "tier", nem "confiança", nem "LLM", nem custo de
  extração. O cliente vê **fonte e data** — o que ele precisa para conferir sozinho — e não
  a régua com que medimos a nós mesmos. `docs/12` §6.6, e o verify confere palavra por
  palavra;
* **nenhum dado pessoal.** Não há campo de nome, telefone ou e-mail no gerador, e não há
  parâmetro para passá-los. Um PDF "personalizado" com o nome do cliente seria o primeiro
  lugar onde PII escaparia do sistema;
* **onde o concorrente vence tem seção própria**, com título. É a mesma regra da tela
  (`docs/12` §3) levada ao papel: um documento que só elogia é um documento que o cliente
  desconta inteiro quando descobre o que ficou de fora.

O HTML é gerado com `escape()` em todo valor: os textos vêm de páginas de terceiros, e um
`<script>` numa citação de fonte não pode virar script no documento.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from html import escape
from typing import Any

#: O rodapé de ressalvas. **Literal**: é a linha que separa "informação com procedência"
#: de "material de propaganda".
RODAPE = (
    "Dados oficiais das montadoras, coletados nas datas indicadas em cada fonte. Valores "
    "de preço e de linha vigente mudam sem aviso — confirme na concessionária antes de "
    "decidir. Este documento não é proposta comercial."
)

#: O aviso que acompanha toda estimativa de custo. Vem de `pipeline/fit/usage_cost.py`.
AVISO_DE_ESTIMATIVA = (
    "As estimativas de combustível usam o consumo indicado e os preços informados na data "
    "da conversa. Não incluem seguro, manutenção ou depreciação."
)

#: Termos que **não** podem aparecer no documento do cliente. O verify confere.
TERMOS_INTERNOS_PROIBIDOS = ("tier", "confiança", "confianca", "LLM", "prompt", "token")

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: "Segoe UI", Arial, sans-serif; color: #1f2933; font-size: 11pt; }
h1 { font-size: 20pt; margin: 0 0 2mm 0; color: #00274d; }
h2 { font-size: 13pt; margin: 8mm 0 2mm 0; color: #00274d;
     border-bottom: 1px solid #cbd2d9; padding-bottom: 1mm; }
h3 { font-size: 11pt; margin: 4mm 0 1mm 0; }
p, li, td, th { line-height: 1.45; }
table { width: 100%; border-collapse: collapse; margin-top: 2mm; }
th, td { text-align: left; padding: 1.5mm 2mm; border-bottom: 1px solid #e4e7eb; }
th { background: #f5f7fa; font-size: 10pt; }
.cabecalho { border-bottom: 3px solid #00274d; padding-bottom: 3mm; }
.par { font-size: 12pt; color: #3e4c59; margin: 1mm 0 0 0; }
.atencao { border: 2px solid #b26b00; background: #fff8e6; padding: 3mm; margin-top: 3mm; }
.atencao h3 { margin-top: 0; color: #8a5300; }
.fonte { font-size: 9pt; color: #52606d; word-break: break-all; }
.rodape { margin-top: 8mm; border-top: 1px solid #cbd2d9; padding-top: 3mm;
          font-size: 9pt; color: #52606d; }
.numero { font-variant-numeric: tabular-nums; }
.ganha { color: #0b6b3a; font-weight: 600; }
.perde { color: #9b1c1c; font-weight: 600; }
"""

#: O **mesmo** documento com o CSS que o motor de reserva entende (`xhtml2pdf`).
#:
#: O `xhtml2pdf` implementa um subconjunto de CSS: sem flexbox, sem grid, sem `var()`,
#: `@media` fraco. O que ele não entende ele **ignora com aviso**, então o que muda aqui é
#: só o pedido — não o documento:
#:
#: * `border-collapse`, `word-break` e `font-variant-numeric` saem: são as três que o motor
#:   lista como não implementadas. A tabela continua com a linha divisória de cada célula,
#:   que é o que dava o desenho;
#: * `font-family` vira `Helvetica`, a fonte que o motor já tem embutida. "Segoe UI" não
#:   está registrada nele, e registrar exigiria **baixar arquivo de fonte** — o que a
#:   geração não faz (nada de rede);
#: * `line-height` em `%`, porque o valor sem unidade não é aplicado;
#: * `background` vira `background-color`, a forma que o motor lê;
#: * `font-weight: 600` vira `bold`: peso numérico não existe nas fontes embutidas;
#: * `.atencao h3/p` com margem zero: o motor desenha a borda do `div` **por bloco filho**,
#:   e sem zerar a margem a caixa de atenção sai partida em duas.
#:
#: Nenhuma seção, número, fonte, data ou aviso depende de qualquer uma dessas regras.
CSS_XHTML2PDF = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: Helvetica; color: #1f2933; font-size: 11pt; }
h1 { font-size: 20pt; margin: 0 0 2mm 0; color: #00274d; }
h2 { font-size: 13pt; margin: 8mm 0 2mm 0; color: #00274d;
     border-bottom: 1px solid #cbd2d9; padding-bottom: 1mm; }
h3 { font-size: 11pt; margin: 4mm 0 1mm 0; }
p, li, td, th { line-height: 140%; }
table { width: 100%; margin-top: 2mm; }
th, td { text-align: left; padding: 1.5mm 2mm; border-bottom: 1px solid #e4e7eb; }
th { background-color: #f5f7fa; font-size: 10pt; }
.cabecalho { border-bottom: 3px solid #00274d; padding-bottom: 3mm; }
.par { font-size: 12pt; color: #3e4c59; margin: 1mm 0 0 0; }
.atencao { border: 2px solid #b26b00; background-color: #fff8e6;
           padding: 2mm 3mm; margin-top: 3mm; }
.atencao h3 { margin: 0; color: #8a5300; }
.atencao p { margin: 0; }
.fonte { font-size: 9pt; color: #52606d; }
.rodape { margin-top: 8mm; border-top: 1px solid #cbd2d9; padding-top: 3mm;
          font-size: 9pt; color: #52606d; }
.ganha { color: #0b6b3a; font-weight: bold; }
.perde { color: #9b1c1c; font-weight: bold; }
"""

#: Onde o `<style>` do documento começa e termina. Fechado no fim do `</style>`, não
#: guloso: o documento tem um só bloco, e um `.*` guloso comeria o corpo inteiro.
_BLOCO_DE_ESTILO = re.compile(r"<style>.*?</style>", re.DOTALL)


def com_css(documento: str, css: str) -> str:
    """O mesmo documento com outro CSS. **Só o `<style>` muda; o conteúdo, nunca.**

    É assim que o motor de reserva recebe um CSS que ele entende (:data:`CSS_XHTML2PDF`)
    sem que exista um segundo gerador de documento — dois geradores seriam duas verdades, e
    a seção que o critério de aceite exige cairia em um deles primeiro.

    Se o documento não tiver bloco de estilo, volta inteiro: a troca é um acabamento, e
    nenhum motivo para não renderizar.
    """
    return _BLOCO_DE_ESTILO.sub(lambda _: f"<style>{css}</style>", documento, count=1)


@dataclass
class LinhaDeComparacao:
    """Uma linha da tabela: campo, os dois valores, e quem leva."""

    campo: str
    rotulo: str
    valor_ford: str
    valor_concorrente: str
    unidade: str = ""
    quem_leva: str = ""
    """`"ford"`, `"concorrente"` ou vazio. Vazio não é empate: é "não ordenamos"."""


@dataclass
class Fonte:
    """Uma fonte citada, com URL e data. Sem uma das duas, não é fonte conferível."""

    url: str
    data: str
    campos: list[str] = field(default_factory=list)


@dataclass
class Relatorio:
    """Tudo o que o documento mostra. Nenhum campo de identificação do cliente."""

    rotulo_ford: str
    rotulo_concorrente: str
    gerado_em: str = ""
    linhas: list[LinhaDeComparacao] = field(default_factory=list)
    pontos: list[str] = field(default_factory=list)
    ponto_do_concorrente: str = ""
    custo_ford: str = ""
    custo_concorrente: str = ""
    frase_do_custo: str = ""
    diferenca_anual: str = ""
    fontes: list[Fonte] = field(default_factory=list)
    aviso_de_comparabilidade: str = ""
    aderencia_ford: str = ""
    aderencia_concorrente: str = ""
    rotulo_da_aderencia: str = ""


def _data_legivel(iso: str) -> str:
    if not iso:
        return "data não registrada"
    try:
        return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def _linha_de_tabela(linha: LinhaDeComparacao, relatorio: Relatorio) -> str:
    classe_ford = "ganha" if linha.quem_leva == "ford" else ""
    classe_conc = "ganha" if linha.quem_leva == "concorrente" else ""
    return (
        "<tr>"
        f"<th scope='row'>{escape(linha.rotulo)}</th>"
        f"<td class='numero {classe_ford}'>{escape(linha.valor_ford)}</td>"
        f"<td class='numero {classe_conc}'>{escape(linha.valor_concorrente)}</td>"
        "</tr>"
    )


def montar(relatorio: Relatorio) -> str:
    """O HTML completo. Toda interpolação passa por `escape()`."""
    gerado = _data_legivel(relatorio.gerado_em) if relatorio.gerado_em else ""
    partes: list[str] = [
        "<!doctype html>",
        "<html lang='pt-BR'><head><meta charset='utf-8'>",
        f"<title>Comparativo — {escape(relatorio.rotulo_ford)}</title>",
        f"<style>{CSS}</style></head><body>",
        "<div class='cabecalho'>",
        "<h1>Comparativo técnico</h1>",
        f"<p class='par'>{escape(relatorio.rotulo_ford)} &times; "
        f"{escape(relatorio.rotulo_concorrente)}</p>",
    ]
    if gerado:
        partes.append(f"<p class='fonte'>Documento gerado em {escape(gerado)}.</p>")
    partes.append("</div>")

    if relatorio.aviso_de_comparabilidade:
        # O aviso de par não comparável vem ANTES da tabela: depois dela, o leitor já
        # formou a conclusão que o aviso deveria qualificar.
        partes.append(
            "<div class='atencao'><h3>Sobre esta comparação</h3>"
            f"<p>{escape(relatorio.aviso_de_comparabilidade)}</p></div>"
        )

    if relatorio.aderencia_ford:
        partes.append("<h2>Aderência ao perfil informado</h2>")
        partes.append(
            "<p><strong>"
            f"{escape(relatorio.rotulo_ford)}:</strong> {escape(relatorio.aderencia_ford)}"
            " &nbsp;·&nbsp; <strong>"
            f"{escape(relatorio.rotulo_concorrente)}:</strong> "
            f"{escape(relatorio.aderencia_concorrente)}</p>"
        )
        if relatorio.rotulo_da_aderencia:
            partes.append(f"<p class='fonte'>{escape(relatorio.rotulo_da_aderencia)}</p>")

    if relatorio.linhas:
        partes.append("<h2>Ficha comparada</h2>")
        partes.append(
            "<table><thead><tr><th>Item</th>"
            f"<th>{escape(relatorio.rotulo_ford)}</th>"
            f"<th>{escape(relatorio.rotulo_concorrente)}</th></tr></thead><tbody>"
        )
        partes.extend(_linha_de_tabela(linha, relatorio) for linha in relatorio.linhas)
        partes.append("</tbody></table>")

    if relatorio.custo_ford or relatorio.custo_concorrente:
        partes.append("<h2>Custo estimado de combustível</h2>")
        partes.append(
            "<p><strong>"
            f"{escape(relatorio.rotulo_ford)}:</strong> {escape(relatorio.custo_ford or '—')}"
            " &nbsp;·&nbsp; <strong>"
            f"{escape(relatorio.rotulo_concorrente)}:</strong> "
            f"{escape(relatorio.custo_concorrente or '—')}</p>"
        )
        if relatorio.diferenca_anual:
            partes.append(f"<p>{escape(relatorio.diferenca_anual)}</p>")
        partes.append(
            f"<p class='fonte'>{escape(relatorio.frase_do_custo or AVISO_DE_ESTIMATIVA)}</p>"
        )

    if relatorio.pontos:
        partes.append("<h2>Pontos a favor da Ford</h2><ol>")
        partes.extend(f"<li>{escape(ponto)}</li>" for ponto in relatorio.pontos)
        partes.append("</ol>")

    # A seção do concorrente **sempre** aparece quando há o ponto, com o título que o
    # critério de aceite exige.
    if relatorio.ponto_do_concorrente:
        partes.append(
            f"<h2>Onde a {escape(relatorio.rotulo_concorrente)} leva vantagem</h2>"
            f"<div class='atencao'><p>{escape(relatorio.ponto_do_concorrente)}</p></div>"
        )

    if relatorio.fontes:
        partes.append("<h2>Fontes consultadas</h2><ul>")
        for fonte in relatorio.fontes:
            # O nome do campo humanizado, como na tabela comparada acima. Esta lista era a
            # única parte do documento que imprimia o nome cru do banco — `adas_itens,
            # airbags_qtd, capacidade_carga_kg, …` — num papel que vai para o cliente por
            # WhatsApp (QA-BUG-10). A URL, logo acima, tem underscore legítimo e continua
            # intocada.
            rotulos = ", ".join(_rotulo_de_campo(c) for c in fonte.campos)
            campos = f" — {escape(rotulos)}" if fonte.campos else ""
            partes.append(
                f"<li class='fonte'>{escape(fonte.url)} "
                f"(coletado em {escape(_data_legivel(fonte.data))}){campos}</li>"
            )
        partes.append("</ul>")

    partes.append(f"<div class='rodape'><p>{escape(RODAPE)}</p></div>")
    partes.append("</body></html>")
    return "\n".join(partes)


def _rotulo_de_campo(campo: str) -> str:
    """`capacidade_carga_kg` → "Capacidade carga kg".

    A mesma regra da tabela comparada e da tela: troca `_` por espaço e capitaliza, e
    para aí. Um dicionário de rótulos bonitos criaria um segundo vocabulário para manter
    em sincronia com os 58 campos do schema, e a primeira divergência entre os dois seria
    invisível.
    """
    texto = campo.replace("_", " ").strip()
    return texto[:1].upper() + texto[1:]


def termos_internos_no_texto(html: str) -> list[str]:
    """Os termos internos que vazaram para o documento. Vazio é o esperado.

    Usado pelo teste e pelo verify: "nenhum texto contém 'confiança', 'tier' ou 'LLM'" é
    critério de aceite, e uma verificação sobre o HTML final é a única que pega o termo que
    entrou por um valor de dado, não por um literal no código.
    """
    plano = html.lower()
    return [t for t in TERMOS_INTERNOS_PROIBIDOS if t.lower() in plano]


def de_dados(
    *,
    comparacao: dict[str, Any],
    argumentario: dict[str, Any] | None = None,
    gerado_em: str = "",
) -> Relatorio:
    """Monta o :class:`Relatorio` a partir das respostas da API.

    `comparacao` é o corpo de `POST /comparisons` (com `fit`, quando houver perfil);
    `argumentario` é o de `POST /comparisons/{par}/arguments`.
    """
    from pipeline.schema import UNIDADE_CANONICA

    fit = comparacao.get("fit") or {}
    concorrentes = fit.get("concorrentes") or []
    primeiro = concorrentes[0] if concorrentes else {}
    aderencia = primeiro.get("aderencia") or {}

    rotulo_ford = (fit.get("base") or {}).get("rotulo") or "Ford"
    rotulo_conc = primeiro.get("rotulo") or "concorrente"

    relatorio = Relatorio(
        rotulo_ford=rotulo_ford,
        rotulo_concorrente=rotulo_conc,
        gerado_em=gerado_em,
        rotulo_da_aderencia=aderencia.get("rotulo") or fit.get("rotulo") or "",
    )
    if aderencia.get("aderencia_ford") is not None:
        relatorio.aderencia_ford = f"{aderencia['aderencia_ford']:.1f} de 10"
        relatorio.aderencia_concorrente = f"{aderencia.get('aderencia_concorrente', 0):.1f} de 10"

    # A tabela vem das dimensões avaliadas: são os campos que **os dois** têm, que é
    # exatamente o que se pode comparar na frente do cliente.
    vistos: set[str] = set()
    for dimensao in aderencia.get("dimensoes", []):
        for indice, nota_ford in enumerate(dimensao.get("detalhe_ford", [])):
            campo = nota_ford.get("campo")
            if not campo or campo in vistos:
                continue
            detalhe_conc = dimensao.get("detalhe_concorrente", [])
            if indice >= len(detalhe_conc):
                continue
            nota_conc = detalhe_conc[indice]
            vistos.add(campo)
            nf, nc = nota_ford.get("nota"), nota_conc.get("nota")
            quem = ""
            if nf is not None and nc is not None:
                quem = "ford" if nf > nc else ("concorrente" if nc > nf else "")
            unidade = UNIDADE_CANONICA.get(campo) or ""
            relatorio.linhas.append(
                LinhaDeComparacao(
                    campo=campo,
                    rotulo=campo.replace("_", " ").capitalize(),
                    valor_ford=_valor_legivel(nota_ford.get("valor"), unidade),
                    valor_concorrente=_valor_legivel(nota_conc.get("valor"), unidade),
                    unidade=unidade,
                    quem_leva=quem,
                )
            )

    custo_base = fit.get("usage_cost_base") or {}
    custo_conc = primeiro.get("usage_cost") or {}
    comparado = primeiro.get("custo_comparado") or {}
    relatorio.custo_ford = _custo_legivel(custo_base)
    relatorio.custo_concorrente = _custo_legivel(custo_conc)
    relatorio.frase_do_custo = custo_conc.get("frase") or custo_base.get("frase") or ""
    if comparado.get("diferenca_ano") is not None:
        quem = comparado.get("quem_gasta_menos")
        nome = rotulo_ford if quem == "ford" else rotulo_conc if quem == "concorrente" else ""
        valor = abs(float(comparado["diferenca_ano"]))
        relatorio.diferenca_anual = f"Diferença estimada de R$ {valor:,.2f} por ano".replace(
            ",", "X"
        ).replace(".", ",").replace("X", ".") + (f" — quem gasta menos: {nome}." if nome else ".")

    if argumentario:
        relatorio.pontos = [p.get("texto", "") for p in argumentario.get("pontos", [])]
        forte = argumentario.get("ponto_forte_concorrente")
        if forte:
            relatorio.ponto_do_concorrente = forte.get("texto", "")

    comparabilidade = primeiro.get("comparabilidade") or {}
    relatorio.aviso_de_comparabilidade = comparabilidade.get("aviso") or ""

    return relatorio


def _valor_legivel(valor: Any, unidade: str) -> str:
    if valor is None:
        return "não informado"
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
    return f"{texto} {unidade}".strip()


def _custo_legivel(custo: dict[str, Any]) -> str:
    if custo.get("custo_mes") is None:
        return custo.get("motivo_sem_custo") or "sem estimativa"
    mes = float(custo["custo_mes"])
    return (
        f"R$ {mes:,.2f} por mês".replace(",", "X").replace(".", ",").replace("X", ".")
        + f" ({custo.get('consumo', {}).get('valor_kml', '—')} km/l"
        f", {custo.get('combustivel', '')})"
    )
