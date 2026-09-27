#!/usr/bin/env python
"""Gera `tests/fixtures/snapshots/` a partir de `gabarito/raw/`.

Por que um gerador e não uma cópia manual: as fixtures de replay são o substrato de
`make eval` e de todo teste do pipeline. Se alguém trocar um texto bruto, o comando
regenera e o diff mostra exatamente o que mudou. Cópia manual apodrece em silêncio.

Formato de snapshot (o mesmo que a WP-08 vai escrever em `data/snapshots/`):

    tests/fixtures/snapshots/<version_id>/<captured_at>/<source_id>/
        page.md      páginas HTML convertidas
        doc.md       PDFs convertidos
        meta.json    url final, tier, tipo, status, sha256, captured_at, origem
    tests/fixtures/snapshots/<version_id>/fontes.json
        todas as fontes consultadas, inclusive as `bloqueada` (o CAPTCHA da GM é caso
        de teste: fonte bloqueada vira status, nunca truque)

Sobre `registro_de_evidencia`: parte das evidências do gabarito veio de páginas que não
foram salvas em HTML na coleta original — só o trecho verbatim e a URL ficaram
registrados nos JSON do Manus. Esses snapshots existem, mas `meta.json` diz o que são
(`tipo="registro_de_evidencia"`, `origem=...`) para ninguém tratá-los como captura de
página oficial. Sem eles, campos legítimos do gabarito ficariam sem texto para grounding
em replay.

Uso:  python scripts/build_fixtures.py [--check]
      --check apenas confere que o que está no disco bate com o que seria gerado.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "gabarito" / "raw"
DESTINO = ROOT / "tests" / "fixtures" / "snapshots"

#: Data da coleta original registrada no gabarito (`origem: Manus rodada N (2026-09-01)`).
CAPTURED_AT = "2026-09-01"
TS = "2026-09-01T00-00-00Z"
#: Data da coleta ao vivo desta rodada (`scripts/coleta/coletar_faltantes.py`).
COLETA_10SET = "2026-09-10"


def ts_de(captured_at: str) -> str:
    """`2026-09-10` -> `2026-09-10T00-00-00Z`, o nome da pasta de captura."""
    return f"{captured_at}T00-00-00Z"


@dataclass(frozen=True)
class Fonte:
    source_id: str
    arquivo: str | None
    url: str
    tier: int
    tipo: str
    status: str = "consultada"
    formato: str = "page.md"
    origem: str = ""
    nota: str = ""
    gerado: bool = False
    """`arquivo` e relativo a raiz do repo (saida de gerar_pdf), nao a gabarito/raw."""
    captured_at: str = ""
    """Data da captura, quando **nao** e a da coleta original de 2026-09-01.

    A coleta de 10/09/2026 (`scripts/coleta/coletar_faltantes.py`) trouxe a linha da
    Ranger, a tabela do PBE e a FIPE dos cinco. Carimbar tudo com 2026-09-01 poria data
    errada na evidencia, e a data e parte da prova."""


@dataclass(frozen=True)
class VeiculoFixture:
    version_id: str
    descricao: str
    fontes: tuple[Fonte, ...] = field(default_factory=tuple)


FORD_SITE = "https://www.ford.com.br/picapes/ranger-raptor/raptor-4wd-at/"
FORD_PDF = (
    "https://www.ford.com.br/content/dam/Ford/website-assets/latam/br/nameplate/2025/"
    "ranger-raptor/pdf/fbr-ranger-raptor-ficha-tecnica.pdf"
)
FORD_AUTOESPORTE = (
    "https://autoesporte.globo.com/carros/testes-de-carros/review/2024/05/"
    "teste-ford-ranger-raptor-e-piccape-que-acelera-mais-que-muito-esportivo.ghtml"
)
FORD_FIPE = (
    "https://www.tabelafipebrasil.com/carros/FORD/"
    "RANGER-RAPTOR-30-V6-BI-TURBO-4WD-AUT/2026-Gasolina"
)
TOYOTA_SITE = "https://www.toyota.com.br/modelos/hilux-cabine-dupla"
TOYOTA_PDF = "https://media.toyota.com.br/d400f124-b3ac-4d73-a885-5d6828812f11.pdf"
TOYOTA_FIPE_SRX = (
    "https://www.tabelafipebrasil.com/carros/TOYOTA/HILUX-CD-SRX-PLUS-4X4-28-TDI-DIE-AUT"
)
TOYOTA_FIPE_GRS = "https://www.tabelafipebrasil.com/carros/TOYOTA/HILUX-CD-GR-S-4X4-28-TDI-DIES-AUT"
VW_SITE = "https://www.vw.com.br/pt/carros/amarok.html"
VW_AUTOESPORTE = (
    "https://autoesporte.globo.com/setor-automotivo/mercado-automotivo/noticia/2025/08/"
    "volkswagen-amarok-2026-precos-versoes-equipamentos.ghtml"
)
VW_FIPE = (
    "https://www.tabelafipebrasil.com/carros/VW---VOLKSWAGEN/"
    "AMAROK-EXTREME-CD-30-4X4-TB-DIES-AUT/2026-Diesel"
)
GM_SITE = "https://www.chevrolet.com.br/picapes/s10"
GM_AUTOESPORTE = (
    "https://autoesporte.globo.com/setor-automotivo/mercado-automotivo/noticia/2026/07/"
    "chevrolet-s10-2027-precos-versoes-equipamentos-consumo.ghtml"
)
GM_FIPE = (
    "https://www.webmotors.com.br/tabela-fipe/carros/chevrolet/s10/2027/"
    "28-16v-turbo-diesel-high-country-cd-4x4-automatico"
)
GM_IMPRENSA = "https://media.gm.com/brasil"

CNW_RAPTOR = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=46982"
CNW_LIMITED = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=49974"
CNW_S10 = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=47930"
CNW_AMAROK = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=44849"
CNW_HILUX = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=41190"
CNW_CAPTURA = "2026-09-15"

MANUS = "registro verbatim da coleta de 2026-09-01 (execução do Manus seguindo o protocolo)"
COLETA = (
    "coleta ao vivo de 2026-09-10 por scripts/coleta/coletar_faltantes.py "
    "(robots.txt consultado, 1 req/s, user-agent identificado)"
)

# --- as fontes que a coleta de 10/09/2026 trouxe -----------------------------------
FORD_RANGER_COMPARADOR = "https://www.ford.com.br/picapes/ranger/compare-as-versoes.html"
FORD_RANGER_LIMITED = (
    "https://www.ford.com.br/picapes/ranger/compare-as-versoes/limited-30-diesel-4wd-at.html"
)
FORD_RANGER_PDF = (
    "https://www.ford.com.br/content/dam/Ford/website-assets/latam/br/nameplate/2025/"
    "nova-geracao-ranger/pdf/fbr-ranger-ficha-tecnica.pdf"
)
PBE_TABELA = (
    "https://www.gov.br/inmetro/pt-br/assuntos/regulamentacao/avaliacao-da-conformidade/"
    "programa-brasileiro-de-etiquetagem/tabelas-de-eficiencia-energetica/"
    "veiculos-automotivos-pbe-veicular"
)
FIPE_BASE = "https://parallelum.com.br/fipe/api/v1/carros/marcas"
FIPE_RAPTOR_API = f"{FIPE_BASE}/22/modelos/10891/anos/2026-1"
FIPE_HILUX_API = f"{FIPE_BASE}/56/modelos/10926/anos/2026-3"
FIPE_AMAROK_API = f"{FIPE_BASE}/59/modelos/8532/anos/2026-3"
FIPE_S10_API = f"{FIPE_BASE}/23/modelos/7305/anos/2027-3"
FIPE_RANGER_LIMITED_API = f"{FIPE_BASE}/22/modelos/10761/anos/32000-3"


def fonte_pbe() -> Fonte:
    """A tabela do PBE, igual para todos: um documento, uma linha por configuração."""
    return Fonte(
        "pbe_tabela",
        "pbe_tabela_veiculos.md",
        PBE_TABELA,
        2,
        "pbe",
        origem=COLETA,
        captured_at=COLETA_10SET,
        nota="tabela PBEV 2026 (18º ciclo, atualizada em 31/08/2026); uma linha por "
        "configuração publicada, com o consumo urbano e rodoviário medidos",
    )


def fonte_carrosnaweb(slug: str, arquivo: str, url: str) -> Fonte:
    """Ficha tier 3 do CarrosNaWeb — rpm de potência, torque+rpm, marchas, 0-100,
    suspensão, pneus, aro e preço, no mesmo formato para qualquer marca. Capturada ao
    vivo em 2026-09-15 via navegador (o site responde 500 sem um; `robots.txt` permite
    `/fichadetalhe.asp` explicitamente). Nunca cv, que a fonte renderiza como imagem."""
    return Fonte(
        f"carrosnaweb_{slug}",
        arquivo,
        url,
        3,
        "ficha",
        captured_at=CNW_CAPTURA,
        nota="código opaco por versão+ano-modelo; ano-modelo reconfirmado no cabeçalho "
        "pelo conector (pipeline/connectors/carrosnaweb.py); potência em cv vem como imagem",
    )


def fonte_fipe(slug: str, url: str) -> Fonte:
    return Fonte(
        f"fipe_{slug}",
        f"fipe_api_{slug}.md",
        url,
        2,
        "fipe",
        origem=COLETA,
        captured_at=COLETA_10SET,
        nota="resposta da API comunitária da FIPE; o corpo JSON é o texto salvo e a "
        'citação é o par `"Valor":"R$ …"` dentro dele',
    )


VEICULOS: tuple[VeiculoFixture, ...] = (
    VeiculoFixture(
        "ford_ranger_raptor_2026",
        "Ford Ranger Raptor 3.0 V6 Bi-turbo 4WD AT 2026 — referência Ford",
        (
            Fonte(
                "ford_site_versao",
                "ford_raptor_site_versao.md",
                FORD_SITE,
                1,
                "pagina_oficial",
            ),
            Fonte(
                "ford_ficha_tecnica",
                "ford_raptor_ficha_tecnica_oficial.txt",
                FORD_PDF,
                1,
                "pdf_oficial",
                formato="doc.md",
            ),
            Fonte(
                "registro_evidencias_raptor",
                "manus_raptor.json",
                FORD_SITE,
                1,
                "registro_de_evidencia",
                origem=MANUS,
                nota="cobre FIPE, preço e aceleração, cujas páginas não foram salvas em HTML",
            ),
            fonte_fipe("raptor", FIPE_RAPTOR_API),
            Fonte(
                "pbe_tabela",
                None,
                PBE_TABELA,
                2,
                "pbe",
                status="nao_encontrado",
                origem=COLETA,
                captured_at=COLETA_10SET,
                nota="a tabela PBEV 2026 lista 12 configurações da Ranger e nenhuma é a "
                "Raptor (o ciclo só publica as diesel); consumo fica `nao_encontrado`",
            ),
            Fonte(
                "autoesporte_raptor",
                None,
                FORD_AUTOESPORTE,
                3,
                "imprensa",
                status="consultada",
                nota="0-100 medido em 6,5 s; o trecho está no registro de evidências",
            ),
            Fonte("fipe_raptor", None, FORD_FIPE, 2, "fipe", nota="referência 2026-09"),
            fonte_carrosnaweb(
                "ranger_raptor_2026", "carrosnaweb_ranger_raptor_2026.md", CNW_RAPTOR
            ),
        ),
    ),
    VeiculoFixture(
        "toyota_hilux_gr_sport_2026_inexistente",
        "Toyota Hilux GR-Sport — caso negativo do resolvedor (fora da linha 2026)",
        (
            Fonte("toyota_site_cd", "toyota_hilux_site.md", TOYOTA_SITE, 1, "pagina_oficial"),
            Fonte(
                "registro_evidencias_grsport",
                "manus_hilux_gr_sport_negativo.json",
                TOYOTA_SITE,
                1,
                "registro_de_evidencia",
                origem=MANUS,
                nota="linha vigente 2026 e ausência da GR-Sport",
            ),
            Fonte(
                "fipe_grsport",
                None,
                TOYOTA_FIPE_GRS,
                2,
                "fipe",
                nota="histórico; último ano-modelo 2024",
            ),
        ),
    ),
    VeiculoFixture(
        "toyota_hilux_srx_plus_at_2026",
        "Toyota Hilux SRX Plus AT (Cabine Dupla) 2026 — concorrente",
        (
            Fonte(
                "toyota_pdf_my26",
                "toyota_hilux_my26_p6_p7_layout.txt",
                TOYOTA_PDF,
                1,
                "pdf_oficial",
                formato="doc.md",
                nota="páginas 6-7 da lista de equipamentos MY26, com o layout de tabela preservado",
            ),
            Fonte(
                "toyota_pdf_my26_completo",
                "tests/fixtures/pdf/toyota_hilux_my26/doc.md",
                TOYOTA_PDF,
                1,
                "pdf_oficial",
                formato="doc.md",
                gerado=True,
                nota="extracao das 10 paginas pelo pipeline (pipeline/parse/pdf.py, motor "
                "pdfplumber), com layout de tabela preservado. E o doc.md que a coleta real "
                "produz; a fonte parcial ao lado cobre so as paginas 6-7.",
            ),
            Fonte("toyota_site_cd", "toyota_hilux_site.md", TOYOTA_SITE, 1, "pagina_oficial"),
            Fonte(
                "fipe_srx_plus",
                None,
                TOYOTA_FIPE_SRX,
                2,
                "fipe",
                status="pendente_coleta",
                nota="preço e FIPE seguem pendentes no gabarito v1",
            ),
            fonte_fipe("hilux_srx_plus", FIPE_HILUX_API),
            fonte_pbe(),
            fonte_carrosnaweb(
                "hilux_srx_plus_2026", "carrosnaweb_hilux_srx_plus_2026.md", CNW_HILUX
            ),
        ),
    ),
    VeiculoFixture(
        "vw_amarok_v6_extreme_2026",
        "Volkswagen Amarok V6 Extreme 2026 — concorrente",
        (
            Fonte("vw_site", "vw_amarok.md", VW_SITE, 1, "pagina_oficial"),
            Fonte(
                "autoesporte_amarok",
                "autoesporte_amarok_2026.md",
                VW_AUTOESPORTE,
                3,
                "imprensa",
            ),
            Fonte("fipe_amarok", "fipe_amarok_extreme_2026.md", VW_FIPE, 2, "fipe"),
            fonte_fipe("amarok_extreme", FIPE_AMAROK_API),
            fonte_pbe(),
            Fonte(
                "registro_evidencias_amarok",
                "manus_amarok_v6_extreme.json",
                VW_SITE,
                1,
                "registro_de_evidencia",
                origem=MANUS,
            ),
            fonte_carrosnaweb(
                "amarok_v6_extreme_2026", "carrosnaweb_amarok_v6_extreme_2026.md", CNW_AMAROK
            ),
        ),
    ),
    VeiculoFixture(
        "chevrolet_s10_high_country_2027",
        "Chevrolet S10 High Country 2027 — concorrente",
        (
            Fonte("chevrolet_site", "chevrolet_s10_site.md", GM_SITE, 1, "pagina_oficial"),
            Fonte(
                "registro_evidencias_s10",
                "manus_s10_high_country.json",
                GM_SITE,
                1,
                "registro_de_evidencia",
                origem=MANUS,
            ),
            Fonte("autoesporte_s10", None, GM_AUTOESPORTE, 3, "imprensa"),
            Fonte("fipe_s10", None, GM_FIPE, 2, "fipe"),
            fonte_fipe("s10_high_country", FIPE_S10_API),
            fonte_pbe(),
            Fonte(
                "gm_imprensa",
                None,
                GM_IMPRENSA,
                1,
                "sala_de_imprensa",
                status="bloqueada",
                nota="CAPTCHA na sala de imprensa da GM; fonte bloqueada vira status, "
                "nunca tentativa de burlar (docs/12 §3.12)",
            ),
            fonte_carrosnaweb(
                "s10_high_country_2027", "carrosnaweb_s10_high_country_2027.md", CNW_S10
            ),
        ),
    ),
    VeiculoFixture(
        "ford_ranger_limited_2027",
        "Ford Ranger Limited 3.0 V6 Diesel 4WD AT 2027 — Ford diesel de topo "
        "(coleta de 2026-09-10; escolha automática pela maior a partir de, confirmar)",
        (
            Fonte(
                "ford_site_linha",
                "ford_ranger_linha_comparador.md",
                FORD_RANGER_COMPARADOR,
                1,
                "pagina_oficial",
                origem=COLETA,
                captured_at=COLETA_10SET,
                nota="a raiz do modelo não publica a linha em HTML (monta por JavaScript) "
                "e responde 403 ao navegador headless; esta é a rota irmã do mesmo site "
                "oficial, que publica as 12 versões com o 'a partir de'",
            ),
            Fonte(
                "ford_site_versao",
                "ford_ranger_limited_site_versao.md",
                FORD_RANGER_LIMITED,
                1,
                "pagina_oficial",
                origem=COLETA,
                captured_at=COLETA_10SET,
            ),
            Fonte(
                "ford_ficha_tecnica",
                "ford_ranger_ficha_tecnica_oficial.txt",
                FORD_RANGER_PDF,
                1,
                "pdf_oficial",
                formato="doc.md",
                origem=COLETA,
                captured_at=COLETA_10SET,
                nota="a página de especificações deste PDF é **imagem**: o texto extraível "
                "é o folheto de serviços. As especificações vêm da página da versão — a "
                "fonte foi consultada e o que ela dá está dito",
            ),
            fonte_fipe("ranger_limited", FIPE_RANGER_LIMITED_API),
            fonte_pbe(),
            fonte_carrosnaweb(
                "ranger_limited_2027", "carrosnaweb_ranger_limited_2027.md", CNW_LIMITED
            ),
        ),
    ),
)


# ---------------------------------------------------------------------- linha vigente
#
# O resolvedor (WP-07) precisa da linha vigente por marca+modelo. Em replay ele lê
# `tests/fixtures/lineups/<marca>/<modelo>/lineup.md`, gerado aqui.
#
# Cada entrada abaixo é **derivada** de uma fonte salva em `gabarito/raw/`, e o cabeçalho
# do arquivo diz de qual. Nada é inventado: onde a coleta original não capturou a linha
# completa, o arquivo registra isso explicitamente em vez de completar com suposição — é
# exatamente o caso da Ranger, cuja linha só tem a Raptor porque a página salva é a da
# versão, não a do modelo.
DESTINO_LINEUPS = ROOT / "tests" / "fixtures" / "lineups"


@dataclass(frozen=True)
class VersaoLinha:
    nome_exato: str
    ano_modelo: int
    preco_a_partir_brl: int | None = None
    url: str = ""


@dataclass(frozen=True)
class Linha:
    marca: str
    modelo: str
    url: str
    derivado_de: str
    versoes: tuple[VersaoLinha, ...]
    nota: str = ""
    captured_at: str = ""
    """Data da coleta desta linha, quando não é a original de 2026-09-01."""


LINHAS: tuple[Linha, ...] = (
    Linha(
        "Ford",
        "Ranger",
        FORD_RANGER_COMPARADOR,
        "gabarito/raw/ford_ranger_linha_comparador.md (coleta de 2026-09-10) + "
        "gabarito/raw/ford_raptor_site_versao.md (a Raptor, da coleta de 2026-09-01)",
        (
            VersaoLinha("Raptor 3.0 V6 Bi-turbo 4WD AT", 2026, 499000, FORD_SITE),
            VersaoLinha("Limited 3.0 V6 Diesel 4WD AT", 2027, 346900, FORD_RANGER_COMPARADOR),
            VersaoLinha("XLT 3.0 V6 Diesel 4WD AT", 2027, 315900, FORD_RANGER_COMPARADOR),
            VersaoLinha("XLS 3.0 V6 Diesel 4WD AT", 2027, 309600, FORD_RANGER_COMPARADOR),
            VersaoLinha("XLS 2.0 Diesel 4x4 AT", 2027, 285900, FORD_RANGER_COMPARADOR),
            VersaoLinha("XL 2.0 CD Diesel 4x4 AT", 2027, 282600, FORD_RANGER_COMPARADOR),
            VersaoLinha("XL 2.0 CD Diesel 4x4 MT", 2026, 272600, FORD_RANGER_COMPARADOR),
            VersaoLinha("XL 2.0 CS Diesel 4x4 AT", 2027, 266600, FORD_RANGER_COMPARADOR),
            VersaoLinha("XL 2.0 CH Diesel 4x4 AT", 2027, 258600, FORD_RANGER_COMPARADOR),
            VersaoLinha("XL 2.0 CS Diesel 4x4 MT", 2027, 256600, FORD_RANGER_COMPARADOR),
            VersaoLinha("XL 2.0 CH Diesel 4x4 MT", 2027, 248600, FORD_RANGER_COMPARADOR),
            VersaoLinha("Black 2.0L 4x2 AT Diesel", 2027, 242600, FORD_RANGER_COMPARADOR),
        ),
        captured_at=COLETA_10SET,
        nota="A Raptor vem da coleta de 2026-09-01 (a página da VERSÃO); as demais vêm "
        "do comparador de versões coletado em 2026-09-10, que publica o 'a partir de' "
        "de cada uma. A Raptor não aparece no comparador porque tem página de modelo "
        "própria (ranger-raptor), e é por isso que as duas datas convivem nesta linha.",
    ),
    Linha(
        "Toyota",
        "Hilux",
        TOYOTA_SITE,
        'gabarito/raw/toyota_hilux_site.md (bloco "Conheça as versões", linhas 19-23)',
        (
            VersaoLinha("STD Power Pack AT", 2026, None, TOYOTA_SITE),
            VersaoLinha("SR AT", 2026, None, TOYOTA_SITE),
            VersaoLinha("SRV AT", 2026, None, TOYOTA_SITE),
            VersaoLinha("SRX AT", 2026, None, TOYOTA_SITE),
            VersaoLinha("SRX Plus AT", 2026, None, TOYOTA_SITE),
        ),
        nota="A Hilux GR-Sport NÃO está nesta linha — é o caso negativo do resolvedor. "
        "Preços não constam na página salva (status pendente_coleta no gabarito v1).",
    ),
    Linha(
        "Volkswagen",
        "Amarok",
        VW_SITE,
        "gabarito/raw/manus_amarok_v6_extreme.json (campo linha_vigente; preços com "
        "fonte na Autoesporte)",
        (
            VersaoLinha("V6 Comfortline", 2026, 339990, VW_SITE),
            VersaoLinha("V6 Highline", 2026, 356990, VW_SITE),
            VersaoLinha("V6 Extreme", 2026, 379990, VW_SITE),
        ),
    ),
    Linha(
        "Chevrolet",
        "S10",
        GM_SITE,
        "gabarito/raw/manus_s10_high_country.json (campo linha_vigente)",
        (
            VersaoLinha("S10 CABINE SIMPLES", 2027, 265690, GM_SITE),
            VersaoLinha("S10 WT MT", 2027, 285890, GM_SITE),
            VersaoLinha("S10 WT AT", 2027, 304590, GM_SITE),
            VersaoLinha("S10 Z71", 2027, 325290, GM_SITE),
            VersaoLinha("S10 LTZ", 2027, 333690, GM_SITE),
            VersaoLinha("Trail Boss", 2027, 341290, GM_SITE),
            VersaoLinha("S10 High Country", 2027, 348790, GM_SITE),
        ),
    ),
)


def slug(texto: str) -> str:
    return texto.lower().replace(" ", "-")


def _lineup_md(linha: Linha) -> str:
    partes = [
        f"# Linha vigente — {linha.marca} {linha.modelo}",
        "",
        f"**URL:** {linha.url}",
        f"**Coletado em:** {linha.captured_at or CAPTURED_AT}",
        f"**Derivado de:** {linha.derivado_de}",
        "**Gerado por:** scripts/build_fixtures.py",
    ]
    if linha.nota:
        partes += ["", f"> **Atenção:** {linha.nota}"]
    partes += [
        "",
        "| nome_exato | ano_modelo | preco_a_partir_brl | url |",
        "|---|---|---|---|",
    ]
    for v in linha.versoes:
        preco = "" if v.preco_a_partir_brl is None else str(v.preco_a_partir_brl)
        partes.append(f"| {v.nome_exato} | {v.ano_modelo} | {preco} | {v.url} |")
    partes.append("")
    return "\n".join(partes)


def gerar_lineups(destino: Path = DESTINO_LINEUPS) -> list[Path]:
    criados: list[Path] = []
    for linha in LINHAS:
        pasta = destino / slug(linha.marca) / slug(linha.modelo)
        pasta.mkdir(parents=True, exist_ok=True)
        alvo = pasta / "lineup.md"
        texto = _lineup_md(linha)
        alvo.write_text(texto, encoding="utf-8", newline="\n")
        meta = {
            "marca": linha.marca,
            "modelo": linha.modelo,
            "url_final": linha.url,
            "tier": 1,
            "tipo": "linha_vigente",
            "status": "consultada",
            "captured_at": linha.captured_at or CAPTURED_AT,
            "text_path": "lineup.md",
            "sha256": sha256(texto.encode("utf-8")),
            "derivado_de": linha.derivado_de,
            "gerado_por": "scripts/build_fixtures.py",
            "versoes": len(linha.versoes),
        }
        if linha.nota:
            meta["nota"] = linha.nota
        (pasta / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        criados.extend([alvo, pasta / "meta.json"])
    return criados


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


# ------------------------------------------------------------------ fixtures de PDF
#
# `specs/WP-09.md`: "No CI, use fixtures doc.md/tables.json ja gerados (commit em
# tests/fixtures)". Gerar aqui, e nao no teste, tem duas consequencias boas: o CI nao
# precisa do extra `pdf` nem baixa modelo do Docling, e a extracao fica auditavel — o
# `meta.json` registra o motor usado e o sha256 do PDF de origem, entao trocar o PDF sem
# regerar vira `--check` vermelho em vez de fixture velha passando por nova.
DESTINO_PDF = ROOT / "tests" / "fixtures" / "pdf"

PDFS: tuple[tuple[str, str], ...] = (("toyota_hilux_my26", "toyota_hilux_my26_ficha_oficial.pdf"),)


def gerar_pdf(destino: Path = DESTINO_PDF) -> list[Path]:
    """Extrai `doc.md` + `tables.json` dos PDFs de `gabarito/raw/`."""
    from pipeline.parse.pdf import parse_pdf

    criados: list[Path] = []
    for nome, arquivo in PDFS:
        origem = RAW / arquivo
        if not origem.exists():
            raise SystemExit(f"gabarito/raw/{arquivo} nao existe")
        dados = origem.read_bytes()
        documento = parse_pdf(dados)
        pasta = destino / nome
        pasta.mkdir(parents=True, exist_ok=True)

        doc_md = pasta / "doc.md"
        doc_md.write_text(documento.markdown, encoding="utf-8", newline="\n")
        tables = pasta / "tables.json"
        tables.write_text(documento.tables_json() + "\n", encoding="utf-8", newline="\n")
        (pasta / "meta.json").write_text(
            json.dumps(
                {
                    "nome": nome,
                    "arquivo_de_origem": f"gabarito/raw/{arquivo}",
                    "sha256_do_pdf": sha256(dados),
                    "motor": documento.motor,
                    "paginas": documento.n_paginas,
                    "tabelas": len(documento.tabelas),
                    "gerado_por": "scripts/build_fixtures.py",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        criados.extend([doc_md, tables, pasta / "meta.json"])
    return criados


def conferir_pdf(destino: Path = DESTINO_PDF) -> list[str]:
    """Confere existencia e sha256 do PDF de origem, sem reextrair.

    Nao reextrai de proposito: `--check` roda no CI, que nao tem o extra `pdf`. O que
    importa conferir e que a fixture corresponde ao **mesmo** PDF.
    """
    problemas: list[str] = []
    for nome, arquivo in PDFS:
        pasta = destino / nome
        for esperado in ("doc.md", "tables.json", "meta.json"):
            if not (pasta / esperado).exists():
                problemas.append(f"FALTANDO   {(pasta / esperado).relative_to(ROOT)}")
        meta_json = pasta / "meta.json"
        if not meta_json.exists():
            continue
        meta = json.loads(meta_json.read_text(encoding="utf-8"))
        atual = sha256((RAW / arquivo).read_bytes())
        if meta.get("sha256_do_pdf") != atual:
            problemas.append(
                f"DIVERGENTE {(pasta / 'doc.md').relative_to(ROOT)} "
                f"(o PDF de origem mudou; rode o gerador com o extra `pdf` instalado)"
            )
    return problemas


def gerar(destino: Path = DESTINO) -> list[Path]:
    """Escreve as fixtures e devolve os caminhos criados."""
    if destino.exists():
        for filho in destino.iterdir():
            if filho.name == ".gitkeep":
                continue
            shutil.rmtree(filho) if filho.is_dir() else filho.unlink()
    destino.mkdir(parents=True, exist_ok=True)
    (destino / ".gitkeep").touch()

    criados: list[Path] = []
    for veiculo in VEICULOS:
        base = destino / veiculo.version_id
        base.mkdir(parents=True, exist_ok=True)
        fontes_meta = []
        for fonte in veiculo.fontes:
            registro = {
                "source_id": fonte.source_id,
                "url": fonte.url,
                "tier": fonte.tier,
                "tipo": fonte.tipo,
                "status": fonte.status,
                "tem_texto_salvo": fonte.arquivo is not None,
            }
            if fonte.nota:
                registro["nota"] = fonte.nota
            if fonte.origem:
                registro["origem"] = fonte.origem
            fontes_meta.append(registro)

            if fonte.arquivo is None:
                continue
            origem_arquivo = (ROOT if fonte.gerado else RAW) / fonte.arquivo
            if not origem_arquivo.exists():
                raise SystemExit(f"{fonte.arquivo} não existe")
            texto = origem_arquivo.read_text(encoding="utf-8", errors="replace")
            capturado = fonte.captured_at or CAPTURED_AT
            pasta = base / ts_de(capturado) / fonte.source_id
            pasta.mkdir(parents=True, exist_ok=True)
            alvo = pasta / fonte.formato
            alvo.write_text(texto, encoding="utf-8", newline="\n")
            meta = {
                "source_id": fonte.source_id,
                "version_id": veiculo.version_id,
                "url_final": fonte.url,
                "http_status": 200,
                "tier": fonte.tier,
                "tipo": fonte.tipo,
                "status": fonte.status,
                "captured_at": capturado,
                "text_path": fonte.formato,
                "sha256": sha256(texto.encode("utf-8")),
                "bytes": len(texto.encode("utf-8")),
                "arquivo_de_origem": (
                    fonte.arquivo if fonte.gerado else f"gabarito/raw/{fonte.arquivo}"
                ),
                "gerado_por": "scripts/build_fixtures.py",
            }
            if fonte.origem:
                meta["origem"] = fonte.origem
            if fonte.nota:
                meta["nota"] = fonte.nota
            (pasta / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            criados.extend([alvo, pasta / "meta.json"])

        arquivo_fontes = base / "fontes.json"
        arquivo_fontes.write_text(
            json.dumps(
                {
                    "version_id": veiculo.version_id,
                    "descricao": veiculo.descricao,
                    "captured_at": CAPTURED_AT,
                    "fontes": fontes_meta,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        criados.append(arquivo_fontes)
    return criados


def conferir(destino: Path = DESTINO) -> int:
    """Confere que o disco bate com o que o gerador produziria."""
    faltando: list[str] = []
    divergente: list[str] = []
    for veiculo in VEICULOS:
        base = destino / veiculo.version_id
        if not (base / "fontes.json").exists():
            faltando.append(str((base / "fontes.json").relative_to(ROOT)))
        for fonte in veiculo.fontes:
            if fonte.arquivo is None:
                continue
            alvo = base / ts_de(fonte.captured_at or CAPTURED_AT) / fonte.source_id / fonte.formato
            if not alvo.exists():
                faltando.append(str(alvo.relative_to(ROOT)))
                continue
            esperado = ((ROOT if fonte.gerado else RAW) / fonte.arquivo).read_text(
                encoding="utf-8", errors="replace"
            )
            if alvo.read_text(encoding="utf-8") != esperado:
                divergente.append(str(alvo.relative_to(ROOT)))
    for linha in LINHAS:
        pasta = DESTINO_LINEUPS / slug(linha.marca) / slug(linha.modelo)
        alvo = pasta / "lineup.md"
        if not alvo.exists():
            faltando.append(str(alvo.relative_to(ROOT)))
        elif alvo.read_text(encoding="utf-8") != _lineup_md(linha):
            divergente.append(str(alvo.relative_to(ROOT)))

    for problema in conferir_pdf():
        (divergente if problema.startswith("DIVERGENTE") else faltando).append(problema)

    for caminho in faltando:
        print(
            caminho if caminho.startswith(("FALTANDO", "DIVERGENTE")) else f"FALTANDO   {caminho}"
        )
    for caminho in divergente:
        print(caminho if caminho.startswith("DIVERGENTE") else f"DIVERGENTE {caminho}")
    if faltando or divergente:
        print("\nrode: python scripts/build_fixtures.py")
        return 1
    print("fixtures conferem com gabarito/raw/")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true", help="apenas confere, não escreve")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    if args.check:
        return conferir()
    criados = gerar_pdf() + gerar() + gerar_lineups()
    print(f"{len(criados)} arquivos em tests/fixtures/ (snapshots + lineups + pdf)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
