/**
 * O cliente da API. Um lugar só decide como falar com o back-end.
 *
 * Duas decisões que valem estar aqui e não espalhadas:
 *
 * * **o `problem+json` é lido e vira `ErroDaApi` com `title` e `detail`.** A API se deu o
 *   trabalho de explicar cada erro em português; jogar isso fora e mostrar "erro na
 *   requisição" desperdiça a parte mais útil do contrato;
 *
 * * **o papel viaja em `X-Role`, e é a única coisa que identifica quem chama.** Não há
 *   token, não há renovação e não há sessão (D-204): a ferramenta abre direto na Consulta
 *   e o papel é o seletor da barra lateral, guardado no navegador (`lib/papel.ts`). O
 *   servidor usa o cabeçalho só para **filtrar** o que é por papel — o vendedor vê as
 *   sessões de showroom que ele registrou — e nunca para negar. Quem decide o que mostrar
 *   é a tela, com a matriz de `lib/permissoes.ts`.
 *
 * O que saiu daqui, e por quê: `definirTokens`, `garantirSessao`, a renovação
 * compartilhada e a rotação de refresh. Eram a resposta certa para os defeitos de D-186 —
 * e o problema inteiro deixou de existir quando a entrada deixou de pedir credencial.
 * O código de JWT continua no servidor, atrás de `AUTH_ENABLED`; o cliente dele não.
 */

import type {
  Alerta,
  AlertaDetalhado,
  Argumentario,
  AtributoResolvido,
  CandidatoComparavel,
  CoberturaDaMarca,
  Cadeia,
  CamposDoSimulador,
  Comparacao,
  Dimensoes,
  Divergencia,
  EstadoDoJob,
  EventoCompetitivo,
  Ficha,
  FiltroDaFila,
  FiltroDeAlertas,
  JobDoRelatorio,
  NeedsProfile,
  PainelDeWinLoss,
  Paridade,
  PropostaDeBenchmark,
  ResumoDeWinLoss,
  Saude,
  SaudeDoServidor,
  SessaoDeShowroom,
  Simulacao,
  Problema,
  OverrideDoCenario,
  Resolucao,
  Sugestoes,
  Usuario,
  ValidacaoEdital,
  Veiculo,
} from './tipos'
import { CABECALHO_PAPEL, papelAtual } from './papel'

const BASE = '/api/v1'

/**
 * A recusa do servidor, em português, para uma ação que o papel de quem olha não permite.
 *
 * Existe por dois defeitos medidos em 09/09/2026, e os dois têm a mesma forma: **a regra
 * está certa e a tela não diz nada**.
 *
 * * o **analista** não atende no salão e recebe 403 em `criar_sessao_showroom` (matriz de
 *   `docs/12` §6.6). Quem clicava em "abrir sessão" com o perfil errado via nada
 *   acontecer;
 * * o **vendedor** recebe 403 em `/insights/summary` (D-103), e o cartão "Resumo"
 *   simplesmente **desaparecia** da tela de Insights.
 *
 * "Nada acontecer" e "não estar ali" são indistinguíveis de tela quebrada: a pessoa
 * clica de novo, e depois desconfia do sistema todo. A mensagem usa o `detail` do
 * `problem+json`, que traz o papel que falta — informação melhor que qualquer texto que
 * a tela invente.
 */
export function mensagemDeRecusa(erro: unknown, acao: string): string | undefined {
  if (!erro) return undefined
  if (!(erro instanceof ErroDaApi)) {
    return `Não foi possível ${acao}. Tente de novo.`
  }
  if (erro.semPermissao) {
    return `Seu perfil não pode ${acao}. ${erro.detalhe}`
  }
  return `Não foi possível ${acao}: ${erro.detalhe}`
}

export class ErroDaApi extends Error {
  constructor(
    readonly status: number,
    readonly titulo: string,
    readonly detalhe: string,
    readonly problema?: Problema,
  ) {
    super(`${titulo}: ${detalhe}`)
    this.name = 'ErroDaApi'
  }

  /** O token expirou — o cliente sabe o que fazer: renovar. */
  get expirou(): boolean {
    return this.status === 401 && this.titulo === 'Token expirado'
  }

  /** Autenticado, mas sem permissão. A tela mostra o papel que falta. */
  get semPermissao(): boolean {
    return this.status === 403
  }
}

