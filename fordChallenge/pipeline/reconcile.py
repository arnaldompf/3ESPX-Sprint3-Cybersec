"""Reconciliação multi-fonte: de candidatos soltos para observações por campo.

Este módulo é **fino de propósito**. A tentação era pôr aqui a escolha por tier, a
concordância entre fontes, os `conflicts` e a confiança — mas essas regras já existem em
`pipeline/status.py`, e duas implementações das regras de honestidade é o pior cenário
possível (a mesma razão da D-46, que fez o eval reexportar o grounding em vez de
reimplementá-lo). Se a reconciliação decidisse status por conta própria, a ficha exibida
e a ficha medida passariam a ser produzidas por códigos diferentes.

O que sobra para cá é o trabalho real de tradução, e ele não é trivial:

* **candidato → observação**, aplicando a normalização (`pipeline/normalize.py`) para que
  o valor comparado seja canônico e o `raw_value` nunca se perca;
* **agrupamento por campo**, preservando **todos** os candidatos — inclusive os que
  discordam, que é o que sustenta `divergente`;
* **`sources_checked`**, que é o que separa `nao_disponivel` de `nao_encontrado`: sem a
  lista de fontes consultadas, "não achei" e "a fonte diz que não tem" viram a mesma
  coisa;
* o registro do que **não** foi normalizável, que fica visível em vez de desaparecer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline import claim_type, matching
from pipeline.connectors.base import normalizar_versao
from pipeline.eval.compare import comparar_valor
from pipeline.extract.run import Candidato
from pipeline.normalize import NaoNormalizavel, normalizar_campo
from pipeline.status import Decisao, Observacao, decidir_todos


@dataclass
class ResultadoReconciliacao:
    """As decisões por campo, e o que ficou de fora com o motivo."""

    decisoes: dict[str, Decisao] = field(default_factory=dict)
    observacoes: dict[str, list[Observacao]] = field(default_factory=dict)
    sources_checked: list[str] = field(default_factory=list)
    nao_normalizaveis: list[str] = field(default_factory=list)
    """`campo: motivo` de cada candidato descartado na normalização."""

    @property
    def campos_com_valor(self) -> set[str]:
        return {campo for campo, d in self.decisoes.items() if d.spec.value is not None}


def observacao_de(candidato: Candidato) -> Observacao:
    """Traduz um candidato em observação, canonicalizando valor e unidade.

    A normalização roda sobre o **valor já extraído**, não sobre o texto bruto. A
    diferença não é de estilo: `valor_bruto` é o trecho casado na fonte — *"0 a 100 km/h
    em 5,8 segundos"* — e re-extrair dele joga fora o parse que a regra do fast-path já
    fez, pegando o **primeiro** número da frase. Isso punha `aceleracao_0_100_s = 0.0` na
    ficha, com um trecho que groundeia perfeitamente: número errado com evidência válida,
    a classe de defeito da D-44. `valor_bruto` continua indo para a evidência como
    `raw_value`, que é onde o texto da fonte pertence.

    A exceção é `valor is None`: aí quem carrega a informação é o bruto, porque é ele que
    traz a marca de ausência declarada ("—", "não disponível") que separa
    `nao_disponivel` de `nao_encontrado`.

    `NaoNormalizavel` **não** é engolido: quem chama registra o campo e o motivo. Um valor
    que não normaliza tem de virar campo sem valor com explicação, nunca um valor forçado
    no tipo errado.
    """
    from pipeline.semantics import rejection_reason, validate_date, validate_list, validate_number

    motivo = rejection_reason(candidato.campo, candidato.quote, url=candidato.url)
    if motivo:
        raise NaoNormalizavel(motivo)
    bruto = candidato.valor if candidato.valor is not None else candidato.valor_bruto
    normalizado = normalizar_campo(candidato.campo, bruto, unidade=candidato.unidade)
    if not validate_list(candidato.campo, normalizado.valor, candidato.quote):
        raise NaoNormalizavel("lista_contem_item_sem_prova_no_trecho")
    if not validate_number(candidato.campo, normalizado.valor, candidato.quote, candidato.unidade):
        raise NaoNormalizavel("valor_normalizado_nao_corresponde_ao_numero_da_evidencia")
    if not validate_date(candidato.campo, normalizado.valor, candidato.quote):
        raise NaoNormalizavel("data_sem_prova_no_trecho")
    notas = candidato.notas
    if normalizado.conversao:
        notas = f"{notas}; {normalizado.conversao}".strip("; ")

    # O tipo da afirmação sai do trecho verbatim, nunca de conhecimento do modelo: a mesma
    # matéria da Autoesporte traz os 5,8 s que a Ford declara e os 6,5 s que a revista
    # mediu, e sem isso a ficha dizia "as fontes divergem" sobre uma fonte só. O termo que
    # disparou vai para as notas — etiqueta sem o que a sustenta é opinião do sistema.
    tipo, termo = claim_type.classificar(candidato.quote, raw_value=candidato.valor_bruto or "")
    if tipo:
        notas = f'{notas}; tipo de afirmação "{tipo}" por "{termo}"'.strip("; ")

    return Observacao(
        campo=candidato.campo,
        valor=normalizado.valor,
        quote=candidato.quote,
        source_id=candidato.source_id,
        url=candidato.url,
        tier=candidato.tier,
        captured_at=candidato.captured_at,
        raw_value=candidato.valor_bruto or normalizado.raw_value,
        unidade=normalizado.unidade or candidato.unidade,
        pagina=candidato.pagina,
        notas=notas,
        ausencia_declarada=normalizado.ausencia_declarada,
        tipo_de_afirmacao=tipo,
    )


def agrupar(
    candidatos: list[Candidato],
) -> tuple[dict[str, list[Observacao]], list[str]]:
    """Agrupa candidatos por campo, devolvendo também o que não normalizou.

    Nenhum candidato é descartado por discordar de outro: divergência é resultado, não
    ruído a filtrar. O único descarte é o que não vira valor canônico, e ele sai
    nomeado.
    """
    por_campo: dict[str, list[Observacao]] = {}
    recusados: list[str] = []
    for candidato in candidatos:
        try:
            observacao = observacao_de(candidato)
        except NaoNormalizavel as exc:
            recusados.append(f"{candidato.campo}: {exc}")
            continue
        por_campo.setdefault(candidato.campo, []).append(observacao)
    return por_campo, recusados


# --------------------------------------------- célula vence texto na fonte tabular
def preferir_celulas(candidatos: list[Candidato]) -> tuple[list[Candidato], list[str]]:
    """Numa fonte tabular, o valor da **célula** da versão vence o do texto da linha.

    O defeito real, e é o mais insidioso que a orquestração produziu. A linha da ficha
    da Hilux é:

        Rodas    Aço estampado 17"   Liga leve 17"   Liga leve 18"

    Uma linha, três versões, três colunas. O recorte por versão sabe qual coluna é da SRX
    Plus (18"). Mas o fast-path também lê o **texto corrido** da mesma linha e encontra
    17" ali — o valor da coluna de outra versão. Os dois viravam candidatos tier 1 da
    mesma fonte, `status.decidir` fazia o que tem de fazer com dois valores tier 1
    incompatíveis, e o campo saía **`divergente` entre 17 e 18**: uma divergência que não
    existe na fonte, fabricada por ler a linha em vez da coluna.

    Divergência inventada é pior que valor faltando, porque ela consome a confiança do
    usuário no mecanismo que existe para mostrar discordância real.

    O escopo é estreito: só descarta o texto **da mesma fonte** e **do mesmo campo** em
    que a célula respondeu. Outra fonte que discorde continua produzindo divergência — e
    aí ela é real.
    """
    com_celula = {(c.source_id, c.campo) for c in candidatos if c.de_celula}
    if not com_celula:
        return candidatos, []
    mantidos: list[Candidato] = []
    descartados: list[str] = []
    for candidato in candidatos:
        if not candidato.de_celula and (candidato.source_id, candidato.campo) in com_celula:
            descartados.append(
                f"{candidato.campo}: descartado {candidato.valor!r} lido do texto de "
                f"{candidato.source_id} — a coluna da versão nesta fonte já respondeu, "
                "e a linha da tabela percorre todas as versões"
            )
            continue
        mantidos.append(candidato)
    return mantidos, descartados


#: Fontes que **nunca** são descartadas por especificidade, por `source_id`.
#:
#: A referência interna do cliente (o slide da Ford) existe **para** discordar da fonte
#: pública: silenciá-la apagaria o Fogo Amigo, que é a cena-assinatura do produto. E
#: silenciar por "especificidade" seria especialmente errado — o slide fala da mesma
#: versão, ele só está desatualizado, que é exatamente o que o alerta diz.
#:
#: Por `source_id` e não por tier: o tier da referência interna é **4**
#: (`run.TIER_REFERENCIA_INTERNA`), a posição correta na ordenação — abaixo de oficial e
#: de FIPE. O "tier 0" que aparece em `pipeline/radar/internal.py` é rótulo de origem,
#: não posição (D-87). Protegê-la por tier 0, como a primeira versão desta guarda fazia,
#: não protegia nada: as quatro divergências da Raptor foram silenciadas em silêncio, e
#: só os testes do slide reclamaram.
FONTES_QUE_NAO_SE_DESCARTAM = frozenset({"referencia_interna"})


def preferir_especifico_da_versao(
    candidatos: list[Candidato], escopos: dict[str, str]
) -> tuple[list[Candidato], list[str]]:
    """Evidência **da versão** vence evidência de página de linha, no mesmo campo.

    `preferir_celulas` resolve o caso em que a coluna e a linha estão na **mesma** fonte.
    Este resolve o caso em que estão em fontes diferentes, que é o mais comum e o que
    sobrava. Dois casos medidos em 10/09/2026:

    * **Hilux, aro 17 × 18.** A coluna da SRX Plus na ficha PDF diz 18. A página
      `hilux-cabine-dupla` — que é a página do **modelo** e lista cinco versões —
      menciona 17 e 18. Somando as menções, 17 aparecia mais vezes e ganhava por
      maioria: a ficha saía com o aro da SRV;
    * **Ranger Limited.** O comparador de versões (uma página, doze versões) oferece 16,
      17, 18 e 20 de aro, 6 e 10 marchas, 170 e 250 cv. A página da própria versão diz
      18, 10 e 250. Sem esta regra, a Limited herdava número da XL.

    O que conta como **específico**: valor lido da coluna recortada da versão
    (`de_celula`) ou de fonte cuja URL é a da própria versão (`escopos[source_id] ==
    "versao"`). O que conta como **de linha**: o resto, exceto a referência interna
    (tier 0, ver `TIER_QUE_NAO_SE_DESCARTA`).

    Não apaga divergência real: só descarta o **não específico** quando existe específico
    no mesmo campo **e** o valor discorda dele. Não específico que concorda continua na
    lista e reforça a confiança, como qualquer fonte concordante. Duas fontes de linha
    que discordam entre si continuam produzindo `divergente` — e aí a discordância é
    sobre o mesmo nível de evidência, que é quando ela significa algo.
    """

    def e_especifico(c: Candidato) -> bool:
        return bool(c.de_celula) or escopos.get(c.source_id) == "versao"

    especificos: dict[str, list[Candidato]] = {}
    for c in candidatos:
        if e_especifico(c):
            especificos.setdefault(c.campo, []).append(c)
    if not especificos:
        return candidatos, []

    mantidos: list[Candidato] = []
    descartados: list[str] = []
    for c in candidatos:
        donos = especificos.get(c.campo)
        if (
            donos is None
            or e_especifico(c)
            or c.source_id in FONTES_QUE_NAO_SE_DESCARTAM
            or any(comparar_valor(c.campo, d.valor, c.valor).igual for d in donos)
        ):
            mantidos.append(c)
            continue
        descartados.append(
            f"{c.campo}: descartado {c.valor!r} de {c.source_id} — a evidência "
            f"específica desta versão diz {donos[0].valor!r}, e {c.source_id} cobre a "
            "linha inteira (uma página/tabela por várias versões)"
        )

    # O ESPECÍFICO VAI NA FRENTE, e isto não é cosmética.
    #
    # Quem concorda com o específico continua na lista — é fonte concordante e aumenta a
    # confiança, corretamente. Mas a **primeira** evidência do grupo é a que a ficha
    # exibe no "ver evidência", e ela vinha na ordem em que o extrator produziu: a da
    # página de linha. Medido na Ranger Limited, com o valor certo em todos os cinco:
    #
    #   cilindros  = V6          citando "XLS 3.0 V6 Diesel 4WD AT 2027"
    #   combustivel = diesel     citando "XL 2.0 CH Diesel 4x4 MT 2027"
    #   aspiracao  = turbo       citando "Motor 2.0 Turbo Diesel"        (a XL)
    #   transmissao.tipo = automatica  citando "Automática de 6 velocidades" (a XL)
    #   rodas_material = liga leve     citando 'Rodas de liga leve 17"'  (a XLS)
    #
    # Num produto cuja promessa é "clique e veja a prova", uma prova que fala de outra
    # versão é pior que nenhuma prova: ela parece certa. A ordenação é estável — a ordem
    # relativa dentro de cada grupo é preservada.
    mantidos.sort(key=lambda c: not e_especifico(c))
    return mantidos, descartados


# ------------------------------------------------- atribuição por seção da versão
#: Distância mínima, em caracteres, para considerar que um nome de versão **titula** o
#: trecho em vez de apenas aparecer perto dele. Uma página lista o nome, o preço, a frase
#: de efeito e então os bullets: da linha do nome até o primeiro bullet dá ~80 caracteres.
ALCANCE_DA_SECAO = 3000

#: Marcadores de item de lista. O bullet é o que distingue "equipamento **desta** versão"
#: de "fato da linha inteira" nas páginas de montadora e nas reportagens.
_BULLET = re.compile(r"^\s*(?:[•·▪◦‣]|[-*+]\s|\d+[.)]\s)")


def e_item_de_lista(texto: str, posicao: int) -> bool:
    """A citação nesta posição começa um item de lista?"""
    inicio = texto.rfind("\n", 0, posicao) + 1
    return bool(_BULLET.match(texto[inicio : posicao + 2]))


def descobrir_secoes_de_versao(
    texto: str, *, marca: str, modelo: str, versao: str
) -> tuple[str, list[str]]:
    """Descobre os tÃ­tulos reais de versÃ£o numa pÃ¡gina de modelo.

    A pesquisa de um veÃ­culo novo nÃ£o tem ``lineup`` no banco para alimentar
    :func:`filtrar_por_secao`. Ainda assim, pÃ¡ginas de imprensa costumam listar as
    versÃµes como ``Marca Modelo VersÃ£o: detalhes``. Esta funÃ§Ã£o usa somente esses
    tÃ­tulos literais e escolhe um alvo apenas quando hÃ¡ um melhor casamento Ãºnico.
    Ambiguidade devolve vazio e, portanto, nunca descarta um dado por palpite.
    """
    modelo_normalizado = normalizar_versao(modelo)
    if not modelo_normalizado or not versao.strip():
        return "", []

    nomes: list[str] = []
    for bruta in texto.splitlines():
        linha = bruta.strip().strip("#*â€¢- ")
        if ":" not in linha:
            continue
        nome = linha.split(":", 1)[0].strip()
        if not 3 <= len(nome) <= 180:
            continue
        if modelo_normalizado not in normalizar_versao(nome):
            continue
        if nome not in nomes:
            nomes.append(nome)

    if len(nomes) < 2:
        return "", []

    resultado = matching.avaliar(
        normalizar_versao(versao),
        [normalizar_versao(nome) for nome in nomes],
        cobertura_minima=0.25,
        limiar=0.0,
    )
    if resultado.vencedor is None:
        return "", []
    alvo = nomes[resultado.vencedor.indice]
    return alvo, [nome for nome in nomes if nome != alvo]


def secoes_da_versao(
    texto: str, alvo: str, outras: list[str]
) -> tuple[list[tuple[int, int]], bool]:
    """Onde, no texto, começa e acaba o bloco de cada versão-alvo.

    A seção do alvo vai da posição do nome dele até a posição do **próximo** nome de
    versão qualquer. Devolve `(seções, aplicavel)`; `aplicavel` é falso quando o alvo não
    é nomeado no texto ou nenhuma outra versão é — aí não há como atribuir por seção, e
    não filtrar é mais honesto que filtrar por adivinhação.
    """
    posicoes: list[tuple[int, str]] = []
    for nome in [alvo, *outras]:
        inicio = 0
        while (achado := texto.find(nome, inicio)) >= 0:
            posicoes.append((achado, nome))
            inicio = achado + 1
    posicoes.sort()
    if not any(n == alvo for _, n in posicoes) or not any(n != alvo for _, n in posicoes):
        return [], False

    secoes: list[tuple[int, int]] = []
    for i, (inicio, nome) in enumerate(posicoes):
        if nome != alvo:
            continue
        seguinte = next((p for p, n in posicoes[i + 1 :] if n != alvo), None)
        secoes.append((inicio, seguinte if seguinte is not None else inicio + ALCANCE_DA_SECAO))
    return secoes, True


def filtrar_por_secao(
    candidatos: list[Candidato],
    *,
    textos: dict[str, str],
    alvo: str,
    outras: list[str],
) -> tuple[list[Candidato], list[str]]:
    """Descarta o que a página atribui a **outra** versão.

    O defeito real: a página da S10 lista as sete versões em blocos, e
    `"• Rodas de liga leve 18”;"` está no bloco da **Trail Boss**. O fast-path leu o
    bullet e a High Country ganhou rodas de outra versão — valor verdadeiro do veículo
    errado, que é indistinguível de um acerto para quem lê. É a mesma falha que a WP-13
    resolveu no preço, um nível acima: lá era a linha antes do número, aqui é o bloco
    antes do bullet.

    Descarta **só** quando dá para atribuir, e as condições são estreitas de propósito:

    1. o texto nomeia o alvo **e** ao menos uma outra versão (sem isso não há blocos);
    2. a citação ocorre **uma única vez** (citação repetida não tem posição definida, e
       escolher qual ocorrência vale seria voltar ao problema);
    3. a citação é um **item de lista** — começa com marcador de bullet.

    A condição 3 foi aprendida medindo. Sem ela, a guarda descartava `combustivel`,
    `potencia_cv`, `aspiracao` e `cilindros` da S10 e da Amarok: essas páginas declaram o
    motor **uma vez para a linha inteira**, num parágrafo que por acaso fica depois do
    nome de alguma versão. Um fato válido para a linha não é "de outra versão", e a
    guarda derrubava 6 valores certos para remover 2 errados.

    O que **é** por versão nessas páginas é o bullet de equipamento sob o título da
    versão — e é exatamente ali que o `"• Rodas de liga leve 18”"` da Trail Boss estava.
    Nesta guarda o falso positivo custa um valor verdadeiro, então ela erra para menos.
    """
    mantidos: list[Candidato] = []
    descartados: list[str] = []
    cache: dict[str, tuple[list[tuple[int, int]], bool]] = {}
    por_versao = _campos_descritos_por_versao(candidatos, textos=textos, outras=outras)

    for candidato in candidatos:
        texto = textos.get(candidato.source_id, "")
        if not texto or not candidato.quote:
            mantidos.append(candidato)
            continue
        if candidato.source_id not in cache:
            cache[candidato.source_id] = secoes_da_versao(texto, alvo, outras)
        secoes, aplicavel = cache[candidato.source_id]
        if not aplicavel:
            mantidos.append(candidato)
            continue

        posicao = texto.find(candidato.quote)
        if posicao < 0 or texto.find(candidato.quote, posicao + 1) >= 0:
            mantidos.append(candidato)
            continue
        if any(inicio <= posicao < fim for inicio, fim in secoes):
            mantidos.append(candidato)
            continue
        if (
            not e_item_de_lista(texto, posicao)
            and (
                candidato.source_id,
                candidato.campo,
            )
            not in por_versao
        ):
            mantidos.append(candidato)
            continue
        dona = _versao_da_posicao(texto, posicao, outras)
        if not dona:
            # Fora das seções do alvo, mas **nenhuma** outra versão titula a posição:
            # não há evidência de que o trecho seja de outra versão, e descartar em "não
            # sei dizer" contradiz o princípio desta guarda. Aconteceu de verdade com o
            # preço da Amarok: a reportagem escreve "Volkswagen Amarok Extreme" onde o
            # catálogo escreve "V6 Extreme", o nome literal do alvo não casa naquele
            # bullet, e um valor certo (R$ 379.990, o do gabarito) era descartado.
            mantidos.append(candidato)
            continue
        descartados.append(
            f"{candidato.campo}: descartado — o trecho está no bloco de "
            f"{dona!r}, não no de {alvo!r}"
        )
    return mantidos, descartados


#: Em quantas seções de versão distintas o campo tem de aparecer para a fonte contar
#: como "descreve este campo por versão". Duas: uma só é fato da linha repetido no
#: lugar errado; a partir de duas, a página está respondendo o campo versão a versão.
SECOES_PARA_SER_POR_VERSAO = 2


def _campos_descritos_por_versao(
    candidatos: list[Candidato], *, textos: dict[str, str], outras: list[str]
) -> set[tuple[str, str]]:
    """`{(source_id, campo)}` das fontes que respondem aquele campo **por versão**.

    Existe para separar dois tipos de página que a guarda de seção tratava igual:

    * a **página do modelo** (S10, Amarok) declara o motor uma vez, para a linha inteira,
      num parágrafo que por acaso cai depois do nome de alguma versão. Exigir bullet ali
      é o que impede a guarda de derrubar `combustivel`, `potencia_cv`, `aspiracao` e
      `cilindros` — seis valores certos para remover dois errados;
    * o **comparador de versões** (Ford) repete o bloco inteiro de especificações para
      cada uma das doze versões, sem bullet nenhum. Ali, "Motor 2.0 Turbo Diesel" fora da
      seção da Limited é o motor da XL, e exigir bullet fazia a Limited sair com motor
      2.0 — oito ocorrências de 2.0 (as XL) contra três de 3.0 V6, decidido por maioria.

    A diferença medível é esta: o comparador tem o **mesmo campo** em várias seções de
    versão; a página do modelo tem uma. Por isso a chave é `(fonte, campo)` e não a
    fonte inteira — na mesma página, `motor_descricao` pode ser por versão e
    `garantia_meses` ser da linha.
    """
    ocorrencias: dict[tuple[str, str], set[str]] = {}
    for candidato in candidatos:
        texto = textos.get(candidato.source_id, "")
        if not texto or not candidato.quote:
            continue
        posicao = texto.find(candidato.quote)
        if posicao < 0 or texto.find(candidato.quote, posicao + 1) >= 0:
            continue
        dona = _versao_da_posicao(texto, posicao, outras)
        if dona:
            ocorrencias.setdefault((candidato.source_id, candidato.campo), set()).add(dona)
    return {
        chave for chave, donas in ocorrencias.items() if len(donas) >= SECOES_PARA_SER_POR_VERSAO
    }


def _versao_da_posicao(texto: str, posicao: int, nomes: list[str]) -> str:
    """Qual versão titula a posição: a de nome mais próximo **antes** dela."""
    melhor, dona = -1, ""
    for nome in nomes:
        # The quote may start at the heading itself (``Version: wheels 18``). The old
        # exclusive end hid that heading and assigned the line to the previous section.
        achado = texto.rfind(nome, 0, min(len(texto), posicao + len(nome)))
        if achado > melhor:
            melhor, dona = achado, nome
    return dona


def reconciliar(
    candidatos: list[Candidato],
    *,
    textos: dict[str, str],
    campos: list[str],
    sources_checked: list[str] | None = None,
    target=None,
) -> ResultadoReconciliacao:
    """Decide todos os campos pedidos a partir dos candidatos de todas as fontes.

    `campos` é a lista **completa** de campos da ficha, não só os que têm candidato: um
    campo sem candidato precisa aparecer como `nao_encontrado` explícito, com as fontes
    que foram consultadas em vão. Ausência silenciosa é a falha que o schema canônico
    existe para impedir.
    """
    identidade_recusada = []
    if target is not None:
        from pipeline.identity import claim_rejection

        validos = []
        for candidato in candidatos:
            from pipeline.connectors import carrosnaweb, vw_manual_warranty
            from pipeline.connectors.pbe import supports as pbe_supports

            source = candidato.source_text or textos.get(candidato.source_id, "")
            scoped_pbe = pbe_supports(
                candidato.campo, target, source, candidato.url, candidato.quote, candidato.valor
            )
            scoped_warranty = vw_manual_warranty.supports(
                candidato.campo, target, source, candidato.url, candidato.quote, candidato.valor
            )
            scoped_carrosnaweb = carrosnaweb.supports(
                candidato.campo, target, source, candidato.url, candidato.quote, candidato.valor
            )
            reason = (
                "cadeia_garantia_vw_invalida_ou_campo_fora_do_escopo"
                if vw_manual_warranty.is_chain(source) and not scoped_warranty
                else None
            ) or claim_rejection(
                target,
                candidato.quote,
                source_text=(
                    "" if (scoped_pbe or scoped_warranty or scoped_carrosnaweb) else source
                ),
            )
            if reason:
                identidade_recusada.append(f"{candidato.campo}: {reason} ({candidato.source_id})")
            else:
                validos.append(candidato)
        candidatos = validos
    por_campo, recusados = agrupar(candidatos)
    recusados.extend(identidade_recusada)
    fontes = list(sources_checked if sources_checked is not None else sorted(textos))
    decisoes = decidir_todos(
        por_campo,
        textos=textos,
        campos=campos,
        sources_checked=fontes,
    )
    return ResultadoReconciliacao(
        decisoes=decisoes,
        observacoes=por_campo,
        sources_checked=fontes,
        nao_normalizaveis=recusados,
    )
