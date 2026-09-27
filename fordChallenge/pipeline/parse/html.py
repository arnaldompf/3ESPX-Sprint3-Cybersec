"""Limpeza do markdown de página — tirar o que não é informação do veículo.

O markdown que sai da coleta traz menu, banner de cookies, rodapé jurídico e texto de
concessionária. Isso atrapalha de duas formas concretas:

* infla o texto enviado ao LLM (custo por token, e `docs/05` limita o chunk a 12k);
* **e é onde estão os falsos positivos**: o rodapé jurídico da VW tem a frase "preços
  públicos sugeridos estão em reais (R$)", e a política de cookies fala de "Aviso" e
  "Política". Um regex de preço solto acha número no rodapé; um extrator de itens acha
  "Consulte a concessionária" como equipamento.

Duas garantias que a limpeza **precisa** ter, porque o grounding depende disso:

1. **Nunca reescreve o que sobra.** As linhas mantidas ficam byte a byte iguais às do
   original, para que o `evidence_quote` continue localizável no texto salvo.
2. **Registra o que tirou.** `Limpeza.removidas` diz quantas linhas e por qual regra —
   limpeza silenciosa que engole uma especificação é indistinguível de fonte incompleta.
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass, field

#: Linhas de navegação e de chamada para ação. Casam a linha **inteira** (após strip),
#: nunca um pedaço: "Performance" sozinho é menu, mas dentro de uma frase é conteúdo.
NAVEGACAO = {
    "menu",
    "buscar",
    "pesquisar",
    "fechar",
    "voltar",
    "início",
    "inicio",
    "home",
    "sobre",
    "performance",
    "conforto",
    "design",
    "acessórios",
    "acessorios",
    "solicitar contato",
    "fale conosco",
    "monte o seu",
    "encontre um concessionário",
    "encontre uma concessionária",
    "agende um test drive",
    "test drive",
    "saiba mais",
    "veja mais",
    "ver mais",
    "leia mais",
    "compartilhar",
    "imprimir",
    "voltar ao topo",
    "cookies",
    "aceitar",
    "aceitar todos",
    "aceitar todos os cookies",
    "rejeitar",
    "configurar cookies",
    "gerenciar cookies",
    "aviso de privacidade",
    "política de cookies",
    "politica de cookies",
    "política de privacidade",
    "politica de privacidade",
    "informações legais",
    "informacoes legais",
    "termos de uso",
    "mapa do site",
    "trabalhe conosco",
    "imprensa",
    "investidores",
}

#: Prefixos/frases que marcam bloco jurídico ou promocional. Casam por conteúdo porque
#: aparecem no meio de parágrafos longos.
RUIDO = (
    "imagem meramente ilustrativa",
    "imagens meramente ilustrativas",
    "consulte as condições e modelos disponíveis",
    "consulte uma concessionária",
    "consulte a concessionária",
    "cada concessionária tem a liberdade de praticar",
    "sujeitos a alterações sem aviso prévio",
    "no trânsito, enxergar o outro salva vidas",
    "desacelere. seu bem maior é a vida",
    "utilizamos cookies",
    "este site utiliza cookies",
    "ao continuar navegando",
    "alerta aos consumidores",
    "fique atento aos possíveis golpes",
    "não estão autorizados a importar",
    "siga-nos",
    "redes sociais",
    "todos os direitos reservados",
)

#: Linhas de social/contato que não carregam especificação.
SOCIAL = re.compile(
    r"^\s*(?:@[\w.]+|/[\w.-]+|(?:facebook|instagram|twitter|linkedin|youtube|tiktok)"
    r"(?:\.com)?[\w./-]*|sac:?\s*0800[\d\s-]*|[\w.+-]+@[\w.-]+\.\w+)\s*$",
    re.IGNORECASE,
)

#: Linha só com pontuação, separador ou marcador vazio.
VAZIA = re.compile(r"^\s*(?:[-–—*_=•·|]+|\[\s*\]|\(\s*\))\s*$")

#: Comprimento a partir do qual um parágrafo é considerado bloco jurídico quando
#: contém marca de rodapé. O rodapé da VW tem 2 mil caracteres numa linha só.
LIMITE_PARAGRAFO_JURIDICO = 400


@dataclass
class Limpeza:
    """Resultado da limpeza, com o rastro do que saiu."""

    texto: str
    removidas: list[tuple[str, str]] = field(default_factory=list)
    """`(regra, linha)` de cada linha descartada."""

    @property
    def n_removidas(self) -> int:
        return len(self.removidas)

    def por_regra(self) -> dict[str, int]:
        contagem: dict[str, int] = {}
        for regra, _ in self.removidas:
            contagem[regra] = contagem.get(regra, 0) + 1
        return contagem


def _e_navegacao(linha: str) -> bool:
    return linha.strip().lower().rstrip(".:") in NAVEGACAO


def _e_ruido(linha: str) -> bool:
    baixa = linha.lower()
    return any(marca in baixa for marca in RUIDO)


def limpar_markdown(texto: str, *, manter_cabecalho: bool = True) -> Limpeza:
    """Remove navegação, cookies e rodapé jurídico, **sem reescrever** o que fica.

    `manter_cabecalho` preserva as linhas de título e a linha `**URL:**` que a coleta
    grava no topo — é proveniência, não conteúdo de página.
    """
    mantidas: list[str] = []
    removidas: list[tuple[str, str]] = []

    for bruta in texto.splitlines():
        linha = bruta.rstrip()
        strip = linha.strip()

        if manter_cabecalho and (strip.startswith("**URL:**") or strip.startswith("# ")):
            mantidas.append(linha)
            continue

        if not strip:
            mantidas.append(linha)
            continue
        if VAZIA.match(strip):
            # separador de seção não é ruído: mantém, ajuda o chunking
            mantidas.append(linha)
            continue
        if _e_navegacao(strip):
            removidas.append(("navegacao", strip))
            continue
        if SOCIAL.match(strip):
            removidas.append(("social", strip))
            continue
        if _e_ruido(strip):
            regra = "juridico" if len(strip) >= LIMITE_PARAGRAFO_JURIDICO else "promocional"
            removidas.append((regra, strip))
            continue
        mantidas.append(linha)

    # colapsa sequências de linhas vazias que a remoção deixou para trás
    saida: list[str] = []
    for linha in mantidas:
        if not linha.strip() and saida and not saida[-1].strip():
            continue
        saida.append(linha)

    return Limpeza("\n".join(saida).strip() + "\n", removidas)


def limpar(texto: str, **kw) -> str:
    """Atalho que devolve só o texto limpo."""
    return limpar_markdown(texto, **kw).texto


# ------------------------------------------------------------------------- chunking
def dividir_em_blocos(texto: str, *, max_chars: int = 40_000) -> list[str]:
    """Parte o texto em blocos, sem cortar no meio de uma linha.

    `docs/05` limita o chunk a ~12k tokens e manda "tabelas inteiras". Aqui a unidade é a
    **linha**, e o corte acontece em linha vazia quando existe uma por perto — partir uma
    tabela ao meio destrói a relação entre cabeçalho e valor.
    """
    linhas = texto.splitlines()
    blocos: list[str] = []
    atual: list[str] = []
    tamanho = 0
    for linha in linhas:
        if tamanho + len(linha) + 1 > max_chars and atual:
            # recua até a última linha vazia, para não cortar tabela
            corte = len(atual)
            for i in range(len(atual) - 1, max(0, len(atual) - 40), -1):
                if not atual[i].strip():
                    corte = i
                    break
            blocos.append("\n".join(atual[:corte]).strip())
            atual = atual[corte:]
            tamanho = sum(len(x) + 1 for x in atual)
        atual.append(linha)
        tamanho += len(linha) + 1
    if atual:
        blocos.append("\n".join(atual).strip())
    return [b for b in blocos if b]


# ------------------------------------------------------------- HTML bruto -> texto
#: Elementos cujo conteúdo **nunca** é informação do veículo — e é de onde saem os números
#: falsos. Medido em 13/09/2026: "1.6l" e "5.5l" dentro de `<svg d="...">` viraram cilindrada.
_TAGS_SEM_CONTEUDO = (
    "script",
    "style",
    "svg",
    "noscript",
    "template",
    "iframe",
    "head",
    "canvas",
    "video",
    "audio",
    "picture",
    "source",
    "object",
)

#: Elementos que começam linha nova no texto. `tr` é tratado à parte (células por tabulação).
_BLOCOS = (
    "p",
    "div",
    "li",
    "ul",
    "ol",
    "dl",
    "dt",
    "dd",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "section",
    "article",
    "header",
    "footer",
    "nav",
    "aside",
    "main",
    "table",
    "thead",
    "tbody",
    "blockquote",
    "pre",
    "figcaption",
    "figure",
    "summary",
    "details",
    "form",
    "label",
    "option",
    "address",
    "hr",
)

_TAGS_DE_ESTRUTURA = re.compile(
    r"</?(?:div|p|span|a|li|ul|ol|table|tr|td|th|h[1-6]|section|article|nav|header|footer|img|br)\b",
    re.IGNORECASE,
)


def parece_html(texto: str) -> bool:
    """O texto é uma página HTML, e não markdown ou texto puro?

    Pela **estrutura**, não pela extensão do endereço: a página da montadora pode não
    terminar em `.html`, e um `a < b e c > d` solto num texto não é tag.
    """
    if not texto:
        return False
    amostra = texto[:6000].lower()
    if "<!doctype html" in amostra or "<html" in amostra or "<body" in amostra:
        return True
    return len(_TAGS_DE_ESTRUTURA.findall(amostra)) >= 3


def html_para_texto(html: str) -> str:
    """HTML cru em texto legível, uma linha por bloco, células de tabela por tabulação.

    **Por que aqui e não no `fetch`.** O pipeline clássico lê o markdown que o navegador
    salvou; o Pesquisador lê `resposta.text` da rede, e até 13/09/2026 entregava isso ao
    extrator sem converter. As citações gravadas traziam `<p class="...">`, e o fast-path
    achava número em caminho de SVG. Este texto é o que a gaveta de evidência mostra e o
    que o grounding confere: precisa ser o mesmo objeto que o extrator leu.

    Texto que **não** é HTML volta intacto — em replay, o `fetch` já devolve markdown.
    """
    if not html or not parece_html(html):
        return html
    from bs4 import BeautifulSoup

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - lxml ausente ou HTML muito quebrado
        soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(list(_TAGS_SEM_CONTEUDO)):
        tag.decompose()

    # `<br>` vem **antes** da tabela: numa célula de ficha a quebra separa dois valores
    # ("Dianteiro<br>Traseiro"), e ela precisa existir quando a célula virar texto.
    for br in soup.find_all("br"):
        br.replace_with(soup.new_string("\n"))

    # Linha de tabela: as células lado a lado, separadas por tabulação. É a forma que o
    # fast-path já lê ("Altura do veículo (mm)\t1922"), vinda do markdown do navegador.
    #
    # **Linha que contém outra tabela é layout, não ficha.** Sites de ficha antigos (ASP)
    # usam tabela como grade de página e aninham tudo dentro de uma `<table>`: a `<tr>`
    # externa contém as internas. Colapsá-la em "célula⇥célula" engolia a página inteira
    # numa linha — medido em 13/09/2026 na ficha da S10 do `carrosnaweb`: 13 mil caracteres
    # viravam **3 linhas** e o fast-path lia 2 campos. A linha de layout só ganha quebra
    # antes e depois, e o que está dentro dela é convertido por si.
    for tr in soup.find_all("tr"):
        if tr.find("table") is not None:
            tr.insert_before(soup.new_string("\n"))
            tr.insert_after(soup.new_string("\n"))
            continue
        celulas = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        tr.replace_with(soup.new_string("\n" + "\t".join(c for c in celulas if c) + "\n"))
    for tag in soup.find_all(list(_BLOCOS)):
        tag.insert_before(soup.new_string("\n"))
        tag.insert_after(soup.new_string("\n"))

    bruto = soup.get_text()
    linhas = [re.sub(r"[  ]+", " ", linha).strip() for linha in bruto.splitlines()]
    saida: list[str] = []
    vazias = 0
    for linha in linhas:
        if not linha:
            vazias += 1
            if vazias == 1 and saida:
                saida.append("")
            continue
        vazias = 0
        saida.append(linha)
    return "\n".join(saida).strip() + "\n"


#: `<meta charset="...">` ou `<meta http-equiv="Content-Type" content="...; charset=...">`,
#: nos bytes crus — nunca no texto já decodificado, que é exatamente o que pode estar errado.
_META_CHARSET = re.compile(rb'charset\s*=\s*["\']?\s*([a-zA-Z0-9_-]+)', re.IGNORECASE)


def meta_charset(conteudo: bytes) -> str:
    """Nome da codificação declarada nos primeiros 4 KB da página, ou `""` sem pista."""
    achado = _META_CHARSET.search(conteudo[:4096])
    return achado.group(1).decode("ascii", errors="ignore") if achado else ""


def decodificar_html(conteudo: bytes, declarado: str = "") -> str:
    """Bytes de página → texto, tentando em ordem: `<meta charset>` da própria página,
    `declarado` (ex.: o `Content-Type` do cabeçalho HTTP), utf-8 e por fim windows-1252
    — que aceita quase todo byte, cobrindo a maioria das páginas latinas sem `<meta>`
    explícito (o caso do `carrosnaweb`, que é windows-1252 e não declara charset no HTML).

    Nunca decodifica direto com ``errors="replace"``: um "�" no meio do texto salvo faz o
    `evidence_quote` verbatim deixar de casar, e o grounding falha em silêncio — sem
    avisar ninguém. Só cai em `errors="replace"` se **nenhuma** codificação candidata
    servir, o que indica bytes de fato corrompidos, não charset mal declarado.
    """
    vistos: set[str] = set()
    for nome in (meta_charset(conteudo), declarado, "utf-8", "cp1252"):
        if not nome:
            continue
        try:
            codec = codecs.lookup(nome).name
        except LookupError:
            continue
        if codec in vistos:
            continue
        vistos.add(codec)
        try:
            return conteudo.decode(codec)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("utf-8", errors="replace")
