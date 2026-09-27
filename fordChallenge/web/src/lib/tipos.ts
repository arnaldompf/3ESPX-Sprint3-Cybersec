/**
 * Os tipos do contrato, escritos a partir de `schema/canonical_spec.schema.json` e
 * `reports/openapi.json`.
 *
 * Por que **não** gerados automaticamente: `openapi-typescript` traria mais uma
 * dependência de build e um passo de geração que envelhece em silêncio — e o que a tela
 * consome é um punhado de formas estáveis, não as 26 rotas. O que garante que estes tipos
 * batem com a API é o teste `contrato.test.ts`, que lê o `reports/openapi.json` de
 * verdade e falha quando um campo esperado deixa de existir. Isso pega a divergência
 * quando ela acontece, que é o que a geração automática também faria — mas sem cadeia de
 * ferramenta.
 */

/** Os seis status de `pipeline/schema.py`. Fechado de propósito. */
export type Status =
  | 'verificado'
  | 'nao_verificado'
  | 'nao_disponivel'
  | 'nao_encontrado'
  | 'divergente'
  | 'pendente'

/**
 * As quatro etiquetas de `docs/13` §2.
 *
 * **Três qualificam um VALOR** (FATO, INFERÊNCIA, SIMULAÇÃO). `SEM_DADO` é a ausência de
 * valor, e é de outra natureza: não diz nada sobre um número porque não há número. Antes
 * de 12/09/2026 um campo vazio recebia INFERÊNCIA — e um `nao_disponivel` vazio recebia
 * FATO, verde, que é a leitura mais perigosa possível para quem está com o cliente ao lado.
 */
export type Etiqueta = 'FATO' | 'INFERENCIA' | 'SIMULACAO' | 'SEM_DADO' | 'CATALOGO'

export interface Evidencia {
  evidence_id: string
  source_url: string
  tier: number
  quote: string
  captured_at: string
  raw_value?: string | null
  snapshot_id?: string | null
  page?: number | null
  /**
   * O que a fonte estava fazendo ao dizer este número.
   *
   * Uma **mesma página** pode trazer os dois: a matéria da Autoesporte sobre a Ranger
   * Raptor registra os 5,8 s que a Ford declara e os 6,5 s que a revista mediu. É o que
   * separa "as fontes divergem" de "mesma fonte, dois valores: declarado × medido".
   */
  tipo_de_afirmacao?: 'declarado' | 'medido' | 'listado' | null
}

export interface Conflito {
  value: unknown
  evidence: Evidencia
  notes?: string | null
}

export interface Campo {
  value: unknown
  unit?: string | null
  status: Status
  confidence: number
  evidences: Evidencia[]
  conflicts: Conflito[]
  sources_checked: string[]
  notes?: string | null
  /** Marcado pelo back-end em dado de demonstração (`docs/13`: faixa SIMULAÇÃO). */
  is_simulated?: boolean
  /**
   * De onde veio o valor, quando **não** foi extraído de uma fonte externa.
   *
   * Hoje só `"catalogo"`: a identidade da versão consultada (marca, modelo, versão,
   * ano-modelo, código FIPE), que está no nosso cadastro. Ela merece marca própria porque
   * não é FATO (não há trecho verbatim), não é INFERÊNCIA (nada foi inferido) e não é
   * vazio (o valor existe).
   */
  origem?: string | null
}

export interface ResolucaoDaVersao {
  status: 'encontrada' | 'versao_inexistente' | 'ambigua'
  matched_version?: string | null
  alternatives: string[]
}

export interface MetaDaFicha {
  generated_at: string
  job_id: string
  version_resolution: ResolucaoDaVersao
  sources_checked: string[]
}

/** Os 11 grupos do schema canônico, na ordem em que a ficha os mostra. */
export const GRUPOS = [
  'identificacao',
  'motorizacao',
  'transmissao',
  'tracao',
  'chassi',
  'desempenho',
  'modos',
  'exterior',
  'dimensoes',
  'seguranca',
  'comercial',
] as const

export type Grupo = (typeof GRUPOS)[number]

export type Ficha = {
  [G in Grupo]: Record<string, Campo>
} & {
  schema_version: string
  extras: Record<string, Campo>
  meta: MetaDaFicha
}

