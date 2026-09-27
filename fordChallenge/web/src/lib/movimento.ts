/**
 * Movimento: o pouco que existe, e a única pergunta que o governa.
 *
 * A pergunta é "isto explica alguma coisa?". Fade de rota explica que a tela trocou;
 * gaveta deslizando explica de onde ela veio; linha aparecendo em sequência explica que a
 * lista chegou agora; contador subindo explica que aquele número foi apurado. Fora disso,
 * `030_ANTI_PADROES.md` §19 e §20 proíbem: nada de animação em hover, nada de seta
 * animada, nada de brilho, nada de parallax.
 *
 * **`prefers-reduced-motion` é decidido em dois lugares, de propósito.** O CSS zera a
 * duração de toda animação e transição (`index.css`), o que cobre fade, deslize e brilho
 * sem que nenhum componente precise saber. O que o CSS **não** alcança é animação feita em
 * JavaScript — o contador sobe mudando o texto, e texto trocando 60 vezes por segundo é
 * exatamente o tipo de movimento que quem pede menos movimento não quer. Por isso o hook.
 */

import { useSyncExternalStore } from 'react'

const CONSULTA = '(prefers-reduced-motion: reduce)'

function assinar(aoMudar: () => void): () => void {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {}
  const consulta = window.matchMedia(CONSULTA)
  consulta.addEventListener('change', aoMudar)
  return () => consulta.removeEventListener('change', aoMudar)
}

function ler(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia(CONSULTA).matches
}

/** `true` quando o sistema de quem olha pede menos movimento. */
export function usePrefereMenosMovimento(): boolean {
  // O terceiro argumento é o valor do servidor: sem janela, não há preferência a respeitar
  // e também não há animação acontecendo.
  return useSyncExternalStore(assinar, ler, () => false)
}

/**
 * O atraso da linha `indice` numa lista que aparece escalonada.
 *
 * 30 ms por linha, **no máximo dez**: a partir da décima o atraso para de crescer e a
 * lista inteira chega junto. Sem o teto, uma fila de quarenta alertas levaria 1,2 s para
 * terminar de aparecer — e a última linha é dado, não cortina.
 */
export const PASSO_DO_ESCALONAMENTO_MS = 30
export const MAXIMO_ESCALONADO = 10

export function atrasoDaLinha(indice: number): string {
  return `${Math.min(indice, MAXIMO_ESCALONADO) * PASSO_DO_ESCALONAMENTO_MS}ms`
}
