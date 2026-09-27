/**
 * **Um rótulo esmagado a zero não é um rótulo.**
 *
 * Um avaliador usou o sistema em 12/09/2026 e relatou que "divergência com material
 * interno", no Radar, e "ADAS itens", na Ficha, quebravam "letra a letra".
 *
 * A medição mostrou algo pior, e mais fácil de provar: **não há quebra de palavra
 * nenhuma**. O computed style é `word-break: normal` em todos eles. O que existe é uma
 * caixa de **largura 0 px** — o texto empilha uma palavra por linha e transborda, o que a
 * olho nu lê como letra a letra.
 *
 * **A mecânica.** O rótulo mora num `flex-1` com `min-w-0`: `flex-basis: 0` sem piso de
 * largura. Os irmãos dele na mesma linha são todos `shrink-0`. Quando a soma dos rígidos
 * passa da largura disponível — no Radar dá 1099 px numa linha de 1094 —, o único elemento
 * elástico é espremido até **zero**, e o texto sai por cima. Na Ficha o irmão rígido é o
 * valor de `adas_itens`, com 11 itens juntados por " · ": 2763 px inquebráveis.
 *
 * **O defeito é de 768 px para cima** — exatamente no notebook da apresentação. Em 390 px
 * a linha já empilhava por `flex-wrap` e estava correta.
 *
 * Por isso estes testes medem **geometria**, e não classes: `toBeVisible()` é verdadeiro
 * para uma caixa de 0 px de largura, e o teste de classes em jsdom não tem layout.
 */
import { expect, test } from '@playwright/test'

import { abrir, irPara } from './_ajuda'
import { fichasDoBanco, porNome } from './_fichas'
import { sessaoCompartilhada } from './_sessao'

const sessao = sessaoCompartilhada('admin')

/** `text-meta` é 12px/16px; `text-corpo`, 14px/22px (web/tailwind.config.js). */
const LINHA_META = 16
const LINHA_CORPO = 22

const LARGURAS = [1440, 1280, 1024, 768, 390]

test('Radar: o rótulo do tipo do alerta cabe numa linha, em toda largura', async () => {
  const page = sessao.page()
  await irPara(page, 'radar')

  const rotulo = page.getByTestId('tipo-do-alerta').first()
  await expect(rotulo).toBeVisible()

  for (const largura of LARGURAS) {
    await page.setViewportSize({ width: largura, height: 900 })
    await page.waitForTimeout(120)
    const caixa = await rotulo.boundingBox()
    expect(caixa, `${largura} px: o rótulo sumiu`).not.toBeNull()

    // O sintoma exato: largura esmagada a zero. Medido em 1440, 1280, 1024, 900 e 768.
    expect(caixa!.width, `${largura} px: rótulo esmagado (${caixa!.width} px de largura)`,
    ).toBeGreaterThan(40)
    // E a consequência: o texto empilhava em 4 linhas de 16 px.
    expect(
      caixa!.height,
      `${largura} px: rótulo em ${Math.round(caixa!.height / LINHA_META)} linhas`,
    ).toBeLessThanOrEqual(LINHA_META * 2)
  }

  await page.setViewportSize({ width: 1440, height: 900 })
})

test('Ficha: o rótulo do campo tem piso de largura, e o valor não escapa do cartão', async () => {
  const page = sessao.page()
  const raptor = porNome(await fichasDoBanco(page), /Raptor/)
  await abrir(page, raptor.url, 'Campos com valor')

  // `adas_itens` é o caso extremo do banco: 11 itens juntados por " · ", inquebráveis
  // enquanto o valor foi `shrink-0`. É o campo mais importante do bloco "Segurança e ADAS".
  const rotulo = page.getByTestId('rotulo-adas_itens')
  const valor = page.getByTestId('valor-adas_itens')
  await expect(rotulo).toBeVisible()

  for (const largura of LARGURAS) {
    await page.setViewportSize({ width: largura, height: 900 })
    await page.waitForTimeout(120)

    const caixaDoRotulo = await rotulo.boundingBox()
    expect(caixaDoRotulo!.width, `${largura} px: rótulo esmagado`).toBeGreaterThan(60)
    expect(
      caixaDoRotulo!.height,
      `${largura} px: rótulo em ${Math.round(caixaDoRotulo!.height / LINHA_CORPO)} linhas`,
    ).toBeLessThanOrEqual(LINHA_CORPO * 2)

    // O valor fica DENTRO do cartão. Antes, em 1440, ele passava 1664 px da borda direita
    // e era recortado pelo `overflow-hidden` da seção: o dado sumia sem aviso.
    const caixaDoValor = await valor.boundingBox()
    const borda = await page.evaluate(() => {
      const secao = document.querySelector('main section')
      return secao ? secao.getBoundingClientRect().right : 0
    })
    expect(
      caixaDoValor!.x + caixaDoValor!.width,
      `${largura} px: o valor passa ${Math.round(caixaDoValor!.x + caixaDoValor!.width - borda)} px da borda do cartão`,
    ).toBeLessThanOrEqual(borda + 1)
  }

  await page.setViewportSize({ width: 1440, height: 900 })
})

test('as duas telas corrigidas não deixam conteúdo fora da tela, em nenhuma largura', async () => {
  // A rede de segurança das duas correções acima: dar piso de largura a um elemento pode
  // empurrar a página para fora.
  //
  // A medida ignora o que está dentro de um contêiner com rolagem própria — é a mesma
  // regra de `transversal.spec.ts` (D-216), e existe porque a matriz de 17 colunas rola
  // dentro da moldura dela **por desenho** (`010_DESIGN.md` §8). Medir sem essa ressalva
  // reprovaria o desenho em vez de um defeito.
  const page = sessao.page()
  const raptor = porNome(await fichasDoBanco(page), /Raptor/)

  for (const rota of ['/app/radar', raptor.url]) {
    await page.goto(rota)
    await expect(page.locator('main')).toBeVisible()
    for (const largura of LARGURAS) {
      await page.setViewportSize({ width: largura, height: 900 })
      await page.waitForTimeout(200)
      const cortados = await page.evaluate(() =>
        [...document.querySelectorAll('*')]
          .filter((e) => {
            const r = e.getBoundingClientRect()
            if (!r.width) return false
            for (let p = e.parentElement; p; p = p.parentElement) {
              if (getComputedStyle(p).overflowX !== 'visible') return false
            }
            return r.right > window.innerWidth + 1
          })
          .slice(0, 3)
          .map((e) => `${e.tagName}.${String(e.className).slice(0, 60)}`),
      )
      expect(cortados, `${rota} em ${largura} px deixou conteúdo fora da tela`).toEqual([])
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 })
})
