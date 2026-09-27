"""`specradar eval` — o oráculo do projeto.

Roda o gabarito contra o pipeline em modo replay e escreve `reports/eval.json` e
`reports/eval.md` com as 9 métricas de `docs/09_EVAL_E_GABARITO.md`.

Funciona desde o primeiro dia, mesmo com o pipeline vazio: sem `pipeline.run`, cada
veículo recebe `empty_spec()` e as métricas saem zeradas. Isso é de propósito — assim
toda WP de pipeline nasce medida, e o número que sobe é a prova de que a WP funcionou.

Honestidade das métricas (regra do projeto, não detalhe de implementação):

* métrica sem denominador aparece com `n = 0` e valor `null`, nunca com um zero que
  parece resultado;
* `pendente_coleta` do gabarito **não** conta como erro do pipeline;
* subcampo `None` no gabarito não é avaliado (`docs/09`), e o relatório lista o que
  ficou de fora para que a exclusão seja visível.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline import llm
from pipeline.eval.compare import ResultadoValor, comparar_qualquer, grounding
from pipeline.eval.gabarito import ExpectedField, Gabarito, Vehicle, carregar_gabarito
from pipeline.eval.mapping import status_compativel
from pipeline.schema import SpecField, StandardSpec, empty_spec
from pipeline.store import fontes_de, snapshots_de, textos_de

ROOT = Path(__file__).resolve().parent.parent.parent
NL = chr(10)


# --------------------------------------------------------------------------- métrica
@dataclass
class Metrica:
    """Um número com o denominador visível. `valor` é `None` quando `n == 0`."""

    nome: str
    acertos: float = 0.0
    n: int = 0
    meta: str = ""
    detalhe: str = ""

    @property
    def valor(self) -> float | None:
        return None if self.n == 0 else round(self.acertos / self.n, 4)

    def conta(self, ok: bool) -> None:
        self.n += 1
        self.acertos += 1 if ok else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "valor": self.valor,
            "acertos": round(self.acertos, 4),
            "n": self.n,
            "meta": self.meta,
            **({"detalhe": self.detalhe} if self.detalhe else {}),
        }


#: De onde veio a evidência que sustenta o valor — e o quanto isso é independente do
#: gabarito. A distinção não é cosmética: ela responde "esse 0,95 mede o pipeline ou
#: mede o pipeline se lembrando de onde o gabarito veio?".
#:
#: * `independente` — captura de **página oficial**, **PDF**, **tabela do PBE** ou
#:   **resposta da API FIPE**. O gabarito foi escrito por uma pessoa lendo essas fontes,
#:   mas o texto que o pipeline lê é a fonte, não a anotação;
#: * `derivada_do_gabarito` — `registro_de_evidencia`. São os JSON da coleta de
#:   01/09/2026 (`gabarito/raw/manus_*.json`), a **mesma** rodada que produziu o
#:   `gabarito_v1.json`. `scripts/build_fixtures.py` os transforma em fixture porque
#:   parte das páginas não foi salva em HTML, e sem eles campos legítimos ficariam sem
#:   texto para grounding em replay. Continua sendo texto coletado de verdade — mas
#:   acertar contra ele é menos independente, e o relatório tem de dizer isso;
#: * `sem_evidencia` — o pipeline não afirmou valor, ou afirmou sem evidência (que o
#:   grounding já reprova em outra métrica).
FONTE_INDEPENDENTE = "independente"
FONTE_DERIVADA_DO_GABARITO = "derivada_do_gabarito"
SEM_EVIDENCIA = "sem_evidencia"

#: Tipos de snapshot que **derivam** da mesma coleta que produziu o gabarito.
TIPOS_DERIVADOS_DO_GABARITO = ("registro_de_evidencia",)


@dataclass
class ResultadoCampo:
    caminho: str
    origem: str
    status_gabarito: str
    status_pipeline: str
    esperado: Any
    obtido: Any
    valor_ok: bool | None
    status_ok: bool | None
    grounding_ok: bool | None
    modo: str
    detalhe: str
    independencia: str = SEM_EVIDENCIA
    """`independente`, `derivada_do_gabarito` ou `sem_evidencia`. Ver as constantes."""
    fonte_do_valor: str = ""
    """O `source_id` da evidência principal, para a conta poder ser reconferida."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "caminho": self.caminho,
            "origem": self.origem,
            "independencia": self.independencia,
            "fonte_do_valor": self.fonte_do_valor,
            "status_gabarito": self.status_gabarito,
            "status_pipeline": self.status_pipeline,
            "esperado": self.esperado,
            "obtido": self.obtido,
            "valor_ok": self.valor_ok,
            "status_ok": self.status_ok,
            "grounding_ok": self.grounding_ok,
            "modo": self.modo,
            "detalhe": self.detalhe,
        }


