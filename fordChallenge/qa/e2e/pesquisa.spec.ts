/**
 * A antiga rota Pesquisa redireciona para a Consulta, onde a conversa identifica o carro.
 *
 * A cena que este arquivo guarda é o critério 2 da spec: alguém digita "Ranger Raptor",
 * que **já está no catálogo com ficha**, e a resposta diz que já temos, com a data da
 * coleta, e oferece abrir a ficha — **sem busca e sem modelo**. É a fala mais barata do
 * sistema e a que a apresentação abre.
 *
 * Roda em `REPLAY_MODE=1` (sem rede): a identificação acha a versão no catálogo antes de
 * pensar em procurar fora.
 */
import { expect, test } from '@playwright/test'

import { sessaoCompartilhada } from './_sessao'

const sessao = sessaoCompartilhada('admin')

test('"Ranger Raptor" já está no catálogo: a conversa diz que já temos e oferece abrir a ficha', async () => {
  const page = sessao.page()
  await page.goto('/app/pesquisa')
  await expect(page).toHaveURL(/\/app\/consulta$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Consulta' })).toBeVisible()
  await page.evaluate(() => sessionStorage.removeItem('specradar.pesquisa.conversa.v1'))
  await page.reload()

  // Nenhuma pesquisa pode sair daqui: o carro já está no catálogo.
  const pesquisasDisparadas: string[] = []
  page.on('request', (r) => {
    if (r.method() === 'POST' && /\/api\/v1\/research$/.test(r.url())) pesquisasDisparadas.push(r.url())
  })

  const caixa = page.getByTestId('pesquisa-caixa')
  await expect(caixa).toBeEnabled()
  await caixa.fill('Ranger Raptor')
  await page.getByTestId('pesquisa-enviar').click()

  // O que a pessoa disse aparece como mensagem dela, com hora HH:MM:SS.
  const minha = page.getByTestId('mensagem-texto').first()
  await expect(minha).toContainText('Ranger Raptor')
  await expect(minha.getByTestId('hora-da-mensagem')).toHaveText(/^\d{2}:\d{2}:\d{2}$/)

  // A resposta: já temos, com a data da coleta e o caminho para a ficha.
  const resposta = page.getByTestId('ja-temos')
  await expect(resposta).toBeVisible({ timeout: 60_000 })
  await expect(resposta).toContainText('Já temos')
  await expect(resposta).toContainText(/coletados em \d{2}\/\d{2}\/\d{4}/)

  const abrir = page.getByTestId('abrir-ficha')
  await expect(abrir).toBeVisible()
  await expect(abrir).toHaveAttribute('href', /\/app\/ficha\/.+/)
  await expect(resposta.getByTestId('dados-do-catalogo')).toBeVisible()

  // Toda informação leva etiqueta, e a desta fala é a do catálogo.
  await expect(resposta.getByTestId(/^badge-/)).toBeVisible()

  expect(pesquisasDisparadas).toEqual([])

  // E o botão leva à ficha de verdade.
  await abrir.click()
  await expect(page).toHaveURL(/\/app\/ficha\//)
  await expect(page.getByRole('heading', { level: 1, name: 'Ficha técnica' })).toBeVisible()
})

test('a caixa de texto fica presa embaixo e aceita Enter', async () => {
  const page = sessao.page()
  await page.goto('/app/consulta')
  await expect(page.getByRole('heading', { level: 1, name: 'Consulta' })).toBeVisible()
  await page.evaluate(() => sessionStorage.removeItem('specradar.pesquisa.conversa.v1'))
  await page.reload()

  const caixa = page.getByTestId('pesquisa-caixa')
  const janela = page.viewportSize()!
  const caixaBox = await caixa.boundingBox()
  expect(caixaBox).not.toBeNull()
  // Embaixo da tela, e dentro dela.
  expect(caixaBox!.y + caixaBox!.height).toBeLessThanOrEqual(janela.height)
  expect(caixaBox!.y).toBeGreaterThan(janela.height / 2)

  await caixa.fill('Ranger Raptor')
  await caixa.press('Enter')
  await expect(page.getByTestId('mensagem-texto').first()).toContainText('Ranger Raptor')
  // A caixa esvazia depois de enviar.
  await expect(caixa).toHaveValue('')
})
