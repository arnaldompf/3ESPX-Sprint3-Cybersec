"""Conector PBE/Inmetro: o consumo **medido**, atribuído à versão certa.

O consumo é o campo mais citado numa conversa de venda e o mais fácil de errar. A frase do
PBEV aparece no rodapé das páginas das montadoras, uma por configuração, e a mesma página
traz **quatro** delas — cada uma de uma versão diferente. Ler a primeira que aparece daria
9,3 km/l para uma SRX Plus que faz 9,7, com evidência que groundeia perfeitamente. Errado
com procedência: o pior defeito que este projeto pode produzir.

Por isso o conector **casa a versão dentro da própria frase** e recusa quando a frase
identifica outra versão. Recusar é resultado: o campo fica `nao_encontrado` com as fontes
consultadas, e não com o número do vizinho.

**Duas fontes, nesta ordem.** A primeira é a **tabela anual do programa** (`docs/12`
§6.3): :func:`baixar_tabela` a busca no gov.br e :func:`consumo_na_tabela` recorta a
linha da versão — a linha inteira vira a evidência, com o nome do veículo e os dois
números lado a lado. A segunda é o **fallback**: a frase do PBEV nas páginas oficiais
salvas, que é o que roda quando a tabela não lista a versão (a Ranger Raptor não está
lá: o ciclo 2026 só publica as Ranger diesel).

O download continua exigindo `autorizado=True`: 3,3 MB de rede que ninguém pediu não
saem de dentro de um teste.

Tier 2 e não 1: a medição é do Inmetro sob NBR 7024, não da montadora. É a mesma posição da
FIPE (`pipeline/connectors/fipe.py`), e por o mesmo motivo — fonte oficial, mas de terceiro.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

#: Tier da medição do PBE/Inmetro. Ver o docstring do módulo.
TIER_PBE = 2

#: `source_id` da **frase do PBEV na página da montadora**.
SOURCE_ID = "pbe_inmetro"

#: `source_id` da **tabela anual do programa**. Precisa ser outro, e o motivo é
#: concreto: o grounding confere a citação dentro do texto de `textos[source_id]`. Com
#: o mesmo id para as duas, o texto guardado era o da frase (103 caracteres) e a linha
#: da tabela não era localizada nele — o valor da tabela caía no grounding e sumia sem
#: reclamar. A divergência 9,7/10,6 (página da Toyota) × 9,3/10,0 (tabela do Inmetro)
#: simplesmente não aparecia.
SOURCE_ID_TABELA = "pbe_tabela"

#: A tabela anual do programa. Declarada para o dia em que a coleta ao vivo for autorizada.
URL_TABELA_ANUAL = "https://www.gov.br/inmetro/pt-br/assuntos/avaliacao-da-conformidade/programa-brasileiro-de-etiquetagem/tabelas-de-eficiencia-energetica-veiculos-automotivos-leves"

#: A página que **lista** os ciclos publicados. A URL de `URL_TABELA_ANUAL` responde 404
#: desde que o Inmetro moveu a seção para `regulamentacao/` (medido em 10/09/2026); esta
#: é a que responde 200, e é dela que sai o PDF do ciclo vigente.
URL_PAGINA_DOS_CICLOS = (
    "https://www.gov.br/inmetro/pt-br/assuntos/regulamentacao/avaliacao-da-conformidade/"
    "programa-brasileiro-de-etiquetagem/tabelas-de-eficiencia-energetica/"
    "veiculos-automotivos-pbe-veicular"
)

#: Como a tabela do PBE abrevia rótulos de versão. Sem isto, "Limited" nunca casaria com
#: `LTD` e o consumo oficial da Ranger de topo ficaria `nao_encontrado` com a linha
#: **na tela**. O mapa é explícito de propósito: cada entrada é uma leitura declarada,
#: e uma abreviação que não estiver aqui simplesmente não casa — não é adivinhada.
ABREVIACOES_DA_TABELA = {
    "ltd+": "limited plus",
    "ltd": "limited",
    "hc": "high country",
    "h.country": "high country",
    "p-up": "pick-up",
    "cd": "cabine dupla",
    "cs": "cabine simples",
    "ch": "chassi",
}

#: Como a tabela grafa a marca. `pipeline.connectors.ALIASES` canoniza para "Volkswagen"
#: e "Chevrolet"; a tabela do PBE escreve "VW" e "CHEVROLET". Sem este mapa, a Amarok
#: era recusada com "a tabela não lista nenhuma configuração de Volkswagen Amarok" — e a
#: linha estava lá, com o consumo, escrita "Picape VW AMAROK V6 EXTREME (MY26)".
MARCAS_NA_TABELA = {
    "volkswagen": {"vw", "volkswagen"},
    "chevrolet": {"chevrolet", "gm"},
    "ford": {"ford"},
    "toyota": {"toyota"},
}


def _marca_na_linha(marca: str, tokens_da_linha: set[str]) -> bool:
    """A linha é desta marca? Aceita as grafias que a tabela usa. Ver `MARCAS_NA_TABELA`."""
    chave = " ".join(_tokens(marca))
    grafias = MARCAS_NA_TABELA.get(chave, {chave} if chave else set())
    return bool(grafias & tokens_da_linha)


#: A frase do PBEV, como as montadoras a escrevem.
#:
#: Duas variações reais no mesmo arquivo salvo: `"9,7km/l"` (sem espaço) e `"9,3 km/l"`
#: (com). O `\s?` cobre as duas.
#:
#: A descrição da versão vai **do início da linha** até "percorre", e a âncora de linha
#: corrigiu um defeito medido: a primeira versão usava `[^.\n]` para a descrição, e a
#: classe **excluía o ponto** — em "Hilux Diesel 4×4 SRX Plus (Wide Tread) 2.8 Automático"
#: a captura parava no ponto de "2.8" e sobrava `"8 Automático"`, que não casa com versão
#: nenhuma. As quatro frases eram recusadas com a mensagem certa e pelo motivo errado.
FRASE_PBEV = re.compile(
    r"(?P<descricao>[^\n]{3,240}?),?\s*percorre\s+"
    r"(?P<urbano>\d{1,2}(?:[,.]\d)?)\s?km/l\s+na\s+cidade\s+e\s+"
    r"(?P<rodoviario>\d{1,2}(?:[,.]\d)?)\s?km/l\s+na\s+estrada",
    re.IGNORECASE | re.MULTILINE,
)

#: Fim de uma frase do PBEV anterior, para o caso de duas na mesma linha.
FIM_DE_FRASE_ANTERIOR = re.compile(r"km/l\s+na\s+estrada\.?", re.IGNORECASE)

# POR QUE O PADRÃO NÃO ACEITA PARÁFRASE DE IMPRENSA.
#
# A redação exigida do PBEV é "percorre X km/l na cidade e Y km/l na estrada", e é ela que
# a montadora é obrigada a publicar. A imprensa reescreve: o snapshot da Amarok traz
# "A linha **2025** da caminhonete faz médias 8,7 km/l na cidade e 9,3 km/l na rodovia" —
# e a frase **anterior** diz "Os números de consumo da Amarok 2026 não foram revelados".
#
# Aceitar "faz médias ... na rodovia" pegaria aquele par e o atribuiria ao ano-modelo 2026,
# contra o que a própria fonte afirma, a 120 caracteres de distância da negação. O campo
# fica `nao_encontrado`, que é a resposta certa: o consumo de 2026 não foi publicado.
#
# Alargar este padrão é um pedido que vai aparecer ("está ali, na página!"). A resposta é
# esta nota.

#: Palavras que aparecem em toda frase do PBEV e não distinguem versão nenhuma.
#:
#: Sem esta lista, "Diesel" ou "Automático" casariam qualquer versão com qualquer frase — e
#: o casamento por sobreposição de tokens viraria sorteio.
TOKENS_GENERICOS = frozenset(
    {
        "diesel",
        "gasolina",
        "flex",
        "automatico",
        "manual",
        "at",
        "mt",
        "cabine",
        "dupla",
        "simples",
        "4x4",
        "4x2",
        "4wd",
        "2wd",
        "awd",
        "4",
        "wide",
        "tread",
        "power",
        "pack",
        "e",
        "de",
        "da",
        "do",
        "com",
        "km",
        "l",
    }
)


class ColetaNaoDisponivel(RuntimeError):
    """A coleta ao vivo da tabela anual não está disponível neste ambiente."""


@dataclass(frozen=True)
class TabelaPublicada:
    """O PDF de um ciclo do PBE, com o rótulo que a página do Inmetro dá a ele."""

    url: str
    rotulo: str
    ciclo: str = ""
    tamanho_declarado: str = ""


#: `<a href="...pdf/@@download/file"> ... Tabela PBEV 2026_25_AGO.pdf ... – 3308 KB`
_ANCORA_DE_PDF = re.compile(
    r'<a\s+href="(?P<url>[^"]*?\.pdf/@@download/file)"[^>]*>(?P<rotulo>.*?)</a>'
    r"(?:\s*<span[^>]*>\s*(?P<tamanho>[^<]*?)\s*</span>)?",
    re.IGNORECASE | re.DOTALL,
)
#: `<a class="summary url" href="...">Veículos leves 2026 - 18º Ciclo</a>`
_TITULO_DE_CICLO = re.compile(
    r'<a[^>]*class="summary url"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<titulo>[^<]+)</a>',
    re.IGNORECASE,
)


def _nome_do_arquivo(url: str) -> str:
    """`.../x.pdf/view` e `.../x.pdf/@@download/file` devolvem os dois `x.pdf`.

    É a chave que liga o **título do ciclo** (que está no link `/view`) ao **anexo**
    (que está no link `/@@download/file`). Sem remover o `/view` antes de cortar pelo
    último `/`, a chave virava a palavra `view` para todos os ciclos, os títulos não
    ligavam a anexo nenhum, e `ciclo` saía vazio em todas as linhas.
    """
    limpo = url.split("/@@download")[0].removesuffix("/view").rstrip("/")
    return limpo.rsplit("/", 1)[-1]


def descobrir_tabelas(html: str) -> list[TabelaPublicada]:
    """Os PDFs de tabela anunciados na página dos ciclos, do mais novo para o mais velho.

    "Mais novo" é o **ano no título do ciclo**, não a ordem do HTML: a página lista os
    ciclos em ordem de publicação, e o Inmetro republica ciclo antigo quando corrige
    algo. O ano do título é o que diz de que linha a tabela fala.
    """
    titulos = {
        _nome_do_arquivo(m.group("url")): m.group("titulo").strip()
        for m in _TITULO_DE_CICLO.finditer(html)
    }
    achadas: list[TabelaPublicada] = []
    for m in _ANCORA_DE_PDF.finditer(html):
        url = m.group("url")
        arquivo = _nome_do_arquivo(url)
        rotulo = " ".join(re.sub(r"<[^>]+>", " ", m.group("rotulo")).split())
        achadas.append(
            TabelaPublicada(
                url=url,
                rotulo=rotulo,
                ciclo=titulos.get(arquivo, ""),
                tamanho_declarado=" ".join((m.group("tamanho") or "").split()),
            )
        )

    def ano_do_ciclo(t: TabelaPublicada) -> int:
        # `(?<!\d)…(?!\d)` e não `\b`: o rótulo real é "Tabela PBEV 2026_25_AGO.pdf", e
        # `\b` não casa entre "2026" e "_" porque `_` é caractere de palavra. Com `\b`
        # o ciclo de 2026 valia 0, a lista devolvia a máscara de 2025 em primeiro, o
        # download trazia o PDF errado — e o parser lia **0 configurações** sem erro
        # nenhum, que é a forma mais cara de falhar neste projeto.
        anos = [int(a) for a in re.findall(r"(?<!\d)(20\d{2})(?!\d)", f"{t.ciclo} {t.rotulo}")]
        return max(anos) if anos else 0

    return sorted(achadas, key=ano_do_ciclo, reverse=True)


def baixar_tabela(*, autorizado: bool = False, url: str = "") -> bytes:
    """O PDF da tabela do PBE. **Não executa** sem autorização explícita.

    A autorização continua explícita porque baixar 3,3 MB do gov.br é rede que ninguém
    pediu quando se está só rodando teste. Com `autorizado=True`, o caminho é real:
    descobre o ciclo vigente em :data:`URL_PAGINA_DOS_CICLOS` e baixa o PDF, com
    robots.txt e 1 req/s como qualquer outra coleta.
    """
    if not autorizado:
        raise ColetaNaoDisponivel(
            "coleta ao vivo da tabela do PBE não executada. Para habilitar: "
            "`baixar_tabela(autorizado=True)` (o parse usa o motor de PDF disponível, "
            "`uv sync --extra pdf` dá o pdfplumber, que preserva a grade). A lista de "
            f"ciclos está em {URL_PAGINA_DOS_CICLOS}. Sem isso, o consumo vem da frase "
            "do PBEV nos snapshots salvos das páginas oficiais (fallback, tier 2)."
        )

    from pipeline.fetch import http

    alvo = url
    if not alvo:
        indice = http.fetch(URL_PAGINA_DOS_CICLOS)
        if not indice.ok:
            raise ColetaNaoDisponivel(
                f"a página dos ciclos do PBE respondeu {indice.status}: {indice.motivo}"
            )
        tabelas = descobrir_tabelas(indice.texto)
        if not tabelas:
            raise ColetaNaoDisponivel(f"nenhum PDF de tabela anunciado em {URL_PAGINA_DOS_CICLOS}")
        alvo = tabelas[0].url

    resposta = http.fetch(alvo, usar_cache=False)
    if not resposta.ok:
        raise ColetaNaoDisponivel(f"o PDF do PBE respondeu {resposta.status}: {resposta.motivo}")
    if not resposta.conteudo.startswith(b"%PDF-"):
        raise ColetaNaoDisponivel(f"{alvo} não devolveu um PDF")
    return resposta.conteudo


def _tokens(texto: str) -> set[str]:
    """Tokens normalizados e **sem os genéricos**. Ver `TOKENS_GENERICOS`."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c)
    )
    brutos = re.findall(r"[a-z0-9]+", sem_acento)
    return {t for t in brutos if t not in TOKENS_GENERICOS}