@dataclass
class ResultadoVeiculo:
    id: str
    descricao: str
    papel: str
    metricas: dict[str, Metrica] = field(default_factory=dict)
    campos: list[ResultadoCampo] = field(default_factory=list)
    nao_avaliados: list[str] = field(default_factory=list)
    fontes_bloqueadas: list[str] = field(default_factory=list)
    tempo_s: float = 0.0
    custo_brl: float = 0.0
    uso: dict[str, Any] = field(default_factory=dict)
    """O gasto de LLM **medido** neste veículo: chamadas, tokens, custo e provedor.

    Existe porque `custo_brl` era `0.0` fixo. Com `LLM_FAKE=1` isso é verdade — não há
    chamada. Com modelo real era uma **estimativa de zero** publicada como fato, que é o
    número que este projeto não imprime."""
    observacoes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "descricao": self.descricao,
            "papel": self.papel,
            "metricas": {k: v.to_dict() for k, v in self.metricas.items()},
            "time_per_vehicle_s": round(self.tempo_s, 3),
            "cost_per_vehicle_brl": round(self.custo_brl, 4),
            "llm": self.uso,
            "nao_avaliados": self.nao_avaliados,
            "fontes_bloqueadas": self.fontes_bloqueadas,
            "observacoes": self.observacoes,
            "campos": [c.to_dict() for c in self.campos],
        }


NOMES_METRICAS = (
    ("field_accuracy", "≥ 0,90"),
    ("status_fidelity", "≥ 0,90"),
    ("hallucination_rate", "0"),
    ("grounding_rate", "1,0"),
    ("coverage", "1,0"),
    ("resolver_accuracy", "1,0"),
    ("slide_divergences_found", "4/4"),
)


def _metricas_vazias() -> dict[str, Metrica]:
    return {nome: Metrica(nome, meta=meta) for nome, meta in NOMES_METRICAS}


# ----------------------------------------------------------------- execução do pipeline
def executar_pipeline(veiculo: Vehicle, *, replay: bool = True) -> StandardSpec:
    """Roda o pipeline para um veículo do gabarito.

    Enquanto a WP-12 não existe, devolve `empty_spec()` — todos os campos presentes,
    todos `nao_encontrado`, nenhum valor. É o ponto de partida honesto: o eval mede um
    pipeline que não afirma nada, e cada WP move o número.
    """
    try:
        from pipeline.run import run as pipeline_run
    except ImportError:
        return empty_spec(job_id=f"eval:{veiculo.id}")
    return pipeline_run(  # pragma: no cover - ativa a partir da WP-12
        marca=veiculo.marca,
        modelo=veiculo.modelo,
        versao=veiculo.versao,
        replay=replay,
        version_id=veiculo.id,
    )


def _textos_fora_de_snapshot(version_id: str) -> dict[str, str]:
    """`{source_id: texto}` das fontes que o pipeline lê **sem** passar por `snapshots/`.

    Hoje há uma só: a referência interna (o deck comercial que o cliente entrega). Ela
    não é captura de página, então não vira snapshot — mas é fonte de extração como
    qualquer outra, e o valor que sai dela carrega citação literal como qualquer outro.

    Import tardio, pelo mesmo motivo de `executar_pipeline`: o eval tem de continuar
    importável num ambiente sem o pipeline montado.
    """
    try:
        from pipeline.run import referencia_interna
    except ImportError:  # pragma: no cover - ambiente sem o pipeline
        return {}
    documento = referencia_interna(version_id)
    return {documento.source_id: documento.texto} if documento is not None else {}


def _valor_e_status(spec: StandardSpec, caminho: str) -> tuple[Any, str, SpecField | None]:
    campo = spec.get(caminho)
    if campo is None:
        return None, "pendente", None
    return campo.value, str(campo.status), campo


