"""Renderiza o relatório: PDF pelo primeiro motor que funciona, HTML se nenhum funcionar.

**A ordem dos motores é declarada, e o motor usado fica registrado.** São três degraus:

1. **`weasyprint`** — é o motor previsto pela spec (`specs/WP-28.md`) e o que dá o desenho
   mais fiel ao CSS da tela. Ele depende de bibliotecas **nativas** (GTK/Pango/Cairo) que
   não existem neste Windows: o import levanta `OSError`, não `ImportError`;
2. **`xhtml2pdf`** — motor de reserva, Python puro (reportlab). Entende um subconjunto de
   CSS, e por isso recebe o **mesmo documento com um CSS mais simples**
   (`html.CSS_XHTML2PDF`). Simplifica o estilo, nunca o conteúdo: o HTML continua sendo a
   fonte única, e nenhuma seção, número, fonte ou aviso muda de um motor para o outro;
3. **HTML** — último recurso. Não é um PDF vazio com status "concluído" (alguém abriria o
   link na frente do cliente) nem um job que falha escondendo um documento pronto: é o
   `.html` gravado **com o motivo por escrito**, dizendo o que falta e como habilitar.

Quem gerou o arquivo vai no resultado (`motor`, `renderizador`) e daí para o payload do
job. Proveniência de arquivo não é adivinhação — a mesma regra que vale para os dados vale
para o documento que os carrega.

Os dois motores são **extras opcionais** (`uv sync --extra pdfgen`). Com o extra ausente o
código não estoura e não silencia: devolve o degrau que sobrou e o motivo de cada motor
descartado.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]

#: Onde os relatórios ficam. Dentro de `data/`, que é diretório de artefato gerado.
DIRETORIO = RAIZ / "data" / "reports"

#: A ordem de tentativa, **em ordem de preferência**. WeasyPrint é o previsto; o
#: `xhtml2pdf` é a reserva. Depois destes dois vem o HTML, que não é motor de PDF e por
#: isso não está na lista.
MOTORES: tuple[str, ...] = ("weasyprint", "xhtml2pdf")

#: O que dizer quando **nenhum** motor de PDF pôde renderizar. Diz o que falta em cada um
#: e como habilitar — um "não foi possível gerar o PDF" seco manda o leitor adivinhar.
MOTIVO_SEM_PDF = (
    "PDF não gerado: nenhum motor disponível. O WeasyPrint precisa das bibliotecas nativas "
    "(GTK/Pango/Cairo), que não existem em todo Windows — instale o GTK "
    "(https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows) ou, em "
    "Linux, `apt install libpango-1.0-0 libpangoft2-1.0-0`. O motor de reserva xhtml2pdf é "
    "Python puro e não precisa de nada nativo: `uv sync --extra pdfgen` o instala. O "
    "relatório foi gravado em HTML, com exatamente o mesmo conteúdo."
)


@dataclass
class MotorDePdf:
    """Um motor da lista: se dá para usar aqui e, quando não dá, por quê."""

    nome: str
    disponivel: bool
    motivo: str = ""
    versao: str = ""


@dataclass
class Resultado:
    """O arquivo gerado, o formato, **quem gerou** e o motivo, quando houver."""

    caminho: Path
    formato: str
    """`pdf` ou `html`."""
    renderizador: str
    """O motor com a versão, para o payload do job: `xhtml2pdf 0.2.18`."""
    motivo: str = ""
    bytes_gerados: int = 0
    motor: str = ""
    """Só o nome do motor, legível por máquina: `weasyprint`, `xhtml2pdf` ou `html`."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "caminho": str(self.caminho),
            "arquivo": self.caminho.name,
            "formato": self.formato,
            "motor": self.motor,
            "renderizador": self.renderizador,
            "motivo": self.motivo,
            "bytes": self.bytes_gerados,
        }


def recusar_recurso_externo(uri: str, rel: str = "") -> str:
    """Recusa qualquer recurso citado pelo documento. **A geração não vai à rede.**

    Passada ao `xhtml2pdf` como `link_callback`, é o que garante que nenhuma fonte, folha
    de estilo ou imagem de fora entre no PDF: o documento do cliente é montado só com o que
    já está no processo. Hoje ele não cita recurso nenhum; se algum dia citar, isto falha
    alto e o degrau seguinte assume — em vez de uma requisição silenciosa no meio de uma
    conversa de venda.
    """
    raise ValueError(f"recurso externo recusado na geração do PDF: {uri!r} (rel={rel!r})")


def weasyprint_disponivel() -> tuple[bool, str]:
    """`(disponível, motivo)`. Não levanta: a checagem é parte da resposta.

    O import do `weasyprint` **executa** o carregamento das bibliotecas nativas e pode
    levantar `OSError` — não só `ImportError`. Capturar `Exception` aqui é deliberado: o
    objetivo é decidir o formato, e qualquer falha de import significa "não dá".
    """
    try:
        import weasyprint  # noqa: F401
    except Exception as exc:  # pragma: no cover - depende do sistema
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def xhtml2pdf_disponivel() -> tuple[bool, str]:
    """`(disponível, motivo)` do motor de reserva. Também não levanta.

    É Python puro, então aqui o "não dá" quase sempre quer dizer "o extra `pdfgen` não foi
    instalado" — e é isso que o motivo tem de dizer.
    """
    try:
        from xhtml2pdf import pisa  # noqa: F401
    except Exception as exc:  # pragma: no cover - depende do ambiente
        return False, f"{type(exc).__name__}: {exc} (instale com `uv sync --extra pdfgen`)"
    return True, ""


