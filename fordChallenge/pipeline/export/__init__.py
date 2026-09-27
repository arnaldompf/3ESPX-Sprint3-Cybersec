"""Exportação: a comparação sai da tela em formato que sobrevive a ela.

Quatro destinos, e cada um tem um leitor diferente:

* **CSV** — quem vai abrir e olhar. Separador `;` e BOM, porque o destino é Excel em
  português;
* **XLSX** — quem vai trabalhar em cima: cabeçalho congelado, largura de coluna, e uma aba
  separada para fontes e ressalvas;
* **Parquet + DDL do BigQuery** — quem vai **carregar na stack da Ford**. Formato longo,
  esquema fixo;
* **PDF** — quem vai levar impresso (`pipeline/report/`).

A regra que atravessa os quatro: **toda célula com valor carrega a fonte e a data**, e
célula sem valor carrega o motivo por extenso. Um número numa planilha, sem a URL e sem o
dia em que foi lido, é indistinguível de um número que alguém digitou.
"""

from pipeline.export.arquivos import (
    COLUNAS_DO_PARQUET,
    TIPOS_DO_BIGQUERY,
    FormatoIndisponivel,
    ddl_do_bigquery,
    linhas_longas,
    para_parquet,
    para_xlsx,
)
from pipeline.export.tabela import (
    SITUACAO_POR_ESTADO,
    VAZIO_POR_STATUS,
    Celula,
    Coluna,
    Linha,
    Tabela,
    para_csv,
)

__all__ = [
    "COLUNAS_DO_PARQUET",
    "SITUACAO_POR_ESTADO",
    "TIPOS_DO_BIGQUERY",
    "VAZIO_POR_STATUS",
    "Celula",
    "Coluna",
    "FormatoIndisponivel",
    "Linha",
    "Tabela",
    "ddl_do_bigquery",
    "linhas_longas",
    "para_csv",
    "para_parquet",
    "para_xlsx",
]