@dataclass
class RegistroPbe:
    """Uma frase do PBEV: a versão que ela descreve e os dois consumos."""

    descricao: str
    urbano_kml: float
    rodoviario_kml: float
    trecho: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "descricao": self.descricao,
            "consumo_urbano_kml": self.urbano_kml,
            "consumo_rodoviario_kml": self.rodoviario_kml,
            "trecho": self.trecho,
        }


def _para_float(texto: str) -> float:
    return float(texto.replace(",", "."))


def parse(texto: str) -> list[RegistroPbe]:
    """Todas as frases do PBEV no texto, uma por configuração."""
    registros: list[RegistroPbe] = []
    for achado in FRASE_PBEV.finditer(texto):
        # Duas frases do PBEV na mesma linha: corta o que sobrou da anterior, senão a
        # descrição desta carregaria a versão da outra e o casamento ficaria ambíguo.
        pedacos = FIM_DE_FRASE_ANTERIOR.split(achado.group("descricao"))
        registros.append(
            RegistroPbe(
                descricao=" ".join(pedacos[-1].split()),
                urbano_kml=_para_float(achado.group("urbano")),
                rodoviario_kml=_para_float(achado.group("rodoviario")),
                # O trecho verbatim é a evidência. Cortado na frase, não no parágrafo:
                # o parágrafo inteiro traz o aviso da NBR e não localiza o número.
                trecho=" ".join(achado.group(0).split()),
            )
        )
    return registros