# ------------------------------------------------------------------- avaliação de campo
def _classificar_independencia(campo: SpecField | None, tipos: dict[str, str]) -> tuple[str, str]:
    """`(independencia, source_id)` da evidência principal do campo.

    Ver `FONTE_INDEPENDENTE` para o porquê. `tipos` é `{source_id: tipo do snapshot}`.
    """
    if campo is None or not campo.evidences:
        return SEM_EVIDENCIA, ""
    fonte = campo.evidences[0].snapshot_id or ""
    tipo = tipos.get(fonte, "")
    if tipo in TIPOS_DERIVADOS_DO_GABARITO:
        return FONTE_DERIVADA_DO_GABARITO, fonte
    return FONTE_INDEPENDENTE, fonte


def _avalia_campo(
    esperado: ExpectedField,
    spec: StandardSpec,
    textos: dict[str, str],
    tipos: dict[str, str] | None = None,
) -> tuple[ResultadoCampo, dict[str, bool | None]]:
    obtido, status_pipeline, campo = _valor_e_status(spec, esperado.caminho)
    independencia, fonte_do_valor = _classificar_independencia(campo, tipos or {})

    valor_ok: bool | None = None
    resultado: ResultadoValor | None = None
    if esperado.avalia_valor:
        resultado = comparar_qualquer(esperado.campo, esperado.valores_esperados, obtido)
        valor_ok = resultado.igual

    status_ok: bool | None = None
    if esperado.avalia_status:
        status_ok = status_compativel(esperado.status, status_pipeline)

    # grounding: só faz sentido quando o pipeline afirmou algo
    g_ok: bool | None = None
    if obtido is not None and campo is not None:
        g_ok = any(
            grounding(ev.quote, textos.get(ev.snapshot_id or "", "")).ok
            or any(grounding(ev.quote, t).ok for t in textos.values())
            for ev in campo.evidences
        )

    # alucinação: gabarito vazio e pipeline com valor
    alucinou = esperado.status in {"nao_encontrado", "nao_disponivel"} and obtido is not None

    # cobertura: o pipeline se pronunciou sobre o campo?
    coberto = status_pipeline != "pendente"

    return (
        ResultadoCampo(
            caminho=esperado.caminho,
            origem=esperado.origem,
            status_gabarito=esperado.status,
            status_pipeline=status_pipeline,
            esperado=esperado.valor,
            obtido=obtido,
            valor_ok=valor_ok,
            status_ok=status_ok,
            grounding_ok=g_ok,
            modo=resultado.modo if resultado else "",
            detalhe=resultado.detalhe if resultado else "",
            independencia=independencia,
            fonte_do_valor=fonte_do_valor,
        ),
        {
            "valor": valor_ok,
            "status": status_ok,
            "grounding": g_ok,
            "alucinou": alucinou
            if esperado.status in {"nao_encontrado", "nao_disponivel"}
            else None,
            "coberto": coberto,
        },
    )


def _avalia_resolvedor(veiculo: Vehicle, spec: StandardSpec) -> tuple[bool, str]:
    """GR-Sport tem de virar `versao_inexistente` com `SRX Plus AT` nas alternativas."""
    resolucao = spec.meta.version_resolution
    if veiculo.e_caso_negativo:
        esperado = veiculo.resultado_esperado
        assert esperado is not None
        if resolucao.status != esperado.status:
            return False, f"status={resolucao.status!r}, esperado {esperado.status!r}"
        sugestao = esperado.sugestao_equivalente or ""
        if sugestao and not any(sugestao in alt for alt in resolucao.alternatives):
            return False, f"alternativas {resolucao.alternatives} sem {sugestao!r}"
        return True, "versao_inexistente com a alternativa correta"
    if resolucao.status != "encontrada":
        return False, f"status={resolucao.status!r}, esperado 'encontrada'"
    return True, "encontrada"


