/**
 * Uma página por arquivo de teste, e não uma por teste.
 *
 * **Por que.** Uma pessoa não recarrega o aplicativo a cada tela: ela abre uma vez e
 * navega. Abrir uma página por teste também custaria um carregamento completo do
 * aplicativo em cada um — e o que esta suíte mede é a cena, não o `boot`.
 *
 * Até 11/09/2026 havia um segundo motivo, mais duro: o limite de 60 requisições por
 * minuto de `docs/02`. Uma sessão por teste esgotava a cota de um papel em poucos minutos
 * e as telas passavam a responder "Muitas requisições" — defeito do ensaio, não do
 * produto. O limite saiu do caminho de execução (D-206) e esse motivo caiu; o primeiro
 * continua valendo, e é o suficiente.
 *
 * O preço é que um teste que quebre a página atrapalha o seguinte. Com `workers: 1` e
 * uma suíte que verifica tela, é troca boa — e cada teste começa navegando para onde
 * precisa, o que reinicia o estado da tela.
 *
 * Uso:
 *
 * ```ts
 * const sessao = sessaoCompartilhada('vendedor')
 * test('…', async () => {
 *   const page = sessao.page()
 *   …
 * })
 * ```
 */
import { type Browser, type Page, test } from '@playwright/test'

import { entrar, type Papel } from './_ajuda'

export interface SessaoCompartilhada {
  /** A página autenticada do arquivo. Só vale dentro de um teste. */
  page(): Page
}

export function sessaoCompartilhada(papel: Papel): SessaoCompartilhada {
  test.describe.configure({ mode: 'serial' })

  let pagina: Page | undefined

  test.beforeAll(async ({ browser }: { browser: Browser }) => {
    pagina = await browser.newPage()
    await entrar(pagina, papel)
  })

  test.afterAll(async () => {
    await pagina?.close()
    pagina = undefined
  })

  return {
    page() {
      if (!pagina) throw new Error('a sessão compartilhada não foi aberta')
      return pagina
    },
  }
}
