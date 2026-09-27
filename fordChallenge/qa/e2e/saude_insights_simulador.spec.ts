/**
 * Saúde do conhecimento, Insights de win/loss e Simulador de cenário.
 *
 * Um arquivo e um teste por tela, de propósito: cada tela dessas é uma consulta pesada no
 * servidor. Um teste por asserção refazia as três telas a cada vez, e o ensaio passava
 * mais tempo carregando que conferindo — peso do ensaio, não do produto.
 */
import { expect, test } from '@playwright/test'

import { irPara } from './_ajuda'
import { sessaoCompartilhada } from './_sessao'

/**
 * Uma sessão para as três telas, no papel do gestor — que é quem abre Insights e
 * Simulador, e também enxerga a Saúde. Uma sessão por arquivo, e não uma por teste: o
 * papel do gestor alcança as três, e trocar de papel no meio embaralharia o que se mede.
 */
const doGestor = sessaoCompartilhada('gestor')

test('Saúde: status por regra, denominador em cada métrica e as divergências nos dois escopos', async () => {
  const page = doGestor.page()
  await irPara(page, 'saude')
  const main = page.locator('main')

  // Um status por versão, e cada um vem de uma regra com nome — não de uma nota.
  await expect(main).toContainText(/INSUFICIENTE|REVISAR|OK/)
  await expect(main).toContainText('por que este status?')
  await page.getByRole('button', { name: /por que este status\?/i }).first().click()
  await expect(main).toContainText(/regra: [a-z_]+ · limiar de \d+ dias/)
  await expect(main).toContainText('poucos_verificados')
  await expect(main).toContainText('tem_conflito')

  // Cobertura de pesquisa exclui os quatro campos de identidade: 54 campos.
  await expect(main).toContainText(/\d+\/\d+/)
  await expect(main).toContainText('Cobertura por montadora')
  await expect(main).toContainText(/\d+ de 54/)

  // "ver quais, e por quê" abre com o motivo escrito.
  const detalhe = page.locator('main details').first()
  await detalhe.locator('summary').click()
  await expect(detalhe).toContainText(/fonte bloqueada|conflito|desatualizad|não confirmad/i)

  // Os dois escopos de divergência.
  await expect(main).toContainText('oficial × imprensa')
  await page.getByLabel(/escopo/i).selectOption({ label: 'material interno × fonte pública' })
  await expect(main).toContainText('referência interna')
  await expect(main).toContainText('fonte pública')
})

test('Insights: real e simulado em blocos separados, contagem sem percentual abaixo de n=20', async () => {
  const page = doGestor.page()
  await irPara(page, 'insights')
  const main = page.locator('main')

  await expect(main).toContainText('Percentual só aparece com n ≥ 20')
  await expect(main).toContainText('SIMULAÇÃO')
  await expect(main).toContainText(/separadas das \d+ reais/)
  await expect(main).toContainText('Os dois blocos nunca são somados')

  // O bloco real: contagens, e percentual só quando a amostra dá.
  const texto = await main.innerText()
  const real = Number(texto.match(/real n = (\d+)/)?.[1] ?? -1)
  expect(real, 'o resumo declara o n real').toBeGreaterThanOrEqual(0)
  if (real > 0 && real < 20) {
    await expect(main).toContainText(`Um percentual sobre ${real} caso(s)`)
  }

  // O filtro "desde": uma data no futuro zera o real e o estado vazio é digno.
  await page.getByLabel('desde').fill('2027-12-31')
  await expect(main).toContainText('Nenhuma sessão real registrada ainda')
  await expect(main).toContainText('Quando os vendedores fecharem uma sessão')
  await expect(main).not.toContainText('undefined')
  await expect(main).not.toContainText('NaN')
})

test('Simulador: abre com cenário de verdade, hipótese marcada e nada gravado', async () => {
  const page = doGestor.page()
  await irPara(page, 'simulador')
  const main = page.locator('main')

  await expect(main).toContainText('SIMULAÇÃO')
  await expect(main).toContainText('tudo nesta tela é hipótese informada por você')

  // O par padrão é Ranger Limited × Amarok V6 Extreme (D-208): os dois têm
  // `preco_sugerido_brl`, e sem preço dos dois lados a pergunta desta tela ("e se o
  // concorrente baixar 5%?") não tem sobre o que incidir. Antes o padrão era a Hilux,
  // que não tem preço: a tela abria em "Sem cenário para este par" e o apresentador
  // trocava o concorrente à mão, ao vivo.
  await expect(page.getByLabel(/concorrente do cenário/i)).toHaveValue(/.+/)
  await expect(main).toContainText('Volkswagen Amarok V6 Extreme')
  await expect(main).not.toContainText('preco_sugerido_brl')
  await expect(main).not.toContainText('None')
  // A Realidade continua à vista ao lado da hipótese, que é o ponto de D-198.
  await expect(main).toContainText('Realidade')
  await expect(main).toContainText(/ganhamos/i)

  const slider = page.locator('input[type=range]')

  for (const passo of ['-10', '-5', '0', '10']) {
    await slider.fill(passo)
    await expect(main).toContainText(
      new RegExp(`Preço do concorrente: ${passo === '10' ? '\\+10' : passo}%`),
    )
  }

  await slider.fill('-5')
  await expect(main).toContainText('379.990')
  await expect(main).toContainText('360.990')
  await expect(main).toContainText('hipótese informada pelo usuário')
  await expect(main).toContainText('SIMULAÇÃO — não é dado observado')

  // Remover itens muda o cenário e continua sem gravar nada.
  await page.getByRole('checkbox', { name: 'Potência (cv)' }).check()
  await page.getByRole('checkbox', { name: 'Torque (N·m)' }).check()
  await page.getByRole('checkbox', { name: 'Capacidade carga (kg)' }).check()
  await expect(main).toContainText('Potência (cv):')
  await expect(main).toContainText('Torque (N·m):')
})
