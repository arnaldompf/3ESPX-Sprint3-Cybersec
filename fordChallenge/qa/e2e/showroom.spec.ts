/**
 * O Showroom pelos olhos do vendedor: perfil, aderência, argumentário e registro.
 *
 * QA-BUG-13 mora aqui: o aviso de dimensão insuficiente saía com os nomes de coluna do
 * banco ("Sem dado comparável em: reduzida, bloqueio_diferencial, pneus_tipo,
 * amortecedores.") e com asteriscos de Markdown que a tela não interpreta ("dimensão
 * **excluída do total**"). É a tela que o vendedor abre na frente do cliente.
 */
import { expect, type Page, test } from '@playwright/test'

import { irPara } from './_ajuda'
import { sessaoCompartilhada } from './_sessao'

const PERFIL_FAZENDEIRO = 'trabalho rural / carga'

const sessao = sessaoCompartilhada('vendedor')

async function compararFazendeiro(page: Page, kmMes = '2000') {
  await irPara(page, 'showroom')
  await page.getByLabel(/^versão Ford$/).selectOption({ label: 'Ranger Limited 3.0 V6 Diesel 4WD AT' })
  await page.getByLabel(/^concorrente$/).selectOption({ label: 'Toyota Hilux SRX Plus AT' })
  await page.getByRole('button', { name: PERFIL_FAZENDEIRO }).click()
  await page.getByLabel('km por mês').fill(kmMes)
  await page.getByRole('button', { name: 'comparar por este perfil' }).click()
  await expect(page.getByRole('heading', { name: 'Aderência ao perfil' })).toBeVisible()
}

test('a comparação do fazendeiro sai com as duas notas e o rótulo de aderência', async () => {
  const page = sessao.page()
  await compararFazendeiro(page)
  const main = page.locator('main')

  await expect(main).toContainText('Aderência ao perfil informado — não é um ranking de qualidade')
  await expect(main).toContainText('Onde Ford Ranger Limited 3.0 V6 Diesel 4WD AT vence')
  await expect(main).toContainText('Onde Toyota Hilux SRX Plus AT vence')
  await expect(main).toContainText('O produto não esconde onde o concorrente ganha')
  // O peso considerado à vista, com o denominador — nunca uma nota solta.
  await expect(main).toContainText(/calculado sobre \d+% do peso do perfil/)
})

test('nenhum nome de campo do banco nem Markdown cru na tela do vendedor (QA-BUG-13)', async () => {
  const page = sessao.page()
  await compararFazendeiro(page)

  const texto = await page.locator('main').innerText()
  const linhas = texto.split(String.fromCharCode(10))

  const comUnderscore = linhas.filter(
    (l) => /[a-z0-9]_[a-z0-9]/.test(l) && !/https?:|file:/.test(l),
  )
  expect(comUnderscore, `nome de campo cru: ${comUnderscore.join(' | ')}`).toEqual([])

  const comAsterisco = linhas.filter((l) => l.includes('**'))
  expect(comAsterisco, `Markdown cru: ${comAsterisco.join(' | ')}`).toEqual([])
})

test('dimensão sem dado sai marcada com o motivo, nunca vira nota baixa', async () => {
  const page = sessao.page()
  await compararFazendeiro(page)
  const main = page.locator('main')

  await expect(main).toContainText('insuficiente: fora do total')
  await expect(main).toContainText('ficou fora do total por falta de dado comparável')
  await expect(main).toContainText('Sem dado comparável em:')
})

test('consumo sem ano aplicável não sustenta estimativa de custo', async () => {
  const page = sessao.page()
  await compararFazendeiro(page, '2000')
  const main = page.locator('main')

  await expect(main).toContainText('Custo de combustível estimado')
  await expect(main).toContainText('sem custo estimado: falta consumo')
  await expect(main).toContainText('não há diferença a calcular')
  await expect(main.locator('[data-testid^="custo-"]').filter({ hasText: '/mês' })).toHaveCount(0)
})

test('km/mês zero não quebra a estimativa', async () => {
  const page = sessao.page()
  await compararFazendeiro(page, '0')
  const main = page.locator('main')
  await expect(main).toContainText('Custo de combustível estimado')
  await expect(main).not.toContainText('NaN')
  await expect(main).not.toContainText('Infinity')
})

