/**
 * Perguntas sobre a tela que o CSS não responde sozinho.
 *
 * O caso é o Showroom: em ≤ 768 px ele é um **stepper de um passo por vez** (o vendedor
 * está de pé, com o celular na mão, na frente do cliente), e em tela larga os cinco passos
 * aparecem empilhados — cinco cliques para preencher um formulário que cabe inteiro na
 * tela seria burocracia. Esconder por `display:none` não serve aqui: o passo escondido
 * continuaria recebendo `Tab`, e o `<select>` do passo 1 seria focável estando invisível.
 *
 * `matchMedia` ausente devolve `false`, e `false` é o lado seguro: sem a API, a tela mostra
 * **tudo**. É o que acontece em jsdom, e é a resposta certa lá — um teste que não consegue
 * medir a janela não deve ver metade da página escondida.
 */

import { useEffect, useState } from 'react'

export function useMediaQuery(consulta: string): boolean {
  const [casa, setCasa] = useState(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
    return window.matchMedia(consulta).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined
    const lista = window.matchMedia(consulta)
    const aoMudar = (evento: MediaQueryListEvent) => setCasa(evento.matches)
    setCasa(lista.matches)
    lista.addEventListener('change', aoMudar)
    return () => lista.removeEventListener('change', aoMudar)
  }, [consulta])

  return casa
}

/** O limiar de `010_DESIGN.md` §8: até 768 px a tela é de celular. */
export const E_CELULAR = '(max-width: 768px)'
