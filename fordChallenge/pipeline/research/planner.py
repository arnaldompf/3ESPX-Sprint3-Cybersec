"""O planejador: de `marca + modelo + versão` para **consultas por tier**.

**Determinístico de propósito**, e essa é a decisão mais discutível deste módulo — então
vale explicar. Os quatro motores de busca estudados em 12/09/2026 usam um modelo de
linguagem para expandir a pergunta em N consultas, e faz sentido para eles: a pergunta é
livre, e o modelo é bom em achar ângulos que o autor não pensou.

Aqui a pergunta **não é livre**. É sempre a mesma: *quais são os 58 campos desta versão?*
Um modelo gerando consultas criativas sobre isso gastaria uma chamada por rodada para
reinventar, com variações, as mesmas seis frases que um template escreve de graça — e com
o risco de escrever uma que não devolve nada. Onde o modelo é insubstituível é na leitura
do documento, e é lá que ele é chamado.

**A inversão que os quatro não fazem.** A expansão deles é por *ângulo editorial* (o que
é, como compara, o que dizem os donos). A nossa é por **família de campos**, com um mapa
`consulta → campos_alvo`: é o que permite, na segunda rodada, perguntar exatamente pelo que
ficou vazio em vez de repetir a busca inteira.

**Operadores de busca são armadilha, e a saída é medir.** O gpt-researcher **proíbe**
`site:` e `filetype:` nos prompts dele porque muitos backends devolvem vazio com eles. Nós
os usamos na rodada T1 — são o caminho mais curto para o PDF oficial —, mas cada consulta
carrega `tem_operador`, e o run registra qual das duas formas trouxe a fonte. Se a restrita
vier vazia, a aberta já está na fila.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.research import fontes
from pipeline.research.classify import OFICIAIS
from pipeline.schema import GRUPOS

#: As famílias de campo, e como se pergunta por cada uma em português.
#:
#: O rótulo à direita entra literalmente na consulta da segunda rodada — é ele que
#: transforma "faltam `capacidade_reboque_kg` e `tanque_l`" numa frase que um buscador
#: entende. Sem esse mapa, a consulta dirigida sairia com o nome da coluna do banco, que é
#: o defeito que o projeto já corrigiu em outras três telas.
#:
#: As chaves **são** os grupos de `pipeline.schema.GRUPOS`, e um teste confere que o mapa
#: cobre o schema inteiro. `identificacao` fica de fora de propósito: marca, modelo e versão
#: são a **entrada** da pesquisa, não o que ela procura.
FAMILIAS: dict[str, str] = {
    "motorizacao": "motor potência torque",
    "transmissao": "câmbio transmissão marchas",
    "tracao": "tração reduzida bloqueio de diferencial",
    "chassi": "suspensão freios direção",
    "desempenho": "desempenho aceleração velocidade máxima consumo",
    "modos": "modos de condução",
    "exterior": "rodas pneus faróis",
    "dimensoes": "dimensões capacidade de carga reboque tanque",
    "seguranca": "itens de segurança ADAS airbags",
    "comercial": "preço garantia",
}

#: Como cada campo se lê numa consulta dirigida da segunda rodada.
#:
#: Só os campos em que o nome canônico não vira uma boa busca sozinho. O resto sai de
#: `campo.replace("_", " ")`, que já funciona: `capacidade_carga_kg` → "capacidade carga kg"
#: é uma consulta razoável.
COMO_SE_PERGUNTA: dict[str, str] = {
    "adas_itens": "itens de assistência à condução ADAS",
    "adas_nome_comercial": "nome do pacote de assistência à condução",
    "aceleracao_0_100_s": "aceleração de 0 a 100 km/h em segundos",
    "airbags_qtd": "quantidade de airbags",
    "bloqueio_diferencial": "bloqueio de diferencial traseiro",
    "capacidade_carga_kg": "capacidade de carga útil em kg",
    "capacidade_reboque_kg": "capacidade de reboque em kg",
    "codigo_fipe": "código FIPE",
    "consumo_rodoviario_kml": "consumo na estrada km/l",
    "consumo_urbano_kml": "consumo na cidade km/l",
    "entre_eixos_mm": "distância entre eixos em mm",
    "garantia_meses": "garantia de fábrica em meses",
    "largura_mm": "largura da carroceria sem espelhos retrovisores",
    "preco_fipe_brl": "preço na tabela FIPE",
    "preco_sugerido_brl": "preço sugerido",
    "paddle_shifters": "trocas de marcha por aletas no volante",
    "reduzida": "tração com caixa de redução 4L",
    "suspensao_dianteira": "tipo de suspensão dianteira",
    "suspensao_traseira": "tipo de suspensão traseira",
    "amortecedores": "tipo de amortecedores",
    "modos_amortecedor": "ajustes selecionáveis dos amortecedores",
    "modos_direcao": "ajustes selecionáveis da assistência de direção",
    "modos_escapamento": "modos selecionáveis do escapamento",
    "tanque_l": "capacidade do tanque de combustível em litros",
    "vel_max_kmh": "velocidade máxima",
}

#: Quantas consultas dirigidas a segunda rodada pode disparar.
#:
#: Três, pelo mesmo motivo pelo qual o argumentário tem três pontos: com o orçamento de
#: doze páginas, uma quarta consulta compraria resultados que não caberiam na coleta.
LIMITE_DE_CONSULTAS_DIRIGIDAS = 3


@dataclass(frozen=True)
class Consulta:
    """Uma consulta ao buscador, com o **porquê** dela viajando junto.

    `campos_alvo` é o que separa este planejador dos quatro estudados: a consulta sabe o
    que ela está tentando preencher, e por isso a rodada seguinte pode perguntar só pelo
    que ficou faltando.
    """

    texto: str
    tier: int
    motivo: str
    campos_alvo: tuple[str, ...] = ()
    tem_operador: bool = False
    dominios: tuple[str, ...] = ()
    """Restringe a busca aos domínios que a sondagem aprovou (`fontes.yaml`).

    É a diferença entre procurar na web e procurar **onde tem ficha**. Medido na primeira
    pesquisa ao vivo da S10: 15 dos 20 resultados eram de domínios que a coleta jamais
    aceitaria, e cada um deles custou uma busca."""

    def to_dict(self) -> dict[str, object]:
        return {
            "texto": self.texto,
            "tier": self.tier,
            "motivo": self.motivo,
            "campos_alvo": list(self.campos_alvo),
            "tem_operador": self.tem_operador,
            "dominios": list(self.dominios),
        }


@dataclass
class Alvo:
    """O veículo pedido. `ano` é opcional — a maioria das buscas funciona sem ele."""

    marca: str
    modelo: str
    versao: str = ""
    ano: int | None = None
    mercado: str = "Brasil"

    @property
    def nome(self) -> str:
        return " ".join(p for p in (self.marca, self.modelo, self.versao) if p).strip()

    def qualificar(self, consultas: list[Consulta]) -> list[Consulta]:
        from dataclasses import replace

        result = []
        for consulta in consultas:
            text = consulta.texto
            for token in (self.versao, str(self.ano) if self.ano else "", self.mercado):
                if token and token not in text:
                    text += " " + token
            result.append(replace(consulta, texto=normalizar(text)))
        return result


def _campos_da_familia(familia: str) -> tuple[str, ...]:
    """Os campos canônicos de uma família. A família **é** um grupo do schema."""
    return GRUPOS.get(familia, ())


def primeira_rodada(alvo: Alvo) -> list[Consulta]:
    """As consultas de abertura, **uma por tier**, todas de uma vez.

    Fan-out, e não cascata: esperar o T1 terminar para só então perguntar à FIPE gastaria
    metade do orçamento de três minutos em espera. O que é sequencial é a **coleta** (um
    domínio por vez, 1 req/s); a busca não precisa ser.

    A ordem da lista é a ordem de preferência, e ela sobrevive ao fan-out porque o
    classificador ordena o resultado por tier de novo.
    """
    nome = alvo.nome
    ano = str(alvo.ano) if alvo.ano else ""
    dominios = OFICIAIS.get(alvo.marca, ())
    consultas: list[Consulta] = []

    # ---------------------------------------------------------------- T1: a montadora
    if dominios:
        consultas.append(
            Consulta(
                texto=f"site:{dominios[0]} {alvo.modelo} {alvo.versao} ficha técnica".strip(),
                tier=1,
                motivo="ficha no site oficial, restrita ao domínio da montadora",
                tem_operador=True,
            )
        )
        consultas.append(
            Consulta(
                texto=f"site:{dominios[0]} filetype:pdf {alvo.modelo} {ano}".strip(),
                tier=1,
                motivo="catálogo em PDF: é a ficha inteira, em tabela, sem JavaScript",
                tem_operador=True,
            )
        )

    # A forma aberta vai junto, e não depois: `site:` devolve vazio em vários backends, e
    # descobrir isso só na segunda rodada custaria metade do orçamento.
    consultas.append(
        Consulta(
            texto=f"{nome} ficha técnica oficial",
            tier=1,
            motivo="ficha oficial, busca aberta (rede de segurança do `site:`)",
        )
    )
    consultas.append(
        Consulta(
            texto=f"{alvo.marca} {alvo.modelo} catálogo pdf {ano}".strip(),
            tier=1,
            motivo="catálogo em PDF, busca aberta",
        )
    )
    consultas.append(
        Consulta(
            texto=f"{alvo.marca} sala de imprensa {alvo.modelo}",
            tier=1,
            motivo="release da montadora: costuma trazer a ficha completa do lançamento",
        )
    )

    # --------------------------------------------------- T2: registro de terceiro
    consultas.append(
        Consulta(
            texto=f"tabela fipe {nome}",
            tier=2,
            motivo="preço de referência",
            campos_alvo=("preco_fipe_brl", "codigo_fipe"),
        )
    )
    consultas.append(
        Consulta(
            texto=f"{alvo.marca} {alvo.modelo} PBE Inmetro consumo",
            tier=2,
            motivo="consumo **medido** pelo Inmetro, que é outra coisa do consumo declarado",
            campos_alvo=("consumo_urbano_kml", "consumo_rodoviario_kml"),
        )
    )

    # --------------------------------------------- T3: os sites de ficha, restritos
    #
    # **Uma consulta, muitos domínios.** A Tavily aceita `include_domains` e não cobra a
    # mais por isso; para o que a montadora não publica (dimensões, suspensão, freios,
    # capacidade de carga), a ficha de terceiro é onde o número está. Sem a restrição,
    # a mesma frase traz classificado, fórum e revenda — medido: 15 de 20 resultados da
    # S10 vieram de domínios que a coleta jamais aceitaria.
    de_ficha = tuple(fontes.dominios_de_ficha())
    if de_ficha:
        consultas.append(
            Consulta(
                texto=f"{nome} ficha técnica completa",
                tier=3,
                motivo=(
                    f"ficha de terceiro, restrita a {len(de_ficha)} site(s) que a sondagem aprovou"
                ),
                dominios=de_ficha,
            )
        )

    # A forma aberta continua, para o caso de a restrição não achar nada: `include_domains`
    # com uma lista estreita pode voltar vazio, e uma rodada sem resultado é pior que uma
    # rodada com resultado ruim — o classificador filtra depois.
    for veiculo in ("quatro rodas", "autoesporte", "noticias automotivas"):
        consultas.append(
            Consulta(
                texto=f"{nome} ficha técnica {veiculo}",
                tier=3,
                motivo=f"ficha da imprensa ({veiculo}): completa o que o oficial não publica",
            )
        )

    return alvo.qualificar(consultas)


def consultas_de_lacuna(
    alvo: Alvo, faltando: list[str], *, tentadas: set[str] | None = None
) -> list[Consulta]:
    """As consultas dirigidas da segunda rodada, a partir dos campos que ficaram vazios.

    **Agrupa por família antes de perguntar.** Uma consulta por campo esgotaria o orçamento
    em quinze buscas para preencher quinze lacunas, e a página que responde "capacidade de
    carga" quase sempre responde "capacidade de reboque" na linha de baixo — são a mesma
    tabela. Perguntar pela família é perguntar pela tabela.

    Fora da família conhecida, o campo vira uma consulta própria com o rótulo humano de
    `COMO_SE_PERGUNTA` — nunca o nome da coluna. Depois de esgotar essas consultas,
    `tentadas` libera alternativas com até dois atributos, domínio oficial e busca aberta.
    O histórico é de textos, como nos checkpoints existentes; cada alternativa tem texto
    próprio para que mudar o filtro de domínio não seja confundido com repetir uma busca.
    """
    if not faltando:
        return []

    por_familia: dict[str, list[str]] = {}
    soltos: list[str] = []
    for campo in faltando:
        familia = next((f for f in FAMILIAS if campo in _campos_da_familia(f)), "")
        if familia:
            por_familia.setdefault(familia, []).append(campo)
        else:
            soltos.append(campo)

    # A família com mais lacunas primeiro: é onde uma página só rende mais.
    ordenadas = sorted(por_familia.items(), key=lambda par: (-len(par[1]), par[0]))

    # **A lacuna vai aos sites de ficha, não à web aberta.** O que sobra depois da primeira
    # rodada é justamente o que a montadora não publica — dimensões, suspensão, freios,
    # capacidade de carga —, e é o que a ficha de terceiro traz em tabela. Na S10, dez das
    # onze famílias ficaram vazias, e nenhuma consulta dirigida chegou a um site de ficha.
    de_ficha = tuple(fontes.dominios_de_ficha())

    consultas: list[Consulta] = []
    for familia, campos in ordenadas:
        consultas.append(
            Consulta(
                texto=f"{alvo.nome} {FAMILIAS[familia]}",
                tier=3 if de_ficha else 1,
                motivo=f"lacuna: {len(campos)} campo(s) de {familia} sem valor",
                campos_alvo=tuple(sorted(campos)),
                dominios=de_ficha,
            )
        )

    for campo in soltos:
        consultas.append(
            Consulta(
                texto=f"{alvo.nome} {como_se_pergunta(campo)}",
                tier=3 if de_ficha else 1,
                motivo=f"lacuna: {campo.replace('_', ' ')} sem valor",
                campos_alvo=(campo,),
                dominios=de_ficha,
            )
        )

    # Filtra antes do teto: as três famílias iniciais já tentadas não podem ocultar
    # outras estratégias quando há orçamento para continuar.
    qualificadas = alvo.qualificar(consultas)
    novas = [c for c in qualificadas if c.texto not in (tentadas or set())]
    if novas or not tentadas:
        return novas[:LIMITE_DE_CONSULTAS_DIRIGIDAS]

    # A mesma frase por família costuma retornar as mesmas fichas. Antes de abandonar
    # a lacuna, nomeie os atributos e varie a origem dos resultados. A abertura inicial
    # permanece idêntica, inclusive para os replays gravados. São consultas candidatas:
    # orçamento e coleta continuam sendo responsabilidade do motor, não deste plano.
    grupos = [sorted(set(campos)) for _, campos in ordenadas]
    grupos.extend([[campo] for campo in dict.fromkeys(soltos)])
    oficiais = OFICIAIS.get(alvo.marca, ())
    # Nome de busca não é identidade da evidência. A grafia longa do catálogo pode não
    # aparecer no índice: retire descritores mecânicos apenas nas alternativas. A versão
    # comercial, o ano e o país continuam presentes; a validação usa o alvo original.
    versao_curta = normalizar(
        re.sub(
            r"\b(?:\d[.,]\d(?:\s*(?:l|litros))?|v[468]|4wd|awd|4x[24]|2wd|at|mt|cvt|"
            r"diesel|flex|gasolina|bi[- ]?turbo|turbo)\b",
            " ",
            alvo.versao,
            flags=re.I,
        )
    )
    ampliado = Alvo(
        marca=alvo.marca,
        modelo=alvo.modelo,
        versao=versao_curta or alvo.versao,
        ano=alvo.ano,
        mercado=alvo.mercado,
    )
    alternativas: list[Consulta] = []
    for campos in grupos:
        for inicio in range(0, len(campos), 2):
            par = tuple(campos[inicio : inicio + 2])
            termos = "; ".join(como_se_pergunta(campo) for campo in par)
            alternativas.append(
                Consulta(
                    texto=f"{alvo.nome} {termos} especificações",
                    tier=3 if de_ficha else 1,
                    motivo="lacuna persistente: atributos específicos nos sites de ficha",
                    campos_alvo=par,
                    dominios=de_ficha,
                )
            )
            if oficiais:
                alternativas.append(
                    Consulta(
                        texto=f"site:{oficiais[0]} {ampliado.nome} {termos}",
                        tier=1,
                        motivo="lacuna persistente: conferir os atributos na montadora",
                        campos_alvo=par,
                        tem_operador=True,
                        dominios=oficiais,
                    )
                )
            alternativas.append(
                Consulta(
                    texto=f"{ampliado.nome} {termos} ficha técnica",
                    tier=3,
                    motivo="lacuna persistente: busca aberta para diversificar documentos",
                    campos_alvo=par,
                )
            )

    vistas = set(tentadas)
    for consulta in ampliado.qualificar(alternativas):
        if consulta.texto in vistas:
            continue
        vistas.add(consulta.texto)
        novas.append(consulta)
        if len(novas) == LIMITE_DE_CONSULTAS_DIRIGIDAS:
            break
    return novas


def como_se_pergunta(campo: str) -> str:
    """O campo em português de busca. Nunca o nome da coluna."""
    return COMO_SE_PERGUNTA.get(campo, campo.replace("_", " "))


@dataclass
class Plano:
    """O que o run vai perguntar, e com que orçamento."""

    alvo: Alvo
    consultas: list[Consulta] = field(default_factory=list)

    def sem_operadores(self) -> list[Consulta]:
        """A mesma lista, sem as consultas que dependem de `site:`/`filetype:`.

        É o plano B quando o provedor de busca devolve zero para operadores — que é o
        comportamento que o gpt-researcher documenta e evita proibindo os operadores por
        completo. Aqui eles ficam, e a queda é medida.
        """
        return [c for c in self.consultas if not c.tem_operador]


def planejar(marca: str, modelo: str, versao: str = "", ano: int | None = None) -> Plano:
    alvo = Alvo(marca=marca.strip(), modelo=modelo.strip(), versao=versao.strip(), ano=ano)
    return Plano(alvo=alvo, consultas=primeira_rodada(alvo))


def normalizar(texto: str) -> str:
    """Espaços colapsados. Uma consulta com espaço duplo é outra chave de cache."""
    return re.sub(r"\s+", " ", texto).strip()
