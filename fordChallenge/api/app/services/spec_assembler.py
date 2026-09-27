"""`spec_values` do banco → `StandardSpec` da API.

A regra que dá nome ao módulo, e que é a mais fácil de violar sem perceber:

    **o filtro `attributes` esconde valores, nunca campos.**

`GET /vehicles/{id}/specs?attributes=potencia_cv` devolve a ficha **inteira**, com os 58
campos presentes; o que muda é que os não pedidos vêm sem valor, com `status` dizendo
`nao_verificado` e a nota explicando que não foram consultados. Omitir os campos seria
mais curto e mudaria o significado da resposta: quem lê um JSON sem `torque_nm` não sabe
se o torque **não existe**, se **não foi encontrado** ou se **ninguém perguntou** — e essa
é exatamente a confusão que o schema canônico existe para acabar.

Um campo `divergente` tem mais de uma linha em `spec_values` (a tabela não tem
`UNIQUE (version_id, field)` justamente por isso). A montagem junta essas linhas num
`SpecField` com `conflicts` preenchido, em vez de escolher uma — escolher em silêncio é o
que a regra proíbe.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlmodel import Session, select

from api.app.models import Brand, SpecValue, VehicleModel, Version
from api.app.models import Evidence as EvidenceRow
from pipeline.schema import (
    GRUPOS,
    UNIDADE_CANONICA,
    Evidence,
    SpecField,
    SpecMeta,
    StandardSpec,
    Status,
    empty_spec,
    grupo_de,
)

#: Nota dos campos que o filtro `attributes` deixou de fora.
NOTA_NAO_PEDIDO = "campo não solicitado nesta consulta (`attributes`)"

#: Os campos de identificação que o **catálogo** sabe responder, e como lê-los.
#:
#: `carroceria` fica de fora de propósito: não existe coluna para ela no catálogo, e
#: inventar uma seria exatamente o que o produto não faz.
DO_CATALOGO = {
    "marca": lambda marca, modelo, versao: marca.nome,
    "modelo": lambda marca, modelo, versao: modelo.nome,
    "versao": lambda marca, modelo, versao: versao.nome_exato,
    "ano_modelo": lambda marca, modelo, versao: versao.ano_modelo,
    "codigo_fipe": lambda marca, modelo, versao: versao.codigo_fipe,
    "segmento": lambda marca, modelo, versao: getattr(modelo, "segmento", None),
}

#: Por que este valor não tem trecho verbatim, dito de um jeito que o vendedor entende.
NOTA_CATALOGO = (
    "valor do catálogo: é a identidade da versão que você consultou, e está no nosso "
    "cadastro — não foi lido de uma página do fabricante"
)


def _evidencia_de(linha: EvidenceRow | None) -> Evidence | None:
    if linha is None:
        return None
    captura = linha.captured_at
    return Evidence(
        evidence_id=linha.id,
        source_url=linha.source_url,
        tier=linha.tier,
        quote=linha.quote,
        captured_at=captura.isoformat() if isinstance(captura, dt.datetime) else str(captura or ""),
        raw_value=linha.raw_value,
        snapshot_id=linha.snapshot_id,
        page=linha.page,
        tipo_de_afirmacao=linha.tipo_de_afirmacao,  # type: ignore[arg-type]
    )


def _campo_de(linhas: list[tuple[SpecValue, EvidenceRow | None]], nome: str) -> SpecField:
    """Aplica a política compartilhada às linhas legadas sem decisão materializada.
    Várias linhas não significam necessariamente conflito: autoridade e equivalência
    determinam o valor principal e as contestações preservadas."""
    from pipeline.publication import from_rows

    return from_rows(linhas, nome)


def _campo_nao_pedido(nome: str) -> SpecField:
    """Campo fora do filtro: presente, sem valor, e **dizendo** que não foi pedido.

    `nao_verificado` e não `nao_encontrado`: a diferença é que ninguém procurou, e trocar
    um pelo outro faria a resposta afirmar que a fonte foi consultada em vão.
    """
    return SpecField(
        value=None,
        unit=UNIDADE_CANONICA.get(nome),
        status=Status.NAO_VERIFICADO,
        confidence=0.0,
        notes=NOTA_NAO_PEDIDO,
    )


def campos_pedidos(attributes: str | list[str] | None) -> set[str] | None:
    """Normaliza o parâmetro `attributes`. `None` significa "a ficha toda".

    Aceita `?attributes=potencia_cv,torque_nm` e `?attributes=a&attributes=b`, porque as
    duas formas aparecem em cliente HTTP de verdade.
    """
    if attributes is None:
        return None
    if isinstance(attributes, str):
        brutos = attributes.split(",")
    else:
        brutos = [parte for item in attributes for parte in str(item).split(",")]
    nomes = {p.strip().split(".")[-1] for p in brutos if p.strip()}
    return nomes or None


def _preencher_identificacao(
    sessao: Session,
    version_id: str,
    spec: StandardSpec,
    pedidos: set[str] | None,
) -> None:
    """Marca, modelo, versão, ano-modelo e FIPE saem do **catálogo**, não das fontes.

    **O defeito que isto corrige** (achado por um avaliador em 12/09/2026): o cabeçalho da
    Ficha dizia "Ford Ranger Raptor 3.0 V6 Bi-turbo 4WD AT · ano-modelo 2026 · FIPE
    003506-8" — lendo `GET /vehicles/{id}` — e o bloco Identificação, cinco centímetros
    abaixo, dizia "não encontrado nas fontes" nos **mesmos cinco campos**. A ficha só lia
    `spec_values`, e o catálogo nunca chegava nela.

    "Não encontrado" ali era falso, e de um jeito que corrói a tela inteira: se o sistema
    diz que não encontrou o que ele mesmo está exibindo no topo, por que acreditar nele
    sobre o torque?

    **Três regras, e cada uma existe por uma razão:**

    * **evidência vence catálogo.** Se o pipeline provou o campo numa fonte, o valor é o
      dele — é a hierarquia do produto, e o ano-modelo do site do fabricante vale mais que
      o do nosso cadastro;
    * **o catálogo preenche, nunca inventa.** Coluna vazia continua `nao_encontrado`;
    * **`origem="catalogo"` viaja no JSON.** A tela precisa poder dizer de onde veio, e
      um valor sem trecho verbatim não pode se passar por FATO: a regra do projeto é
      nenhum valor sem evidência, e a saída honesta é nomear a outra procedência.

    O filtro `attributes` continua mandando: o catálogo preenche o que foi pedido, e nada
    além.
    """
    linha = sessao.exec(
        select(Version, VehicleModel, Brand)
        .join(VehicleModel, VehicleModel.id == Version.model_id)
        .join(Brand, Brand.id == VehicleModel.brand_id)
        .where(Version.id == version_id)
    ).first()
    if linha is None:
        return

    versao, modelo, marca = linha
    for nome, ler in DO_CATALOGO.items():
        if pedidos is not None and nome not in pedidos:
            continue
        atual = spec.identificacao.get(nome)
        if atual is not None and atual.value is not None:
            continue
        valor = ler(marca, modelo, versao)
        if valor in (None, ""):
            continue
        spec.identificacao[nome] = SpecField(
            value=valor,
            status=Status.NAO_VERIFICADO,
            confidence=0.0,
            origem="catalogo",
            notes=NOTA_CATALOGO,
        )


def montar(
    sessao: Session,
    version_id: str,
    *,
    attributes: str | list[str] | None = None,
    job_id: str = "",
    sources_checked: list[str] | None = None,
) -> StandardSpec:
    """Monta a `StandardSpec` de uma versão a partir de `spec_values`.

    Versão sem nenhum valor gravado devolve a ficha vazia — todos os campos presentes,
    `nao_encontrado`, nenhum valor. É resposta legítima, e a única honesta antes de o
    pipeline rodar para aquela versão.
    """
    pedidos = campos_pedidos(attributes)
    spec = empty_spec(job_id=job_id or f"specs:{version_id}", sources_checked=sources_checked)

    linhas = sessao.exec(
        select(SpecValue, EvidenceRow)
        .join(EvidenceRow, EvidenceRow.id == SpecValue.evidence_id, isouter=True)
        .where(SpecValue.version_id == version_id)
    ).all()

    por_campo: dict[str, list[tuple[SpecValue, EvidenceRow | None]]] = defaultdict(list)
    fontes: set[str] = set(sources_checked or [])
    for valor, evidencia in linhas:
        por_campo[valor.field].append((valor, evidencia))
        if evidencia is not None and evidencia.snapshot_id:
            fontes.add(evidencia.snapshot_id)

    from api.app.models import FieldDecision

    decisions = sessao.exec(
        select(FieldDecision)
        .where(FieldDecision.version_id == version_id)
        .order_by(FieldDecision.criado_em, FieldDecision.id)
    ).all()
    published = {d.field: SpecField.model_validate(d.payload) for d in decisions}
    canonicos = {campo for campos in GRUPOS.values() for campo in campos}
    for nome in sorted(por_campo.keys() | published.keys()):
        do_campo = por_campo.get(nome, [])
        if pedidos is not None and nome not in pedidos:
            continue
        caminho = f"{grupo_de(nome)}.{nome}" if nome in canonicos else nome
        spec.set(caminho, published[nome] if nome in published else _campo_de(do_campo, nome))

    _preencher_identificacao(sessao, version_id, spec, pedidos)

    if pedidos is not None:
        # Os campos fora do filtro continuam **presentes**, sem valor e com a nota. É o
        # ponto do módulo: o filtro esconde valor, não campo.
        for grupo, campos in GRUPOS.items():
            for campo in campos:
                if campo not in pedidos:
                    spec.set(f"{grupo}.{campo}", _campo_nao_pedido(campo))

    spec.meta = SpecMeta(
        generated_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        job_id=job_id or f"specs:{version_id}",
        sources_checked=sorted(fontes),
    )
    return spec


def matriz_de_comparacao(
    sessao: Session,
    *,
    base_version_id: str,
    concorrentes: list[str],
    attributes: str | list[str] | None = None,
) -> dict:
    """A matriz de `docs/04`: `cells[i][j]` é um `SpecField`, com `diff` marcado.

    `diff=True` quando os valores canônicos diferem **ou um lado está vazio** — e o "ou"
    é a parte que importa. Numa comparação comercial, "o concorrente tem e nós não
    sabemos" é informação tão acionável quanto "o concorrente tem 20 cv a mais"; tratar
    vazio como igual esconderia exatamente a lacuna que o vendedor precisa conhecer antes
    de entrar na conversa.
    """
    ids = [base_version_id, *concorrentes]
    fichas = {vid: montar(sessao, vid, attributes=attributes) for vid in ids}

    pedidos = campos_pedidos(attributes)
    if pedidos is None:
        nomes = [campo for campos in GRUPOS.values() for campo in campos]
    else:
        nomes = [c for campos in GRUPOS.values() for c in campos if c in pedidos]

    celulas: list[list[dict]] = []
    for nome in nomes:
        linha: list[dict] = []
        base = fichas[base_version_id].get(f"{grupo_de(nome)}.{nome}")
        for vid in ids:
            campo = fichas[vid].get(f"{grupo_de(nome)}.{nome}")
            linha.append(
                {
                    **(campo.model_dump(mode="json") if campo else {}),
                    "diff": _difere(base, campo),
                }
            )
        celulas.append(linha)

    return {
        "attributes": nomes,
        "vehicles": ids,
        "base_vehicle_id": base_version_id,
        "cells": celulas,
    }


def _difere(base: SpecField | None, outro: SpecField | None) -> bool:
    """Os dois lados divergem? Vazio de um lado conta como divergência."""
    from pipeline.eval.compare import comparar_valor

    if base is None or outro is None:
        return base is not outro
    if base.value is None or outro.value is None:
        # Um lado vazio: só não é diferença se os dois estiverem vazios.
        return base.value is not outro.value
    campo = "comparacao"
    return not comparar_valor(campo, base.value, outro.value).igual