@dataclass
class ResultadoPbe:
    """O consumo da versão pedida, ou o motivo de não haver.

    `motivo` preenchido com `registro=None` é resultado legítimo: significa "a página traz
    consumo, mas de outras versões" — que é diferente de "a página não fala de consumo", e
    a diferença é exatamente a dos dois vazios do projeto.
    """

    registro: RegistroPbe | None = None
    motivo: str = ""
    candidatos: list[str] = field(default_factory=list)

    @property
    def tem_valor(self) -> bool:
        return self.registro is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "registro": self.registro.to_dict() if self.registro else None,
            "motivo": self.motivo,
            "candidatos": list(self.candidatos),
        }


def casar(registros: list[RegistroPbe], *, versao: str, modelo: str = "") -> ResultadoPbe:
    """Escolhe o registro da versão pedida, ou recusa **com o motivo**.

    O critério é sobreposição de tokens distintivos (sem os genéricos), e a exigência é
    dura: **todos** os tokens distintivos da versão têm de estar na descrição da frase. Uma
    correspondência parcial escolheria a "SRX" quando se pediu a "SRX Plus" — as duas
    existem na mesma página, com consumos diferentes.
    """
    if not registros:
        return ResultadoPbe(motivo="nenhuma frase do PBEV no texto consultado")

    alvo = _tokens(versao) - _tokens(modelo)
    if not alvo:
        return ResultadoPbe(
            motivo=(
                f"o nome da versão {versao!r} não tem token distintivo depois de remover os "
                "genéricos; sem isso o casamento seria sorteio"
            ),
            candidatos=[r.descricao for r in registros],
        )

    casados = [r for r in registros if alvo <= _tokens(r.descricao)]
    if not casados:
        return ResultadoPbe(
            motivo=(
                f"a página traz consumo do PBEV, mas de outras versões: nenhuma frase "
                f"identifica {versao!r}. O campo fica `nao_encontrado` em vez de receber o "
                "número do vizinho."
            ),
            candidatos=[r.descricao for r in registros],
        )
    if len(casados) > 1:
        # Empate é recusa. Duas frases que servem para a mesma versão significam que o
        # critério não distingue o suficiente, e escolher uma seria decidir por sorteio.
        return ResultadoPbe(
            motivo=(
                f"{len(casados)} frases do PBEV casam com {versao!r}; sem critério para "
                "escolher, nenhuma é usada"
            ),
            candidatos=[r.descricao for r in casados],
        )
    return ResultadoPbe(registro=casados[0], candidatos=[r.descricao for r in registros])


