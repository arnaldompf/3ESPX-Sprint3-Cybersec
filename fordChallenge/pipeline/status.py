"""Status e confiança por campo — onde as regras de honestidade decidem.

Cada campo da ficha recebe um dos seis status, e a escolha nunca é uma questão de gosto:

* **`verificado`** — há evidência localizada no texto salvo, e as fontes que falam do
  campo concordam dentro da tolerância.
* **`divergente`** — há evidência, mas as fontes discordam. **Todos** os valores ficam em
  `conflicts`, com a evidência de cada um. O sistema não escolhe em silêncio (`docs/12` §3.3).
* **`nao_verificado`** — havia um valor, mas o `evidence_quote` não foi localizado. O
  **valor é descartado**; o quote fica guardado para auditoria.
* **`nao_disponivel`** — a fonte oficial **afirma** a ausência: "não disponível", "não
  oferecido", ou `—` na coluna daquela versão.
* **`nao_encontrado`** — nenhuma das fontes consultadas menciona o campo. A lista de
  fontes consultadas vai em `sources_checked`, porque "não encontrei" sem dizer onde
  procurei não é informação.
* **`pendente`** — ainda não foi coletado.

Os dois vazios são **estados diferentes** e nunca se colapsam: "a Ford diz que não tem"
não é "não achei". A tela mostra os dois de formas distintas (`docs/13` §2), e o eval
mede a fidelidade dessa distinção.

Confiança (`docs/02`, item 8): base do melhor tier (T1 0,90 · T2 0,85 · T3 0,60 · T4 0,40
· T5 0,20), mais 0,05 por fonte concordante extra, teto 1,0. Campo `divergente` **não**
ganha bônus: discordância não aumenta certeza.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.eval.compare import comparar_valor
from pipeline.ground import Localizacao, locate, registrar_falha
from pipeline.schema import CONFIANCA_POR_TIER, Conflict, Evidence, SpecField, Status

#: Bônus por fonte concordante além da primeira (`docs/02`).
BONUS_POR_CONCORDANTE = 0.05
#: Teto de confiança.
CONFIANCA_MAXIMA = 1.0
#: `docs/05`: campo sustentado **apenas** por imprensa não passa de 0,60.
CONFIANCA_MAXIMA_TIER3 = 0.60


@dataclass
class Observacao:
    """Um valor observado numa fonte, antes de virar (ou não) valor da ficha."""

    campo: str
    valor: Any
    quote: str
    source_id: str = ""
    url: str = ""
    tier: int = 5
    captured_at: str = ""
    raw_value: str = ""
    unidade: str | None = None
    pagina: int | None = None
    notas: str = ""
    ausencia_declarada: bool = False
    """A fonte afirmou que o item não existe nesta versão."""
    tipo_de_afirmacao: str | None = None
    evidence_ref: Evidence | None = None
    """`declarado` / `medido` / `listado`. `None` é desconhecido, e é o padrão."""

    def evidencia(self, *, evidence_id: str = "") -> Evidence:
        if self.evidence_ref is not None:
            return self.evidence_ref
        return Evidence(
            evidence_id=evidence_id or f"{self.source_id}:{self.campo}",
            source_url=self.url or f"snapshot://{self.source_id}",
            tier=max(1, min(5, self.tier)),
            quote=self.quote[:300],
            captured_at=self.captured_at or "",
            raw_value=self.raw_value or None,
            snapshot_id=self.source_id or None,
            page=self.pagina,
            tipo_de_afirmacao=self.tipo_de_afirmacao,  # type: ignore[arg-type]
        )


@dataclass
class Decisao:
    """O que o campo virou, e por quê."""

    campo: str
    spec: SpecField
    motivo: str = ""
    grupos: list[list[Observacao]] = field(default_factory=list)
    """Observações agrupadas por valor compatível — o que sustenta `divergente`."""
    localizacoes: dict[str, Localizacao] = field(default_factory=dict)
    descartadas: list[Observacao] = field(default_factory=list)
    """Observações cujo quote não foi localizado; guardadas para auditoria."""

    @property
    def status(self) -> Status:
        return self.spec.status


def authority(campo: str, obs: Observacao) -> int:
    """Prioridade específica do atributo, sempre depois da validação de aplicabilidade."""
    if campo in {"consumo_urbano_kml", "consumo_rodoviario_kml"}:
        from urllib.parse import urlparse

        host = (urlparse(obs.url).hostname or "").lower()
        if (
            host == "inmetro.gov.br"
            or host.endswith(".inmetro.gov.br")
            or (host == "www.gov.br" and "/inmetro/" in obs.url)
        ):
            return 0
    return obs.tier


def _agrupar_por_valor(campo: str, observacoes: list[Observacao]) -> list[list[Observacao]]:
    """Agrupa observações cujos valores são compatíveis na tolerância do campo.

    Usa `comparar_valor` — a **mesma** função do eval. Se a reconciliação achasse
    "compatível" o que o eval acha "diferente", o pipeline concordaria consigo mesmo e
    discordaria da régua.
    """
    grupos: list[list[Observacao]] = []
    for obs in sorted(observacoes, key=lambda o: (o.tier, repr(o.valor), o.url, o.quote)):
        for grupo in grupos:
            if all(_compativel(campo, o.valor, obs.valor) for o in grupo):
                grupo.append(obs)
                break
        else:
            grupos.append([obs])
    for grupo in grupos:
        grupo.sort(key=lambda o: (o.tier, o.url, o.source_id, repr(o.valor)))
    grupos.sort(key=lambda g: (min(authority(campo, o) for o in g), repr(g[0].valor), g[0].url))
    return grupos


def _compativel(campo: str, a: Any, b: Any) -> bool:
    """Compara equivalência nas duas direções. Textos podem admitir recorte
    contextual; listas exigem os mesmos itens após os aliases explícitos."""
    return comparar_valor(campo, a, b).igual or comparar_valor(campo, b, a).igual


def _confianca(grupo: list[Observacao], *, divergente: bool) -> float:
    melhor_tier = min(o.tier for o in grupo)
    base = CONFIANCA_POR_TIER.get(melhor_tier, 0.2)
    if divergente:
        # Discordância não aumenta certeza. Fica a base do melhor tier, sem bônus.
        return round(base, 4)
    from pipeline.ground import normalize_texto

    fontes = min(
        len({o.source_id or o.url for o in grupo}), len({normalize_texto(o.quote) for o in grupo})
    )
    valor = base + BONUS_POR_CONCORDANTE * max(fontes - 1, 0)
    if melhor_tier >= 3:
        valor = min(valor, CONFIANCA_MAXIMA_TIER3)
    return round(min(valor, CONFIANCA_MAXIMA), 4)


def _representante(grupo: list[Observacao]) -> Observacao:
    """Escolhe uma observação do grupo equivalente. A autoridade vem primeiro;
    uma data completa conserva o dia quando a outra informa apenas o mesmo mês.
    Listas só chegam ao mesmo grupo quando contêm os mesmos itens canônicos."""
    if grupo[0].campo == "preco_data":
        melhor_tier = min(o.tier for o in grupo)
        return max((o for o in grupo if o.tier == melhor_tier), key=lambda o: len(str(o.valor)))
    listas = [o for o in grupo if isinstance(o.valor, (list, tuple))]
    if listas:
        return max(listas, key=lambda o: len(o.valor))
    return grupo[0]


def decidir(
    campo: str,
    observacoes: list[Observacao],
    *,
    textos: dict[str, str],
    sources_checked: list[str] | None = None,
) -> Decisao:
    """Aplica grounding, agrupa por valor e devolve o campo com status e confiança.

    A ordem é obrigatória: **grounding primeiro**. Um valor cujo quote não é localizado
    nem entra no agrupamento — senão ele poderia "vencer" por maioria e virar valor da
    ficha sem evidência.
    """
    fontes = list(sources_checked or sorted({o.url or o.source_id for o in observacoes}))

    if not observacoes:
        return Decisao(
            campo,
            SpecField.vazio(Status.NAO_ENCONTRADO, sources_checked=fontes),
            motivo="nenhuma fonte consultada menciona o campo",
        )

    localizacoes: dict[str, Localizacao] = {}
    validas: list[Observacao] = []
    descartadas: list[Observacao] = []
    ausencias: list[Observacao] = []

    for obs in observacoes:
        achado = locate(obs.quote, textos.get(obs.source_id, ""))
        localizacoes[f"{obs.source_id}:{obs.quote[:40]}"] = achado
        if achado.ok and obs.ausencia_declarada:
            ausencias.append(obs)
        elif achado.ok:
            validas.append(obs)
        else:
            registrar_falha(campo)
            descartadas.append(obs)

    if validas:
        grupos = _agrupar_por_valor(campo, validas)
        # Autoridade decide antes da quantidade. Republicações não vencem a fonte primária.
        melhor_tier = min(authority(campo, o) for o in validas)
        contestadas = [
            o for g in grupos if min(authority(campo, o) for o in g) > melhor_tier for o in g
        ]
        grupos = [g for g in grupos if min(authority(campo, o) for o in g) == melhor_tier]
        descartadas.extend(contestadas)
        principal = grupos[0]
        divergente = len(grupos) > 1
        representante = _representante(principal)
        evidencias = [o.evidencia() for o in principal]
        conflitos = [
            Conflict(
                value=g[0].valor,
                evidence=g[0].evidencia(),
                notes=g[0].notas or None,
            )
            for g in grupos[1:]
        ]
        conflitos.extend(
            Conflict(
                value=o.valor,
                evidence=o.evidencia(),
                notes="contestação de fonte inferior; decisão principal preservada",
            )
            for o in contestadas
        )
        spec = SpecField(
            value=representante.valor,
            unit=representante.unidade,
            status=Status.DIVERGENTE if divergente else Status.VERIFICADO,
            confidence=_confianca(principal, divergente=divergente),
            evidences=evidencias,
            conflicts=conflitos,
            sources_checked=fontes,
            notes=_nota(principal, grupos, descartadas),
        )
        motivo = (
            f"{len(grupos)} valores distintos com evidência: divergência exposta"
            if divergente
            else f"{len(principal)} fonte(s) concordante(s), melhor tier "
            f"{min(o.tier for o in principal)}"
        )
        return Decisao(campo, spec, motivo, grupos, localizacoes, descartadas)

    if ausencias:
        # A fonte **oficial** afirmando ausência é `nao_disponivel`. Imprensa dizendo que
        # não viu não é afirmação de ausência — é ausência de menção.
        oficiais = [o for o in ausencias if o.tier <= 2]
        alvo = oficiais or ausencias
        return Decisao(
            campo,
            SpecField(
                value=None,
                status=Status.NAO_DISPONIVEL if oficiais else Status.NAO_ENCONTRADO,
                evidences=[o.evidencia() for o in oficiais],
                sources_checked=fontes,
                notes=(
                    f"a fonte oficial ({alvo[0].source_id}) marca ausência para esta versão"
                    if oficiais
                    else "só fonte não-oficial deixou de mencionar; não é afirmação de ausência"
                ),
            ),
            motivo="ausência declarada pela fonte oficial" if oficiais else "sem menção",
        )

    # Havia valor, mas nenhum quote foi localizado: o valor é descartado.
    return Decisao(
        campo,
        SpecField.vazio(
            Status.NAO_VERIFICADO,
            sources_checked=fontes,
            notes=(
                f"{len(descartadas)} valor(es) descartado(s): o trecho citado não foi "
                "localizado no texto salvo da fonte. Quote guardado para auditoria."
            ),
        ),
        motivo="grounding falhou em todas as observações",
        descartadas=descartadas,
        localizacoes=localizacoes,
    )


def _nota(
    principal: list[Observacao],
    grupos: list[list[Observacao]],
    descartadas: list[Observacao],
) -> str | None:
    partes = [o.notas for o in principal if o.notas]
    if len(grupos) > 1:
        valores = ", ".join(str(g[0].valor)[:40] for g in grupos)
        partes.append(f"fontes divergem: {valores}")
    if descartadas:
        partes.append(
            f"{len(descartadas)} contestação(ões) ou valor(es) sem suporte; não publicado(s)"
        )
    return " · ".join(dict.fromkeys(partes)) or None


def decidir_todos(
    observacoes_por_campo: dict[str, list[Observacao]],
    *,
    textos: dict[str, str],
    campos: list[str] | None = None,
    sources_checked: list[str] | None = None,
) -> dict[str, Decisao]:
    """Decide todos os campos pedidos. Campo sem observação vira `nao_encontrado`."""
    alvo = campos or sorted(observacoes_por_campo)
    return {
        campo: decidir(
            campo,
            observacoes_por_campo.get(campo, []),
            textos=textos,
            sources_checked=sources_checked,
        )
        for campo in alvo
    }