/** Quantos dos campos do slide de validação do edital (`docs/01_REQUISITOS_EDITAL.md`,
 * Ranger Raptor) esta ficha comprova — separado do resto dos 54 campos, sem excluí-los. */
export interface ValidacaoEdital {
  total: number
  achados: number
  com_valor: number
  vazio_justificado: number
  respondidos: number
  sem_resposta: number
  campos_achados: string[]
  campos_vazios: {
    campo: string
    status: string
    vazio_justificado: boolean
    sources_checked: string[]
  }[]
}

export interface Resolucao {
  status: 'encontrada' | 'versao_inexistente' | 'ambigua'
  matched_version?: string | null
  alternatives: string[]
  score: number
  mensagem: string
  fipe_last_year?: number | null
  sources: string[]
  bloqueadas: string[]
  pendencias: string[]
}

export interface Veiculo {
  id: string
  marca: string
  modelo: string
  versao: string
  ano_modelo: number
  codigo_fipe?: string | null
  in_lineup: boolean
}

/** Os sete tipos de `docs/12` §6.1. Vocabulário fechado: ver `AlertType` no back-end. */
export type TipoDeAlerta =
  | 'preco_oficial'
  | 'preco_fipe'
  | 'versao_nova'
  | 'versao_removida'
  | 'campo_alterado'
  | 'fonte_bloqueada'
  | 'referencia_interna_divergente'

export interface Alerta {
  id: string
  type: TipoDeAlerta | string
  version_id?: string | null
  field?: string | null
  old: unknown
  new: unknown
  created_at: string
  lido: boolean
  tratado: boolean
  /** Verdadeiro obriga a faixa SIMULAÇÃO. Ver `docs/13` §2 e `Badge.tsx`. */
  is_simulated: boolean
}

/**
 * O impacto calculado por regra (`pipeline/radar/impact.py`), não por LLM.
 *
 * Os dois `motivo_sem_*` existem porque **campo vazio e conta impossível são coisas
 * diferentes**: sem preço da Ford equivalente não há gap, e dizer isso é honesto; deixar
 * o gap em branco pareceria gap zero.
 */
export interface Impacto {
  delta?: number | null
  delta_pct?: number | null
  gap_antes?: number | null
  gap_depois?: number | null
  dimensoes_afetadas: string[]
  direcao: 'favorece_ford' | 'desfavorece_ford' | 'neutro' | string
  material: boolean
  motivo_sem_delta: string
  motivo_sem_gap: string
}

/** Uma sugestão por área. Chave fechada: as quatro de `docs/12` §6.3. */
export interface Reacoes {
  marketing: string
  vendas: string
  produto: string
  ci: string
}

export interface AlertaDetalhado extends Alerta {
  impact?: Impacto | null
  reactions?: Reacoes | null
  evidence_before?: Evidencia | null
  evidence_after?: Evidencia | null
}

export interface FiltroDeAlertas {
  desde?: string
  tipo?: string
  concorrente?: string
  /** `false` esconde os simulados. Eles vêm por padrão, sempre marcados. */
  incluirSimulados?: boolean
}

/** WP-32 — os quatro estados da matriz. `desconhecido` é de primeira classe. */
export type EstadoDeParidade = 'vantagem' | 'paridade' | 'gap' | 'desconhecido'

export interface CelulaDeParidade {
  campo: string
  grupo: string
  estado: EstadoDeParidade
  valor_ford: unknown
  valor_concorrente: unknown
  unidade?: string | null
  motivo: string
  /** Distingue "falta dado" de "campo sem lado melhor definido". Ver `pipeline/parity.py`. */
  motivo_tipo: string
  diferenca?: number | null
  evidence_id_ford?: string | null
  evidence_id_concorrente?: string | null
}

export interface ContagemDeParidade {
  vantagem: number
  paridade: number
  gap: number
  desconhecido: number
  total: number
  /** O denominador honesto: exclui o que ninguém mediu. */
  comparados: number
}

export interface CriterioDeComparabilidade {
  id: string
  rotulo: string
  estado: 'atendido' | 'nao_atendido' | 'sem_dados' | string
  valor_ford: unknown
  valor_concorrente: unknown
  motivo: string
}