def _avalia_divergencias_do_slide(
    veiculo: Vehicle, spec: StandardSpec
) -> tuple[int, int, list[str]]:
    """`slide_divergences_found`: 2 divergências slide×fonte + 2 rpm ausentes = 4/4.

    Só se aplica ao veículo Ford de referência, que é o único com `slide_ford`
    preenchido no gabarito.
    """
    alvos: list[tuple[ExpectedField, str]] = []
    for campo in veiculo.campos:
        if campo.status == "divergente" and campo.tem_slide:
            alvos.append((campo, "divergente"))
        elif campo in veiculo.campos_ausentes_em_fonte_publica:
            alvos.append((campo, "ausente_em_fonte_publica"))

    achados: list[str] = []
    for campo, tipo in alvos:
        obtido = spec.get(campo.caminho)
        if obtido is None:
            continue
        if tipo == "divergente" and str(obtido.status) == "divergente" and obtido.conflicts:
            achados.append(
                f"{campo.caminho}: divergência exposta com {len(obtido.conflicts) + 1} valores"
            )
        elif tipo == "ausente_em_fonte_publica" and str(obtido.status) in {
            "nao_encontrado",
            "nao_disponivel",
        }:
            achados.append(f"{campo.caminho}: ausência em fonte pública reportada")
    return len(achados), len(alvos), achados


# --------------------------------------------------------------------------- por veículo
def avaliar_veiculo(veiculo: Vehicle, *, replay: bool = True) -> ResultadoVeiculo:
    resultado = ResultadoVeiculo(
        id=veiculo.id,
        descricao=f"{veiculo.marca} {veiculo.modelo} {veiculo.versao} {veiculo.ano_modelo}",
        papel=veiculo.papel,
        metricas=_metricas_vazias(),
        nao_avaliados=list(veiculo.nao_avaliados),
    )

    inicio = time.perf_counter()
    with llm.medindo() as medida:
        spec = executar_pipeline(veiculo, replay=replay)
    resultado.tempo_s = time.perf_counter() - inicio
    resultado.uso = medida.to_dict()
    resultado.custo_brl = medida.custo_brl

    textos = textos_de(veiculo.id)
    # A referência interna (o deck comercial) **não** é snapshot — é documento entregue
    # pelo cliente, e por isso mora fora de `data/snapshots/`. Mas o pipeline extrai dela
    # como de qualquer fonte, e o valor que sai dali tem citação literal como qualquer
    # outro. Sem esta linha o eval não tinha o texto contra o qual conferir, e o campo
    # aparecia como **não groundeado** — `exterior.pneus_tipo` da Raptor, medido em
    # 12/09/2026: valor certo, citação certa, corpus do eval incompleto. A regra
    # inviolável é "nenhum valor sem evidência"; a métrica tem de enxergar a mesma
    # evidência que o pipeline enxergou, ou ela mede o eval, não o produto.
    for source_id, texto in _textos_fora_de_snapshot(veiculo.id).items():
        textos.setdefault(source_id, texto)
    # `{source_id: tipo}` — é o que separa captura de fonte de registro da coleta.
    tipos = {s.source_id: s.tipo for s in snapshots_de(veiculo.id)}
    bloqueadas = [f.url for f in fontes_de(veiculo.id) if f.status == "bloqueada"]
    resultado.fontes_bloqueadas = bloqueadas
    if bloqueadas:
        resultado.observacoes.append(
            f"{len(bloqueadas)} fonte(s) bloqueada(s) — status registrado, sem tentativa de burlar"
        )
    if not textos:
        resultado.observacoes.append("nenhum snapshot em replay para esta versão")

    m = resultado.metricas
    for esperado in veiculo.campos:
        campo_res, sinais = _avalia_campo(esperado, spec, textos, tipos)
        resultado.campos.append(campo_res)
        if sinais["valor"] is not None:
            m["field_accuracy"].conta(bool(sinais["valor"]))
        if sinais["status"] is not None:
            m["status_fidelity"].conta(bool(sinais["status"]))
        if sinais["grounding"] is not None:
            m["grounding_rate"].conta(bool(sinais["grounding"]))
        if sinais["alucinou"] is not None:
            m["hallucination_rate"].conta(bool(sinais["alucinou"]))
        m["coverage"].conta(bool(sinais["coberto"]))

    ok_resolver, motivo = _avalia_resolvedor(veiculo, spec)
    m["resolver_accuracy"].conta(ok_resolver)
    m["resolver_accuracy"].detalhe = motivo

    achados, total, descricoes = _avalia_divergencias_do_slide(veiculo, spec)
    if total:
        m["slide_divergences_found"].acertos = achados
        m["slide_divergences_found"].n = total
        m["slide_divergences_found"].detalhe = "; ".join(descricoes) or "nenhuma detectada"

    # O custo é o **medido** em `avaliar_veiculo`, não uma constante. Com `LLM_FAKE=1` ele
    # dá zero porque nenhuma chamada acontece — zero de verdade, e não estimativa de zero.
    if os.environ.get("LLM_FAKE", "") in {"1", "true", "True"}:
        resultado.observacoes.append(
            f"LLM_FAKE=1 — {resultado.uso.get('chamadas', 0)} leitura(s) de fixture, "
            "nenhuma chamada de rede, custo real zero"
        )
    elif resultado.uso.get("chamadas"):
        contas = ", ".join(f"{k}: {v}" for k, v in resultado.uso.get("por_provedor", {}).items())
        resultado.observacoes.append(
            f"modelo real — {resultado.uso['chamadas']} chamada(s) ({contas}), "
            f"{resultado.uso['tokens_entrada']}→{resultado.uso['tokens_saida']} tokens "
            f"({resultado.uso['tokens_de_raciocinio']} de raciocínio), "
            f"R$ {resultado.custo_brl:.4f}"
        )

    return resultado


