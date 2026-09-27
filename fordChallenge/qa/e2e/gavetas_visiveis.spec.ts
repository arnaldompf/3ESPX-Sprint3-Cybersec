/**
 * **Visibilidade real**: o painel está na tela, e não só no DOM.
 *
 * Este arquivo nasceu de dois defeitos que um avaliador encontrou usando o sistema em
 * 12/09/2026 e que a suíte inteira, verde, não via:
 *
 * * na Ficha, a gaveta de evidência abria **fora da tela** (`top: -1344px` com a página
 *   rolada) — clicar em "ver evidência" parecia não fazer nada;
 * * no Radar, a gaveta do "Por quê?" abria com **62 px de altura** — a altura da linha da
 *   fila, não a da tela.
 *
 * **Por que a suíte não via.** `toBeVisible()` do Playwright responde "está no DOM, tem
 * caixa, não está escondido por CSS" — e responde **true** para um painel em `top:
 * -1344px`. `ficha.spec.ts` e `radar.spec.ts` usam `toBeVisible()` + `toContainText()`, e
 * as duas asserções continuavam verdadeiras com o painel fora da tela. O teste de tela em
 * jsdom (`FieldRow.test.tsx`) tampouco ajuda: jsdom não tem layout, não mede `top` nem
 * `height`, e passaria com os 62 px.
 *
 * **A causa.** `animation: … both` com apenas o keyframe `from` deixa
 * `transform: matrix(1, 0, 0, 1, 0, 0)` residual — identidade, mas diferente de `none`.
 * Qualquer `transform != none` vira containing block de todo `position: fixed`
 * descendente: a gaveta se ancorava em `.rota-entra` (a altura da página) na Ficha e em
 * `.linha-entra` (a altura da linha) no Radar, em vez da tela. O `createPortal` para
 * `document.body` (7d16b24) é a correção; estes testes são o que impede o retorno.
 *
 * **A regra que estes testes escrevem, e que vale para toda superfície flutuante nova:**
 * dentro da viewport, altura útil de pelo menos 300 px, o trecho literal legível, e
 * nenhum ancestral que sequestre o `position: fixed`.
 */
import { expect, test } from '@playwright/test'

import {
  abrir,
  exigirNoTopo,
  exigirSemAncestralQueAncora,
  exigirVisivelDeVerdade,
  irPara,
} from './_ajuda'
import { fichasDoBanco, porNome } from './_fichas'
import { sessaoCompartilhada } from './_sessao'

const sessao = sessaoCompartilhada('admin')

test('Ficha: a gaveta de evidência abre DENTRO da tela, com a página rolada', async () => {
  const page = sessao.page()
  const raptor = porNome(await fichasDoBanco(page), /Raptor/)
  await abrir(page, raptor.url, 'Campos com valor')

  // **Rolar antes de clicar é o teste.** Sem rolar, o painel sequestrado ficaria em
  // `top: 56` e as asserções passariam verdes com o defeito presente — é exatamente esse
  // buraco que deixou o defeito chegar a quem usou o sistema. E tem de ser antes: a
  // Gaveta trava `body.overflow` ao abrir, então rolar depois não funciona.
  const ultimo = page.getByRole('button', { name: /ver evidência/i }).last()
  await ultimo.scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => window.scrollY), 'a página precisa estar rolada').toBeGreaterThan(
    400,
  )
  await ultimo.click()

  const gaveta = page.getByTestId('gaveta-evidencia')
  const altura = page.viewportSize()!.height
  const caixa = await exigirVisivelDeVerdade(page, gaveta, 'gaveta de evidência')
  // `inset-y-0` obriga a altura a ser a da tela. Nada menos é aceitável.
  expect(caixa.height, 'inset-y-0 tem de dar a tela inteira').toBeGreaterThanOrEqual(altura - 1)
  await exigirSemAncestralQueAncora(gaveta, 'gaveta de evidência')
  await exigirNoTopo(gaveta, 'gaveta de evidência')

  // O trecho literal é o produto: tem de estar legível, dentro da tela.
  const trecho = gaveta.getByTestId('trecho-literal').first()
  await exigirVisivelDeVerdade(page, trecho, 'trecho literal', { alturaMinima: 16 })
  expect((await trecho.innerText()).trim().length, 'trecho literal vazio').toBeGreaterThan(10)

  await page.keyboard.press('Escape')
  await expect(gaveta).toHaveCount(0)
})

