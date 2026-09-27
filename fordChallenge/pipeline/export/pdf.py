"""O PDF do benchmark: a matriz, a lista de fontes e as ressalvas — nessa ordem.

**Por que um documento próprio, e não o relatório de `pipeline/report/html.py`.** Aquele
compara **dois** veículos e fala a língua do argumentário: quem leva cada linha, o custo,
a frase de fechamento. Este compara **N** e fala a língua da auditoria: o que cada célula
diz, de onde veio e no dia em que veio. São dois documentos com leitores diferentes, e
fundi-los faria o segundo herdar as decisões de tom do primeiro.

**A lista de fontes é a metade do documento que justifica a outra.** Uma tabela de
paridade num PDF, sem as URLs e sem as datas, é indistinguível de um slide — e a promessa
inteira do produto é essa distinção. Por isso as fontes vêm **agrupadas por URL**, com os
campos que cada uma sustenta: é assim que alguém confere uma afirmação específica sem
reabrir o sistema.

O motor é o de `pipeline/report/render.py`: WeasyPrint quando houver, `xhtml2pdf` de
reserva, e HTML com o motivo escrito quando nenhum dos dois estiver disponível. Um `.pdf`
truncado no disco é pior que nenhum — alguém o abriria na frente do cliente.
"""

from __future__ import annotations

import datetime as dt
from html import escape
from pathlib import Path

from pipeline.export.tabela import Tabela
from pipeline.report import render

#: A cor de cada situação. Discretas de propósito: papel colorido de tabela vira slide, e
#: o leitor passa a olhar a cor em vez do número. O símbolo carrega a informação.
_ESTILO = """
  @page { size: A4 landscape; margin: 14mm; }
  body { font-family: -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
         color: #1a1d21; font-size: 9pt; }
  h1 { font-size: 15pt; margin: 0 0 2mm; }
  h2 { font-size: 11pt; margin: 6mm 0 2mm; border-bottom: 1px solid #d8dbe0;
       padding-bottom: 1mm; }
  .meta { color: #5b6169; font-size: 8pt; margin: 0 0 4mm; }
  table { width: 100%; border-collapse: collapse; }
  th, td { border-bottom: 1px solid #e4e6ea; padding: 1.4mm 2mm; text-align: left;
           vertical-align: top; }
  thead th { background: #f4f5f7; font-size: 8pt; text-transform: uppercase;
             letter-spacing: .04em; }
  td.campo { font-weight: 600; width: 34mm; }
  td.grupo { color: #5b6169; font-size: 7.5pt; width: 22mm; }
  .situacao { font-size: 7.5pt; color: #5b6169; display: block; }
  .ganhamos { color: #1f7a3d; }
  .perdemos { color: #a32b2b; }
  .naosabemos { color: #8a6a12; }
  .fonte { font-size: 8pt; }
  .fonte td { word-break: break-all; }
  ul.ressalvas { margin: 0; padding-left: 5mm; }
  ul.ressalvas li { margin-bottom: 1.5mm; }
  .rodape { margin-top: 6mm; color: #5b6169; font-size: 7.5pt; border-top: 1px solid
            #d8dbe0; padding-top: 2mm; }
"""

_CLASSE = {"ganhamos": "ganhamos", "perdemos": "perdemos", "não sabemos": "naosabemos"}


def _data_legivel(iso: str) -> str:
    if not iso:
        return "data não registrada"
    try:
        return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def fontes_agrupadas(tabela: Tabela) -> list[tuple[str, str, list[str]]]:
    """`(url, data, campos)` — uma entrada por fonte, com o que ela sustenta.

    Agrupado por URL porque é assim que se confere: ninguém abre a mesma página quatro
    vezes para checar quatro campos. A data anda junto da URL e nunca sozinha — fonte sem
    data não é conferível, é só um endereço.
    """
    por_url: dict[tuple[str, str], list[str]] = {}
    for linha in tabela.linhas:
        for celula in linha.celulas:
            if not celula.fonte_url:
                continue
            chave = (celula.fonte_url, celula.fonte_data)
            campos = por_url.setdefault(chave, [])
            if linha.rotulo not in campos:
                campos.append(linha.rotulo)
    return [(url, data, campos) for (url, data), campos in sorted(por_url.items())]


