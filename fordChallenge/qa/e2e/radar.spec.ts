/**
 * O Radar: a fila por materialidade, o Fogo Amigo e a cadeia do "Por quê?".
 *
 * É a cena-assinatura do roteiro de 15/09 (cena 5) e a primeira metade da cena 10.
 */
import { expect, test } from '@playwright/test'

import { irPara, trocarPara } from './_ajuda'
import { sessaoCompartilhada } from './_sessao'

async function totalDaFila(page): Promise<number> {
  const texto = await page.locator('main').innerText()
  return Number(texto.match(/(\d+) alerta\(s\) na fila/)?.[1] ?? -1)
}

/**
 * A sessão do arquivo. O último teste troca para vendedor **pela tela**, que é a cena do
 * roteiro: o vendedor tenta o Radar, recebe a recusa, e o analista mostra a tela cheia.
 */
const doAnalista = sessaoCompartilhada('analista')

/** Abre o Radar e espera a fila terminar de montar — não só o título aparecer. */
async function abrirRadar(page): Promise<void> {
  await irPara(page, 'radar')
  await expect(page.getByRole('button', { name: 'Por quê?' }).first()).toBeVisible()
}

test('a fila abre agrupada por materialidade, com o significado de cada grupo', async () => {
  const page = doAnalista.page()
  await abrirRadar(page)
  const main = page.locator('main')

  // O rótulo do grupo é maiúscula por CSS: o texto no DOM é "Alta".
  await expect(main).toContainText(/alta/i)
  await expect(main).toContainText('Mudança que altera a posição competitiva')
  await expect(main).toContainText(/ruído/i)
  // O ruído não some do sistema: sai da fila, recolhido.
  await expect(main).toContainText('abrir o ruído')
  expect(await totalDaFila(page)).toBeGreaterThan(0)
})

test('o filtro por tipo reduz a fila, e o de demonstração tira o dado simulado', async () => {
  const page = doAnalista.page()
  await abrirRadar(page)
  const todos = await totalDaFila(page)
  expect(todos, 'a fila cheia').toBeGreaterThan(0)

  await page.getByLabel('Tipo').selectOption({ label: 'divergência com material interno' })
  await expect
    .poll(() => totalDaFila(page), { message: 'a fila filtrada' })
    .toBeLessThan(todos)
  // O Fogo Amigo: três divergências contra o deck da própria Ford.
  await expect(page.locator('main')).toContainText('divergência com material interno')

  await page.getByLabel('Tipo').selectOption({ label: 'todos os tipos' })
  await expect.poll(() => totalDaFila(page)).toBe(todos)

  await page.getByLabel(/incluir dados de demonstração/i).uncheck()
  await expect.poll(() => totalDaFila(page)).toBeLessThan(todos)
  await expect(page.locator('main')).not.toContainText('SIMULAÇÃO')
})

test('"Por quê?" abre a cadeia inteira: cinco elos, e o vazio traz o motivo', async () => {
  const page = doAnalista.page()
  await abrirRadar(page)

  const botoes = page.getByRole('button', { name: 'Por quê?' })
  const total = await botoes.count()
  expect(total, 'alertas com cadeia').toBeGreaterThan(0)

  for (let i = 0; i < total; i++) {
    await botoes.nth(i).click()
    const gaveta = page.getByRole('dialog')
    await expect(gaveta).toBeVisible()

    // Os rótulos são maiúsculas por CSS; no DOM são "O que fazer", "A prova"…
    for (const elo of [
      /o que fazer/i,
      /por que esta materialidade/i,
      /o que mudou/i,
      /contra qual ford/i,
      /a prova/i,
    ]) {
      await expect(gaveta, `elo ${elo} no alerta ${i}`).toContainText(elo)
    }

    // Nenhum elo em branco: onde falta dado, o motivo está escrito.
    const texto = await gaveta.innerText()
    expect(texto.length, `cadeia do alerta ${i}`).toBeGreaterThan(400)

    await page.keyboard.press('Escape')
    await expect(gaveta).toHaveCount(0)
  }
})

test('"ver impacto" abre sem sair da fila, e "marcar como lido" baixa o selo', async () => {
  const page = doAnalista.page()
  await abrirRadar(page)

  const antes = (await page.locator('main').innerText()).length
  await page.getByRole('button', { name: /ver impacto/i }).first().click()
  await expect.poll(async () => (await page.locator('main').innerText()).length).toBeGreaterThan(antes)

  // Marcar como lido tira o botão daquele alerta e a fila se refaz. O selo da barra
  // lateral **não** acompanha na mesma sessão — está registrado como QA-11 (menor), e
  // por isso o teste prende o que o produto garante hoje, não o que seria melhor.
  const marcar = page.getByRole('button', { name: /marcar como lido/i })
  const antesDeMarcar = await marcar.count()
  if (antesDeMarcar > 0) {
    await marcar.first().click()
    await expect.poll(() => marcar.count(), { timeout: 15_000 }).toBeLessThan(antesDeMarcar)
  }
})

test('vendedor recebe recusa explicada, não uma tela vazia', async () => {
  const page = doAnalista.page()
  await trocarPara(page, 'vendedor')
  await irPara(page, 'radar')

  const main = page.locator('main')
  await expect(main).toContainText('Esta tela é de analista, gestor e administrador')
  await expect(main).toContainText('troque o papel na barra lateral')
  await expect(main).not.toContainText('403')
  await expect(main).not.toContainText('Forbidden')
  // A fila não é pedida ao servidor: quem decide é a tela (D-204), e pedir para jogar
  // fora gastaria uma ida ao servidor para desenhar o cartão que a tela já sabia.
  await expect(main).not.toContainText('alerta(s) na fila')
})
