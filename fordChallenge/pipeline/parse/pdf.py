"""PDF → texto + tabelas, preservando o que o grounding precisa.

O PDF é a melhor fonte do projeto: é onde a Toyota publica rpm (lição 3 do gabarito) e é
onde a ficha da Ford traz os modos de condução que expuseram a divergência com o slide
interno. Mas o valor útil está em **tabela de múltiplas versões**, e é aí que a extração
ingênua erra: `pypdf` devolve `"Pneus 265/65 R17 265/60 R18"` numa linha só, sem dizer
qual medida é de qual versão. Atribuir a errada seria a inferência proibida
("nada inferido de outra versão").

Por isso o parser entrega **duas** coisas:

* `markdown` — o texto contínuo, verbatim, para grounding;
* `tabelas` — a **grade** com as células e o seu alcance de colunas, que o
  `version_slicer` usa para recortar a coluna da versão alvo.

Leitura digital primeiro; diagnóstico e OCR local seletivo por página depois.
Docling exige configuração explícita de artefatos locais. Nenhum motor baixa pesos
implicitamente. Estados parciais e a proveniência geométrica acompanham o texto.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.parse.pdf_ocr import ocr_pagina as _ocr_pagina
from pipeline.parse.pdf_quality import diagnosticar_pagina


class PdfIlegivel(RuntimeError):
    """Nenhum motor conseguiu ler o PDF."""


@dataclass
class Tabela:
    """Uma tabela do PDF, já como grade retangular.

    Célula mesclada aparece com o valor na **primeira** coluna do alcance e vazia nas
    seguintes — é assim que o pdfplumber devolve, e é o que permite reconstruir o alcance
    sem adivinhar.
    """

    pagina: int
    linhas: list[list[str]] = field(default_factory=list)
    indice: int = 0
    spans: dict[str, int] = field(default_factory=dict)
    """Colspan comprovado pela geometria, indexado por 'linha:coluna' (zero-based)."""
    celulas: list[dict] = field(default_factory=list)
    bbox: list[float] = field(default_factory=list)
    motor: str = ""
    coord_origin: str = "top_left"

    @property
    def n_colunas(self) -> int:
        return max((len(linha) for linha in self.linhas), default=0)

    def linha_de_cabecalho(self, marcador: str = "versão") -> int | None:
        """Índice da linha que nomeia as versões (a que começa com `VERSÃO`)."""
        alvo = marcador.strip().lower()
        for i, linha in enumerate(self.linhas):
            if not linha:
                continue
            primeira = (linha[0] or "").strip().lower()
            if primeira.startswith(alvo) and any((c or "").strip() for c in linha[1:]):
                return i
        return None

    def to_dict(self) -> dict:
        return {
            "pagina": self.pagina,
            "indice": self.indice,
            "linhas": self.linhas,
            "spans": self.spans,
            "celulas": self.celulas,
            "bbox": self.bbox,
            "motor": self.motor,
            "coord_origin": self.coord_origin,
        }

    @classmethod
    def from_dict(cls, dados: dict) -> Tabela:
        return cls(
            pagina=int(dados["pagina"]),
            indice=int(dados.get("indice", 0)),
            linhas=[[("" if c is None else str(c)) for c in linha] for linha in dados["linhas"]],
            spans=dados.get("spans", {}),
            celulas=dados.get("celulas", []),
            bbox=dados.get("bbox", []),
            motor=dados.get("motor", ""),
            coord_origin=dados.get("coord_origin", "top_left"),
        )


@dataclass
class DocumentoPdf:
    markdown: str
    paginas: list[str] = field(default_factory=list)
    tabelas: list[Tabela] = field(default_factory=list)
    motor: str = ""
    diagnosticos: list[dict] = field(default_factory=list)
    status: str = "complete"
    avisos: list[str] = field(default_factory=list)
    schema_version: int = 2

    @classmethod
    def from_dict(cls, data: dict) -> DocumentoPdf:
        return cls(
            markdown=data.get("markdown", ""),
            paginas=data.get("paginas", []),
            tabelas=[Tabela.from_dict(t) for t in data.get("tabelas", [])],
            motor=data.get("motor", ""),
            diagnosticos=data.get("diagnosticos", []),
            status=data.get("status", "complete"),
            avisos=data.get("avisos", []),
            schema_version=data.get("schema_version", 1),
        )

    @property
    def n_paginas(self) -> int:
        return len(self.paginas)

    def tabelas_da_pagina(self, pagina: int) -> list[Tabela]:
        return [t for t in self.tabelas if t.pagina == pagina]

    def texto_para_extracao(self) -> str:
        """Only approved OCR/layout may replace native text at the extractor boundary.

        Full OCR output stays in markdown/diagnostics for review. Legacy documents
        without page diagnostics preserve the previous markdown contract.
        """
        if not self.diagnosticos or not self.paginas:
            return self.markdown
        by_page = {d["pagina"]: d for d in self.diagnosticos}
        safe = []
        for numero, text in enumerate(self.paginas, 1):
            diag = by_page.get(numero, {})
            generated = (
                "ocr_text" in diag
                or "layout_text" in diag
                or "ocr" in diag
                or diag.get("motor") == "docling"
                or "rapidocr" in diag.get("motor", "")
            )
            if generated and diag.get("status") != "complete":
                text = diag.get("native_text", "")
            safe.append(text)
        return "\n\n".join(safe)

    def tabelas_para_extracao(self) -> list[Tabela]:
        """Keep native grades when a model-produced replacement is still pending."""
        by_page = {d["pagina"]: d for d in self.diagnosticos}
        safe = []
        restored_pages = set()
        for table in self.tabelas:
            diag = by_page.get(table.pagina, {})
            if table.motor == "docling" and diag and diag.get("status") != "complete":
                if table.pagina not in restored_pages:
                    safe.extend(Tabela.from_dict(t) for t in diag.get("native_tables", []))
                    restored_pages.add(table.pagina)
                continue
            safe.append(table)
        return safe

    def tables_json(self) -> str:
        return json.dumps(
            {
                "motor": self.motor,
                "tabelas": [t.to_dict() for t in self.tabelas],
                "diagnosticos": self.diagnosticos,
                "status": self.status,
                "avisos": self.avisos,
                "schema_version": self.schema_version,
            },
            ensure_ascii=False,
            indent=2,
        )


# ------------------------------------------------------------------------- motores
def motor_preferido() -> str:
    """Motor a usar, respeitando `PDF_MOTOR` quando alguém força um."""
    forcado = os.environ.get("PDF_MOTOR", "").strip().lower()
    if forcado:
        return forcado
    if _tem("pdfplumber"):
        return "pdfplumber"
    return "pypdf"


def _tem(modulo: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(modulo) is not None


def motores_disponiveis() -> dict[str, bool]:
    """Diagnóstico: o que dá para usar nesta máquina."""
    return {
        "docling": _tem("docling") and bool(os.environ.get("PDF_DOCLING_ARTIFACTS_PATH")),
        "pdfplumber": _tem("pdfplumber"),
        "pypdf": _tem("pypdf"),
        "pdftotext": shutil.which("pdftotext") is not None,
    }


def _com_pdfplumber(dados: bytes) -> DocumentoPdf:
    import pdfplumber

    paginas: list[str] = []
    tabelas: list[Tabela] = []
    diagnostics: list[dict] = []
    with pdfplumber.open(io.BytesIO(dados)) as documento:
        for numero, pagina in enumerate(documento.pages, start=1):
            # layout=True mantém a posição das colunas no texto contínuo, que é o que
            # faz "Potência (cv/rpm) 204 / 3.400" aparecer numa linha só.
            texto = pagina.extract_text(layout=True) or ""
            paginas.append(texto)
            found = pagina.find_tables()
            diagnostics.append(diagnosticar_pagina(pagina, numero, texto, found))
            for i, table in enumerate(found):
                bruta = table.extract()
                linhas = [
                    [("" if c is None else str(c).replace("\n", " ").strip()) for c in linha]
                    for linha in bruta
                ]
                if any(any(c for c in linha) for linha in linhas):
                    xs = sorted({c[0] for c in table.cells} | {c[2] for c in table.cells})
                    spans = {}
                    cells = []
                    ys = sorted({c[1] for c in table.cells} | {c[3] for c in table.cells})
                    for ri, row in enumerate(table.rows):
                        for ci, cell in enumerate(row.cells):
                            if cell is not None:
                                count = sum(cell[0] - 0.5 <= x < cell[2] - 0.5 for x in xs)
                                if count > 1:
                                    spans[f"{ri}:{ci}"] = count
                                row_span = sum(cell[1] - 0.5 <= y < cell[3] - 0.5 for y in ys)
                                cells.append(
                                    {
                                        "row": ri,
                                        "col": ci,
                                        "row_span": max(1, row_span),
                                        "col_span": max(1, count),
                                        "text": linhas[ri][ci],
                                        "bbox": list(cell),
                                        "coord_origin": "top_left",
                                        "column_header": False,
                                        "row_header": False,
                                        "pagina": numero,
                                    }
                                )
                    parsed_table = Tabela(
                        pagina=numero,
                        linhas=linhas,
                        indice=i,
                        spans=spans,
                        celulas=cells,
                        bbox=list(table.bbox),
                        motor="pdfplumber",
                    )
                    header = parsed_table.linha_de_cabecalho()
                    for cell in parsed_table.celulas:
                        cell["column_header"] = header is not None and cell["row"] == header
                    tabelas.append(parsed_table)
    return DocumentoPdf(
        "\n\n".join(paginas), paginas, tabelas, "pdfplumber", diagnosticos=diagnostics
    )


def _com_pypdf(dados: bytes) -> DocumentoPdf:
    from pypdf import PdfReader

    leitor = PdfReader(io.BytesIO(dados))
    paginas = [(p.extract_text() or "") for p in leitor.pages]
    # Sem grade: o pypdf não expõe a geometria da tabela. Devolver `tabelas=[]` é honesto;
    # o slicer então avisa que não pode recortar por coluna.
    diagnostics = [
        {
            "pagina": i,
            "motor": "pypdf",
            "status": "needs_ocr" if not p.strip() else "complete",
            "q_pdf": {"text_chars": len(p.strip()), "geometry_unavailable": True},
        }
        for i, p in enumerate(paginas, 1)
    ]
    for page, text, diag in zip(leitor.pages, paginas, diagnostics, strict=True):
        images = _pypdf_tem_imagem(page.get("/Resources", {}))
        diag["q_pdf"]["has_images"] = images
        if len(text.strip()) < 100 and images:
            diag["status"] = "needs_ocr"
        elif not text.strip() and not images:
            diag["status"] = "empty"
    return DocumentoPdf("\n\n".join(paginas), paginas, [], "pypdf", diagnosticos=diagnostics)


def _pypdf_tem_imagem(resources, depth: int = 0) -> bool:
    """Inspect XObjects without decoding images; nested forms have a depth bound."""
    if depth > 8:
        return False
    resources = resources.get_object() if hasattr(resources, "get_object") else resources
    objects = resources.get("/XObject", {})
    objects = objects.get_object() if hasattr(objects, "get_object") else objects
    for item in objects.values():
        item = item.get_object()
        if item.get("/Subtype") == "/Image":
            return True
        if item.get("/Subtype") == "/Form" and _pypdf_tem_imagem(
            item.get("/Resources", {}), depth + 1
        ):
            return True
    return False


def _bbox_docling(bbox) -> tuple[list, str]:
    if bbox is None:
        return [], "unknown"
    origin = getattr(bbox, "coord_origin", "unknown")
    return [float(getattr(bbox, k)) for k in ("l", "t", "r", "b")], str(
        getattr(origin, "value", origin)
    )


def _tabela_docling(tabela, indice: int) -> Tabela:
    """Use source cells; pandas stores headers in columns and drops them from values."""
    data = tabela.data
    grade = [["" for _ in range(data.num_cols)] for _ in range(data.num_rows)]
    prov = getattr(tabela, "prov", []) or []
    pagina = int(getattr(prov[0], "page_no", 1)) if prov else 1
    bbox, origin = _bbox_docling(getattr(prov[0], "bbox", None) if prov else None)
    cells, spans = [], {}
    for cell in data.table_cells:
        row, col = cell.start_row_offset_idx, cell.start_col_offset_idx
        if not (0 <= row < data.num_rows and 0 <= col < data.num_cols):
            continue
        text = str(cell.text or "")
        grade[row][col] = text
        rs, cs = int(cell.row_span), int(cell.col_span)
        if cs > 1:
            spans[f"{row}:{col}"] = cs
        cell_bbox, cell_origin = _bbox_docling(getattr(cell, "bbox", None))
        cells.append(
            {
                "row": row,
                "col": col,
                "row_span": rs,
                "col_span": cs,
                "text": text,
                "bbox": cell_bbox,
                "coord_origin": cell_origin,
                "column_header": bool(cell.column_header),
                "row_header": bool(cell.row_header),
                "pagina": pagina,
            }
        )
    return Tabela(pagina, grade, indice, spans, cells, bbox, "docling", origin)


def _com_docling(dados: bytes) -> DocumentoPdf:
    if not os.environ.get("PDF_DOCLING_ARTIFACTS_PATH"):
        raise PdfIlegivel("Docling exige configuração de artefatos locais")
    from pipeline.parse.pdf_ocr import docling_local

    result = docling_local(dados)
    if "documento" not in result:
        raise PdfIlegivel(result.get("reason", "Docling local indisponível"))
    return DocumentoPdf.from_dict(result["documento"])


def _docling_inprocess(dados: bytes, pagina: int | None = None) -> DocumentoPdf:
    """Only called in the network-disabled subprocess, with explicit local assets."""
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    from pipeline.parse.pdf_ocr import disponibilidade, modelos_locais

    path = Path(os.environ["PDF_DOCLING_ARTIFACTS_PATH"])
    if not path.is_dir():
        raise FileNotFoundError("diretório local Docling ausente")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(dados)
        caminho = tmp.name
    try:
        configured_timeout = float(os.environ.get("PDF_DOCLING_PAGE_TIMEOUT", "25"))
        options = PdfPipelineOptions(
            artifacts_path=path,
            do_table_structure=True,
            do_ocr=False,
            document_timeout=min(55, max(1, configured_timeout)),
            enable_remote_services=False,
            accelerator_options=AcceleratorOptions(num_threads=2, device=AcceleratorDevice.CPU),
        )
        available, _ = disponibilidade()
        if available:
            models = modelos_locais()
            options.do_ocr = True
            options.ocr_options = RapidOcrOptions(
                backend="onnxruntime",
                lang=["iso:pt"],
                det_model_path=models["Det.model_path"],
                rec_model_path=models["Rec.model_path"],
                cls_model_path=models["Cls.model_path"],
                rapidocr_params={
                    "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                    "EngineConfig.onnxruntime.inter_op_num_threads": 2,
                    "EngineConfig.onnxruntime.use_cuda": False,
                },
            )
        resultado = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        ).convert(caminho, **({"page_range": (pagina, pagina)} if pagina else {}))
        documento = resultado.document
        markdown = documento.export_to_markdown()
        page_numbers = sorted(documento.pages)
        paginas = [
            documento.export_to_markdown(page_no=numero) if numero in page_numbers else ""
            for numero in range(1, max(page_numbers, default=0) + 1)
        ]
        tabelas = [_tabela_docling(t, i) for i, t in enumerate(documento.tables)]
        diagnostics = [
            {
                "pagina": n,
                "motor": "docling",
                "status": "needs_review" if options.do_ocr else "complete",
                "conversion_status": str(resultado.status),
                "regioes": [],
            }
            for n in page_numbers
        ]
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(dados))
        for diag in diagnostics:
            # Original digital text is a distinct artifact, not a model transcript.
            diag["native_text"] = reader.pages[diag["pagina"] - 1].extract_text() or ""
            diag["layout_text"] = paginas[diag["pagina"] - 1]
            for item in documento.texts:
                for prov in item.prov:
                    if prov.page_no == diag["pagina"]:
                        box, origin = _bbox_docling(prov.bbox)
                        diag["regioes"].append(
                            {
                                "text": item.text,
                                "bbox": box,
                                "coord_origin": origin,
                                "pagina": prov.page_no,
                            }
                        )
            if not paginas[diag["pagina"] - 1].strip():
                diag["status"] = "needs_ocr"
            if "partial" in str(resultado.status).lower():
                diag["status"] = "partial_conversion"
        return DocumentoPdf(markdown, paginas, tabelas, "docling", diagnosticos=diagnostics)
    finally:
        Path(caminho).unlink(missing_ok=True)


def _com_pdftotext(dados: bytes) -> DocumentoPdf:  # pragma: no cover - binário externo
    binario = shutil.which("pdftotext")
    if not binario:
        raise PdfIlegivel("pdftotext não está no PATH")
    with tempfile.TemporaryDirectory() as pasta:
        entrada = Path(pasta) / "entrada.pdf"
        entrada.write_bytes(dados)
        saida = Path(pasta) / "saida.txt"
        subprocess.run(  # noqa: S603 - binario resolvido por shutil.which, args fixos
            [binario, "-layout", "-enc", "UTF-8", str(entrada), str(saida)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        texto = saida.read_text(encoding="utf-8", errors="replace")
    return DocumentoPdf(texto, texto.split("\f"), [], "pdftotext")


_MOTORES = {
    "docling": _com_docling,
    "pdfplumber": _com_pdfplumber,
    "pypdf": _com_pypdf,
    "pdftotext": _com_pdftotext,
}

#: Ordem de fallback quando o motor preferido falha.
ORDEM_DE_FALLBACK = ("pdfplumber", "pypdf", "pdftotext")


def parse_pdf(
    dados: bytes,
    *,
    motor: str | None = None,
    max_paginas_ocr: int = 3,
    timeout_ocr: float = 25,
    orcamento_ocr: float = 50,
    paginas_ocr: list[int] | None = None,
) -> DocumentoPdf:
    """Lê um PDF com o melhor motor disponível, caindo para o próximo se algum falhar.

    Falha de motor **não** é falha do pipeline: o próximo tenta. Só quando todos falham é
    que levanta — e aí o campo vira `nao_encontrado` com a fonte registrada, nunca um
    valor chutado.
    """
    if not dados.startswith(b"%PDF"):
        raise PdfIlegivel("conteúdo sem assinatura %PDF")
    if len(dados) > 50 * 1024 * 1024:
        raise PdfIlegivel("PDF excede limite de 50 MiB")

    tentativas = [motor] if motor else [motor_preferido()]
    tentativas += [m for m in ORDEM_DE_FALLBACK if m not in tentativas]

    erros: list[str] = []
    for nome in tentativas:
        funcao = _MOTORES.get(nome)
        if funcao is None:
            erros.append(f"{nome}: motor desconhecido")
            continue
        try:
            documento = funcao(dados)
        except ImportError as exc:
            erros.append(f"{nome}: não instalado ({exc})")
            continue
        except Exception as exc:
            erros.append(f"{nome}: {type(exc).__name__}: {exc}")
            continue
        if documento.markdown.strip() or documento.diagnosticos:
            documento.avisos.extend(erros)
            return _completar_paginas(
                documento,
                dados,
                max_paginas_ocr=max_paginas_ocr,
                timeout_ocr=timeout_ocr,
                orcamento_ocr=orcamento_ocr,
                paginas_ocr=paginas_ocr,
            )
        erros.append(f"{nome}: texto vazio")
    raise PdfIlegivel("nenhum motor leu o PDF: " + " · ".join(erros))


def _completar_paginas(
    documento: DocumentoPdf,
    dados: bytes,
    *,
    max_paginas_ocr: int,
    timeout_ocr: float,
    orcamento_ocr: float,
    paginas_ocr: list[int] | None,
) -> DocumentoPdf:
    deadline = time.monotonic() + max(0, orcamento_ocr)
    attempted_pages: set[int] = set()
    enabled = os.environ.get("PDF_OCR_ENABLED", "1") != "0"
    for diag in documento.diagnosticos:
        n = diag["pagina"]
        if diag["status"] != "needs_ocr" or (paginas_ocr is not None and n not in paginas_ocr):
            continue
        remaining = deadline - time.monotonic()
        if not enabled or len(attempted_pages) >= max_paginas_ocr or remaining <= 0:
            documento.avisos.append(f"página {n}: OCR pendente por configuração/orçamento")
            continue
        attempted_pages.add(n)
        original_status = diag["status"]
        result = _ocr_pagina(dados, n, timeout=min(timeout_ocr, remaining))
        diag["native_text"] = documento.paginas[n - 1] if n <= len(documento.paginas) else ""
        diag["ocr_text"] = result.get("text", "")
        diag["status_before_ocr"] = original_status
        diag["status"] = result.get("status", "error")
        diag["ocr"] = {k: v for k, v in result.items() if k not in {"text", "regions"}}
        if result.get("text", "").strip():
            while len(documento.paginas) < n:
                documento.paginas.append("")
            native = documento.paginas[n - 1]
            documento.paginas[n - 1] = (native.rstrip() + "\n" + result["text"]).strip()
            diag["regioes"] = diag.get("regioes", []) + result.get("regions", [])
            diag["motor"] = (
                "pdfplumber+rapidocr"
                if documento.motor == "pdfplumber"
                else documento.motor + "+rapidocr"
            )
            if diag.get("q_pdf", {}).get("empty_tables", 0):
                diag["status"] = "needs_layout"
        if diag["status"] != "complete":
            reason = result.get("reason", "OCR exige validação de texto/layout/escopo")
            documento.avisos.append(f"página {n}: {diag['status']} — {reason}")
    # Layout escalation is explicit, local and limited to selected incomplete pages.
    if os.environ.get("PDF_DOCLING_ARTIFACTS_PATH"):
        from pipeline.parse.pdf_ocr import docling_local

        for diag in documento.diagnosticos:
            remaining = deadline - time.monotonic()
            n = diag["pagina"]
            if (
                diag["status"] not in {"needs_layout", "needs_review"}
                or (n not in attempted_pages and len(attempted_pages) >= max_paginas_ocr)
                or remaining <= 0
            ):
                continue
            if paginas_ocr is not None and n not in paginas_ocr:
                continue
            attempted_pages.add(n)
            result = docling_local(dados, pagina=n, timeout=min(timeout_ocr, remaining))
            diag["layout_attempt"] = {
                "status": result.get("status"),
                "reason": result.get("reason", ""),
            }
            if "documento" in result:
                converted = DocumentoPdf.from_dict(result["documento"])
                if len(converted.paginas) >= n and converted.paginas[n - 1].strip():
                    native_text = diag.get("native_text", documento.paginas[n - 1])
                    native_tables = [t.to_dict() for t in documento.tabelas_da_pagina(n)]
                    documento.paginas[n - 1] = converted.paginas[n - 1]
                    documento.tabelas = [
                        t for t in documento.tabelas if t.pagina != n
                    ] + converted.tabelas_da_pagina(n)
                    page_diag = next((d for d in converted.diagnosticos if d["pagina"] == n), {})
                    diag.update(page_diag)
                    diag["native_text"] = native_text
                    diag["native_tables"] = native_tables
                    diag["layout_text"] = converted.paginas[n - 1]
    incomplete = [d for d in documento.diagnosticos if d.get("status") not in {"complete", "empty"}]
    documento.status = "partial" if incomplete else "complete"
    for d in incomplete:
        message = f"página {d['pagina']}: {d['status']}"
        if message not in documento.avisos:
            documento.avisos.append(message)
    documento.markdown = "\n\n".join(documento.paginas) if documento.paginas else documento.markdown
    return documento


def parse_arquivo(caminho: str | Path, **kw) -> DocumentoPdf:
    return parse_pdf(Path(caminho).read_bytes(), **kw)


# ------------------------------------------------------------------- prints de página
def renderizar_paginas(
    dados: bytes, destino: Path, *, paginas: list[int] | None = None, dpi: int = 110
) -> list[Path]:
    """Grava `page_N.png` das páginas pedidas — evidência visual (`docs/05`).

    Melhor esforço: sem rasterizador disponível, devolve lista vazia em vez de levantar.
    Print é prova complementar; a evidência que sustenta valor é o trecho de texto.
    """
    try:
        import pdfplumber
    except ImportError:
        return []
    destino.mkdir(parents=True, exist_ok=True)
    criados: list[Path] = []
    try:
        with pdfplumber.open(io.BytesIO(dados)) as documento:
            alvos = paginas or list(range(1, len(documento.pages) + 1))
            for numero in alvos:
                if not 1 <= numero <= len(documento.pages):
                    continue
                arquivo = destino / f"page_{numero}.png"
                documento.pages[numero - 1].to_image(resolution=dpi).save(str(arquivo))
                criados.append(arquivo)
    except Exception:
        return criados
    return criados
