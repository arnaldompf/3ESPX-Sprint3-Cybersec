"""`specradar refresh --watchlist` — recoleta e gera os alertas reais do Radar.

O que "watchlist" significa aqui: as versões que já têm ficha no banco. Não há tabela de
watchlist separada porque ela seria redundante — uma versão entra no radar quando alguém
pediu uma extração dela, e é isso que a existência de `spec_values` registra. Inventar uma
segunda lista criaria dois lugares para manter em sincronia.

**Como o alerta nasce sem inventar mudança:** o pipeline roda de novo, a ficha nova é
comparada com a que está no banco, e `pipeline/radar/` classifica e enriquece. Em replay,
sobre os mesmos snapshots, o resultado é **zero alertas** — e isso é o teste de
determinismo (o mesmo do `specradar diff`). Alerta aparecendo em replay significa que a
extração não é reproduzível.

A mudança real da demo vem de `docs/12` §2.3: a FIPE muda a referência mensal, e a tabela
de outubro gera diffs verdadeiros nos quatro veículos. É por isso que este comando existe
com `--watchlist` em vez de um botão na tela: quem roda é o cron depois da publicação da
tabela.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import structlog
from sqlmodel import Session, select

from api.app.db import engine
from api.app.models import (
    Alert,
    Brand,
    Equivalent,
    InternalReference,
    SpecValue,
    VehicleModel,
    Version,
)
from pipeline.radar import tipos
from pipeline.schema import StandardSpec

log = structlog.get_logger(__name__)


@dataclass
class ResultadoDoRefresh:
    """O que a passada fez. Contadores separados porque significam coisas diferentes."""

    versoes: int = 0
    alertas: int = 0
    #: Alertas de divergência com o material interno. Contados à parte porque são de outra
    #: natureza: não é o mercado que mudou, é o nosso próprio material que está errado.
    alertas_internos: int = 0
    sem_mudanca: int = 0
    sem_evidencia_descartados: int = 0
    erros: list[str] = field(default_factory=list)


def versoes_na_watchlist(sessao: Session) -> list[Version]:
    """As versões que já têm ficha gravada. Ver o docstring do módulo."""
    ids = sessao.exec(select(SpecValue.version_id).distinct()).all()
    if not ids:
        return []
    return list(sessao.exec(select(Version).where(Version.id.in_(list(ids)))).all())


def _identidade(sessao: Session, version: Version) -> tuple[str, str, str]:
    modelo = sessao.get(VehicleModel, version.model_id)
    marca = sessao.get(Brand, modelo.brand_id) if modelo else None
    return (
        marca.nome if marca else "",
        modelo.nome if modelo else "",
        version.nome_exato,
    )


def _preco_do_equivalente(sessao: Session, version_id: str) -> tuple[float | None, str | None]:
    """O preço da versão Ford equivalente, e o id dela.

    Sem equivalente cadastrado devolve `(None, None)`, e o impacto sai sem gap com o
    motivo — ver `pipeline/radar/impact.py`. Inventar um par para poder exibir um número
    compararia coisas que o gestor decidiu que não se comparam.
    """
    equivalencia = sessao.exec(
        select(Equivalent).where(Equivalent.competitor_version_id == version_id)
    ).first()
    if equivalencia is None or not equivalencia.ford_version_id:
        return None, (equivalencia.ford_version_id if equivalencia else None)

    linha = sessao.exec(
        select(SpecValue).where(
            SpecValue.version_id == equivalencia.ford_version_id,
            SpecValue.field == "preco_sugerido_brl",
        )
    ).first()
    valor = linha.value_json if linha is not None else None
    return (float(valor) if isinstance(valor, int | float) else None), equivalencia.ford_version_id


def _e_da_ford(marca: str) -> bool:
    return marca.strip().lower() == "ford"


def _ja_existe(sessao: Session, *, tipo: str, version_id: str, campo: str, old, new) -> bool:
    """Um alerta idêntico já aberto? Então não abre outro.

    Sem esta checagem cada passada do cron republicaria a mesma divergência, e uma lista
    que cresce sozinha treina o usuário a ignorá-la. O critério é a **tupla inteira**
    (tipo, versão, campo, antes, depois): mudar qualquer ponta é fato novo.
    """
    # `old`/`new` ficam em coluna JSON, e comparar JSON no WHERE muda de dialeto entre
    # SQLite e Postgres. Filtrar pelas três colunas indexáveis e conferir os valores em
    # Python roda igual nos dois — e a lista por (tipo, versao, campo) é curta.
    candidatos = sessao.exec(
        select(Alert).where(
            Alert.type == tipo,
            Alert.version_id == version_id,
            Alert.field == campo,
        )
    ).all()
    return any(a.old == old and a.new == new for a in candidatos)


def alertas_de_referencia_interna(
    sessao: Session, version: Version, ficha: StandardSpec, *, resultado: ResultadoDoRefresh
) -> list[Alert]:
    """Compara o material interno com a ficha pública e abre os alertas da diferença.

    `docs/12` §6.1 diz que a origem dos alertas é "o diff entre as duas coletas **mais** a
    comparação com `internal_references`" — e o segundo termo é o que o cliente viu na
    demo: o deck dizendo "Baja" onde a página da Ford diz "Off-Road". Sem isto aqui, a
    divergência só apareceria no instante do upload e nunca mais, mesmo depois de a fonte
    pública mudar.
    """
    from pipeline.radar import internal

    linhas = sessao.exec(
        select(InternalReference).where(InternalReference.version_id == version.id)
    ).all()
    if not linhas:
        return []

    internos = {linha.field: linha.value_json for linha in linhas}
    raws = {linha.field: (linha.raw_value or "") for linha in linhas}
    documento = next((linha.documento for linha in linhas if linha.documento), "referencia interna")

    publicos: dict[str, object] = {}
    for caminho, campo in ficha.itens():
        publicos[caminho.split(".", 1)[-1]] = campo.value

    # A evidência do alerta vem do **banco**, não da ficha recém-rodada.
    #
    # DEFEITO CORRIGIDO: aqui saía `campo.evidences[0].evidence_id`, que na ficha do
    # pipeline é um id sintético (`source_id:campo`) e **não** a chave de nenhuma linha de
    # `evidences`. O alerta gravava "ford_ficha_tecnica:modos_direcao", e a cadeia do
    # "Por quê?" (WP-34) não achava a evidência: o elo saía com o motivo de ausência
    # justamente na cena-assinatura do Fogo Amigo. Nada acusava — o campo é opcional, e
    # `_evidencia_out` devolve `None` para id inexistente.
    #
    # A evidência só é anexada quando o valor do banco **é** o valor público comparado:
    # citar o trecho de um valor diferente do que está no alerta seria prova de outra
    # coisa. Divergindo, o elo fica vazio e a cadeia diz o motivo (WP-34).
    evidencias: dict[str, str | None] = {}
    for linha in sessao.exec(select(SpecValue).where(SpecValue.version_id == version.id)).all():
        if linha.evidence_id and linha.value_json == publicos.get(linha.field):
            evidencias[linha.field] = linha.evidence_id

    gravados: list[Alert] = []
    for divergencia in internal.comparar_com_publico(
        internos, publicos, documento=documento, raws=raws
    ):
        alerta = tipos.da_divergencia_interna(divergencia)
        if _ja_existe(
            sessao,
            tipo=alerta.type,
            version_id=version.id,
            campo=divergencia.campo,
            old=divergencia.valor_interno,
            new=divergencia.valor_publico,
        ):
            continue
        linha = Alert(
            type=alerta.type,
            version_id=version.id,
            field=divergencia.campo,
            old=divergencia.valor_interno,
            new=divergencia.valor_publico,
            evidence_after_id=evidencias.get(divergencia.campo),
            impact_json=alerta.impacto.to_dict(),
            reactions_json=alerta.reacoes.to_dict() if alerta.reacoes else None,
            is_simulated=False,
        )
        sessao.add(linha)
        gravados.append(linha)

    if gravados:
        sessao.commit()
        resultado.alertas_internos += len(gravados)
    return gravados


def refrescar_versao(
    sessao: Session, version: Version, *, resultado: ResultadoDoRefresh
) -> list[Alert]:
    """Roda o pipeline de novo e grava os alertas da diferença."""
    from api.app.services import spec_assembler
    from pipeline.run import run

    marca, modelo, versao = _identidade(sessao, version)
    antes: StandardSpec = spec_assembler.montar(sessao, version.id)

    try:
        depois = run(marca, modelo, versao, replay=True, version_id=version.id)
    except Exception as exc:  # pragma: no cover - falha de fonte não derruba a passada
        resultado.erros.append(f"{version.id}: {type(exc).__name__}: {exc}")
        log.warning("refresh.falhou", version_id=version.id, erro=str(exc))
        return []

    preco_ford, ford_id = _preco_do_equivalente(sessao, version.id)
    detectados = tipos.detectar(
        antes,
        depois,
        preco_ford=preco_ford,
        preco_ford_equivalente_id=ford_id,
        e_do_concorrente=not _e_da_ford(marca),
    )

    # A comparação com o material interno roda **sempre**, mesmo quando a ficha pública
    # não mudou: o deck pode ter sido subido depois da última passada.
    internos = alertas_de_referencia_interna(sessao, version, depois, resultado=resultado)

    if not detectados:
        if not internos:
            resultado.sem_mudanca += 1
        return internos

    gravados: list[Alert] = []
    for alerta in detectados:
        gravados.append(
            Alert(
                type=alerta.type,
                version_id=version.id,
                field=alerta.field,
                old=alerta.old,
                new=alerta.new,
                impact_json=alerta.impacto.to_dict(),
                reactions_json=alerta.reacoes.to_dict() if alerta.reacoes else None,
                is_simulated=False,
            )
        )
    for linha in gravados:
        sessao.add(linha)
    sessao.commit()
    resultado.alertas += len(gravados)
    return gravados + internos


def main(*, watchlist: bool = False, limite: int | None = None) -> int:
    """Ponto de entrada da CLI. Devolve 0 mesmo sem alertas — silêncio é resultado."""
    resultado = ResultadoDoRefresh()

    with Session(engine()) as sessao:
        # `--watchlist` nao filtra hoje porque a watchlist E a lista de versoes com
        # ficha (ver o docstring). O parametro existe no contrato da CLI da spec e
        # fica registrado para quando houver curadoria de quais versoes monitorar.
        versoes = versoes_na_watchlist(sessao)
        del watchlist
        if limite:
            versoes = versoes[:limite]
        resultado.versoes = len(versoes)
        for version in versoes:
            refrescar_versao(sessao, version, resultado=resultado)

    print(
        f"refresh: {resultado.versoes} versao(oes), {resultado.alertas} alerta(s) de mudanca, "
        f"{resultado.alertas_internos} de divergencia interna, "
        f"{resultado.sem_mudanca} sem mudanca"
    )
    if resultado.erros:
        print(f"  {len(resultado.erros)} falha(s):")
        for erro in resultado.erros[:5]:
            print(f"    {erro}")
    if resultado.versoes == 0:
        # Não é erro: watchlist vazia significa que ninguém extraiu nada ainda.
        print("  (nenhuma versao com ficha no banco; rode `specradar extract` primeiro)")
    return 0


#: Os alertas de demonstração. **Sempre** com `is_simulated=True`, e o texto diz isso.
#:
#: `docs/12` §3.8 é explícito: dado de demonstração leva o rótulo SIMULAÇÃO em tela e no
#: vídeo. O que existe aqui é o cenário da §6.1 — preço de concorrente caindo, FIPE
#: mudando de referência — para a tela do Radar ter o que mostrar antes de a tabela de
#: outubro sair.
CENARIOS_SIMULADOS = (
    {
        "type": "preco_oficial",
        "field": "preco_sugerido_brl",
        "old": 348790,
        "new": 329990,
        "nota": "concorrente reduziu o preco de tabela",
    },
    {
        "type": "preco_fipe",
        "field": "preco_fipe_brl",
        "old": 294378,
        "new": 301500,
        "nota": "nova referencia mensal da FIPE",
    },
    {
        "type": "campo_alterado",
        "field": "garantia_meses",
        "old": 36,
        "new": 60,
        "nota": "concorrente ampliou a garantia",
    },
)


def semear_alertas_simulados(quantidade: int, *, version_id: str | None = None) -> int:
    """Gera alertas de demonstração, **todos** com `is_simulated=True`.

    Chamado por `specradar seed --simulated-alerts N`. O impacto e as reações saem das
    mesmas regras do alerta real — o que é simulado é o **dado**, não o cálculo: um
    impacto calculado por outro caminho na demo mostraria uma tela que não existe.
    """
    from pipeline.radar import impact, reactions

    criados = 0
    agora = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    with Session(engine()) as sessao:
        alvo = version_id
        if alvo is None:
            primeira = sessao.exec(select(Version)).first()
            alvo = primeira.id if primeira is not None else None
        if alvo is None:
            print("seed: nenhuma versao no banco; rode `specradar seed` antes")
            return 0

        for indice in range(quantidade):
            cenario = CENARIOS_SIMULADOS[indice % len(CENARIOS_SIMULADOS)]
            impacto = impact.calcular(
                campo=str(cenario["field"]),
                antes=cenario["old"],
                depois=cenario["new"],
            )
            sessao.add(
                Alert(
                    type=str(cenario["type"]),
                    version_id=alvo,
                    field=str(cenario["field"]),
                    old=cenario["old"],
                    new=cenario["new"],
                    impact_json=impacto.to_dict(),
                    reactions_json=reactions.to_dict(str(cenario["type"]), impacto.direcao),
                    # A marca que a tela usa para pintar a faixa SIMULACAO.
                    is_simulated=True,
                    created_at=agora - dt.timedelta(hours=indice),
                )
            )
            criados += 1
        sessao.commit()

    print(f"seed: {criados} alerta(s) SIMULADO(s) — todos com is_simulated=true")
    return criados