export interface Comparabilidade {
  version_id: string
  rotulo: string
  comparavel: boolean
  criterios_atendidos: number
  criterios_avaliaveis: number
  total_de_criterios: number
  /** `"4/6 critérios atendidos"`. Nunca porcentagem. */
  resumo: string
  nao_atendidos: string[]
  sem_dados: string[]
  detalhes: CriterioDeComparabilidade[]
  /** Preenchido, a tela é **obrigada** a exibir. */
  aviso: string
  versao_dos_criterios: string
  /**
   * Só o simulador (WP-35) preenche: diz que a comparabilidade foi avaliada sobre os
   * valores **reais**, porque a hipótese de um cenário não torna um par comparável.
   */
  escopo?: string
}

export interface FlagDeCarga {
  /** Falso quando não há valor de carga: aí não há flag a exibir, nem "não atinge". */
  aplicavel: boolean
  valor?: boolean | null
  capacidade_kg?: number | null
  texto: string
  etiqueta: string
  motivo: string
}

export interface ColunaDeParidade {
  version_id: string
  rotulo: string
  celulas: CelulaDeParidade[]
  contagem: ContagemDeParidade
  comparabilidade: Comparabilidade
  flag_de_carga: FlagDeCarga
}

export interface Paridade {
  ford_version: string
  ford_rotulo: string
  colunas: ColunaDeParidade[]
  legenda: Record<string, string>
  flag_de_carga_ford: FlagDeCarga
  versao_dos_criterios: string
}

export interface CandidatoComparavel {
  version_id: string
  rotulo: string
  comparabilidade: Comparabilidade
}

/** WP-33 — Saúde do Conhecimento. Todo indicador vem com denominador. */
export interface CampoComProblema {
  campo: string
  motivo: string
  detalhe: string
}

export interface Indicador {
  valor: number
  de: number
  /** `null` quando o denominador é zero — e `null` não é `0`. */
  fracao?: number | null
  campos: CampoComProblema[]
}

export type StatusDeSaude = 'OK' | 'REVISAR' | 'INSUFICIENTE'

export interface RegraDeSaude {
  nome: string
  status: string
  explicacao: string
}

export interface Saude {
  version_id: string
  rotulo: string
  verificados: Indicador
  desatualizados: Indicador
  conflitos: Indicador
  nao_confirmados: Indicador
  fontes_bloqueadas: Indicador
  ultima_atualizacao?: string | null
  status: StatusDeSaude | string
  regra_do_status: string
  explicacao_do_status: string
  limiar_de_dias: number
  /** "indicador operacional do MVP, não probabilidade de verdade". Exibido sempre. */
  texto_fixo: string
  regras: RegraDeSaude[]
}

export interface CoberturaDaMarca {
  marca: string
  versoes_mapeadas: number
  versoes_com_ficha: number
  campos_com_fonte_oficial: Indicador
  nao_encontrados: Indicador
  divergencias: Indicador
  por_campo: Record<string, Indicador>
}

export interface ValorDivergente {
  valor: unknown
  origem: string
  tier?: number | null
}

export interface Divergencia {
  escopo: string
  version_id?: string | null
  rotulo: string
  campo?: string | null
  valores: ValorDivergente[]
  gap?: number | null
  detectado_em?: string | null
}

/** WP-26 — Customer Need Engine. */
export interface NeedsProfile {
  uso?: string[]
  prioridades_rank?: string[]
  pesos_override?: Record<string, number> | null
  faixa_preco_brl?: [number, number] | null
  km_mes?: number
  combustivel_preco?: { diesel?: number; gasolina?: number }
}

export interface NotaDeCampo {
  campo: string
  nota: number | null
  valor: unknown
  motivo: string
}

