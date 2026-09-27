"""Adaptador entre o banco e `pipeline/health.py`.

A regra de saúde é função pura (`health.avaliar`), e este módulo faz o trabalho chato de
ler `spec_values`, `evidences`, `sources` e `alerts` e entregar as linhas no formato que
ela consome. A separação existe para a regra ser testável sem banco — e para não haver
duas contas de saúde, uma no serviço e outra no módulo.

**A colapsagem por campo é a parte que merece atenção.** Um campo `divergente` tem mais de
uma linha em `spec_values` (é o que permite a tela mostrar os dois valores). A saúde conta
**campos**, não linhas: três fontes discordando é **um** conflito. Contar por linha faria o
painel piorar a cada fonte nova consultada, punindo justamente o comportamento desejado.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any

from sqlmodel import Session, select

from api.app.config import get_settings
from api.app.models import Alert, Brand, Evidence, SpecValue, VehicleModel, Version
from pipeline import health


def _rotulo(sessao: Session, version: Version) -> str:
    modelo = sessao.get(VehicleModel, version.model_id)
    marca = sessao.get(Brand, modelo.brand_id) if modelo else None
    partes = [p for p in (marca.nome if marca else "", modelo.nome if modelo else "") if p]
    return " ".join([*partes, version.nome_exato]).strip()


def _linhas_por_campo(sessao: Session, version_id: str) -> list[health.LinhaDeCampo]:
    """Lê os 54 campos pesquisáveis da mesma decisão exibida pela API.
    Tier e captura vêm das provas publicadas; conflitos e ausências ficam separados."""
    from api.app.services.spec_assembler import montar
    from pipeline.research.gaps import campos_procuraveis

    if not sessao.exec(select(SpecValue.id).where(SpecValue.version_id == version_id)).first():
        return []
    spec = montar(sessao, version_id)
    if spec is None:
        return []
    procuraveis = set(campos_procuraveis())
    saida = []
    for path, field in spec.itens():
        name = path.split(".")[-1]
        if name not in procuraveis:
            continue
        evidence = field.evidences
        dates = []
        for item in evidence:
            try:
                dates.append(
                    dt.datetime.fromisoformat(item.captured_at.replace("Z", "+00:00")).replace(
                        tzinfo=None
                    )
                )
            except (ValueError, TypeError):
                continue
        saida.append(
            health.LinhaDeCampo(
                campo=name,
                status=field.status.value,
                tier=min((e.tier for e in evidence), default=None),
                captured_at=max(dates) if dates else None,
                source_url=evidence[0].source_url if evidence else "",
            )
        )
    return saida


def _bloqueadas_da_versao(sessao: Session, version_id: str) -> list[str]:
    """As fontes bloqueadas registradas para esta versão.

    Vêm dos alertas `fonte_bloqueada` que `pipeline/persist.py` grava — é o único lugar
    onde a informação é **por versão**. A tabela `sources` guarda o estado da fonte, mas
    não diz qual extração bateu nela.
    """
    alertas = sessao.exec(
        select(Alert).where(Alert.type == "fonte_bloqueada", Alert.version_id == version_id)
    ).all()
    return [a.field for a in alertas if a.field]


def saude_da_versao(
    sessao: Session, version_id: str, *, limiar_de_dias: int | None = None
) -> health.SaudeDaVersao:
    """A saúde de uma versão. Versão sem ficha devolve `INSUFICIENTE`, não erro."""
    version = sessao.get(Version, version_id)
    limiar = limiar_de_dias if limiar_de_dias is not None else get_settings().health_stale_days
    return health.avaliar(
        _linhas_por_campo(sessao, version_id),
        version_id=version_id,
        rotulo=_rotulo(sessao, version) if version else "",
        bloqueadas=_bloqueadas_da_versao(sessao, version_id),
        limiar_de_dias=limiar,
    )


# --------------------------------------------------------------------------- cobertura
def cobertura(sessao: Session) -> list[health.CoberturaDaMarca]:
    """Cobertura por montadora, com os denominadores.

    `versoes_mapeadas` conta o catálogo; `versoes_com_ficha` conta quantas dessas alguém
    já extraiu. `por_campo` tem `versoes_com_ficha` como denominador — é o que faz
    "cobertura da Toyota em rpm = 1/1" significar "a única versão que temos publica rotação".
     A diferença entre os dois números é a informação: "temos 7 versões da S10
    mapeadas e 1 com ficha" diz o que falta fazer, enquanto uma porcentagem só esconderia
    o tamanho do trabalho.
    """
    marcas = sessao.exec(select(Brand)).all()
    saida: list[health.CoberturaDaMarca] = []

    for marca in marcas:
        versoes = sessao.exec(
            select(Version)
            .join(VehicleModel, VehicleModel.id == Version.model_id)
            .where(VehicleModel.brand_id == marca.id)
        ).all()
        resultado = health.CoberturaDaMarca(marca=marca.nome, versoes_mapeadas=len(versoes))

        oficiais = nao_encontrados = divergentes = 0
        total_de_campos = 0
        destacados: dict[str, list[int]] = {campo: [0, 0] for campo in health.CAMPOS_DESTACADOS}

        for version in versoes:
            linhas = _linhas_por_campo(sessao, version.id)
            if not linhas:
                continue
            resultado.versoes_com_ficha += 1
            total_de_campos += len(linhas)
            com_valor = {linha.campo for linha in linhas if linha.status == "verificado"}
            for linha in linhas:
                if linha.status == "nao_encontrado":
                    nao_encontrados += 1
                if linha.status == "divergente":
                    divergentes += 1
                if linha.tier == health.TIER_OFICIAL:
                    oficiais += 1
            # O denominador dos campos destacados é **versões com ficha**, não linhas de
            # campo existentes. "Cobertura da Toyota em rpm = 100%" é uma afirmação sobre
            # as versões que temos, e contar linhas daria zero numa ficha parcial — o que
            # sairia como "0/0" e some da tela justamente quando há o que dizer.
            for campo in destacados:
                destacados[campo][1] += 1
                if campo in com_valor:
                    destacados[campo][0] += 1

        resultado.campos_com_fonte_oficial = health.Indicador(oficiais, total_de_campos)
        resultado.nao_encontrados = health.Indicador(nao_encontrados, total_de_campos)
        resultado.divergencias = health.Indicador(divergentes, total_de_campos)
        resultado.por_campo = {
            campo: health.Indicador(valor, de) for campo, (valor, de) in destacados.items()
        }
        saida.append(resultado)

    # Ordem estável e útil: quem tem mais versão com ficha primeiro, depois pelo nome.
    saida.sort(key=lambda c: (-c.versoes_com_ficha, c.marca))
    return saida


# ------------------------------------------------------------------------ divergências
#: Os dois escopos de `docs/13` §3.
OFICIAL_VS_IMPRENSA = "official_vs_press"
INTERNO_VS_PUBLICO = "internal_vs_public"
ESCOPOS = (OFICIAL_VS_IMPRENSA, INTERNO_VS_PUBLICO)


def divergencias(sessao: Session, *, escopo: str) -> list[dict[str, Any]]:
    """As divergências, com **os dois valores**, as duas fontes e o gap quando há.

    `official_vs_press` lê os campos `divergente` de `spec_values`: cada valor concorrente
    tem a sua evidência, e o tier de cada uma é o que diz se a discordância é entre a
    montadora e a imprensa ou entre duas páginas oficiais. `internal_vs_public` lê os
    alertas `referencia_interna_divergente`, que já nascem com os dois lados.
    """
    if escopo == INTERNO_VS_PUBLICO:
        alertas = sessao.exec(
            select(Alert)
            .where(Alert.type == "referencia_interna_divergente")
            .order_by(Alert.created_at.desc())
        ).all()
        saida = []
        for alerta in alertas:
            version = sessao.get(Version, alerta.version_id) if alerta.version_id else None
            saida.append(
                {
                    "escopo": escopo,
                    "version_id": alerta.version_id,
                    "rotulo": _rotulo(sessao, version) if version else "",
                    "campo": alerta.field,
                    "valores": [
                        {"valor": alerta.old, "origem": "referência interna", "tier": None},
                        {"valor": alerta.new, "origem": "fonte pública", "tier": None},
                    ],
                    "gap": None,
                    "detectado_em": (
                        alerta.created_at.isoformat()
                        if isinstance(alerta.created_at, dt.datetime)
                        else None
                    ),
                }
            )
        return saida

    linhas = sessao.exec(
        select(SpecValue, Evidence)
        .join(Evidence, Evidence.id == SpecValue.evidence_id, isouter=True)
        .where(SpecValue.status == "divergente")
    ).all()

    agrupado: dict[tuple[str, str], list[tuple[SpecValue, Evidence | None]]] = defaultdict(list)
    for valor, evidencia in linhas:
        agrupado[(valor.version_id, valor.field)].append((valor, evidencia))

    saida = []
    for (version_id, campo), itens in sorted(agrupado.items()):
        version = sessao.get(Version, version_id)
        valores = [
            {
                "valor": v.value_json,
                "origem": (e.source_url if e is not None else "sem evidência"),
                "tier": (e.tier if e is not None else None),
            }
            for v, e in itens
        ]
        numeros = [x["valor"] for x in valores if isinstance(x["valor"], int | float)]
        saida.append(
            {
                "escopo": escopo,
                "version_id": version_id,
                "rotulo": _rotulo(sessao, version) if version else "",
                "campo": campo,
                "valores": valores,
                # Gap só existe entre números. Em campo de texto ou lista, `None` — e
                # `None` não é zero: zero afirmaria que os valores coincidem.
                "gap": (max(numeros) - min(numeros)) if len(numeros) >= 2 else None,
                "detectado_em": None,
            }
        )
    return saida
