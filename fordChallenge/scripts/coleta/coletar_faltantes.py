#!/usr/bin/env python
"""Coleta o que faltava: Ranger diesel de topo, consumo do PBE e FIPE dos cinco.

Este script **sai para a rede**. Não roda no CI, nenhum teste o chama, e ele obedece as
mesmas quatro regras de sempre (`pipeline/fetch/http.py`): robots.txt consultado antes,
≤ 1 requisição por segundo por domínio, user-agent identificado, e 403/CAPTCHA vira
estado do dado — nunca uma segunda tentativa disfarçada.

O que ele produz, e onde:

* `data/snapshots/<version_id>/<ts>/<source_id>/` — a captura, com `raw.html`/`raw.pdf`
  ao lado do texto e o `meta.json` com URL final, tier, data e sha256;
* `gabarito/raw/<arquivo>` — o mesmo texto, que `scripts/build_fixtures.py` transforma
  em fixture de replay. É por aqui que a coleta chega à demo sem virar cópia manual;
* `reports/coleta.json` — o relatório: o que veio, de onde, e o que **não** veio, com o
  motivo de cada.

Quatro alvos, nesta ordem:

1. **linha Ranger + versão diesel de topo.** Medido em 10/09/2026: a raiz
   `ford.com.br/picapes/ranger/` responde 200 ao cliente HTTP mas **sem nenhuma versão
   no HTML** (monta a linha por JavaScript), e responde `403 Akamai` ao Chromium do
   Playwright. As duas tentativas ficam no relatório. A rota irmã
   `.../compare-as-versoes.html` responde 200 e publica as versões com preço — é dela
   que sai a linha, e a escolha do topo diesel é por **maior preço**, registrada como
   `escolha automática, confirmar`;
2. **preço oficial da Hilux SRX Plus.** Toyota recusa HTTP e navegador; a captura
   arquivada existe mas mostra `R$ --,--` (o preço vem por chamada que o arquivo não
   guardou). Fica `pendente_coleta`, com a URL exata no relatório;
3. **consumo dos cinco pela tabela do PBE/Inmetro**, com fallback para a frase do PBEV
   nas páginas salvas;
4. **FIPE dos cinco pela API comunitária**, gravando o JSON como snapshot tier 2 — o
   corpo é o texto salvo, e `"Valor":"R$ ..."` dentro dele é a citação.

Uso:

    python scripts/coleta/coletar_faltantes.py                # tudo
    python scripts/coleta/coletar_faltantes.py --alvo fipe    # um alvo
    python scripts/coleta/coletar_faltantes.py --seco         # só diz o que faria
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RAW = ROOT / "gabarito" / "raw"
RELATORIO = ROOT / "reports" / "coleta.json"

# A coleta é o oposto de replay. Sem isto, `http.fetch` resolveria por snapshot e o
# script "coletaria" o que já estava salvo — que é a pior forma de não coletar nada.
os.environ["REPLAY_MODE"] = "0"

from pipeline.connectors import fipe as conector_fipe  # noqa: E402
from pipeline.connectors import pbe as conector_pbe  # noqa: E402
from pipeline.connectors.ford import (  # noqa: E402
    COMPARADOR_DE_VERSOES,
    FICHAS_PDF,
    parse_lineup_html,
)
from pipeline.fetch import browser, http, wayback  # noqa: E402
from pipeline.parse import pdf as parse_pdf  # noqa: E402
from pipeline.snapshots import escrever_snapshot  # noqa: E402
from scripts.coleta.texto_de_html import page_md  # noqa: E402

# ------------------------------------------------------------------ os alvos
FORD_LINHA = "https://www.ford.com.br/picapes/ranger/"
FORD_COMPARADOR = COMPARADOR_DE_VERSOES.format(modelo="ranger")
FORD_PDF_RANGER = FICHAS_PDF["limited"]
TOYOTA_CD = "https://www.toyota.com.br/modelos/hilux-cabine-dupla"

#: `version_id` novo da Ranger diesel de topo. O ano vem do nome da versão na página.
RANGER_DIESEL_ID = "ford_ranger_limited_2027"

#: Os cinco veículos, para PBE e FIPE. `codigo_fipe` vem do gabarito (catálogo, não
#: medição — ver o docstring de `pipeline/connectors/fipe.py`); o da Ranger Limited foi
#: descoberto na própria navegação e conferido contra o nome que a API devolve.
VEICULOS = (
    {
        "version_id": "ford_ranger_raptor_2026",
        "marca": "Ford",
        "modelo": "Ranger",
        "versao": "Raptor 3.0 V6 Bi-turbo 4WD AT",
        "ano": 2026,
        "codigo_fipe": "003506-8",
        "slug": "raptor",
    },
    {
        "version_id": "toyota_hilux_srx_plus_at_2026",
        "marca": "Toyota",
        "modelo": "Hilux",
        "versao": "SRX Plus AT (Cabine Dupla)",
        "ano": 2026,
        "codigo_fipe": "002215-2",
        "slug": "hilux_srx_plus",
    },
    {
        "version_id": "vw_amarok_v6_extreme_2026",
        "marca": "Volkswagen",
        "modelo": "Amarok",
        "versao": "V6 Extreme",
        "ano": 2026,
        "codigo_fipe": "005506-9",
        "slug": "amarok_extreme",
    },
    {
        "version_id": "chevrolet_s10_high_country_2027",
        "marca": "Chevrolet",
        "modelo": "S10",
        "versao": "High Country",
        "ano": 2027,
        "codigo_fipe": "004464-4",
        "slug": "s10_high_country",
    },
    {
        "version_id": RANGER_DIESEL_ID,
        "marca": "Ford",
        "modelo": "Ranger",
        "versao": "Limited 3.0 V6 Diesel 4WD AT",
        "ano": 2027,
        "codigo_fipe": "003497-5",
        "slug": "ranger_limited",
    },
)


def hoje() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


@dataclass
class Passo:
    """Um passo da coleta: o que se tentou, o que veio, e o motivo quando não veio."""

    alvo: str
    url: str
    status: str
    detalhe: str = ""
    arquivo_raw: str = ""
    snapshot: str = ""
    valores: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "alvo": self.alvo,
            "url": self.url,
            "status": self.status,
            "detalhe": self.detalhe,
            "arquivo_raw": self.arquivo_raw,
            "snapshot": self.snapshot,
            "valores": self.valores,
        }


def _salvar_raw(nome: str, conteudo: str) -> str:
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / nome).write_text(conteudo, encoding="utf-8", newline="\n")
    return f"gabarito/raw/{nome}"


# ------------------------------------------------------------------ 1) a Ranger
def _diagnosticar_raiz_http(passos: list[Passo]) -> None:
    """O que a raiz do modelo devolve ao cliente HTTP. Inofensivo: pode rodar antes."""
    bruto = http.fetch(FORD_LINHA, usar_cache=False)
    reconhecidas = (
        len(parse_lineup_html(bruto.texto, marca="Ford", modelo="Ranger", uma_por_rotulo=False))
        if bruto.ok
        else 0
    )
    passos.append(
        Passo(
            "ranger:raiz:http",
            FORD_LINHA,
            bruto.status,
            f"{bruto.motivo} · {reconhecidas} versão(ões) no HTML"
            + (" — a página monta a linha por JavaScript" if bruto.ok and not reconhecidas else ""),
        )
    )


def _diagnosticar_raiz_navegador(passos: list[Passo]) -> None:
    """O que a raiz devolve ao Chromium. **Por último, sempre.**

    Medido em 10/09/2026: assim que o Akamai recusa o navegador headless, as duas
    requisições HTTP seguintes ao mesmo domínio — que sozinhas respondem 200 — voltam
    403. A penalidade é do IP, não da rota. Rodar este diagnóstico antes da coleta
    derrubou a página da versão e o PDF numa execução inteira, e o relatório dizia
    "a Ford bloqueia tudo" quando o que bloqueava era a nossa própria ordem de chamadas.
    """
    pelo_navegador = browser.fetch_browser(FORD_LINHA, screenshot=False)
    passos.append(
        Passo(
            "ranger:raiz:navegador",
            FORD_LINHA,
            pelo_navegador.status,
            pelo_navegador.motivo
            + " (diagnóstico feito por último: o 403 penaliza o IP por alguns segundos)",
        )
    )


def coletar_ranger(passos: list[Passo], *, seco: bool = False) -> dict | None:
    """Linha Ranger, versão diesel de topo e o PDF de ficha. Devolve a versão escolhida."""
    # O DADO PRIMEIRO, O DIAGNÓSTICO DEPOIS — e isto não é preferência de estilo.
    # Medido em 10/09/2026: quando a chamada do Chromium leva o 403 do Akamai, a borda
    # penaliza o IP por alguns segundos, e a requisição HTTP **seguinte** (que sozinha
    # responde 200) volta bloqueada. Fazer o diagnóstico antes da coleta transformava o
    # relatório numa profecia auto-realizável.
    comparador = http.fetch(FORD_COMPARADOR, usar_cache=False)
    if not comparador.ok:
        arquivada = wayback.buscar_arquivada(FORD_COMPARADOR)
        passos.append(
            Passo("ranger:comparador:wayback", FORD_COMPARADOR, arquivada.status, arquivada.motivo)
        )
        if not arquivada.ok:
            passos.append(
                Passo(
                    "ranger:linha",
                    FORD_COMPARADOR,
                    "pendente_coleta",
                    "nem o site nem o arquivo entregaram a linha vigente da Ranger",
                )
            )
            return None
        html_comparador, captura_em = arquivada.texto, arquivada.captured_at
    else:
        html_comparador, captura_em = comparador.texto, hoje()

    versoes = parse_lineup_html(
        html_comparador,
        marca="Ford",
        modelo="Ranger",
        url=FORD_COMPARADOR,
        uma_por_rotulo=False,
    )
    com_preco = [v for v in versoes if v.preco_a_partir_brl]
    diesel = [v for v in com_preco if "diesel" in v.nome_exato.lower()]
    if not diesel:
        passos.append(
            Passo(
                "ranger:linha",
                FORD_COMPARADOR,
                "pendente_coleta",
                f"{len(versoes)} versões reconhecidas, nenhuma identificada como diesel",
            )
        )
        return None

    escolhida = max(diesel, key=lambda v: v.preco_a_partir_brl or 0)
    passos.append(
        Passo(
            "ranger:linha",
            FORD_COMPARADOR,
            "ok",
            (
                f"{len(versoes)} versões na linha, {len(diesel)} diesel com preço. "
                "Escolha automática pela **maior** a partir de — confirmar."
            ),
            valores={
                "escolhida": escolhida.nome_exato,
                "ano_modelo": escolhida.ano_modelo,
                "preco_a_partir_brl": escolhida.preco_a_partir_brl,
                "linha": [
                    {
                        "nome": v.nome_exato,
                        "ano": v.ano_modelo,
                        "preco": v.preco_a_partir_brl,
                    }
                    for v in versoes
                ],
            },
        )
    )
    _diagnosticar_raiz_http(passos)

    if seco:
        _diagnosticar_raiz_navegador(passos)
        return {"nome": escolhida.nome_exato, "ano": escolhida.ano_modelo}

    conteudo = page_md(html_comparador, url=FORD_COMPARADOR)
    passos[-1].arquivo_raw = _salvar_raw("ford_ranger_linha_comparador.md", conteudo)
    escrito = escrever_snapshot(
        version_id=RANGER_DIESEL_ID,
        url_final=FORD_COMPARADOR,
        texto=conteudo,
        tier=1,
        tipo="pagina_oficial",
        source_id="ford_site_linha",
        bruto=html_comparador,
        captured_at=captura_em,
        extras={
            "nota": (
                "a raiz do modelo não publica a linha em HTML (monta por JavaScript) e "
                "responde 403 ao navegador headless; esta é a rota irmã do mesmo site "
                "oficial, que publica a linha com preço"
            )
        },
    )
    passos[-1].snapshot = str(escrito.caminho.relative_to(ROOT))

    # -- a página da versão escolhida
    caminho = escolhida.nome_exato.lower()
    for de, para in (
        ("limited 3.0 v6 diesel 4wd at", "limited-30-diesel-4wd-at"),
        ("xlt 3.0 v6 diesel 4wd at", "xlt-30-diesel-4wd-at"),
        ("xls 3.0 v6 diesel 4wd at", "xls-3-0-diesel-4wd-at"),
    ):
        if caminho == de:
            caminho = para
            break
    else:
        passos.append(
            Passo(
                "ranger:versao",
                FORD_COMPARADOR,
                "pendente_coleta",
                (
                    f"a versão escolhida ({escolhida.nome_exato}) não tem rota conhecida em "
                    "compare-as-versoes/; a página da versão não foi coletada"
                ),
            )
        )
        return {"nome": escolhida.nome_exato, "ano": escolhida.ano_modelo}

    url_versao = f"https://www.ford.com.br/picapes/ranger/compare-as-versoes/{caminho}.html"
    pagina = http.fetch(url_versao, usar_cache=False)
    if not pagina.ok:
        passos.append(Passo("ranger:versao", url_versao, pagina.status, pagina.motivo))
    else:
        conteudo = page_md(pagina.texto, url=url_versao)
        escrito = escrever_snapshot(
            version_id=RANGER_DIESEL_ID,
            url_final=url_versao,
            texto=conteudo,
            tier=1,
            tipo="pagina_oficial",
            source_id="ford_site_versao",
            bruto=pagina.texto,
            http_status=pagina.http_status,
            captured_at=hoje(),
        )
        passos.append(
            Passo(
                "ranger:versao",
                url_versao,
                "ok",
                f"{len(conteudo)} caracteres de texto salvo",
                arquivo_raw=_salvar_raw("ford_ranger_limited_site_versao.md", conteudo),
                snapshot=str(escrito.caminho.relative_to(ROOT)),
            )
        )

    # -- o PDF de ficha técnica
    documento = http.fetch(FORD_PDF_RANGER, usar_cache=False)
    if not documento.ok or not documento.conteudo.startswith(b"%PDF-"):
        passos.append(
            Passo("ranger:pdf", FORD_PDF_RANGER, documento.status, documento.motivo or "não é PDF")
        )
    else:
        lido = parse_pdf.parse_pdf(documento.conteudo)
        util = "\n".join(linha for linha in lido.markdown.splitlines() if linha.strip())
        # O PDF da nova Ranger tem a página de especificações **em imagem**: o texto
        # extraível é só o folheto de serviços. Registrar isso é o ponto — a fonte foi
        # consultada, e o que ela dá está dito.
        nota = (
            "página de especificações é imagem: o texto extraível é o folheto de "
            "serviços. As especificações desta versão vêm da página da versão."
            if "Potência" not in util and "Torque" not in util
            else ""
        )
        escrito = escrever_snapshot(
            version_id=RANGER_DIESEL_ID,
            url_final=FORD_PDF_RANGER,
            texto=util,
            tier=1,
            tipo="pdf_oficial",
            source_id="ford_ficha_tecnica",
            formato="doc.md",
            bruto=documento.conteudo,
            http_status=documento.http_status,
            captured_at=hoje(),
            extras=(
                {"motor_de_pdf": lido.motor, "nota": nota} if nota else {"motor_de_pdf": lido.motor}
            ),
        )
        passos.append(
            Passo(
                "ranger:pdf",
                FORD_PDF_RANGER,
                "ok",
                nota or f"{len(util)} caracteres, motor {lido.motor}",
                arquivo_raw=_salvar_raw("ford_ranger_ficha_tecnica_oficial.txt", util + "\n"),
                snapshot=str(escrito.caminho.relative_to(ROOT)),
            )
        )
    _diagnosticar_raiz_navegador(passos)
    return {"nome": escolhida.nome_exato, "ano": escolhida.ano_modelo}


# ----------------------------------------------------- 2) o preço da Hilux SRX Plus
def coletar_preco_hilux(passos: list[Passo], *, seco: bool = False) -> None:
    """Preço oficial da SRX Plus: site, navegador e arquivo. Os três, e o que der."""
    direto = http.fetch(TOYOTA_CD, usar_cache=False)
    passos.append(Passo("hilux:preco:http", TOYOTA_CD, direto.status, direto.motivo))
    if direto.ok and "R$" in direto.texto:
        if not seco:
            conteudo = page_md(direto.texto, url=TOYOTA_CD)
            escrito = escrever_snapshot(
                version_id="toyota_hilux_srx_plus_at_2026",
                url_final=TOYOTA_CD,
                texto=conteudo,
                tier=1,
                tipo="pagina_oficial",
                source_id="toyota_site_cd_preco",
                bruto=direto.texto,
                captured_at=hoje(),
            )
            passos[-1].snapshot = str(escrito.caminho.relative_to(ROOT))
        return

    pelo_navegador = browser.fetch_browser(TOYOTA_CD, screenshot=False)
    passos.append(
        Passo("hilux:preco:navegador", TOYOTA_CD, pelo_navegador.status, pelo_navegador.motivo)
    )

    arquivada = wayback.buscar_arquivada(TOYOTA_CD)
    if not arquivada.ok:
        passos.append(Passo("hilux:preco", TOYOTA_CD, "pendente_coleta", arquivada.motivo))
        return
    # A captura existe. Renderizá-la no navegador é legítimo (o arquivo não bloqueia) e
    # é o que mostra o que ela **de fato** publica.
    renderizada = browser.fetch_browser(arquivada.url_arquivo, screenshot=False, timeout_ms=90_000)
    texto = renderizada.markdown if renderizada.ok else ""
    tem_preco = "R$ --" not in texto and "R$" in texto
    passos.append(
        Passo(
            "hilux:preco:wayback",
            arquivada.url_arquivo,
            "ok" if tem_preco else "pendente_coleta",
            (
                f"captura de {arquivada.captured_at} renderizada; "
                + (
                    "traz preço"
                    if tem_preco
                    else (
                        "a página arquivada mostra 'A partir de: R$ --,--' — o preço vem de "
                        "chamada que o arquivo não guardou. Preço oficial da SRX Plus fica "
                        "`pendente_coleta`; o valor FIPE existe e é outro campo."
                    )
                )
            ),
            valores={"captured_at": arquivada.captured_at},
        )
    )


# ------------------------------------------------------------------- 3) o PBE
def coletar_pbe(passos: list[Passo], *, seco: bool = False) -> None:
    """A tabela anual do PBE e o consumo de cada um dos cinco."""
    try:
        pdf_bytes = conector_pbe.baixar_tabela(autorizado=True)
    except conector_pbe.ColetaNaoDisponivel as exc:
        passos.append(Passo("pbe:tabela", conector_pbe.URL_PAGINA_DOS_CICLOS, "erro", str(exc)))
        return

    linhas = conector_pbe.linhas_da_tabela(pdf_bytes)
    registros = conector_pbe.parse_tabela(linhas)
    passos.append(
        Passo(
            "pbe:tabela",
            conector_pbe.URL_PAGINA_DOS_CICLOS,
            "ok",
            f"{len(linhas)} linhas de texto, {len(registros)} configurações de veículo",
        )
    )
    if seco:
        return

    # O texto salvo é a lista de configurações — não a tabela inteira, que traz 20
    # categorias e 400 linhas de outros segmentos. O recorte é por **linha de veículo**,
    # e o critério (ter categoria, descrição e trio de consumos) está no parser.
    corpo = "\n".join(r.trecho for r in registros)
    documento = (
        f"# Tabela PBE Veicular — configurações publicadas\n\n"
        f"**URL:** {conector_pbe.URL_PAGINA_DOS_CICLOS}\n\n---\n\n{corpo}\n"
    )
    arquivo = _salvar_raw("pbe_tabela_veiculos.md", documento)

    for veiculo in VEICULOS:
        resultado = conector_pbe.casar_na_tabela(
            registros,
            versao=veiculo["versao"],
            modelo=veiculo["modelo"],
            marca=veiculo["marca"],
        )
        if not resultado.tem_valor:
            passos.append(
                Passo(
                    f"pbe:{veiculo['slug']}",
                    conector_pbe.URL_PAGINA_DOS_CICLOS,
                    "nao_encontrado",
                    resultado.motivo,
                    arquivo_raw=arquivo,
                )
            )
            continue
        escrito = escrever_snapshot(
            version_id=veiculo["version_id"],
            url_final=conector_pbe.URL_PAGINA_DOS_CICLOS,
            texto=documento,
            tier=conector_pbe.TIER_PBE,
            tipo="pbe",
            source_id=conector_pbe.SOURCE_ID_TABELA,
            bruto=pdf_bytes,
            captured_at=hoje(),
            extras={"linha_da_versao": resultado.registro.descricao},
        )
        passos.append(
            Passo(
                f"pbe:{veiculo['slug']}",
                conector_pbe.URL_PAGINA_DOS_CICLOS,
                "ok",
                resultado.registro.descricao,
                arquivo_raw=arquivo,
                snapshot=str(escrito.caminho.relative_to(ROOT)),
                valores={
                    "consumo_urbano_kml": resultado.registro.urbano_kml,
                    "consumo_rodoviario_kml": resultado.registro.rodoviario_kml,
                    "trecho": resultado.registro.trecho,
                },
            )
        )


# ------------------------------------------------------------------ 4) a FIPE
def coletar_fipe(passos: list[Passo], *, seco: bool = False) -> None:
    """FIPE dos cinco pela API comunitária, com o JSON virando snapshot tier 2."""
    for veiculo in VEICULOS:
        consulta = conector_fipe.price(
            veiculo["codigo_fipe"],
            veiculo["ano"],
            marca=veiculo["marca"],
            modelo=f"{veiculo['modelo']} {veiculo['versao']}",
        )
        if not consulta.ok:
            passos.append(
                Passo(
                    f"fipe:{veiculo['slug']}",
                    consulta.url,
                    "nao_encontrado",
                    consulta.motivo,
                )
            )
            continue
        corpo = http.fetch(consulta.url).texto
        if seco:
            passos.append(Passo(f"fipe:{veiculo['slug']}", consulta.url, "ok", "(seco)"))
            continue
        documento = (
            f"# FIPE {consulta.modelo_fipe} — {consulta.referencia}\n\n"
            f"**URL:** {consulta.url}\n\n---\n\n{corpo}\n"
        )
        escrito = escrever_snapshot(
            version_id=veiculo["version_id"],
            url_final=consulta.url,
            texto=documento,
            tier=conector_fipe.TIER_FIPE,
            tipo="fipe",
            source_id=f"fipe_{veiculo['slug']}",
            bruto=corpo,
            captured_at=hoje(),
            extras={
                "codigo_fipe": consulta.codigo,
                "referencia": consulta.referencia,
                "zero_km": consulta.zero_km,
            },
        )
        passos.append(
            Passo(
                f"fipe:{veiculo['slug']}",
                consulta.url,
                "ok",
                f"{consulta.modelo_fipe} · referência {consulta.referencia}",
                arquivo_raw=_salvar_raw(f"fipe_api_{veiculo['slug']}.md", documento),
                snapshot=str(escrito.caminho.relative_to(ROOT)),
                valores={
                    "preco_fipe_brl": consulta.preco_brl,
                    "fipe_referencia": consulta.referencia,
                    "quote_preco": consulta.quote_preco,
                    "quote_referencia": consulta.quote_referencia,
                    "zero_km": consulta.zero_km,
                },
            )
        )


# --------------------------------------------------------------------- comando
ALVOS = {
    "ranger": coletar_ranger,
    "hilux-preco": coletar_preco_hilux,
    "pbe": coletar_pbe,
    "fipe": coletar_fipe,
}


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--alvo", choices=[*ALVOS, "tudo"], default="tudo")
    analisador.add_argument("--seco", action="store_true", help="não escreve nada em disco")
    args = analisador.parse_args(argv)

    passos: list[Passo] = []
    escolhidos = ALVOS if args.alvo == "tudo" else {args.alvo: ALVOS[args.alvo]}
    for nome, funcao in escolhidos.items():
        print(f"\n=== {nome} ===", flush=True)
        try:
            funcao(passos, seco=args.seco)
        except Exception as exc:  # o relatório precisa registrar a falha, não morrer nela
            passos.append(Passo(nome, "", "erro", f"{type(exc).__name__}: {exc}"))
        for passo in passos:
            if passo.alvo.startswith(nome.split("-")[0]):
                print(f"  {passo.status:16} {passo.alvo:28} {passo.detalhe[:90]}")

    if not args.seco:
        RELATORIO.parent.mkdir(parents=True, exist_ok=True)
        RELATORIO.write_text(
            json.dumps(
                {
                    "coletado_em": datetime.now(UTC).isoformat(timespec="seconds"),
                    "user_agent": http.user_agent(),
                    "passos": [p.to_dict() for p in passos],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"\nrelatório: {RELATORIO.relative_to(ROOT)}")

    problemas = [p for p in passos if p.status not in {"ok", "cache", "replay"}]
    print(f"\n{len(passos) - len(problemas)} passo(s) ok, {len(problemas)} sem valor:")
    for p in problemas:
        print(f"  {p.status:16} {p.alvo:28} {p.detalhe[:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
