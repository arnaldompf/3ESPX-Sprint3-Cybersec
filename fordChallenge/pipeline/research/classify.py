"""De uma URL de resultado de busca para um **tier** — com o motivo escrito ao lado.

O tier é a peça que faz o Pesquisador ser um instrumento de inteligência competitiva e não
um agregador de links: ele decide **em quem acreditar quando duas fontes discordam**, e a
ordem é a de `docs/05`:

* **T1** — o fabricante falando de si: site oficial, PDF de catálogo, configurador, sala
  de imprensa. É a fonte que o produto trata como verdade sobre o que a montadora oferece;
* **T2** — registro de terceiro com autoridade: FIPE (preço) e PBE/Inmetro (consumo
  medido). Não é o fabricante, e é por isso que vale: quando o número do Inmetro discorda
  do número da montadora, a tela mostra os dois;
* **T3** — imprensa especializada. Útil, e frequentemente a única que publica aceleração
  medida — mas nunca vence o oficial numa divergência;
* **T5** — qualquer outra coisa. Fórum, blog, agregador, classificado. Entra na lista de
  fontes consideradas **com o motivo do descarte**, e não na coleta.

**Regras primeiro, modelo depois, e isso não é economia — é honestidade.** Um domínio é um
fato verificável: `ford.com.br` é a Ford. Deixar um modelo de linguagem decidir isso seria
trocar uma certeza por uma probabilidade, e ainda pagar por ela. O modelo entra apenas
onde a regra não alcança, **uma vez por rodada** e não uma vez por URL, e o que ele devolve
é registrado como `INFERENCIA` com a regra à vista.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

#: O domínio oficial de cada marca que o projeto conhece.
#:
#: Uma marca fora deste mapa **não** deixa o Pesquisador sem T1: `dominio_parece_oficial`
#: casa o nome da marca contra o domínio, que é como quase toda montadora se registra
#: (`ram.com.br`, `mitsubishimotors.com.br`). O mapa existe para os casos em que o nome não
#: basta — `vw.com.br` não contém "volkswagen", e `chevrolet.com.br` é da GM.
OFICIAIS: dict[str, tuple[str, ...]] = {
    "Ford": ("ford.com.br", "ford.com"),
    "Toyota": ("toyota.com.br", "media.toyota.com.br", "toyota.com"),
    "Volkswagen": ("vw.com.br", "volkswagen.com.br", "vwnews.com.br"),
    "Chevrolet": ("chevrolet.com.br", "gm.com.br", "media.gm.com"),
    # A Stellantis publica a ficha técnica de Fiat, RAM, Jeep e Peugeot no mesmo lugar:
    # `media.stellantis.com/uploads/br/model-document/…`. Descoberto medindo a busca ao vivo
    # em 13/09/2026 — a primeira consulta da RAM trouxe o PDF de lá, e ele estava caindo
    # como domínio não reconhecido porque o rótulo registrável é "stellantis", não "ram".
    "Fiat": ("fiat.com.br", "stellantis.com", "media.stellantis.com"),
    "RAM": ("ram.com.br", "stellantis.com", "media.stellantis.com"),
    "Jeep": ("jeep.com.br", "stellantis.com", "media.stellantis.com"),
    "Peugeot": ("peugeot.com.br", "stellantis.com", "media.stellantis.com"),
    "Citroën": ("citroen.com.br", "stellantis.com", "media.stellantis.com"),
    "Mitsubishi": ("mitsubishimotors.com.br", "mitsubishi.com.br", "mmcb.com.br"),
    "Nissan": ("nissan.com.br", "nissannews.com"),
}

#: T2: registro de terceiro com autoridade.
REGISTROS: dict[str, str] = {
    "veiculos.fipe.org.br": "tabela FIPE",
    "fipe.org.br": "tabela FIPE",
    "parallelum.com.br": "API pública da tabela FIPE",
    "gov.br": "PBE/Inmetro",
    "inmetro.gov.br": "PBE/Inmetro",
}

#: O que um endereço `gov.br` precisa dizer para contar como registro do veículo.
#:
#: Medido ao vivo em 13/09/2026: `pcdf.df.gov.br/transparencia/licitacoes/pregao/...` — um
#: edital de compra de viaturas da Polícia Civil do DF — entrou como **tier 2, PBE/Inmetro**
#: e gravou `ano_modelo = 2020` de uma "L200 TRITON SPORT GLS" numa ficha da Triton 2026.
#: Governo publica muita coisa sobre carros; registro do veículo é só o do Inmetro/PBE.
MARCAS_DE_REGISTRO_GOV = ("inmetro", "pbe", "conpet")


#: T3: os domínios de terceiro que publicam ficha, **lidos de `fontes.yaml`**.
#:
#: Era uma tupla escrita aqui, e ela respondia a uma pergunta só: "conhecido?". O arquivo
#: responde a três — que tipo de página é (ficha ou matéria), se o `fetch` simples passa, e
#: quantos campos o site rendeu **por regra** na última sondagem. Domínio reprovado sai da
#: lista com o motivo escrito, em vez de sumir sem explicação.
def _de_terceiro() -> tuple[str, ...]:
    from pipeline.research import fontes

    return tuple(f.dominio for f in fontes.carregar().do_tipo("ficha", "imprensa"))


#: Domínios que nunca valem a coleta, por mais bem posicionados que apareçam.
DESCARTADOS: dict[str, str] = {
    "youtube.com": "vídeo: não há texto a citar",
    "facebook.com": "rede social: não é publicação técnica do fabricante",
    "instagram.com": "rede social: não é publicação técnica do fabricante",
    "x.com": "rede social: não é publicação técnica do fabricante",
    "twitter.com": "rede social: não é publicação técnica do fabricante",
    "reddit.com": "fórum: opinião de usuário, sem ficha técnica publicada",
    "quora.com": "fórum: opinião de usuário, sem ficha técnica publicada",
    "mercadolivre.com.br": "classificado: anúncio de particular, não ficha do fabricante",
    "olx.com.br": "classificado: anúncio de particular, não ficha do fabricante",
    "wikipedia.org": "enciclopédia: não é fonte primária de ficha técnica",
}

#: O tier de quem não casou nenhuma regra. 5 é "fonte não verificada" em `docs/03`.
TIER_DESCONHECIDO = 5

#: Caminhos que denunciam **manual do proprietário**, e não ficha técnica.
#:
#: Medido ao vivo em 13/09/2026, e foi o achado que mais mudou a qualidade da pesquisa: as
#: 18 páginas coletadas somaram **141,7 MB** — média de 7,9 MB cada —, e as maiores eram
#: manuais de 400 páginas. Um manual do proprietário do Versa não tem a ficha técnica da
#: Frontier; ele só gasta o orçamento de doze páginas e o tempo de leitura.
#:
#: O domínio é oficial, então a regra de tier o aceitava com razão. O que faltava era
#: perguntar **o que** aquele documento é.
#: Endereços de manual, garantia e pós-venda: domínio oficial, documento errado.
#:
#: Os padrões casam o **prefixo** `manual-do-prop`, e não a palavra escrita certo. A URL
#: da própria Chevrolet é `s10-2025-manual-do-**propietario**.pdf`, sem o segundo R, e
#: escapou do padrão completo: o manual entrou como tier 1 e rendeu 43 das 58 linhas de
#: uma rodada — cilindrada lida de "Óleo do motor 5,6 L", torque lido da linha do câmbio
#: manual. Grafia de terceiro não é contrato; o prefixo é o que as duas têm em comum.
CAMINHOS_DE_MANUAL: tuple[str, ...] = (
    "/manuais/",
    "/manual/",
    "/manual-",
    "/literatura-de-bordo/",
    "manual-do-prop",
    "manual_do_prop",
    "manualdoprop",
    "guia-do-prop",
    "guia_do_prop",
    "owners-manual",
    "owner-manual",
    "/uploads/originals/",
    "/garantia/",
    "/pos-venda/",
)


#: Endereços que anunciam **vários veículos na mesma página** — comparação ou listagem.
#:
#: Uma tabela de comparação tem um rótulo e quatro colunas de valor, e nenhuma delas vem
#: marcada como "a versão que você pediu". Na S10 de 14/09/2026 isso rendeu **dezessete
#: valores de torque** para a mesma picape, de 79 a 440 Nm, cada um com citação verdadeira.
#: Não é o site que está errado: `carrosnaweb.com.br/fichadetalhe.asp` é ficha de uma
#: versão só, e continua valendo. É a página que compara que não serve de fonte.
CAMINHOS_DE_COMPARACAO: tuple[str, ...] = (
    "resultcompara",
    "/comparativo",
    "/comparativos",
    "/comparar",
    "comparacao-entre",
    "-vs-",
    "-x-",
)

#: Página de busca ou índice do próprio site: leva muitos carros e a ficha de nenhum.
CAMINHOS_DE_LISTAGEM: tuple[str, ...] = (
    "varnome=",
    "/busca?",
    "/busca/",
    "/resultado-da-busca",
    "?s=",
)


@dataclass(frozen=True)
class Classificacao:
    """O que decidimos sobre uma URL, e **por quê**.

    `motivo` não é decoração: ele aparece na tela, ao lado de cada fonte considerada, e é
    o que permite a alguém discordar da escolha. Uma fonte descartada em silêncio é
    indistinguível de uma fonte que ninguém viu.
    """

    url: str
    tier: int
    motivo: str
    dominio: str = ""
    e_pdf: bool = False
    aceita: bool = True
    tipo: str = ""
    """`oficial`, `registro`, `ficha` ou `imprensa` (`pipeline/research/fontes.py`).

    O tier diz **em quem acreditar**; o tipo diz **o que a página é**, e são perguntas
    diferentes. `icarros.com.br/catalogo/...` e `kbb.com.br` são os dois tier 3, e a
    sondagem de 13/09/2026 mediu 16 campos por regra no primeiro e 5 no segundo. Sem o
    tipo, a coleta gasta a mesma página nos dois."""
    navegador: bool = False
    """A sondagem mostrou que o `fetch` simples não passa neste domínio."""

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "tier": self.tier,
            "motivo": self.motivo,
            "dominio": self.dominio,
            "e_pdf": self.e_pdf,
            "aceita": self.aceita,
            "tipo": self.tipo,
            "navegador": self.navegador,
        }


def dominio_de(url: str) -> str:
    """O host sem `www.`, em minúsculas. URL inválida devolve string vazia."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host.removeprefix("www.")


