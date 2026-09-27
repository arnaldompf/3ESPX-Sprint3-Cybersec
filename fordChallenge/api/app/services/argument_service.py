"""Monta o argumentário a partir do banco, e respeita o que o gestor travou.

A ordem de precedência é a de `docs/12` §6.4, e ela não é negociável:

1. **texto travado pelo gestor** — se existe, é ele, e a resposta diz `aprovado=true`;
2. reescrita do LLM **verificada** contra as células;
3. template determinístico.

O travado vem primeiro porque é a única forma de o Product Marketing garantir a mensagem
numa campanha. Um argumentário que "melhora" sozinho depois de aprovado tornaria a
aprovação decorativa.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlmodel import Session, select

from api.app.models import ArgumentTemplate, Brand, Evidence, SpecValue, VehicleModel, Version
from api.app.services import fit_service
from pipeline.arguments import llm_rewrite, template
from pipeline.fit import engine

#: O separador do `comparison_id`.
#:
#: A spec pede `POST /comparisons/{id}/arguments`, e comparações **não são persistidas**
#: (`/comparisons` é sem estado desde a WP-06). O id é o par `fordId:concorrenteId`, que
#: é determinístico, não exige tabela nova e é o mesmo valor que `showroom_sessions`
#: guarda em `comparison_id`. Está registrado em `DECISOES_NOITE.md`.
SEPARADOR_DO_PAR = ":"


class ParInvalido(ValueError):
    """O `comparison_id` não tem a forma `fordId:concorrenteId`."""


def par_de(comparison_id: str) -> tuple[str, str]:
    partes = comparison_id.split(SEPARADOR_DO_PAR)
    if len(partes) != 2 or not all(partes):
        raise ParInvalido(
            f"`{comparison_id}` não é um par válido. O formato é "
            f"`fordVersionId{SEPARADOR_DO_PAR}competitorVersionId`."
        )
    return partes[0], partes[1]


def id_do_par(ford_version_id: str, competitor_version_id: str) -> str:
    return f"{ford_version_id}{SEPARADOR_DO_PAR}{competitor_version_id}"


def _rotulo(sessao: Session, version: Version | None) -> str:
    if version is None:
        return ""
    modelo = sessao.get(VehicleModel, version.model_id)
    marca = sessao.get(Brand, modelo.brand_id) if modelo else None
    partes = [p for p in (marca.nome if marca else "", modelo.nome if modelo else "") if p]
    return " ".join([*partes, version.nome_exato]).strip()


def _celulas(
    sessao: Session, ford_version_id: str, competitor_version_id: str
) -> dict[str, template.CampoDaCelula]:
    """Campo → valores, unidades, evidências e datas dos dois lados.

    Só entra campo com valor **nos dois**: um argumento precisa de comparação, e "a Ford
    tem 620 kg contra sem valor" não é frase que alguém use na frente do cliente.
    """

    def por_versao(version_id: str) -> dict[str, tuple[SpecValue, Evidence | None]]:
        linhas = sessao.exec(
            select(SpecValue, Evidence)
            .join(Evidence, Evidence.id == SpecValue.evidence_id, isouter=True)
            .where(SpecValue.version_id == version_id, SpecValue.status == "verificado")
        ).all()
        return {valor.field: (valor, evidencia) for valor, evidencia in linhas}

    da_ford = por_versao(ford_version_id)
    do_conc = por_versao(competitor_version_id)

    saida: dict[str, template.CampoDaCelula] = {}
    for campo in sorted(set(da_ford) & set(do_conc)):
        vf, ef = da_ford[campo]
        vc, ec = do_conc[campo]
        saida[campo] = template.CampoDaCelula(
            campo=campo,
            valor_ford=vf.value_json,
            valor_concorrente=vc.value_json,
            unidade=vf.unit or vc.unit,
            evidence_id_ford=ef.id if ef else None,
            evidence_id_concorrente=ec.id if ec else None,
            fonte_ford=(ef.source_url if ef else ""),
            fonte_concorrente=(ec.source_url if ec else ""),
            data_ford=(ef.captured_at.isoformat() if ef and ef.captured_at else ""),
            data_concorrente=(ec.captured_at.isoformat() if ec and ec.captured_at else ""),
        )
    return saida


def aprovado_do_par(
    sessao: Session, ford_version_id: str, competitor_version_id: str
) -> ArgumentTemplate | None:
    return sessao.exec(
        select(ArgumentTemplate).where(
            ArgumentTemplate.ford_version_id == ford_version_id,
            ArgumentTemplate.competitor_version_id == competitor_version_id,
        )
    ).first()


def montar(
    sessao: Session,
    *,
    ford_version_id: str,
    competitor_version_id: str,
    perfil: engine.NeedsProfile,
    permitir_llm: bool = True,
) -> dict[str, Any]:
    """O argumentário do par, com a precedência do docstring do módulo."""
    ford = sessao.get(Version, ford_version_id)
    concorrente = sessao.get(Version, competitor_version_id)
    rotulo_ford = _rotulo(sessao, ford)
    rotulo_conc = _rotulo(sessao, concorrente)

    fit = fit_service.montar(
        sessao,
        base_version_id=ford_version_id,
        concorrentes=[competitor_version_id],
        perfil=perfil,
    )
    aderencia = fit["concorrentes"][0]["aderencia"]
    celulas = _celulas(sessao, ford_version_id, competitor_version_id)

    argumentario = template.montar(
        aderencia,
        celulas,
        rotulo_ford=rotulo_ford,
        rotulo_concorrente=rotulo_conc,
    )

    reescrita = llm_rewrite.reescrever(argumentario, celulas, permitir_llm=permitir_llm)
    textos = reescrita.textos
    gerado_por = reescrita.gerado_por

    linha = aprovado_do_par(sessao, ford_version_id, competitor_version_id)
    aprovado = bool(linha and linha.aprovado)
    travado = bool(linha and linha.travado)
    if travado and linha is not None and linha.textos:
        # Travado ganha de tudo. Ver o docstring do módulo.
        textos = list(linha.textos)
        gerado_por = "travado_pelo_gestor"

    dados = argumentario.to_dict()
    for indice, ponto in enumerate(dados["pontos"]):
        if indice < len(textos):
            ponto["texto"] = textos[indice]
    if dados["ponto_forte_concorrente"] is not None and len(textos) > len(dados["pontos"]):
        dados["ponto_forte_concorrente"]["texto"] = textos[len(dados["pontos"])]

    dados.update(
        {
            "comparison_id": id_do_par(ford_version_id, competitor_version_id),
            "ford": {"version_id": ford_version_id, "rotulo": rotulo_ford},
            "concorrente": {"version_id": competitor_version_id, "rotulo": rotulo_conc},
            "gerado_por": gerado_por,
            "aprovado": aprovado,
            "aprovado_por": (linha.aprovado_por or "") if linha else "",
            "travado": travado,
            "reescrita": reescrita.to_dict(),
            "pesos": fit["pesos"],
            "rotulo_da_aderencia": fit["rotulo"],
            # A tela mostra isto quando existe. `docs/12` §6.4.
            "selo": "aprovado pelo Product Marketing" if aprovado else "",
        }
    )
    return dados


def registrar_aprovacao(
    sessao: Session,
    *,
    ford_version_id: str,
    competitor_version_id: str,
    textos: list[str] | None,
    aprovado: bool,
    travado: bool,
    usuario_id: str,
    nota: str | None = None,
) -> ArgumentTemplate:
    """Cria ou atualiza a aprovação do par. Idempotente por par."""
    linha = aprovado_do_par(sessao, ford_version_id, competitor_version_id)
    if linha is None:
        linha = ArgumentTemplate(
            ford_version_id=ford_version_id,
            competitor_version_id=competitor_version_id,
        )
    linha.textos = list(textos or [])
    linha.aprovado = aprovado
    linha.travado = travado
    linha.aprovado_por = usuario_id
    linha.nota = nota
    linha.atualizado_em = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    sessao.add(linha)
    sessao.commit()
    sessao.refresh(linha)
    return linha