def montar_html(tabela: Tabela) -> str:
    """O documento inteiro. **Toda** interpolação passa por `escape()`."""
    partes: list[str] = [
        "<!doctype html>",
        "<html lang='pt-BR'><head><meta charset='utf-8'>",
        f"<title>{escape(tabela.titulo)}</title>",
        f"<style>{_ESTILO}</style></head><body>",
        f"<h1>{escape(tabela.titulo)}</h1>",
        f"<p class='meta'>Gerado em {escape(_data_legivel(tabela.gerada_em))}"
        + (
            f" · critérios de comparabilidade versão {escape(tabela.versao_dos_criterios)}"
            if tabela.versao_dos_criterios
            else ""
        )
        + f" · {tabela.campos_com_valor} de {len(tabela.linhas)} campos com valor em pelo "
        "menos um veículo</p>",
        "<h2>Matriz de paridade</h2>",
        "<table><thead><tr><th>Campo</th><th>Dimensão</th>",
    ]
    for coluna in tabela.colunas:
        rotulo = escape(coluna.rotulo)
        extra = f"<br><span class='situacao'>{escape(coluna.comparabilidade)}</span>"
        partes.append(f"<th>{rotulo}{extra if coluna.comparabilidade else ''}</th>")
    partes.append("</tr></thead><tbody>")

    for linha in tabela.linhas:
        partes.append(
            f"<tr><td class='campo'>{escape(linha.rotulo or linha.campo)}</td>"
            f"<td class='grupo'>{escape(linha.grupo)}</td>"
        )
        for celula in linha.celulas:
            classe = _CLASSE.get(celula.situacao, "")
            situacao = (
                f"<span class='situacao {classe}'>{escape(celula.situacao)}</span>"
                if celula.situacao
                else ""
            )
            partes.append(f"<td>{escape(celula.texto)}{situacao}</td>")
        partes.append("</tr>")
    partes.append("</tbody></table>")

    fontes = fontes_agrupadas(tabela)
    partes.append("<h2>Fontes</h2>")
    if fontes:
        partes.append(
            "<table class='fonte'><thead><tr><th>Endereço</th><th>Lido em</th>"
            "<th>Campos que sustenta</th></tr></thead><tbody>"
        )
        for url, data, campos in fontes:
            partes.append(
                f"<tr><td>{escape(url)}</td>"
                f"<td>{escape(_data_legivel(data))}</td>"
                f"<td>{escape(', '.join(campos))}</td></tr>"
            )
        partes.append("</tbody></table>")
    else:
        # Dizer que não há fonte é informação; omitir a seção faria o documento parecer
        # uma tabela de números sem procedência — que é exatamente o que ele não é.
        partes.append(
            "<p>Nenhum campo desta comparação tem fonte registrada. Os valores vêm do "
            "catálogo ou não foram coletados; confira a coluna de cada célula.</p>"
        )

    partes.append("<h2>Ressalvas</h2>")
    if tabela.ressalvas:
        partes.append("<ul class='ressalvas'>")
        partes += [f"<li>{escape(r)}</li>" for r in tabela.ressalvas]
        partes.append("</ul>")
    else:
        partes.append("<p>Nenhuma ressalva registrada para esta comparação.</p>")

    partes.append(
        "<p class='rodape'>Cada valor desta tabela foi lido da página indicada, na data "
        "indicada. Célula sem valor traz o motivo escrito: <em>não encontrado</em> "
        "significa que nenhuma fonte cita o campo, e <em>não disponível</em> significa que "
        "a fonte oficial afirma que o item não existe — não são a mesma coisa.</p>"
    )
    partes.append("</body></html>")
    return "".join(partes)


def gerar(tabela: Tabela, *, nome: str, diretorio: Path | None = None) -> render.Resultado:
    """Grava o PDF (ou o HTML com o motivo, quando não há motor)."""
    return render.renderizar(montar_html(tabela), nome, diretorio=diretorio)