def _casa(dominio: str, alvo: str) -> bool:
    """`media.toyota.com.br` casa `toyota.com.br`; `nottoyota.com.br` **não** casa.

    O sufixo tem de começar num limite de rótulo, senão `fakeford.com.br` viraria oficial
    da Ford — e a fonte falsa entraria com o tier da verdadeira.
    """
    return dominio == alvo or dominio.endswith("." + alvo)


def _slug_da_marca(marca: str) -> str:
    return re.sub(r"[^a-z0-9]", "", marca.lower())


#: Sufixos que uma montadora acrescenta ao próprio nome no domínio.
#:
#: `mitsubishimotors.com.br` é a Mitsubishi; `ford-noticias.com.br` não é a Ford. A lista é
#: fechada de propósito: qualquer sufixo serve para um blog se disfarçar.
SUFIXOS_CORPORATIVOS: tuple[str, ...] = (
    "motors",
    "brasil",
    "dobrasil",
    "br",
    "veiculos",
    "automoveis",
    "caminhoes",
)


def rotulo_registravel(dominio: str) -> str:
    """O rótulo que alguém **registrou**, sem subdomínio e sem sufixo público.

    `media.toyota.com.br` → `toyota`. `ford.blogspot.com` → `blogspot` — que é a chave
    deste teste: quem registrou foi o Blogspot, não a Ford, e é por isso que um blog com
    "ford" no host não pode herdar o tier da montadora.
    """
    partes = [p for p in dominio.split(".") if p]
    if len(partes) < 2:
        return ""
    # `x.com.br`, `x.net.br`, `x.gov.br`: dois sufixos públicos, o rótulo é o antepenúltimo.
    if len(partes) >= 3 and partes[-1] == "br" and len(partes[-2]) <= 3:
        return partes[-3]
    return partes[-2]