def consumo_de(texto: str, *, versao: str, modelo: str = "") -> ResultadoPbe:
    """`parse` + `casar` num passo. É o que o pipeline chama."""
    return casar(parse(texto), versao=versao, modelo=modelo)


# ------------------------------------------------------------- a tabela oficial
#: Um trio de decimais em sequência: `urbano rodoviário combinado`, na ordem da tabela.
#: Combustível flex traz **dois** trios (etanol e depois gasolina) e o que se cita é o
#: segundo; diesel e gasolina puros trazem um só. Por isso o parser usa o **último**.
_TRIO_DE_CONSUMO = re.compile(r"(?<![\d,])(\d{1,2},\d)\s+(\d{1,2},\d)\s+(\d{1,2},\d)(?![\d,])")
#: Onde a descrição do veículo acaba: a coluna "Tipo de Propulsão".
_FIM_DA_DESCRICAO = re.compile(r"\s+(Combust[ãa]o|El[ée]trico|H[íi]brido)\b", re.IGNORECASE)
#: A categoria abre a linha. Só as que interessam ao projeto entram — a tabela tem 20.
_CATEGORIA = re.compile(
    r"^(Picape|Comercial|Fora de Estrada\s*\w*|Utilit[áa]rio\s*\w*)\s+", re.IGNORECASE
)