/** O cabeçalho de papel em toda chamada. Nada mais identifica quem está pedindo. */
function cabecalhoDePapel(): Record<string, string> {
  return { [CABECALHO_PAPEL]: papelAtual() }
}

async function lerProblema(resposta: Response): Promise<ErroDaApi> {
  let problema: Problema | undefined
  try {
    problema = (await resposta.json()) as Problema
  } catch {
    problema = undefined
  }
  return new ErroDaApi(
    resposta.status,
    problema?.title ?? `HTTP ${resposta.status}`,
    problema?.detail ?? resposta.statusText,
    problema,
  )
}

interface Opcoes {
  metodo?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  corpo?: unknown
}

async function chamar<T>(caminho: string, opcoes: Opcoes = {}): Promise<T> {
  const { metodo = 'GET', corpo } = opcoes
  const cabecalhos: Record<string, string> = cabecalhoDePapel()
  if (corpo !== undefined) cabecalhos['Content-Type'] = 'application/json'

  const resposta = await fetch(`${BASE}${caminho}`, {
    method: metodo,
    headers: cabecalhos,
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  })

  if (resposta.ok) {
    if (resposta.status === 204) return undefined as T
    return (await resposta.json()) as T
  }
  throw await lerProblema(resposta)
}

export const api = {
  /** Publico. Diz a versao, o estado do banco e se a autenticacao esta ligada. */
  saudeDoServidor: () => chamar<SaudeDoServidor>('/health'),

  /** Quem esta olhando, segundo o papel que a barra lateral mandou em `X-Role`. */
  eu: () => chamar<Usuario>('/auth/me'),

  resolver: (marca: string, modelo: string, versao: string) =>
    chamar<Resolucao>('/resolutions', { metodo: 'POST', corpo: { marca, modelo, versao } }),

  /**
   * O Pesquisador (WP-41). Só existe com `RESEARCH_ENABLED=1` na API — sem a bandeira, a
   * rota não é montada e a chamada dá 404, que é o que a tela trata.
   *
   * O `POST` devolve **202**: uma pesquisa leva até três minutos, e quem acompanha é
   * `trilhaDaPesquisa`.
   */
  pesquisar: (corpo: {
    marca: string
    modelo: string
    versao?: string
    ano?: number
    rodadas?: number
    paginas?: number
    segundos?: number
  }) =>
    chamar<{ run_id: string; job_id: string; status: string; events_url: string }>('/research', {
      metodo: 'POST',
      corpo,
    }),

  continuarPesquisa: (runId: string) =>
    chamar<{ run_id: string; job_id: string; status: string; events_url: string }>(
      `/research/${runId}/continue`,
      { metodo: 'POST', corpo: { segundos: 900, rodadas: 5, paginas: 40 } },
    ),

  /** A trilha de uma pesquisa, em JSON. É o que o painel ao vivo consulta a cada segundo. */
  trilhaDaPesquisa: (runId: string) =>
    chamar<import('./tipos').TrilhaDePesquisa>(`/research/${runId}/events`),

  /** O resumo de um run, sem precisar dos eventos. Mesma forma da trilha. */
  pesquisa: (runId: string) => chamar<import('./tipos').TrilhaDePesquisa>(`/research/${runId}`),

  /**
   * WP-42 — de um texto solto ("Triton", "a picape nova da RAM") ao carro certo.
   *
   * `ano` só vai quando a pessoa o escolheu: sem ele, o servidor tenta o texto, depois as
   * fontes, e por fim assume o vigente — rotulado como tal na resposta.
   */
  identificar: (texto: string, ano?: number) =>
    chamar<import('./tipos').Identificacao>('/research/identify', {
      metodo: 'POST',
      corpo: ano === undefined ? { texto } : { texto, ano },
    }),

  resolverAtributo: (text: string) =>
    chamar<AtributoResolvido>('/attributes/resolve', { metodo: 'POST', corpo: { text } }),

  /**
   * A caixa única da Consulta: um texto solto vira versão do catálogo, com o ano.
   *
   * Dispara a cada tecla (com espera), então **não** pede desempate por IA: o servidor só
   * gasta chamada de modelo quando quem chama pede, e quem chama aqui não pede.
   */
  sugerir: (q: string, limite = 6) =>
    chamar<Sugestoes>(`/catalog/suggest?q=${encodeURIComponent(q)}&limite=${limite}`),

  veiculos: (marca?: string, modelo?: string) => {
    const q = new URLSearchParams()
    if (marca) q.set('marca', marca)
    if (modelo) q.set('modelo', modelo)
    const sufixo = q.toString()
    return chamar<Veiculo[]>(`/vehicles${sufixo ? `?${sufixo}` : ''}`)
  },

  veiculo: (id: string) => chamar<Veiculo>(`/vehicles/${id}`),

  ficha: (id: string, atributos?: string[]) => {
    const q = atributos?.length ? `?attributes=${atributos.join(',')}` : ''
    return chamar<Ficha>(`/vehicles/${id}/specs${q}`)
  },

  validacaoEdital: (id: string) => chamar<ValidacaoEdital>(`/vehicles/${id}/validacao-edital`),

  alertas: (filtro: FiltroDeAlertas = {}) => {
    const q = new URLSearchParams()
    if (filtro.desde) q.set('since', filtro.desde)
    if (filtro.tipo) q.set('type', filtro.tipo)
    if (filtro.concorrente) q.set('competitor', filtro.concorrente)
    // Só manda quando é `false`: o padrão do back-end já é incluir, e mandar o padrão
    // de volta em toda chamada mudaria a URL do cache do React Query sem motivo.
    if (filtro.incluirSimulados === false) q.set('incluir_simulados', 'false')
    const sufixo = q.toString()
    return chamar<Alerta[]>(`/alerts${sufixo ? `?${sufixo}` : ''}`)
  },

  /** O detalhe: impacto, reações sugeridas e as evidências dos dois lados. */
  alerta: (id: string) => chamar<AlertaDetalhado>(`/alerts/${id}`),

  marcarAlerta: (id: string, campos: { read?: boolean; tratado?: boolean }) =>
    chamar<Alerta>(`/alerts/${id}`, { metodo: 'PATCH', corpo: campos }),

  /**
   * WP-34 — a fila de prioridade: o mesmo alerta, com materialidade e posição.
   *
   * Os filtros são os mesmos de `alertas` de propósito: a fila **substitui** a lista na
   * tela, e duas consultas para a mesma informação poderiam discordar sobre quantos
   * alertas de um tipo existem.
   */
  eventos: (filtro: FiltroDaFila = {}) => {
    const q = new URLSearchParams()
    if (filtro.desde) q.set('since', filtro.desde)
    if (filtro.tipo) q.set('type', filtro.tipo)
    if (filtro.concorrente) q.set('competitor', filtro.concorrente)
    if (filtro.prioridade) q.set('priority', filtro.prioridade)
    // Como em `alertas`: só manda quando é `false`, para não mudar a chave do cache.
    if (filtro.incluirSimulados === false) q.set('incluir_simulados', 'false')
    if (filtro.incluirRuido === false) q.set('incluir_ruido', 'false')
    const sufixo = q.toString()
    return chamar<EventoCompetitivo[]>(`/events${sufixo ? `?${sufixo}` : ''}`)
  },

  /** WP-34 — a cadeia inteira do "Por quê?", do elo da ação ao snapshot. */
  cadeia: (alertaId: string) => chamar<Cadeia>(`/alerts/${alertaId}/trace`),

  /**
   * WP-35 — o simulador. **Nada é gravado**: a resposta é calculada em memória.
   *
   * `needs_profile` é opcional; sem ele a resposta traz `motivo_sem_aderencia` em vez de
   * omitir o bloco, porque nota sem os pesos do perfil seria número inventado.
   */
  simular: (corpo: {
    base_version_ids: string[]
    overrides: OverrideDoCenario[]
    needs_profile?: NeedsProfile
    grupos?: string[]
  }) => chamar<Simulacao>('/scenarios', { metodo: 'POST', corpo }),

  /** WP-35 — o que o simulador aceita alterar. A tela não mantém a própria lista. */
  camposDoSimulador: () => chamar<CamposDoSimulador>('/scenarios/fields'),

  /** WP-32 — as versoes Ford candidatas a comparar com a versao pedida. */
  comparaveis: (versionId: string, incluirNaoComparaveis = true) => {
    const q = new URLSearchParams({ version_id: versionId })
    if (!incluirNaoComparaveis) q.set('incluir_nao_comparaveis', 'false')
    return chamar<CandidatoComparavel[]>(`/comparables?${q.toString()}`)
  },

  /** WP-32 — a matriz de paridade. O aviso de comparabilidade vem dentro de cada coluna. */
  paridade: (fordVersion: string, concorrentes: string[], grupos?: string[]) => {
    const q = new URLSearchParams({
      ford_version: fordVersion,
      competitors: concorrentes.join(','),
    })
    if (grupos?.length) q.set('grupos', grupos.join(','))
    return chamar<Paridade>(`/parity?${q.toString()}`)
  },

  /**
   * FASE 3 — o conjunto de concorrentes proposto para uma versão **Ford**.
   *
   * Como o Pesquisador, só existe com a bandeira ligada na API: sem ela a rota não é
   * montada e a chamada dá 404. A tela trata esse 404 como "não ligado neste ambiente",
   * que é outra coisa de falha — e a diferença importa para quem está apresentando.
   */
  propostaDeBenchmark: (versionId: string) =>
    chamar<PropostaDeBenchmark>(
      `/benchmark/proposta?version_id=${encodeURIComponent(versionId)}`,
    ),

  /** WP-33 — a saude de todas as versoes com ficha, pior primeiro. */
  saude: () => chamar<Saude[]>('/insights/knowledge-health/versions'),

  /** WP-33 — a saude de uma versao. `limiarDeDias` sobrepoe o do ambiente. */
  saudeDaVersao: (versionId: string, limiarDeDias?: number) => {
    const q = new URLSearchParams({ version_id: versionId })
    if (limiarDeDias) q.set('limiar_de_dias', String(limiarDeDias))
    return chamar<Saude>(`/insights/knowledge-health?${q.toString()}`)
  },

  cobertura: () => chamar<CoberturaDaMarca[]>('/insights/coverage'),

  divergencias: (escopo: 'official_vs_press' | 'internal_vs_public') =>
    chamar<Divergencia[]>(`/insights/divergences?scope=${escopo}`),

  /** WP-26 — a tabela de dimensoes, pesos e faixas. Uma tabela so, no back-end. */
  dimensoes: () => chamar<Dimensoes>('/dimensions'),

  /** WP-27 — o argumentario do par `fordId:concorrenteId`. */
  argumentos: (comparisonId: string, perfil?: NeedsProfile, permitirLlm = true) =>
    chamar<Argumentario>(`/comparisons/${comparisonId}/arguments`, {
      metodo: 'POST',
      corpo: { ...(perfil ? { needs_profile: perfil } : {}), permitir_llm: permitirLlm },
    }),

  criarSessao: (corpo: {
    ford_version_id: string
    competitor_version_ids?: string[]
    comparison_id?: string
    needs_profile?: NeedsProfile
  }) => chamar<SessaoDeShowroom>('/showroom-sessions', { metodo: 'POST', corpo }),

  fecharSessao: (
    id: string,
    corpo: { outcome?: string; motivos?: string[]; atributo_decisivo?: string },
  ) => chamar<SessaoDeShowroom>(`/showroom-sessions/${id}`, { metodo: 'PATCH', corpo }),

  winLossPorConcorrente: (fordVersion?: string, desde?: string) => {
    const q = new URLSearchParams()
    if (fordVersion) q.set('ford_version', fordVersion)
    if (desde) q.set('since', desde)
    const sufixo = q.toString()
    return chamar<PainelDeWinLoss>(`/insights/competitors${sufixo ? `?${sufixo}` : ''}`)
  },

  winLossResumo: (desde?: string) =>
    chamar<ResumoDeWinLoss>(`/insights/summary${desde ? `?since=${desde}` : ''}`),

  /** WP-28 — pede o relatorio do par. Devolve 202 + job; quem gera e o worker. */
  pedirRelatorio: (comparisonId: string, perfil?: NeedsProfile) =>
    chamar<JobDoRelatorio>(`/comparisons/${comparisonId}/pdf`, {
      metodo: 'POST',
      corpo: perfil ? { needs_profile: perfil } : {},
    }),

  job: (id: string) => chamar<EstadoDoJob>(`/jobs/${id}`),

  /**
   * WP-26 — a matriz de comparacao. Com `perfil`, a resposta traz o bloco `fit`.
   *
   * Sem `perfil` o corpo nao leva a chave: a rota trata ausencia e `null` como coisas
   * diferentes, e mandar `null` faria o pydantic recusar o que deveria ser opcional.
   */
  comparar: (base: string, concorrentes: string[], perfil?: NeedsProfile) =>
    chamar<Comparacao>('/comparisons', {
      metodo: 'POST',
      corpo: {
        base_vehicle_id: base,
        competitor_ids: concorrentes,
        ...(perfil ? { needs_profile: perfil } : {}),
      },
    }),
}