def _versao_do_xhtml2pdf() -> str:
    import xhtml2pdf

    return str(getattr(xhtml2pdf, "__version__", "") or "")


def _gerar_com_weasyprint(documento: str, caminho: Path) -> str:
    import weasyprint

    weasyprint.HTML(string=documento).write_pdf(target=str(caminho))
    return f"weasyprint {weasyprint.__version__}"


def _gerar_com_xhtml2pdf(documento: str, caminho: Path) -> str:
    """Renderiza com o motor de reserva, trocando **só o CSS** do documento."""
    from xhtml2pdf import pisa

    from pipeline.report import html as gerador

    simples = gerador.com_css(documento, gerador.CSS_XHTML2PDF)
    with caminho.open("wb") as saida:
        estado = pisa.CreatePDF(
            src=simples,
            dest=saida,
            encoding="utf-8",
            link_callback=recusar_recurso_externo,
        )
    if estado.err:
        raise RuntimeError(f"xhtml2pdf relatou {estado.err} erro(s) na renderização")
    return f"xhtml2pdf {_versao_do_xhtml2pdf()}".strip()


#: Cada motor: como checar se dá, e como gerar. A ordem de uso é a de :data:`MOTORES`.
_IMPLEMENTACOES: dict[str, tuple[Any, Any]] = {
    "weasyprint": (weasyprint_disponivel, _gerar_com_weasyprint),
    "xhtml2pdf": (xhtml2pdf_disponivel, _gerar_com_xhtml2pdf),
}


def motores_de_pdf(motores: tuple[str, ...] | None = None) -> list[MotorDePdf]:
    """A lista de motores **na ordem de preferência**, com disponibilidade e motivo.

    Serve para o diagnóstico (o `verify` e o ensaio da demo imprimem isto) e para nenhuma
    resposta ficar com um "não dá" sem justificativa ao lado.
    """
    lista: list[MotorDePdf] = []
    for nome in motores if motores is not None else MOTORES:
        implementacao = _IMPLEMENTACOES.get(nome)
        if implementacao is None:
            lista.append(MotorDePdf(nome=nome, disponivel=False, motivo="motor desconhecido"))
            continue
        disponivel, motivo = implementacao[0]()
        versao = ""
        if disponivel and nome == "xhtml2pdf":
            versao = _versao_do_xhtml2pdf()
        elif disponivel:  # pragma: no cover - depende do sistema
            import weasyprint

            versao = str(weasyprint.__version__)
        lista.append(MotorDePdf(nome=nome, disponivel=disponivel, motivo=motivo, versao=versao))
    return lista


def _motivo_do_reserva(nome: str, descartados: list[str]) -> str:
    """Por que o arquivo saiu de um motor que não é o primeiro da lista."""
    if not descartados:
        return ""
    return (
        f"PDF gerado pelo motor de reserva {nome}: o WeasyPrint, que é o motor previsto, "
        f"não pôde renderizar aqui. O conteúdo é o mesmo — só o CSS é mais simples. "
        f"Detalhe: {'; '.join(descartados)}"
    )


def renderizar(
    html: str,
    nome: str,
    *,
    diretorio: Path | None = None,
    motores: tuple[str, ...] | None = None,
) -> Resultado:
    """Grava o relatório. PDF pelo primeiro motor que funcionar; HTML se nenhum, **com o
    motivo**.

    `motores` existe para o teste percorrer os degraus (inclusive o de baixo, com `()`) sem
    depender de qual biblioteca está instalada na máquina.
    """
    destino = diretorio or DIRETORIO
    destino.mkdir(parents=True, exist_ok=True)

    descartados: list[str] = []
    for motor in motores_de_pdf(motores):
        if not motor.disponivel:
            descartados.append(f"{motor.nome}: {motor.motivo}")
            continue
        caminho = destino / f"{nome}.pdf"
        try:
            renderizador = _IMPLEMENTACOES[motor.nome][1](html, caminho)
        except Exception as exc:  # pragma: no cover - falha de renderização
            # Um `.pdf` truncado no disco é pior que nenhum: alguém o abriria na frente do
            # cliente. Apaga e desce um degrau, levando o motivo.
            caminho.unlink(missing_ok=True)
            descartados.append(f"{motor.nome}: {type(exc).__name__}: {exc}")
            continue
        return Resultado(
            caminho=caminho,
            formato="pdf",
            motor=motor.nome,
            renderizador=renderizador,
            motivo=_motivo_do_reserva(motor.nome, descartados),
            bytes_gerados=caminho.stat().st_size,
        )

    caminho = destino / f"{nome}.html"
    caminho.write_text(html, encoding="utf-8", newline="\n")
    detalhe = f" Detalhe: {'; '.join(descartados)}" if descartados else ""
    return Resultado(
        caminho=caminho,
        formato="html",
        motor="html",
        renderizador="html (fallback)",
        motivo=f"{MOTIVO_SEM_PDF}{detalhe}",
        bytes_gerados=caminho.stat().st_size,
    )
