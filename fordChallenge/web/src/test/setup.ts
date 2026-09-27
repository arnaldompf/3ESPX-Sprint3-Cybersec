import '@testing-library/jest-dom/vitest'
import { beforeEach } from 'vitest'

import { limparFluxo } from '@/lib/fluxoShowroom'
import { esquecerPapel } from '@/lib/papel'

/**
 * Cada teste começa no papel inicial, e nenhum herda o papel do anterior.
 *
 * O papel vive fora do React de propósito (memória do módulo + `localStorage`, para
 * sobreviver ao recarregamento). O preço disso num arquivo de teste é que ele **também**
 * sobrevive entre testes: um teste que troca para `vendedor` para conferir a recusa
 * deixaria o próximo esperando a fila do analista e vendo um cartão de recusa, com a
 * falha aparecendo no teste errado. Zerar aqui é estrutural, e não disciplina de quem
 * escreve o teste.
 */
beforeEach(() => {
  esquecerPapel()
  // O fluxo do Showroom vive em `sessionStorage` para sobreviver à troca de tela. O
  // preço é o mesmo do papel: sem zerar aqui, um teste que escolhe um par deixaria o
  // próximo começando com esse par na tela, e a falha apareceria no teste errado.
  limparFluxo()
})
