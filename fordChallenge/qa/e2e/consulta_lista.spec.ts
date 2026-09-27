/**
 * QA-BUG-06 — a lista "Versões com ficha no banco" sumia em **qualquer** erro.
 *
 * A lista mostra saúde do conhecimento, que é dado interno: ela é do analista, do gestor e
 * do admin, e para o vendedor não aparece — isso é regra de produto e está certo. O que
 * estava errado é o `!fichas.error` cru: ele tratava permissão, 429, 500 e queda de rede do
 * mesmo jeito, escondendo a seção **sem uma palavra**. Medido em 11/09/2026: com a cota de
 * 60 requisições por minuto estourada, o admin abria a Consulta e simplesmente não havia
 * lista — nem erro, nem aviso, nem esqueleto. Quem está no palco conclui que o banco está
 * vazio.
 *
 * A regra que este arquivo fixa: **a regra de papel esconde em silêncio** (não é falha),
 * **qualquer erro fala**. Desde D-204 quem aplica a regra é a tela, e não um 403 do
 * servidor — o que muda é de onde vem a decisão, não o que a pessoa vê.
 */
import { expect, test } from '@playwright/test'

import { abrir, entrar } from './_ajuda'

test('vendedor não vê a lista, e isso não é erro: nenhuma mensagem de falha', async ({ page }) => {
  await entrar(page, 'vendedor')
  await abrir(page, '/app/consulta', 'Consulta')

  await expect(page.locator('main')).not.toContainText('Versões com ficha no banco')
  await expect(page.locator('main')).not.toContainText('Não foi possível')
})

test('erro que não é permissão aparece na tela, em vez de a lista sumir calada', async ({
  page,
}) => {
  await entrar(page, 'gestor')

  // A tela não tem como provocar um 500; o teste provoca, que é o ponto do ensaio.
  await page.route('**/api/v1/insights/knowledge-health/versions*', (rota) =>
    rota.fulfill({
      status: 500,
      contentType: 'application/problem+json',
      body: JSON.stringify({
        type: '/problemas/interno',
        title: 'Erro interno',
        status: 500,
        detail: 'Falha ao ler a saúde do conhecimento.',
      }),
    }),
  )

  await abrir(page, '/app/consulta', 'Consulta')

  const main = page.locator('main')
  await expect(main).toContainText('Versões com ficha no banco')
  await expect(main).toContainText('Não foi possível')
  await expect(main).not.toContainText('Traceback')
})

test('429 também fala: a lista não desaparece por excesso de requisição', async ({ page }) => {
  /* O limite saiu do caminho de execução (D-206) e este servidor não devolve 429. O
   * teste continua valendo e é provocado: a tela roda em máquina de gente, atrás de
   * proxy e de balanceador, e um 429 de qualquer camada não pode fazer a seção sumir
   * calada. O que ele trava é o tratamento, não a existência do limite. */
  await entrar(page, 'gestor')

  await page.route('**/api/v1/insights/knowledge-health/versions*', (rota) =>
    rota.fulfill({
      status: 429,
      contentType: 'application/problem+json',
      body: JSON.stringify({
        type: '/problemas/rate-limit',
        title: 'Limite de requisições excedido',
        status: 429,
        detail: 'Muitas requisições. Aguarde antes de tentar novamente.',
      }),
    }),
  )

  await abrir(page, '/app/consulta', 'Consulta')

  await expect(page.locator('main')).toContainText('Versões com ficha no banco')
  await expect(page.locator('main')).toContainText('Muitas requisições')
})