# ---------------------------------------------------------------------------- agregação
def agregar(resultados: list[ResultadoVeiculo]) -> dict[str, Metrica]:
    """Agrega por soma de acertos e de denominadores — não por média de médias.

    Média de médias daria peso igual a um veículo com 27 campos e a um com 16.
    """
    total = _metricas_vazias()
    for r in resultados:
        for nome, metrica in r.metricas.items():
            total[nome].acertos += metrica.acertos
            total[nome].n += metrica.n
    return total


def _fmt(valor: float | None) -> str:
    return "—" if valor is None else f"{valor:.3f}".replace(".", ",")


def _atingiu(nome: str, metrica: Metrica) -> str:
    v = metrica.valor
    if v is None:
        return "—"
    limites = {
        "field_accuracy": lambda x: x >= 0.90,
        "status_fidelity": lambda x: x >= 0.90,
        "hallucination_rate": lambda x: x == 0.0,
        "grounding_rate": lambda x: x == 1.0,
        "coverage": lambda x: x == 1.0,
        "resolver_accuracy": lambda x: x == 1.0,
        "slide_divergences_found": lambda x: x == 1.0,
    }
    teste = limites.get(nome)
    if teste is None:
        return "—"
    return "OK" if teste(v) else "FALTA"


def relatorio_md(
    gab: Gabarito, resultados: list[ResultadoVeiculo], agregado: dict[str, Metrica]
) -> str:
    linhas: list[str] = []
    ap = linhas.append
    ap("# Relatório do eval — SpecRadar")
    ap("")
    ap(f"Gabarito `{gab.versao}` (gerado em {gab.gerado_em}) · {len(gab.veiculos)} veículos")
    ap("")
    ap("Cada métrica aparece com o **denominador visível**. Métrica sem denominador sai")
    ap("como `—` e não como zero: não medimos o que não deu para medir.")
    ap("")
    ap("## Agregado")
    ap("")
    ap("| Métrica | Valor | Acertos / n | Meta | |")
    ap("|---|---:|---:|---|---|")
    for nome, _ in NOMES_METRICAS:
        met = agregado[nome]
        ap(
            f"| `{nome}` | {_fmt(met.valor)} | {met.acertos:g} / {met.n} "
            f"| {met.meta} | {_atingiu(nome, met)} |"
        )
    tempo = sum(r.tempo_s for r in resultados)
    custo = sum(r.custo_brl for r in resultados)
    n = max(len(resultados), 1)
    ap(f"| `time_per_vehicle_s` | {tempo / n:.3f} | {tempo:.3f} s no total | reportar | — |")
    ap(f"| `cost_per_vehicle_brl` | {custo / n:.4f} | R$ {custo:.4f} no total | reportar | — |")
    ap("")

    ap("## De onde vem cada acerto — independente × derivado do gabarito")
    ap("")
    ap("Um `field_accuracy` alto responde a pergunta certa só se disser **contra o que**")
    ap("ele acertou. Duas populações, e elas não valem o mesmo:")
    ap("")
    ap("- **independente** — o valor saiu de captura de página oficial, PDF, tabela do")
    ap("  PBE/Inmetro ou resposta da API FIPE. Uma pessoa leu essas fontes para escrever o")
    ap("  gabarito, mas o texto que o pipeline lê é a **fonte**, não a anotação;")
    ap("- **derivado do gabarito** — o valor saiu de `registro_de_evidencia`: os JSON da")
    ap("  coleta de 01/09/2026 (`gabarito/raw/manus_*.json`), a **mesma** rodada que")
    ap("  produziu o `gabarito_v1.json`. Eles são fixture porque parte das páginas não foi")
    ap("  salva em HTML, e sem eles campos legítimos ficariam sem texto para grounding em")
    ap("  replay. Continua sendo texto coletado de verdade — mas acertar contra ele é")
    ap("  menos independente, e o número não deve esconder isso.")
    ap("")
    ap("| População | Campos medidos | Valor certo | field_accuracy |")
    ap("|---|---:|---:|---:|")
    for rotulo, chave in (
        ("independente", FONTE_INDEPENDENTE),
        ("derivado do gabarito", FONTE_DERIVADA_DO_GABARITO),
        ("sem evidência (pipeline não afirmou)", SEM_EVIDENCIA),
    ):
        medidos = [
            c
            for r in resultados
            for c in r.campos
            if c.valor_ok is not None and c.independencia == chave
        ]
        acertos = sum(1 for c in medidos if c.valor_ok)
        taxa = _fmt(acertos / len(medidos)) if medidos else "—"
        ap(f"| {rotulo} | {len(medidos)} | {acertos} | {taxa} |")
    ap("")
    por_fonte: dict[str, list[int]] = {}
    for r in resultados:
        for c in r.campos:
            if c.valor_ok is None or not c.fonte_do_valor:
                continue
            registro = por_fonte.setdefault(f"{c.fonte_do_valor} ({c.independencia})", [0, 0])
            registro[0] += int(bool(c.valor_ok))
            registro[1] += 1
    if por_fonte:
        ap("Por fonte, para a conta poder ser reconferida:")
        ap("")
        ap("| Fonte da evidência | acertos / medidos |")
        ap("|---|---:|")
        for fonte in sorted(por_fonte, key=lambda k: (-por_fonte[k][1], k)):
            acertos, medidos = por_fonte[fonte]
            ap(f"| `{fonte}` | {acertos} / {medidos} |")
        ap("")

    ap("## Por veículo")
    ap("")
    ap("| Veículo | papel | field_acc | status_fid | halluc | grounding | coverage |")
    ap("|---|---|---:|---:|---:|---:|---:|")
    for r in resultados:
        m = r.metricas
        ap(
            f"| {r.descricao} | {r.papel} | {_fmt(m['field_accuracy'].valor)} "
            f"| {_fmt(m['status_fidelity'].valor)} | {_fmt(m['hallucination_rate'].valor)} "
            f"| {_fmt(m['grounding_rate'].valor)} | {_fmt(m['coverage'].valor)} |"
        )
    ap("")

    ap("## Resolvedor de versão")
    ap("")
    for r in resultados:
        met = r.metricas["resolver_accuracy"]
        marca = "OK" if met.valor == 1.0 else "FALHOU"
        ap(f"- **{r.descricao}** — {marca}: {met.detalhe}")
    ap("")

    ford = next((r for r in resultados if r.metricas["slide_divergences_found"].n), None)
    if ford:
        met = ford.metricas["slide_divergences_found"]
        ap("## Slide interno × fonte pública (Fogo Amigo)")
        ap("")
        ap(f"{met.acertos:g} de {met.n} apontadas. {met.detalhe}")
        ap("")

    faltas = [
        (r.descricao, c)
        for r in resultados
        for c in r.campos
        if c.valor_ok is False or c.status_ok is False
    ]
    if faltas:
        ap("## Campos em falta")
        ap("")
        ap("| Veículo | Campo | Gabarito | Pipeline | Esperado | Obtido | Motivo |")
        ap("|---|---|---|---|---|---|---|")
        for descricao, c in faltas[:120]:
            ap(
                f"| {descricao} | `{c.caminho}` | {c.status_gabarito} | {c.status_pipeline} "
                f"| {str(c.esperado)[:40]} | {str(c.obtido)[:40]} | {c.detalhe or c.modo} |"
            )
        if len(faltas) > 120:
            ap("")
            omitidas = len(faltas) - 120
            ap(f"_{omitidas} linhas omitidas; a lista completa está em `reports/eval.json`._")
        ap("")

    nao_avaliados = [(r.descricao, x) for r in resultados for x in r.nao_avaliados]
    if nao_avaliados:
        ap("## Fora da avaliação (visível de propósito)")
        ap("")
        ap("Subcampos que o gabarito registra e o schema canônico não tem. Não contam como")
        ap("erro nem como acerto — e ficam listados para que a exclusão nunca seja silenciosa.")
        ap("")
        for descricao, x in nao_avaliados:
            ap(f"- {descricao}: `{x}`")
        ap("")

    bloqueadas = [(r.descricao, u) for r in resultados for u in r.fontes_bloqueadas]
    if bloqueadas:
        ap("## Fontes bloqueadas")
        ap("")
        ap("Bloqueio virou status. Nenhuma tentativa de burlar anti-bot (`docs/12` §3.12).")
        ap("")
        for descricao, url in bloqueadas:
            ap(f"- {descricao}: {url}")
        ap("")

    observacoes = {o for r in resultados for o in r.observacoes}
    if observacoes:
        ap("## Observações")
        ap("")
        for o in sorted(observacoes):
            ap(f"- {o}")
        ap("")

    return "\n".join(linhas) + "\n"


