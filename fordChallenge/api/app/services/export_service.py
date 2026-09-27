"""Do banco para a tabela de exportação — a ponte entre a matriz e o arquivo.

**Por que existe uma ponte, e não uma conversão do `to_dict` da matriz.** A matriz é uma
visão de tela: símbolo, cor, truncagem, e a evidência reduzida a um `evidence_id` porque a
gaveta busca o resto quando alguém clica. O arquivo não tem gaveta. Tudo que a pessoa
precisaria clicar para ver tem de estar **na linha** — a URL, a data da captura e o trecho
verbatim.

A ponte também é onde a etiqueta é decidida, e ela sai do `status` e da `origem` do campo,
nunca de uma regra própria: duas fontes de verdade para a mesma etiqueta é como a tela
acabou dizendo FATO para um campo vazio em 12/09.
"""

from __future__ import annotations

import datetime as dt

from api.app.errors import ProblemaHTTP
from api.app.models import Brand, VehicleModel, Version
from api.app.services import spec_assembler
from pipeline import comparables, parity
from pipeline.export import tabela as tab


#: `status` + `origem` -> a etiqueta que a tela mostra. Uma fonte de verdade só.
#:
#: `CATÁLOGO` existe porque chamar esses campos de INFERÊNCIA mentiria sobre o método
#: (nada foi inferido) e de FATO mentiria sobre a prova (não há trecho verbatim). A outra
#: procedência foi **nomeada** em vez de disfarçada — ver `api/app/services/spec_assembler`.
def etiqueta_de(campo) -> str:
    if campo is None or campo.value is None or campo.value == "":
        return "SEM DADO"
    if getattr(campo, "origem", None) == "catalogo":
        return "CATÁLOGO"
    if campo.evidences:
        return "FATO"
    return "INFERÊNCIA"


def _rotulo(sessao, version: Version) -> str:
    modelo = sessao.get(VehicleModel, version.model_id)
    marca = sessao.get(Brand, modelo.brand_id) if modelo else None
    partes = [p for p in (marca.nome if marca else "", modelo.nome if modelo else "") if p]
    return " ".join([*partes, version.nome_exato]).strip()


def _versao(sessao, version_id: str) -> Version:
    linha = sessao.get(Version, version_id)
    if linha is None:
        raise ProblemaHTTP(404, f"Versão {version_id!r} não existe.")
    return linha


def _campo_da_spec(spec, campo: str):
    """O campo pelo caminho canônico, ou `None`. A matriz usa o nome curto; a spec, o caminho."""
    from pipeline.schema import caminho_canonico

    caminho = caminho_canonico(campo)
    if not caminho:
        return None
    try:
        return spec.get(caminho)
    except (KeyError, ValueError, AttributeError):
        return None


def _celula(campo_da_spec, *, situacao: str = "") -> tab.Celula:
    """Uma célula com **tudo** que a gaveta da tela mostraria: valor, fonte, data, trecho."""
    if campo_da_spec is None:
        return tab.Celula(status="nao_encontrado", situacao=situacao, etiqueta="SEM DADO")

    evidencia = campo_da_spec.evidences[0] if campo_da_spec.evidences else None
    status = campo_da_spec.status
    return tab.Celula(
        valor=campo_da_spec.value,
        unidade=campo_da_spec.unit or "",
        status=getattr(status, "value", str(status)),
        situacao=situacao,
        fonte_url=evidencia.source_url if evidencia else "",
        # A data da **captura**, e não a de hoje: uma página lida em março não vira dado
        # de setembro por ter sido exportada em setembro.
        fonte_data=(evidencia.captured_at or "")[:10] if evidencia else "",
        trecho=evidencia.quote if evidencia else "",
        etiqueta=etiqueta_de(campo_da_spec),
    )


def montar_tabela(
    sessao,
    *,
    ford_version_id: str,
    competitor_ids: list[str],
    grupos: list[str] | None = None,
    gerada_em: str | None = None,
) -> tab.Tabela:
    """A tabela de exportação de um benchmark: referência primeiro, concorrentes depois."""
    if not competitor_ids:
        raise ProblemaHTTP(422, "Informe ao menos um concorrente.")

    referencia = _versao(sessao, ford_version_id)
    if referencia.id in competitor_ids:
        raise ProblemaHTTP(422, "A versão de referência não pode estar entre os concorrentes.")

    spec_ref = spec_assembler.montar(sessao, referencia.id)
    rotulo_ref = _rotulo(sessao, referencia)
    atributos_ref = comparables.atributos_de_spec(spec_ref, versao=referencia.nome_exato)

    colunas = [tab.Coluna(version_id=referencia.id, rotulo=rotulo_ref, e_referencia=True)]
    ressalvas: list[str] = []
    colunas_de_paridade = []

    for version_id in competitor_ids:
        concorrente = _versao(sessao, version_id)
        spec_conc = spec_assembler.montar(sessao, concorrente.id)
        rotulo = _rotulo(sessao, concorrente)
        coluna = parity.montar_coluna(
            spec_ref,
            spec_conc,
            version_id=concorrente.id,
            rotulo=rotulo,
            grupos=grupos,
        )
        comp = comparables.avaliar(
            atributos_ref,
            comparables.atributos_de_spec(spec_conc, versao=concorrente.nome_exato),
        )
        colunas.append(
            tab.Coluna(
                version_id=concorrente.id,
                rotulo=rotulo,
                comparabilidade=comp.resumo,
                aviso=comp.aviso,
            )
        )
        if comp.aviso:
            ressalvas.append(f"{rotulo}: {comp.aviso}")
        colunas_de_paridade.append((spec_conc, coluna))

    # Os campos, na ordem da primeira coluna de paridade — a mesma ordem da tela.
    primeira = colunas_de_paridade[0][1]
    linhas: list[tab.Linha] = []
    for indice, celula_ref in enumerate(primeira.celulas):
        campo = celula_ref.campo
        celulas = [_celula(_campo_da_spec(spec_ref, campo))]
        for spec_conc, coluna in colunas_de_paridade:
            celula = coluna.celulas[indice] if indice < len(coluna.celulas) else None
            situacao = tab.SITUACAO_POR_ESTADO.get(
                getattr(celula.estado, "value", str(celula.estado)) if celula else "",
                "",
            )
            celulas.append(_celula(_campo_da_spec(spec_conc, campo), situacao=situacao))
        linhas.append(
            tab.Linha(
                campo=campo,
                grupo=celula_ref.grupo,
                rotulo=campo.replace("_", " "),
                celulas=tuple(celulas),
            )
        )

    sem_nenhum_valor = sum(1 for linha in linhas if not any(c.tem_valor for c in linha.celulas))
    if sem_nenhum_valor:
        ressalvas.append(
            f"{sem_nenhum_valor} de {len(linhas)} campos não têm valor em nenhum dos "
            "veículos comparados. Eles aparecem com o motivo escrito, não em branco."
        )

    return tab.Tabela(
        titulo=f"Benchmark — {rotulo_ref}",
        gerada_em=(gerada_em or dt.datetime.now(dt.UTC).isoformat(timespec="seconds")),
        colunas=colunas,
        linhas=linhas,
        ressalvas=ressalvas,
        versao_dos_criterios=comparables.carregar().versao,
    )