def linhas_da_tabela(dados: bytes) -> list[str]:
    """As linhas do PDF da tabela, reconstruídas do posicionamento dos caracteres.

    Duas coisas quebram o `extract_text` normal neste PDF, e as duas são tratadas aqui:

    * **cada glifo é pintado três vezes** com deslocamento sub-pixel (efeito de sombra do
      gerador). Sem deduplicar, "Picape" sai `"PPiiccaappee"` e nenhum nome casa. A chave
      da deduplicação é `(caractere, x, y)` arredondados — remove a repetição exata, e
      **não** dois caracteres iguais vizinhos de verdade;
    * **as linhas ficam a menos de 2pt umas das outras**, e o agrupamento padrão junta
      duas linhas de veículos diferentes numa só — que é como o consumo de um vira o
      consumo do outro. O agrupamento aqui é por faixa de 1,5pt.

    O texto que sai daqui é o que vai para o snapshot: o grounding confere a citação
    contra ele, e o `raw.pdf` fica ao lado para quem quiser reconferir no original.
    """
    import pdfplumber

    saida: list[str] = []
    with pdfplumber.open(io.BytesIO(dados)) as documento:
        for pagina in documento.pages:
            vistos: set[tuple] = set()
            unicos = []
            for c in pagina.chars:
                chave = (c["text"], round(c["x0"] / 0.6), round(c["top"] / 0.6))
                if chave in vistos:
                    continue
                vistos.add(chave)
                unicos.append(c)
            por_linha: dict[int, list] = {}
            for c in unicos:
                por_linha.setdefault(round(c["top"] / 1.5), []).append(c)
            for chave in sorted(por_linha):
                ordenados = sorted(por_linha[chave], key=lambda c: c["x0"])
                partes: list[str] = []
                anterior = None
                for c in ordenados:
                    if anterior is not None and c["x0"] - anterior["x1"] > 1.2:
                        partes.append(" ")
                    partes.append(c["text"])
                    anterior = c
                linha = "".join(partes).strip()
                if linha:
                    saida.append(linha)
    return saida