def dominio_parece_oficial(dominio: str, marca: str) -> bool:
    """O **rótulo registrável** é a marca (ou a marca mais um sufixo corporativo)?

    É o que dá T1 a uma montadora fora do mapa `OFICIAIS` — `ram.com.br`,
    `mitsubishimotors.com.br` — sem precisar cadastrar cada marca do país antes de
    pesquisar a primeira.

    **A comparação é do rótulo inteiro, e não "contém".** Três domínios provam por quê, e os
    três estão no teste: `fakeford.com.br` (contém "ford" e não é a Ford),
    `ford-noticias.com.br` (idem) e `ford.blogspot.com` (o rótulo registrado é `blogspot`).
    Dar T1 a qualquer um deles faria uma divergência com o site real ser resolvida a favor
    do impostor — e o tier existe justamente para decidir em quem acreditar.
    """
    slug = _slug_da_marca(marca)
    if len(slug) < 3:
        return False
    rotulo = re.sub(r"[^a-z0-9]", "", rotulo_registravel(dominio))
    if not rotulo:
        return False
    if rotulo == slug:
        return True
    if rotulo.startswith(slug):
        return rotulo[len(slug) :] in SUFIXOS_CORPORATIVOS
    return False


def fala_do_modelo(url: str, titulo: str, modelo: str, snippet: str = "") -> bool:
    """A URL ou o título mencionam o **modelo** pedido?

    **A peça que faltava, e ela custou uma rodada ao vivo para aparecer.** O classificador
    acertava o domínio e errava o documento: pesquisando a Nissan Frontier, as páginas
    escolhidas foram `nissan.com.br/veiculos/modelos.html`, a página do Kicks Play e — o
    caso que encerra a discussão — o **regulamento de um festival de cultura japonesa**
    hospedado no domínio da Nissan. Todas T1, todas oficiais, nenhuma sobre a Frontier.

    Os quatro motores de busca estudados resolvem isso com *rerank* por embedding. Aqui
    basta uma pergunta determinística: **o nome do modelo aparece no endereço ou no
    título?** É a diferença entre "página da Nissan" e "página da Frontier", e ela é
    verificável sem chamar ninguém.

    Sem modelo pedido, devolve `True`: a regra existe para filtrar, não para bloquear quem
    não a usa.

    **O resumo da busca conta, e só aqui.** Medido na S10 em 14/09/2026:
    `carrosnaweb.com.br/fichadetalhe.asp?codigo=47930` é a ficha de **uma** versão, com a
    tabela rótulo/valor que a pesquisa mais quer — e o endereço é um código. Sem o resumo,
    a melhor página da rodada era descartada por "não menciona S10". `snippet` é metadado
    do buscador e nunca vira evidência (`Achado` não tem como virar): ele decide **o que
    baixar**, e o valor continua saindo do texto salvo da página.
    """
    alvo = re.sub(r"[^a-z0-9]", "", modelo.lower())
    if len(alvo) < 3:
        return True
    achavel = re.sub(r"[^a-z0-9]", "", f"{url} {titulo} {snippet}".lower())
    return alvo in achavel