test('Radar: "Por quê?" não herda a altura da linha da fila', async () => {
  const page = sessao.page()
  await irPara(page, 'radar')
  const linha = page.locator('[data-testid^="alerta-"]').first()
  await expect(linha).toBeVisible()
  const caixaDaLinha = await linha.boundingBox()

  // Clicar sem esperar a fila assentar: `.linha-entra` tem atraso de até 300 ms e fill
  // `backwards`, então o transform está aplicado desde o primeiro quadro e durante todo o
  // atraso. Pegar essa janela é justamente o ponto — é nela que o defeito nascia.
  await linha.getByRole('button', { name: 'Por quê?' }).click()

  const gaveta = page.getByTestId('gaveta-porque')
  const altura = page.viewportSize()!.height
  const caixa = await exigirVisivelDeVerdade(page, gaveta, 'gaveta "Por quê?"')
  expect(caixa.height, 'a gaveta herdou a altura da linha da fila').not.toBe(caixaDaLinha!.height)
  expect(caixa.height, 'inset-y-0 tem de dar a tela inteira').toBeGreaterThanOrEqual(altura - 1)
  await exigirSemAncestralQueAncora(gaveta, 'gaveta "Por quê?"')
  await exigirNoTopo(gaveta, 'gaveta "Por quê?"')

  // Com a cadeia carregada, o primeiro elo continua dentro da tela.
  await expect(gaveta.getByTestId('elo-1')).toBeVisible()
  await exigirVisivelDeVerdade(page, gaveta.getByTestId('elo-1'), 'elo 1', { alturaMinima: 20 })

  await page.keyboard.press('Escape')
  await expect(gaveta).toHaveCount(0)
})

test('as outras superfícies flutuantes cabem na tela', async () => {
  const page = sessao.page()
  await irPara(page, 'consulta')

  await exigirVisivelDeVerdade(page, page.getByTestId('barra-lateral'), 'barra lateral', {
    alturaMinima: 400,
  })
  await exigirVisivelDeVerdade(page, page.getByTestId('barra-superior'), 'barra superior', {
    alturaMinima: 40,
  })

  await page.getByTestId('trocar-papel').click()
  const menu = page.getByTestId('lista-de-papeis')
  await exigirVisivelDeVerdade(page, menu, 'menu de papéis', { alturaMinima: 120 })
  await exigirNoTopo(menu, 'menu de papéis')
  await page.keyboard.press('Escape')
  await expect(menu).toHaveCount(0)
})

/**
 * A sentinela da causa raiz, no lugar onde ela mora.
 *
 * Os testes acima provam o sintoma (o painel na tela). Este prova que o **gatilho está
 * desarmado**: nenhuma classe de animação do aplicativo deixa `transform` residual no
 * estilo computado depois de terminar. Enquanto ele passar, um `position: fixed` novo
 * dentro de uma linha de lista ou de uma rota animada continua se ancorando na tela.
 */
test('nenhuma animação deixa transform residual no estilo computado', async () => {
  const page = sessao.page()
  await irPara(page, 'radar')

  const residuais = await page.evaluate(async () => {
    const classes = ['rota-entra', 'linha-entra', 'gaveta-entra']
    const achados: string[] = []
    for (const classe of classes) {
      const alvo = document.querySelector<HTMLElement>(`.${classe}`)
      if (!alvo) continue
      await Promise.all(alvo.getAnimations().map((a) => a.finished))
      const { transform } = getComputedStyle(alvo)
      if (transform !== 'none') achados.push(`.${classe} → transform: ${transform}`)
    }
    return achados
  })

  expect(
    residuais,
    'transform != none (mesmo identidade) vira containing block de todo position:fixed descendente',
  ).toEqual([])
})

/**
 * 390 px tem fixture própria: `sessaoCompartilhada` abre `browser.newPage()` sem viewport
 * e herdaria os 1440×900 do projeto `desktop`.
 */
test.describe('390 px', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('a gaveta e a barra inferior cabem no celular', async ({ page }) => {
    await abrir(page, '/app/radar', /alerta|materialidade/i)

    await page.getByRole('button', { name: 'Por quê?' }).first().click()
    const gaveta = page.getByTestId('gaveta-porque')
    const caixa = await exigirVisivelDeVerdade(page, gaveta, 'gaveta "Por quê?" em 390 px')
    // Em ≤ 768 px a gaveta é `w-full`: 440 px numa tela de 390 px seria um modal disfarçado.
    expect(caixa.width, 'em ≤ 768 px a gaveta ocupa a tela inteira').toBe(390)
    await exigirSemAncestralQueAncora(gaveta, 'gaveta "Por quê?" em 390 px')

    await page.keyboard.press('Escape')
    await expect(gaveta).toHaveCount(0)

    await exigirVisivelDeVerdade(page, page.getByTestId('barra-inferior'), 'barra inferior', {
      alturaMinima: 50,
    })
  })
})