def parse_tabela(linhas: list[str]) -> list[RegistroPbe]:
    """As linhas de veículo da tabela, uma por configuração publicada.

    Só entram linhas que tenham **categoria reconhecida, descrição e um trio de
    consumos**. Linha de cabeçalho, de rodapé e de legenda não têm as três coisas, e
    ficam de fora sem precisar de lista de exceção.
    """
    registros: list[RegistroPbe] = []
    for linha in linhas:
        if not _CATEGORIA.match(linha):
            continue
        corte = _FIM_DA_DESCRICAO.search(linha)
        if not corte:
            continue
        descricao = " ".join(linha[: corte.start()].split())
        trios = _TRIO_DE_CONSUMO.findall(linha[corte.end() :])
        if not trios:
            continue
        urbano, rodoviario, _combinado = trios[-1]
        registros.append(
            RegistroPbe(
                descricao=descricao,
                urbano_kml=_para_float(urbano),
                rodoviario_kml=_para_float(rodoviario),
                # A linha inteira é a evidência: é ela que contém o número e o nome do
                # veículo lado a lado. Recortar só o trio deixaria o número sem dono.
                trecho=" ".join(linha.split()),
            )
        )
    return registros


def _tokens_da_tabela(texto: str) -> set[str]:
    """`_tokens`, mas com as abreviações da tabela expandidas antes. Ver o mapa."""
    minusculo = texto.lower()
    for abreviado, extenso in ABREVIACOES_DA_TABELA.items():
        minusculo = re.sub(rf"(?<![\w.]){re.escape(abreviado)}(?![\w])", extenso, minusculo)
    return _tokens(minusculo)


def casar_na_tabela(
    registros: list[RegistroPbe], *, versao: str, modelo: str = "", marca: str = ""
) -> ResultadoPbe:
    """Escolhe a linha da tabela que descreve a versão pedida.

    Por que não reusar :func:`casar`: aquele critério é "todos os tokens do pedido estão
    na descrição", e na tabela isso empata sempre. `LTD` e `LTD+` são duas linhas com
    consumos diferentes, e as duas contêm os tokens de "Limited 3.0 V6" — a regra de lá
    devolveria "2 frases casam, nenhuma é usada" para **toda** versão de topo.

    A regra daqui é bidirecional: o pedido tem de estar **inteiro** no candidato (senão
    não é a versão), e vence o candidato cujo **rótulo de versão** tenha menos sobra em
    relação ao pedido. `LTD` → "limited" não sobra nada; `LTD+` → "limited plus" sobra
    "plus". Empate no melhor continua sendo recusa.
    """
    if not registros:
        return ResultadoPbe(motivo="a tabela do PBE não trouxe nenhuma linha de veículo")

    genericos_do_contexto = _tokens_da_tabela(modelo) | set(
        MARCAS_NA_TABELA.get(" ".join(_tokens(marca)), _tokens_da_tabela(marca))
    )
    alvo = _tokens_da_tabela(versao) - genericos_do_contexto
    if not alvo:
        return ResultadoPbe(
            motivo=(
                f"o nome da versão {versao!r} não tem token distintivo depois de remover "
                "modelo, marca e genéricos; sem isso o casamento seria sorteio"
            )
        )

    do_modelo = [
        r
        for r in registros
        if _tokens_da_tabela(modelo) <= _tokens_da_tabela(r.descricao)
        and (not marca or _marca_na_linha(marca, _tokens_da_tabela(r.descricao)))
    ]
    if not do_modelo:
        return ResultadoPbe(
            motivo=(
                f"a tabela do PBE não lista nenhuma configuração de {marca} {modelo}. "
                "Consumo `nao_encontrado` — a tabela não afirma ausência, só não o traz."
            )
        )

    candidatos = []
    for r in do_modelo:
        tokens = _tokens_da_tabela(r.descricao) - genericos_do_contexto
        if not alvo <= tokens:
            continue
        candidatos.append((len(tokens - alvo), r))
    if not candidatos:
        return ResultadoPbe(
            motivo=(
                f"a tabela do PBE lista {len(do_modelo)} configuração(ões) de {modelo}, "
                f"mas nenhuma identifica {versao!r}. O campo fica `nao_encontrado` em vez "
                "de receber o número do vizinho."
            ),
            candidatos=[r.descricao for r in do_modelo],
        )

    melhor = min(sobra for sobra, _ in candidatos)
    empatados = [r for sobra, r in candidatos if sobra == melhor]
    if len(empatados) > 1:
        return ResultadoPbe(
            motivo=(
                f"{len(empatados)} linhas da tabela do PBE descrevem {versao!r} igualmente "
                "bem; sem critério para escolher, nenhuma é usada"
            ),
            candidatos=[r.descricao for r in empatados],
        )
    return ResultadoPbe(registro=empatados[0], candidatos=[r.descricao for r in do_modelo])