# -------------------------------------------------------------------------------- main
def rodar(
    *,
    gabarito: str | Path = "gabarito/gabarito_v1.json",
    replay: bool = True,
    veiculo: str | None = None,
) -> tuple[dict[str, Any], Gabarito, list[ResultadoVeiculo], dict[str, Metrica]]:
    """Roda o eval uma vez e devolve o dict do JSON mais o material do relatório.

    Com `replay=True`, liga `REPLAY_MODE=1` no processo **antes** de tocar no pipeline:
    o eval promete determinismo a tudo que roda por baixo dele, inclusive ao
    `pipeline.run` da WP-12. Sem isso, `--replay` seria uma flag decorativa e o leitor
    de snapshots iria procurar em `data/snapshots/` (vazio), zerando o grounding em
    silêncio — foi exatamente o que aconteceu na primeira execução.
    """
    if replay:
        os.environ["REPLAY_MODE"] = "1"
    gab = carregar_gabarito(gabarito)
    veiculos = [gab.por_id(veiculo)] if veiculo else list(gab.veiculos)
    resultados = [avaliar_veiculo(v, replay=replay) for v in veiculos]
    agregado = agregar(resultados)
    n = max(len(resultados), 1)
    dados = {
        "gabarito": {
            "versao": gab.versao,
            "gerado_em": gab.gerado_em,
            "arquivo": str(gab.caminho),
        },
        "replay": replay,
        "llm_fake": os.environ.get("LLM_FAKE", "") in {"1", "true", "True"},
        "aggregate": {
            **{nome: met.to_dict() for nome, met in agregado.items()},
            "time_per_vehicle_s": round(sum(r.tempo_s for r in resultados) / n, 3),
            "cost_per_vehicle_brl": round(sum(r.custo_brl for r in resultados) / n, 4),
        },
        # atalho no topo: o portão de 11/09 e o CI leem daqui
        "field_accuracy": agregado["field_accuracy"].valor,
        "vehicles": [r.to_dict() for r in resultados],
    }
    return dados, gab, resultados, agregado


def main(
    *,
    gabarito: str = "gabarito/gabarito_v1.json",
    replay: bool = True,
    saida_json: str = "reports/eval.json",
    saida_md: str = "reports/eval.md",
    veiculo: str | None = None,
) -> int:
    dados, gab, resultados, agregado = rodar(gabarito=gabarito, replay=replay, veiculo=veiculo)

    caminho_json = ROOT / saida_json
    caminho_md = ROOT / saida_md
    caminho_json.parent.mkdir(parents=True, exist_ok=True)
    caminho_json.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2) + NL,
        encoding="utf-8",
        newline=NL,
    )
    caminho_md.write_text(relatorio_md(gab, resultados, agregado), encoding="utf-8", newline=NL)

    print(f"eval: {len(resultados)} veículo(s) · gabarito {gab.versao}")
    for nome, _ in NOMES_METRICAS:
        met = agregado[nome]
        print(f"  {nome:26} {_fmt(met.valor):>7}  ({met.acertos:g}/{met.n})  meta {met.meta}")
    print(f"  {'time_per_vehicle_s':26} {dados['aggregate']['time_per_vehicle_s']:>7}")
    print(f"relatórios: {saida_json} · {saida_md}")
    return 0
