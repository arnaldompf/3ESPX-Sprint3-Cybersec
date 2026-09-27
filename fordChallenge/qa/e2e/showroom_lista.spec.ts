/**
 * QA-BUG-14 — o Showroom abria com os dois seletores vazios e **nenhum aviso**.
 *
 * `const lista = veiculos.data ?? []` engole a falha: se `GET /vehicles` não responder —
 * 429 por excesso de requisição, 500, rede caída —, os `<select>` de Ford e de
 * concorrente saem sem uma opção, o botão "comparar por este perfil" não leva a lugar
 * nenhum e a tela não diz uma palavra. Flagrado em 11/09/2026 no meio do ensaio: dois
 * seletores com zero opções e a tela inteira parecendo normal.
 *
 * É a tela que o vendedor abre na frente do cliente, e a mesma família do QA-BUG-06 na
 * Consulta: falha de rede disfarçada de "não tem nada aqui".
 */
import { expect, test } from '@playwright/test'

import { abrir, irPara } from './_ajuda'
import { sessaoCompartilhada } from './_sessao'

// Analista, e não vendedor: o Showroom é do vendedor, mas este arquivo mede o estado de
// **erro** da tela, que não depende do papel. O arquivo `showroom.spec.ts` é que entra
// como vendedor e mede o fluxo dele.
const sessao = sessaoCompartilhada('analista')

// A página é a mesma para os testes do arquivo: uma rota interceptada num teste
// continuaria valendo no seguinte.
test.afterEach(async () => {
  await sessao.page().unrouteAll({ behavior: 'ignoreErrors' })
})

test('falha ao carregar os veículos aparece na tela, em vez de seletores vazios', async () => {
  const page = sessao.page()
  await page.route('**/api/v1/vehicles*', (rota) =>
    rota.fulfill({
      status: 500,
      contentType: 'application/problem+json',
      body: JSON.stringify({
        type: '/problemas/interno',
        title: 'Erro interno',
        status: 500,
        detail: 'Falha ao listar os veículos.',
      }),
    }),
  )

  await irPara(page, 'showroom')

  await expect(page.locator('main')).toContainText('Não foi possível')
  await expect(page.locator('main')).not.toContainText('Traceback')
})

test('com os veículos no ar, os dois seletores têm opção', async () => {
  const page = sessao.page()
  // Carga nova: o erro do teste anterior fica guardado no cache da tela, e desfazer a
  // interceptação não o apaga. É o mesmo que a pessoa faz — recarrega.
  await abrir(page, '/app/showroom', 'Perfil anônimo')

  await expect(page.getByLabel(/^versão Ford$/).locator('option').first()).toBeAttached()
  await expect(page.getByLabel(/^concorrente$/).locator('option').first()).toBeAttached()
  await expect(page.locator('main')).not.toContainText('Não foi possível')
})