def consumo_na_tabela(
    dados_ou_linhas: bytes | list[str], *, versao: str, modelo: str = "", marca: str = ""
) -> tuple[ResultadoPbe, list[str]]:
    """Da tabela ao consumo da versão, num passo. Devolve `(resultado, linhas)`.

    As linhas voltam junto porque é **elas** que vão para o snapshot: guardar o resultado
    sem o texto de onde ele saiu deixaria a evidência sem original para conferir.
    """
    linhas = (
        linhas_da_tabela(dados_ou_linhas)
        if isinstance(dados_ou_linhas, bytes)
        else list(dados_ou_linhas)
    )
    return casar_na_tabela(parse_tabela(linhas), versao=versao, modelo=modelo, marca=marca), linhas


_DIRECOES_PBE = {"H": "Hidráulica", "M": "Mecânica", "E": "Elétrica", "E-H": "Eletro-hidráulica"}
_COLUNAS_ANTES_DIRECAO = re.compile(
    r"\s+(?:A|M|DCT|CVT|MTA)(?:\s*-\s*\d+)?\s+[SN]\s+"
    r"(?P<direcao>E-H|H|E|M)\s+[DFGE]\s+"
)


def _url_oficial_pbe(url: str) -> bool:
    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "www.gov.br"
            and parsed.port in {None, 443}
            and not parsed.username
            and not parsed.password
            and parsed.path.startswith("/inmetro/")
            and "veiculos-automotivos-pbe-veicular" in parsed.path
        )
    except ValueError:
        return False


def _direcao_da_linha(texto: str, linha: str) -> tuple[str, str, str] | None:
    """Lê transmissão, ar, direção e combustível; exige legenda do mesmo cabeçalho.

    A citação permanece a linha original. A legenda é outro trecho literal preservado
    nas notas e no snapshot; nunca fabricamos uma frase que junte trechos distantes.
    """
    if not linha or linha not in texto or len(linha) > 300:
        return None
    corte = _FIM_DA_DESCRICAO.search(linha)
    if not corte:
        return None
    columns = _COLUNAS_ANTES_DIRECAO.match(linha[corte.end() :])
    if not columns:
        return None
    codigo = columns.group("direcao")
    valor = _DIRECOES_PBE[codigo]
    anterior = texto[: texto.index(linha)]
    inicio = anterior.rfind("Transmissão")
    if inicio < 0:
        return None
    # O cabeçalho precede as linhas; não buscar uma legenda numa configuração vizinha.
    cabecalho = anterior[inicio:]
    primeira_linha = next(
        (
            m.start()
            for m in re.finditer(
                r"(?m)^(?:Picape|Comercial|Utilitário|Fora de Estrada)\s", cabecalho
            )
        ),
        len(cabecalho),
    )
    cabecalho = cabecalho[:primeira_linha]
    if not re.search(r"Direção[\s\S]{0,160}\bAssistida\b", cabecalho):
        return None
    nome = re.search(rf"(?<![\w-]){re.escape(valor)}\b", cabecalho)
    if nome is None:
        return None
    legenda = cabecalho[nome.start() : nome.end() + 300]
    simbolo = re.search(r"\((E-H|H|M|E)\)", legenda)
    if simbolo is None or simbolo.group(1) != codigo:
        return None
    return valor, codigo, legenda[: simbolo.end()]