#: Quantos anos antes do ano-modelo uma página ainda pode estar falando do mesmo carro.
#:
#: Uma geração de picape dura de seis a oito anos. Cinco anos de distância do ano-modelo
#: põe a página, com quase certeza, na geração anterior — outro motor, outro câmbio, outra
#: ficha. Quatro é a margem que deixa passar o lançamento antecipado ("a nova S10 2027",
#: publicado em 2025) sem deixar passar o teste da geração que saiu de linha.
ANOS_DE_TOLERANCIA = 1

#: Ano de quatro dígitos isolado no caminho da URL — não pedaço de um código maior.
_ANO_NO_CAMINHO = re.compile(r"(?<!\d)(19[89]\d|20\d\d)(?!\d)")


def ano_da_url(url: str) -> int | None:
    """O ano que o **caminho** da URL carrega, ou `None`.

    Quando há mais de um, vale o **mais novo**: `/2026/07/retrospectiva-2015.html` é uma
    página de 2026 que fala de 2015, e barrá-la pelo 2015 seria ler o texto ao contrário.

    A busca ignora `?query` e `#âncora` — `fichadetalhe.asp?codigo=47930` não tem ano
    nenhum, e tratar um código de catálogo como data reprovaria uma ficha boa.
    """
    caminho = url.split("?", 1)[0].split("#", 1)[0]
    achados = {int(a) for a in _ANO_NO_CAMINHO.findall(caminho)}
    return max(achados) if achados else None


