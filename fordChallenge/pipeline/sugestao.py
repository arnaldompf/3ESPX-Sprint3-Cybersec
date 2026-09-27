"""A caixa única: de um texto solto para uma versão do catálogo, com o ano certo.

**Por que isto existe.** A Consulta pedia marca, modelo e versão em três campos separados,
e quem está num showroom com o cliente ao lado digita *"S10 High"* — não *"Chevrolet"*,
*"S10"*, *"High Country"* em três caixas. Este módulo é a tradução entre as duas coisas.

**Por que é função pura, fora da API.** O ranqueador é a parte que erra, e erro de
ranqueador só se vê com muitos casos. Aqui ele é testável sem banco, sem HTTP e sem
sessão: uma lista de :class:`Linha` entra, uma ordem sai.

**O ranqueador não é novo.** É :func:`pipeline.matching.avaliar`, o mesmo do resolvedor de
versão (WP-07), com a normalização de :func:`pipeline.ontology.normalize`. O docstring de
`pipeline/matching.py` conta as três vezes em que alguém trocou aquela regra por
`token_set_ratio` puro e ressuscitou os mesmos bugs; escrever um quarto ranqueador aqui
seria a quarta.

**O ano-modelo é dimensão separada de propósito.** No banco, cada ano é uma linha própria
de `versions` — a chave é `(model_id, nome_exato, ano_modelo)`. Ranquear as linhas cruas
faria *"Ranger Raptor"* devolver a mesma versão três vezes, uma por ano, empurrando as
outras versões para fora da lista. Aqui as linhas são **agrupadas por versão** e o ano vira
uma escolha dentro dela, que é como a pessoa pensa: primeiro o carro, depois o ano.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pipeline import matching
from pipeline.ontology import normalize

#: Quantas sugestões devolver por padrão. A melhor vai em destaque; o resto, recolhido.
LIMITE_PADRAO = 8

#: Anos-modelo plausíveis para um veículo. Serve para separar *"raptor 2025"* (ano) de
#: *"S10"* (nome que tem número) — sem isto, `10` de "S10" viraria ano e o nome perderia
#: um token.
_ANO = re.compile(r"\b(19[8-9]\d|20[0-4]\d)\b")


@dataclass(frozen=True)
class AnoDisponivel:
    """Um ano-modelo de uma versão, e se existe ficha salva dele."""

    ano_modelo: int
    version_id: str
    codigo_fipe: str | None = None
    in_lineup: bool = False
    tem_ficha: bool = False
    """Há célula gravada para esta versão — é o que a tela chama de *cópia salva*.

    Sem isto o seletor de ano ofereceria anos que abrem uma ficha vazia, e ficha vazia
    sem motivo é o defeito que este projeto passou a noite de 12/09 consertando."""


@dataclass(frozen=True)
class Linha:
    """Uma versão do catálogo com **todos** os anos-modelo em que ela existe."""

    marca: str
    modelo: str
    versao: str
    anos: tuple[AnoDisponivel, ...] = ()

    @property
    def texto(self) -> str:
        """`"Chevrolet S10 High Country"` — o que a pessoa leria e o que se compara."""
        return " ".join(p for p in (self.marca, self.modelo, self.versao) if p).strip()

    @property
    def anos_com_ficha(self) -> tuple[int, ...]:
        return tuple(a.ano_modelo for a in self.anos if a.tem_ficha)

    def ano(self, ano_modelo: int) -> AnoDisponivel | None:
        return next((a for a in self.anos if a.ano_modelo == ano_modelo), None)

    @property
    def mais_recente_com_ficha(self) -> AnoDisponivel | None:
        """O ano padrão: o mais recente **que tem ficha**.

        Cai para o mais recente sem ficha quando nenhum tem — para que a tela possa
        dizer *"não temos cópia deste ano"* em vez de não dizer nada."""
        com_ficha = [a for a in self.anos if a.tem_ficha]
        if com_ficha:
            return max(com_ficha, key=lambda a: a.ano_modelo)
        return max(self.anos, key=lambda a: a.ano_modelo) if self.anos else None


@dataclass(frozen=True)
class Sugestao:
    """Uma linha do catálogo avaliada contra o que a pessoa digitou."""

    linha: Linha
    score: float
    """`token_set_ratio` entre o pedido e o nome da versão, 0–100."""
    cobertura: float
    """Fração dos tokens do pedido presentes no nome. É o critério primário."""
    exato: bool = False
    ano_escolhido: AnoDisponivel | None = None
    ano_pedido_sem_ficha: int | None = None
    """O ano que a pessoa digitou e que **não** tem cópia salva.

    Preenchido só quando ela nomeou um ano. É o gatilho da frase *"ainda não temos essa
    versão/ano; pesquisar agora?"* — e a razão de o campo existir em vez de a tela
    comparar listas por conta própria."""


@dataclass(frozen=True)
class Sugestoes:
    """O resultado inteiro: a melhor, as outras, e por que não houve melhor."""

    consulta: str
    ano_pedido: int | None = None
    melhor: Sugestao | None = None
    outras: tuple[Sugestao, ...] = ()
    empatadas: tuple[Sugestao, ...] = ()
    total: int = 0
    motivo: str = ""
    desempate: str = "regra"
    """Quem escolheu a melhor: `regra` (rapidfuzz) ou `ia` (o modelo, num empate).

    **A tela precisa disto, e não é zelo.** Uma escolha por regra é reproduzível: o mesmo
    texto devolve a mesma versão amanhã. Uma escolha por modelo não é, e apresentar as
    duas com a mesma cara faria a ferramenta afirmar com igual firmeza duas coisas de
    naturezas diferentes — que é a única coisa que este projeto não faz."""

    @property
    def ambigua(self) -> bool:
        """Duas ou mais linhas empataram na regra — ninguém venceu, e não é erro."""
        return self.melhor is None and len(self.empatadas) > 1

    @property
    def vazia(self) -> bool:
        """Nenhum candidato passou do limiar: o caminho é o Pesquisador, não a lista."""
        return self.melhor is None and not self.empatadas


def separar_ano(consulta: str) -> tuple[str, int | None]:
    """Tira o ano-modelo do texto. `"raptor 2025"` -> `("raptor", 2025)`.

    O ano sai do texto comparado de propósito. Deixá-lo dentro faria *"raptor 2025"*
    pontuar pior contra *"Ford Ranger Raptor"* do que *"raptor"* sozinho — o pedido mais
    específico casaria pior, que é o oposto do esperado.
    """
    achados = _ANO.findall(consulta)
    if not achados:
        return consulta.strip(), None
    ano = int(achados[-1])
    sem_ano = _ANO.sub(" ", consulta)
    return re.sub(r"\s+", " ", sem_ano).strip(), ano


def _com_ano(sugestao: Sugestao, ano_pedido: int | None) -> Sugestao:
    """Escolhe o ano-modelo desta sugestão, respeitando o que a pessoa pediu."""
    linha = sugestao.linha
    if ano_pedido is not None:
        pedido = linha.ano(ano_pedido)
        if pedido is not None and pedido.tem_ficha:
            return _troca(sugestao, ano_escolhido=pedido)
        # Pediu um ano que não temos (ou que temos sem ficha). A resposta não é escolher
        # outro ano em silêncio: é oferecer o padrão **e** dizer qual ano faltou.
        return _troca(
            sugestao,
            ano_escolhido=linha.mais_recente_com_ficha,
            ano_pedido_sem_ficha=ano_pedido,
        )
    return _troca(sugestao, ano_escolhido=linha.mais_recente_com_ficha)


def _troca(sugestao: Sugestao, **campos) -> Sugestao:
    base = {
        "linha": sugestao.linha,
        "score": sugestao.score,
        "cobertura": sugestao.cobertura,
        "exato": sugestao.exato,
        "ano_escolhido": sugestao.ano_escolhido,
        "ano_pedido_sem_ficha": sugestao.ano_pedido_sem_ficha,
    }
    base.update(campos)
    return Sugestao(**base)


def sugerir(
    consulta: str,
    linhas: Sequence[Linha],
    *,
    limite: int = LIMITE_PADRAO,
) -> Sugestoes:
    """Ordena o catálogo contra um texto solto.

    Devolve a melhor em destaque, as demais em `outras` e — quando a regra não elege
    ninguém — `vazia`, que é o sinal para a tela oferecer o Pesquisador em vez de uma
    lista de quase-acertos apresentada como acerto.
    """
    texto, ano_pedido = separar_ano(consulta)
    alvo = normalize(texto)
    if not alvo or not linhas:
        return Sugestoes(
            consulta=consulta,
            ano_pedido=ano_pedido,
            total=len(linhas),
            motivo="consulta vazia" if not alvo else "catálogo vazio",
        )

    candidatos = [normalize(linha.texto) for linha in linhas]
    resultado = matching.avaliar(alvo, candidatos)

    def como_sugestao(m: matching.Match) -> Sugestao:
        return _com_ano(
            Sugestao(
                linha=linhas[m.indice],
                score=m.score,
                cobertura=m.cobertura,
                exato=m.exato,
            ),
            ano_pedido,
        )

    # `todos` vem na ordem da lista recebida; a ordem que a tela mostra é cobertura
    # primeiro, score depois — a mesma prioridade que `avaliar` usa para decidir.
    ordenadas = sorted(resultado.todos, key=lambda m: (-m.cobertura, -m.score, m.valor))
    escolhidos = {m.indice for m in (resultado.empatados or ())}
    if resultado.vencedor is not None:
        escolhidos.add(resultado.vencedor.indice)

    melhor = como_sugestao(resultado.vencedor) if resultado.vencedor else None
    empatadas = tuple(como_sugestao(m) for m in resultado.empatados)
    outras = tuple(
        como_sugestao(m) for m in ordenadas if m.indice not in escolhidos and m.cobertura > 0
    )[: max(0, limite)]

    motivo = ""
    if melhor is None and empatadas:
        motivo = f"{len(empatadas)} versões empataram na mesma pontuação"
    elif melhor is None:
        motivo = "nenhuma versão do catálogo passou do limiar de semelhança"

    return Sugestoes(
        consulta=consulta,
        ano_pedido=ano_pedido,
        melhor=melhor,
        outras=outras,
        empatadas=empatadas,
        total=len(linhas),
        motivo=motivo,
        desempate="regra",
    )


@dataclass(frozen=True)
class AlvoDePesquisa:
    """O que mandar ao Pesquisador quando o catálogo não tem o carro.

    O Pesquisador pede marca, modelo e versão separados, e a caixa única recebe uma frase.
    Partir a frase em três pedaços pela posição das palavras dá errado no caso mais comum:
    *"amarok v6 highline"* viraria marca *"amarok"*, modelo *"v6"*, versão *"highline"* —
    e as consultas de busca sairiam todas erradas, gastando as duas rodadas do orçamento.
    """

    marca: str
    modelo: str
    versao: str
    de_onde: str = "texto"
    """`catalogo` quando marca e modelo vieram de um quase-acerto (o caminho bom);
    `texto` quando não houve quase-acerto nenhum e a frase foi partida por posição."""


def alvo_de_pesquisa(sugestoes: Sugestoes) -> AlvoDePesquisa:
    """Traduz a frase digitada no trio que o Pesquisador aceita.

    **A marca e o modelo saem do quase-acerto**, e é isso que faz a tradução funcionar:
    *"amarok v6 highline"* não casa com nenhuma versão do catálogo, mas casa **dois terços**
    da "Volkswagen Amarok V6 Extreme". Dali saem a marca e o modelo certos; o que a pessoa
    digitou e sobrou — *"v6 highline"* — é a versão.
    """
    texto, _ = separar_ano(sugestoes.consulta)
    candidatas = [
        *([sugestoes.melhor] if sugestoes.melhor else []),
        *sugestoes.empatadas,
        *sugestoes.outras,
    ]
    perto = next((s for s in candidatas if s.cobertura > 0), None)

    if perto is not None:
        marca, modelo = perto.linha.marca, perto.linha.modelo
        conhecidos = set(normalize(f"{marca} {modelo}").split())
        sobra = " ".join(p for p in texto.split() if normalize(p) not in conhecidos)
        return AlvoDePesquisa(
            marca=marca,
            modelo=modelo,
            versao=sobra.strip() or perto.linha.versao,
            de_onde="catalogo",
        )

    # Nenhum quase-acerto: a frase é tudo o que existe. Partir por posição é um chute, e
    # o `de_onde` diz que é — para a tela poder pedir confirmação em vez de sair correndo.
    partes = texto.split()
    return AlvoDePesquisa(
        marca=partes[0] if partes else "",
        modelo=partes[1] if len(partes) > 1 else "",
        versao=" ".join(partes[2:]),
        de_onde="texto",
    )


#: O que se pede ao modelo no desempate. Curto de propósito: a resposta é um índice.
_SISTEMA_DO_DESEMPATE = (
    "Você escolhe qual versão de um veículo a pessoa quis dizer. Responda apenas com o "
    "índice da opção. Se nenhuma opção corresponder claramente ao pedido, responda -1. "
    "Não invente versões; escolha entre as listadas ou nenhuma."
)


def desempatar(sugestoes: Sugestoes, *, cliente=None) -> Sugestoes:
    """**Uma** chamada ao modelo para escolher entre versões empatadas. Nunca mais de uma.

    O empate é raro por construção — `avaliar` só empata quando duas versões cobrem o
    pedido igual e pontuam igual — e é exatamente o caso em que a regra não tem mais o que
    dizer. Chamar o modelo antes disso seria pagar latência em toda tecla digitada para
    refazer o que o rapidfuzz já resolveu em microssegundos.

    Sem chave, ou com `LLM_FAKE=1`, devolve o empate **como está**. Empate visível é uma
    resposta honesta; empate desfeito por sorteio não é.
    """
    if not sugestoes.ambigua:
        return sugestoes

    from pipeline import llm  # local: manter o módulo importável sem o LiteLLM

    if llm.modo_fake() or not llm.tem_chave():
        return _trocar_sugestoes(
            sugestoes,
            motivo=f"{sugestoes.motivo}; sem chave de IA para desempatar",
        )

    opcoes = "\n".join(f"{i}: {s.linha.texto}" for i, s in enumerate(sugestoes.empatadas))
    resposta = llm.extrair_json(
        prompt=(
            f'A pessoa digitou: "{sugestoes.consulta}"\n\n'
            f"Opções:\n{opcoes}\n\n"
            'Responda {"escolhida": <índice>, "porque": "<até 12 palavras>"}.'
        ),
        campos=["escolhida", "porque"],
        sistema=_SISTEMA_DO_DESEMPATE,
        max_tokens=256,
        cliente=cliente,
    )
    if not resposta.ok:
        return _trocar_sugestoes(
            sugestoes,
            motivo=f"{sugestoes.motivo}; a IA não respondeu ({resposta.motivo[:80]})",
        )

    try:
        escolhida = int(resposta.dados.get("escolhida"))
    except (TypeError, ValueError):
        escolhida = -1
    if not 0 <= escolhida < len(sugestoes.empatadas):
        # Inclui o -1 combinado: "nenhuma das opções". O empate continua de pé, e é a
        # resposta certa — melhor duas opções na tela do que uma errada em destaque.
        return _trocar_sugestoes(
            sugestoes,
            motivo=f"{sugestoes.motivo}; a IA não escolheu nenhuma",
        )

    vencedora = sugestoes.empatadas[escolhida]
    perdedoras = tuple(s for i, s in enumerate(sugestoes.empatadas) if i != escolhida)
    porque = str(resposta.dados.get("porque") or "").strip()[:120]
    return _trocar_sugestoes(
        sugestoes,
        melhor=vencedora,
        empatadas=(),
        outras=perdedoras + sugestoes.outras,
        desempate="ia",
        motivo=f"empate desfeito pela IA{f': {porque}' if porque else ''}",
    )


def _trocar_sugestoes(sugestoes: Sugestoes, **campos) -> Sugestoes:
    base = {
        "consulta": sugestoes.consulta,
        "ano_pedido": sugestoes.ano_pedido,
        "melhor": sugestoes.melhor,
        "outras": sugestoes.outras,
        "empatadas": sugestoes.empatadas,
        "total": sugestoes.total,
        "motivo": sugestoes.motivo,
        "desempate": sugestoes.desempate,
    }
    base.update(campos)
    return Sugestoes(**base)