export interface DimensaoAvaliada {
  dimensao: string
  rotulo: string
  peso: number
  nota_ford: number | null
  nota_concorrente: number | null
  campos_usados: string[]
  campos_sem_dado: { campo: string; motivo: string }[]
  cobertura: number | null
  /** Dimensão excluída do total por falta de dado comparável. Aparece marcada, nunca some. */
  insuficiente: boolean
  aviso: string
  /**
   * Quem ficou no piso da faixa observada (`"ford"` e/ou `"concorrente"`).
   *
   * Nota perto de zero aqui não quer dizer "este carro não tem o item": quer dizer "é o
   * menor valor entre os poucos veículos da amostra".
   */
  nota_no_piso?: string[]
  /** A frase que explica a régua quando alguém ficou no piso. */
  aviso_da_escala?: string | null
  detalhe_ford: NotaDeCampo[]
  detalhe_concorrente: NotaDeCampo[]
}

export interface Aderencia {
  aderencia_ford: number | null
  aderencia_concorrente: number | null
  pesos: Record<string, number>
  dimensoes: DimensaoAvaliada[]
  vence_em: { ford: string[]; concorrente: string[] }
  /** Soma dos pesos que entraram. Menor que 100 quando alguma dimensão é insuficiente. */
  peso_considerado: number
  avisos: string[]
  rotulo: string
  versao_das_dimensoes: string
  versao_das_faixas: string
}

export interface CustoDeUso {
  version_id: string
  rotulo: string
  combustivel: string
  consumo: {
    valor_kml: number | null
    origem: string
    rotulo_da_origem: string
    campo: string
  }
  preco_por_litro: number | null
  km_mes: number | null
  litros_mes: number | null
  custo_mes: number | null
  custo_ano: number | null
  frase: string
  motivo_sem_custo: string
}

export interface CustoComparado {
  ford: CustoDeUso
  concorrente: CustoDeUso
  diferenca_mes: number | null
  diferenca_ano: number | null
  quem_gasta_menos: string
  motivo_sem_diferenca: string
}

export interface ConcorrenteComFit {
  version_id: string
  rotulo: string
  aderencia: Aderencia
  usage_cost: CustoDeUso
  custo_comparado: CustoComparado
}

export interface Fit {
  rotulo: string
  versao_das_dimensoes: string
  versao_das_faixas: string
  perfil: NeedsProfile
  pesos: Record<string, number>
  base: { version_id: string; rotulo: string }
  usage_cost_base: CustoDeUso
  concorrentes: ConcorrenteComFit[]
}

export interface Comparacao {
  fit?: Fit
  [chave: string]: unknown
}

export interface CampoDaDimensao {
  campo: string
  tipo: string
  direcao?: string | null
  faixa?: {
    minimo: number
    maximo: number
    amostras: number
    de_onde: string
    insuficiente: boolean
  } | null
}

export interface Dimensoes {
  versao: string
  versao_das_faixas: string
  pesos_por_rank: number[]
  cobertura_minima: number
  usos: string[]
  rotulo_obrigatorio: string
  dimensoes: { id: string; rotulo: string; campos: CampoDaDimensao[] }[]
}

/** WP-27 — argumentário, sessão de showroom e win/loss. */
export interface PontoDoArgumentario {
  dimensao: string
  rotulo_da_dimensao: string
  peso: number
  campo: string
  valor_ford: unknown
  valor_concorrente: unknown
  unidade?: string | null
  texto: string
  /** Os `evidence_id` das duas pontas. Frase sem isso é alegação bem escrita. */
  fonte_por_ponto: string[]
  a_favor: boolean
}

export interface Argumentario {
  pontos: PontoDoArgumentario[]
  ponto_forte_concorrente: PontoDoArgumentario | null
  fonte_por_ponto: string[][]
  gerado_por: string
  aprovado: boolean
  travado?: boolean
  avisos: string[]
  comparison_id: string
  ford: { version_id: string; rotulo: string }
  concorrente: { version_id: string; rotulo: string }
  pesos: Record<string, number>
  /** "aprovado pelo Product Marketing", quando existe. */
  selo: string
  reescrita?: { gerado_por: string; motivo: string } | null
}

export type DesfechoDaSessao = 'fechou' | 'perdeu' | 'em_andamento'

export interface SessaoDeShowroom {
  id: string
  dealer_id?: string | null
  vendedor_id?: string | null
  ford_version_id: string
  competitor_version_ids: string[]
  comparison_id?: string | null
  outcome: DesfechoDaSessao | string
  motivos: string[]
  atributo_decisivo?: string | null
  is_simulated: boolean
  created_at: string
  updated_at?: string | null
}

