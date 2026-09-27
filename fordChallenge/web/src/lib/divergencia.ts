/**
 * **"As fontes divergem" nem sempre é verdade.**
 *
 * A ficha da Ranger Raptor mostra 5,8 s e 6,5 s para a aceleração 0–100, e escrevia, ao
 * lado, *"As fontes divergem"*. Só que a fonte é **uma só**: a mesma matéria da
 * Autoesporte registra o número que a Ford declara e o que a revista cronometrou. As duas
 * evidências têm a mesma `source_url`, byte a byte.
 *
 * Não são duas fontes discordando; é uma fonte registrando duas coisas diferentes — e a
 * diferença entre elas é o melhor argumento que a página oferece a quem vende. Dizer "as
 * fontes divergem" erra o fato **e** joga fora o argumento.
 *
 * **Três saídas, e não duas.** A terceira é a que mantém o produto honesto:
 *
 * 1. URLs diferentes → as fontes divergem mesmo;
 * 2. mesma URL **com** os tipos → "Mesma fonte, dois valores: declarado × medido";
 * 3. mesma URL **sem** os tipos (evidência antiga, `tipo_de_afirmacao` nulo) → a frase
 *    neutra, que é verdadeira sem afirmar o que não se sabe.
 *
 * Nunca inventar "declarado × medido" só porque as URLs são iguais. A igualdade de URL diz
 * que a fonte é a mesma; ela não diz o que a fonte estava fazendo.
 */
import type { Campo, Evidencia } from './tipos'

export const FONTES_DIFERENTES = 'As fontes divergem. Os dois valores, com a evidência de cada:'
export const MESMA_FONTE_SEM_TIPO = 'Mesma fonte, dois valores. Cada um com o seu trecho:'

/** Como cada tipo se lê na tela. */
export const ROTULO_DO_TIPO_DE_AFIRMACAO: Record<string, string> = {
  declarado: 'declarado',
  medido: 'medido',
  listado: 'listado',
}

function evidenciasDe(dados: Campo): Evidencia[] {
  const todas = [...dados.evidences]
  for (const conflito of dados.conflicts) {
    if (conflito.evidence) todas.push(conflito.evidence)
  }
  return todas
}

/** A frase que explica a divergência deste campo. */
export function textoDaDivergencia(dados: Campo): string {
  const evidencias = evidenciasDe(dados)
  if (evidencias.length < 2) return FONTES_DIFERENTES

  const urls = new Set(evidencias.map((e) => e.source_url).filter(Boolean))
  if (urls.size !== 1) return FONTES_DIFERENTES

  // Mesma fonte. Agora: ela diz o que estava fazendo em cada valor?
  const tipos: string[] = []
  for (const evidencia of evidencias) {
    const tipo = evidencia.tipo_de_afirmacao
    if (tipo && !tipos.includes(tipo)) tipos.push(tipo)
  }
  if (tipos.length < 2) return MESMA_FONTE_SEM_TIPO

  const lidos = tipos.map((t) => ROTULO_DO_TIPO_DE_AFIRMACAO[t] ?? t)
  return `Mesma fonte, dois valores: ${lidos.join(' × ')}.`
}

/** O sufixo que qualifica um valor na linha da divergência: `· declarado`. */
export function sufixoDoTipo(evidencia: Evidencia | undefined): string {
  const tipo = evidencia?.tipo_de_afirmacao
  if (!tipo) return ''
  return ` · ${ROTULO_DO_TIPO_DE_AFIRMACAO[tipo] ?? tipo}`
}
