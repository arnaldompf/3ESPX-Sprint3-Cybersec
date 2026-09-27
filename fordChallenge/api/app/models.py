"""Modelo de dados do SpecRadar — `docs/02_ARQUITETURA.md` (Modelo de dados) em código.

Treze tabelas, nenhuma de "grafo": o problema é tabular e a alucinação se resolve na
extração (schema + grounding), não no armazenamento (ADR-1).

Três decisões atravessam o arquivo e explicam a forma de quase todas as colunas:

**Portabilidade Postgres/SQLite.** Dev roda em SQLite (sem Docker nesta máquina),
produção em Postgres 16. Então: `sqlalchemy.JSON` em vez de `JSONB`, chave primária
como `str` de `uuid4().hex` em vez de `UUID` nativo, e nenhum tipo `ENUM` de banco —
os vocabulários fechados moram em `StrEnum` do Python e viajam como texto. O preço é
não ter o banco validando o vocabulário; o ganho é uma migração que roda igual nos dois.

**Vocabulário emprestado, não redefinido.** `spec_values.status` usa exatamente os
valores de :class:`pipeline.schema.Status` e `spec_values.field` exatamente os nomes de
:func:`pipeline.schema.campos_canonicos`. Duplicar essas listas aqui seria criar uma
segunda fonte de verdade que envelhece em silêncio.

**Nenhum valor sem evidência.** `spec_values.evidence_id` aponta para a evidência
principal e `evidences` guarda o trecho verbatim com a URL e a data da captura. Um valor
gravado sem evidência é bug de quem escreveu, não estado válido — e é por isso que a
coluna existe desde a primeira migração, não como acréscimo posterior.

Datas: sempre `datetime` timezone-aware em UTC no lado do Python. O SQLite não guarda o
fuso, então o que volta do banco pode ser naive; converta na borda de saída, nunca
assuma que o que voltou tem `tzinfo`.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

# --------------------------------------------------------------------------------------
# Vocabulários fechados. Ficam em `StrEnum` (não em `ENUM` do banco) para a migração ser
# a mesma no Postgres e no SQLite; a coluna é `str` e recebe `.value`.
# --------------------------------------------------------------------------------------


class Role(StrEnum):
    """Papéis da matriz de permissões (`docs/12` §6.6). RBAC em runtime é da WP-04."""

    VENDEDOR = "vendedor"
    ANALISTA = "analista"
    GESTOR = "gestor"
    ADMIN = "admin"


class JobStatus(StrEnum):
    """Estados da fila (a fila é esta tabela; sem Redis — ADR-3)."""

    PENDENTE = "pendente"
    EXECUTANDO = "executando"
    CONCLUIDO = "concluido"
    FALHOU = "falhou"
    CANCELADO = "cancelado"


class SourceStatus(StrEnum):
    """Estado de uma fonte.

    `BLOQUEADA` existe para que CAPTCHA, 403 e paywall virem **estado declarado** em vez
    de gambiarra de contorno: scraping educado é regra inviolável (ADR-7), então a fonte
    que fecha a porta fica registrada como fechada e o campo vira `nao_encontrado`.
    """

    ATIVA = "ativa"
    BLOQUEADA = "bloqueada"
    ERRO = "erro"
    DESATIVADA = "desativada"


class AlertType(StrEnum):
    """Os sete tipos de alerta de `docs/12` §6.1.

    Vocabulario fechado porque a tela desenha icone por tipo e as reacoes sugeridas sao
    indexadas por ele: um tipo novo chegando como texto livre apareceria sem icone e sem
    reacao, silenciosamente.
    """

    PRECO_OFICIAL = "preco_oficial"
    PRECO_FIPE = "preco_fipe"
    VERSAO_NOVA = "versao_nova"
    VERSAO_REMOVIDA = "versao_removida"
    CAMPO_ALTERADO = "campo_alterado"
    FONTE_BLOQUEADA = "fonte_bloqueada"
    REFERENCIA_INTERNA_DIVERGENTE = "referencia_interna_divergente"


class SynonymType(StrEnum):
    """A semente tem os dois tipos e eles não se misturam.

    `CAMPO` mapeia texto livre → campo canônico ("modos de volante" → `modos_direcao`).
    `VALOR` mapeia token → forma canônica **dentro** de um campo ("Esportivo" → `sport`),
    e por isso só o tipo `VALOR` preenche `valor_canonico`.
    """

    CAMPO = "campo"
    VALOR = "valor"


def novo_id() -> str:
    """Chave primária. `uuid4().hex` como texto: portável e legível em log e URL."""
    return uuid4().hex


def agora() -> dt.datetime:
    """Instante atual em UTC, timezone-aware. Nunca `utcnow()` (devolve naive)."""
    return dt.datetime.now(dt.UTC)


# --------------------------------------------------------------------------------------
# Catálogo: marca → modelo → versão
# --------------------------------------------------------------------------------------
class FieldObservation(SQLModel, table=True):
    """Afirmação imutável, separada da projeção publicada."""

    __tablename__ = "field_observations"
    id: str = Field(default_factory=novo_id, primary_key=True)
    version_id: str = Field(foreign_key="versions.id", index=True)
    field: str = Field(index=True)
    fingerprint: str = Field(unique=True, max_length=64)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    validation: str = Field(default="pendente_reavaliacao")
    reason: str = Field(default="")
    criado_em: dt.datetime = Field(default_factory=agora)


class FieldDecision(SQLModel, table=True):
    """Histórico de decisões; a API apresenta exatamente este envelope."""

    __tablename__ = "field_decisions"
    id: str = Field(default_factory=novo_id, primary_key=True)
    version_id: str = Field(foreign_key="versions.id", index=True)
    field: str = Field(index=True)
    policy_version: str = Field(default="quality-1")
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    observation_ids: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    criado_em: dt.datetime = Field(default_factory=agora, index=True)


class Brand(SQLModel, table=True):
    """Montadora. `nome` é único porque é a chave natural usada pelo resolvedor."""

    __tablename__ = "brands"

    id: str = Field(default_factory=novo_id, primary_key=True)
    nome: str = Field(unique=True, index=True, max_length=80)
    criado_em: dt.datetime = Field(default_factory=agora)


class VehicleModel(SQLModel, table=True):
    """Modelo (nameplate). A classe não se chama `Model` para não confundir com o módulo."""

    __tablename__ = "models"
    __table_args__ = (UniqueConstraint("brand_id", "nome", name="uq_models_brand_nome"),)

    id: str = Field(default_factory=novo_id, primary_key=True)
    brand_id: str = Field(foreign_key="brands.id", index=True)
    nome: str = Field(max_length=80)
    segmento: str | None = Field(default=None, max_length=60)
    criado_em: dt.datetime = Field(default_factory=agora)


class Version(SQLModel, table=True):
    """Versão de um ano-modelo.

    `nome_exato` é o nome **como a montadora escreve**, não o que o usuário digitou: o
    resolvedor do WP-07 compara a consulta com ele e é essa distinção que permite dizer
    "GR-Sport não está na linha vigente" em vez de inventar uma equivalência.

    `in_lineup` + `lineup_checked_at` andam juntos: saber que a versão saiu de linha só
    tem valor com a data em que isso foi conferido.
    """

    __tablename__ = "versions"
    __table_args__ = (
        UniqueConstraint("model_id", "nome_exato", "ano_modelo", name="uq_versions_nome_ano"),
    )

    id: str = Field(default_factory=novo_id, primary_key=True)
    model_id: str = Field(foreign_key="models.id", index=True)
    nome_exato: str = Field(max_length=160)
    ano_modelo: int = Field(index=True)
    mercado: str = Field(default="BR", max_length=8)
    identidade_estado: str = Field(default="pendente_reavaliacao", max_length=40)
    configuracao_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    codigo_fipe: str | None = Field(default=None, max_length=40, index=True)
    in_lineup: bool = Field(default=False)
    lineup_checked_at: dt.datetime | None = Field(default=None)
    criado_em: dt.datetime = Field(default_factory=agora)


# --------------------------------------------------------------------------------------
# Coleta: fontes, snapshots, extrações, evidências
# --------------------------------------------------------------------------------------
class Source(SQLModel, table=True):
    """Fonte consultada, com o tier que gradua a confiança.

    `tier` 1–5 é o mesmo de :data:`pipeline.schema.CONFIANCA_POR_TIER`; a restrição de
    faixa fica no banco porque tier fora dela envenenaria o cálculo de confiança sem dar
    erro em lugar nenhum.
    """

    __tablename__ = "sources"
    __table_args__ = (CheckConstraint("tier BETWEEN 1 AND 5", name="ck_sources_tier"),)

    id: str = Field(default_factory=novo_id, primary_key=True)
    url: str = Field(unique=True, index=True, max_length=1000)
    tipo: str = Field(max_length=40)  # site_oficial | pdf_imprensa | tabela_fipe | midia | forum
    tier: int
    dominio: str = Field(index=True, max_length=200)
    robots_ok: bool = Field(default=False)
    status: str = Field(default=SourceStatus.ATIVA.value, index=True, max_length=20)
    motivo: str | None = Field(default=None, max_length=300)  # por que está bloqueada/erro
    ultima_checagem_em: dt.datetime | None = Field(default=None)
    criado_em: dt.datetime = Field(default_factory=agora)


class Snapshot(SQLModel, table=True):
    """Captura de uma fonte em um instante: o que foi lido, guardado em disco (ADR-4).

    `url` é repetida aqui, além de existir em `sources`, porque o índice exigido pela spec
    é `(url, captured_at)` — "o que esta URL dizia naquele dia" é a pergunta que o modo
    replay e a auditoria fazem, e ela não deve depender de um join.
    """

    __tablename__ = "snapshots"
    __table_args__ = (Index("ix_snapshots_url_captured_at", "url", "captured_at"),)

    id: str = Field(default_factory=novo_id, primary_key=True)
    source_id: str = Field(foreign_key="sources.id", index=True)
    version_id: str | None = Field(default=None, foreign_key="versions.id", index=True)
    url: str = Field(max_length=1000)
    captured_at: dt.datetime = Field(default_factory=agora)
    raw_path: str | None = Field(default=None, max_length=500)
    text_path: str | None = Field(default=None, max_length=500)
    screenshot_path: str | None = Field(default=None, max_length=500)
    sha256: str | None = Field(default=None, index=True, max_length=64)
    http_status: int | None = Field(default=None)


class Extraction(SQLModel, table=True):
    """Uma rodada de extração por LLM, com o custo que ela deu.

    Custo e tokens ficam gravados porque o ADR-5 (modelo pequeno por padrão) só se
    sustenta com medição — sem esta linha, "o projeto custou dezenas de dólares" seria
    estimativa sem base.
    """

    __tablename__ = "extractions"

    id: str = Field(default_factory=novo_id, primary_key=True)
    job_id: str | None = Field(default=None, foreign_key="jobs.id", index=True)
    version_id: str | None = Field(default=None, foreign_key="versions.id", index=True)
    modelo_llm: str = Field(max_length=120)
    prompt_versao: str | None = Field(default=None, max_length=40)
    tokens_entrada: int = Field(default=0)
    tokens_saida: int = Field(default=0)
    custo_usd: float = Field(default=0.0)
    latencia_ms: int | None = Field(default=None)
    criado_em: dt.datetime = Field(default_factory=agora)


class Evidence(SQLModel, table=True):
    """Proveniência de um valor: o trecho verbatim e onde ele estava.

    Espelha :class:`pipeline.schema.Evidence` campo a campo (`source_url`, `captured_at`,
    `raw_value`, `page`) para que persistir e serializar não exijam tradução — tradução
    entre duas formas do mesmo dado é onde a proveniência se perde.

    `offset` é a posição do `quote` no texto salvo do snapshot: é o que torna o grounding
    reconferível depois, e não apenas na hora.
    """

    __tablename__ = "evidences"

    id: str = Field(default_factory=novo_id, primary_key=True)
    snapshot_id: str | None = Field(default=None, foreign_key="snapshots.id", index=True)
    source_url: str = Field(max_length=1000)
    tier: int
    quote: str = Field(max_length=300)
    offset: int | None = Field(default=None)
    captured_at: dt.datetime = Field(default_factory=agora)
    raw_value: str | None = Field(default=None, max_length=300)
    page: int | None = Field(default=None)
    #: `declarado` / `medido` / `listado` — o que a fonte estava fazendo ao dizer o
    #: número. NULL é `desconhecido`, e é o padrão: o tipo só entra quando um termo
    #: literal do trecho verbatim o sustenta (`pipeline/claim_type.py`).
    tipo_de_afirmacao: str | None = Field(default=None, max_length=12)
    criado_em: dt.datetime = Field(default_factory=agora)

    __table_args__ = (CheckConstraint("tier BETWEEN 1 AND 5", name="ck_evidences_tier"),)


# --------------------------------------------------------------------------------------
# Ficha: valores e sinônimos
# --------------------------------------------------------------------------------------
class SpecValue(SQLModel, table=True):
    """Um campo da ficha de uma versão. É a tabela central do produto.

    `value_json` guarda o valor **canônico** (número, texto, booleano ou lista) já
    normalizado pelo WP-01; `unit`, `status` e `confidence` são colunas porque toda
    consulta filtra por elas. `status` usa o vocabulário de :class:`pipeline.schema.Status`,
    inclusive os dois vazios distintos (`nao_disponivel` ≠ `nao_encontrado`).

    Não há `UNIQUE (version_id, field)`: um campo `divergente` precisa poder ter mais de
    uma linha durante a reconciliação, e forçar unicidade aqui empurraria o sistema a
    escolher um vencedor em silêncio — exatamente o que a regra proíbe. O índice
    composto existe para a leitura; a unicidade é decisão do repositório.
    """

    __tablename__ = "spec_values"
    __table_args__ = (Index("ix_spec_values_version_field", "version_id", "field"),)

    id: str = Field(default_factory=novo_id, primary_key=True)
    version_id: str = Field(foreign_key="versions.id")
    field: str = Field(max_length=80)
    value_json: Any | None = Field(default=None, sa_column=Column("value_json", JSON))
    unit: str | None = Field(default=None, max_length=20)
    status: str = Field(max_length=20, index=True)
    confidence: float = Field(default=0.0)
    evidence_id: str | None = Field(default=None, foreign_key="evidences.id", index=True)
    extraction_id: str | None = Field(default=None, foreign_key="extractions.id", index=True)
    criado_em: dt.datetime = Field(default_factory=agora)
    atualizado_em: dt.datetime = Field(default_factory=agora)


class Synonym(SQLModel, table=True):
    """Ontologia persistida: como a fonte (ou o vendedor) escreve → campo canônico.

    `tipo` separa os dois mapeamentos que a semente carrega e que não podem se confundir:
    sinônimo de **campo** ("modos de volante" → `modos_direcao`) e sinônimo de **valor**
    ("Esportivo" → `sport`, dentro de `modos_conducao`). Só o segundo preenche
    `valor_canonico`.

    `marca` restringe o termo a uma montadora quando ele é comercial — "Terrain Management
    System" é Ford e não deve casar num Amarok.
    """

    __tablename__ = "synonyms"
    __table_args__ = (Index("ix_synonyms_termo_tipo", "termo", "tipo"),)

    id: str = Field(default_factory=novo_id, primary_key=True)
    termo: str = Field(index=True, max_length=200)
    campo_canonico: str = Field(index=True, max_length=80)
    valor_canonico: str | None = Field(default=None, max_length=120)
    marca: str | None = Field(default=None, max_length=80)
    tipo: str = Field(default=SynonymType.CAMPO.value, max_length=10)
    criado_em: dt.datetime = Field(default_factory=agora)


# --------------------------------------------------------------------------------------
# Operação: fila, usuários, alertas, auditoria
# --------------------------------------------------------------------------------------
class Job(SQLModel, table=True):
    """A fila (ADR-3: tabela no banco, um worker, sem Redis).

    `stage` guarda o passo do pipeline em que o job está (coleta, parse, extração,
    grounding, normalização, reconciliação, persistência) porque um job que morre no meio
    tem de dizer **onde** morreu; `error` guarda o motivo. O índice em `status` é o que o
    worker usa para pegar o próximo pendente.
    """

    __tablename__ = "jobs"

    id: str = Field(default_factory=novo_id, primary_key=True)
    tipo: str = Field(default="extract", max_length=40)
    status: str = Field(default=JobStatus.PENDENTE.value, index=True, max_length=20)
    stage: str | None = Field(default=None, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column("payload", JSON))
    error: str | None = Field(default=None, max_length=2000)
    tentativas: int = Field(default=0)
    criado_em: dt.datetime = Field(default_factory=agora)
    atualizado_em: dt.datetime = Field(default_factory=agora)
    iniciado_em: dt.datetime | None = Field(default=None)
    concluido_em: dt.datetime | None = Field(default=None)


class ResearchRun(SQLModel, table=True):
    """Uma pesquisa: o que se procurou, o que se achou, e o que custou.

    **Existe para que a pesquisa seja auditável depois**, e não só assistível enquanto
    acontece. A tela mostra o painel ao vivo; esta tabela é o que permite alguém voltar
    três dias depois e perguntar "de onde veio este número?" — a resposta é a trilha de
    `ResearchEvent`, com cada consulta, cada URL considerada e o motivo de cada descarte.
    """

    __tablename__ = "research_runs"

    id: str = Field(default_factory=novo_id, primary_key=True)
    marca: str = Field(max_length=80)
    modelo: str = Field(max_length=120)
    versao: str = Field(default="", max_length=200)
    version_id: str | None = Field(default=None, foreign_key="versions.id", index=True)
    """A versão do catálogo, quando a pesquisa acabou virando ficha de um veículo nosso."""
    status: str = Field(default="executando", max_length=20, index=True)
    provedor_de_busca: str = Field(default="", max_length=40)
    #: `cobertura`, `sem_progresso`, `rodadas`, `paginas` ou `tempo`. Nunca vazio: "acabou"
    #: não é resposta, e a diferença entre "a fonte não tem" e "não deu tempo" é o produto.
    motivo_da_parada: str = Field(default="", max_length=20)
    rodadas: int = Field(default=0)
    paginas: int = Field(default=0)
    consultas: int = Field(default=0)
    campos_com_valor: int = Field(default=0)
    campos_alvo: int = Field(default=0)
    segundos: float = Field(default=0.0)
    tokens: int = Field(default=0)
    custo_brl: float = Field(default=0.0)
    erro: str | None = Field(default=None, max_length=2000)
    criado_em: dt.datetime = Field(default_factory=agora)
    concluido_em: dt.datetime | None = Field(default=None)


class ResearchEvent(SQLModel, table=True):
    """Um passo de uma pesquisa. **A URL descartada entra aqui, com o motivo.**

    Mostrar só o que deu certo faria a tela parecer mais limpa e a pesquisa, menos
    conferível. Uma fonte descartada em silêncio é indistinguível de uma fonte que ninguém
    viu — e o produto inteiro se apoia em não fazer isso.
    """

    __tablename__ = "research_events"

    id: str = Field(default_factory=novo_id, primary_key=True)
    run_id: str = Field(foreign_key="research_runs.id", index=True)
    ordem: int = Field(default=0)
    tipo: str = Field(max_length=30, index=True)
    texto: str = Field(max_length=1000)
    #: FATO / INFERENCIA / SIMULACAO — a mesma convenção de `docs/13` §2 que rege a ficha.
    etiqueta: str = Field(default="FATO", max_length=12)
    rodada: int = Field(default=0)
    decorrido: float = Field(default=0.0)
    dados: dict[str, Any] = Field(default_factory=dict, sa_column=Column("dados", JSON))
    criado_em: dt.datetime = Field(default_factory=agora)


class WorkerHeartbeat(SQLModel, table=True):
    """O sinal de vida do worker. **Uma linha só**, carimbada a cada volta do laço.

    **Por que existe** (12/09/2026): um avaliador pediu o documento do cliente e a tela
    girou até desistir. O worker tinha morrido, e nada no sistema sabia disso — nem quem
    olhava a tela, nem `/health`, nem quem administra a máquina. A tela dizia "quem cuida
    da máquina precisa religar o processador de fila", que é jargão **e** inútil: a pessoa
    que lê essa frase é um vendedor.

    **Por que não deu para reaproveitar `jobs`.** `Job.atualizado_em` só se move quando
    existe job. Com a fila vazia — que é o estado normal — não há linha para carimbar, e
    "nenhum job recente" é indistinguível de "worker morto". O batimento resolve isso
    porque é gravado **mesmo sem trabalho a fazer**: é essa a informação.

    **Uma linha, `id` fixo.** Não é histórico: a pergunta é "está vivo agora?". Guardar
    uma linha por batimento encheria a tabela com dado que ninguém lê.
    """

    __tablename__ = "worker_heartbeat"

    #: Sempre `"worker"`. A chave fixa é o que torna o carimbo um UPSERT de uma linha.
    id: str = Field(default="worker", primary_key=True, max_length=20)
    visto_em: dt.datetime = Field(default_factory=agora)
    #: O PID de quem carimbou, para quem for investigar no log.
    pid: int | None = Field(default=None)
    #: Quantos jobs este processo já concluiu desde que subiu.
    jobs_concluidos: int = Field(default=0)


class User(SQLModel, table=True):
    """Usuário do sistema. É o único lugar com dado de pessoa — e só e-mail e nome (LGPD).

    `password_hash` é argon2 (nunca a senha). `role` é texto com o vocabulário de
    :class:`Role`; a matriz de permissões que consome esse papel é da WP-04.
    """

    __tablename__ = "users"

    id: str = Field(default_factory=novo_id, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=254)
    nome: str = Field(max_length=120)
    password_hash: str = Field(max_length=255)
    role: str = Field(default=Role.VENDEDOR.value, index=True, max_length=20)
    ativo: bool = Field(default=True)
    criado_em: dt.datetime = Field(default_factory=agora)
    ultimo_login_em: dt.datetime | None = Field(default=None)


class Alert(SQLModel, table=True):
    """Mudança detectada, com **as duas evidências** e o impacto comercial (WP-25).

    `old`/`new` são JSON porque o valor canônico pode ser lista. As **duas** evidências
    ficam guardadas — a do valor antigo e a do novo — e isso não é zelo: um alerta que só
    prova o valor novo obriga quem recebe a confiar na memória do sistema sobre o antigo.
    Com as duas, a mudança inteira é conferível.

    `impact_json` e `reactions_json` guardam o resultado das **regras** de
    `pipeline/radar/` (sem LLM), calculado no momento da detecção. Guardar em vez de
    recalcular na leitura é deliberado: o impacto depende da tabela de equivalentes e dos
    preços **daquele dia**, e recalcular meses depois daria outro número para o mesmo
    alerta — o histórico deixaria de ser histórico.
    """

    __tablename__ = "alerts"

    id: str = Field(default_factory=novo_id, primary_key=True)
    type: str = Field(index=True, max_length=40)
    version_id: str | None = Field(default=None, foreign_key="versions.id", index=True)
    field: str | None = Field(default=None, max_length=80)
    old: Any | None = Field(default=None, sa_column=Column("old", JSON))
    new: Any | None = Field(default=None, sa_column=Column("new", JSON))
    evidence_id: str | None = Field(default=None, foreign_key="evidences.id", index=True)
    evidence_before_id: str | None = Field(default=None, foreign_key="evidences.id", index=True)
    evidence_after_id: str | None = Field(default=None, foreign_key="evidences.id", index=True)
    impact_json: Any | None = Field(default=None, sa_column=Column("impact_json", JSON))
    reactions_json: Any | None = Field(default=None, sa_column=Column("reactions_json", JSON))
    is_simulated: bool = Field(default=False, index=True)
    """Dado de demonstração. A tela **tem** de mostrar o rótulo SIMULAÇÃO (`docs/12` §3.8)."""
    created_at: dt.datetime = Field(default_factory=agora, index=True)
    lido: bool = Field(default=False)
    tratado: bool = Field(default=False)
    tratado_em: dt.datetime | None = Field(default=None)


class InternalReference(SQLModel, table=True):
    """Referência interna da montadora: o valor que o material comercial afirma (tier 0).

    Tier **0** e não 1: é o documento do próprio cliente, e vale menos que o site oficial
    da montadora justamente porque é ele que costuma estar desatualizado — foi o que o
    slide da Raptor mostrou ("Baja" onde a ficha pública diz "Off-Road"). O produto existe
    para o vendedor descobrir isso pelo SpecRadar e não pelo cliente.

    `docs/12` §7 chama isso de **dado sensível**: é material interno da Ford, e o acesso é
    restrito a gestor e admin.
    """

    __tablename__ = "internal_references"
    __table_args__ = (
        UniqueConstraint("version_id", "field", name="uq_internal_references_versao_campo"),
    )

    id: str = Field(default_factory=novo_id, primary_key=True)
    version_id: str = Field(foreign_key="versions.id", index=True)
    field: str = Field(max_length=80, index=True)
    value_json: Any | None = Field(default=None, sa_column=Column("value_json", JSON))
    raw_value: str | None = Field(default=None, max_length=300)
    documento: str | None = Field(default=None, max_length=200)
    """De onde veio: nome do arquivo ou do slide. Sem isso, o valor não tem procedência."""
    enviado_por: str | None = Field(default=None, foreign_key="users.id")
    criado_em: dt.datetime = Field(default_factory=agora)


class Equivalent(SQLModel, table=True):
    """Concorrente → versão Ford equivalente, mantida pelo gestor (`docs/12` §6.1).

    É o que permite dizer "o gap de preço era R$ 30 mil e virou R$ 42 mil" quando o
    concorrente muda o preço. Sem a equivalência, o alerta informa a mudança e não o que
    ela significa para a Ford.

    A equivalência é **decisão comercial**, não cálculo: quem decide que a Hilux SRX Plus
    compete com a Ranger diesel topo é o gestor, e por isso a tabela é editável e tem
    `nota` para o critério ficar escrito.
    """

    __tablename__ = "equivalents"
    __table_args__ = (
        UniqueConstraint("competitor_version_id", "ford_version_id", name="uq_equivalents_par"),
    )

    id: str = Field(default_factory=novo_id, primary_key=True)
    competitor_version_id: str = Field(foreign_key="versions.id", index=True)
    ford_version_id: str | None = Field(default=None, foreign_key="versions.id", index=True)
    """`None` significa **sem equivalente direto**, e é resposta legítima: a Raptor não
    tem par entre as picapes diesel de trabalho. Deixar em branco por omissão seria
    diferente de afirmar que não há."""
    nota: str | None = Field(default=None, max_length=300)
    definido_por: str | None = Field(default=None, foreign_key="users.id")
    criado_em: dt.datetime = Field(default_factory=agora)


class ShowroomOutcome(StrEnum):
    """O resultado de uma sessão de showroom. Vocabulário fechado (`docs/12` §6.5)."""

    FECHOU = "fechou"
    PERDEU = "perdeu"
    EM_ANDAMENTO = "em_andamento"


#: Os motivos de perda que o vendedor pode marcar. `docs/12` §6.5, literal.
#:
#: Fechado de propósito: motivo em texto livre viraria trinta variações de "preço" e o
#: painel de insights não conseguiria agrupar nada. `outro` existe para o caso que não
#: cabe, e a frequência de `outro` é o sinal de que falta uma opção na lista.
MOTIVOS_DE_SESSAO = (
    "preco",
    "consumo",
    "capacidade",
    "seguranca",
    "desempenho",
    "conforto",
    "marca_confianca",
    "prazo_entrega",
    "financiamento",
    "outro",
)


class ShowroomSession(SQLModel, table=True):
    """Uma conversa de showroom registrada, **sem nenhum dado pessoal**.

    A ausência de PII é estrutural, não uma promessa: não há coluna de nome, telefone,
    e-mail ou CPF, e o schema da API recusa campo extra. O que se guarda é o **par
    comparado**, o perfil de necessidades (que já é anônimo) e o desfecho — o suficiente
    para o Product Marketing aprender e insuficiente para identificar alguém.

    `vendedor_id` e `dealer_id` identificam **quem atendeu**, não o cliente. É o que
    permite ao vendedor ver as próprias sessões (`docs/12` §6.6, escopo `proprios`).
    """

    __tablename__ = "showroom_sessions"

    id: str = Field(default_factory=novo_id, primary_key=True)
    dealer_id: str | None = Field(default=None, index=True, max_length=64)
    vendedor_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    ford_version_id: str = Field(foreign_key="versions.id", index=True)
    competitor_version_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    needs_profile_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    comparison_id: str | None = Field(default=None, max_length=200)
    """O par comparado, no formato `fordId:concorrenteId` (ver `api/app/routers/showroom.py`)."""
    outcome: str = Field(default=ShowroomOutcome.EM_ANDAMENTO.value, index=True, max_length=20)
    motivos: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    atributo_decisivo: str | None = Field(default=None, max_length=80)
    is_simulated: bool = Field(default=False, index=True)
    """Sessão de demonstração. O painel a separa e rotula SIMULAÇÃO (`docs/13` §2)."""
    created_at: dt.datetime = Field(default_factory=agora, index=True)
    updated_at: dt.datetime | None = Field(default=None)


class ArgumentTemplate(SQLModel, table=True):
    """O argumentário aprovado (ou travado) pelo gestor, por **par de versões**.

    `docs/12` §6.4 dá ao gestor três verbos: aprovar, editar e **travar**. Travar é o mais
    forte — enquanto `travado` é verdadeiro, a API devolve o texto do gestor e ignora tanto
    o template quanto qualquer reescrita. É o que permite ao Product Marketing garantir a
    mensagem numa campanha, e é por isso que a tela mostra "aprovado pelo Product
    Marketing" quando existe.

    O par é a chave: um argumento que vale para Ranger × Hilux não vale para Ranger × S10.
    """

    __tablename__ = "argument_templates"
    __table_args__ = (
        UniqueConstraint("ford_version_id", "competitor_version_id", name="uq_argumento_par"),
    )

    id: str = Field(default_factory=novo_id, primary_key=True)
    ford_version_id: str = Field(foreign_key="versions.id", index=True)
    competitor_version_id: str = Field(foreign_key="versions.id", index=True)
    textos: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    """Os textos aprovados, na ordem. Vazio significa "aprovou o template como está"."""
    aprovado: bool = Field(default=False)
    travado: bool = Field(default=False, index=True)
    aprovado_por: str | None = Field(default=None, foreign_key="users.id")
    nota: str | None = Field(default=None, max_length=300)
    criado_em: dt.datetime = Field(default_factory=agora)
    atualizado_em: dt.datetime | None = Field(default=None)


class CompetitiveEvent(SQLModel, table=True):
    """O alerta **enriquecido**: materialidade, regras que dispararam e prioridade.

    Tabela separada de `alerts` de propósito. O alerta é o **fato** ("o preço mudou de X
    para Y", com as duas evidências) e não muda; o evento é a **leitura** daquele fato
    ("isto é ALTA porque entrou na faixa de preço"), e a leitura muda quando as regras ou
    os pesos mudam. Guardar as duas coisas na mesma linha faria um ajuste de peso reescrever
    o histórico do que aconteceu.

    `rules_fired` é gravado junto porque a faixa sem as regras é um oráculo: o painel mostra
    "ALTA" e o "Por quê?" mostra a conta que produziu aquele ALTA — inclusive a versão do
    `rules.yaml` que estava valendo.
    """

    __tablename__ = "competitive_events"

    id: str = Field(default_factory=novo_id, primary_key=True)
    alert_id: str = Field(foreign_key="alerts.id", index=True)
    version_id: str | None = Field(default=None, foreign_key="versions.id", index=True)
    comparable_version_id: str | None = Field(default=None, foreign_key="versions.id")
    """A versão Ford comparável usada nas regras de faixa de preço e de gap."""
    materiality: str = Field(default="RUIDO", index=True, max_length=10)
    pontos: float = Field(default=0.0)
    rules_fired: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    parity_flips: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    priority_rank: int = Field(default=3000, index=True)
    """Menor primeiro. Os degraus por faixa garantem que MEDIA nunca passe na frente de ALTA."""
    versao_das_regras: str | None = Field(default=None, max_length=40)
    is_simulated: bool = Field(default=False, index=True)
    criado_em: dt.datetime = Field(default_factory=agora, index=True)


class RefreshToken(SQLModel, table=True):
    """Um refresh emitido, para que ele possa ser **revogado**.

    Sem esta tabela, revogar sessao significa trocar o `JWT_SECRET` e derrubar todos os
    usuarios de uma vez. O `jti` do token e a chave: o access continua sem estado (TTL
    curto resolve), e so o refresh — que vive 7 dias — precisa ser rastreado.

    `substituido_por` guarda a rotacao. Reuso de refresh ja rotacionado e o sinal
    classico de token roubado, e ficar com a cadeia inteira permite revogar a familia em
    vez de so o token apresentado (`docs/04`).
    """

    __tablename__ = "refresh_tokens"

    jti: str = Field(primary_key=True, max_length=64)
    user_id: str = Field(foreign_key="users.id", index=True)
    expira_em: dt.datetime
    criado_em: dt.datetime = Field(default_factory=agora)
    revogado_em: dt.datetime | None = Field(default=None)
    substituido_por: str | None = Field(default=None, max_length=64)
    motivo_da_revogacao: str | None = Field(default=None, max_length=120)

    @property
    def ativo(self) -> bool:
        return self.revogado_em is None


class AuditLog(SQLModel, table=True):
    """Quem fez o quê, quando, em qual alvo.

    `ator_email` fica desnormalizado ao lado de `user_id` de propósito: auditoria tem de
    continuar legível depois de o usuário ser removido, e o e-mail é o único identificador
    de pessoa que o sistema guarda.
    """

    __tablename__ = "audit_log"

    id: str = Field(default_factory=novo_id, primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    ator_email: str | None = Field(default=None, max_length=254)
    acao: str = Field(index=True, max_length=80)
    alvo_tipo: str | None = Field(default=None, max_length=40)
    alvo_id: str | None = Field(default=None, max_length=64)
    detalhe: dict[str, Any] | None = Field(default=None, sa_column=Column("detalhe", JSON))
    criado_em: dt.datetime = Field(default_factory=agora, index=True)


#: Ordem de criação das tabelas (pais antes de filhas). A migração inicial é escrita à
#: mão e segue esta ordem; o `downgrade` percorre ao contrário.
ORDEM_DAS_TABELAS: tuple[str, ...] = (
    "brands",
    "models",
    "versions",
    "sources",
    "jobs",
    "users",
    "snapshots",
    "extractions",
    "evidences",
    "spec_values",
    "synonyms",
    "alerts",
    "internal_references",
    "equivalents",
    "refresh_tokens",
    "audit_log",
)
