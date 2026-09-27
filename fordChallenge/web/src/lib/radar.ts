/**
 * A leitura humana do alerta: rótulo do tipo, sentido do impacto, texto do gap.
 *
 * Fica separado da tela por um motivo prático: **o sinal do número não diz o sentido**.
 * Um delta de −R$ 18.800 no preço do concorrente é ruim para a Ford; o mesmo −R$ 18.800
 * num preço Ford é bom. Quem decide isso é `pipeline/radar/impact.py`, que já devolve
 * `direcao` do ponto de vista da Ford — aqui a tela só **traduz**, nunca recalcula. Ter
 * duas contas de sentido (uma no back, outra no componente) é como se produz uma tela que
 * diz "favorece" ao lado de uma seta para baixo.
 *
 * O `gap` segue a convenção do back-end: **positivo = Ford mais cara**.
 */
import type { Impacto } from './tipos'

/** Os sete tipos de `docs/12` §6.1, em português. O ícone de cada um vive em `Icones.tsx`. */
export const ROTULO_DO_TIPO: Record<string, string> = {
  preco_oficial: 'preço de tabela',
  preco_fipe: 'preço FIPE',
  versao_nova: 'versão nova',
  versao_removida: 'versão removida',
  campo_alterado: 'especificação alterada',
  fonte_bloqueada: 'fonte bloqueada',
  referencia_interna_divergente: 'divergência com material interno',
}

/** As dimensões do Need Engine, em português. Mapa de `impact.DIMENSOES_POR_CAMPO`. */
export const ROTULO_DA_DIMENSAO: Record<string, string> = {
  preco: 'preço',
  revenda: 'revenda',
  custo_de_uso: 'custo de uso',
  carga: 'carga',
  desempenho: 'desempenho',
  off_road: 'off-road',
  seguranca: 'segurança',
}

interface Sentido {
  rotulo: string
  /** Classe de cor. Nunca é o único portador do sentido — o texto vem junto. */
  classe: string
  seta: string
}

const NEUTRO: Sentido = {
  rotulo: 'sentido não determinado',
  classe: 'bg-empate-fundo text-empate',
  seta: '•',
}

const SENTIDOS: Record<string, Sentido> = {
  neutro: NEUTRO,
  favorece_ford: {
    rotulo: 'favorece a Ford',
    classe: 'bg-ganhamos-fundo text-ganhamos',
    seta: '▲',
  },
  desfavorece_ford: {
    rotulo: 'desfavorece a Ford',
    classe: 'bg-perdemos-fundo text-perdemos',
    seta: '▼',
  },
}

/** Direção desconhecida cai em neutro, não em erro: tipo novo no back não quebra a tela. */
export function sentidoDe(direcao: string): Sentido {
  return SENTIDOS[direcao] ?? NEUTRO
}

const BRL = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  maximumFractionDigits: 0,
})

export function formatarReais(valor: number): string {
  return BRL.format(valor)
}

/** Com sinal explícito: "+R$ 7.122" e "−R$ 18.800" se leem sem precisar do contexto. */
export function formatarDelta(valor: number): string {
  const sinal = valor > 0 ? '+' : valor < 0 ? '−' : ''
  return `${sinal}${BRL.format(Math.abs(valor))}`
}

export function formatarPct(valor: number): string {
  const sinal = valor > 0 ? '+' : valor < 0 ? '−' : ''
  return `${sinal}${Math.abs(valor).toFixed(2).replace('.', ',')}%`
}

/**
 * A frase do gap, ou o motivo de não haver uma.
 *
 * `null` de `gap_depois` **não** vira "R$ 0": zero de gap significaria preços iguais, o
 * que é uma afirmação. Sem equivalente cadastrado não há afirmação nenhuma a fazer, e o
 * back-end manda o motivo em `motivo_sem_gap` justamente para a tela poder dizer isso.
 */
export function frasearGap(impacto: Impacto): { texto: string; ehFato: boolean } {
  if (impacto.gap_depois === null || impacto.gap_depois === undefined) {
    return {
      texto: impacto.motivo_sem_gap || 'sem gap calculado',
      ehFato: false,
    }
  }
  const depois = impacto.gap_depois
  const lado = depois > 0 ? 'a Ford está mais cara' : depois < 0 ? 'a Ford está mais barata' : 'preços iguais'
  const valor = depois === 0 ? '' : ` em ${BRL.format(Math.abs(depois))}`
  const antes =
    impacto.gap_antes === null || impacto.gap_antes === undefined
      ? ''
      : ` (era ${formatarDelta(impacto.gap_antes)})`
  return { texto: `${lado}${valor}${antes}`, ehFato: true }
}

/** As quatro áreas, na ordem em que a tela as mostra. */
export const AREAS = [
  { chave: 'marketing', rotulo: 'Marketing' },
  { chave: 'vendas', rotulo: 'Vendas' },
  { chave: 'produto', rotulo: 'Produto' },
  { chave: 'ci', rotulo: 'Inteligência competitiva' },
] as const
