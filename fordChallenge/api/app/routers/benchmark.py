"""Benchmark: de uma versão Ford ao conjunto de concorrentes que vale comparar.

**A rota existe só com `BENCHMARK_ENABLED`**, como o Pesquisador — e pela mesma razão:
uma capacidade nova entra atrás de interruptor até a apresentação passar, para que
desligá-la seja uma variável de ambiente e não um `git revert` às pressas.

**O que esta rota faz, e o que ela recusa a fazer.** Ela propõe; ninguém compara nada sem
um humano confirmar. A proposta traz, por concorrente, o `k/n` de critérios atendidos e o
aviso quando o par é incomparável — e quando o modelo não tem versão do **mesmo ano** no
catálogo, ela diz isso em vez de cair para outro ano em silêncio. Comparar a Ranger 2027
com uma Hilux 2024 produziria uma tabela correta e enganosa.

Três origens de informação convivem na resposta, e a tela precisa distingui-las:

* **mapa** — a lista escrita em `pipeline/benchmark/segments.yaml`, com data e autor;
* **catálogo** — a versão escolhida pela régua de `pipeline/comparables.py`;
* **pesquisa** — o que ainda não existe e precisa ser coletado pelo Pesquisador.

Apresentar as três com a mesma cara seria a mesma mentira de método que a etiqueta
FATO/INFERÊNCIA existe para impedir.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlmodel import select

from api.app.deps import SessaoDep, exige
from api.app.errors import ProblemaHTTP
from api.app.models import Brand, SpecValue, VehicleModel, Version
from api.app.permissions import Acao
from api.app.services import export_service, spec_assembler
from pipeline import comparables, export
from pipeline.benchmark import segments
from pipeline.export import pdf

router = APIRouter(tags=["benchmark"], dependencies=[Depends(exige(Acao.CONSULTAR_FICHAS))])


class CriterioOut(BaseModel):
    id: str
    rotulo: str
    estado: str
    # `Any` e não `str`: o valor que decidiu o critério pode ser número (faixa de preço)
    # ou lista (finalidade). O mesmo contrato de `api/app/routers/parity.py`.
    valor_ford: Any = None
    valor_concorrente: Any = None
    motivo: str = ""


class ComparabilidadeOut(BaseModel):
    """`k/n` e os nomes. Nunca porcentagem — ver `pipeline/comparables.py`."""

    comparavel: bool
    criterios_atendidos: int
    criterios_avaliaveis: int
    total_de_criterios: int
    resumo: str
    nao_atendidos: list[str] = []
    sem_dados: list[str] = []
    detalhes: list[CriterioOut] = []
    aviso: str = ""
    versao_dos_criterios: str = ""


class CandidatoOut(BaseModel):
    """Um concorrente proposto, e tudo que falta para ele entrar na comparação."""

    marca: str
    modelo: str
    rotulo_do_modelo: str
    categoria_diferente: bool = False
    motivo_da_categoria: str = ""
    no_catalogo: bool = False
    version_id: str | None = None
    rotulo: str | None = None
    ano_modelo: int | None = None
    comparabilidade: ComparabilidadeOut | None = None
    precisa_pesquisa: bool = False
    motivo_da_pesquisa: str = ""
    """Por que este concorrente ainda não pode entrar. Vazio quando já pode."""


class SegmentoOut(BaseModel):
    id: str
    rotulo: str
    descricao: str = ""
    origem: str
    """`mapa` (lista escrita, com data) ou `desconhecido` (cai para o Pesquisador).

    A tela **tem** de mostrar a diferença: uma lista escrita à mão e uma lista proposta
    por busca em fonte T3 não têm o mesmo peso."""


class FordOut(BaseModel):
    version_id: str
    marca: str
    modelo: str
    versao: str
    ano_modelo: int
    rotulo: str


class PropostaOut(BaseModel):
    """O conjunto comparável proposto. Ninguém compara nada antes de um humano confirmar."""

    ford: FordOut
    segmento: SegmentoOut
    versao_do_mapa: str = ""
    candidatos: list[CandidatoOut] = []
    prontos: int = 0
    """Quantos já têm versão no catálogo, no mesmo ano-modelo, e passam na régua."""
    a_pesquisar: int = 0
    consulta_de_descoberta: str | None = None
    """A busca a fazer quando o segmento é desconhecido. `null` quando o mapa respondeu."""
    aviso: str = ""


def _rotulo(sessao, version: Version) -> str:
    modelo = sessao.get(VehicleModel, version.model_id)
    marca = sessao.get(Brand, modelo.brand_id) if modelo else None
    partes = [p for p in (marca.nome if marca else "", modelo.nome if modelo else "") if p]
    return " ".join([*partes, version.nome_exato]).strip()


def _marca_e_modelo(sessao, version: Version) -> tuple[str, str]:
    modelo = sessao.get(VehicleModel, version.model_id)
    marca = sessao.get(Brand, modelo.brand_id) if modelo else None
    return (marca.nome if marca else ""), (modelo.nome if modelo else "")


def _comparabilidade_out(resultado) -> ComparabilidadeOut:
    dados = resultado.to_dict()
    return ComparabilidadeOut(
        **{k: v for k, v in dados.items() if k != "detalhes"},
        detalhes=[CriterioOut(**d) for d in dados["detalhes"]],
    )


def _versoes_do_modelo(sessao, marca: str, modelo: str, ano_modelo: int) -> list[Version]:
    """As versões daquele modelo **no mesmo ano-modelo e com ficha coletada**.

    Duas exclusões, e as duas nasceram de erro silencioso:

    * **outro ano-modelo, nunca.** Cair de ano faria a matriz sair impecável comparando a
      Ranger 2026 com uma Hilux 2024, e nenhuma célula estaria errada;
    * **versão sem célula, nunca.** Medido em 13/09/2026: o benchmark da Raptor escolheu a
      *Amarok V6 Comfortline* — zero células — em vez da *V6 Extreme*, que tem 116. As duas
      empataram em critérios atendidos (a maioria sai do denominador por falta de dado) e o
      desempate alfabético entregou a errada. O sintoma na tela era **"96 não sabemos"**:
      uma matriz impecável comparando contra uma coluna vazia.

    Existir no catálogo e ter ficha não são a mesma coisa, e para o benchmark só a segunda
    conta — o objetivo é comparar dado, não nome.
    """
    versoes = sessao.exec(
        select(Version)
        .join(VehicleModel, VehicleModel.id == Version.model_id)
        .join(Brand, Brand.id == VehicleModel.brand_id)
        .where(
            Brand.nome == marca,
            VehicleModel.nome == modelo,
            Version.ano_modelo == ano_modelo,
        )
    ).all()
    if not versoes:
        return []
    com_ficha = set(
        sessao.exec(
            select(SpecValue.version_id)
            .where(SpecValue.version_id.in_([v.id for v in versoes]))
            .distinct()
        ).all()
    )
    return [v for v in versoes if v.id in com_ficha]


def _existe_no_catalogo(sessao, marca: str, modelo: str, ano_modelo: int) -> bool:
    """O modelo existe naquele ano, mesmo sem ficha? Separa os dois motivos de recusa."""
    return (
        sessao.exec(
            select(Version.id)
            .join(VehicleModel, VehicleModel.id == Version.model_id)
            .join(Brand, Brand.id == VehicleModel.brand_id)
            .where(
                Brand.nome == marca,
                VehicleModel.nome == modelo,
                Version.ano_modelo == ano_modelo,
            )
            .limit(1)
        ).first()
        is not None
    )


def _melhor_versao(sessao, candidatas: list[Version], atributos_ford: dict):
    """A versão do concorrente que melhor casa com a Ford, pela régua de comparabilidade.

    Mais critérios atendidos primeiro; comparável antes de incomparável; empate resolvido
    pelo nome, para a ordem ser estável entre chamadas — lista que muda de ordem sozinha
    parece dado mudando.
    """
    avaliadas = []
    for versao in candidatas:
        spec = spec_assembler.montar(sessao, versao.id)
        resultado = comparables.avaliar(
            atributos_ford,
            comparables.atributos_de_spec(spec, versao=versao.nome_exato),
        )
        avaliadas.append((resultado, versao))
    avaliadas.sort(
        key=lambda par: (
            -par[0].criterios_atendidos,
            not par[0].comparavel,
            par[1].nome_exato,
        )
    )
    return avaliadas[0] if avaliadas else (None, None)


@router.get(
    "/benchmark/proposta",
    response_model=PropostaOut,
    summary="Propõe o conjunto de concorrentes de uma versão Ford",
)
def propor(
    sessao: SessaoDep,
    version_id: str = Query(..., description="A versão **Ford** que abre o benchmark"),
) -> PropostaOut:
    ford = sessao.get(Version, version_id)
    if ford is None:
        raise ProblemaHTTP(404, f"Versão {version_id!r} não existe.")

    marca_ford, modelo_ford = _marca_e_modelo(sessao, ford)
    if marca_ford.strip().lower() != "ford":
        # Não é limitação técnica: é o desenho. O benchmark é a visão da Ford sobre a
        # concorrência, e inverter os papéis produziria uma tabela com outro significado.
        raise ProblemaHTTP(
            422,
            f"O benchmark parte de uma versão Ford. {_rotulo(sessao, ford)} é de {marca_ford}.",
        )

    spec_ford = spec_assembler.montar(sessao, ford.id)
    atributos_ford = comparables.atributos_de_spec(spec_ford, versao=ford.nome_exato)
    mapa = segments.carregar()

    try:
        segmento = segments.segmento_de(modelo_ford, mapa=mapa)
    except segments.SegmentoDesconhecido:
        return PropostaOut(
            ford=FordOut(
                version_id=ford.id,
                marca=marca_ford,
                modelo=modelo_ford,
                versao=ford.nome_exato,
                ano_modelo=ford.ano_modelo,
                rotulo=_rotulo(sessao, ford),
            ),
            segmento=SegmentoOut(id="", rotulo="", origem="desconhecido"),
            versao_do_mapa=mapa.versao,
            consulta_de_descoberta=segments.consulta_de_descoberta(marca_ford, modelo_ford),
            aviso=(
                f"O segmento da {modelo_ford} não está no mapa escrito. A lista de "
                "concorrentes tem de vir de pesquisa, em fontes de imprensa "
                "especializada (tier 3), e ser confirmada por você antes de virar "
                "comparação."
            ),
        )

    candidatos: list[CandidatoOut] = []
    for concorrente in segments.concorrentes_de(modelo_ford, mapa=mapa):
        base = {
            "marca": concorrente.marca,
            "modelo": concorrente.modelo,
            "rotulo_do_modelo": concorrente.rotulo,
            "categoria_diferente": concorrente.categoria_diferente,
            "motivo_da_categoria": concorrente.motivo,
        }
        versoes = _versoes_do_modelo(sessao, concorrente.marca, concorrente.modelo, ford.ano_modelo)
        if not versoes:
            # Dois motivos diferentes, e a tela merece saber qual: "não temos o carro" e
            # "temos o carro e não coletamos a ficha" pedem ações diferentes de quem lê.
            existe = _existe_no_catalogo(
                sessao, concorrente.marca, concorrente.modelo, ford.ano_modelo
            )
            motivo = (
                f"{concorrente.rotulo} do ano-modelo {ford.ano_modelo} está no catálogo, "
                "mas nenhuma versão dele tem ficha coletada"
                if existe
                else f"nenhuma versão de {concorrente.rotulo} no ano-modelo "
                f"{ford.ano_modelo} está no catálogo"
            )
            candidatos.append(
                CandidatoOut(**base, precisa_pesquisa=True, motivo_da_pesquisa=motivo)
            )
            continue

        resultado, escolhida = _melhor_versao(sessao, versoes, atributos_ford)
        candidatos.append(
            CandidatoOut(
                **base,
                no_catalogo=True,
                version_id=escolhida.id,
                rotulo=_rotulo(sessao, escolhida),
                ano_modelo=escolhida.ano_modelo,
                comparabilidade=_comparabilidade_out(resultado),
            )
        )

    prontos = sum(1 for c in candidatos if c.no_catalogo)
    a_pesquisar = sum(1 for c in candidatos if c.precisa_pesquisa)
    incomparaveis = [
        c.rotulo_do_modelo
        for c in candidatos
        if c.comparabilidade and not c.comparabilidade.comparavel
    ]

    avisos = []
    if a_pesquisar:
        avisos.append(
            f"{a_pesquisar} de {len(candidatos)} concorrentes não têm versão no "
            f"ano-modelo {ford.ano_modelo} no catálogo e precisam ser coletados."
        )
    if incomparaveis:
        avisos.append(
            "Pares que a régua reprova, e que só entram se você decidir: "
            + ", ".join(incomparaveis)
            + "."
        )

    return PropostaOut(
        ford=FordOut(
            version_id=ford.id,
            marca=marca_ford,
            modelo=modelo_ford,
            versao=ford.nome_exato,
            ano_modelo=ford.ano_modelo,
            rotulo=_rotulo(sessao, ford),
        ),
        segmento=SegmentoOut(
            id=segmento.id,
            rotulo=segmento.rotulo,
            descricao=segmento.descricao,
            origem="mapa",
        ),
        versao_do_mapa=mapa.versao,
        candidatos=candidatos,
        prontos=prontos,
        a_pesquisar=a_pesquisar,
        aviso=" ".join(avisos),
    )


# --------------------------------------------------------------------------------------
# Exportação
# --------------------------------------------------------------------------------------
#: Onde os arquivos exportados ficam. Mesma convenção de `pipeline/report/render.py`.
DIRETORIO_DE_EXPORTACAO = Path("data/exports")

#: O nome de arquivo aceito na rota de download. Padrão fechado, e `resolve()` depois —
#: a rota lê caminho vindo da URL, e `../../.env` é o primeiro teste que alguém faz.
NOME_DE_ARQUIVO = re.compile(r"^[A-Za-z0-9._-]{1,120}\.(csv|xlsx|parquet|sql|md|pdf|html)$")
PASTA = re.compile(r"^[a-f0-9]{8,32}$")

#: Os formatos que a rota sabe servir, e o tipo com que cada um desce.
TIPOS: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "parquet": "application/vnd.apache.parquet",
    "sql": "application/sql",
    "md": "text/markdown; charset=utf-8",
    "pdf": "application/pdf",
    "html": "text/html; charset=utf-8",
}


class ArquivoOut(BaseModel):
    nome: str
    formato: str
    bytes: int
    url: str


class RecusadoOut(BaseModel):
    """Um formato que não saiu, **e por quê**. Nunca um arquivo de zero byte."""

    formato: str
    motivo: str


class ExportacaoOut(BaseModel):
    pasta: str
    titulo: str
    gerada_em: str
    campos: int
    campos_com_valor: int
    """O denominador honesto: quantos dos campos têm valor em pelo menos um veículo."""
    arquivos: list[ArquivoOut] = []
    recusados: list[RecusadoOut] = []
    ressalvas: list[str] = []
    carregamento_no_bigquery: str = ""
    """O que fazer com o Parquet e o DDL. **A ferramenta não carrega sozinha** — ver
    `docs/data_contract.md` §9."""


class ExportacaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ford_version: str
    competitors: list[str]
    grupos: list[str] | None = None


def _leia_me(tabela, ddl: str) -> str:
    ressalvas = "\n".join(f"- {r}" for r in tabela.ressalvas) or "- nenhuma"
    comandos = (
        "bq mk --dataset --location=southamerica-east1 SEU_PROJETO:specradar\n"
        "bq query --use_legacy_sql=false < bigquery.sql\n"
        "bq load --source_format=PARQUET "
        "SEU_PROJETO:specradar.matriz_de_paridade matriz.parquet"
    )
    return "\n".join(
        [
            f"# {tabela.titulo}",
            "",
            f"Gerado em {tabela.gerada_em} pelo SpecRadar.",
            "",
            "## O que está nesta pasta",
            "",
            "| arquivo | para quem |",
            "|---|---|",
            "| matriz.csv | quem vai abrir e olhar (`;` e BOM, para Excel em português) |",
            "| matriz.xlsx | quem vai trabalhar em cima |",
            "| matriz.parquet | a ingestão — formato longo, esquema fixo |",
            "| bigquery.sql | o CREATE TABLE correspondente |",
            "",
            "O contrato de cada coluna está em `docs/data_contract.md`.",
            "",
            "## Ressalvas desta exportação",
            "",
            ressalvas,
            "",
            "## Para carregar no BigQuery",
            "",
            "```bash",
            comandos,
            "```",
            "",
            "**O SpecRadar não executa esse carregamento sozinho, mesmo com credencial "
            "presente no ambiente.** Enviar dado para fora do ambiente onde ele foi "
            "produzido é decisão de quem responde pelo dado, não do processo que o gerou "
            "— e uma credencial num arquivo de ambiente diz que *é possível*, não que "
            "*está autorizado*. Confirme projeto, dataset e região antes de rodar.",
            "",
            "```sql",
            ddl.rstrip("\n"),
            "```",
            "",
        ]
    )


@router.post(
    "/benchmark/export",
    response_model=ExportacaoOut,
    summary="Gera os arquivos do benchmark (CSV, XLSX, Parquet e o DDL do BigQuery)",
)
def exportar(sessao: SessaoDep, pedido: ExportacaoIn) -> ExportacaoOut:
    """Escreve os arquivos e devolve o que saiu — **e o que não saiu, com o motivo**.

    Formato que falha por falta de biblioteca vira `recusados`, nunca um arquivo de zero
    byte: planilha vazia só se descobre quebrada na frente de outra pessoa.
    """
    tabela = export_service.montar_tabela(
        sessao,
        ford_version_id=pedido.ford_version,
        competitor_ids=pedido.competitors,
        grupos=pedido.grupos,
    )

    # A pasta sai do conteúdo, e não do relógio: exportar duas vezes a mesma comparação no
    # mesmo dia devolve a mesma pasta, em vez de encher o disco com cópias idênticas.
    chave = "|".join([pedido.ford_version, *sorted(pedido.competitors), tabela.gerada_em[:10]])
    pasta_nome = hashlib.sha256(chave.encode("utf-8")).hexdigest()[:16]
    pasta = DIRETORIO_DE_EXPORTACAO / pasta_nome
    pasta.mkdir(parents=True, exist_ok=True)

    arquivos: list[ArquivoOut] = []
    recusados: list[RecusadoOut] = []

    def registrar(caminho: Path, formato: str) -> None:
        arquivos.append(
            ArquivoOut(
                nome=caminho.name,
                formato=formato,
                bytes=caminho.stat().st_size,
                url=f"/api/v1/benchmark/export/{pasta_nome}/{caminho.name}",
            )
        )

    csv_path = pasta / "matriz.csv"
    csv_path.write_text(export.para_csv(tabela), encoding="utf-8")
    registrar(csv_path, "csv")

    ddl = export.ddl_do_bigquery()
    sql_path = pasta / "bigquery.sql"
    sql_path.write_text(ddl, encoding="utf-8")
    registrar(sql_path, "sql")

    leia_me = pasta / "LEIA-ME.md"
    leia_me.write_text(_leia_me(tabela, ddl), encoding="utf-8")
    registrar(leia_me, "md")

    for formato, escrever, nome in (
        ("xlsx", export.para_xlsx, "matriz.xlsx"),
        ("parquet", export.para_parquet, "matriz.parquet"),
    ):
        try:
            registrar(escrever(tabela, pasta / nome), formato)
        except export.FormatoIndisponivel as exc:
            recusados.append(RecusadoOut(formato=formato, motivo=str(exc)))

    # O PDF desce um degrau sozinho: sem motor, sai HTML **com o motivo dentro** em vez de
    # um `.pdf` truncado, que alguém abriria na frente do cliente.
    documento = pdf.gerar(tabela, nome="benchmark", diretorio=pasta)
    registrar(documento.caminho, documento.formato)
    if documento.motivo:
        recusados.append(RecusadoOut(formato="pdf", motivo=documento.motivo))

    return ExportacaoOut(
        pasta=pasta_nome,
        titulo=tabela.titulo,
        gerada_em=tabela.gerada_em,
        campos=len(tabela.linhas),
        campos_com_valor=tabela.campos_com_valor,
        arquivos=arquivos,
        recusados=recusados,
        ressalvas=tabela.ressalvas,
        carregamento_no_bigquery=(
            "O Parquet e o DDL estão prontos. O carregamento é feito por uma pessoa, com "
            "o projeto e o dataset confirmados — o SpecRadar não envia dado para fora do "
            "ambiente onde ele foi produzido. Os comandos estão no LEIA-ME.md."
        ),
    )


@router.get(
    "/benchmark/export/{pasta}/{arquivo}",
    summary="Baixa um arquivo gerado pela exportação",
)
def baixar(pasta: str, arquivo: str) -> FileResponse:
    """Serve o arquivo do diretório de exportação, **e só de lá**."""
    if not PASTA.match(pasta) or not NOME_DE_ARQUIVO.match(arquivo):
        raise ProblemaHTTP(422, "Nome de pasta ou de arquivo inválido.")
    caminho = DIRETORIO_DE_EXPORTACAO / pasta / arquivo
    # `resolve()` nos dois lados: os padrões já barram `..`, e esta é a segunda linha de
    # defesa — a que continua valendo se algum dia alguém afrouxar o padrão.
    if not caminho.resolve().is_relative_to(DIRETORIO_DE_EXPORTACAO.resolve()):
        raise ProblemaHTTP(422, "Caminho fora do diretório de exportação.")
    if not caminho.exists():
        raise ProblemaHTTP(404, f"Arquivo {arquivo!r} não existe nesta exportação.")
    return FileResponse(
        path=str(caminho),
        media_type=TIPOS.get(caminho.suffix.lstrip("."), "application/octet-stream"),
        filename=caminho.name,
    )