test('o argumentário cita cada ponto e explica quando falta vantagem comprovada do concorrente', async () => {
  const page = sessao.page()
  await compararFazendeiro(page)
  await page.getByRole('button', { name: 'gerar argumentos' }).click()

  const main = page.locator('main')
  // O consumo sem MY aplicável saiu da comparação; não se inventa um quarto ponto.
  await expect(main).toContainText('nenhuma dimensão com dado comparável em que o concorrente leve vantagem')
  await expect(main).toContainText('Isto não significa que ele não tenha nenhuma')
  await expect(page.getByTestId('ponto-de-atencao')).toHaveCount(0)
  // Cada ponto traz uma URL e uma data entre parênteses.
  const texto = await main.innerText()
  const comFonte = texto.match(/\(https?:\/\/[^\s]+, \d{2}\/\d{2}\/\d{4}\)/g) ?? []
  expect(comFonte.length, 'pontos com fonte e data').toBeGreaterThanOrEqual(3)
})

test('o fluxo sobrevive a ir até a Ficha e voltar', async () => {
  // O defeito que um avaliador relatou em 12/09/2026: o vendedor escolhia o par, marcava
  // os usos, ordenava as prioridades, comparava — e ao abrir a Ficha para conferir um
  // campo perdia tudo. `/showroom` é uma rota dentro do Layout, e navegar desmontava o
  // componente com os oito `useState` do fluxo dentro. Com o cliente ao lado, refazer
  // seis toques é o que faz alguém parar de usar a ferramenta.
  const page = sessao.page()
  await compararFazendeiro(page, '3200')

  await irPara(page, 'consulta')
  await expect(page.getByRole('heading', { level: 1, name: 'Consulta' })).toBeVisible()
  await irPara(page, 'showroom')

  await expect(page.getByLabel(/^versão Ford$/)).toHaveValue(/.+/)
  const ford = await page.getByLabel(/^versão Ford$/).inputValue()
  expect(ford, 'a versão Ford voltou vazia').not.toBe('')
  await expect(page.getByLabel('km por mês')).toHaveValue('3200')
  // O perfil marcado continua marcado.
  await expect(page.getByRole('button', { name: PERFIL_FAZENDEIRO })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
})

test('o selo diz quem está à frente, e nunca "melhor"', async () => {
  const page = sessao.page()
  await compararFazendeiro(page)
  const selo = page.getByTestId('selo-de-resultado')
  await expect(selo).toBeVisible()
  const texto = (await selo.innerText()).toLowerCase()
  expect(texto).toMatch(/à frente por \d|empate técnico/)
  // `docs/12` §3: o score é aderência ao perfil informado, não julgamento de qualidade.
  expect(texto).not.toMatch(/melhor|superior|ganha de/)
})

test('registrar fechou, perdeu com motivo e em andamento', async () => {
  const page = sessao.page()
  // Uma comparação, uma sessão, os três desfechos em sequência: depois do primeiro
  // registro o botão "abrir sessão" some e o formulário continua — corrigir o desfecho
  // da conversa é o caso real. Refazer a comparação a cada volta só faria o ensaio
  // esperar de novo pelo que ele já tinha na tela.
  await compararFazendeiro(page)
  await page.getByRole('button', { name: /^abrir sessão$/i }).click()
  await expect(page.getByRole('group', { name: '1. Desfecho' })).toBeVisible()

  for (const [desfecho, motivo] of [
    ['fechou', null],
    ['perdeu', 'preço'],
    ['em andamento', null],
  ] as const) {
    await page.getByRole('button', { name: new RegExp(`^${desfecho}$`) }).click()

    if (motivo) {
      // O passo 2 só existe quando a venda foi perdida.
      await expect(page.getByRole('group', { name: '2. Por que perdeu' })).toBeVisible()
      await page.getByRole('checkbox', { name: motivo }).check()
    } else {
      await expect(page.getByRole('group', { name: '2. Por que perdeu' })).toHaveCount(0)
      // …e aí o atributo decisivo é o passo **2**, não o 3: a numeração é dos passos
      // visíveis. Com números literais a tela pulava de "1." para "3." (QA-22).
      await expect(page.getByLabel('atributo decisivo')).toBeVisible()
      await expect(page.locator('main')).toContainText('2. Atributo decisivo')
      await expect(page.locator('main')).not.toContainText('3. Atributo decisivo')
    }

    await page.getByRole('button', { name: /registrar resultado/i }).click()
    await expect(page.locator('main')).toContainText('Resultado registrado')
  }
})
