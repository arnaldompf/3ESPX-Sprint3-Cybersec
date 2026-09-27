"""De um texto solto para um veículo — **perguntando**, quando não dá para saber.

Quem digita `"Hilux"` não disse qual carro quer: a Toyota vende sete versões dela. As duas
saídas ruins são escolher uma no chute e devolver "não encontrado". A saída certa é a que
uma pessoa daria: **perguntar qual**, mostrando as que existem.

**Três fontes, nesta ordem, e a ordem é a economia.**

1. **o catálogo**, de graça e instantâneo. Se o texto casa com uma versão que já temos
   ficha, acabou — não há o que perguntar nem o que pesquisar;
2. **uma busca leve**, até três consultas, com cache por dia. É ela que descobre que a
   Hilux tem SR, SRV e SRX **hoje**, e não em 2019;
3. **uma chamada de modelo pequeno**, que só organiza o que a busca trouxe.

**O modelo nunca lista versões de memória, e isso não é preferência.** Ele recebe os
títulos e resumos que o buscador devolveu e é instruído a escolher **entre eles**. Uma opção
sem fonte é descartada antes de chegar à tela — a mesma regra do resto do pipeline, aplicada
à navegação: se ninguém publicou, nós não sabemos.

**O ano nunca vira pergunta.** Vale o que a pessoa escreveu (`"S10 2027"`); senão, o que
as fontes dizem da linha atual; senão, o **ano vigente**, e a resposta diz de onde o ano
saiu (`ano_origem`) para a tela rotular o assumido como INFERÊNCIA e deixar trocar.
Perguntar o ano a quem quer saber quantos cavalos o carro tem é fazer a pessoa trabalhar
para a ferramenta.

**Modelo ambíguo também é pergunta.** *"a picape nova da RAM"* pode ser Rampage ou Dakota;
o modelo devolve os modelos que os resultados sustentam, e a tela pergunta qual — antes de
perguntar a versão.

**Sem chave de modelo, o módulo continua funcionando** — só com o catálogo, que é o
comportamento de antes. A demonstração roda assim, e é por isso que ela roda.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pipeline import sugestao
from pipeline.ontology import normalize
from pipeline.version_names import nome_canonico_de_versao

#: O teto de resultados que vão ao modelo. Oito páginas dão o panorama de uma linha de
#: versões; vinte só encarecem o prompt e trazem revenda e classificado.
RESULTADOS_NA_BUSCA = 8

#: Quantos resultados pedir a cada consulta. Menos que o teto, porque são três consultas.
RESULTADOS_POR_CONSULTA = 5

#: O teto de saída da chamada. A resposta é uma lista curta de nomes — não precisa de mais,
#: e um teto largo aqui só paga raciocínio que ninguém lê. (Com o raciocínio desligado, a
#: resposta medida em 13/09/2026 teve 368 tokens.)
TETO_DE_SAIDA = 1200

#: Quantas opções chegam à tela. Acima disso, a pergunta deixa de ser uma pergunta.
MAXIMO_DE_OPCOES = 8

_SISTEMA = (
    "Você ajuda alguém a identificar QUAL veículo (marca, modelo e versão) ela quer, a "
    "partir de resultados de busca que eu te dou. Regras: (1) só cite modelos e versões que "
    "aparecem nos resultados — nunca de memória; (2) para cada item, diga de qual resultado "
    "ele saiu, pelo número; (3) prefira a linha mais recente (o ano-modelo mais novo que os "
    "resultados mostram) e não misture anos antigos; (4) se o texto puder ser mais de um "
    "modelo, liste os modelos em vez das versões; (5) se os resultados não permitirem "
    "identificar, diga isso. Responda em português do Brasil, só com o JSON pedido."
)


@dataclass(frozen=True)
class Opcao:
    """Uma escolha que a busca sustenta, com a fonte de onde saiu.

    `fontes` vazio faz a opção ser descartada antes da tela: uma versão sem fonte é o
    modelo respondendo de memória, que é o que este módulo existe para não fazer.
    `tipo` é `versao` (o caso comum) ou `modelo` (quando o texto podia ser mais de um carro).
    """

    valor: str
    detalhe: str = ""
    fontes: tuple[str, ...] = ()
    tipo: str = "versao"
    marca: str = ""
    modelo: str = ""
    ano: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valor": self.valor,
            "detalhe": self.detalhe,
            "fontes": list(self.fontes),
            "tipo": self.tipo,
            "marca": self.marca,
            "modelo": self.modelo,
            "ano": self.ano,
        }


#: Os três desfechos. `nao_entendi` é resultado, não erro.
RESOLVIDO = "resolvido"
PRECISA_ESCOLHER = "precisa_escolher"
NAO_ENTENDI = "nao_entendi"

#: De onde saiu o ano-modelo da resposta.
ANO_DO_PEDIDO = "pedido"
ANO_DAS_FONTES = "fontes"
ANO_VIGENTE = "vigente"
ANO_DO_CATALOGO = "catalogo"

#: Marcas que permitem reconhecer um pedido **estruturado pelo próprio usuário** sem
#: gastar modelo. Não é uma lista de veículos nem uma fonte de dado técnico: serve apenas
#: para separar `marca | modelo | versão` em textos completos como
#: `"Mitsubishi Triton HPE-S"`. Apelidos só normalizam a marca, nada mais.
_MARCAS_DO_PEDIDO: tuple[tuple[str, str], ...] = (
    ("land rover", "Land Rover"),
    ("mercedes benz", "Mercedes-Benz"),
    ("alfa romeo", "Alfa Romeo"),
    ("aston martin", "Aston Martin"),
    ("chevrolet", "Chevrolet"),
    ("citroen", "Citroën"),
    ("mitsubishi", "Mitsubishi"),
    ("volkswagen", "Volkswagen"),
    ("hyundai", "Hyundai"),
    ("renault", "Renault"),
    ("peugeot", "Peugeot"),
    ("nissan", "Nissan"),
    ("toyota", "Toyota"),
    ("honda", "Honda"),
    ("ford", "Ford"),
    ("fiat", "Fiat"),
    ("jeep", "Jeep"),
    ("audi", "Audi"),
    ("bmw", "BMW"),
    ("byd", "BYD"),
    ("gwm", "GWM"),
    ("kia", "Kia"),
    ("ram", "RAM"),
    ("volvo", "Volvo"),
    ("vw", "Volkswagen"),
)


@dataclass(frozen=True)
class Identificacao:
    """O que se sabe do veículo, e o que falta perguntar."""

    texto: str
    estado: str = NAO_ENTENDI
    marca: str = ""
    modelo: str = ""
    versao: str = ""
    ano: int | None = None
    ano_origem: str = ""
    """`pedido` (estava no texto), `fontes` (os resultados mostram), `vigente` (assumido —
    a tela rotula INFERÊNCIA), `catalogo` (a versão já existe)."""
    pergunta: str = ""
    """A pergunta em português, pronta para a tela. Vazia quando não há o que perguntar."""
    opcoes: tuple[Opcao, ...] = ()
    origem: str = "catalogo"
    """`catalogo` (de graça), `busca` (consultas + uma chamada de modelo) ou `nenhuma`."""
    consultas: tuple[str, ...] = ()
    fontes: tuple[str, ...] = ()
    motivo: str = ""
    uso: dict[str, Any] = field(default_factory=dict)
    """O que a chamada custou: chamadas, tokens, custo. Vazio quando não houve chamada."""
    version_id: str = ""
    """A versão do catálogo, quando a identificação saiu de lá."""
    tem_ficha: bool = False

    @property
    def nome(self) -> str:
        return " ".join(p for p in (self.marca, self.modelo, self.versao) if p).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "texto": self.texto,
            "estado": self.estado,
            "marca": self.marca,
            "modelo": self.modelo,
            "versao": self.versao,
            "ano": self.ano,
            "ano_origem": self.ano_origem,
            "nome": self.nome,
            "pergunta": self.pergunta,
            "opcoes": [o.to_dict() for o in self.opcoes],
            "origem": self.origem,
            "consultas": list(self.consultas),
            "fontes": list(self.fontes),
            "motivo": self.motivo,
            "uso": dict(self.uso),
            "version_id": self.version_id,
            "tem_ficha": self.tem_ficha,
        }


def ano_vigente() -> int:
    """O ano assumido quando ninguém disse e nenhuma fonte mostrou."""
    return dt.date.today().year


def _do_pedido_explicito(texto_sem_ano: str, ano: int | None) -> Identificacao | None:
    """Lê `marca modelo versão` quando a pessoa escreveu as três partes.

    O alvo da pesquisa não é um dado técnico e não precisa ser descoberto por LLM
    quando veio literalmente do pedido. Exigimos uma marca conhecida no prefixo e pelo
    menos modelo + versão; `"Triton"` ou `"a picape nova da RAM"` continuam ambíguos e
    seguem para a busca/modelo. A pesquisa subsequente ainda aplica os gates de identidade
    a cada fonte, portanto isto não autoriza misturar outra versão.
    """
    partes = texto_sem_ano.strip().split()
    for alias, marca in _MARCAS_DO_PEDIDO:
        n_marca = len(alias.split())
        if len(partes) < n_marca + 2:
            continue
        if normalize(" ".join(partes[:n_marca])) != normalize(alias):
            continue
        modelo = partes[n_marca]
        versao = " ".join(partes[n_marca + 1 :]).strip()
        if not modelo or not versao:
            return None
        ano_final = ano or ano_vigente()
        return Identificacao(
            texto=texto_sem_ano if ano is None else f"{texto_sem_ano} {ano}",
            estado=RESOLVIDO,
            marca=marca,
            modelo=modelo,
            versao=nome_canonico_de_versao(modelo, versao),
            ano=ano_final,
            ano_origem=ANO_DO_PEDIDO if ano else ANO_VIGENTE,
            origem="pedido",
            motivo="marca, modelo e versão foram informados no pedido",
        )
    return None


def consultas_de_versoes(texto: str, ano: int | None = None) -> list[str]:
    """As buscas que descobrem as versões de hoje. Três, e em português.

    "ficha técnica" e "versões" porque é assim que a imprensa automotiva brasileira titula
    a página que lista versões; "site oficial" porque a página da montadora é a que
    responde com autoridade — e o classificador da pesquisa vai preferi-la depois.
    """
    base = texto.strip()
    alvo = ano or ano_vigente()
    return [
        f"{base} versões ficha técnica",
        f"{base} versões {alvo} preços",
        f"{base} site oficial",
    ]


def consulta_de_versoes(texto: str) -> str:
    """A primeira das consultas. Mantida para quem chamava a versão de uma consulta só."""
    return consultas_de_versoes(texto)[0]


def _do_catalogo(texto: str, catalogo: Sequence[sugestao.Linha]) -> Identificacao | None:
    """O caminho de graça: o texto casa com o que já temos?

    Só devolve `resolvido` quando **uma** versão vence. Empate não é resposta: vira a
    pergunta, com as empatadas como opções — e sem gastar busca nem modelo, porque o
    catálogo já respondeu o suficiente.
    """
    if not catalogo:
        return None
    r = sugestao.sugerir(texto, catalogo)
    if r.melhor is not None:
        ano = r.melhor.ano_escolhido
        return Identificacao(
            texto=texto,
            estado=RESOLVIDO,
            marca=r.melhor.linha.marca,
            modelo=r.melhor.linha.modelo,
            versao=r.melhor.linha.versao,
            ano=ano.ano_modelo if ano else None,
            ano_origem=ANO_DO_CATALOGO if ano else "",
            origem="catalogo",
            motivo="a versão já está no catálogo",
            version_id=(ano.version_id if ano else "") or "",
            tem_ficha=bool(ano and ano.tem_ficha),
        )
    if r.ambigua:
        return Identificacao(
            texto=texto,
            estado=PRECISA_ESCOLHER,
            marca=r.empatadas[0].linha.marca,
            modelo=r.empatadas[0].linha.modelo,
            pergunta="Qual destas versões você quer?",
            opcoes=tuple(
                Opcao(
                    valor=s.linha.versao,
                    detalhe="já está no catálogo",
                    marca=s.linha.marca,
                    modelo=s.linha.modelo,
                    ano=s.ano_escolhido.ano_modelo if s.ano_escolhido else None,
                )
                for s in r.empatadas[:MAXIMO_DE_OPCOES]
            ),
            origem="catalogo",
            motivo=r.motivo,
        )
    return None


def _buscar(texto: str, *, ano: int | None, provedor: str = ""):
    """A busca leve: até três consultas, resultados deduplicados por URL.

    Devolve `(achados, consultas, falha)` — `falha` preenchida só quando **nenhuma**
    consulta respondeu. Uma consulta fora do ar não derruba as outras duas.
    """
    from pipeline.research import search

    consultas = consultas_de_versoes(texto, ano)
    achados: list = []
    vistos: set[str] = set()
    falhas: list[str] = []
    for consulta in consultas:
        try:
            resposta = search.buscar(consulta, provedor=provedor, quantos=RESULTADOS_POR_CONSULTA)
        except Exception as exc:
            # Busca fora do ar, sem chave ou proibida em replay. Nenhuma delas é motivo para
            # a tela quebrar: o caminho do catálogo já respondeu o que dava.
            falhas.append(f"{type(exc).__name__}: {exc}"[:160])
            continue
        if not resposta.ok:
            falhas.append(str(resposta.erro)[:160])
            continue
        for achado in resposta.achados:
            if achado.url in vistos:
                continue
            vistos.add(achado.url)
            achados.append(achado)
            if len(achados) >= RESULTADOS_NA_BUSCA:
                break
        if len(achados) >= RESULTADOS_NA_BUSCA:
            break
    falha = "" if achados or not falhas else falhas[0]
    return achados[:RESULTADOS_NA_BUSCA], consultas, falha


def _prompt(texto: str, achados, *, ano: int | None = None) -> str:
    linhas = [f'A pessoa digitou: "{texto}"']
    if ano:
        linhas.append(f"Ela quer o ano-modelo {ano}.")
    else:
        linhas.append(
            f"Ela não disse o ano: prefira a linha mais recente (hoje é {ano_vigente()})."
        )
    linhas += ["", "Resultados da busca:"]
    for i, achado in enumerate(achados, 1):
        titulo = " ".join(str(achado.titulo or "").split())
        linhas.append(f"[{i}] {titulo}")
        if achado.snippet:
            linhas.append(f"    {' '.join(str(achado.snippet).split())[:400]}")
    linhas += [
        "",
        "Responda com este JSON:",
        "{",
        '  "marca": "<marca, ou vazio>",',
        '  "modelo": "<modelo, ou vazio se o texto puder ser mais de um modelo>",',
        '  "versao": "<a versão, SE a pessoa já disse qual; senão vazio>",',
        '  "ano_modelo": <o ano-modelo da linha atual que os resultados mostram, ou null>,',
        '  "modelos": [{"marca": "<marca>", "modelo": "<modelo>", "fonte": <número>}],',
        '  "versoes": [{"nome": "<nome da versão>", "detalhe": "<até 8 palavras>",',
        '               "fonte": <número do resultado>, "ano": <ano ou null>}],',
        '  "pergunta": "<a pergunta a fazer, ou vazio se não há dúvida>"',
        "}",
        "",
        "Preencha `modelos` só quando o texto puder ser mais de um modelo; nesse caso deixe "
        "`versoes` vazio. Só inclua o que aparece nos resultados acima, com o número da fonte.",
    ]
    return "\n".join(linhas)


def _lista(dados: dict[str, Any], chave: str) -> list:
    bruto = dados.get(chave)
    if isinstance(bruto, str):
        # Alguns modelos devolvem a lista como texto JSON. Vale tentar uma vez.
        try:
            bruto = json.loads(bruto)
        except (TypeError, ValueError):
            return []
    return list(bruto) if isinstance(bruto, list) else []


def _indice_valido(bruto: Any, achados) -> int | None:
    try:
        indice = int(bruto)
    except (TypeError, ValueError):
        return None
    return indice if 1 <= indice <= len(achados) else None


def _inteiro(bruto: Any) -> int | None:
    try:
        valor = int(str(bruto).strip()[:4])
    except (TypeError, ValueError):
        return None
    return valor if 1990 <= valor <= 2100 else None


def _opcoes_de(dados: dict[str, Any], achados, *, marca: str, modelo: str) -> tuple[Opcao, ...]:
    """As versões do modelo, **filtradas pelas que têm fonte**."""
    saida: list[Opcao] = []
    vistos: set[str] = set()
    for bruto in _lista(dados, "versoes"):
        if not isinstance(bruto, dict):
            continue
        nome = str(bruto.get("nome") or "").strip()
        if not nome or normalize(nome) in vistos:
            continue
        indice = _indice_valido(bruto.get("fonte"), achados)
        if indice is None:
            # Fonte inventada é opção inventada. Cair fora é mais barato que explicar.
            continue
        vistos.add(normalize(nome))
        saida.append(
            Opcao(
                valor=nome,
                detalhe=str(bruto.get("detalhe") or "").strip()[:80],
                fontes=(achados[indice - 1].url,),
                tipo="versao",
                marca=marca,
                modelo=modelo,
                ano=_inteiro(bruto.get("ano")),
            )
        )
    return tuple(saida[:MAXIMO_DE_OPCOES])


def _modelos_de(dados: dict[str, Any], achados) -> tuple[Opcao, ...]:
    """Os modelos possíveis, quando o texto podia ser mais de um carro. Só com fonte."""
    saida: list[Opcao] = []
    vistos: set[str] = set()
    for bruto in _lista(dados, "modelos"):
        if not isinstance(bruto, dict):
            continue
        marca = str(bruto.get("marca") or "").strip()
        modelo = str(bruto.get("modelo") or "").strip()
        if not modelo or normalize(f"{marca} {modelo}") in vistos:
            continue
        indice = _indice_valido(bruto.get("fonte"), achados)
        if indice is None:
            continue
        vistos.add(normalize(f"{marca} {modelo}"))
        saida.append(
            Opcao(
                valor=" ".join(p for p in (marca, modelo) if p),
                detalhe="",
                fontes=(achados[indice - 1].url,),
                tipo="modelo",
                marca=marca,
                modelo=modelo,
            )
        )
    return tuple(saida[:MAXIMO_DE_OPCOES])


def identificar(
    texto: str,
    *,
    catalogo: Sequence[sugestao.Linha] = (),
    ano: int | None = None,
    cliente=None,
    provedor_de_busca: str = "",
    so_catalogo: bool = False,
) -> Identificacao:
    """Identifica o veículo, perguntando quando não der para saber.

    Gasta, no máximo, **três** buscas e **uma** chamada de modelo pequeno — e nenhuma das
    duas quando o catálogo já responde. `ano` sobrepõe o que estiver no texto.
    """
    texto = (texto or "").strip()
    if not texto:
        return Identificacao(texto=texto, motivo="nada foi digitado", origem="nenhuma")

    sem_ano, ano_do_texto = sugestao.separar_ano(texto)
    ano_pedido = ano or ano_do_texto

    do_catalogo = _do_catalogo(texto, catalogo)
    if do_catalogo is not None:
        return do_catalogo

    if so_catalogo:
        return Identificacao(
            texto=texto,
            estado=NAO_ENTENDI,
            origem="catalogo",
            ano=ano_pedido,
            ano_origem=ANO_DO_PEDIDO if ano_pedido else "",
            motivo=("não achei no catálogo e a pesquisa externa está desligada neste ambiente"),
        )

    do_pedido = _do_pedido_explicito(sem_ano or texto, ano_pedido)
    if do_pedido is not None:
        # Conserva o texto verbatim na trilha mesmo quando `separar_ano` tirou o ano.
        return Identificacao(**{**vars(do_pedido), "texto": texto})

    from pipeline import llm

    if llm.modo_fake() or not llm.tem_chave():
        return Identificacao(
            texto=texto,
            estado=NAO_ENTENDI,
            origem="nenhuma",
            ano=ano_pedido,
            ano_origem=ANO_DO_PEDIDO if ano_pedido else "",
            motivo=(
                "não achei no catálogo, e não há modelo configurado para procurar as "
                "versões. Escreva marca, modelo e versão completos."
            ),
        )

    achados, consultas, falha = _buscar(
        sem_ano or texto, ano=ano_pedido, provedor=provedor_de_busca
    )
    if not achados:
        return Identificacao(
            texto=texto,
            estado=NAO_ENTENDI,
            origem="busca",
            ano=ano_pedido,
            ano_origem=ANO_DO_PEDIDO if ano_pedido else "",
            consultas=tuple(consultas),
            motivo=falha or "a busca não devolveu nenhum resultado para este texto",
        )

    with llm.medindo() as medida:
        resposta = llm.extrair_json(
            prompt=_prompt(texto, achados, ano=ano_pedido),
            campos=["marca", "modelo", "versao", "ano_modelo", "modelos", "versoes", "pergunta"],
            sistema=_SISTEMA,
            max_tokens=TETO_DE_SAIDA,
            cliente=cliente,
        )

    fontes = tuple(dict.fromkeys(a.url for a in achados))
    comum: dict[str, Any] = {
        "texto": texto,
        "origem": "busca",
        "consultas": tuple(consultas),
        "fontes": fontes,
        "uso": medida.to_dict(),
    }
    if not resposta.ok:
        return Identificacao(
            **comum,
            estado=NAO_ENTENDI,
            ano=ano_pedido,
            ano_origem=ANO_DO_PEDIDO if ano_pedido else "",
            motivo=f"a busca respondeu, o modelo não: {resposta.motivo[:160]}",
        )

    dados = resposta.dados if isinstance(resposta.dados, dict) else {}
    marca = str(dados.get("marca") or "").strip()
    modelo = str(dados.get("modelo") or "").strip()
    versao = str(dados.get("versao") or "").strip()

    # O ano: o do pedido vence; senão o que as fontes mostram; senão o vigente, assumido.
    ano_das_fontes = _inteiro(dados.get("ano_modelo"))
    if ano_pedido:
        ano_final, ano_origem = ano_pedido, ANO_DO_PEDIDO
    elif ano_das_fontes:
        ano_final, ano_origem = ano_das_fontes, ANO_DAS_FONTES
    else:
        ano_final, ano_origem = ano_vigente(), ANO_VIGENTE
    comum.update({"ano": ano_final, "ano_origem": ano_origem})

    modelos = _modelos_de(dados, achados)
    if not modelo and len(modelos) >= 2:
        return Identificacao(
            **comum,
            estado=PRECISA_ESCOLHER,
            marca=marca,
            pergunta=str(dados.get("pergunta") or "").strip() or "De qual modelo você fala?",
            opcoes=modelos,
        )
    if not modelo and len(modelos) == 1:
        marca, modelo = modelos[0].marca or marca, modelos[0].modelo

    opcoes = _opcoes_de(dados, achados, marca=marca, modelo=modelo)
    comum.update({"marca": marca, "modelo": modelo})

    if versao and modelo:
        return Identificacao(**comum, estado=RESOLVIDO, versao=versao, opcoes=opcoes)
    if opcoes:
        return Identificacao(
            **comum,
            estado=PRECISA_ESCOLHER,
            pergunta=str(dados.get("pergunta") or "").strip()
            or f"Qual versão d{'a' if modelo else 'o'} {modelo or texto} você quer?",
            opcoes=opcoes,
        )
    return Identificacao(
        **comum,
        estado=NAO_ENTENDI,
        motivo=(
            "a busca respondeu, mas nenhuma versão saiu dos resultados com fonte. "
            "Escreva marca, modelo e versão completos."
        ),
    )