def _linhas_exatas(texto: str, target: Any) -> list[str]:
    """O marcador MY encerra a versão; tokens extras como Plus não podem desaparecer."""
    if not target.ano_modelo:
        return []
    alvo = _tokens_da_tabela(f"{target.modelo} {target.versao}")
    casadas = []
    for linha in texto.splitlines():
        if not _CATEGORIA.match(linha):
            continue
        anos = list(re.finditer(r"\(MY\s*(\d{2}|20\d{2})\)", linha, re.I))
        if len(anos) != 1:
            continue
        my = anos[0]
        ano = int(my.group(1))
        if (ano + 2000 if ano < 100 else ano) != target.ano_modelo:
            continue
        identificacao = linha[: my.start()]
        tokens = _tokens_da_tabela(identificacao)
        if not _marca_na_linha(target.marca, tokens):
            continue
        contexto = _tokens_da_tabela(_CATEGORIA.match(linha).group(0)) | set(
            MARCAS_NA_TABELA.get(" ".join(_tokens(target.marca)), _tokens(target.marca))
        )
        if tokens - contexto != alvo:
            continue
        casadas.append(linha)
    return casadas


def candidatos_direcao(texto: str, url: str, target: Any) -> list[Any]:
    """Direção da linha oficial com marca, versão e MY explícitos; sem rede ou LLM."""
    from pipeline.extract.run import Candidato

    if not _url_oficial_pbe(url):
        return []
    casadas = _linhas_exatas(texto, target)
    if len(casadas) != 1:
        return []
    linha = casadas[0]
    proof = _direcao_da_linha(texto, linha)
    if proof is None:
        return []
    valor, codigo, legenda = proof
    return [
        Candidato(
            campo="direcao",
            valor=valor,
            valor_bruto=codigo,
            quote=linha,
            origem="servico:pbe:direcao",
            source_id=SOURCE_ID_TABELA,
            source_text=texto,
            url=url,
            tier=TIER_PBE,
            de_celula=True,
            notas=(
                f"Direção Assistida: coluna após Ar Cond.; {codigo}={valor}. "
                f"Legenda literal: {legenda}"
            ),
        )
    ]


def direcao_comprovada(texto: str, quote: str, value: str, target: Any, url: str) -> bool:
    """Confere novamente linha, legenda e escopo a partir do texto original salvo."""
    return any(
        c.quote == quote and c.valor == value for c in candidatos_direcao(texto, url, target)
    )


def supports(field: str, target: Any, text: str, url: str, quote: str, value: Any) -> bool:
    """Prova tabular de direção/consumo, reaplicável à publicação e à auditoria.

    Não usar a ocorrência do ano em outra linha como identidade da célula. Consumo
    requer também os rótulos de cidade/estrada/quilometragem no original preservado.
    """
    if field == "direcao":
        return direcao_comprovada(text, quote, value, target, url)
    if field not in {"consumo_urbano_kml", "consumo_rodoviario_kml"}:
        return False
    if not _url_oficial_pbe(url) or isinstance(value, bool):
        return False
    linhas = _linhas_exatas(text, target)
    if len(linhas) != 1 or " ".join(quote.split()) != " ".join(linhas[0].split()):
        return False
    cabecalho = text[: text.index(linhas[0])]
    if not all(label in cabecalho for label in ("Quilometragem por Litro", "Cidade", "Estrada")):
        return False
    registros = parse_tabela(linhas)
    if len(registros) != 1:
        return False
    expected = (
        registros[0].urbano_kml if field == "consumo_urbano_kml" else registros[0].rodoviario_kml
    )
    try:
        return abs(float(value) - expected) < 1e-9
    except (TypeError, ValueError):
        return False


def documento_de(
    texto: str, *, versao: str, modelo: str = "", url: str = "", captured_at: str = ""
) -> Any:
    """A frase casada, embalada como `Documento` de extração em **tier 2**.

    Devolve `None` quando não há casamento. O documento carrega **só a frase da versão**,
    e é isso que faz o grounding conferir o número contra o texto certo: passar a página
    inteira deixaria as outras três frases disponíveis para o extrator.
    """
    from pipeline.extract.run import Documento

    resultado = consumo_de(texto, versao=versao, modelo=modelo)
    if not resultado.tem_valor or resultado.registro is None:
        return None
    return Documento(
        texto=resultado.registro.trecho,
        source_id=SOURCE_ID,
        url=url or URL_TABELA_ANUAL,
        tier=TIER_PBE,
        captured_at=captured_at,
    )
