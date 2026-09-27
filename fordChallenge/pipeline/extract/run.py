"""Extração de um documento: fast-path primeiro, LLM só no que sobrou.

A ordem não é otimização, é política. O fast-path (`fastpath.py`) resolve por regex os
campos com unidade explícita, e o **trecho casado é a evidência** — grounding automático,
custo zero, determinismo total. Só o que ele não resolve vai ao modelo, e com o
`evidence_quote` obrigatório. `docs/12` §6.8: "campos resolvidos pelo fast-path não vão
ao LLM".

O que sai daqui é uma lista de :class:`Candidato` — valor + evidência + de onde veio.
Escolher entre candidatos do mesmo campo **não** é papel deste módulo: é da reconciliação
(WP-12), que precisa ver todos para poder marcar `divergente`. Filtrar aqui esconderia
divergência, que é justamente o que o produto promete mostrar.

Escalonamento (`docs/05`): mais de 3 tabelas, ou ≥ 30% de campos nulos na primeira
passada, e a segunda usa o modelo grande — com o motivo registrado no log e no resultado.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pipeline import llm
from pipeline.extract import fastpath, prompt
from pipeline.parse.html import dividir_em_blocos

if TYPE_CHECKING:
    from pipeline.research.reading_state import EstadoLeitura

log = logging.getLogger(__name__)

#: Tamanho de bloco em caracteres. `docs/05` fala em ~12k tokens; ~4 chars por token em
#: português, com margem para o prompt.
MAX_CHARS_POR_BLOCO = 40_000


@dataclass
class Candidato:
    """Um valor extraído de uma fonte, com tudo que a reconciliação precisa saber."""

    campo: str
    valor: Any
    quote: str
    origem: str
    """`fastpath:<regra>` ou `llm:<modelo>`."""
    unidade: str | None = None
    valor_bruto: str = ""
    source_id: str = ""
    source_text: str = ""
    url: str = ""
    tier: int = 5
    captured_at: str = ""
    pagina: int | None = None
    notas: str = ""
    de_celula: bool = False
    """Veio da **celula** da coluna da versao, nao do texto corrido da fonte.

    Vale mais que o texto numa fonte tabular, e `pipeline/reconcile.py` usa isto para
    decidir: a linha de uma ficha percorre todas as versoes, a celula e de uma.
    """

    @property
    def do_fastpath(self) -> bool:
        return self.origem.startswith("fastpath")


@dataclass
class ResultadoExtracao:
    """O que a extração de um documento produziu, e o que ela custou."""

    candidatos: list[Candidato] = field(default_factory=list)
    campos_alvo: tuple[str, ...] = ()
    usos: list[llm.Uso] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    escalou: bool = False
    motivo_do_escalonamento: str = ""
    leitura: dict[str, Any] = field(default_factory=dict)
    """Progresso opcional por bloco; conclusão de leitura não é aprovação de valores."""

    @property
    def campos_resolvidos(self) -> set[str]:
        return {c.campo for c in self.candidatos}

    @property
    def campos_do_fastpath(self) -> set[str]:
        return {c.campo for c in self.candidatos if c.do_fastpath}

    @property
    def fastpath_rate(self) -> float | None:
        """Fração dos campos-alvo resolvida sem LLM (`docs/12` §6.8)."""
        if not self.campos_alvo:
            return None
        return len(self.campos_do_fastpath & set(self.campos_alvo)) / len(self.campos_alvo)

    @property
    def custo_brl(self) -> float:
        return round(sum(u.custo_brl for u in self.usos), 6)

    @property
    def tokens(self) -> tuple[int, int]:
        return (
            sum(u.tokens_entrada for u in self.usos),
            sum(u.tokens_saida for u in self.usos),
        )

    def por_campo(self, campo: str) -> list[Candidato]:
        return [c for c in self.candidatos if c.campo == campo]

    def to_dict(self) -> dict[str, Any]:
        return {
            "campos_alvo": list(self.campos_alvo),
            "campos_resolvidos": sorted(self.campos_resolvidos),
            "fastpath_rate": self.fastpath_rate,
            "custo_brl": self.custo_brl,
            "tokens_entrada": self.tokens[0],
            "tokens_saida": self.tokens[1],
            "escalou": self.escalou,
            "motivo_do_escalonamento": self.motivo_do_escalonamento,
            "avisos": self.avisos,
            "leitura": self.leitura,
            "candidatos": [
                {
                    "campo": c.campo,
                    "valor": c.valor,
                    "quote": c.quote,
                    "origem": c.origem,
                    "unidade": c.unidade,
                    "source_id": c.source_id,
                    "tier": c.tier,
                    "notas": c.notas,
                }
                for c in self.candidatos
            ],
        }


@dataclass
class Documento:
    """Um documento pronto para extração, com a proveniência que o acompanha."""

    texto: str
    source_id: str = ""
    url: str = ""
    tier: int = 5
    captured_at: str = ""
    celulas: tuple = ()
    """Células já recortadas para a versão alvo (`version_slicer`)."""
    n_tabelas: int = 0
    multiversao: bool = False
    sha256_original: str = ""
    parser_version: str = ""


def _identidade_tabular(documento: Documento, target):
    """Confere contexto documental e mecânica/ano da coluna separadamente."""
    from pipeline.ground import normalize_texto
    from pipeline.identity import (
        Applicability,
        IdentityAssessment,
        VehicleTarget,
        _engines,
        assess,
    )
    from pipeline.ontology import normalize
    from pipeline.parse.version_slicer import coluna_da_versao

    shared = assess(
        VehicleTarget(target.marca, target.modelo, "", None, mercado=target.mercado),
        documento.texto,
        url=documento.url,
    )
    if shared.status != Applicability.COMPATIBLE:
        return shared
    if not documento.celulas:
        return IdentityAssessment(Applicability.INSUFFICIENT, ("coluna_sem_celulas",))

    # Os cabeçalhos vêm da geometria, não do pedido. Uma célula compartilhada pode
    # listar outras versões; apenas um cabeçalho compatível com o nome do alvo vale.
    headers = set()
    normalized_source = normalize_texto(documento.texto)
    for cell in documento.celulas:
        covered = list(getattr(cell, "versoes_cobertas", ()))
        index = coluna_da_versao(["Versão", *covered], target.versao)
        if index is None or normalize_texto(covered[index - 1]) not in normalized_source:
            return IdentityAssessment(
                Applicability.INSUFFICIENT, ("coluna_sem_cabecalho_inequivoco_da_versao",)
            )
        headers.add(covered[index - 1])
    scoped = (
        "\n".join(sorted(headers))
        + "\n"
        + "\n".join(f"{c.rotulo}: {c.valor}" for c in documento.celulas)
    )

    column = assess(target, scoped, url=documento.url)
    if not column.observed.get("anos_modelo"):
        # MY global só vem do cabeçalho anterior à tabela. Ano da coluna vizinha,
        # copyright ou captura não se transforma no ano da configuração selecionada.
        labels = {normalize(c.rotulo).strip() for c in documento.celulas if c.rotulo}
        prefix = []
        for line in documento.texto.splitlines():
            clean = normalize(line).strip("#* |-\t")
            if (
                "|" in line
                or re.match(r"^vers(?:ao|oes)\b", clean)
                or any(re.match(re.escape(label) + r"(?:\s|:|$)", clean) for label in labels)
            ):
                break
            if not _engines(line) and not re.search(r"\b(?:cambio|transmissao|tracao)\b", clean):
                prefix.append(line)
        column = assess(target, "\n".join(prefix) + "\n" + scoped, url=documento.url)

    # Marca/modelo/mercado foram comprovados pelo documento completo. A coluna deve
    # sustentar todo o restante, inclusive o MY; não concatenamos valores da entrada.
    # `modelo_nao_comprovado` é a forma **forte** do mesmo "ausente" — dispara quando a
    # URL também não cita o modelo (comum em CDN por hash, como a Hilux em
    # media.toyota.com.br/<uuid>.pdf) — e precisa da mesma exceção, ou a coluna certa é
    # rejeitada por um sinal que o design deste filtro já considerava irrelevante aqui.
    ignored = {"identidade_ausente:" + name for name in ("marca", "modelo", "mercado")}
    ignored.add("modelo_nao_comprovado")
    reasons = tuple(reason for reason in column.reasons if reason not in ignored)
    state = (
        Applicability.COMPATIBLE
        if not reasons
        else Applicability.INCOMPATIBLE
        if column.status == Applicability.INCOMPATIBLE
        else Applicability.INSUFFICIENT
    )
    return IdentityAssessment(state, reasons, column.observed)


def _do_fastpath(documento: Documento, campos: set[str]) -> list[Candidato]:
    # `de_celula` também é usado pelos pares rótulo/valor do texto corrido. Em uma
    # tabela multiversão esse sinal sozinho não prova que o valor veio da coluna alvo.
    if documento.multiversao:
        achados = []
        for cell in documento.celulas:
            found = fastpath.extrair_de_celulas([cell], campos=campos, texto=documento.texto)
            if not found:
                # Valores com unidade ("250 cv") usam a mesma regra de pares, mas
                # restrita a UMA célula recortada. O trecho continua vindo da fonte.
                found = fastpath.extrair_de_pares(f"{cell.rotulo}: {cell.valor}", campos=campos)
                for item in found:
                    item.quote = fastpath.quote_de_celula(str(cell.valor), documento.texto)
                    item.notas = f"linha «{cell.rotulo}» da tabela, página {cell.pagina}"
            achados.extend(found)
    else:
        achados = fastpath.extrair(
            documento.texto, celulas=documento.celulas, campos=campos
        ).achados
    return [
        Candidato(
            campo=a.campo,
            valor=a.valor,
            quote=a.quote,
            origem=f"fastpath:{a.regra}",
            unidade=a.unidade,
            valor_bruto=a.valor_bruto,
            source_id=documento.source_id,
            url=documento.url,
            tier=documento.tier,
            captured_at=documento.captured_at,
            notas=a.notas,
            de_celula=a.de_celula,
        )
        for a in achados
    ]


@dataclass(frozen=True)
class PlanoDeChamada:
    """Uma chamada de LLM que *seria* feita, sem fazê-la.

    Existe para o gravador de fixtures (`scripts/record_llm_fixtures.py`) poder calcular
    exatamente a mesma chave que o pipeline vai procurar. Sem isso, a fixture seria
    gravada com uma chave e lida com outra, e o modo `LLM_FAKE=1` passaria a "não achar
    fixture" sem ninguém entender por quê.
    """

    prompt: str
    campos: tuple[str, ...]
    modelo: str
    source_id: str
    chave: str


def montar_prompt(
    documento: Documento,
    campos: list[str],
    *,
    marca: str = "",
    modelo_veiculo: str = "",
    versao: str = "",
) -> str:
    """O prompt exato que o pipeline manda para uma fonte e um conjunto de campos."""
    tabelas = "\n".join(
        f"{c.rotulo}: {c.valor}" for c in documento.celulas if getattr(c, "rotulo", "")
    )
    return prompt.montar(
        texto=documento.texto,
        campos=campos,
        marca=marca,
        modelo=modelo_veiculo,
        versao=versao,
        fonte=documento.url or documento.source_id,
        tabelas=tabelas,
    )


def planejar_chamadas(
    documento: Documento,
    campos: set[str],
    *,
    marca: str = "",
    modelo_veiculo: str = "",
    versao: str = "",
) -> list[PlanoDeChamada]:
    """O que iria ao LLM para este documento, sem chamar nada.

    Só os campos que o fast-path **não** resolve entram, que é a mesma regra que
    `extrair_documento` aplica.
    """
    resolvidos = {c.campo for c in _do_fastpath(documento, campos)}
    faltando = sorted(campos - resolvidos)
    if not faltando:
        return []
    planos: list[PlanoDeChamada] = []
    for bloco in dividir_em_blocos(documento.texto, max_chars=MAX_CHARS_POR_BLOCO):
        parcial = Documento(
            texto=bloco,
            source_id=documento.source_id,
            url=documento.url,
            tier=documento.tier,
            captured_at=documento.captured_at,
            celulas=documento.celulas,
            n_tabelas=documento.n_tabelas,
        )
        corpo = montar_prompt(
            parcial, faltando, marca=marca, modelo_veiculo=modelo_veiculo, versao=versao
        )
        for modelo_llm in (llm.modelo_pequeno(), llm.modelo_grande()):
            planos.append(
                PlanoDeChamada(
                    prompt=corpo,
                    campos=tuple(faltando),
                    modelo=modelo_llm,
                    source_id=documento.source_id,
                    chave=llm.chave_de_fixture(modelo=modelo_llm, prompt=corpo, campos=faltando),
                )
            )
    return planos


#: Teto de tokens de saída de **uma passada de extração**. Medido, não escolhido.
#:
#: O default de `extrair_json` é 4096, e ele serve para pedido curto. Uma passada de
#: extração é outra coisa: 58 campos, cada um pedindo valor **e** `evidence_quote`
#: verbatim, sobre um documento inteiro. Medido em 13/09/2026, no mesmo documento da
#: Raptor (17.978 caracteres, prompt de 21.300):
#:
#: ==================  ==========  ==========  =================================
#: teto                kimi-k2.6   gemini-3.6  o que acontece com 4096
#: ==================  ==========  ==========  =================================
#: 4.096               falha       falha       Kimi nem começa a escrever (4095
#:                                             tokens de raciocínio); o Gemini
#:                                             escreve e é cortado no meio
#: 32.768              24.557 tok  9.833 tok   os dois respondem
#: ==================  ==========  ==========  =================================
#:
#: **Teto não é gasto.** Cobra-se o que o modelo produz, não o que foi permitido: subir
#: o teto não encarece quem responde curto. O que ele evita é a chamada que custa caro
#: (115 s e US$ 0,02 no Kimi) e volta sem nada — o pior negócio possível.
#:
#: `LLM_MAX_TOKENS` sobrepõe, para quem estiver num provedor com teto menor.
ORCAMENTO_DE_SAIDA = max(4096, int(os.environ.get("LLM_MAX_TOKENS") or 32768))


#: Quantos blocos de um documento podem ir ao modelo. Medido, e caro quando faltava.
#:
#: `extrair_documento` mandava **todos** os blocos, um por chamada. Numa página de coleta
#: (teto de 2 MB) isso dá 27 blocos de 40 mil caracteres — e foi o que aconteceu em
#: 13/09/2026: o Pesquisador gastou **54 chamadas de LLM em 2 páginas** para fechar 2 dos
#: 55 campos, R$ 1,77, e estourou a cota diária da conta no primeiro veículo dos cinco.
#:
#: Oito blocos são 320 mil caracteres — mais do que qualquer ficha técnica de verdade. O
#: que o teto corta é a página que trouxe o site inteiro junto, e ali a ficha não está no
#: bloco 20.
MAX_BLOCOS_AO_LLM = max(1, int(os.environ.get("LLM_MAX_BLOCOS") or 8))


def _blocos_que_valem(
    texto: str, faltando: list[str], teto: int | None = None
) -> tuple[list[str], int]:
    """Os blocos que vão ao modelo, em ordem de relevância, e quantos ficaram de fora.

    `teto` sobrepõe `MAX_BLOCOS_AO_LLM` para quem tem orçamento próprio: o Pesquisador lê
    **um** bloco por documento, porque paga cada chamada de um teto de quatro por pesquisa.

    **Ordem antes de teto.** Cortar os últimos de uma lista em ordem de leitura assume que
    a ficha técnica está no começo da página, e numa página de montadora ela costuma estar
    no fim — depois do menu, do banner e da galeria. A pontuação é grosseira de propósito:
    quantos **termos dos campos que faltam** o bloco menciona. Custa uma varredura de
    string e não chama ninguém.

    Empate mantém a ordem original (`sorted` é estável), então um documento pequeno — que
    cabe no teto — sai exatamente como antes.
    """
    limite = max(1, teto) if teto else MAX_BLOCOS_AO_LLM
    blocos = dividir_em_blocos(texto, max_chars=MAX_CHARS_POR_BLOCO)
    if len(blocos) <= limite:
        return blocos, 0

    from pipeline.ontology import carregar

    onto = carregar()
    querendo = set(faltando)
    termos = {
        t.lower()
        for entrada in onto.campos
        if entrada.campo_canonico in querendo
        for t in entrada.termos
        if len(t) >= 4
    }

    def nota(bloco: str) -> int:
        baixo = bloco.lower()
        return -sum(1 for termo in termos if termo in baixo)

    escolhidos = sorted(blocos, key=nota)[:limite]
    return escolhidos, len(blocos) - len(escolhidos)


def _do_llm(
    documento: Documento,
    campos: list[str],
    *,
    marca: str,
    modelo_veiculo: str,
    versao: str,
    modelo_llm: str | None,
) -> tuple[list[Candidato], llm.Uso | None, str, bool]:
    """Uma passada de LLM sobre um documento, para os campos pedidos."""
    if not campos:
        return [], None, "", True

    corpo = montar_prompt(
        documento, campos, marca=marca, modelo_veiculo=modelo_veiculo, versao=versao
    )
    resposta = llm.extrair_json(
        prompt=corpo,
        campos=campos,
        modelo=modelo_llm,
        sistema=prompt.SISTEMA,
        max_tokens=ORCAMENTO_DE_SAIDA,
    )
    if not resposta.ok:
        return [], resposta.uso, resposta.motivo, False

    candidatos: list[Candidato] = []
    for campo, bruto in resposta.dados.items():
        if campo not in campos or bruto is None:
            continue
        if not isinstance(bruto, dict):
            # resposta fora de forma: sem `evidence_quote` não há valor
            continue
        quote = str(bruto.get("evidence_quote") or "").strip()
        valor = bruto.get("value", bruto.get("raw_value"))
        if not quote or valor is None:
            # `docs/05`: nenhum valor sem evidência. Aqui o valor simplesmente não entra.
            continue
        candidatos.append(
            Candidato(
                campo=campo,
                valor=valor,
                quote=quote,
                origem=f"llm:{resposta.uso.modelo if resposta.uso else 'desconhecido'}",
                unidade=bruto.get("unit"),
                valor_bruto=str(bruto.get("raw_value") or ""),
                source_id=documento.source_id,
                url=documento.url,
                tier=documento.tier,
                captured_at=documento.captured_at,
            )
        )
    return candidatos, resposta.uso, resposta.motivo, True


def _extrair_retomavel(
    documento: Documento,
    campos: set[str],
    faltando: list[str],
    resultado: ResultadoExtracao,
    *,
    estado: EstadoLeitura,
    marca: str,
    modelo_veiculo: str,
    versao: str,
    ano_modelo: int | None,
    permitir_llm: bool,
    max_blocos: int | None,
    escalonar: bool,
    documento_sha256: str,
    parser_version: str,
    policy_version: str | None,
    configuracao_alvo: dict | None,
) -> ResultadoExtracao:
    from pipeline.ontology import carregar
    from pipeline.publication import POLICY_VERSION
    from pipeline.research.reading_state import (
        PARSER_VERSION,
        block_id,
        hash_text,
        pendente,
        resumo,
        tentativa,
    )

    blocks = dividir_em_blocos(documento.texto, max_chars=MAX_CHARS_POR_BLOCO)
    indexed = [(block_id(i, text), text) for i, text in enumerate(blocks)]
    models = {"small": llm.modelo_pequeno(), "large": llm.modelo_grande()}
    original_hash = documento_sha256 or documento.sha256_original or hash_text(documento.texto)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", original_hash):
        raise ValueError("hash SHA-256 original inválido para o estado de leitura")
    identidade = {
        "sha256_original": original_hash.lower(),
        "sha256_texto": hash_text(documento.texto),
        "source_id": documento.source_id,
        "url": documento.url,
        "alvo": {
            "marca": marca,
            "modelo": modelo_veiculo,
            "versao": versao,
            "ano_modelo": ano_modelo,
        },
        "configuracao_alvo": configuracao_alvo or {},
        "policy": policy_version if policy_version is not None else POLICY_VERSION,
        "parser": parser_version or documento.parser_version or PARSER_VERSION,
        "campos": sorted(campos),
        "campos_llm": faltando,
        "extrator": {
            "version": "resumable-extract-1",
            "max_chars": MAX_CHARS_POR_BLOCO,
            "prompt_sha256": hash_text(
                montar_prompt(
                    documento, faltando, marca=marca, modelo_veiculo=modelo_veiculo, versao=versao
                )
            ),
            "system_sha256": hash_text(prompt.SISTEMA),
            "modelos": models,
            "provedor": llm.provedor_atual(),
            "modo_fixture": llm.modo_fake(),
            "provedor_alternativo": os.environ.get("LLM_PROVIDER_ALT", ""),
            "modelo_alternativo": os.environ.get("LLM_MODEL_ALT", ""),
            "api_base_sha256": hash_text(llm.api_base()),
            "api_base_alt_sha256": hash_text(os.environ.get("LLM_API_BASE_ALT", "")),
            "orcamento_saida": ORCAMENTO_DE_SAIDA,
            "escalonar": escalonar,
            "n_tabelas": documento.n_tabelas,
        },
    }
    key, context = estado.contexto(identidade, [b for b, _ in indexed])
    terms = {
        term.lower()
        for entry in carregar().campos
        if entry.campo_canonico in faltando
        for term in entry.termos
        if len(term) >= 4
    }
    # Relevância é estável e calculada antes do teto; índices preservam duplicatas.
    indexed.sort(key=lambda item: -sum(term in item[1].lower() for term in terms))
    used: list[str] = []
    completed: list[str] = []
    failures: list[dict] = []
    limit = max(0, max_blocos) if max_blocos is not None else MAX_BLOCOS_AO_LLM
    for bid, text in indexed:
        phase = pendente(context, bid)
        while phase and permitir_llm and len(used) < limit:
            requested = context["escalonamentos"][bid] if phase == "large" else faltando
            task = f"{bid}:{phase}"
            used.append(task)
            parcial = Documento(
                texto=text,
                source_id=documento.source_id,
                url=documento.url,
                tier=documento.tier,
                captured_at=documento.captured_at,
                celulas=documento.celulas,
                n_tabelas=documento.n_tabelas,
            )
            try:
                candidates, usage, _reason, ok = _do_llm(
                    parcial,
                    requested,
                    marca=marca,
                    modelo_veiculo=modelo_veiculo,
                    versao=versao,
                    modelo_llm=models[phase],
                )
                failure_code = "provider_failure"
            except (TimeoutError, llm.SemProvedor) as exc:
                candidates, usage, ok = [], None, False
                failure_code = (
                    "timeout" if isinstance(exc, TimeoutError) else "provider_unavailable"
                )
            if usage:
                resultado.usos.append(usage)
            tentativa(context, task, ok=ok, motivo="success" if ok else failure_code)
            if not ok:
                failures.append({"bloco": bid, "passagem": phase, "motivo": failure_code})
                resultado.avisos.append(f"leitura pendente do bloco {bid}: {failure_code}")
                # Uma falha de conta/prazo não deve disparar todos os outros blocos.
                break
            resultado.candidatos.extend(candidates)
            context["sucessos"][task] = {"campos": list(requested), "modelo": models[phase]}
            completed.append(task)
            if phase == "large":
                resultado.escalou = True
                resultado.motivo_do_escalonamento = "passagem por bloco retomável"
            elif escalonar:
                missing = sorted(set(faltando) - {c.campo for c in candidates})
                should_escalate, why = prompt.deve_escalar(
                    campos_pedidos=len(campos),
                    campos_nulos=len(missing),
                    n_tabelas=documento.n_tabelas,
                )
                if missing and should_escalate:
                    context["escalonamentos"][bid] = missing
                    resultado.motivo_do_escalonamento = why
            phase = pendente(context, bid)
        if failures or len(used) >= limit:
            break
    resultado.leitura = resumo(key, context, usados=used, concluidos=completed, falhas=failures)
    if resultado.leitura["pendentes"]:
        resultado.avisos.append(
            f"{resultado.leitura['pendentes']} bloco(s) com leitura pendente; "
            "estado preservado para retomada, sem inferir ausência de informação"
        )
    return resultado


def extrair_documento(
    documento: Documento,
    campos: set[str],
    *,
    marca: str = "",
    modelo_veiculo: str = "",
    versao: str = "",
    permitir_llm: bool = True,
    max_blocos: int | None = None,
    escalonar: bool = True,
    ano_modelo: int | None = None,
    estado_leitura: EstadoLeitura | None = None,
    documento_sha256: str = "",
    parser_version: str = "",
    policy_version: str | None = None,
    configuracao_alvo: dict | None = None,
) -> ResultadoExtracao:
    """Extrai os campos de **um** documento: fast-path e, no resto, LLM.

    `max_blocos` e `escalonar` são os dois botões que o Pesquisador aperta: um bloco por
    documento e sem segunda passada com o modelo grande. Fora dele, os padrões preservam
    o comportamento do eval — que é medido, e não se mexe por acidente.

    Com `estado_leitura`, `max_blocos` limita tentativas de passagens nesta chamada,
    incluindo a eventual passagem grande; zero preserva toda a fila. A ordem passa a
    ser sempre por relevância. A conclusão só avança após resposta `ok`; candidatos
    devem ser acumulados pelo chamador e salvos no mesmo checkpoint que o estado.
    """
    resultado = ResultadoExtracao(campos_alvo=tuple(sorted(campos)))

    if ano_modelo is not None:
        from pipeline.identity import Applicability, VehicleTarget, assess

        target = VehicleTarget(marca, modelo_veiculo, versao, ano_modelo)
        assessment = (
            _identidade_tabular(documento, target)
            if documento.multiversao
            else assess(target, documento.texto, url=documento.url)
        )
        if assessment.status != Applicability.COMPATIBLE:
            resultado.avisos.append(
                f"{documento.source_id}: {assessment.status}: " + ", ".join(assessment.reasons)
            )
            return resultado

    resultado.candidatos.extend(_do_fastpath(documento, campos))
    if documento.multiversao:
        resultado.candidatos = [c for c in resultado.candidatos if c.de_celula]
        resultado.avisos.append("tabela multiversão: somente células da coluna comprovada")
        return resultado
    faltando = sorted(campos - resultado.campos_do_fastpath)

    if not faltando:
        log.info("extract.fastpath_resolveu_tudo", extra={"source": documento.source_id})
        return resultado
    if estado_leitura is not None:
        return _extrair_retomavel(
            documento,
            campos,
            faltando,
            resultado,
            estado=estado_leitura,
            marca=marca,
            modelo_veiculo=modelo_veiculo,
            versao=versao,
            ano_modelo=ano_modelo,
            permitir_llm=permitir_llm,
            max_blocos=max_blocos,
            escalonar=escalonar,
            documento_sha256=documento_sha256,
            parser_version=parser_version,
            policy_version=policy_version,
            configuracao_alvo=configuracao_alvo,
        )
    if not permitir_llm:
        resultado.avisos.append(
            f"{len(faltando)} campo(s) sem fast-path e LLM desativado: {', '.join(faltando)}"
        )
        return resultado

    blocos, pulados = _blocos_que_valem(documento.texto, faltando, teto=max_blocos)
    if pulados:
        teto = max(1, max_blocos) if max_blocos else MAX_BLOCOS_AO_LLM
        resultado.avisos.append(
            f"{pulados} bloco(s) do documento não foram ao modelo: o teto é "
            f"{teto} e os escolhidos são os que mencionam os campos que "
            f"faltam. Campo que só exista nos pulados fica `nao_encontrado`."
        )
    for i, bloco in enumerate(blocos, start=1):
        parcial = Documento(
            texto=bloco,
            source_id=documento.source_id,
            url=documento.url,
            tier=documento.tier,
            captured_at=documento.captured_at,
            celulas=documento.celulas if i == 1 else (),
            n_tabelas=documento.n_tabelas,
        )
        candidatos, uso, motivo, _ok = _do_llm(
            parcial,
            faltando,
            marca=marca,
            modelo_veiculo=modelo_veiculo,
            versao=versao,
            modelo_llm=llm.modelo_pequeno(),
        )
        resultado.candidatos.extend(candidatos)
        if uso:
            resultado.usos.append(uso)
        if motivo and not candidatos:
            resultado.avisos.append(f"bloco {i}/{len(blocos)}: {motivo}")
        faltando = sorted(set(faltando) - {c.campo for c in candidatos})
        if not faltando:
            break

    if faltando and escalonar:
        escalar, motivo = prompt.deve_escalar(
            campos_pedidos=len(campos),
            campos_nulos=len(faltando),
            n_tabelas=documento.n_tabelas,
        )
        if escalar:
            resultado.escalou = True
            resultado.motivo_do_escalonamento = motivo
            log.info("extract.escalou_modelo", extra={"motivo": motivo})
            candidatos, uso, motivo_llm, _ok = _do_llm(
                documento,
                faltando,
                marca=marca,
                modelo_veiculo=modelo_veiculo,
                versao=versao,
                modelo_llm=llm.modelo_grande(),
            )
            resultado.candidatos.extend(candidatos)
            if uso:
                resultado.usos.append(uso)
            faltando = sorted(set(faltando) - {c.campo for c in candidatos})
            if motivo_llm and not candidatos:
                resultado.avisos.append(f"2a passada (modelo grande): {motivo_llm}")

    if faltando:
        resultado.avisos.append(
            f"{len(faltando)} campo(s) sem valor nesta fonte: {', '.join(faltando)}"
        )
    return resultado


def extrair_fontes(
    documentos: list[Documento],
    campos: set[str],
    **kw,
) -> ResultadoExtracao:
    """Extrai de várias fontes e **junta** os candidatos, sem escolher entre eles.

    Escolher é da reconciliação (WP-12). Aqui as fontes só somam evidência: duas fontes
    com o mesmo valor sobem a confiança depois, e duas com valores diferentes viram
    `divergente` — nenhuma das duas coisas é possível se este passo já tiver descartado.
    """
    total = ResultadoExtracao(campos_alvo=tuple(sorted(campos)))
    for documento in documentos:
        parcial = extrair_documento(documento, campos, **kw)
        total.candidatos.extend(parcial.candidatos)
        total.usos.extend(parcial.usos)
        total.avisos.extend(parcial.avisos)
        if parcial.leitura:
            total.leitura.setdefault("documentos", []).append(parcial.leitura)
        total.escalou = total.escalou or parcial.escalou
        if parcial.motivo_do_escalonamento and not total.motivo_do_escalonamento:
            total.motivo_do_escalonamento = parcial.motivo_do_escalonamento
    return total
