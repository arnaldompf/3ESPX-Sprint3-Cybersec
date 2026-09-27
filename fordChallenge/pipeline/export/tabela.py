"""A tabela de exportação: **uma linha por campo, uma coluna por veículo**.

É a forma que a planilha, o Parquet e o PDF compartilham. Existe como estrutura própria,
e não como "o que o `to_dict` da matriz devolve", por uma razão que já custou caro neste
projeto: a matriz é uma visão de **tela** (símbolos, cores, truncagem), e uma exportação é
um **arquivo que sobrevive à tela**. Quem abre o CSV daqui a seis meses não tem a legenda
ao lado, e por isso aqui não há símbolo — há a palavra.

**Toda célula com valor carrega a fonte e a data.** Não é zelo: um número numa planilha,
sem a URL e sem o dia em que foi lido, é indistinguível de um número que alguém digitou.
A promessa inteira do produto é essa distinção, e ela não pode terminar na borda do
navegador.

**Célula sem valor não fica em branco.** Fica com o estado escrito — `não encontrado`,
`não disponível`, `não verificado` —, porque em planilha a célula vazia é lida como zero,
como "não se aplica" ou como erro de exportação, e as três leituras são falsas.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

#: Como cada estado da matriz se chama por extenso num arquivo.
#:
#: Na tela há símbolo e cor; num CSV aberto seis meses depois não há legenda ao lado. O
#: dicionário é a tradução, e `desconhecido` vira "não sabemos" — a mesma palavra da tela,
#: para que ninguém precise aprender dois vocabulários para o mesmo dado.
SITUACAO_POR_ESTADO: dict[str, str] = {
    "vantagem": "ganhamos",
    "paridade": "empate",
    "gap": "perdemos",
    "desconhecido": "não sabemos",
}

#: O que escrever numa célula sem valor. Nunca vazio.
VAZIO_POR_STATUS: dict[str, str] = {
    "nao_encontrado": "não encontrado em nenhuma fonte",
    "nao_disponivel": "a fonte oficial declara que não existe",
    "nao_verificado": "sem evidência que sustente o valor",
    "divergente": "as fontes divergem",
    "pendente_coleta": "ainda não coletado",
}

#: O texto de uma célula sem valor e sem status conhecido.
SEM_DADO = "sem dado"


@dataclass(frozen=True)
class Celula:
    """O valor de um campo para um veículo, com a proveniência junto."""

    valor: Any = None
    unidade: str = ""
    status: str = ""
    situacao: str = ""
    """`ganhamos` / `empate` / `perdemos` / `não sabemos`. Vazio na coluna da Ford, que é
    a referência — ela não ganha nem perde de si mesma."""
    fonte_url: str = ""
    fonte_data: str = ""
    """A data da **captura**, em ISO. Não a de hoje: uma página lida em março não vira
    dado de setembro por ter sido exportada em setembro."""
    trecho: str = ""
    """O trecho verbatim. Cortado em 300 caracteres, como na evidência."""
    etiqueta: str = ""
    """FATO / INFERÊNCIA / CATÁLOGO / SEM DADO — a mesma da tela."""

    @property
    def texto(self) -> str:
        """O que vai na célula da planilha. **Nunca vazio.**"""
        if self.valor is None or self.valor == "":
            return VAZIO_POR_STATUS.get(self.status, SEM_DADO)
        if isinstance(self.valor, list):
            corpo = ", ".join(str(v) for v in self.valor)
        elif isinstance(self.valor, bool):
            corpo = "sim" if self.valor else "não"
        else:
            corpo = str(self.valor)
        return f"{corpo} {self.unidade}".strip()

    @property
    def tem_valor(self) -> bool:
        return self.valor is not None and self.valor != ""


@dataclass(frozen=True)
class Coluna:
    """Um veículo da comparação."""

    version_id: str
    rotulo: str
    e_referencia: bool = False
    """A versão Ford que abre o benchmark. Vem sempre em primeiro."""
    comparabilidade: str = ""
    """`"4/6 critérios atendidos"`. Vazio na referência."""
    aviso: str = ""
    """O aviso de comparabilidade. Preenchido, **tem de aparecer** no arquivo."""


@dataclass(frozen=True)
class Linha:
    """Um campo da ficha, com a célula de cada veículo."""

    campo: str
    grupo: str
    rotulo: str
    celulas: tuple[Celula, ...] = ()


@dataclass
class Tabela:
    """A exportação inteira: colunas, linhas, e as ressalvas que viajam com ela."""

    titulo: str
    gerada_em: str
    colunas: list[Coluna] = field(default_factory=list)
    linhas: list[Linha] = field(default_factory=list)
    ressalvas: list[str] = field(default_factory=list)
    """Comparabilidade, dado faltante, bloqueio de fonte. Nunca omitidas do arquivo."""
    versao_dos_criterios: str = ""

    @property
    def campos_com_valor(self) -> int:
        """Quantos campos têm valor em **pelo menos** um veículo. O denominador honesto."""
        return sum(1 for linha in self.linhas if any(c.tem_valor for c in linha.celulas))

    def cabecalho(self) -> list[str]:
        """`campo, grupo, <veículo> …` com valor, situação, fonte e data por veículo."""
        colunas = ["campo", "grupo"]
        for coluna in self.colunas:
            nome = coluna.rotulo
            colunas += [nome, f"{nome} · situação", f"{nome} · fonte", f"{nome} · data"]
        return colunas

    def como_linhas(self) -> list[list[str]]:
        """As linhas da planilha, já como texto. Nenhuma célula sai vazia."""
        saida: list[list[str]] = []
        for linha in self.linhas:
            valores = [linha.rotulo or linha.campo, linha.grupo]
            for celula in linha.celulas:
                valores += [
                    celula.texto,
                    celula.situacao or "—",
                    celula.fonte_url or "—",
                    celula.fonte_data or "—",
                ]
            saida.append(valores)
        return saida


def para_csv(tabela: Tabela) -> str:
    """O CSV, com as ressalvas no rodapé.

    **O rodapé não é enfeite.** Um CSV é o formato que mais viaja: vira anexo de e-mail,
    vira aba de outra planilha, vira tabela num slide. Se a ressalva de comparabilidade
    ficar só na tela que o gerou, a primeira cópia já perde a informação que impede a
    leitura errada — e é a cópia que circula.

    `\\r\\n` e BOM porque o destino é Excel em português: sem o BOM, "não disponível" abre
    como "nÃ£o disponÃ­vel", e a planilha inteira parece corrompida.
    """
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    escritor.writerow([tabela.titulo])
    escritor.writerow([f"gerado em {tabela.gerada_em}"])
    if tabela.versao_dos_criterios:
        escritor.writerow([f"critérios de comparabilidade: versão {tabela.versao_dos_criterios}"])
    escritor.writerow([])
    escritor.writerow(tabela.cabecalho())
    for linha in tabela.como_linhas():
        escritor.writerow(linha)
    if tabela.ressalvas:
        escritor.writerow([])
        escritor.writerow(["ressalvas"])
        for ressalva in tabela.ressalvas:
            escritor.writerow([ressalva])
    return "﻿" + buffer.getvalue()
