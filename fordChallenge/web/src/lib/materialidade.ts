/**
 * O vocabulário da fila de prioridade. **Nenhuma regra de negócio aqui.**
 *
 * A régua inteira — os pesos, os limiares e a frase que define cada faixa — vive em
 * `pipeline/materiality/rules.yaml`, e a API manda o `significado` junto com o evento.
 * Este módulo só decide como a faixa **aparece**: o rótulo em português, a cor e o ícone.
 *
 * A separação é a mesma de `radar.ts`: traduzir é trabalho da tela, decidir não é. Se a
 * cor viesse com uma segunda definição do que é "ALTA", uma revisão do YAML deixaria a
 * tela pintando o contrário do que a régua diz.
 */
import type { Materialidade } from './tipos'

/** A ordem da fila. Mais urgente primeiro — a mesma de `BASE_DO_RANK` no motor. */
export const ORDEM_DAS_FAIXAS: Materialidade[] = ['ALTA', 'MEDIA', 'BAIXA', 'RUIDO']

export const ROTULO_DA_FAIXA: Record<string, string> = {
  ALTA: 'Alta',
  MEDIA: 'Média',
  BAIXA: 'Baixa',
  RUIDO: 'Ruído',
}

/**
 * Cor **e** ícone, nunca só cor: a faixa é a informação mais importante da fila, e
 * vermelho contra verde é o par clássico de confusão em daltonismo (mesma razão do
 * `Badge`).
 */
export const CLASSES_DA_FAIXA: Record<string, string> = {
  ALTA: 'bg-perdemos-fundo text-alta',
  MEDIA: 'bg-naoSabemos-fundo text-media',
  BAIXA: 'bg-superficie-2 text-baixa',
  RUIDO: 'bg-superficie-2 text-ruido',
}

/** A cor do ponto de 6 px dentro do pill de prioridade. */
export const PONTO_DA_FAIXA: Record<string, string> = {
  ALTA: 'bg-alta',
  MEDIA: 'bg-media',
  BAIXA: 'bg-baixa',
  RUIDO: 'bg-ruido',
}

export const ICONE_DA_FAIXA: Record<string, string> = {
  ALTA: '▲',
  MEDIA: '◆',
  BAIXA: '▽',
  RUIDO: '·',
}

/** A pontuação com sinal. Peso negativo existe (`par_nao_comparavel` subtrai). */
export function formatarPontos(pontos: number): string {
  return `${pontos > 0 ? '+' : ''}${pontos.toLocaleString('pt-BR')} ponto(s)`
}

/**
 * A inversão de paridade em português.
 *
 * O texto é montado aqui e não no back-end porque é frase de tela; o **dado** (o campo e
 * os dois estados) vem da API, e nenhum dos dois lados é recalculado.
 */
const ESTADO_DE_PARIDADE: Record<string, string> = {
  vantagem: 'vantagem da Ford',
  paridade: 'paridade',
  gap: 'gap contra a Ford',
  desconhecido: 'desconhecido',
}

export function frasearInversao(antes?: string, depois?: string): string {
  const de = antes ? (ESTADO_DE_PARIDADE[antes] ?? antes) : 'estado anterior não registrado'
  const para = depois ? (ESTADO_DE_PARIDADE[depois] ?? depois) : 'estado novo não registrado'
  return `${de} → ${para}`
}
