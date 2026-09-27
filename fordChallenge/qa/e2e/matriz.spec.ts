/**
 * A Matriz de paridade: quatro estados, o aviso de par não comparável e "não sabemos"
 * com a mesma proeminência dos outros três (cena 6 do roteiro de 15/09).
 *
 * **Dois testes, não seis.** Cada carregamento da Matriz é uma comparação inteira no
 * servidor, e cada concorrente marcado é outra. Um teste por asserção refazia a matriz
 * inteira a cada vez, e o ensaio passava mais tempo montando tabela que conferindo — peso
 * do ensaio, não do produto. Aqui cada teste abre a tela uma vez e verifica tudo o que
 * aquela tela promete.
 */
import { expect, type Page, test } from '@playwright/test'

import { irPara } from './_ajuda'
import { sessaoCompartilhada } from './_sessao'

const doGestor = sessaoCompartilhada('gestor')

async function abrirMatriz(page: Page): Promise<void> {
  await irPara(page, 'matriz')
  await expect(page.locator('table tbody tr').first()).toBeVisible()
}

async function concorrentes(page: Page): Promise<number> {
  const t = await page.locator('main').innerText()
  return Number(t.match(/Concorrentes \((\d+) de \d+\)/)?.[1] ?? -1)
}

test('os quatro estados, o aviso de par não comparável e "não sabemos" que nunca vira empate', async () => {
  const page = doGestor.page()
  await abrirMatriz(page)
  const main = page.locator('main')

  // A legenda, com os quatro estados e a promessa sobre "perdemos".
  await expect(main).toContainText(/ganhamos/i)
  await expect(main).toContainText(/empate/i)
  await expect(main).toContainText(/perdemos/i)
  await expect(main).toContainText(/não sabemos/i)
  await expect(main).toContainText(
    'O concorrente é melhor neste campo. Aparece sempre, sem exceção.',
  )
  await expect(main).toContainText(
    'Não sabemos: falta valor verificado de um dos lados, ou o campo não tem um lado melhor definido. Nunca é exibido como empate.',
  )

  // O par padrão: três concorrentes.
  await expect(main).toContainText(/contra \d+ concorrente\(s\)/)
  expect(await concorrentes(page)).toBe(3)

  // O aviso de comparabilidade fica **acima** da tabela, e a tabela continua.
  await expect(main).toContainText('par não comparável')
  await expect(page.locator('table tbody tr').first()).toBeVisible()

  // Célula a célula: o desconhecido declara "não sabemos" e jamais "empate".
  const desconhecidas = page.getByTestId('estado-desconhecido')
  const quantas = await desconhecidas.count()
  expect(quantas, 'a base tem campos sem os dois lados').toBeGreaterThan(0)
  for (let i = 0; i < Math.min(quantas, 8); i++) {
    const celula = desconhecidas.nth(i)
    // O rótulo vive no `title` e, para quem usa leitor de tela, num `sr-only` — que o
    // `innerText` não enxerga. `textContent` pega os dois casos.
    const rotulo = (await celula.getAttribute('title')) || (await celula.textContent()) || ''
    expect(rotulo, `célula desconhecida ${i}`).toContain('não sabemos')
    expect(rotulo, `célula desconhecida ${i}`).not.toContain('empate')
  }
})

test('trocar a Ford, filtrar por dimensão e escolher 1, 3 ou 6 concorrentes', async () => {
  const page = doGestor.page()
  await abrirMatriz(page)
  const linhasTodas = await page.locator('table tbody tr').count()

  await page.getByLabel('Dimensão').selectOption({ label: 'motorização' })
  await expect.poll(() => page.locator('table tbody tr').count()).toBeLessThan(linhasTodas)

  await page.getByLabel('Dimensão').selectOption({ label: 'todas as dimensões' })
  await expect.poll(() => page.locator('table tbody tr').count()).toBe(linhasTodas)

  await page
    .getByLabel(/versão Ford de referência/i)
    .selectOption({ label: 'Ranger Raptor 3.0 V6 Bi-turbo 4WD AT' })
  await expect(page.locator('main')).toContainText(
    'Ford Ranger Raptor 3.0 V6 Bi-turbo 4WD AT contra 3 concorrente(s)',
  )

  // 3 → 1
  await page.getByRole('button', { name: /^Volkswagen Amarok V6 Extreme$/ }).first().click()
  await page.getByRole('button', { name: /^Chevrolet S10 High Country$/ }).first().click()
  await expect.poll(() => concorrentes(page)).toBe(1)
  await expect(page.locator('main')).toContainText('contra 1 concorrente(s)')

  // 1 → 6
  for (const nome of [
    /^Volkswagen Amarok V6 Extreme$/,
    /^Chevrolet S10 High Country$/,
    /^Chevrolet S10 LTZ$/,
    /^Chevrolet S10 Z71$/,
    /^Toyota Hilux SRV AT$/,
  ]) {
    await page.getByRole('button', { name: nome }).first().click()
  }
  await expect.poll(() => concorrentes(page)).toBe(6)
  await expect(page.locator('main')).toContainText('contra 6 concorrente(s)')
})