export interface ContagemDeWinLoss {
  valor: number
  de: number
  /** `null` quando `de < 20`: percentual sobre poucos casos é ruído (`docs/12` §6.5). */
  percentual: number | null
}

export interface PorConcorrente {
  version_id: string
  rotulo: string
  n: number
  fechou: ContagemDeWinLoss
  perdeu: ContagemDeWinLoss
  em_andamento: ContagemDeWinLoss
  top_motivos: { chave: string; n: number }[]
  top_atributos_decisivos: { chave: string; n: number }[]
  perfis: { chave: string; n: number }[]
  mostra_percentual: boolean
  aviso: string
}

export interface PainelDeWinLoss {
  real: PorConcorrente[]
  simulado: PorConcorrente[]
  n_real: number
  n_simulado: number
  rotulo_simulacao: string
  n_minimo_para_percentual: number
  escopo: string
  aviso_de_escopo: string
}

export interface BlocoDeResumo {
  n: number
  fechou: ContagemDeWinLoss
  perdeu: ContagemDeWinLoss
  em_andamento: ContagemDeWinLoss
  top_motivos: { chave: string; n: number }[]
  top_atributos_decisivos: { chave: string; n: number }[]
  mostra_percentual: boolean
  aviso: string
}

export interface ResumoDeWinLoss {
  real: BlocoDeResumo
  simulado: BlocoDeResumo
  rotulo_simulacao: string
  n_minimo_para_percentual: number
  escopo: string
}

/** WP-28 — o job e o relatório para o cliente. */
export interface JobDoRelatorio {
  job_id: string
  status: string
  location: string
}

export interface EstadoDoJob {
  id: string
  tipo: string
  status: string
  stage?: string | null
  error?: string | null
  /** Onde baixar quando `status === "concluido"`. Rota **autenticada**. */
  result_url?: string | null
  criado_em: string
}

export interface AtributoResolvido {
  canonical?: string | null
  caminho?: string | null
  extra_slug?: string | null
  score: number
}

