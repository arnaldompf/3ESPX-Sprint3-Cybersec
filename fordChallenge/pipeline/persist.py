"""Persistência da ficha: `spec_values`, `evidences` e `extractions`.

Três decisões moldam este módulo, e todas as três são sobre **não perder informação**:

* **a evidência é gravada antes do valor**, e o valor aponta para ela. Um `spec_value`
  sem `evidence_id` seria um número sem procedência no banco — exatamente o que o produto
  promete não existir. Se a evidência falhar, o valor não entra;
* **`divergente` grava mais de uma linha** em `spec_values`. Não há `UNIQUE (version_id,
  field)` na tabela justamente por isso (ver o docstring do modelo): forçar unicidade
  empurraria o sistema a escolher um vencedor em silêncio;
* **o custo da extração é gravado** mesmo quando é zero. "Custou R$ 0,00" com
  `LLM_FAKE=1` é um fato medido; sem a linha em `extractions`, seria uma alegação.

O módulo é tolerante à **ausência de banco**: em replay e nos testes o `DATABASE_URL`
aponta para um SQLite descartável, e o eval roda sem persistir nada. Persistir é efeito
colateral do job, não condição para ele ter resultado.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pipeline.schema import STATUS_COM_EVIDENCIA, StandardSpec, Status

if TYPE_CHECKING:  # pragma: no cover - só para tipo
    from pipeline.run import JobContext

log = logging.getLogger(__name__)


@dataclass
class ResultadoPersistencia:
    """O que foi gravado, contado por tabela — e o que não deu, com o motivo."""

    spec_values: int = 0
    evidences: int = 0
    extractions: int = 0
    alerts: int = 0
    snapshots: int = 0
    """Linhas de `snapshots` gravadas. Contam **em replay** também: é o que faz o elo 5
    do "Por quê?" mostrar sha256 e data em vez do motivo de estar vazio."""
    erros: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.erros

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_values": self.spec_values,
            "evidences": self.evidences,
            "extractions": self.extractions,
            "alerts": self.alerts,
            "snapshots": self.snapshots,
            "erros": list(self.erros),
        }


def _sessao():
    """Abre sessão do banco. Devolve `None` quando não há banco configurado."""
    try:
        from api.app.db import session_scope

        return session_scope()
    except Exception as exc:  # pragma: no cover - sem banco no ambiente
        log.debug("persist.sem_banco", extra={"erro": str(exc)})
        return None


@dataclass
class LinhaDeValor:
    """Uma linha de `spec_values`, com o que ela precisa e nada mais.

    Existe porque `SpecField` e `Conflict` **não** têm a mesma forma: o conflito carrega
    só `value` e `evidence`, sem `unit`, `status` nem `confidence`. Tratá-los como iguais
    quebrou a gravação com `AttributeError` em `unit` — e quebrou **depois** de já ter
    gravado 25 linhas, o que deixaria a ficha pela metade no banco se a transação não
    fosse revertida.
    """

    campo: str
    valor: Any
    unidade: str | None
    status: str
    confianca: float
    evidencia: Any


def _valores_a_gravar(spec: StandardSpec) -> list[LinhaDeValor]:
    """As linhas que vão a `spec_values`, uma por valor.

    Um campo `divergente` rende **uma linha por valor concorrente**, cada uma com a sua
    própria evidência. É o que permite a tela mostrar "a fonte A diz X, a fonte B diz Y"
    lendo o banco, em vez de recalcular a divergência a cada consulta. O valor concorrente
    herda `status` e `unit` do campo — é o mesmo campo, visto por outra fonte.
    """
    linhas: list[LinhaDeValor] = []
    for caminho, campo in spec.itens():
        nome = caminho.split(".", 1)[-1]
        principal = campo.evidences[0] if campo.evidences else None
        linhas.append(
            LinhaDeValor(
                campo=nome,
                valor=campo.value,
                unidade=campo.unit,
                status=str(campo.status),
                confianca=float(campo.confidence or 0.0),
                evidencia=principal,
            )
        )
        if campo.status is Status.DIVERGENTE:
            for conflito in campo.conflicts:
                linhas.append(
                    LinhaDeValor(
                        campo=nome,
                        valor=conflito.value,
                        unidade=campo.unit,
                        status=str(campo.status),
                        confianca=float(campo.confidence or 0.0),
                        evidencia=conflito.evidence,
                    )
                )
    return linhas


def resolver_version_id(sessao, ctx: JobContext) -> str | None:
    """O `versions.id` do banco a partir da identidade do job.

    Existe porque o pipeline e o banco chamam a mesma versao por nomes diferentes: em
    replay o `ctx.version_id` e a chave do **snapshot** (`ford_ranger_raptor_2026`),
    enquanto `versions.id` e um id gerado pelo seed. Persistir com a chave do snapshot
    criaria linhas com `version_id` que nenhuma consulta da API encontra — a ficha ficaria
    gravada e invisivel.

    O casamento e por **nome exato** de (marca, modelo, versao), que e o que o resolvedor
    ja devolveu em `matched_version`. Nao ha fuzzy aqui de proposito: gravar a ficha do
    veiculo errado e pior que nao gravar, e o resolvedor ja fez o trabalho de casar o
    nome antes.

    A segunda tentativa, pelo **nome canonico** (`pipeline/version_names.py`), tambem nao e
    fuzzy: e a mesma funcao deterministica que o catalogo aplica ao gravar. Ela existe
    porque as duas pontas escrevem o mesmo carro de jeitos diferentes — a pagina da GM diz
    "S10 High Country" e o catalogo, desde a migracao 0006, guarda "High Country". Sem ela,
    a ficha da S10 saia do pipeline com 17 campos e nao era gravada em lugar nenhum: o
    `extract` imprimia os valores e o banco ficava vazio, que foi o defeito medido.
    """
    from sqlmodel import select

    from api.app.models import Brand, VehicleModel, Version
    from pipeline.version_names import chave_de_versao

    if ctx.version_id:
        explicit = sessao.get(Version, ctx.version_id)
        if explicit is not None:
            return explicit.id if not ctx.ano or explicit.ano_modelo == ctx.ano else None

    nome = (ctx.resolucao.matched_version if ctx.resolucao else "") or ctx.versao
    do_modelo = (
        select(Version)
        .join(VehicleModel, VehicleModel.id == Version.model_id)
        .join(Brand, Brand.id == VehicleModel.brand_id)
        .where(Brand.nome == ctx.marca, VehicleModel.nome == ctx.modelo)
    )
    if ctx.ano:
        do_modelo = do_modelo.where(Version.ano_modelo == ctx.ano)

    linha = sessao.exec(do_modelo.where(Version.nome_exato == nome)).first()
    if linha is not None:
        return linha.id

    procurada = chave_de_versao(ctx.modelo, nome)
    candidatas = [
        v
        for v in sessao.exec(do_modelo).all()
        if chave_de_versao(ctx.modelo, v.nome_exato) == procurada
    ]
    # Duas linhas com a mesma chave canonica so existem em banco nao migrado. Escolher uma
    # seria gravar a ficha num dos dois registros por sorteio; nao escolher deixa o erro
    # aparecer com o nome do veiculo, que e o que leva alguem a rodar a migracao.
    return candidatas[0].id if len(candidatas) == 1 else None


#: Domínios cuja indisponibilidade é **conhecida e declarada**, para a fonte bloqueada
#: entrar no banco com o motivo em vez de virar um `nao_encontrado` sem explicação.
MOTIVO_PADRAO_DE_BLOQUEIO = "fonte respondeu 403/CAPTCHA/paywall; registrada, nunca contornada"


def _dominio(url: str) -> str:
    """`https://media.gm.com/brasil` -> `media.gm.com`. Sem `urlparse` por uma linha."""
    sem_esquema = url.split("://", 1)[-1]
    return sem_esquema.split("/", 1)[0][:200]


def registrar_fontes_bloqueadas(ctx_ou_urls, version_id: str, sessao) -> int:
    """Grava a fonte bloqueada como **estado**: linha em `sources` + alerta por versão.

    Aceita o `JobContext` da extração clássica **ou** uma lista de URLs (o Pesquisador não
    tem `JobContext`; tem `Fonte`s). A regra é a mesma nos dois casos, e é por isso que a
    função é uma só.

    Existe porque `ctx.fontes_bloqueadas` só vivia em memória: o pipeline sabia que a sala
    de imprensa da GM está atrás de CAPTCHA, dizia isso no log, e **nada** disso chegava
    ao banco. A Saúde do Conhecimento (WP-33) precisa contar fonte bloqueada por versão, e
    sem persistir a informação o painel diria "0 fontes bloqueadas" — que é pior que não
    ter o indicador, porque afirma o contrário do que aconteceu.

    O alerta é do tipo `fonte_bloqueada`, um dos sete de `docs/12` §6.1 que até aqui não
    tinha emissor. Deduplicado por (tipo, versão, url): o cron roda todo dia, e uma lista
    que cresce sozinha treina o usuário a ignorá-la.
    """
    from sqlmodel import select

    from api.app.models import Alert, Source, SourceStatus

    urls = getattr(ctx_ou_urls, "fontes_bloqueadas", ctx_ou_urls)
    gravados = 0
    for url in dict.fromkeys(urls):
        fonte = sessao.exec(select(Source).where(Source.url == url)).first()
        if fonte is None:
            sessao.add(
                Source(
                    url=url[:1000],
                    tipo="desconhecido",
                    # Tier 3 e o menos comprometedor que a restricao do banco aceita
                    # (1..5) para uma fonte que nunca foi lida: chamar de tier 1 afirmaria
                    # oficialidade que ninguem verificou.
                    tier=3,
                    dominio=_dominio(url),
                    robots_ok=True,
                    status=SourceStatus.BLOQUEADA.value,
                    motivo=MOTIVO_PADRAO_DE_BLOQUEIO,
                    # Quando o pipeline **registrou** este estado. Para a sala de imprensa
                    # da GM nao houve requisicao (o conector nao pede para receber 403), e
                    # e por isso que o campo se chama "ultima checagem" e nao "ultima
                    # requisicao": o que aconteceu agora foi a avaliacao, nao o acesso.
                    ultima_checagem_em=dt.datetime.now(dt.UTC).replace(tzinfo=None),
                )
            )
        else:
            fonte.status = SourceStatus.BLOQUEADA.value
            fonte.motivo = fonte.motivo or MOTIVO_PADRAO_DE_BLOQUEIO
            sessao.add(fonte)

        ja_existe = any(
            a.field == url
            for a in sessao.exec(
                select(Alert).where(
                    Alert.type == "fonte_bloqueada",
                    Alert.version_id == version_id,
                )
            ).all()
        )
        if not ja_existe:
            sessao.add(
                Alert(
                    type="fonte_bloqueada",
                    version_id=version_id,
                    # `field` guarda a URL: o alerta e sobre a fonte, nao sobre um campo.
                    field=url[:200],
                    old=None,
                    new=None,
                    is_simulated=False,
                )
            )
            gravados += 1
    return gravados


def indice_de_snapshots(sessao, urls, *, version_id: str | None = None) -> dict:
    """Para cada URL, o snapshot já gravado: `(id, captured_at)`, a captura mais recente.

    **Por que pela URL, e não pelo id.** O `snapshot_id` que a evidência carrega vem de
    `SourceRecord.source_id` — o identificador da *fixture*, não a chave da tabela
    `snapshots`, que é gerada na gravação. A única ligação que existe entre os dois lados
    é a URL da fonte, e ela casa: na base da demo, 150 das 152 evidências têm uma linha de
    `snapshots` com exatamente a mesma URL.

    **O que quebrava sem isto** (medido em 11/09/2026):

    * `evidences.snapshot_id` nulo em todas as linhas. `spec_assembler.montar` monta
      `sources_checked` a partir desse campo, e o contador **"Fontes consultadas"** do topo
      da ficha marcava **0** nas cinco fichas — ao lado de "30 campos com valor" e de
      trinta botões "ver evidência" que abrem com URL e citação (QA-BUG-03);
    * `evidences.captured_at` no padrão da coluna, que é a hora da **gravação**. A gaveta
      dizia "Coletado em: 11/09/2026" para uma página salva em 01/09/2026, e o elo 5 do
      "Por quê?" mostrava as duas datas lado a lado — a errada por cima da certa
      (QA-BUG-04).

    A captura **mais recente** é a escolhida: a tabela guarda uma linha por
    `(url, captured_at)` porque a auditoria pergunta "o que esta URL dizia naquele dia",
    e a ficha mostra o estado de agora.
    """
    from sqlmodel import select

    from api.app.models import Snapshot as SnapshotRow

    limpas = sorted({(u or "").strip()[:1000] for u in urls if (u or "").strip()})
    if not limpas:
        return {}

    indice: dict = {}
    query = select(SnapshotRow).where(SnapshotRow.url.in_(limpas))
    # Configuradores podem compartilhar a URL entre versões, com respostas diferentes.
    # Uma captura mais nova de outra configuração não pode virar a prova desta ficha.
    if version_id is not None:
        query = query.where(SnapshotRow.version_id == version_id)
    linhas = sessao.exec(query.order_by(SnapshotRow.captured_at)).all()
    for linha in linhas:
        # Ordenado por data crescente: a última atribuição fica com a captura mais nova.
        indice[linha.url] = (linha.id, linha.captured_at)
    return indice


def registrar_snapshots(ctx: JobContext, version_id: str, sessao) -> int:
    """Grava uma linha em `snapshots` por fonte lida — **inclusive em replay**.

    Por que isto existe, e é um buraco visível na demonstração. O elo 5 do "Por quê?"
    mostra `sha256` e data de captura lendo a tabela `snapshots`
    (`materiality_service._snapshots_de`). Em replay o texto vem de fixture e **ninguém
    escrevia a linha**: `pipeline/snapshots.py:registrar_no_banco` só é chamada na coleta
    ao vivo, que em replay é justamente o que não acontece. Resultado: a cadeia abria com
    "nenhum snapshot gravado para as URLs desta evidência" — mensagem honesta, e uma
    ausência desnecessária, porque o `meta.json` de cada fixture **tem** o sha256 e a
    data.

    O que se grava é o que a fixture afirma, sem inventar nada:

    * `sha256` e `captured_at` saem do `meta.json` da fixture (é o hash do texto salvo,
      calculado por `scripts/build_fixtures.py`);
    * `text_path` aponta para o arquivo real no disco, para quem quiser reconferir;
    * `http_status` só entra se o `meta.json` o registrar.

    Deduplicado por `(url, captured_at)` — o índice que a tabela já tem, e a pergunta que
    a auditoria faz: "o que esta URL dizia naquele dia". Rodar o `extract` duas vezes não
    duplica linha.
    """
    gravados = 0
    for snap in ctx.snapshots:
        url = (snap.url or "").strip()
        if not url or not snap.meta.get("sha256"):
            # Sem URL não há o que auditar; sem sha256, a linha seria um registro sem a
            # única informação que ela existe para carregar.
            continue
        if gravar_snapshot(
            sessao,
            url=url,
            tier=snap.tier,
            tipo=str(snap.tipo or "desconhecido"),
            captured_at=_data_do_snapshot(snap),
            sha256=str(snap.meta["sha256"]),
            text_path=str(snap.caminho / snap.meta.get("text_path", "")),
            http_status=snap.meta.get("http_status"),
            version_id=version_id,
        ):
            gravados += 1
    return gravados


def gravar_snapshot(
    sessao,
    *,
    url: str,
    tier: int,
    tipo: str,
    captured_at: dt.datetime,
    sha256: str,
    text_path: str | None,
    http_status: int | None,
    version_id: str,
) -> bool:
    """Uma linha em `snapshots` (e a `Source`, se ainda não existir). `False` se já havia.

    Deduplicado por `(url, captured_at)` — o índice que a tabela já tem, e a pergunta que
    a auditoria faz: "o que esta URL dizia naquele dia". Gravar duas vezes não duplica.
    A extração clássica chama isto por fixture; o Pesquisador, por página baixada.
    """
    from sqlmodel import select

    from api.app.models import Snapshot as SnapshotRow
    from api.app.models import Source, SourceStatus

    url = (url or "").strip()[:1000]
    if not url or not sha256:
        return False

    ja_existe = sessao.exec(
        select(SnapshotRow).where(
            SnapshotRow.url == url,
            SnapshotRow.captured_at == captured_at,
            SnapshotRow.sha256 == sha256,
            SnapshotRow.version_id == version_id,
        )
    ).first()
    if ja_existe is not None:
        # Recuperação de uma cópia antes ausente: mesma URL/versão/data/conteúdo.
        # Não troca a identidade da captura nem reaponta para outra revisão.
        if text_path and not ja_existe.text_path:
            import hashlib
            from pathlib import Path

            restored = Path(text_path)
            if restored.is_file() and hashlib.sha256(restored.read_bytes()).hexdigest() == sha256:
                ja_existe.text_path = str(restored)
                sessao.add(ja_existe)
        return False

    fonte = sessao.exec(select(Source).where(Source.url == url)).first()
    if fonte is None:
        fonte = Source(
            url=url,
            tipo=str(tipo or "desconhecido")[:50],
            tier=max(1, min(5, int(tier))),
            dominio=_dominio(url),
            robots_ok=True,
            status=SourceStatus.ATIVA.value,
            ultima_checagem_em=captured_at,
        )
        sessao.add(fonte)
        sessao.flush()

    sessao.add(
        SnapshotRow(
            source_id=fonte.id,
            version_id=version_id,
            url=url,
            captured_at=captured_at,
            text_path=(str(text_path)[:500] if text_path else None),
            sha256=str(sha256)[:64],
            http_status=http_status,
        )
    )
    return True


def gravar_extracao(
    sessao,
    *,
    version_id: str,
    modelo_llm: str,
    tokens_entrada: int,
    tokens_saida: int,
    custo_usd: float,
    job_id: str | None = None,
) -> str:
    """Uma linha em `extractions`: o custo da leitura, mesmo quando é zero."""
    from api.app.models import Extraction

    linha = Extraction(
        job_id=job_id or None,
        version_id=version_id,
        modelo_llm=(modelo_llm or "fixture")[:120],
        tokens_entrada=int(tokens_entrada),
        tokens_saida=int(tokens_saida),
        custo_usd=float(custo_usd),
    )
    sessao.add(linha)
    sessao.flush()
    return linha.id


@dataclass
class Fusao:
    """O que uma pesquisa fez com a ficha que já existia — campo a campo.

    Cinco números, porque são cinco coisas diferentes de dizer a quem lê: **preenchi** um
    vazio, **substituí** o que uma pesquisa anterior tinha posto, **mantive** o que veio da
    coleta dirigida, achei o **mesmo** valor (e não duplico a linha) ou achei um valor
    **diferente** do que a fonte melhor diz — e aí as duas linhas ficam, e a ficha mostra
    `divergente`.
    """

    preenchidos: int = 0
    substituidos: int = 0
    mantidos: int = 0
    iguais: int = 0
    divergencias: int = 0
    evidencias: int = 0
    linhas: int = 0
    """Linhas de `spec_values` efetivamente escritas. Os cinco contadores acima falam de
    **campos** (é o que a conversa mostra); este fala de linhas, que é o que a tabela tem —
    um campo divergente rende uma linha por valor concorrente."""
    removidas: int = 0
    """Linhas de pesquisa anterior que saíram para as novas entrarem."""
    erros: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "preenchidos": self.preenchidos,
            "substituidos": self.substituidos,
            "mantidos": self.mantidos,
            "iguais": self.iguais,
            "divergencias": self.divergencias,
            "evidencias": self.evidencias,
            "linhas": self.linhas,
            "removidas": self.removidas,
            "erros": list(self.erros),
        }

    @property
    def gravados(self) -> int:
        """Campos que a pesquisa mexeu: preencheu, substituiu ou pôs ao lado."""
        return self.preenchidos + self.substituidos + self.divergencias


def mesmo_valor(a: Any, b: Any) -> bool:
    """Dois valores dizem a mesma coisa?

    Existe porque "igual" numa ficha não é `==`: `470` e `470.0` são o mesmo torque,
    `"Diesel"` e `" diesel"` o mesmo combustível, e `["abs", "ebd"]` e `["ebd", "abs"]` a
    mesma lista de itens. Sem isto, a pesquisa gravaria uma linha nova a cada rodada para
    o mesmo número — e a ficha mostraria "divergente" contra ela mesma.
    """
    if a is None or b is None:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)), abs(float(b)))
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        return sorted(_texto_comparavel(x) for x in a) == sorted(_texto_comparavel(x) for x in b)
    return _texto_comparavel(a) == _texto_comparavel(b)


def _texto_comparavel(valor: Any) -> str:
    import unicodedata

    bruto = unicodedata.normalize("NFKD", str(valor)).strip().casefold()
    return "".join(c for c in bruto if not unicodedata.combining(c))


def origem_das_linhas(sessao, linhas: list) -> dict[str, str]:
    """Para cada `spec_values.id`, de onde ele veio: `pesquisa` ou `dirigida`.

    A diferença decide o que pode ser substituído. Uma linha de **pesquisa anterior** é
    descartável: a pesquisa nova viu as mesmas fontes, ou melhores. Uma linha de **coleta
    dirigida** (o conector da montadora, o gabarito) não é: ela veio de uma fonte tier 1
    escolhida a dedo, e apagá-la para pôr uma matéria de revista no lugar é trocar o melhor
    pelo disponível.

    O caminho é `SpecValue.extraction_id → Extraction.job_id → Job.tipo`. Sem `extraction`
    ou sem `job`, é dirigida — é o que o `seed` do gabarito produz.
    """
    from sqlmodel import select

    from api.app.models import Extraction, Job

    ids = {linha.extraction_id for linha in linhas if linha.extraction_id}
    de_pesquisa: set[str] = set()
    if ids:
        for extraction_id, tipo in sessao.exec(
            select(Extraction.id, Job.tipo)
            .join(Job, Job.id == Extraction.job_id, isouter=True)
            .where(Extraction.id.in_(ids))
        ).all():
            if (tipo or "") == "research":
                de_pesquisa.add(extraction_id)
    return {
        linha.id: ("pesquisa" if linha.extraction_id in de_pesquisa else "dirigida")
        for linha in linhas
    }


def fundir_valores(
    sessao,
    *,
    version_id: str,
    spec: StandardSpec,
    snapshots: dict,
    extraction_id: str | None = None,
    require_source_proof: bool = False,
    rejected_evidences: dict[str, str] | None = None,
) -> Fusao:
    """Reconcilia a ficha com a decisão anterior pela política compartilhada.

    Vazio não apaga valor. Autoridade e aplicabilidade decidem a publicação;
    a origem pesquisa não concede permissão de substituir. Observações e decisões
    ficam no histórico; spec_values é a projeção atual, gravada na mesma transação."""
    import hashlib
    import json

    from sqlmodel import select

    from api.app.models import Brand, FieldDecision, FieldObservation, VehicleModel, Version
    from api.app.models import Evidence as EvidenceRow
    from api.app.models import Snapshot as SnapshotRow
    from pipeline.identity import VehicleTarget
    from pipeline.publication import POLICY_VERSION, choose, from_rows
    from pipeline.schema import SpecField

    # Serializa escritores desta versão no Postgres; SQLite serializa a transação de escrita.
    if sessao.get_bind().dialect.name == "sqlite":
        from sqlalchemy import update

        sessao.exec(
            update(Version)
            .where(Version.id == version_id)
            .values(identidade_estado=Version.identidade_estado)
        )
    else:
        sessao.exec(select(Version).where(Version.id == version_id).with_for_update()).first()
    fusao = Fusao()
    version = sessao.get(Version, version_id)
    model = sessao.get(VehicleModel, version.model_id) if version else None
    brand = sessao.get(Brand, model.brand_id) if model else None
    target = (
        VehicleTarget(brand.nome, model.nome, version.nome_exato, version.ano_modelo)
        if version and model and brand
        else None
    )
    existentes = _por_campo(sessao, version_id)
    source_texts: dict[str, str] = {}
    snapshot_texts: dict[str, str] = {}
    for path, incoming in spec.itens():
        campo = path.split(".", 1)[-1]
        incoming = incoming.model_copy(deep=True)
        for evidence in [*incoming.evidences, *(c.evidence for c in incoming.conflicts)]:
            explicit = (
                sessao.get(SnapshotRow, evidence.snapshot_id) if evidence.snapshot_id else None
            )
            snapshot = (
                (explicit.id, explicit.captured_at)
                if explicit
                and explicit.url == evidence.source_url
                and explicit.version_id == version_id
                else snapshots.get(evidence.source_url.strip()[:1000])
            )
            if snapshot:
                evidence.snapshot_id = snapshot[0]
                if snapshot[1] is not None:
                    evidence.captured_at = snapshot[1].isoformat()
            else:
                evidence.snapshot_id = None
            evidence.evidence_id = _materializar_evidencia(sessao, evidence, snapshots, fusao)
        rows = existentes.get(campo, [])
        previous = from_rows(
            [(r, sessao.get(EvidenceRow, r.evidence_id) if r.evidence_id else None) for r in rows],
            campo,
        )
        latest = sessao.exec(
            select(FieldDecision)
            .where(FieldDecision.version_id == version_id, FieldDecision.field == campo)
            .order_by(FieldDecision.criado_em.desc(), FieldDecision.id.desc())
        ).first()
        if latest:
            previous = SpecField.model_validate(latest.payload)
        ids = []
        for label, cell in [("pendente_reavaliacao", previous), ("validada_pipeline", incoming)]:
            if cell.value is None and not cell.evidences:
                continue
            payload = cell.model_dump(mode="json")
            key_payload = {
                "version": version_id,
                "field": campo,
                "value": cell.value,
                "status": str(cell.status),
                "evidence": sorted(
                    (e.source_url, e.quote, e.raw_value or "") for e in cell.evidences
                ),
                "conflicts": sorted(
                    (repr(c.value), c.evidence.source_url, c.evidence.quote) for c in cell.conflicts
                ),
            }
            fingerprint = hashlib.sha256(
                json.dumps(key_payload, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            obs = sessao.exec(
                select(FieldObservation).where(FieldObservation.fingerprint == fingerprint)
            ).first()
            if obs is None:
                obs = FieldObservation(
                    version_id=version_id,
                    field=campo,
                    fingerprint=fingerprint,
                    payload=payload,
                    validation=label,
                    reason="envelope recebido na publicação",
                )
                sessao.add(obs)
                sessao.flush()
            ids.append(obs.id)
        cells = [previous, incoming] if rows else [incoming]
        # A citação não contém necessariamente o título "Kit Opcional" acima dela.
        # Reavalie também o contexto original, com hash, ao projetar a ficha.
        for cell in cells:
            for evidence in [*cell.evidences, *(c.evidence for c in cell.conflicts)]:
                if evidence.evidence_id in source_texts:
                    continue
                record = sessao.get(EvidenceRow, evidence.evidence_id)
                snapshot_id = record.snapshot_id if record else None
                snapshot_row = sessao.get(SnapshotRow, snapshot_id) if snapshot_id else None
                if snapshot_id and snapshot_id not in snapshot_texts:
                    from pathlib import Path

                    file = (
                        Path(snapshot_row.text_path)
                        if snapshot_row and snapshot_row.text_path
                        else None
                    )
                    content = file.read_text(encoding="utf-8") if file and file.is_file() else ""
                    snapshot_texts[snapshot_id] = (
                        content
                        if snapshot_row
                        and hashlib.sha256(content.encode()).hexdigest() == snapshot_row.sha256
                        else ""
                    )
                if snapshot_id:
                    source_texts[evidence.evidence_id] = (
                        snapshot_texts.get(snapshot_id, "")
                        if snapshot_row
                        and snapshot_row.version_id in {None, version_id}
                        and snapshot_row.url == evidence.source_url
                        else ""
                    )
        decision = choose(
            campo,
            cells,
            target=target,
            source_texts=source_texts,
            require_source_proof=require_source_proof,
            rejected_evidences=rejected_evidences,
        )
        payload = decision.model_dump(mode="json")
        if latest and latest.payload == payload:
            fusao.mantidos += int(previous.value is not None)
            fusao.iguais += 1
            continue
        sessao.add(
            FieldDecision(
                version_id=version_id,
                field=campo,
                policy_version=POLICY_VERSION,
                payload=payload,
                observation_ids=sorted(set(ids)),
            )
        )
        # Reescreve apenas a projeção. Observações, decisões e evidências antigas ficam.
        for row in rows:
            sessao.delete(row)
            fusao.removidas += 1
        projected = StandardSpec.model_validate(spec.model_dump())
        projected.set(path, decision)
        to_write = [r for r in _valores_a_gravar(projected) if r.campo == campo]
        for row in to_write:
            _gravar_uma(sessao, version_id, row, snapshots, extraction_id, fusao)
        if decision.status == Status.DIVERGENTE:
            fusao.divergencias += 1
        elif previous.value is None and decision.value is not None:
            fusao.preenchidos += 1
        elif mesmo_valor(previous.value, decision.value):
            fusao.mantidos += int(previous.value is not None)
            fusao.iguais += int(incoming.value is not None)
        else:
            fusao.substituidos += 1
    sessao.flush()
    return fusao


def _por_campo(sessao, version_id: str) -> dict[str, list]:
    from sqlmodel import select

    from api.app.models import SpecValue

    linhas = sessao.exec(select(SpecValue).where(SpecValue.version_id == version_id)).all()
    agrupadas: dict[str, list] = {}
    for linha in linhas:
        agrupadas.setdefault(linha.field, []).append(linha)
    return agrupadas


def _apagar_linha(sessao, linha) -> None:
    """Apaga a linha e a evidência dela, quando ninguém mais aponta para essa evidência."""
    from sqlmodel import select

    from api.app.models import Evidence as EvidenceRow
    from api.app.models import SpecValue

    evidence_id = linha.evidence_id
    sessao.delete(linha)
    sessao.flush()
    if not evidence_id:
        return
    ainda_usada = sessao.exec(select(SpecValue).where(SpecValue.evidence_id == evidence_id)).first()
    if ainda_usada is not None:
        return
    evidencia = sessao.get(EvidenceRow, evidence_id)
    if evidencia is not None:
        sessao.delete(evidencia)


def _materializar_evidencia(sessao, evidencia, snapshots, fusao) -> str:
    """A decisão e a projeção apontam para a mesma evidência persistida."""
    from sqlmodel import select

    from api.app.models import Evidence as EvidenceRow
    from api.app.models import Snapshot as SnapshotRow

    # Uma decisão anterior pode vencer a nova captura da mesma URL. Sua referência
    # já materializada continua ligada ao documento em que a citação foi observada.
    linked = sessao.get(EvidenceRow, evidencia.evidence_id)
    if linked and all(
        (
            linked.snapshot_id == evidencia.snapshot_id,
            linked.source_url == evidencia.source_url,
            linked.quote == evidencia.quote,
            linked.raw_value == (evidencia.raw_value or None),
            linked.tier == evidencia.tier,
        )
    ):
        return linked.id
    explicit = sessao.get(SnapshotRow, evidencia.snapshot_id) if evidencia.snapshot_id else None
    snapshot = (
        (explicit.id, explicit.captured_at)
        if explicit and explicit.url == evidencia.source_url
        else snapshots.get(evidencia.source_url.strip()[:1000])
    )
    snapshot_id = snapshot[0] if snapshot else evidencia.snapshot_id
    existing = sessao.exec(
        select(EvidenceRow).where(
            EvidenceRow.source_url == evidencia.source_url,
            EvidenceRow.quote == evidencia.quote[:300],
            EvidenceRow.snapshot_id == snapshot_id,
            EvidenceRow.raw_value == (evidencia.raw_value or None),
            EvidenceRow.tier == evidencia.tier,
        )
    ).first()
    if existing is not None:
        return existing.id
    row = EvidenceRow(
        snapshot_id=snapshot_id,
        source_url=evidencia.source_url,
        tier=evidencia.tier,
        quote=evidencia.quote[:300],
        captured_at=snapshot[1] if snapshot else None,
        raw_value=evidencia.raw_value or None,
        page=evidencia.page,
        tipo_de_afirmacao=evidencia.tipo_de_afirmacao,
    )
    sessao.add(row)
    sessao.flush()
    fusao.evidencias += 1
    return row.id


def _gravar_uma(
    sessao,
    version_id: str,
    linha_de_valor: LinhaDeValor,
    snapshots: dict,
    extraction_id: str | None,
    fusao: Fusao,
) -> bool:
    """Uma linha de `spec_values` (com a evidência). `False` quando a regra a recusa."""
    from api.app.models import SpecValue

    evidencia = linha_de_valor.evidencia
    evidence_id = None
    if evidencia is not None:
        evidence_id = _materializar_evidencia(sessao, evidencia, snapshots, fusao)
    elif linha_de_valor.status in STATUS_COM_EVIDENCIA:
        fusao.erros.append(
            f"{linha_de_valor.campo}: status {linha_de_valor.status} exige "
            "evidência e não há; não gravado"
        )
        return False

    sessao.add(
        SpecValue(
            version_id=version_id,
            field=linha_de_valor.campo,
            value_json=linha_de_valor.valor,
            unit=linha_de_valor.unidade,
            status=linha_de_valor.status,
            confidence=linha_de_valor.confianca,
            evidence_id=evidence_id,
            extraction_id=extraction_id,
        )
    )
    fusao.linhas += 1
    return True


def gravar_valores(
    sessao,
    *,
    version_id: str,
    spec: StandardSpec,
    snapshots: dict,
    extraction_id: str | None = None,
) -> tuple[int, int, list[str]]:
    """As linhas de `spec_values` e `evidences` de uma ficha: `(valores, evidências, erros)`.

    **A regra "sem trecho não grava" mora aqui**, e só aqui: um status que exige evidência
    sem evidência é incoerência de dado, não de gravação — melhor não gravar e dizer, do que
    gravar um valor órfão. A extração clássica e o Pesquisador passam pelo mesmo portão.
    """
    from api.app.models import Evidence as EvidenceRow
    from api.app.models import SpecValue

    valores = evidencias = 0
    erros: list[str] = []
    for linha_de_valor in _valores_a_gravar(spec):
        evidencia = linha_de_valor.evidencia
        evidence_id = None
        if evidencia is not None:
            do_snapshot = snapshots.get((evidencia.source_url or "").strip()[:1000])
            ev = EvidenceRow(
                snapshot_id=do_snapshot[0] if do_snapshot else None,
                source_url=evidencia.source_url,
                tier=evidencia.tier,
                quote=evidencia.quote[:300],
                captured_at=do_snapshot[1] if do_snapshot else None,
                raw_value=(evidencia.raw_value or None),
                page=evidencia.page,
                tipo_de_afirmacao=evidencia.tipo_de_afirmacao,
            )
            sessao.add(ev)
            sessao.flush()
            evidence_id = ev.id
            evidencias += 1
        elif linha_de_valor.status in STATUS_COM_EVIDENCIA:
            erros.append(
                f"{linha_de_valor.campo}: status {linha_de_valor.status} exige "
                "evidência e não há; não gravado"
            )
            continue

        sessao.add(
            SpecValue(
                version_id=version_id,
                field=linha_de_valor.campo,
                value_json=linha_de_valor.valor,
                unit=linha_de_valor.unidade,
                status=linha_de_valor.status,
                confidence=linha_de_valor.confianca,
                evidence_id=evidence_id,
                extraction_id=extraction_id,
            )
        )
        valores += 1
    return valores, evidencias, erros


def _data_do_snapshot(snap) -> dt.datetime:
    """`captured_at` da fixture (`2026-09-01` ou ISO completo) como `datetime` ingênuo.

    Ingênuo porque a coluna é ingênua e o banco grava UTC: pendurar fuso aqui faria a
    mesma captura aparecer em dois dias diferentes conforme quem lê — o defeito de fuso
    que a WP-31 já corrigiu na tela.
    """
    bruto = str(snap.meta.get("captured_at") or snap.captured_at or "").strip()
    for formato in ("%Y-%m-%dT%H-%M-%SZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(bruto, formato)
        except ValueError:
            continue
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def persistir_ficha(ctx: JobContext, spec: StandardSpec) -> ResultadoPersistencia:
    """Grava a ficha. Sem banco, devolve zeros e registra o motivo — não levanta.

    O job já produziu resultado quando chega aqui; derrubá-lo por indisponibilidade do
    banco transformaria uma ficha pronta em nada.
    """
    resultado = ResultadoPersistencia()
    sessao = _sessao()
    if sessao is None:
        resultado.erros.append("sem banco configurado: ficha não persistida")
        return resultado

    with sessao as s:
        version_id = resolver_version_id(s, ctx)
        if version_id is None:
            # Sem linha em `versions`, a ficha nao tem onde apontar. Dizer isso e melhor
            # que gravar orfa: o `seed` (WP-03) e quem cria o catalogo, e versao nova
            # precisa entrar la antes.
            resultado.erros.append(
                f"versao {ctx.marca} {ctx.modelo} {ctx.versao!r} nao existe na tabela "
                "`versions`; rode `specradar seed` ou cadastre a versao antes de persistir"
            )
            return resultado

        try:
            extraction_id = None
            usos = list(ctx.extracao.usos if ctx.extracao else [])
            if usos:
                extraction_id = gravar_extracao(
                    s,
                    version_id=version_id,
                    modelo_llm=usos[0].modelo or "fixture",
                    tokens_entrada=sum(u.tokens_entrada for u in usos),
                    tokens_saida=sum(u.tokens_saida for u in usos),
                    custo_usd=sum(u.custo_usd for u in usos),
                )
                resultado.extractions = 1

            # Os snapshots vêm **antes** dos valores desde 11/09/2026: é deles que sai a
            # ligação `evidences.snapshot_id` e a data real da coleta. Gravá-los depois
            # deixava as duas pontas nulas (QA-BUG-03 e QA-BUG-04).
            resultado.snapshots += registrar_snapshots(ctx, version_id, s)
            s.flush()
            snapshots = indice_de_snapshots(
                s, (snap.url for snap in ctx.snapshots), version_id=version_id
            )

            fusao = fundir_valores(
                s,
                version_id=version_id,
                spec=spec,
                snapshots=snapshots,
                extraction_id=extraction_id,
                require_source_proof=True,
            )
            resultado.spec_values += fusao.linhas
            resultado.evidences += fusao.evidencias
            resultado.erros.extend(fusao.erros)

            resultado.alerts += registrar_fontes_bloqueadas(ctx, version_id, s)
            s.commit()
        except Exception as exc:  # pragma: no cover - falha de banco
            s.rollback()
            resultado.erros.append(f"falha ao persistir: {exc}")
    return resultado
