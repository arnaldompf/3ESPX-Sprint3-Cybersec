/**
 * QA-BUG-12 — o documento do cliente ficava "Gerando… (pendente)" para sempre.
 *
 * O documento sai por job: a API responde 202 e a tela acompanha, perguntando o estado a
 * cada 1,5 s. Com o **worker desligado** o job nunca sai de `pendente`, e a tela ficava
 * pedindo o estado indefinidamente, mostrando "Gerando… (pendente)" e nada mais. Medido
 * em 11/09/2026 com o worker parado: 25 s depois, a mesma frase, nenhum aviso, nenhuma
 * saída. O vendedor está na frente do cliente.
 *
 * O roteiro de 15/09 chama isto de "o primeiro defeito que o ensaio pegou" e a tabela de
 * emergência manda olhar o worker. A tela é que não dizia.
 *
 * A regra que este arquivo fixa: passado um tempo razoável sem sair de `pendente`, a tela
 * **para de perguntar** e diz o que está acontecendo, com o que fazer.
 */
import { expect, test } from '@playwright/test'

import { irPara } from './_ajuda'
import { sessaoCompartilhada } from './_sessao'

const ESPERA_DA_TELA = 35_000

const sessao = sessaoCompartilhada('vendedor')

// A página é a mesma para os dois testes: sem isto, o job congelado do primeiro
// continuaria interceptado no segundo.
test.afterEach(async () => {
  await sessao.page().unrouteAll({ behavior: 'ignoreErrors' })
})

async function compararEPedirDocumento(page) {
  await irPara(page, 'showroom')
  await page.getByLabel(/^versão Ford$/).selectOption({ label: 'Ranger Limited 3.0 V6 Diesel 4WD AT' })
  await page.getByLabel(/^concorrente$/).selectOption({ label: 'Toyota Hilux SRX Plus AT' })
  await page.getByRole('button', { name: 'trabalho rural / carga' }).click()
  await page.getByRole('button', { name: 'comparar por este perfil' }).click()
  await expect(page.getByRole('heading', { name: 'Aderência ao perfil' })).toBeVisible()
  await page.getByRole('button', { name: /gerar documento/i }).click()
}

test('worker parado: a tela desiste e explica, em vez de girar para sempre', async () => {
  const page = sessao.page()
  // Um worker morto, do ponto de vista da tela, é um job que nunca sai de `pendente`.
  await page.route('**/api/v1/jobs/*', (rota) =>
    rota.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 'parado', status: 'pendente', stage: 'pendente' }),
    }),
  )

  await compararEPedirDocumento(page)

  const estado = page.getByTestId('estado-do-job')
  await expect(estado).toHaveText(/Gerando…/)
  // Passados ~30 s a tela desiste de perguntar e explica, em vez de girar para sempre.
  // A frase é deliberadamente de quem vende, não de quem opera: até 12/09/2026 ela
  // mandava "religar o processador de fila", que não é problema do vendedor nem
  // vocabulário dele.
  await expect(estado).toHaveText(/tente novamente em instantes/, {
    timeout: ESPERA_DA_TELA,
  })
  await expect(estado).not.toHaveText(/Gerando…/)
})

test('worker de pé: o documento fica pronto e abre em .pdf', async () => {
  const page = sessao.page()
  await compararEPedirDocumento(page)

  const link = page.getByRole('link', { name: /abrir o documento/i })
  await expect(link).toBeVisible({ timeout: ESPERA_DA_TELA })
  await expect(link).toHaveAttribute('href', /\.pdf$/)
})

/** O teto de 15 s do parecer de uso, medido de verdade. */
const TETO_DO_DOCUMENTO_MS = 15_000

test(`em replay, o documento sai em menos de ${TETO_DO_DOCUMENTO_MS / 1000} s`, async () => {
  // O número não é chute: a geração em si é sub-segundo (medida em `tests/api/test_pdf.py`,
  // 0,92 s com o job inteiro). O que consome relógio é a espera da fila vazia (2 s) somada
  // ao poll de 1,5 s da tela — pior caso realista perto de 5 s. 15 s é folgado, e é o teto
  // acima do qual quem está com o cliente ao lado desiste.
  const page = sessao.page()
  await irPara(page, 'showroom')
  await page
    .getByLabel(/^versão Ford$/)
    .selectOption({ label: 'Ranger Limited 3.0 V6 Diesel 4WD AT' })
  await page.getByLabel(/^concorrente$/).selectOption({ label: 'Toyota Hilux SRX Plus AT' })
  await page.getByRole('button', { name: 'trabalho rural / carga' }).click()
  await page.getByRole('button', { name: 'comparar por este perfil' }).click()
  await expect(page.getByRole('heading', { name: 'Aderência ao perfil' })).toBeVisible()

  const comecou = Date.now()
  await page.getByRole('button', { name: /gerar documento/i }).click()
  await expect(page.getByRole('link', { name: /abrir o documento/i })).toBeVisible({
    timeout: TETO_DO_DOCUMENTO_MS,
  })
  const levou = Date.now() - comecou
  expect(levou, `o documento levou ${levou} ms`).toBeLessThan(TETO_DO_DOCUMENTO_MS)
})

test('/health diz se o worker está vivo — é onde quem cuida da máquina pergunta', async () => {
  // Até 12/09/2026 não havia onde perguntar: o worker morria e nem a tela, nem o health,
  // nem quem administra sabia. A tela mandava "religar o processador de fila".
  const page = sessao.page()
  const saude = await page.evaluate(async () => {
    const r = await fetch('/api/v1/health')
    return r.json()
  })
  expect(saude.worker, 'o health não publica o worker').toBeTruthy()
  expect(saude.worker.ok, `worker fora do ar: ${saude.worker.motivo}`).toBe(true)
  expect(saude.worker.ha_quantos_segundos).toBeLessThan(10)
  // A API não degrada por causa do worker: são coisas diferentes.
  expect(saude.status).toBe('ok')
})
