"""Pesquisa por lacunas com documentos originais e leitura retomável.

O laço descobre fontes, coleta originais e entrega somente texto/células ao extrator.
Snippets de busca não são evidência. PDFs preservam bytes, páginas, geometria e
estados parciais; o texto decodificado de um binário nunca é reconstruído como PDF.

O Leitor mantém candidatos e progresso por documento/configuração/política/bloco.
Cada passagem respeita a cota de chamadas; uma continuação visita blocos pendentes,
sem repetir respostas concluídas. Falha de modelo conserva a passagem para retry.
Grounding, identidade, normalização e reconciliação continuam sendo os portões de
publicação. Ler mais texto não comprova ano-modelo ou equipamento opcional.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import structlog

from pipeline import deadline
from pipeline.extract.run import Candidato, Documento
from pipeline.research import classify, gaps, planner, service_budget
from pipeline.research import search as busca
from pipeline.research.discovery import document_links, url_key
from pipeline.research.events import Evento, Tipo, Trilha
from pipeline.research.reading_state import EstadoLeitura, digest
from pipeline.schema import StandardSpec, empty_spec

log = structlog.get_logger(__name__)

#: Quantas páginas uma rodada pode baixar.
#:
#: O funil do Perplexica é o mesmo: busca barata em muitos, leitura cara em poucos. Com
#: doze páginas de orçamento total e duas rodadas, seis por rodada deixa a segunda com
#: fôlego para as lacunas — que é onde ela rende mais.
PAGINAS_POR_RODADA = 6

#: Tier acima do qual não se gasta página.
#:
#: Tier 5 é "não reconhecido". Baixar um domínio desconhecido custaria uma das doze páginas
#: para, na melhor hipótese, achar um número sem autoridade para sustentá-lo.
TIER_MAXIMO_PARA_COLETA = 3


@dataclass
class Fonte:
    """Uma página que o Pesquisador decidiu ler, e o que saiu dela."""

    url: str
    tier: int
    motivo: str
    consulta: str
    texto: str = ""
    captured_at: str = ""
    baixada: bool = False
    bloqueada: bool = False
    erro: str = ""
    sha256: str = ""
    """Hash do texto salvo, como o `fetch` o calculou. É o que a tabela `snapshots` guarda
    para alguém reconferir depois que a página mudou."""
    http_status: int | None = None
    tipo: str = "desconhecido"
    """Tipo concreto consumido pelos conectores: página/PDF oficial, FIPE, PBE etc."""
    e_pdf: bool = False
    documento_pdf: Any = None
    raw_path: str = ""
    creditos: float = 0.0
    links: list[tuple[str, str]] = field(default_factory=list)
    sha256_binario: str = ""
    mime_type: str = ""
    fetch_ok: bool = False
    parse_status: str = ""

    @property
    def source_id(self) -> str:
        """Um id estável para o grounding casar texto com evidência.

        Determinístico de propósito: `hash()` do Python varia entre processos, e um
        `source_id` que muda a cada execução faria o grounding procurar o texto de uma
        fonte que, para ele, é outra.
        """
        import hashlib

        dominio = classify.dominio_de(self.url).replace(".", "_")
        digest = hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:8]
        return f"{dominio}:{digest}"


@dataclass
class Resultado:
    """O que uma pesquisa produziu: a ficha, a trilha e a conta."""

    marca: str
    modelo: str
    versao: str
    spec: StandardSpec
    trilha: Trilha
    cobertura: gaps.Cobertura
    orcamento: gaps.Orcamento
    motivo_da_parada: gaps.Motivo
    fontes: list[Fonte] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    observacoes: list[dict] = field(default_factory=list)
    lacunas: list[dict] = field(default_factory=list)
    medicao: Any = None
    """O `llm.Medicao` da pesquisa inteira: chamadas, tokens, custo. `None` só se o laço
    não chegou a rodar."""
    servicos: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "veiculo": f"{self.marca} {self.modelo} {self.versao}".strip(),
            "cobertura": self.cobertura.to_dict(),
            "orcamento": self.orcamento.to_dict(),
            "motivo_da_parada": self.motivo_da_parada.value,
            "explicacao": gaps.explicar(self.motivo_da_parada, self.cobertura, self.orcamento),
            "fontes": [
                {
                    "url": f.url,
                    "tier": f.tier,
                    "tipo": f.tipo,
                    "motivo": f.motivo,
                    "baixada": f.baixada,
                    "bloqueada": f.bloqueada,
                    "original_preservado": bool(f.raw_path),
                    "parse_status": f.parse_status,
                    "paginas_pendentes": [
                        {"pagina": d["pagina"], "status": d.get("status", "")}
                        for d in getattr(f.documento_pdf, "diagnosticos", [])
                        if d.get("status") not in {"complete", "empty"}
                    ],
                }
                for f in self.fontes
            ],
            "eventos": self.trilha.to_list(),
            "avisos": self.avisos,
            "lacunas": self.lacunas,
            "medicao": self.medicao.to_dict() if self.medicao is not None else None,
            "servicos": self.servicos,
        }


#: Teto de tempo por página, e **uma** tentativa.
#:
#: Medido ao vivo em 13/09/2026: com os padrões do `fetch` (30 s de timeout e três
#: tentativas), uma página levava até **55 s**, e a pesquisa do Amarok terminou em 334 s
#: com teto de 150. A conta que importa: 12 páginas em 3 minutos dão **15 s por página**.
#:
#: Retentativa é política de coleta noturna, onde ninguém espera. Aqui há alguém olhando a
#: tela com o cliente ao lado, e uma página que não respondeu em 20 s não vai responder em
#: 90 — ela vai só consumir o orçamento das outras onze.
TIMEOUT_DA_PAGINA_S = 20.0
TENTATIVAS_POR_PAGINA = 1

#: Teto de texto por página, em caracteres.
#:
#: Medido ao vivo em 13/09/2026: as 18 páginas de uma rodada somaram **141,7 MB** — média
#: de 7,9 MB cada, e a maior com 19,4 MB. Não eram fichas técnicas: eram manuais de
#: proprietário de 400 páginas, de domínio oficial.
#:
#: O classificador passou a barrar os caminhos de manual, e este teto é a segunda linha de
#: defesa para o que escapar. Uma ficha técnica tem dezenas de KB; 2 milhões de caracteres
#: são cerca de 500 páginas de texto, e ler isso gasta o orçamento sem render campo.
#:
#: **O documento não é truncado: é descartado, com o motivo.** Cortar um PDF ao meio daria
#: uma ficha montada sobre meia fonte, sem ninguém saber qual metade.
TETO_DE_TEXTO = 2_000_000

#: Abaixo disto, a página não tem ficha técnica nenhuma — e não conta como lida.
#:
#: Medido ao vivo em 13/09/2026: `webmotors.com.br` devolveu **1 caractere** e
#: `carrosnaweb.com.br`, **zero** — e as duas entraram na trilha como "baixada", inflando o
#: contador de páginas lidas da tela. Uma página que não trouxe texto é uma porta que não
#: abriu; chamá-la de lida é a mesma classe de erro que chamar 34 respostas 429 de "34
#: chamadas com custo zero".
MINIMO_DE_TEXTO_APROVEITAVEL = 200

#: Abaixo disto no relógio, escalar só faria a pesquisa parar por tempo sem
#: terminar a página. O navegador leva de 2 a 5 s por página, e o arquivo mais.
SEGUNDOS_PARA_ESCALAR = 45.0

#: Blocos de um documento que vão ao modelo **na pesquisa**: um.
#:
#: Cada chamada sai de uma cota de quatro por pesquisa (`Orcamento.chamadas_llm`). Um
#: documento de cinco blocos que virasse cinco chamadas gastaria a cota inteira numa página
#: só — e o bloco escolhido é o que mais fala dos campos que faltam, não o primeiro.
BLOCOS_AO_MODELO_NA_PESQUISA = 1


@dataclass
class Coleta:
    """O que `_coletar` devolve de uma página. Vazio com `erro` quando não deu."""

    texto: str = ""
    captured_at: str = ""
    erro: str = ""
    sha256: str = ""
    http_status: int | None = None
    via: str = "http"
    documento_pdf: Any = None
    raw_path: str = ""
    creditos: float = 0.0
    links: list[tuple[str, str]] = field(default_factory=list)
    """Qual degrau trouxe o texto: `http`, `navegador` ou `arquivo`. Vai para a trilha:
    quem lê precisa saber que a página veio do Internet Archive, e de quando."""
    sha256_binario: str = ""
    mime_type: str = ""
    fetch_ok: bool = False
    parse_status: str = ""


def _coletar(url: str, **kwargs) -> Coleta:
    try:
        with deadline.budget(75 if ".pdf" in url.lower() else 35):
            result = _coletar_fonte(url, **kwargs)
            if not result.links and not result.documento_pdf:
                result.links = document_links(result.texto, url)
            return result
    except TimeoutError:
        return Coleta(erro="limite de tempo na coleta")


def _coletar_fonte(
    url: str,
    *,
    tier: int = 3,
    navegador: bool = False,
    ano: int | None = None,
    escalar: bool = True,
) -> Coleta:
    """Baixa uma página, escalando quando a porta da frente está fechada.

    **Não reimplementa nada**: robots.txt, 1 req/s por domínio, user-agent identificado e
    a cópia com hash são do `pipeline/fetch/http.py`, e é lá que devem continuar. Bloqueio
    continua virando estado (`fonte_bloqueada`), nunca um truque — ADR-7. Escalar não é
    burlar: é usar um navegador de verdade, que executa o JavaScript da própria página, e
    depois a cópia pública que o Internet Archive já guardou.

    Três degraus, nesta ordem:

    1. **`http.fetch`** — o caminho normal, e o único em replay;
    2. **navegador** (Crawl4AI + Chromium) quando a resposta veio bloqueada **ou sem texto
       aproveitável**. O segundo caso é o `icarros.com.br/catalogo`: 348 k de HTML e 3 k de
       texto, porque a ficha é montada por JavaScript. Site marcado `navegador: true` em
       `fontes.yaml` pula o degrau 1, que só gastaria relógio;
    3. **Internet Archive**, e **só para tier 1**. Para uma ficha de terceiro há outra
       página na fila; para a montadora, não há substituto. A data que fica é a da
       **captura**, não a de hoje — a evidência diz quando aquilo foi verdade.

    Em `REPLAY_MODE=1` nada escala: o replay resolve por snapshot em disco, e ir à rede
    faria o teste passar por motivo errado.
    """
    from pipeline import snapshots
    from pipeline.fetch import http

    em_replay = http.modo_replay()

    def com_texto(texto: str, captured_at: str, http_status, via: str, raw: str = "") -> Coleta:
        return Coleta(
            texto=texto,
            captured_at=captured_at,
            # O hash é do texto que o extrator leu e a evidência aponta — não do HTML cru.
            sha256=snapshots.sha256_de(texto) if texto else "",
            http_status=http_status,
            via=via,
            links=document_links(raw or texto, url),
        )

    from pipeline.research.extract_service import collect

    service = collect(url)
    if service is not None:
        return service

    bloqueada = True
    http_status = None
    if not (navegador and not em_replay):
        try:
            resultado = http.fetch(
                url, timeout=TIMEOUT_DA_PAGINA_S, tentativas=TENTATIVAS_POR_PAGINA
            )
        except Exception as exc:
            return Coleta(erro=f"{type(exc).__name__}: {exc}"[:200])

        http_status = getattr(resultado, "http_status", None)
        bloqueada = getattr(resultado, "bloqueada", False) or resultado.status == "blocked"
        if not bloqueada:
            raw = getattr(resultado, "conteudo", b"") or b""
            headers = getattr(resultado, "headers", {}) or {}
            mime_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            # Fixtures de replay podem conter somente o Markdown já convertido.
            # Isso é texto de evidência, nunca bytes originais reconstruídos.
            if em_replay and not raw and not (resultado.texto or "").startswith("%PDF"):
                return com_texto(
                    resultado.texto or "",
                    getattr(resultado, "captured_at", "") or "",
                    http_status,
                    "replay",
                )
            raw_path, binary_hash = "", ""
            if raw.startswith(b"%PDF") and not em_replay:
                from pipeline.research.documents import preservar_pdf

                try:
                    raw_path, binary_hash = preservar_pdf(raw)
                except (OSError, ValueError) as exc:
                    return Coleta(
                        erro=f"original PDF não preservado: {exc}",
                        http_status=http_status,
                        fetch_ok=True,
                        parse_status="not_parsed",
                    )
            texto = _texto_da_pagina(url, resultado.texto or "", raw, mime_type=mime_type)
            if isinstance(texto, Coleta):  # PDF ilegível: o motivo já veio pronto
                texto.http_status = http_status
                texto.captured_at = getattr(resultado, "captured_at", "") or ""
                texto.sha256 = snapshots.sha256_de(texto.texto) if texto.texto else ""
                texto.raw_path = raw_path
                texto.sha256_binario = binary_hash or getattr(resultado, "sha256_binario", "")
                texto.mime_type = mime_type or ("application/pdf" if raw else "")
                texto.fetch_ok = bool(getattr(resultado, "ok", False))
                return texto
            if len(texto) >= MINIMO_DE_TEXTO_APROVEITAVEL:
                return com_texto(
                    texto,
                    getattr(resultado, "captured_at", "") or "",
                    http_status,
                    "http",
                    resultado.texto or "",
                )
            # Respondeu, mas veio o esqueleto: o degrau 2 existe exatamente para isto.

    if em_replay or not escalar:
        return Coleta(
            erro="bloqueada" if bloqueada else "página sem texto aproveitável",
            http_status=http_status,
        )

    do_navegador = _pelo_navegador(url)
    if do_navegador is not None:
        return com_texto(do_navegador[0], do_navegador[1], do_navegador[2], "navegador")

    if int(tier) == 1:
        do_arquivo = _pelo_arquivo(url, ano=ano)
        if do_arquivo is not None:
            return do_arquivo

    return Coleta(erro="bloqueada", http_status=http_status)


def _texto_da_pagina(url: str, texto: str, conteudo: bytes, *, mime_type: str = "") -> str | Coleta:
    """O texto que o extrator lê: PDF pelo leitor de PDF, HTML convertido, resto como veio."""
    from pipeline.parse.html import decodificar_html, html_para_texto, meta_charset, parece_html

    conteudo = conteudo or b""
    e_pdf = (
        url.lower().split("?")[0].endswith(".pdf")
        or conteudo[:5] == b"%PDF-"
        or texto[:5] == "%PDF-"
        or mime_type == "application/pdf"
    )
    if e_pdf:
        # **PDF é lido pelo leitor de PDF, nunca decodificado como texto.** Até 13/09/2026
        # o Pesquisador entregava os bytes do PDF como se fossem página, e o extrator
        # procurava número em lixo binário. Sem leitor instalado, a página é descartada
        # com o motivo — melhor que uma ficha montada sobre ruído.
        from pipeline.parse.pdf import parse_pdf

        if not conteudo:
            return Coleta(
                erro="PDF sem bytes originais; texto decodificado não é um arquivo",
                parse_status="missing_original",
            )
        try:
            data = conteudo
            if deadline.remaining() is None:
                documento = parse_pdf(data)
            else:
                from pipeline.parse.pdf import DocumentoPdf
                from pipeline.research.reprocess import _executar

                # O parser cria workers OCR/layout: expirar somente o processo pai
                # deixa inferências órfãs. A retomada já encerra a árvore inteira.
                documento = DocumentoPdf.from_dict(_executar(data, None, deadline.timeout(60)))
        except Exception as exc:
            return Coleta(
                erro=f"PDF ilegível ou sem leitor: {type(exc).__name__}: {exc}"[:200],
                parse_status="failed",
            )
        return Coleta(
            texto=documento.texto_para_extracao(),
            documento_pdf=documento,
            parse_status=getattr(documento, "status", "complete"),
            erro="" if documento.texto_para_extracao().strip() else "PDF com leitura pendente",
        )
    if parece_html(texto):
        # A página da rede vem em HTML cru; o extrator e o grounding leem **texto**. Em
        # replay o `fetch` já devolve o markdown salvo, e nada muda.
        #
        # Charset mal detectado, corrigido aqui: o `carrosnaweb` é windows-1252 e não
        # declara isso no cabeçalho HTTP; sem isto o `httpx`/upstream decodifica como
        # utf-8 com substituição, o acento vira "�" e o `evidence_quote` verbatim deixa
        # de casar no texto salvo — o grounding falha em silêncio.
        charset = meta_charset(conteudo)
        if conteudo and ("�" in texto or (charset and charset.lower() not in ("utf-8", "utf8"))):
            texto = decodificar_html(conteudo, declarado=mime_type)
        return html_para_texto(texto)
    return texto


def _pelo_navegador(url: str) -> tuple[str, str, int | None] | None:
    """`(texto, captured_at, http_status)` do Chromium, ou `None` quando não deu."""
    from datetime import UTC, datetime

    from pipeline.fetch import browser

    if not browser.disponivel():
        return None
    try:
        resposta = browser.fetch_browser(url, screenshot=False)
    except Exception as exc:
        log.warning("research.navegador_falhou", url=url, erro=str(exc)[:200])
        return None
    texto = (resposta.markdown or "").strip()
    if not texto and resposta.html:
        convertido = _texto_da_pagina(url, resposta.html, b"")
        texto = convertido if isinstance(convertido, str) else ""
    if len(texto) < MINIMO_DE_TEXTO_APROVEITAVEL:
        return None
    return texto, datetime.now(UTC).strftime("%Y-%m-%d"), resposta.http_status


def _pelo_arquivo(url: str, *, ano: int | None = None) -> Coleta | None:
    """Captura tipada do Internet Archive, preservando PDF e data original.

    A data é a **da captura**. Gravar a de hoje diria que a montadora afirma isso agora,
    quando o que se leu é o que ela afirmava naquele dia.

    E a data também **decide**: uma captura de 2019 da página da S10 é a S10 de 2019. Na
    medição de 14/09/2026 foi exatamente isso que entrou, com tier 1 e citação verdadeira —
    `numero_marchas 6` e `torque_nm 460`, quando a de 2027 tem oito marchas e 510 Nm. A
    regra do ano de `classify` vale para a cópia arquivada igual: página velha é página
    velha, esteja ela no ar ou no arquivo.
    """
    from pipeline.fetch import wayback
    from pipeline.research import classify

    try:
        arquivo = wayback.buscar_arquivada(url)
    except Exception as exc:
        log.warning("research.arquivo_falhou", url=url, erro=str(exc)[:200])
        return None
    if not arquivo.ok:
        return None
    captura = (arquivo.captured_at or "")[:4]
    if ano and captura.isdigit() and int(ano) - int(captura) > classify.ANOS_DE_TOLERANCIA:
        log.info("research.arquivo_velho_demais", url=url, captura=captura, ano=ano)
        return None
    from pipeline.research.documents import preservar_pdf
    from pipeline.snapshots import sha256_de

    raw = arquivo.conteudo or b""
    raw_path, binary_hash = "", ""
    if raw.startswith(b"%PDF"):
        raw_path, binary_hash = preservar_pdf(raw)
    texto = _texto_da_pagina(url, arquivo.texto or "", raw)
    if isinstance(texto, Coleta):
        result = texto
    elif len(texto) >= MINIMO_DE_TEXTO_APROVEITAVEL:
        result = Coleta(texto=texto, parse_status="complete")
    else:
        return None
    result.captured_at = (arquivo.captured_at or "")[:10]
    result.via = "arquivo"
    result.sha256 = sha256_de(result.texto) if result.texto else ""
    result.raw_path = raw_path
    result.sha256_binario = binary_hash
    result.mime_type = "application/pdf" if binary_hash else ""
    result.fetch_ok = True
    return result


def _tipo_concreto(classificacao: classify.Classificacao) -> str:
    """Traduz o tipo da busca para os tipos já entendidos pelo pipeline principal."""
    if "/tabela-fipe/" in classificacao.url:
        return "fipe"
    if classificacao.tipo == "oficial":
        return "pdf_oficial" if classificacao.e_pdf else "pagina_oficial"
    if classificacao.tipo == "registro":
        dominio = classificacao.dominio or classify.dominio_de(classificacao.url)
        if "fipe" in dominio or "parallelum" in dominio:
            return "fipe"
        if "inmetro" in dominio or dominio.endswith("gov.br"):
            return "pbe"
    return classificacao.tipo or "desconhecido"


@dataclass(frozen=True)
class _SnapshotDaPesquisa:
    """Adapter mínimo de :class:`Fonte` para os conectores do pipeline principal."""

    fonte: Fonte

    @property
    def source_id(self) -> str:
        return self.fonte.source_id

    @property
    def texto(self) -> str:
        return self.fonte.texto

    @property
    def url(self) -> str:
        return self.fonte.url

    @property
    def tier(self) -> int:
        return self.fonte.tier

    @property
    def tipo(self) -> str:
        return self.fonte.tipo

    @property
    def captured_at(self) -> str:
        return self.fonte.captured_at


def _documentos_de(fontes: list[Fonte], alvo: planner.Alvo | None = None) -> list[Documento]:
    """As páginas baixadas, no formato que o extrator já sabe ler."""
    from pipeline.run import TIPOS_FORA_DA_EXTRACAO

    documentos = []
    for f in fontes:
        if not (
            f.baixada
            and f.texto
            and f.tipo not in (*TIPOS_FORA_DA_EXTRACAO, "garantia", "configurador_vw")
        ):
            continue
        cells = ()
        multiversao = False
        texto = f.texto
        pdf = f.documento_pdf
        if f.documento_pdf is not None:
            from pipeline.parse.version_slicer import recortar, versoes_do_documento

            texto = f.documento_pdf.texto_para_extracao()
            pdf = replace(
                f.documento_pdf,
                markdown=texto,
                tabelas=f.documento_pdf.tabelas_para_extracao(),
            )
            multiversao = bool(versoes_do_documento(pdf))
            if alvo is not None:
                cells = tuple(recortar(pdf, alvo.versao).celulas)
        documentos.append(
            Documento(
                texto=texto,
                source_id=f.source_id,
                url=f.url,
                tier=f.tier,
                captured_at=f.captured_at,
                celulas=cells,
                n_tabelas=len(pdf.tabelas) if pdf else 0,
                multiversao=multiversao,
                sha256_original=f.sha256_binario,
                parser_version=(
                    f"pdf-{getattr(f.documento_pdf, 'schema_version', 1)}:{f.documento_pdf.motor}"
                    if f.documento_pdf
                    else "html-1"
                ),
            )
        )
    return documentos


def _grupo_de(campo: str) -> str:
    from pipeline.schema import GRUPOS

    for grupo, campos in GRUPOS.items():
        if campo in campos:
            return grupo
    return ""


@dataclass
class Leitor:
    """Acumula candidatos e retoma blocos sem repetir passagens concluídas.

    Fast-path lê o documento/células; o modelo recebe somente o que couber na cota.
    O checkpoint salva candidatos e estado de leitura juntos. Mudança do documento
    invalida candidatos antigos daquela fonte antes de uma nova extração.
    """

    alvo: planner.Alvo
    orcamento: gaps.Orcamento
    trilha: Trilha
    pending: list[dict] = field(default_factory=list)
    candidatos: dict[str, list[Candidato]] = field(default_factory=dict)
    textos: dict[str, str] = field(default_factory=dict)
    fipe_somente_snapshots: bool = False
    usos: list[Any] = field(default_factory=list)
    sem_saldo: bool = False
    """As contas configuradas recusaram por saldo/cota. A partir daqui o modelo não entra."""
    teto_atingido: bool = False
    """O teto de gasto desta máquina foi batido. Idem."""
    _avisou_cota: bool = False
    estado_leitura: EstadoLeitura = field(default_factory=EstadoLeitura)
    leituras: dict[str, dict] = field(default_factory=dict)
    services_budget: service_budget.ServiceBudget = field(
        default_factory=service_budget.ServiceBudget
    )

    @property
    def modelo_disponivel(self) -> bool:
        return (
            self.orcamento.chamadas_llm_restantes > 0
            and not self.sem_saldo
            and not self.teto_atingido
        )

    def _espera(self, segundos: float, motivo: str) -> None:
        self.trilha.registrar(
            Tipo.ESPERA,
            f"aguardando {segundos:.0f} s pela cota do modelo ({motivo})",
            segundos=round(segundos, 1),
            motivo=motivo,
        )

    def ler(
        self,
        documentos: list[Documento],
        *,
        campos: list[str],
        fontes: list[Fonte] | None = None,
    ) -> tuple[StandardSpec, list[str]]:
        """Retoma blocos pendentes e reconcilia com os candidatos já preservados."""
        from pipeline import llm, reconcile
        from pipeline.extract.run import extrair_documento
        from pipeline.run import (
            CAMPOS_DE_SERVICO,
            JobContext,
            consultar_comerciais,
            consultar_consumo,
            consultar_preco_oficial,
        )

        campos_pedidos = {c.split(".", 1)[-1] for c in campos}
        alvo = campos_pedidos - set(CAMPOS_DE_SERVICO)
        avisos: list[str] = []

        # Tier primeiro, e dentro do tier a ordem de coleta (`sorted` é estável): se a
        # cota do modelo é curta, ela vai para a fonte oficial, não para a revista.
        from pipeline.publication import POLICY_VERSION

        novos = sorted((d for d in documentos if d.texto), key=lambda d: d.tier)
        for doc in novos:
            if self.orcamento.decorrido >= self.orcamento.segundos:
                avisos.append("limite de tempo antes da extração; documentos preservados")
                break
            permitir = self.modelo_disponivel
            fingerprint = digest(asdict(doc))
            request = digest(
                {
                    "campos": sorted(alvo),
                    "alvo": asdict(self.alvo),
                    "policy": POLICY_VERSION,
                    "provider": llm.provedor_atual(),
                    "small": llm.modelo_pequeno(),
                    "large": llm.modelo_grande(),
                }
            )
            anterior = self.leituras.get(doc.source_id, {})
            same_document = anterior.get("documento") == fingerprint
            previous_context = self.estado_leitura.contextos.get(
                anterior.get("contexto_id", ""), {}
            )
            previous_fake = anterior.get(
                "modo_fixture",
                previous_context.get("identidade", {}).get("extrator", {}).get("modo_fixture"),
            )
            changed_mode = previous_fake is not None and previous_fake != llm.modo_fake()
            if (
                (anterior and not same_document)
                or (doc.source_id in self.textos and self.textos[doc.source_id] != doc.texto)
                or changed_mode
            ):
                self.candidatos.pop(doc.source_id, None)
                self.estado_leitura.invalidar_fonte(doc.source_id)
            # O extrator conhece a configuração completa (prompt, modo, parser, modelo
            # e campos). Seu estado evita repetir chamadas; um atalho aqui esconderia
            # mudanças de configuração. Fast-path continua lendo o documento inteiro.
            self.textos[doc.source_id] = doc.texto
            if (
                not permitir
                and not self._avisou_cota
                and not (self.sem_saldo or self.teto_atingido)
            ):
                self._avisou_cota = True
                self.trilha.registrar(
                    Tipo.AVISO,
                    f"cota de {self.orcamento.chamadas_llm} chamada(s) ao modelo gasta; as "
                    "próximas páginas são lidas só por regra",
                    chamadas_llm=self.orcamento.chamadas_llm,
                )
            with llm.medindo() as medida, llm.avisando_espera(self._espera):
                parcial = extrair_documento(
                    doc,
                    alvo,
                    marca=self.alvo.marca,
                    modelo_veiculo=self.alvo.modelo,
                    versao=self.alvo.versao or self.alvo.modelo,
                    permitir_llm=permitir,
                    max_blocos=BLOCOS_AO_MODELO_NA_PESQUISA,
                    escalonar=False,
                    ano_modelo=self.alvo.ano,
                    estado_leitura=self.estado_leitura,
                    configuracao_alvo=asdict(self.alvo),
                )
            # VeÃ­culo ainda fora do banco nÃ£o tem lineup para a guarda normal do
            # pipeline. Quando a prÃ³pria pÃ¡gina lista vÃ¡rias versÃµes em seÃ§Ãµes, derive
            # os nomes literais e aplique a mesma atribuiÃ§Ã£o antes do merge. Se o alvo
            # for ambÃ­guo, a descoberta devolve vazio e nada Ã© descartado por palpite.
            alvo_da_secao, outras = reconcile.descobrir_secoes_de_versao(
                doc.texto,
                marca=self.alvo.marca,
                modelo=self.alvo.modelo,
                versao=self.alvo.versao,
            )
            if alvo_da_secao and outras:
                filtrados, fora_da_secao = reconcile.filtrar_por_secao(
                    list(parcial.candidatos),
                    textos={doc.source_id: doc.texto},
                    alvo=alvo_da_secao,
                    outras=outras,
                )
                parcial.candidatos = filtrados
                avisos.extend(fora_da_secao)
            acumulados = self.candidatos.setdefault(doc.source_id, [])
            acumulados.extend(c for c in parcial.candidatos if c not in acumulados)
            self.leituras[doc.source_id] = {
                "documento": fingerprint,
                "pedido": request,
                "modo_fixture": llm.modo_fake(),
                **parcial.leitura,
            }
            self.usos.extend(parcial.usos)
            avisos.extend(parcial.avisos)

            reais = medida.chamadas - medida.de_fixture
            if reais:
                self.orcamento.chamadas_llm_gastas += reais
                do_modelo = [c for c in parcial.candidatos if not c.do_fastpath]
                nome = next((u.modelo for u in parcial.usos if u.modelo), "") or "modelo"
                dominio = classify.dominio_de(doc.url) or doc.source_id
                self.trilha.registrar(
                    Tipo.MODELO,
                    f"{nome} leu tier {doc.tier} · {dominio}: {len(do_modelo)} campo(s) com "
                    f"trecho, {medida.segundos:.0f} s, "
                    f"{medida.tokens_entrada + medida.tokens_saida} tokens",
                    url=doc.url,
                    source_id=doc.source_id,
                    tier=doc.tier,
                    campos=sorted({c.campo for c in do_modelo}),
                    **medida.to_dict(),
                )
            if medida.sem_saldo:
                self.sem_saldo = True
            if medida.teto_atingido:
                self.teto_atingido = True

        snaps = [_SnapshotDaPesquisa(f) for f in (fontes or []) if f.baixada and f.texto]
        if self.orcamento.decorrido < self.orcamento.segundos:
            contexto = JobContext(
                marca=self.alvo.marca,
                modelo=self.alvo.modelo,
                versao=self.alvo.versao,
                ano=self.alvo.ano,
                stage="extracting",
                snapshots=snaps,  # type: ignore[arg-type] -- adapter intencional
            )
            de_servico: list[Candidato] = []
            if "__fipe__" not in self.candidatos:
                try:
                    self.candidatos["__fipe__"] = consultar_comerciais(
                        contexto, somente_snapshots=self.fipe_somente_snapshots
                    )
                except TimeoutError:
                    avisos.append("FIPE: limite de tempo; candidatos anteriores preservados")
                    self.candidatos["__fipe__"] = []
            de_servico.extend(self.candidatos["__fipe__"])
            if any(s.tipo == "pbe" for s in snaps):
                de_servico.extend(consultar_consumo(contexto))
            from pipeline.connectors import (
                carrosnaweb,
                ford_warranty,
                vw_configurator,
                vw_manual_warranty,
            )
            from pipeline.identity import VehicleTarget

            target = VehicleTarget(
                self.alvo.marca, self.alvo.modelo, self.alvo.versao, self.alvo.ano
            )
            for snap in snaps:
                if snap.tipo == "garantia" and "garantia_meses" in campos_pedidos:
                    de_servico.extend(
                        ford_warranty.candidatos(
                            snap.texto, snap.url, target, snap.source_id, snap.captured_at
                        )
                    )
                    de_servico.extend(
                        vw_manual_warranty.candidatos(
                            snap.texto, snap.url, target, snap.source_id, snap.captured_at
                        )
                    )
                elif snap.tipo == "configurador_vw":
                    de_servico.extend(
                        c
                        for c in vw_configurator.candidatos(snap.texto, snap.url, target)
                        if c.campo in campos_pedidos
                    )
                elif snap.tipo == "ficha":
                    de_servico.extend(
                        c
                        for c in carrosnaweb.candidatos(
                            snap.texto, snap.url, target, snap.source_id, snap.captured_at
                        )
                        if c.campo in campos_pedidos
                    )
            if any(s.tipo in {"pagina_oficial", "pdf_oficial", "imprensa"} for s in snaps):
                from pipeline.identity import Applicability, VehicleTarget, assess

                contexto.snapshots = [
                    s
                    for s in snaps
                    if s.tipo in {"fipe", "pbe"}
                    or assess(
                        VehicleTarget(
                            self.alvo.marca, self.alvo.modelo, self.alvo.versao, self.alvo.ano
                        ),
                        s.texto,
                        url=s.url,
                    ).status
                    == Applicability.COMPATIBLE
                ]
                de_servico.extend(consultar_preco_oficial(contexto))
            # A consulta FIPE é reutilizada. Cada citação conserva o texto original do serviço.
            self.candidatos["__servicos__"] = de_servico
            avisos.extend(contexto.avisos)
            for snap in snaps:
                self.textos.setdefault(snap.source_id, snap.texto)
            service_texts: dict[str, list[str]] = defaultdict(list)
            for candidato in de_servico:
                if candidato.source_text:
                    self.textos[candidato.source_id] = candidato.source_text
                    if fontes is not None and not any(f.url == candidato.url for f in fontes):
                        import hashlib
                        from datetime import UTC, datetime

                        fontes.append(
                            Fonte(
                                url=candidato.url,
                                tier=candidato.tier,
                                motivo="resposta estruturada FIPE",
                                consulta="conector FIPE direto",
                                texto=candidato.source_text,
                                tipo="fipe",
                                baixada=True,
                                captured_at=datetime.now(UTC).isoformat(),
                                sha256=hashlib.sha256(candidato.source_text.encode()).hexdigest(),
                            )
                        )
                service_texts[candidato.source_id].append(candidato.quote)
            for source_id, quotes in service_texts.items():
                self.textos.setdefault(source_id, "\n".join(dict.fromkeys(quotes)))

        if not self.textos:
            return empty_spec(job_id="research:sem-documento"), ["nenhuma página pôde ser lida"]

        todos = [c for key, lista in self.candidatos.items() if key != "__fipe__" for c in lista]
        todos, texto_perdeu = reconcile.preferir_celulas(todos)
        avisos.extend(texto_perdeu)
        from pipeline.identity import VehicleTarget

        resultado = reconcile.reconciliar(
            todos,
            textos=dict(self.textos),
            campos=list(campos_pedidos),
            target=VehicleTarget(
                self.alvo.marca, self.alvo.modelo, self.alvo.versao, self.alvo.ano
            ),
        )
        avisos.extend(resultado.nao_normalizaveis)

        spec = empty_spec(
            job_id=f"research:{self.alvo.marca}:{self.alvo.modelo}",
            sources_checked=sorted(self.textos),
        )
        for nome, decisao in resultado.decisoes.items():
            grupo = _grupo_de(nome)
            if grupo:
                spec.set(f"{grupo}.{nome}", decisao.spec)
        return spec, avisos


def _por_dominio(candidatas: list[classify.Classificacao]) -> dict[str, list]:
    """Agrupa por domínio: o mesmo domínio é serial (1 req/s), domínios diferentes não."""
    grupos: dict[str, list] = defaultdict(list)
    for c in candidatas:
        grupos[c.dominio].append(c)
    return grupos


def _registrar_campos_novos(
    trilha: Trilha, spec: StandardSpec, antes: gaps.Cobertura, depois: gaps.Cobertura
) -> None:
    """Um evento `campo` por campo que **passou a ter valor** nesta rodada.

    É o passo que o docstring de `events.py` chama de "o nosso produto": sem ele, a trilha
    prova que uma busca aconteceu; com ele, prova de onde veio cada número.
    """
    novos = set(antes.faltando) - set(depois.faltando)
    if not novos:
        return
    dados = spec.model_dump()
    for grupo_nome, grupo in dados.items():
        if not isinstance(grupo, dict):
            continue
        for campo, celula in grupo.items():
            if campo not in novos or not isinstance(celula, dict) or celula.get("value") is None:
                continue
            evidencias = celula.get("evidences") or []
            primeira = evidencias[0] if evidencias else {}
            url = str(primeira.get("source_url") or "")
            tier = primeira.get("tier")
            unidade = celula.get("unit") or ""
            valor = celula.get("value")
            onde = classify.dominio_de(url) if url else "regra"
            trilha.registrar(
                Tipo.CAMPO,
                f"{campo}: {valor}{' ' + unidade if unidade else ''} — {onde}"
                + (f" (tier {tier})" if tier else ""),
                campo=campo,
                grupo=grupo_nome,
                valor=valor,
                unit=unidade or None,
                status=str(celula.get("status") or ""),
                confianca=celula.get("confidence"),
                evidence_quote=str(primeira.get("quote") or ""),
                url=url,
                tier=tier,
            )


def _retomar_pdfs(fontes: list[Fonte], leitor: Leitor) -> bool:
    """Atualiza parsers legados uma vez; OCR ambíguo exige seleção/revisão explícita."""
    from pipeline.research.reprocess import reprocessar_fonte

    mudou = False
    for i, fonte in enumerate(fontes):
        if leitor.orcamento.estourou():
            break
        restante = leitor.orcamento.segundos - leitor.orcamento.decorrido
        if deadline.remaining() is not None:
            restante = min(restante, deadline.remaining())
        if restante <= 5:
            break
        if not fonte.raw_path:
            continue
        pdf = fonte.documento_pdf
        is_pdf = (
            pdf is not None
            or fonte.e_pdf
            or fonte.mime_type == "application/pdf"
            or fonte.raw_path.lower().endswith(".pdf")
            or fonte.url.lower().split("?", 1)[0].endswith(".pdf")
        )
        if not is_pdf:
            continue
        legado = pdf is not None and getattr(pdf, "schema_version", 1) < 2
        falhou = pdf is None and fonte.parse_status in {"", "not_parsed", "failed", "timeout"}
        if not (legado or falhou):
            continue
        nova = reprocessar_fonte(fonte, timeout=min(60, restante - 5))
        fontes[i] = nova
        # O texto/estrutura anterior não pode continuar sustentando candidatos antigos.
        for key, candidates in leitor.candidatos.items():
            leitor.candidatos[key] = [c for c in candidates if c.source_id != fonte.source_id]
        leitor.textos.pop(fonte.source_id, None)
        leitor.leituras.pop(fonte.source_id, None)
        leitor.trilha.registrar(
            Tipo.LENDO,
            "documento preservado reprocessado localmente",
            url=fonte.url,
            parse_status=nova.parse_status,
            caracteres=len(nova.texto),
            erro=nova.erro,
        )
        mudou = True
    return mudou


def pesquisar(
    marca: str,
    modelo: str,
    versao: str = "",
    *,
    ano: int | None = None,
    campos: list[str] | None = None,
    orcamento: gaps.Orcamento | None = None,
    provedor: str = "",
    ao_evento: Callable[[Evento], None] | None = None,
    checkpoint_path: str = "",
) -> Resultado:
    """Completa a ficha de um veículo procurando as fontes do zero.

    O laço, e a ordem dele:

    1. **planejar** — consultas por tier, todas de uma vez (fan-out);
    2. **buscar** — cada consulta ao provedor, com cache por `(consulta, dia)`;
    3. **classificar** — cada URL vira tier + motivo; as descartadas ficam na trilha **com
       o motivo**, e não somem;
    4. **coletar** — as melhores, respeitando o orçamento de páginas;
    5. **ler** — retomar blocos pendentes, com grounding e identidade;
    6. **medir** — quantos campos fecharam, e quais faltam;
    7. **decidir** — vale outra rodada? E, se não vale, **por quê**.

    O orçamento é conferido **antes e depois** de cada rodada: um limite que só é olhado no
    fim é um limite que já foi estourado quando alguém pergunta.

    `ao_evento` recebe cada evento da trilha **no momento em que ele acontece** — é como o
    worker grava a trilha ao vivo para a tela.
    """
    from pipeline import llm

    inicio = time.monotonic()
    orcamento = orcamento or gaps.Orcamento()
    from pipeline.research.extract_service import calls

    calls.set(0)
    trilha = Trilha(ao_registrar=ao_evento)
    trilha._relogio = lambda: time.monotonic() - inicio

    alvo = planner.Alvo(marca=marca.strip(), modelo=modelo.strip(), versao=versao.strip(), ano=ano)
    procurados = gaps.campos_procuraveis(campos)

    trilha.registrar(
        Tipo.INICIO,
        f"procurando {alvo.nome}",
        veiculo=alvo.nome,
        campos=len(procurados),
        orcamento=orcamento.to_dict(),
    )

    fontes: list[Fonte] = []
    lidas: set[str] = set()
    #: Domínios que já responderam 403/CAPTCHA nesta pesquisa. Ver o corte na escolha.
    dominios_fechados: set[str] = set()
    escalada_fechada: set[str] = set()
    """Domínios em que o navegador e o arquivo já falharam nesta pesquisa. Tentar de novo
    é pagar o mesmo relógio pela mesma porta fechada."""
    spec = empty_spec(job_id=f"research:{marca}:{modelo}")
    cobertura = gaps.medir(spec, campos)
    avisos: list[str] = []
    motivo = gaps.Motivo.RODADAS
    leitor = Leitor(alvo=alvo, orcamento=orcamento, trilha=trilha)

    from pipeline.research import acervo, checkpoint

    tentadas: set[str] = set()
    saved = checkpoint.load(checkpoint_path, alvo)
    if saved:
        from pipeline.parse.pdf import DocumentoPdf

        for data in saved["fontes"]:
            pdf = data.get("documento_pdf")
            if pdf:
                data["documento_pdf"] = DocumentoPdf.from_dict(pdf)
            fontes.append(Fonte(**data))
        lidas.update(url_key(f.url) for f in fontes)
        leitor.candidatos = {k: [Candidato(**c) for c in v] for k, v in saved["candidatos"].items()}
        leitor.textos = saved["textos"]
        leitor.estado_leitura = EstadoLeitura.from_dict(saved.get("estado_leitura"))
        leitor.leituras = saved.get("leituras", {})
        if saved.get("services_budget"):
            leitor.services_budget = service_budget.ServiceBudget.from_dict(
                saved["services_budget"]
            )
        spec = StandardSpec.model_validate(saved["spec"])
        cobertura = gaps.medir(spec, campos)
        tentadas.update(saved["consultas"])
        leitor.pending = saved.get("pending", [])
        spent = saved.get("budget_spent", {})
        orcamento.rodadas_gastas = int(spent.get("rodadas_gastas", 0))
        orcamento.chamadas_llm_gastas = int(spent.get("chamadas_llm_gastas", 0))
        orcamento.paginas_gastas = int(spent.get("paginas_gastas", 0))
        orcamento._inicio -= float(spent.get("decorrido", 0))

    consultas = (
        planner.consultas_de_lacuna(alvo, list(cobertura.faltando), tentadas=tentadas)
        if saved
        else planner.primeira_rodada(alvo)
    )

    # Reservar salva antes da requisição: reiniciar o job não renova seu teto.
    leitor.services_budget.on_change = lambda: checkpoint.save(
        checkpoint_path, alvo, fontes, leitor, spec, tentadas
    )
    services_exceeded = False
    with (
        llm.medindo() as medicao,
        deadline.budget(orcamento.segundos - orcamento.decorrido),
        service_budget.scope(leitor.services_budget),
    ):
        if saved and _retomar_pdfs(fontes, leitor):
            spec, leitura_avisos = leitor.ler(
                _documentos_de(fontes, alvo), campos=procurados, fontes=fontes
            )
            avisos.extend(leitura_avisos)
            cobertura = gaps.medir(spec, campos)
            checkpoint.save(checkpoint_path, alvo, fontes, leitor, spec, tentadas)
        if marca == "Volkswagen" and modelo == "Amarok":
            from pipeline.connectors import vw_configurator
            from pipeline.identity import VehicleTarget

            if url_key(vw_configurator.PAGE) not in lidas:
                try:
                    with deadline.budget(40):
                        structured = vw_configurator.collect(
                            VehicleTarget(marca, modelo, versao, ano)
                        )
                    if structured:
                        fontes.append(
                            Fonte(
                                url=structured.url,
                                texto=structured.texto,
                                tier=1,
                                tipo="configurador_vw",
                                motivo="configurador oficial com chave modelo/ano",
                                consulta="conector configurador VW",
                                baixada=True,
                                captured_at=structured.captured_at,
                                sha256=structured.sha256,
                            )
                        )
                        lidas.add(url_key(structured.url))
                except Exception as exc:
                    avisos.append(f"configurador VW: {type(exc).__name__}: {str(exc)[:150]}")
        if any(c.startswith("consumo_") for c in procurados):
            from pipeline.research.structured import pbe_source

            try:
                pbe_fonte = pbe_source()
                if pbe_fonte and url_key(pbe_fonte.url) not in lidas:
                    fontes.append(pbe_fonte)
                    lidas.add(url_key(pbe_fonte.url))
            except Exception as exc:
                avisos.append(f"conector PBE: {type(exc).__name__}: {str(exc)[:150]}")
        while True:
            estouro = orcamento.estourou()
            if estouro is not None:
                motivo = estouro
                break

            orcamento.rodadas_gastas += 1
            trilha.rodada = orcamento.rodadas_gastas
            trilha.registrar(
                Tipo.RODADA,
                f"rodada {orcamento.rodadas_gastas} de {orcamento.rodadas}",
                consultas=len(consultas),
            )

            # ------------------------------------------------------------ 2. buscar
            candidatas = [
                classify.Classificacao(**c)
                for c in leitor.pending
                if url_key(c["url"]) not in lidas
            ]
            de_qual_consulta: dict[str, str] = {}
            # Novos localizadores cadastrados também entram numa retomada.
            for known in acervo.known_sources(alvo):
                if url_key(known.url) not in lidas:
                    candidatas.append(
                        classify.classificar(
                            known.url, marca=marca, modelo=modelo, titulo=known.titulo, ano=ano
                        )
                    )
                    de_qual_consulta[known.url] = "acervo cadastrado"
            for consulta in consultas:
                if orcamento.decorrido >= orcamento.segundos:
                    break
                if consulta.texto in tentadas:
                    continue
                tentadas.add(consulta.texto)
                try:
                    resposta = busca.buscar(
                        consulta.texto, provedor=provedor, dominios=consulta.dominios
                    )
                except busca.RedeProibidaEmReplay as exc:
                    # Replay com fixture parcial: a consulta que não foi gravada **não**
                    # derruba a pesquisa. Ela vira aviso, e as outras seguem.
                    #
                    # A alternativa — deixar subir — parece mais rigorosa e é pior: uma
                    # gravação com nove das dez consultas mataria o run inteiro, e a pessoa
                    # que estivesse gravando a décima não saberia por quê.
                    trilha.registrar(
                        Tipo.AVISO,
                        "consulta sem resposta gravada (replay)",
                        consulta=consulta.texto,
                        erro=str(exc)[:200],
                    )
                    avisos.append(f"sem fixture de busca: {consulta.texto}")
                    continue
                trilha.registrar(
                    Tipo.CONSULTA,
                    (
                        f"{consulta.texto} (em {len(consulta.dominios)} site(s) de ficha)"
                        if consulta.dominios
                        else consulta.texto
                    ),
                    consulta=consulta.texto,
                    tier=consulta.tier,
                    motivo=consulta.motivo,
                    campos_alvo=list(consulta.campos_alvo),
                    dominios=list(consulta.dominios),
                    do_cache=resposta.do_cache,
                )
                if not resposta.ok:
                    trilha.registrar(
                        Tipo.AVISO,
                        f"a busca não respondeu: {resposta.erro}",
                        consulta=consulta.texto,
                        erro=resposta.erro,
                    )
                    avisos.append(f"busca falhou ({consulta.texto}): {resposta.erro}")
                    if resposta.orcamento_excedido:
                        services_exceeded = True
                        tentadas.discard(consulta.texto)
                        break
                    continue

                trilha.registrar(
                    Tipo.RESULTADOS,
                    f"{len(resposta.achados)} resultado(s)",
                    consulta=consulta.texto,
                    quantos=len(resposta.achados),
                )
                for achado in resposta.achados:
                    if url_key(achado.url) in lidas:
                        continue
                    decisao = classify.classificar(
                        achado.url,
                        marca=alvo.marca,
                        titulo=achado.titulo,
                        modelo=alvo.modelo,
                        ano=alvo.ano,
                        snippet=achado.snippet,
                    )
                    candidatas.append(decisao)
                    de_qual_consulta.setdefault(achado.url, consulta.texto)

            if not candidatas and not fontes:
                # Nenhuma busca respondeu e nada foi coletado até agora. Insistir numa
                # segunda rodada com o mesmo provedor fora do ar só gastaria relógio.
                trilha.registrar(
                    Tipo.AVISO,
                    "nenhuma das consultas devolveu resultado: não há o que coletar",
                    consultas=len(consultas),
                )
                avisos.append("nenhuma das consultas devolveu resultado")
                motivo = gaps.Motivo.SEM_PROGRESSO
                break

            # --------------------------------------------------------- 3. classificar
            vistas: set[str] = set()
            unicas: list[classify.Classificacao] = []
            for c in classify.ordenar(candidatas):
                if url_key(c.url) in vistas:
                    continue
                vistas.add(url_key(c.url))
                unicas.append(c)

            for c in unicas:
                if not c.aceita or c.tier > TIER_MAXIMO_PARA_COLETA:
                    trilha.registrar(
                        Tipo.FONTE_DESCARTADA,
                        f"{c.dominio or c.url}: {c.motivo}",
                        **c.to_dict(),
                    )

            escolhidas = [c for c in unicas if c.aceita and c.tier <= TIER_MAXIMO_PARA_COLETA]
            known_urls = {s.url.rstrip("/") for s in acervo.known_sources(alvo)}
            escolhidas.sort(key=lambda c: 0 if c.url.rstrip("/") in known_urls else 1)
            leitor.pending = [c.to_dict() for c in escolhidas]

            # **Domínio que já fechou a porta não volta para a fila.**
            #
            # Medido ao vivo em 13/09/2026, na S10 High Country: as seis páginas da rodada
            # eram de `chevrolet.com.br`, as seis vieram 403, e **oito outras fontes ficaram
            # de fora por limite de páginas** — havia ficha boa na fila, atrás de seis portas
            # fechadas. A ADR-7 diz para não insistir numa porta fechada; insistir em seis
            # endereços do mesmo prédio é a mesma coisa, com outro nome.
            fechadas = [c for c in escolhidas if c.dominio in dominios_fechados]
            if fechadas:
                escolhidas = [c for c in escolhidas if c.dominio not in dominios_fechados]
                for dominio_fechado in sorted({c.dominio for c in fechadas}):
                    quantas = sum(1 for c in fechadas if c.dominio == dominio_fechado)
                    trilha.registrar(
                        Tipo.AVISO,
                        f"{dominio_fechado} já fechou a porta nesta pesquisa: "
                        f"{quantas} endereço(s) do mesmo domínio saíram da fila",
                        dominio=dominio_fechado,
                        quantas=quantas,
                    )

            cabem = min(PAGINAS_POR_RODADA, orcamento.paginas_restantes)

            # -------------------------------------------------------------- 4. coletar
            #
            # **A vaga é de quem abre a porta, e por isso a fila é consumida, não cortada.**
            #
            # Medido ao vivo em 13/09/2026, na S10 High Country: as seis primeiras da fila
            # eram `chevrolet.com.br` (tier 1, e com razão), as duas primeiras vieram 403 e
            # fecharam o domínio — e as **dez fontes de ficha** que a busca restrita tinha
            # trazido nunca entraram, porque o corte `[:cabem]` já as havia deixado de fora
            # antes de qualquer coleta. O orçamento tinha sido dado a portas fechadas.
            #
            # Agora a rodada percorre a fila inteira, em ordem de preferência, e gasta
            # página só com quem responde. Quem não couber sai no fim, com a conta.
            coletadas_na_rodada = 0
            pulados_por_dominio: dict[str, int] = defaultdict(int)
            fora_por_orcamento = 0

            for posicao, c in enumerate(escolhidas):
                if coletadas_na_rodada >= cabem:
                    fora_por_orcamento = len(escolhidas) - posicao
                    break
                if c.dominio in dominios_fechados:
                    # A porta já fechou: as outras deste domínio saem **sem gastar vaga**.
                    pulados_por_dominio[c.dominio] += 1
                    continue

                # **O orçamento é conferido antes de CADA página, e não só entre rodadas.**
                # Medido ao vivo em 13/09/2026: o primeiro veículo passou de 3,2 minutos com
                # teto de 170 s, porque uma página lenta pendura a coleta e ninguém olha o
                # relógio até a rodada acabar.
                estouro_na_coleta = orcamento.estourou_na_coleta()
                if estouro_na_coleta is not None:
                    trilha.registrar(
                        Tipo.AVISO,
                        f"orçamento atingido no meio da coleta: {estouro_na_coleta.value}",
                        motivo=estouro_na_coleta.value,
                        paginas=orcamento.paginas_gastas,
                        decorrido=orcamento.decorrido,
                    )
                    fora_por_orcamento = len(escolhidas) - posicao
                    break

                trilha.registrar(
                    Tipo.FONTE_ESCOLHIDA,
                    f"tier {c.tier} · {c.dominio}: {c.motivo}",
                    **c.to_dict(),
                )
                trilha.registrar(Tipo.BAIXANDO, c.url, url=c.url, dominio=c.dominio)

                # **Escalar custa relógio.** O Chromium leva de 2 a 5 s por página, e um
                # domínio atrás de Akamai barra o navegador igual: na S10 de 14/09/2026,
                # tentar em todas as páginas da chevrolet.com.br derrubou a rodada de 12
                # páginas para 4, e a pesquisa parou por tempo. Escala quem tem tempo
                # sobrando, num domínio que ainda não provou o contrário.
                vale_escalar = (
                    c.dominio not in escalada_fechada
                    and (orcamento.segundos - orcamento.decorrido) > SEGUNDOS_PARA_ESCALAR
                )
                coleta = _coletar(
                    c.url,
                    tier=c.tier,
                    navegador=c.navegador,
                    ano=alvo.ano,
                    escalar=vale_escalar,
                )
                if vale_escalar and coleta.via == "http" and coleta.erro == "bloqueada":
                    escalada_fechada.add(c.dominio)
                orcamento.paginas_gastas += 1
                coletadas_na_rodada += 1
                lidas.add(url_key(c.url))
                leitor.pending = [p for p in leitor.pending if url_key(p["url"]) != url_key(c.url)]

                if coleta.via == "navegador":
                    trilha.registrar(
                        Tipo.AVISO,
                        f"{c.dominio} não abriu pelo caminho normal; a página foi lida no "
                        "navegador",
                        url=c.url,
                        via="navegador",
                    )
                elif coleta.via == "arquivo":
                    trilha.registrar(
                        Tipo.AVISO,
                        f"{c.dominio} está bloqueado; a página veio do Internet Archive, "
                        f"capturada em {coleta.captured_at or 'data desconhecida'}",
                        url=c.url,
                        via="arquivo",
                        captured_at=coleta.captured_at,
                    )

                fonte = Fonte(
                    url=c.url,
                    tier=c.tier,
                    tipo=_tipo_concreto(c),
                    e_pdf=c.e_pdf,
                    motivo=c.motivo,
                    consulta=de_qual_consulta.get(c.url, ""),
                    texto=coleta.texto,
                    captured_at=coleta.captured_at,
                    baixada=bool(coleta.texto),
                    bloqueada=(coleta.erro == "bloqueada"),
                    erro=coleta.erro,
                    sha256=coleta.sha256,
                    http_status=coleta.http_status,
                    documento_pdf=coleta.documento_pdf,
                    raw_path=coleta.raw_path,
                    creditos=coleta.creditos,
                    links=coleta.links,
                    sha256_binario=coleta.sha256_binario,
                    mime_type=coleta.mime_type,
                    fetch_ok=coleta.fetch_ok,
                    parse_status=coleta.parse_status,
                )
                fontes.append(fonte)
                # Seguir os documentos indicados pela própria página encontra PDFs que
                # não aparecem na busca. O link não prova versão/ano nem qualquer valor.
                for linked_url, title in fonte.links if fonte.tier == 1 else []:
                    if url_key(linked_url) in lidas or url_key(linked_url) in vistas:
                        continue
                    linked = classify.classificar(
                        linked_url, marca=marca, modelo=modelo, titulo=title, ano=ano
                    )
                    vistas.add(url_key(linked_url))
                    if linked.aceita and linked.tier <= TIER_MAXIMO_PARA_COLETA:
                        leitor.pending.append(linked.to_dict())
                        escolhidas.insert(posicao + 1, linked)
                        de_qual_consulta[linked_url] = "link em " + fonte.url
                    else:
                        trilha.registrar(Tipo.FONTE_DESCARTADA, linked.motivo, **linked.to_dict())
                checkpoint.save(checkpoint_path, alvo, fontes, leitor, spec, tentadas)

                if fonte.baixada and len(coleta.texto) < MINIMO_DE_TEXTO_APROVEITAVEL:
                    fonte.baixada = False
                    fonte.erro = "página sem texto aproveitável"
                    fonte.texto = ""
                    trilha.registrar(
                        Tipo.AVISO,
                        f"{c.dominio} respondeu, mas veio sem texto "
                        f"({len(coleta.texto)} caractere(s)): não conta como página lida",
                        url=c.url,
                        caracteres=len(coleta.texto),
                        motivo="página sem texto aproveitável",
                    )
                elif fonte.baixada and len(coleta.texto) > TETO_DE_TEXTO:
                    fonte.baixada = False
                    fonte.texto = ""
                    fonte.erro = "documento grande demais"
                    trilha.registrar(
                        Tipo.FONTE_DESCARTADA,
                        f"{c.dominio}: documento de {len(coleta.texto) / 1_000_000:.1f} "
                        "milhões de caracteres — é manual ou catálogo inteiro, não ficha "
                        "técnica",
                        url=c.url,
                        caracteres=len(coleta.texto),
                        motivo="documento grande demais",
                    )
                elif fonte.bloqueada:
                    dominios_fechados.add(c.dominio)
                    trilha.registrar(
                        Tipo.FONTE_BLOQUEADA,
                        f"{c.dominio} fechou a porta — vira estado, não truque",
                        url=c.url,
                        tier=c.tier,
                        dominio=c.dominio,
                    )
                elif coleta.erro:
                    trilha.registrar(
                        Tipo.AVISO,
                        f"não deu para ler {c.dominio}: {coleta.erro}",
                        url=c.url,
                        erro=coleta.erro,
                    )
                else:
                    trilha.registrar(
                        Tipo.BAIXADA,
                        f"{c.dominio}: {len(coleta.texto)} caracteres salvos",
                        url=c.url,
                        caracteres=len(coleta.texto),
                        captured_at=coleta.captured_at,
                    )
                    # Concluir cada documento antes de abrir o próximo preserva os
                    # resultados mesmo se a próxima fonte consumir todo o prazo.
                    antes_do_documento = gaps.medir(spec, campos)
                    spec, novos_avisos = leitor.ler(
                        _documentos_de(fontes, alvo), campos=procurados, fontes=fontes
                    )
                    avisos.extend(novos_avisos)
                    _registrar_campos_novos(
                        trilha, spec, antes_do_documento, gaps.medir(spec, campos)
                    )
                    checkpoint.save(checkpoint_path, alvo, fontes, leitor, spec, tentadas)

            # O que ficou de fora **tem nome e conta**: corte silencioso é indistinguível
            # de fonte que ninguém viu.
            for dominio_fechado, quantas in sorted(pulados_por_dominio.items()):
                trilha.registrar(
                    Tipo.AVISO,
                    f"{dominio_fechado} já fechou a porta nesta pesquisa: "
                    f"{quantas} endereço(s) do mesmo domínio saíram da fila",
                    dominio=dominio_fechado,
                    quantas=quantas,
                )
            if fora_por_orcamento:
                trilha.registrar(
                    Tipo.AVISO,
                    f"{fora_por_orcamento} fonte(s) ficaram de fora por limite de páginas",
                    sobraram=fora_por_orcamento,
                )

            # ----------------------------------------------------------------- 5. ler
            documentos = _documentos_de(fontes, alvo)
            trilha.registrar(
                Tipo.LENDO, f"lendo {len(documentos)} documento(s)", quantos=len(documentos)
            )
            antes = cobertura
            spec, avisos_da_leitura = leitor.ler(documentos, campos=procurados, fontes=fontes)
            avisos.extend(avisos_da_leitura)

            # -------------------------------------------------------------- 6. medir
            cobertura = gaps.medir(spec, campos)
            checkpoint.save(checkpoint_path, alvo, fontes, leitor, spec, tentadas)
            _registrar_campos_novos(trilha, spec, antes, cobertura)
            trilha.registrar(
                Tipo.COBERTURA,
                f"{cobertura.respondidos} de {cobertura.total} campos respondidos",
                **cobertura.to_dict(),
            )

            # ------------------------------------------------------------ 7. decidir
            if leitor.sem_saldo:
                motivo = gaps.Motivo.MODELO_SEM_SALDO
                break
            if leitor.teto_atingido:
                motivo = gaps.Motivo.TETO_DE_GASTO
                break
            if services_exceeded and cobertura.faltando:
                motivo = gaps.Motivo.TETO_SERVICOS
                break

            continua, parou_por = gaps.vale_outra_rodada(antes, cobertura, orcamento)
            if parou_por == gaps.Motivo.SEM_PROGRESSO and not orcamento.estourou():
                alternativas = planner.consultas_de_lacuna(
                    alvo, list(cobertura.faltando), tentadas=tentadas
                )
                continua = any(c.texto not in tentadas for c in alternativas)
            if not continua:
                motivo = parou_por or gaps.Motivo.COBERTURA
                break

            consultas = planner.consultas_de_lacuna(
                alvo, list(cobertura.faltando), tentadas=tentadas
            )
            if not consultas:
                motivo = gaps.Motivo.SEM_PROGRESSO
                break
            trilha.registrar(
                Tipo.LACUNA,
                f"{len(cobertura.faltando)} campo(s) sem valor: "
                f"{len(consultas)} consulta(s) dirigida(s)",
                faltando=list(cobertura.faltando),
                consultas=[c.texto for c in consultas],
            )

    from pipeline.research.diagnostics import diagnose, observation_records

    checkpoint.save(checkpoint_path, alvo, fontes, leitor, spec, tentadas)
    servicos = leitor.services_budget.to_dict()
    lacunas = diagnose(
        spec,
        alvo,
        fontes,
        avisos,
        tentadas,
        motivo.value,
        orcamento.decorrido,
        leituras=leitor.leituras,
    )
    explicacao = gaps.explicar(motivo, cobertura, orcamento)
    gasto = llm.gasto_da_rodada()
    trilha.registrar(
        Tipo.FIM,
        explicacao,
        motivo=motivo.value,
        lacunas=lacunas,
        custos_servicos={
            "ia_usd": medicao.custo_usd,
            "busca_usd": None,
            "coleta_usd": None,
            "tavily_extract_creditos": sum(f.creditos for f in fontes),
            "servicos": servicos,
            "total_usd": None,
        },
        cobertura=cobertura.to_dict(),
        orcamento=orcamento.to_dict(),
        medicao=medicao.to_dict(),
        gasto_rodada_usd=gasto["usd"],
        teto_usd=llm.teto_usd(),
        bloqueadas=len([f for f in fontes if f.bloqueada]),
        baixadas=len([f for f in fontes if f.baixada]),
    )
    log.info(
        "research.fim",
        veiculo=alvo.nome,
        campos=cobertura.com_valor,
        paginas=orcamento.paginas_gastas,
        segundos=orcamento.decorrido,
        chamadas_llm=orcamento.chamadas_llm_gastas,
        motivo=motivo.value,
    )

    return Resultado(
        marca=alvo.marca,
        modelo=alvo.modelo,
        versao=alvo.versao,
        spec=spec,
        trilha=trilha,
        cobertura=cobertura,
        orcamento=orcamento,
        motivo_da_parada=motivo,
        fontes=fontes,
        avisos=avisos,
        medicao=medicao,
        lacunas=lacunas,
        observacoes=observation_records(leitor),
        servicos=servicos,
    )


__all__ = [
    "BLOCOS_AO_MODELO_NA_PESQUISA",
    "PAGINAS_POR_RODADA",
    "Coleta",
    "Fonte",
    "Leitor",
    "Resultado",
    "pesquisar",
]