export interface Tokens {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export type Papel = 'vendedor' | 'analista' | 'gestor' | 'admin'

export interface Usuario {
  id: string
  email: string
  nome: string
  role: Papel
  ativo: boolean
}

/**
 * `GET /api/v1/health`, o unico endpoint publico.
 *
 * `demo_mode` e o que a tela de entrada consulta para decidir entre os quatro botoes e o
 * formulario de e-mail e senha. A API o publica de proposito: com ele ligado existe uma
 * entrada sem senha, e quem administra a maquina tem de poder descobrir isso sem ler o
 * `.env` (D-185).
 */
export interface SaudeDoServidor {
  status: 'ok' | 'degradado'
  version: string
  db: { ok: boolean; dialeto: string; nome: string; erro: string | null }
  etiqueta: 'FATO'
  demo_mode: boolean
  /** O Pesquisador está montado neste ambiente? */
  research_enabled?: boolean
  /** O Benchmark competitivo está montado neste ambiente? */
  benchmark_enabled?: boolean
}

/** O `problem+json` de `api/app/errors.py`. */
export interface Problema {
  type: string
  title: string
  status: number
  detail: string
  instance: string
  errors?: { campo: string; regra: string; mensagem: string }[]
}

/**
 * WP-34 — a materialidade e a cadeia do "Por quê?".
 *
 * `rules_fired` **nunca** é opcional: a faixa sozinha ("ALTA") é um oráculo, e a régua
 * inteira é o que o produto promete. Se a API deixar de mandar as regras, o tipo quebra a
 * compilação em vez de a tela mostrar uma nota sem justificativa.
 */
export type Materialidade = 'ALTA' | 'MEDIA' | 'BAIXA' | 'RUIDO'

export interface RegraDisparada {
  id: string
  peso: number
  descricao: string
  detalhe: string
}

/** Um estado de paridade que virou (`vantagem` → `gap`, por exemplo). */
export interface InversaoDeParidade {
  campo?: string
  antes?: string
  depois?: string
  motivo?: string
}

export interface EventoCompetitivo {
  id: string
  alert_id: string
  version_id?: string | null
  comparable_version_id?: string | null
  materiality: Materialidade | string
  /** O que a faixa significa. Vem de `rules.yaml`; a tela não repete a frase. */
  significado: string
  pontos: number
  rules_fired: RegraDisparada[]
  parity_flips: InversaoDeParidade[]
  priority_rank: number
  versao_das_regras?: string | null
  is_simulated: boolean
  criado_em: string
  /** O alerta embutido: sem isso a fila faria uma chamada por linha. */
  alerta: Alerta
}

export interface FiltroDaFila extends FiltroDeAlertas {
  prioridade?: Materialidade | ''
  /** `false` colapsa o ruído para fora da fila. O alerta continua em `/alerts`. */
  incluirRuido?: boolean
}

/**
 * A cadeia do "Por quê?": ação → regra → mudança → campo → evidências → snapshots.
 *
 * Os dois `motivo_sem_*` são o que impede **elo vazio**. Um elo que aponta para o nada é
 * pior que um elo ausente, porque parece prova — então onde o dado não existe, a API
 * manda o motivo e a tela o mostra no lugar do elo.
 */
export interface Cadeia {
  alert_id: string
  materiality: Materialidade | string
  significado: string
  pontos: number
  priority_rank: number
  is_simulated: boolean
  versao_das_regras?: string | null
  acao_sugerida: string
  regras: RegraDisparada[]
  mudanca: {
    campo_canonico?: string | null
    before: unknown
    after: unknown
    tipo_de_alerta?: string | null
    detectado_em?: string
  }
  parity_flips: InversaoDeParidade[]
  comparavel: { version_id?: string | null; rotulo: string; motivo: string }
  /** Cada evidência declara **de que lado da mudança** ela é.
   *
   * Opcional no tipo porque `Evidencia` é usada em toda a aplicação e só a cadeia do
   * "Por quê?" tem lado. A tela não infere o lado pelo índice na lista: o serviço filtra
   * os `None` antes de montá-la, e com uma evidência só o índice 0 mentia (D-156). */
  evidencias: (Evidencia & { lado?: 'antes' | 'depois' })[]
  motivo_sem_evidencia: string
  snapshots: {
    snapshot_id: string
    url: string
    sha256?: string | null
    captured_at: string
    http_status?: number | null
  }[]
  motivo_sem_snapshot: string
  nota_dos_pesos: string
  gerado_em: string
}

/**
 * WP-35 — o simulador. **Hipótese do usuário, nunca observação.**
 *
 * `is_simulation` e `rotulo_simulacao` viajam em cada painel de cenário, não só no topo da
 * resposta: a tela mostra os dois lados juntos, e um aviso único no cabeçalho deixaria o
 * painel hipotético sem etiqueta assim que alguém rolasse a página — ou recortasse a
 * imagem para um slide.
 */
export interface OverrideDoCenario {
  version_id: string
  campo: string
  delta_pct?: number
  novo_valor?: unknown
  remover?: boolean
}

export interface OverrideAplicado {
  version_id: string
  campo: string
  antes: unknown
  depois: unknown
  descricao: string
  /** "hipótese informada pelo usuário". A nota da spec: o −5% veio do usuário. */
  origem: string
}

export interface PainelDoCenario {
  version_id: string
  rotulo: string
  coluna: ColunaDeParidade
  aderencia: Aderencia | null
  is_simulation: boolean
  /** Vazio no painel de realidade: ele é FATO. */
  rotulo_simulacao: string
}

export interface MudancaDeParidade {
  campo: string
  antes: EstadoDeParidade | string
  depois: EstadoDeParidade | string
  motivo_antes: string
  motivo_depois: string
}

export interface DiffDoCenario {
  version_id: string
  rotulo: string
  paridade: MudancaDeParidade[]
  aderencia: {
    dimensao: string
    rotulo: string
    peso: number
    antes: { ford: number | null; concorrente: number | null }
    depois: { ford: number | null; concorrente: number | null }
  }[]
  /** A materialidade da hipótese, pelo mesmo motor da WP-34. */
  materialidade: {
    materiality: string
    pontos: number
    significado: string
    rules_fired: RegraDisparada[]
    parity_flips: InversaoDeParidade[]
    is_simulated: boolean
    nota_de_hipotese: string
    campo_avaliado?: string
    motivo_do_campo?: string
  } | null
  motivo_sem_materialidade: string
}

export interface Simulacao {
  is_simulation: boolean
  rotulo: string
  ford: { version_id: string; rotulo: string }
  atual: PainelDoCenario[]
  cenario: PainelDoCenario[]
  diffs: DiffDoCenario[]
  overrides_aplicados: OverrideAplicado[]
  motivo_sem_aderencia: string
  origem_dos_numeros: string
}

export interface CamposDoSimulador {
  delta_pct: { campos: string[]; minimo: number; maximo: number; descricao: string }
  novo_valor: { descricao: string }
  remover: { descricao: string }
  rotulo: string
  origem_dos_numeros: string
  maximo_de_overrides: number
}


/* ------------------------------------------------------------------ o Pesquisador
 *
 * Os passos de uma pesquisa, como a API os entrega. Cada um carrega a etiqueta de
 * `docs/13` §2: **FATO** para o que se observou acontecer (uma consulta foi feita, uma
 * página foi baixada) e **INFERÊNCIA** para o que o sistema decidiu por regra (o tier de um
 * domínio, o motivo de um descarte).
 */
export interface EventoDePesquisa {
  ordem: number
  tipo: string
  texto: string
  etiqueta: string
  rodada: number
  decorrido: number
  dados?: Record<string, unknown>
}

export interface TrilhaDePesquisa {
  continuacao_disponivel?: boolean
  run_id: string
  status: string
  veiculo: string
  /** `cobertura`, `sem_progresso`, `rodadas`, `paginas` ou `tempo`. Nunca vazio. */
  motivo_da_parada: string
  campos_com_valor: number
  campos_alvo: number
  paginas: number
  rodadas: number
  segundos: number
  /**
   * A versão do catálogo em que a ficha foi gravada (WP-42). `null` enquanto a pesquisa
   * roda — e também quando ela acabou sem nada para gravar; aí `erro` diz por quê.
   */
  version_id?: string | null
  tokens?: number
  custo_brl?: number
  erro?: string | null
  eventos: EventoDePesquisa[]
}

/**
 * WP-42 — a identificação: de "Triton" ao carro certo, com fontes.
 *
 * Uma opção **sem fonte nunca chega à tela**: a política de `pipeline/research/identificar.py`
 * derruba antes. O que chega leva `fontes[0]`, e é o domínio dela que o chip mostra.
 */
export interface OpcaoDeVeiculo {
  valor: string
  detalhe: string
  fontes: string[]
  /** `versao` = escolher fecha a versão; `modelo` = ainda falta escolher a versão. */
  tipo: 'versao' | 'modelo' | string
  marca: string
  modelo: string
  ano: number | null
}

/** O que já temos desta versão — para a conversa oferecer a ficha em vez de pesquisar. */
export interface NoCatalogo {
  version_id: string
  ano_modelo: number
  tem_ficha: boolean
  campos_com_valor: number
  /** A data mais recente entre valores gravados e cópias das fontes. */
  coletado_em: string | null
}

/** A resposta de `POST /research/identify`. */
export interface Identificacao {
  texto: string
  estado: 'resolvido' | 'precisa_escolher' | 'nao_entendi' | string
  marca: string
  modelo: string
  versao: string
  ano: number | null
  /**
   * De onde veio o ano. `vigente` é o único que a tela rotula INFERÊNCIA: ninguém disse
   * o ano — o sistema assumiu o corrente, e a pessoa pode trocar.
   */
  ano_origem: 'pedido' | 'fontes' | 'vigente' | 'catalogo' | '' | string
  nome: string
  pergunta: string
  opcoes: OpcaoDeVeiculo[]
  origem: 'catalogo' | 'busca' | 'nenhuma' | string
  consultas: string[]
  fontes: string[]
  motivo: string
  uso: Record<string, unknown>
  no_catalogo: NoCatalogo | null
  gasto_rodada: Record<string, unknown>
}

/** Um ano-modelo de uma versão, e se existe ficha salva dele. */
export interface AnoDisponivel {
  ano_modelo: number
  version_id: string
  codigo_fipe: string | null
  in_lineup: boolean
  /** Há célula gravada. O seletor "outro ano" só oferece anos com isto verdadeiro. */
  tem_ficha: boolean
}

/** Uma versão do catálogo avaliada contra o que a pessoa digitou na caixa única. */
export interface Sugestao {
  marca: string
  modelo: string
  versao: string
  /** `"Chevrolet S10 High Country"` — o rótulo da linha. */
  texto: string
  score: number
  cobertura: number
  ano: AnoDisponivel | null
  anos: AnoDisponivel[]
  /** A pessoa nomeou um ano do qual não há cópia. Gatilho do "pesquisar agora?". */
  ano_pedido_sem_ficha: number | null
}

/** O trio que o Pesquisador aceita, montado a partir da frase digitada. */
export interface AlvoDePesquisa {
  marca: string
  modelo: string
  versao: string
  /** `catalogo` = marca e modelo vieram de um quase-acerto; `texto` = chute por posição. */
  de_onde: string
}

/** A resposta de `GET /catalog/suggest`. */
export interface Sugestoes {
  consulta: string
  ano_pedido: number | null
  melhor: Sugestao | null
  outras: Sugestao[]
  empatadas: Sugestao[]
  total: number
  ambigua: boolean
  /** Nenhuma versão passou do limiar: o caminho da tela aqui é o Pesquisador. */
  vazia: boolean
  /** `regra` (rapidfuzz, reproduzível) ou `ia` (empate desfeito pelo modelo). */
  desempate: string
  motivo: string
  para_pesquisar: AlvoDePesquisa | null
}

/* ------------------------------------------------------------------ Benchmark (FASE 3)
 *
 * O conjunto de concorrentes **proposto** para uma versão Ford. Três origens convivem na
 * resposta e a tela é obrigada a distingui-las: a lista escrita (com data), a versão que
 * já está no nosso cadastro e o que ainda precisa ser procurado.
 */

/** O `k/n` do par, sem `version_id`: aqui a comparabilidade descreve um candidato. */
export interface ComparabilidadeDoCandidato {
  comparavel: boolean
  criterios_atendidos: number
  criterios_avaliaveis: number
  total_de_criterios: number
  /** `"4/6 critérios atendidos"`. Nunca porcentagem. */
  resumo: string
  nao_atendidos: string[]
  sem_dados: string[]
  detalhes: CriterioDeComparabilidade[]
  /** Preenchido, a tela é **obrigada** a exibir. */
  aviso: string
  versao_dos_criterios: string
}

export interface CandidatoDoBenchmark {
  marca: string
  modelo: string
  rotulo_do_modelo: string
  /** Entra na conversa do salão sem ser do mesmo porte. Exibido, nunca escondido. */
  categoria_diferente: boolean
  motivo_da_categoria: string
  /** Verdadeiro: há versão do mesmo ano-modelo no cadastro, e ela vem escolhida abaixo. */
  no_catalogo: boolean
  version_id?: string | null
  rotulo?: string | null
  ano_modelo?: number | null
  comparabilidade?: ComparabilidadeDoCandidato | null
  precisa_pesquisa: boolean
  /** Por que este concorrente ainda não pode entrar. Vazio quando já pode. */
  motivo_da_pesquisa: string
}

export interface SegmentoDoBenchmark {
  id: string
  rotulo: string
  descricao: string
  /** `mapa` (lista escrita, com data) ou `desconhecido` (e aí só resta procurar). */
  origem: string
}

export interface FordDoBenchmark {
  version_id: string
  marca: string
  modelo: string
  versao: string
  ano_modelo: number
  rotulo: string
}

export interface PropostaDeBenchmark {
  ford: FordDoBenchmark
  segmento: SegmentoDoBenchmark
  /** A data da lista escrita. Uma lista sem data não se discute. */
  versao_do_mapa: string
  candidatos: CandidatoDoBenchmark[]
  prontos: number
  a_pesquisar: number
  /** A busca a fazer quando não há lista escrita. `null` quando a lista respondeu. */
  consulta_de_descoberta?: string | null
  aviso: string
}
