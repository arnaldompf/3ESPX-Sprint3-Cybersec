"""Orquestração do job: a máquina de estados linear de `docs/05`.

    queued → resolving → fetching → parsing → extracting → grounding
           → normalizing → reconciling → done | failed | versao_inexistente

Cada estágio é uma função pequena e o `JobContext` carrega o que já foi produzido. Duas
regras de `docs/05` moldam o desenho:

* **falha em uma fonte não falha o job** — a fonte vira `erro` ou `bloqueada` em
  `sources_checked` e o pipeline segue. Uma ficha com quatro fontes e uma bloqueada é um
  resultado; um job derrubado por um 403 é uma ficha perdida;
* **`versao_inexistente` é um estado final legítimo**, não uma falha. O resolvedor
  respondeu; a resposta é que a versão não existe na linha vigente.

O que este módulo **não** faz: decidir status, agrupar por valor, calcular confiança ou
verificar grounding. Isso é de `pipeline/status.py` (via `pipeline/reconcile.py`), e a
razão de não ser duplicado aqui é a D-46 — o eval mede a mesma função que o produto
aplica, e isso só vale se houver uma única implementação.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline import reconcile, resolver
from pipeline.connectors import fipe
from pipeline.extract.run import Candidato, Documento, ResultadoExtracao, extrair_fontes
from pipeline.schema import GRUPOS, SpecMeta, StandardSpec, Status, empty_spec
from pipeline.store import FIXTURES, Snapshot, fontes_de, snapshots_de

log = logging.getLogger(__name__)

#: Estágios na ordem de `docs/05`. A lista é a documentação executável da ordem.
ESTAGIOS = (
    "queued",
    "resolving",
    "fetching",
    "parsing",
    "extracting",
    "grounding",
    "normalizing",
    "reconciling",
)
#: Estados finais.
FINAIS = ("done", "failed", "versao_inexistente")

#: Snapshots que trazem tabela por versão e por isso precisam de recorte de coluna.
#: O `tipo` vem do `meta.json` do snapshot, e os valores reais são `pdf_oficial`,
#: `pagina_oficial`, `imprensa`, `fipe` e `registro_de_evidencia` — a comparação é por
#: **prefixo** porque a primeira versão disto testava `tipo == "pdf"`, não casava com
#: `"pdf_oficial"` e o recorte por versão simplesmente **nunca rodava**. O sintoma não
#: era erro nenhum: era a Hilux ganhando aro 17 e pneu 265/65 R17 (a coluna da SRX, não
#: da SRX Plus) sem que nada reclamasse.
PREFIXOS_COM_TABELA = ("pdf",)
#: Tipos de snapshot que valem como página oficial da montadora (tier 1).
TIPOS_OFICIAIS = ("pagina_oficial", "pdf_oficial")
#: Tipo de snapshot de imprensa, o rebaixamento tier 3 de `specs/WP-13.md`.
TIPO_IMPRENSA = "imprensa"
#: Tipo de snapshot da **tabela** do PBE/Inmetro. Tem tratamento próprio: ver
#: `_documento_do_pbe`, e o comentário em `documentos_de` sobre por que ela não entra
#: no laço geral.
TIPO_PBE = "pbe"
#: Tipo de snapshot da FIPE.
TIPO_FIPE = "fipe"

#: Tipos de fonte que **não** alimentam a extração de especificação. As duas respondem
#: por conector próprio, que sabe ler a estrutura delas, e o texto continua disponível
#: para o grounding (ele vem de `ctx.snapshots`, não dos documentos).
#:
#: A FIPE entrou nesta lista por defeito medido em 10/09/2026: a página de referência da
#: Amarok traz, no rodapé, uma **lista de outros veículos** — e o fast-path leu
#: `"Ford Mustang GT V8 Conversível 2015 Gasolina R$ 340.201,00"` e afirmou que a Amarok
#: tem motor **V8**, com citação que groundeia perfeitamente. O campo saía `divergente`
#: entre V6 e V8. Uma página de preço não é fonte de especificação: ela responde
#: `preco_fipe_brl`, `fipe_referencia` e `codigo_fipe`, e só, por
#: `pipeline/connectors/fipe.py`.
TIPOS_FORA_DA_EXTRACAO = (TIPO_PBE, TIPO_FIPE)

#: Cobertura minima para aceitar um `version_id` adivinhado a partir do pedido da CLI.
#: Alta de proposito: ler os snapshots do veiculo errado produziria uma ficha
#: plausivel e errada, que e o pior resultado possivel aqui.
COBERTURA_MINIMA_DO_ID = 0.75

#: Campos que **não** vêm de texto de página: são consultas a serviço, com regra própria
#: (`pipeline/connectors/fipe.py`). Mantê-los fora do alvo da extração evita que o
#: fast-path pesque um preço qualquer da página e o atribua à versão errada — o defeito
#: que a WP-13 existe para não cometer.
CAMPOS_DE_SERVICO = ("preco_fipe_brl", "fipe_referencia", "preco_sugerido_brl")


def campos_canonicos() -> list[str]:
    """Todos os campos da ficha, em `grupo.campo`, na ordem do schema."""
    return [f"{grupo}.{campo}" for grupo, campos in GRUPOS.items() for campo in campos]


def campos_alvo(atributos: list[str] | None = None) -> list[str]:
    """O que o job vai tentar preencher.

    Sem `atributos`, a ficha inteira: o produto entrega ficha completa, e um campo que
    ninguém tentou preencher é indistinguível de um campo que não existe na fonte.
    """
    if not atributos:
        return campos_canonicos()
    canonicos = {c.split(".", 1)[1]: c for c in campos_canonicos()}
    return [canonicos.get(a, a) for a in atributos]


# ------------------------------------------------------------------ contexto do job
@dataclass
class JobContext:
    """O que o job sabe até agora. Um por execução, sem estado global."""

    marca: str
    modelo: str
    versao: str
    ano: int | None = None
    version_id: str = ""
    replay: bool = True
    atributos: list[str] | None = None
    job_id: str = ""

    stage: str = "queued"
    resolucao: resolver.Resolution | None = None
    snapshots: list[Snapshot] = field(default_factory=list)
    documentos: list[Documento] = field(default_factory=list)
    extracao: ResultadoExtracao | None = None
    comerciais: list[Candidato] = field(default_factory=list)
    medidos: list[Candidato] = field(default_factory=list)
    """Candidatos de **medição de terceiro** (hoje, o consumo do PBE/Inmetro).

    Separados de `comerciais` porque a origem é outra e o tier também pode ser: o
    comercial responde "quanto custa", o medido responde "quanto anda". Os dois entram
    na reconciliação pelo mesmo caminho, com a própria citação."""
    reconciliacao: reconcile.ResultadoReconciliacao | None = None
    fontes_bloqueadas: list[str] = field(default_factory=list)
    fontes_com_erro: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    transicoes: list[tuple[str, float]] = field(default_factory=list)
    """`(estágio, segundos desde o início)` — o que `jobs.stage` grava em produção."""
    persistencia: Any = None
    """`ResultadoPersistencia`, quando `persistir=True`. Visível para quem chamou."""

    def entra(self, stage: str) -> None:
        """Registra a transição. Ordem é invariante: nunca se volta um estágio."""
        if stage not in FINAIS:
            anterior = ESTAGIOS.index(self.stage) if self.stage in ESTAGIOS else -1
            if ESTAGIOS.index(stage) <= anterior:
                raise ValueError(f"transição inválida: {self.stage} → {stage}")
        self.stage = stage
        self.transicoes.append((stage, self._decorrido()))
        log.debug("job.stage", extra={"job_id": self.job_id, "stage": stage})

    def _decorrido(self) -> float:
        if not hasattr(self, "_inicio"):
            self._inicio = time.monotonic()
        return round(time.monotonic() - self._inicio, 4)

    @property
    def textos(self) -> dict[str, str]:
        """Os textos contra os quais o grounding confere, por `source_id`.

        Vêm dos **documentos**, não dos snapshots: documento é o que a extração de fato
        leu, e há fonte que não é snapshot de página — a referência interna do cliente,
        por exemplo. Um texto de fora deste dicionário reprovaria no grounding e o valor
        seria descartado sem que a fonte tivesse culpa.
        """
        textos = {s.source_id: s.texto for s in self.snapshots}
        textos.update({d.source_id: d.texto for d in self.documentos})
        return textos

    @property
    def sources_checked(self) -> list[str]:
        """Toda fonte consultada, com bloqueada e com erro **incluídas**.

        É o que separa `nao_disponivel` de `nao_encontrado`: sem saber que a fonte foi
        consultada, "não achei" e "a fonte diz que não tem" são a mesma frase.
        """
        return sorted({*self.textos, *self.fontes_bloqueadas, *self.fontes_com_erro})


# ------------------------------------------------------------------------- estágios
def resolver_versao(ctx: JobContext) -> resolver.Resolution:
    ctx.entra("resolving")
    resolucao = resolver.resolve(ctx.marca, ctx.modelo, ctx.versao)
    ctx.resolucao = resolucao
    if resolucao.versao_resolvida is not None:
        ctx.ano = resolucao.versao_resolvida.ano_modelo
    ctx.fontes_bloqueadas.extend(resolucao.bloqueadas)
    return resolucao


def documentos_de(
    version_id: str,
    versao: str,
    *,
    raiz: Path | None = None,
    snapshots: list[Snapshot] | None = None,
    marca: str = "",
    modelo: str = "",
) -> tuple[list[Documento], list[Snapshot], list[str]]:
    """Monta os documentos para extração a partir dos snapshots salvos.

    Devolve `(documentos, snapshots, avisos)`. É **público e reusado** por
    `scripts/record_llm_fixtures.py`: o gravador de fixtures tem de montar os documentos
    exatamente como o pipeline monta, senão o prompt muda, a chave da fixture muda e a
    resposta gravada deixa de ser encontrada — deriva silenciosa entre o que se gravou e
    o que se replaya. Antes desta função, o gravador montava **sem** as células
    recortadas, e as duas montagens já tinham divergido.

    O recorte de coluna por versão (`version_slicer`) só se aplica a snapshot com tabela
    por versão: numa ficha de PDF, a coluna da versão errada é o vizinho de tabela, e ler
    a coluna errada é o erro mais fácil de cometer com fonte tabular.
    """
    snaps = snapshots if snapshots is not None else snapshots_de(version_id, raiz)
    documentos: list[Documento] = []
    avisos: list[str] = []
    snapshots_validos: list[Snapshot] = []
    for snap in snaps:
        tem_pdf_local = any(
            (snap.caminho / nome).is_file() for nome in ("documento.json", "tables.json")
        )
        if tem_pdf_local and _documento_pdf_de(snap) is None:
            # Não oferecer o texto rejeitado ao extrator, conectores ou grounding.
            # O original permanece no acervo, com o motivo explícito na execução.
            avisos.append(f"{snap.source_id}: PDF com texto/estrutura inconsistente ou pendente")
            continue
        snapshots_validos.append(snap)
        if not snap.texto:
            continue
        # Ver `TIPOS_FORA_DA_EXTRACAO`: a tabela do PBE traz 400 configurações de outros
        # veículos e a página FIPE traz uma lista de outros modelos no rodapé. Entregar
        # qualquer das duas ao extrator é oferecer o dado do vizinho com evidência que
        # groundeia. As duas entram por conector próprio, que sabe onde olhar.
        if snap.tipo in TIPOS_FORA_DA_EXTRACAO:
            continue
        celulas: tuple = ()
        n_tabelas = 0
        if snap.tipo.startswith(PREFIXOS_COM_TABELA):
            celulas, n_tabelas, aviso = _recorte_da_versao(snap, versao)
            if aviso:
                avisos.append(aviso)
        documentos.append(
            Documento(
                texto=_sem_frases_ambiguas_do_pbev(snap.texto),
                source_id=snap.source_id,
                url=snap.url,
                tier=snap.tier,
                captured_at=snap.captured_at,
                celulas=celulas,
                n_tabelas=n_tabelas,
                # Sem isto, `extrair_documento` manda o texto inteiro (que cobre TODAS
                # as versões da tabela) para `identity.assess`, que rejeita a ficha
                # inteira por câmbio/ano de uma versão vizinha — mesmo com a coluna
                # certa já recortada em `celulas`. `_identidade_tabular` é quem sabe
                # conferir só a coluna; sem a flag, ele nunca é chamado.
                multiversao=bool(celulas),
            )
        )

    pbe_doc, aviso_pbe = _documento_do_pbe(snapshots_validos, versao, modelo=modelo, marca=marca)
    if pbe_doc is not None:
        documentos.append(pbe_doc)
    if aviso_pbe:
        avisos.append(aviso_pbe)
    return documentos, snapshots_validos, avisos


def _sem_frases_ambiguas_do_pbev(texto: str) -> str:
    """Remove as frases do PBEV do texto da página **quando há mais de uma**.

    Existe por um defeito que apareceu no instante em que o conector do PBE entrou: a
    página da Hilux traz **quatro** frases de consumo, uma por configuração. O documento da
    página inteira lia a primeira (10,1 km/l, da SRV/SRX), o documento recortado lia a da
    versão pedida (9,7 km/l, da SRX Plus), e a ficha saía com `consumo` **divergente** — uma
    discordância inventada entre duas leituras da mesma página. É o mesmo defeito que a
    WP-09 teve com a coluna 17"/18" da tabela, pela mesma causa: ler um dado que pertence a
    outra versão.

    Com **uma** frase só, a página pode atribuí-la sem ambiguidade e o texto fica intacto.
    Com mais de uma, a atribuição é do conector, e o que sobra na página não é dado dela.
    """
    from pipeline.connectors.pbe import FRASE_PBEV

    achados = list(FRASE_PBEV.finditer(texto))
    if len(achados) < 2:
        return texto
    saida: list[str] = []
    fim_anterior = 0
    for achado in achados:
        saida.append(texto[fim_anterior : achado.start()])
        fim_anterior = achado.end()
    saida.append(texto[fim_anterior:])
    return "".join(saida)


def _documento_do_pbe(
    snaps: list[Snapshot], versao: str, *, modelo: str = "", marca: str = ""
) -> tuple[Documento | None, str]:
    """A frase do PBEV **da versão pedida**, como documento próprio em tier 2.

    A mesma página oficial traz uma frase de consumo por configuração — quatro na página da
    Hilux. Passar a página inteira ao extrator deixaria as quatro disponíveis, e ele pegaria
    a primeira: consumo do vizinho com evidência que groundeia. Aqui a frase certa é
    recortada por `pipeline/connectors/pbe.py` e entra como **fonte separada**, tier 2
    (medição do Inmetro, não da montadora), pelo mesmo caminho de qualquer outra fonte.

    Quando nenhuma frase identifica a versão, o aviso diz isso — e o campo fica
    `nao_encontrado` com a fonte na lista de consultadas, que é o vazio honesto.
    """
    from pipeline.connectors import pbe

    # A tabela é tratada em `consultar_consumo`, que lê a **coluna** (a linha não tem a
    # palavra "km/l" e nenhum regex sabe qual número é qual). Aqui fica a frase do PBEV
    # da página da montadora — que continua existindo por dois motivos: a tabela não
    # lista tudo (a Raptor, por ser gasolina, não está no ciclo 2026) e, quando as duas
    # existem e discordam, **as duas** têm de chegar à reconciliação. Para a SRX Plus a
    # página diz 9,7/10,6 e a tabela do Inmetro diz 9,3/10,0: duas fontes oficiais em
    # desacordo é `divergente` com os dois valores, não uma escolhida em silêncio.
    for snap in snaps:
        if not snap.texto or "km/l" not in snap.texto:
            continue
        resultado = pbe.consumo_de(snap.texto, versao=versao)
        if resultado.tem_valor and resultado.registro is not None:
            return (
                Documento(
                    texto=resultado.registro.trecho,
                    source_id=pbe.SOURCE_ID,
                    url=snap.url,
                    tier=pbe.TIER_PBE,
                    captured_at=snap.captured_at,
                ),
                "",
            )
        if resultado.candidatos:
            return None, f"pbe: {resultado.motivo}"
    return None, ""


def _recorte_da_versao(snap: Snapshot, versao: str) -> tuple[tuple, int, str]:
    """Recorta a coluna da versão num snapshot tabular. Sem tabelas, segue sem recorte."""
    from pipeline.parse.version_slicer import recortar

    documento = _documento_pdf_de(snap)
    if documento is None or not documento.tabelas:
        return (), 0, ""
    try:
        recorte = recortar(documento, versao)
    except Exception as exc:  # pragma: no cover - tabela malformada no snapshot
        return (), len(documento.tabelas), f"{snap.source_id}: recorte de versão falhou ({exc})"
    if not recorte.celulas:
        return (
            (),
            len(documento.tabelas),
            (
                f"{snap.source_id}: nenhuma coluna casou com {versao!r}; "
                "o texto corrido segue valendo"
            ),
        )
    return tuple(recorte.celulas), len(documento.tabelas), ""


def _documento_pdf_de(snap: Snapshot) -> Any | None:
    """Recupera o `DocumentoPdf` com as tabelas de um snapshot de PDF.

    As tabelas **não** cabem no `meta.json` do snapshot — elas vivem na fixture do PDF
    já parseado (`tests/fixtures/pdf/<nome>/tables.json`), que é o que a WP-09 gera e
    versiona. O elo entre os dois é o `arquivo_de_origem` do snapshot, que aponta para o
    `doc.md` **dentro** dessa pasta; o `tables.json` é o irmão dele.

    Ao vivo, este passo é o `parse_pdf` sobre o PDF baixado. Em replay é a leitura da
    fixture — e é o mesmo `DocumentoPdf` nos dois casos, o que mantém o recorte de coluna
    idêntico entre a coleta real e o replay.
    """
    import json

    from pipeline.parse.pdf import DocumentoPdf, Tabela

    local = snap.caminho / "documento.json"
    if local.is_file():
        from dataclasses import replace

        from pipeline.snapshots import sha256_de

        try:
            parsed = DocumentoPdf.from_dict(json.loads(local.read_text(encoding="utf-8")))
            expected = snap.meta.get("sha256")
            safe_text = parsed.texto_para_extracao()
            if safe_text != snap.texto or (expected and sha256_de(snap.texto) != expected):
                return None
            return replace(parsed, markdown=safe_text, tabelas=parsed.tabelas_para_extracao())
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    local_tables = snap.caminho / "tables.json"
    if local_tables.is_file():
        from dataclasses import replace

        from pipeline.snapshots import sha256_de

        try:
            dados = json.loads(local_tables.read_text(encoding="utf-8"))
            # A grade isolada não contém páginas nem permite separar OCR pendente.
            # Capturas com diagnóstico precisam do documento completo persistido.
            if dados.get("diagnosticos") and not dados.get("paginas"):
                return None
            parsed = DocumentoPdf.from_dict(
                {**dados, "markdown": snap.texto, "paginas": dados.get("paginas", [])}
            )
            expected = snap.meta.get("sha256")
            if parsed.texto_para_extracao() != snap.texto or (
                expected and sha256_de(snap.texto) != expected
            ):
                return None
            return replace(parsed, tabelas=parsed.tabelas_para_extracao())
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    origem = snap.meta.get("arquivo_de_origem", "")
    if not origem:
        return None
    tabelas_json = Path(__file__).resolve().parents[1] / Path(origem).parent / "tables.json"
    if not tabelas_json.exists():
        return None
    dados = json.loads(tabelas_json.read_text(encoding="utf-8"))
    return DocumentoPdf(
        markdown=snap.texto,
        paginas=snap.texto.split("\n\n"),
        tabelas=[Tabela.from_dict(t) for t in dados.get("tabelas", [])],
        motor=dados.get("motor", "fixture"),
    )


#: Onde vive a referência interna do cliente (o deck comercial). Fora de `snapshots/`
#: de propósito: não é captura de página, é documento que o cliente entregou.
DIR_REFERENCIA_INTERNA = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "slide"
#: Tier da referência interna: **abaixo** de oficial (T1), FIPE (T2) e imprensa (T3).
#: É o que faz o valor público vencer e o do slide ir para `conflicts` — a ficha mostra o
#: valor certo e denuncia o deck, e não o contrário. Um slide com tier alto inverteria o
#: produto: o "Fogo Amigo" existe para proteger o vendedor da própria apresentação.
TIER_REFERENCIA_INTERNA = 4


def referencia_interna(version_id: str) -> Documento | None:
    """A referência interna da montadora, se houver, como documento de extração.

    Entra pelo mesmo caminho de qualquer fonte: extração, grounding, status. Nada de
    tratamento especial — é justamente por passar pelas mesmas regras que a divergência
    slide × site nasce **do mecanismo**, e não de um `if` que sabia a resposta.
    """
    caminho = DIR_REFERENCIA_INTERNA / f"{version_id}.md"
    if not caminho.exists():
        return None
    return Documento(
        texto=caminho.read_text(encoding="utf-8"),
        source_id="referencia_interna",
        url=f"file://{caminho.name}",
        tier=TIER_REFERENCIA_INTERNA,
        captured_at="",
    )


def buscar_fontes(ctx: JobContext) -> None:
    """Estágio `fetching`+`parsing`. Em replay, "buscar" é ler o snapshot salvo."""
    ctx.entra("fetching")
    for fonte in fontes_de(ctx.version_id):
        if fonte.status == "bloqueada":
            ctx.fontes_bloqueadas.append(fonte.url)
        elif fonte.status == "erro":
            ctx.fontes_com_erro.append(fonte.url)

    ctx.entra("parsing")
    documentos, snaps, avisos = documentos_de(
        ctx.version_id,
        ctx.resolucao.matched_version if ctx.resolucao else ctx.versao,
        marca=ctx.marca,
        modelo=ctx.modelo,
    )
    ctx.documentos, ctx.snapshots = documentos, snaps
    ctx.avisos.extend(avisos)

    referencia = referencia_interna(ctx.version_id)
    if referencia is not None:
        ctx.documentos.append(referencia)
        ctx.avisos.append(
            f"referência interna carregada ({referencia.source_id}, tier "
            f"{referencia.tier}): divergência contra fonte pública será exposta"
        )


def extrair(ctx: JobContext, campos: list[str]) -> ResultadoExtracao:
    """Estágio `extracting`. Fast-path primeiro, LLM só no resto (WP-10)."""
    ctx.entra("extracting")
    alvo = {c.split(".", 1)[-1] for c in campos} - set(CAMPOS_DE_SERVICO)
    resultado = extrair_fontes(
        ctx.documentos,
        alvo,
        marca=ctx.marca,
        modelo_veiculo=ctx.modelo,
        versao=ctx.resolucao.matched_version if ctx.resolucao else ctx.versao,
        ano_modelo=ctx.ano,
    )
    ctx.extracao = resultado
    ctx.avisos.extend(resultado.avisos)
    return resultado


def consultar_comerciais(ctx: JobContext, *, somente_snapshots: bool = False) -> list[Candidato]:
    """Preço FIPE e referência mensal, que vêm de **serviço**, não de página (WP-13).

    O `preco_sugerido_brl` **não** entra aqui: ele é o "a partir de" da montadora e sai da
    própria página, com a associação preço↔versão que a WP-13 mede em caracteres. Aqui
    ficam só os dois campos que dependem do código FIPE.
    """
    ctx.entra("grounding")
    candidatos: list[Candidato] = []
    consulta = None
    versao_para_fipe = ctx.resolucao.matched_version if ctx.resolucao else ctx.versao

    # A pesquisa aberta pode encontrar diretamente a resposta da API FIPE. Ela já contém
    # código, preço e referência; exigir que o código estivesse antes no catálogo fazia o
    # documento ser baixado e depois ignorado. A identidade é conferida antes do merge.
    for snap in ctx.snapshots:
        if snap.tipo != TIPO_FIPE or not snap.texto:
            continue
        candidata = fipe.parse_pagina_fipe(snap.texto, url=snap.url)
        corresponde, motivo = fipe.corresponde_ao_veiculo(
            candidata,
            marca=ctx.marca,
            modelo=ctx.modelo,
            versao=versao_para_fipe or ctx.versao,
            ano=ctx.ano,
        )
        if not corresponde:
            ctx.avisos.append(f"FIPE [{snap.source_id}]: {motivo}; outra versao nao e fundida")
            continue
        candidata.source_id = snap.source_id
        candidata.tier = fipe.TIER_FIPE
        consulta = candidata
        break

    if consulta is None and somente_snapshots:
        ctx.avisos.append("FIPE offline: nenhuma captura local compatível; sem consulta de rede")
        return candidatos
    codigo = consulta.codigo if consulta else _codigo_fipe_da_versao(ctx)
    if not codigo:
        ctx.avisos.append(
            f"{ctx.version_id}: sem código FIPE resolvido; "
            "preco_fipe_brl e fipe_referencia ficam nao_encontrado"
        )
        return candidatos

    # `marca` e `modelo` são dicas de **navegação** na API comunitária, que não tem rota
    # por código FIPE. O código continua sendo o critério de aceitação (ver `fipe.price`).
    # Em replay nada disso é usado: o valor sai do snapshot salvo.
    if consulta is None:
        consulta = fipe.price(
            codigo,
            ano=ctx.ano,
            marca=ctx.marca,
            modelo=f"{ctx.modelo} {versao_para_fipe or ctx.versao}".strip(),
        )
    if not consulta.ok:
        ctx.avisos.append(f"FIPE {codigo}: {consulta.motivo}")
        return candidatos

    if consulta.modelo_fipe:
        corresponde, motivo = fipe.corresponde_ao_veiculo(
            consulta, marca=ctx.marca, modelo=ctx.modelo, versao=versao_para_fipe, ano=ctx.ano
        )
        if not corresponde:
            ctx.avisos.append(f"FIPE: {motivo}")
            return candidatos

    # Cada campo com **a sua** citação verbatim, tirada do texto que a consulta leu.
    # Compor uma frase aqui ("Referência FIPE: 2026-09; Preço: R$ 339.270") groundearia
    # contra um texto escrito por nós — o que não é evidência de nada, e foi como estes
    # dois campos apareceram no eval com `grounding_ok=False`.
    for campo, valor, quote in (
        ("codigo_fipe", consulta.codigo, consulta.quote_codigo),
        ("preco_fipe_brl", consulta.preco_brl, consulta.quote_preco),
        ("fipe_referencia", consulta.referencia, consulta.quote_referencia),
    ):
        if not quote:
            ctx.avisos.append(f"{campo}: consulta FIPE sem trecho verbatim; campo não afirmado")
            continue
        candidatos.append(
            Candidato(
                campo=campo,
                valor=valor,
                quote=quote,
                origem=f"servico:fipe:{consulta.origem or 'consulta'}",
                source_id=consulta.source_id or f"fipe:{codigo}",
                source_text=consulta.source_text,
                url=consulta.url,
                tier=consulta.tier,
                notas=consulta.origem,
            )
        )
    ctx.comerciais = candidatos
    return candidatos


def consultar_consumo(ctx: JobContext) -> list[Candidato]:
    """Consumo urbano e rodoviário da **tabela** do PBE, como candidatos com citação.

    Por que não deixar para o fast-path, como a frase do PBEV: a linha da tabela não tem
    a palavra "km/l" — os números estão em colunas (`... 8,3 10,1 9,0 ... 2,82 ...`), e
    qualquer regex solto ali pescaria o MJ/km e o chamaria de consumo. Quem sabe qual
    número é qual é o parser da tabela, que leu a **posição** da coluna. O valor sai de
    lá com a linha inteira como evidência, exatamente como a FIPE faz com a resposta da
    API. A frase do PBEV na página da montadora continua pelo fast-path, sem mudança.
    """
    from pipeline.connectors import pbe
    from pipeline.identity import VehicleTarget

    versao = ctx.resolucao.matched_version if ctx.resolucao else ctx.versao
    candidatos: list[Candidato] = []
    for snap in ctx.snapshots:
        if snap.tipo != TIPO_PBE or not snap.texto:
            continue
        for candidate in pbe.candidatos_direcao(
            snap.texto, snap.url, VehicleTarget(ctx.marca, ctx.modelo, versao, ctx.ano)
        ):
            candidate.source_id = snap.source_id
            candidate.captured_at = snap.captured_at
            candidatos.append(candidate)
        resultado = pbe.casar_na_tabela(
            pbe.parse_tabela(snap.texto.splitlines()),
            versao=versao,
            modelo=ctx.modelo,
            marca=ctx.marca,
        )
        if not resultado.tem_valor or resultado.registro is None:
            if resultado.motivo:
                ctx.avisos.append(f"pbe (tabela): {resultado.motivo}")
            break
        registro = resultado.registro
        if ctx.ano is not None:
            import re

            anos = {int(y) for y in re.findall(r"\b(20\d{2})\b", registro.descricao)}
            anos.update(
                2000 + int(y) for y in re.findall(r"\bMY\s*(\d{2})\b", registro.descricao, re.I)
            )
            if ctx.ano not in anos:
                ctx.avisos.append("pbe: ano-modelo da linha não comprovado para o alvo")
                continue
        for campo, valor in (
            ("consumo_urbano_kml", registro.urbano_kml),
            ("consumo_rodoviario_kml", registro.rodoviario_kml),
        ):
            candidatos.append(
                Candidato(
                    campo=campo,
                    valor=valor,
                    quote=registro.trecho,
                    origem="servico:pbe:tabela",
                    source_id=snap.source_id,
                    url=snap.url,
                    tier=pbe.TIER_PBE,
                    notas=f"linha da tabela: {registro.descricao}",
                )
            )
        break
    ctx.medidos = candidatos
    return candidatos


def consultar_preco_oficial(ctx: JobContext) -> list[Candidato]:
    """O "a partir de" da montadora, com o rebaixamento para imprensa de `specs/WP-13.md`.

    A ordem é a da spec: **página oficial primeiro**, e só se ela não publicar preço por
    versão é que vale imprensa, com `confidence ≤ 0,60` e nota. Não é preferência
    estética — o site da Amarok de fato não exibe preço por versão, e o gabarito registra
    `verificado_tier3` justamente por isso.

    `escopo` sai do próprio snapshot: uma `pagina_oficial` cuja URL termina no nome da
    versão é página da versão; as outras cobrem a linha. É o que autoriza aceitar o preço
    único da página da Raptor sem exigir o nome ao lado dele.
    """
    versao = ctx.resolucao.matched_version if ctx.resolucao else ctx.versao
    candidatos: list[Candidato] = []

    for tier_desejado, tipos in ((1, TIPOS_OFICIAIS), (3, (TIPO_IMPRENSA,))):
        for snap in ctx.snapshots:
            if snap.tipo not in tipos or not snap.texto:
                continue
            resultado = fipe.preco_oficial(
                snap.texto,
                versao=versao,
                tier=tier_desejado,
                fonte=snap.source_id,
                data=snap.captured_at,
                escopo=_escopo_do_snapshot(snap, versao),
            )
            if not resultado.ok:
                if resultado.nota:
                    ctx.avisos.append(f"preco_sugerido_brl [{snap.source_id}]: {resultado.nota}")
                continue
            candidatos.append(
                Candidato(
                    campo="preco_sugerido_brl",
                    valor=resultado.valor_brl,
                    quote=resultado.quote,
                    origem=f"conector:preco_oficial:tier{tier_desejado}",
                    source_id=snap.source_id,
                    url=snap.url,
                    tier=tier_desejado,
                    captured_at=snap.captured_at,
                    notas=resultado.nota,
                )
            )
            data, quote_data, nota_data = _data_do_preco(snap, resultado)
            if data:
                candidatos.append(
                    Candidato(
                        campo="preco_data",
                        valor=data,
                        quote=quote_data,
                        origem=f"conector:preco_oficial:tier{tier_desejado}",
                        source_id=snap.source_id,
                        url=snap.url,
                        tier=tier_desejado,
                        captured_at=snap.captured_at,
                        notas=nota_data,
                    )
                )
        if candidatos:
            break

    ctx.comerciais.extend(candidatos)
    return candidatos


#: A data de publicação de uma matéria, como a Autoesporte a escreve: "26/08/2025 13h16
#: Atualizado 26/08/2025 14h49". A **primeira** ocorrência é a publicação; a segunda é a
#: atualização, e o preço vale da publicação.
_DATA_DE_PUBLICACAO = re.compile(r"\b(?P<dia>\d{2})/(?P<mes>\d{2})/(?P<ano>\d{4})\b")


def _data_do_preco(snap: Snapshot, preco: Any) -> tuple[str, str, str]:
    """A data do preço, com a citação que a sustenta.

    São duas regras porque são duas coisas diferentes:

    * **imprensa** publica data, e ela está no texto (`"26/08/2025 13h16"`). O preço vale
      daquela data, não da data em que nós lemos a página — o gabarito da Amarok espera
      `2025-08-26`, e usar a data da coleta daria `2026-09-01`: um ano de diferença num
      campo que existe justamente para datar o preço;
    * **página oficial** não publica data. Aí a resposta honesta é a data da coleta ("o
      site exibia este preço neste dia"), e a evidência é a mesma do preço — que é
      exatamente o que o gabarito faz, citando em `preco_data` o trecho do preço.
    """
    if snap.tipo == TIPO_IMPRENSA:
        achado = _DATA_DE_PUBLICACAO.search(snap.texto)
        if not achado:
            return "", "", ""
        iso = f"{achado.group('ano')}-{achado.group('mes')}-{achado.group('dia')}"
        return iso, achado.group(0), "data de publicação da matéria"
    return (
        snap.captured_at,
        preco.quote,
        "a página oficial não publica data; vale a data da coleta, "
        "e a evidência é a do próprio preço",
    )


#: Tipos de snapshot que são **da versão** por construção, qualquer que seja a URL.
#:
#: O `registro_de_evidencia` é o registro da coleta **daquele veículo**
#: (`scripts/build_fixtures.py` gera um por `version_id`, de um JSON por veículo). A URL
#: dele é a da página de origem, que pode ser de linha — e julgá-lo pela URL fez
#: `preferir_especifico_da_versao` descartar a lista de **11 itens de ADAS da Raptor**,
#: conferida à mão na coleta, em favor de uma lista de 7 lida da página. O registro não
#: percorre versões: ele é de uma.
TIPOS_ESPECIFICOS_DA_VERSAO = ("registro_de_evidencia",)


def _escopo_do_snapshot(snap: Snapshot, versao: str) -> str:
    """`"versao"` quando o snapshot é da própria versão; `"linha"` no resto.

    Duas formas de ser da versão: o **tipo** dizer isso
    (:data:`TIPOS_ESPECIFICOS_DA_VERSAO`) ou a **URL** terminar no nome dela.
    """
    from pipeline.connectors.base import normalizar_versao

    if snap.tipo in TIPOS_ESPECIFICOS_DA_VERSAO:
        return "versao"
    caminho = (snap.url or "").rstrip("/").split("/")[-1].replace("-", " ")
    tokens = set(normalizar_versao(versao).split())
    return "versao" if tokens and tokens & set(normalizar_versao(caminho).split()) else "linha"


def _codigo_fipe_da_versao(ctx: JobContext) -> str:
    resultado = fipe.find_code(
        ctx.marca,
        ctx.modelo,
        ctx.resolucao.matched_version if ctx.resolucao else ctx.versao,
        version_id=ctx.version_id,
    )
    if not resultado.ok and resultado.motivo:
        ctx.avisos.append(f"codigo_fipe: {resultado.motivo}")
    return resultado.codigo or ""


def reconciliar(ctx: JobContext, campos: list[str]) -> reconcile.ResultadoReconciliacao:
    """Estágios `normalizing`+`reconciling`, os dois dentro de `pipeline/reconcile.py`."""
    ctx.entra("normalizing")
    de_servico = ctx.comerciais + ctx.medidos
    candidatos = list(ctx.extracao.candidatos if ctx.extracao else []) + de_servico
    textos = dict(ctx.textos)
    for candidato in de_servico:
        # A consulta a serviço traz a própria evidência: o trecho é a resposta da FIPE,
        # e sem este texto o grounding reprovaria um valor que a fonte de fato afirma.
        textos.setdefault(candidato.source_id, candidato.quote)

    ctx.entra("reconciling")
    # Célula vence texto: numa fonte tabular, a linha percorre todas as versões e só a
    # coluna é da versão pedida. Sem isto, 17" (coluna da SRX) e 18" (coluna da SRX
    # Plus) saíam da MESMA linha e o campo virava uma divergência que não existe.
    candidatos, texto_perdeu = reconcile.preferir_celulas(candidatos)
    ctx.avisos.extend(texto_perdeu)

    # Evidência da versão vence evidência de linha, entre fontes diferentes. O escopo
    # sai da URL do snapshot, a mesma função que `consultar_preco_oficial` usa: uma
    # fonte só é "da versão" se ela mesma é da versão.
    escopos = {s.source_id: _escopo_do_snapshot(s, ctx.versao) for s in ctx.snapshots}
    if ctx.resolucao and ctx.resolucao.matched_version:
        escopos = {
            s.source_id: _escopo_do_snapshot(s, ctx.resolucao.matched_version)
            for s in ctx.snapshots
        }
    candidatos, linha_perdeu = reconcile.preferir_especifico_da_versao(candidatos, escopos)
    ctx.avisos.extend(linha_perdeu)

    # Atribuição por seção: a linha vigente que o resolvedor trouxe é o que permite saber
    # que `"• Rodas de liga leve 18”"` está no bloco da Trail Boss e não no da versão
    # pedida. Sem os nomes das outras versões, esse bullet é indistinguível de um acerto.
    if ctx.resolucao and ctx.resolucao.matched_version:
        outras = [
            v.nome_exato
            for v in ctx.resolucao.lineup
            if v.nome_exato and v.nome_exato != ctx.resolucao.matched_version
        ]
        candidatos, fora_da_secao = reconcile.filtrar_por_secao(
            candidatos,
            textos=textos,
            alvo=ctx.resolucao.matched_version,
            outras=outras,
        )
        ctx.avisos.extend(fora_da_secao)

    from pipeline.identity import VehicleTarget

    resultado = reconcile.reconciliar(
        candidatos,
        textos=textos,
        campos=[c.split(".", 1)[-1] for c in campos],
        sources_checked=ctx.sources_checked,
        target=VehicleTarget(ctx.marca, ctx.modelo, ctx.versao, ctx.ano),
    )
    ctx.reconciliacao = resultado
    return resultado


# ------------------------------------------------------------------------ montagem
def _meta_de(ctx: JobContext) -> SpecMeta:
    resolucao = ctx.resolucao
    return SpecMeta(
        generated_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        job_id=ctx.job_id or f"job:{ctx.version_id or ctx.versao}",
        version_resolution={
            "status": resolucao.status if resolucao else "encontrada",
            "matched_version": resolucao.matched_version if resolucao else None,
            "alternatives": list(resolucao.alternatives) if resolucao else [],
        },
        sources_checked=ctx.sources_checked,
    )


def montar_ficha(ctx: JobContext, campos: list[str]) -> StandardSpec:
    """Monta a `StandardSpec` a partir das decisões, sem reinterpretar nenhuma."""
    spec = empty_spec(job_id=ctx.job_id, sources_checked=ctx.sources_checked)
    spec.meta = _meta_de(ctx)
    if ctx.reconciliacao is None:
        return spec
    for caminho in campos:
        nome = caminho.split(".", 1)[-1]
        decisao = ctx.reconciliacao.decisoes.get(nome)
        if decisao is not None:
            spec.set(caminho, decisao.spec)
    return spec


def _ficha_de_versao_inexistente(ctx: JobContext) -> StandardSpec:
    """Versão inexistente: ficha vazia com o motivo, não ficha com valores de outra versão.

    O erro tentador aqui é devolver a ficha da versão mais parecida. Isso põe dado certo
    de um veículo na resposta sobre outro — e a resposta pareceria boa.
    """
    spec = empty_spec(
        job_id=ctx.job_id,
        status=Status.NAO_ENCONTRADO,
        sources_checked=ctx.sources_checked,
    )
    spec.meta = _meta_de(ctx)
    return spec


# ----------------------------------------------------------------------------- run
def run(
    marca: str,
    modelo: str,
    versao: str,
    *,
    atributos: list[str] | None = None,
    replay: bool = True,
    version_id: str = "",
    job_id: str = "",
    persistir: bool = False,
    contexto: list[Any] | None = None,
) -> StandardSpec:
    """Roda o job de ponta a ponta e devolve a ficha padronizada.

    `contexto` e uma lista opcional onde o `JobContext` e depositado. Existe porque o
    retorno e a **ficha** — que e o que 99% dos chamadores querem — e quem precisa dos
    avisos e do resultado da gravacao (a CLI, o worker) nao deveria ter de reimplementar
    os estagios para chegar neles.

    É a função que `pipeline/eval/run.py` chama: a partir daqui o eval mede o pipeline de
    verdade, e não mais a ficha vazia.
    """
    # O `version_id` que o pipeline usa e a **chave do snapshot**
    # (`ford_ranger_raptor_2026`), nao o `versions.id` do banco. As duas identidades
    # existem, e quem chama nao deveria ter de saber qual delas o pipeline quer: se o id
    # recebido nao corresponde a nenhum snapshot, ele e inferido de marca+modelo+versao.
    #
    # Os dois defeitos que isto corrige, os dois silenciosos:
    #   * sem `version_id`, o worker rodava sem fonte nenhuma e concluia com UM campo;
    #   * com o `versions.id` do banco, o `refresh` comparava a ficha gravada contra uma
    #     ficha VAZIA e gerava 29 alertas de "campo virou None" sobre snapshots
    #     identicos — exatamente o oposto do que o Radar promete.
    if not version_id or not _tem_snapshot(version_id):
        inferido = _version_id_provavel(marca, modelo, versao)
        if inferido:
            version_id = inferido

    ctx = JobContext(
        marca=marca,
        modelo=modelo,
        versao=versao,
        version_id=version_id or "",
        replay=replay,
        atributos=atributos,
        job_id=job_id or f"job:{version_id or versao}",
    )
    ctx._decorrido()  # marca o início
    if contexto is not None:
        contexto.append(ctx)
    campos = campos_alvo(atributos)

    resolucao = resolver_versao(ctx)
    if resolucao.status != "encontrada":
        ctx.entra("versao_inexistente" if resolucao.status == "versao_inexistente" else "done")
        return _ficha_de_versao_inexistente(ctx)

    buscar_fontes(ctx)
    extrair(ctx, campos)
    consultar_comerciais(ctx)
    consultar_consumo(ctx)
    consultar_preco_oficial(ctx)
    reconciliar(ctx, campos)
    spec = montar_ficha(ctx, campos)
    ctx.entra("done")

    if persistir:
        from pipeline.persist import persistir_ficha

        # O resultado fica no contexto: quem chama pela CLI precisa **ver** se gravou.
        # Gravação que falha em silêncio é pior que não gravar — o usuário acha que tem
        # ficha no banco e não tem. Foi o que aconteceu no primeiro `--persistir`: 25
        # linhas gravadas, exceção no meio, transação revertida, e o comando imprimiu
        # "30 campos com valor" como se tudo tivesse ido bem.
        ctx.persistencia = persistir_ficha(ctx, spec)
    return spec


__all__ = [
    "ESTAGIOS",
    "FINAIS",
    "FIXTURES",
    "JobContext",
    "campos_alvo",
    "campos_canonicos",
    "documentos_de",
    "run",
]


# ------------------------------------------------------------------------------- CLI
def main(
    *,
    marca: str,
    modelo: str,
    versao: str,
    atributos: list[str] | None = None,
    replay: bool = True,
    version_id: str = "",
    persistir: bool = False,
    saida: str = "resumo",
) -> int:
    """`specradar extract` — roda o job e imprime o resultado.

    `saida="resumo"` mostra os campos com valor, um por linha, com status e confiança.
    `saida="json"` imprime a `StandardSpec` **validada** contra o schema canônico: a
    validação é o ponto, porque uma ficha que não valida não deve sair para ninguém.

    Devolve 0 quando a versão foi resolvida; **2** quando não existe na linha vigente.
    Não é erro de execução (o resolvedor respondeu), mas quem chama de script precisa
    distinguir "rodou e a versão não existe" de "rodou e achou".
    """
    if replay:
        os.environ.setdefault("REPLAY_MODE", "1")
        os.environ.setdefault("LLM_FAKE", "1")

    contexto: list[Any] = []
    spec = run(
        marca,
        modelo,
        versao,
        atributos=atributos or None,
        replay=replay,
        version_id=version_id,
        persistir=persistir,
        contexto=contexto,
    )
    ctx_usado = contexto[0] if contexto else None

    if saida == "json":
        print(spec.to_json(indent=2))
    else:
        com_valor = [(c, campo) for c, campo in spec.itens() if campo.value is not None]
        resolucao = spec.meta.version_resolution
        print(f"{marca} {modelo} {versao}")
        print(
            f"  resolucao: {resolucao.status}"
            + (f" -> {resolucao.matched_version}" if resolucao.matched_version else "")
        )
        if resolucao.alternatives:
            print(f"  alternativas: {', '.join(resolucao.alternatives)}")
        print(f"  fontes consultadas: {len(spec.meta.sources_checked)}")
        print(f"  campos com valor: {len(com_valor)}")
        for caminho, campo in com_valor:
            print(
                f"    {caminho:38} {str(campo.value)[:44]:46} {campo.status} {campo.confidence:.2f}"
            )

    if persistir:
        gravacao = getattr(ctx_usado, "persistencia", None)
        if gravacao is None:
            print("  gravacao: nao executada")
        else:
            print(
                f"  gravacao: {gravacao.spec_values} valor(es), "
                f"{gravacao.evidences} evidencia(s), {gravacao.extractions} extracao(oes), "
                f"{gravacao.snapshots} snapshot(s)"
            )
            for erro in gravacao.erros:
                print(f"    ERRO: {erro}")

    return 0 if spec.meta.version_resolution.status == "encontrada" else 2


def _version_id_provavel(marca: str, modelo: str, versao: str) -> str:
    """Adivinha o `version_id` dos snapshots a partir de marca/modelo/versao.

    Em replay o `version_id` e a chave dos snapshots salvos, e quem chama pela CLI nao o
    conhece. A cobertura e medida na direcao **id coberto pelo pedido**, e nao o
    contrario: o id `ford_ranger_raptor_2026` tem quatro tokens e o pedido tem nove
    ("Ford Ranger Raptor 3.0 V6 Bi-turbo 4WD AT"). Medindo ao contrario, a cobertura fica
    em 0,33 e nenhum id passa — foi o que aconteceu, e o `extract` da CLI voltava com um
    campo so, sem nenhum erro.

    O **alias de marca** e expandido antes de medir: a chave do snapshot da Amarok e
    `vw_amarok_v6_extreme_2026` e o pedido diz "Volkswagen". Sem a expansao, a cobertura
    fica em 0,60 (tres de cinco tokens), o id e rejeitado, e `specradar extract Volkswagen
    Amarok "V6 Extreme" --replay` volta com **um campo** — o do FIPE, que tem conector
    proprio — sem erro nenhum. O mesmo vale para `gm`/`Chevrolet`. Baixar o limiar de 0,75
    resolveria este caso e abriria a porta para ler o veiculo errado, que e o defeito que
    o limiar existe para impedir.

    Exige **maximo unico**: dois ids igualmente cobertos devolvem vazio, e o pipeline
    segue sem snapshot em vez de ler o veiculo errado.
    """
    from pipeline import matching
    from pipeline.connectors import ALIASES
    from pipeline.connectors.base import normalizar_versao
    from pipeline.store import versoes_disponiveis

    disponiveis = versoes_disponiveis()
    if not disponiveis:
        return ""

    def expandir(texto: str) -> list[str]:
        """Tokens com o alias de marca ja canonizado, nos **dois** lados da medida."""
        return [
            t
            for bruto in normalizar_versao(texto).split()
            for t in normalizar_versao(ALIASES.get(bruto, bruto)).split()
        ]

    pedido = expandir(f"{marca} {modelo} {versao}")
    pontos: list[tuple[float, str]] = []
    for vid in disponiveis:
        pontos.append((matching.cobertura(expandir(vid.replace("_", " ")), pedido), vid))

    melhor = max(p for p, _ in pontos)
    if melhor < COBERTURA_MINIMA_DO_ID:
        return ""
    empatados = [vid for p, vid in pontos if p == melhor]
    return empatados[0] if len(empatados) == 1 else ""


def _tem_snapshot(version_id: str) -> bool:
    """Este `version_id` corresponde a algum snapshot salvo?

    A pergunta existe porque o mesmo veiculo tem duas identidades: a chave do snapshot
    (`ford_ranger_raptor_2026`) e o `versions.id` do banco. Sem a checagem, um id valido
    do banco passava direto e a extracao rodava sem fonte alguma.
    """
    if not version_id:
        return False
    from pipeline.store import versoes_disponiveis

    try:
        return version_id in set(versoes_disponiveis())
    except Exception:  # pragma: no cover - sem diretorio de snapshots
        return False
