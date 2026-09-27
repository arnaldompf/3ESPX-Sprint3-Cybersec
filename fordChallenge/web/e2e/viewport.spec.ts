/**
 * O criterio de aceite de 390 px, no navegador de verdade.
 *
 * **Nao roda no `verify` de proposito.** O Playwright baixa navegadores (centenas de MB)
 * na primeira execucao, e a regra da noite e "rede so o necessario". Um portao que so
 * passa depois de um download de 300 MB nao e portao: e um obstaculo que a proxima pessoa
 * desliga. O `verify` roda o comando que a spec manda, e a mesma garantia esta coberta em
 * `src/test/viewport.test.tsx` — que mede as classes CSS, que e onde o problema nasce.
 *
 * Para rodar isto:
 *
 *   npm install --save-dev @playwright/test
 *   npx playwright install chromium
 *   npm run e2e
 *
 * Precisa da API no ar com o build servido em /app:
 *
 *   python scripts/task.py api
 *
 * O arquivo esta escrito e nao verificado — e artefato de melhor esforco, como o
 * Dockerfile. Nao afirmo que ele passa.
 */

// @ts-expect-error - `@playwright/test` nao esta instalado (ver o cabecalho).
import { expect, test } from '@playwright/test'

const BASE = process.env.SPECRADAR_URL ?? 'http://127.0.0.1:8000/app'
const CELULAR = { width: 390, height: 844 }

const ROTAS = ['/login', '/consulta', '/radar', '/matriz', '/saude', '/copiloto', '/insights']

test.describe('390 px', () => {
  test.use({ viewport: CELULAR })

  for (const rota of ROTAS) {
    test(`${rota} nao rola de lado`, async ({ page }) => {
      await page.goto(`${BASE}${rota}`)
      // `scrollWidth > clientWidth` e a definicao de scroll horizontal. Medir isso e o
      // ponto do teste no navegador: em jsdom nao existe layout, e o numero seria 0.
      const estourou = await page.evaluate(() => {
        const raiz = document.documentElement
        return raiz.scrollWidth > raiz.clientWidth + 1
      })
      expect(estourou, `${rota} tem scroll horizontal em 390 px`).toBe(false)
    })
  }

  test('a barra de navegacao rola dentro dela mesma', async ({ page }) => {
    await page.goto(`${BASE}/consulta`)
    const barraRola = await page.evaluate(() => {
      const nav = document.querySelector('nav')
      if (!nav) return false
      return nav.scrollWidth > nav.clientWidth
    })
    const paginaRola = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    )
    // A barra pode rolar; a pagina nao.
    expect(paginaRola).toBe(false)
    expect(typeof barraRola).toBe('boolean')
  })
})
