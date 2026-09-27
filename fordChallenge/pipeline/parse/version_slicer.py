"""Recorte da versão alvo em documento multi-versão.

O problema, concreto: a ficha técnica MY26 da Toyota tem **uma** tabela com **seis**
versões em colunas. A linha de pneus é

    | Pneus | 265/65 R17 |  |  | 265/60 R18 |  |  |

Seis colunas de versão, dois valores. Qual medida é da SRX Plus AT? Chutar seria a
inferência proibida do projeto — "nada inferido de outra versão".

A resposta está na **geometria da tabela**, não em heurística de texto: uma célula
mesclada aparece com o valor na primeira coluna do seu alcance e vazia nas seguintes.
Então o alcance se reconstrói caminhando da esquerda para a direita:

    Pneus:  STD MT · STD AT · SR AT  → "265/65 R17"
            SRV AT · SRX AT · SRX Plus AT → "265/60 R18"

Confere com o gabarito, que registra `265/60 R18` para a SRX Plus AT — e a mesma regra
acerta `Liga leve 18"`, `50,9 / 2.800` e a suspensão traseira com barra estabilizadora.

Quando a grade **não** está disponível (motor `pypdf`, que não expõe geometria), o
recorte devolve `grade_disponivel=False` e nenhuma célula. Preferir "não sei" a atribuir
a coluna errada é a decisão de produto aqui, não uma limitação escondida.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.connectors.base import normalizar_versao
from pipeline.ontology import normalize
from pipeline.parse.pdf import DocumentoPdf, Tabela


@dataclass(frozen=True)
class Celula:
    """Um valor da tabela, com o alcance de colunas que ele cobre."""

    rotulo: str
    valor: str
    coluna: int
    """Coluna onde o valor começa (1 = primeira versão)."""
    alcance: tuple[int, ...]
    """Todas as colunas de versão cobertas por esta célula."""
    versoes_cobertas: tuple[str, ...]
    pagina: int = 0
    linha: int = 0

    @property
    def compartilhado(self) -> bool:
        """O valor vale para mais de uma versão."""
        return len(self.alcance) > 1


@dataclass
class RecorteDeVersao:
    """O que sobrou da tabela depois de ficar só com a coluna da versão alvo."""

    versao: str
    coluna: int | None = None
    versoes_da_tabela: tuple[str, ...] = ()
    celulas: list[Celula] = field(default_factory=list)
    texto: str = ""
    avisos: list[str] = field(default_factory=list)
    grade_disponivel: bool = True

    @property
    def encontrou_a_versao(self) -> bool:
        return self.coluna is not None

    #: Valores que só marcam presença numa tabela de equipamentos, não informam nada.
    MARCADORES = frozenset({"•", "-", "–", "—", "x", "X", "✓", "*"})

    def valor(self, rotulo: str) -> str | None:
        """Valor da linha cujo rótulo casa com `rotulo`, preferindo o informativo.

        O mesmo rótulo aparece em mais de uma tabela: "Tração" é seção da ficha de
        especificação (valor "4×2, 4×4 e 4×4 reduzida com acionamento eletrônico...") **e**
        linha da tabela de equipamentos (valor "•", só marcando que a versão tem). Pegar o
        primeiro que casava devolvia o bullet, e o campo virava `nao_encontrado` com o
        dado disponível ao lado. Marcador é descartado, e entre os informativos ganha o
        mais longo, que é o que descreve.
        """
        alvo = _chave(rotulo)
        exatos = [c for c in self.celulas if _chave(c.rotulo) == alvo]
        parciais = [c for c in self.celulas if alvo and alvo in _chave(c.rotulo)]
        for grupo in (exatos, parciais):
            informativos = [
                c for c in grupo if c.valor.strip() not in self.MARCADORES and c.valor.strip()
            ]
            if informativos:
                return max(informativos, key=lambda c: len(c.valor)).valor
            if grupo:
                return grupo[0].valor
        return None

    def to_dict(self) -> dict:
        return {
            "versao": self.versao,
            "coluna": self.coluna,
            "versoes_da_tabela": list(self.versoes_da_tabela),
            "grade_disponivel": self.grade_disponivel,
            "avisos": self.avisos,
            "celulas": [
                {
                    "rotulo": c.rotulo,
                    "valor": c.valor,
                    "coluna": c.coluna,
                    "alcance": list(c.alcance),
                    "versoes_cobertas": list(c.versoes_cobertas),
                    "compartilhado": c.compartilhado,
                    "pagina": c.pagina,
                    "linha": c.linha,
                }
                for c in self.celulas
            ],
        }


def _chave(texto: str) -> str:
    """Rótulo normalizado, sem a unidade entre parênteses."""
    sem_unidade = re.sub(r"\([^)]*\)", " ", str(texto))
    return normalizar_versao(sem_unidade)


def _limpa(valor: object) -> str:
    return re.sub(r"\s+", " ", "" if valor is None else str(valor)).strip()


def _identidade_de_coluna(texto: str) -> tuple[frozenset[str], dict[str, set[str]]]:
    """Separa o acabamento dos qualificadores sem usar uma lista fechada de versões.

    ``Limited`` e ``XLT`` continuam distintos mesmo com o mesmo motor. Ano, câmbio
    e carroceria podem faltar no cabeçalho curto; quando presentes nos dois nomes,
    precisam concordar. Modificadores como Plus, Kit Opcional e HPE-S permanecem
    no acabamento e nunca são descartados por similaridade.
    """
    texto = texto.replace("+", " plus ")
    normal = normalize(texto)
    qualifiers = {
        "motor": {
            value.replace(",", ".")
            for value in re.findall(r"(?<!\d)(\d[.,]\d)(?:[lL])?(?!\d)", texto)
        },
        "cilindros": set(re.findall(r"\b[vil](?:[3468]|12)\b", normal)),
        "ano": set(re.findall(r"\b(?:19|20)\d{2}\b", normal)),
    }
    groups = {
        "cambio": {
            "at": r"\b(?:at|aut|automatic[ao])\b",
            "mt": r"\b(?:mt|manual)\b",
        },
        "tracao": {"4x4": r"\b(?:4x4|4wd|awd)\b", "4x2": r"\b(?:4x2|2wd)\b"},
        "combustivel": {
            "diesel": r"\b(?:diesel|turbodiesel|tdi)\b",
            "gasolina": r"\bgasolina\b",
            "flex": r"\bflex\b",
        },
        "carroceria": {
            "dupla": r"\b(?:cd|cabine dupla)\b",
            "simples": r"\b(?:cs|cabine simples)\b",
            "chassi": r"\b(?:ch|chassi)\b",
        },
    }
    for group, values in groups.items():
        qualifiers[group] = {
            value for value, pattern in values.items() if re.search(pattern, normal)
        }

    residual = normalizar_versao(texto)
    residual = re.sub(r"\b(?:ano modelo|my)\s*(?=(?:19|20)\d{2}\b)", " ", residual)
    residual = re.sub(r"\b(?:19|20)\d{2}\b", " ", residual)
    residual = re.sub(r"(?<!\d)\d[.,]\d\s*l?\b", " ", residual)
    residual = re.sub(r"\b[vil](?:[3468]|12)\b", " ", residual)
    residual = re.sub(r"\bbi\s+turbo\b", " ", residual)
    residual = re.sub(r"\bcabine\s+(?:dupla|simples)\b", " ", residual)
    residual = re.sub(
        r"\b(?:diesel|turbodiesel|tdi|gasolina|flex|turbo|biturbo|tb|aut|cd|cs|ch|chassi)\b",
        " ",
        residual,
    )
    return frozenset(residual.split()), qualifiers


def coluna_da_versao(cabecalho: list[str], versao: str) -> int | None:
    """Índice (1-based entre as versões) da coluna cujo cabeçalho casa com `versao`.

    O acabamento precisa ser idêntico. Cabeçalhos podem abreviar motor/ano/câmbio,
    mas qualificadores explícitos contraditórios vetam o casamento. Empate devolve
    ``None``; cobertura de palavras mecânicas nunca vence um acabamento diferente.
    """
    acabamento, qualificadores = _identidade_de_coluna(versao)
    if not acabamento:
        return None
    candidatos: list[int] = []
    for indice, nome in enumerate(cabecalho[1:], start=1):
        identidade, observados = _identidade_de_coluna(_limpa(nome))
        if identidade != acabamento:
            continue
        if any(
            esperado and observados[chave] and esperado != observados[chave]
            for chave, esperado in qualificadores.items()
        ):
            continue
        candidatos.append(indice)
    return candidatos[0] if len(candidatos) == 1 else None


def _rotulo_efetivo(linhas: list[list[str]], i: int) -> str:
    """Rótulo da linha; vazio herda o da linha anterior não vazia (cabeçalho de seção)."""
    for j in range(i, -1, -1):
        rotulo = _limpa(linhas[j][0] if linhas[j] else "")
        if rotulo:
            return rotulo
    return ""


def celulas_da_linha(
    linha: list[str],
    versoes: list[str],
    *,
    rotulo: str,
    pagina: int,
    indice: int,
    spans: dict[str, int] | None = None,
) -> list[Celula]:
    """Reconstrói o alcance de cada célula de uma linha de valores.

    Regra única: um valor não vazio abre um alcance que segue pelas colunas vazias à sua
    direita, até o próximo valor. É como a grade do PDF representa célula mesclada.
    """
    valores = [_limpa(c) for c in linha[1 : len(versoes) + 1]]
    valores += [""] * (len(versoes) - len(valores))

    celulas: list[Celula] = []
    for posicao, valor in enumerate(valores, start=1):
        if valor:
            width = max(1, int((spans or {}).get(f"{indice}:{posicao}", 1)))
            end = min(posicao + width, len(versoes) + 1)
            # Mesmo uma geometria defeituosa não sobrescreve outra célula preenchida.
            if any(valores[c - 1] for c in range(posicao + 1, end)):
                end = posicao + 1
            celulas.append(
                _monta(valor, posicao, range(posicao, end), versoes, rotulo, pagina, indice)
            )
    return celulas


def _monta(
    valor: str,
    inicio: int,
    alcance: range,
    versoes: list[str],
    rotulo: str,
    pagina: int,
    linha: int,
) -> Celula:
    colunas = tuple(alcance)
    return Celula(
        rotulo=rotulo,
        valor=valor,
        coluna=inicio,
        alcance=colunas,
        versoes_cobertas=tuple(versoes[c - 1] for c in colunas if 1 <= c <= len(versoes)),
        pagina=pagina,
        linha=linha,
    )


def recortar_tabela(tabela: Tabela, versao: str) -> RecorteDeVersao:
    """Recorta uma tabela multi-versão, ficando só com o que vale para `versao`."""
    recorte = RecorteDeVersao(versao=versao)
    i_cabecalho = tabela.linha_de_cabecalho()
    if i_cabecalho is None:
        recorte.avisos.append(
            "a tabela não tem linha de cabeçalho de versões (esperado 'VERSÃO ...'); "
            "sem cabeçalho não há como saber a que versão cada coluna pertence"
        )
        recorte.grade_disponivel = False
        return recorte

    cabecalho = tabela.linhas[i_cabecalho]
    versoes = [_limpa(c) for c in cabecalho[1:]]
    recorte.versoes_da_tabela = tuple(versoes)

    coluna = coluna_da_versao(cabecalho, versao)
    recorte.coluna = coluna
    if coluna is None:
        recorte.avisos.append(
            f'"{versao}" não corresponde a nenhuma coluna desta tabela '
            f"(colunas: {', '.join(versoes)})"
        )
        return recorte

    for i in range(i_cabecalho + 1, len(tabela.linhas)):
        linha = tabela.linhas[i]
        if not any(_limpa(c) for c in linha[1:]):
            continue
        rotulo = _rotulo_efetivo(tabela.linhas, i)
        for celula in celulas_da_linha(
            linha, versoes, rotulo=rotulo, pagina=tabela.pagina, indice=i, spans=tabela.spans
        ):
            if coluna in celula.alcance:
                recorte.celulas.append(celula)

    recorte.texto = "\n".join(
        f"{c.rotulo}: {c.valor}" if c.rotulo else c.valor for c in recorte.celulas
    )
    return recorte


def recortar(documento: DocumentoPdf, versao: str) -> RecorteDeVersao:
    """Recorta o documento inteiro, **agregando todas** as tabelas onde a versão aparece.

    Agregar, e não escolher a maior: a ficha MY26 da Toyota tem a especificação
    (potência, torque, pneus, capacidade de carga) numa página e os equipamentos
    (faróis, ADAS, conforto) em outra, com contagens de coluna diferentes. Ficar com a
    maior devolvia 35 itens de equipamento e **nenhuma** especificação — perdia em
    silêncio justamente os campos que o gabarito mede.

    Cada célula carrega a página e a linha de onde veio, então rótulo repetido em duas
    tabelas chega à reconciliação (WP-12) como duas evidências, não como sobrescrita.

    Sem grade (motor `pypdf`), devolve `grade_disponivel=False` com o texto contínuo
    intacto — o texto ainda serve para grounding, o que não dá é atribuir coluna.
    """
    if not documento.tabelas:
        return RecorteDeVersao(
            versao=versao,
            grade_disponivel=False,
            texto=documento.markdown,
            avisos=[
                f"o motor {documento.motor!r} não expõe a grade da tabela; "
                "sem geometria não há recorte por coluna. Instale o extra `pdf` "
                "(pdfplumber) ou `docling`."
            ],
        )

    agregado = RecorteDeVersao(versao=versao)
    versoes_vistas: list[str] = []
    colunas: list[int] = []
    for tabela in documento.tabelas:
        recorte = recortar_tabela(tabela, versao)
        for nome in recorte.versoes_da_tabela:
            if nome not in versoes_vistas:
                versoes_vistas.append(nome)
        if recorte.coluna is None:
            continue
        colunas.append(recorte.coluna)
        agregado.celulas.extend(recorte.celulas)

    agregado.versoes_da_tabela = tuple(versoes_vistas)
    agregado.coluna = colunas[0] if colunas else None
    if not colunas:
        agregado.avisos.append(
            f'"{versao}" não corresponde a nenhuma coluna das {len(documento.tabelas)} '
            f"tabelas do documento (colunas vistas: {', '.join(versoes_vistas)})"
        )
    agregado.celulas.sort(key=lambda c: (c.pagina, c.linha, c.coluna))
    agregado.texto = "\n".join(
        f"{c.rotulo}: {c.valor}" if c.rotulo else c.valor for c in agregado.celulas
    )
    return agregado


def versoes_do_documento(documento: DocumentoPdf) -> list[str]:
    """Todas as versões nomeadas em cabeçalhos de tabela do documento."""
    nomes: list[str] = []
    for tabela in documento.tabelas:
        i = tabela.linha_de_cabecalho()
        if i is None:
            continue
        for celula in tabela.linhas[i][1:]:
            nome = _limpa(celula)
            if nome and nome not in nomes:
                nomes.append(nome)
    return nomes