def classificar(
    url: str,
    *,
    marca: str = "",
    titulo: str = "",
    modelo: str = "",
    ano: int | None = None,
    snippet: str = "",
) -> Classificacao:
    """A URL, o tier e o motivo. **Não** faz requisição: julga pelo endereço.

    `titulo` (o do resultado de busca) serve para duas coisas, e nenhuma delas é decidir o
    tier — título é texto que o dono do site escreve, e o domínio não é: reconhecer catálogo
    em PDF quando a URL não termina em `.pdf`, e procurar o nome do modelo.

    `modelo`, quando informado, barra a página que é do domínio certo e do **veículo
    errado** — ver `fala_do_modelo`.
    """
    dominio = dominio_de(url)
    if not dominio:
        return Classificacao(url, TIER_DESCONHECIDO, "endereço inválido", aceita=False)

    e_pdf = url.lower().split("?")[0].endswith(".pdf") or "pdf" in titulo.lower()
    if dominio.startswith("acessorios."):
        return Classificacao(
            url,
            TIER_DESCONHECIDO,
            "catálogo de acessórios não comprova equipamento de série",
            dominio,
            e_pdf,
            aceita=False,
        )

    # Manual do proprietário: domínio oficial, documento errado. Barrar aqui é o que
    # impede a pesquisa de gastar uma das doze páginas num PDF de 400 páginas que não
    # traz ficha técnica nenhuma.
    caminho = url.lower()
    if (
        marca == "Ford"
        and dominio == "ford.com.br"
        and urlparse(url).path.rstrip("/") == "/servico-ao-cliente/garantia"
    ):
        return Classificacao(
            url,
            1,
            "política contratual: leitura limitada ao modelo/ano explícito",
            dominio,
            tipo="garantia",
        )
    for padrao in CAMINHOS_DE_MANUAL:
        if padrao in caminho:
            return Classificacao(
                url,
                TIER_DESCONHECIDO,
                "manual do proprietário ou pós-venda: não é ficha técnica",
                dominio,
                e_pdf,
                aceita=False,
            )

    for padrao in CAMINHOS_DE_COMPARACAO:
        if padrao in caminho:
            return Classificacao(
                url,
                TIER_DESCONHECIDO,
                "página que compara vários veículos: a tabela tem uma coluna por carro e "
                "nenhuma diz qual é o pedido",
                dominio,
                e_pdf,
                aceita=False,
            )

    for padrao in CAMINHOS_DE_LISTAGEM:
        if padrao in caminho:
            return Classificacao(
                url,
                TIER_DESCONHECIDO,
                "listagem de busca do site: leva muitos carros e a ficha de nenhum",
                dominio,
                e_pdf,
                aceita=False,
            )

    for alvo, motivo in DESCARTADOS.items():
        if _casa(dominio, alvo):
            return Classificacao(url, TIER_DESCONHECIDO, motivo, dominio, e_pdf, aceita=False)

    # O domínio pode ser o certo e o documento, o errado. Esta é a pergunta que separa
    # "página da Nissan" de "página da Frontier".
    if modelo and not fala_do_modelo(url, titulo, modelo, snippet):
        return Classificacao(
            url,
            TIER_DESCONHECIDO,
            f"não menciona {modelo} no endereço nem no título",
            dominio,
            e_pdf,
            aceita=False,
        )

    # Domínio certo, modelo certo, **ano errado**: o teste de 2015 da geração anterior.
    # Custou quatro divergências falsas contra o gabarito da S10 em 14/09/2026.
    # A pasta do gerenciador de mídia pode manter a data em que foi criada mesmo
    # quando o PDF é substituído (Ford: pasta 2025, ficha revisada em setembro/2026).
    # Isso só permite baixar; `identity.assess` ainda exige o MY no documento.
    official_asset = (
        e_pdf
        and "/content/dam/" in caminho
        and not re.search(r"(?:19|20)\d{2}", caminho.rsplit("/", 1)[-1])
        and any(_casa(dominio, official) for official in OFICIAIS.get(marca, ()))
    )
    if ano and not official_asset:
        do_endereco = ano_da_url(url)
        if do_endereco is not None and ano - do_endereco > ANOS_DE_TOLERANCIA:
            return Classificacao(
                url,
                TIER_DESCONHECIDO,
                f"página de {do_endereco}, {ano - do_endereco} anos antes do ano-modelo "
                f"{ano}: descreve a geração anterior",
                dominio,
                e_pdf,
                aceita=False,
            )

    for alvo in OFICIAIS.get(marca, ()):
        if _casa(dominio, alvo):
            qual = "PDF de catálogo oficial" if e_pdf else "site oficial da montadora"
            return Classificacao(url, 1, qual, dominio, e_pdf, tipo="oficial")

    if marca and dominio_parece_oficial(dominio, marca):
        return Classificacao(
            url, 1, f"domínio da própria marca ({dominio})", dominio, e_pdf, tipo="oficial"
        )

    if _casa(dominio, "gov.br") and not any(m in caminho for m in MARCAS_DE_REGISTRO_GOV):
        return Classificacao(
            url,
            TIER_DESCONHECIDO,
            "página governamental fora do Inmetro/PBE (licitação, edital, notícia): não é "
            "registro do veículo",
            dominio,
            e_pdf,
            aceita=False,
        )

    for alvo, motivo in REGISTROS.items():
        if _casa(dominio, alvo):
            return Classificacao(url, 2, motivo, dominio, e_pdf, tipo="registro")

    from pipeline.research import fontes

    de_terceiro = fontes.fonte_de(dominio)
    if de_terceiro is not None:
        qual = (
            "ficha técnica de terceiro" if de_terceiro.tipo == "ficha" else "imprensa especializada"
        )
        if de_terceiro.campos_medidos:
            qual += f" ({de_terceiro.campos_medidos} campos por regra na sondagem)"
        return Classificacao(
            url,
            de_terceiro.tier,
            qual,
            dominio,
            e_pdf,
            tipo=de_terceiro.tipo,
            navegador=de_terceiro.navegador,
        )

    # Domínio que **já foi medido e reprovado** diz isso, em vez de "não reconhecido": a
    # diferença entre "ninguém olhou" e "olhamos, e não serve" é o que evita a próxima
    # pessoa gastar a mesma meia hora.
    reprovado = fontes.motivo_da_reprovacao(dominio)
    if reprovado:
        return Classificacao(
            url,
            TIER_DESCONHECIDO,
            f"domínio já medido e reprovado: {reprovado}",
            dominio,
            e_pdf,
            aceita=False,
        )

    return Classificacao(
        url,
        TIER_DESCONHECIDO,
        "domínio não reconhecido: nem oficial, nem registro público, nem imprensa conhecida",
        dominio,
        e_pdf,
        aceita=False,
    )


def ordenar(classificadas: list[Classificacao]) -> list[Classificacao]:
    """Aceitas primeiro, por tier, e **PDF na frente dentro do mesmo tier**.

    O PDF de catálogo é a melhor fonte que existe para ficha técnica: ele é a ficha, em
    tabela, sem JavaScript e sem escudo antibot. Quando o site e o PDF da mesma montadora
    aparecem juntos, começar pelo PDF costuma fechar mais campos com menos páginas — e o
    orçamento da demo é de doze páginas.
    """
    from pipeline.research.fontes import PESO_DO_TIPO

    return sorted(
        classificadas,
        key=lambda c: (
            not c.aceita,
            c.tier,
            not c.e_pdf,
            # Dentro do mesmo tier, **ficha antes de matéria**: a página de ficha é de uma
            # versão só e se lê por regra. Medido em 13/09/2026: `icarros` rendeu 16 campos
            # sem chamar o modelo; `kbb`, 5.
            PESO_DO_TIPO.get(c.tipo, len(PESO_DO_TIPO)),
            c.url,
        ),
    )
