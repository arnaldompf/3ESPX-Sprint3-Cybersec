/** Ajudantes compartilhados pelos testes de regressão do QA. */
import { expect, type Locator, type Page } from '@playwright/test'

export type Papel = 'vendedor' | 'analista' | 'gestor' | 'admin'

/** A porta de entrada: `/app` cai direto na Consulta. Não há tela de login (D-204). */
export const ENTRADA = '/app'

/**
 * Abre o aplicativo no papel pedido, **trocando pelo seletor da barra lateral**.
 *
 * O nome continua `entrar` porque é o que o teste está dizendo — "esta pessoa está
 * olhando" —, mas não há mais nada a autenticar: a ferramenta abre na Consulta e o papel
 * é um ponto de vista guardado no navegador.
 *
 * A espera pela janela de 60 requisições por minuto saiu junto com o limite (D-206). Ela
 * existia porque a suíte inteira estourava a cota do produto e as telas passavam a
 * responder "Muitas requisições" — defeito do ensaio, não do produto. Sem limite na pilha,
 * a suíte deixou de precisar de paciência artificial.
 */
export async function entrar(page: Page, papel: Papel): Promise<void> {
  await page.goto(ENTRADA)
  await expect(page).toHaveURL(/\/app\/consulta$/)
  await trocarPara(page, papel)
}

/**
 * Troca de papel **pela tela**, como na apresentação: o menu no rodapé da barra lateral.
 *
 * Sem sair de onde se está, que é a diferença de antes: trocar de papel era sair e entrar
 * de novo, passando pela tela de login. Agora a tela aberta continua aberta e passa a
 * responder de outro jeito — é essa a cena do roteiro.
 */
export async function trocarPara(page: Page, papel: Papel): Promise<void> {
  const atual = page.getByTestId('papel-atual')
  // `innerText` e não `toBeVisible`: em <= 768 px a barra lateral não existe, e o papel
  // atual mora num nó que o CSS esconde. O texto continua no DOM, e é dele que se lê
  // quem está olhando; a troca é que muda de controle.
  if ((await atual.innerText()).trim().toLowerCase() === papel) return

  if (await page.getByTestId('trocar-papel').isVisible().catch(() => false)) {
    await page.getByTestId('trocar-papel').click()
    await page.getByTestId(`papel-${papel}`).click()
  } else {
    // Celular: a navegação é a barra inferior, e os papéis ficam dentro de "mais".
    await page.getByRole('button', { name: 'mais' }).click()
    await page.getByTestId(`papel-celular-${papel}`).click()
  }
  await expect(atual).toHaveText(papel)
}

/** Abre uma rota e espera a âncora aparecer. */
export async function abrir(page: Page, rota: string, ancora: string | RegExp): Promise<void> {
  await page.goto(rota)
  await expect(page.locator('main')).toContainText(ancora)
}

/* -------------------------------------------------------------- visibilidade real
 *
 * `toBeVisible()` do Playwright responde "o elemento está no DOM, tem caixa e não está
 * escondido por CSS". Ele responde **true** para um painel em `top: -1344px` — medido em
 * Chromium em 12/09/2026. Era esse o buraco: `ficha.spec.ts` e `radar.spec.ts` passavam
 * verdes enquanto a gaveta de evidência abria fora da tela e a do "Por quê?" abria com
 * 62 px de altura, e quem usou o sistema viu os dois defeitos que a suíte não via.
 *
 * A pergunta que estes três ajudantes respondem é outra: **a pessoa consegue ler isto?**
 * Ela se decompõe em três, e cada uma precisa de uma medida diferente:
 *
 * 1. `exigirVisivelDeVerdade` — está dentro da viewport e tem altura útil (geometria);
 * 2. `exigirSemAncestralQueAncora` — nenhum ancestral sequestrou o `position: fixed`
 *    (a causa raiz: um `transform`, mesmo identidade, vira containing block);
 * 3. `exigirNoTopo` — nada pinta por cima no ponto em que o olho cai (pilha de z-index).
 */

/** Altura mínima para uma superfície flutuante ser útil, e não um filete. */
const ALTURA_UTIL_MINIMA = 300

export interface Caixa {
  x: number
  y: number
  width: number
  height: number
}

/**
 * O elemento está **dentro da tela**, com altura de gente.
 *
 * Mede depois de as animações do próprio elemento terminarem: `.gaveta-entra` desliza
 * 24 px da direita em 200 ms, e medir no meio do deslize faria `x + width` passar da
 * largura da viewport — vermelho falso. `getAnimations().finished` resolve na hora
 * quando `prefers-reduced-motion` zera as durações, então não há espera artificial.
 */
export async function exigirVisivelDeVerdade(
  page: Page,
  alvo: Locator,
  nome: string,
  {
    alturaMinima = ALTURA_UTIL_MINIMA,
    /**
     * O elemento pode passar do fim da tela?
     *
     * `false` (o padrão) é a regra das **superfícies flutuantes**: uma gaveta que não cabe
     * na viewport tem conteúdo que ninguém alcança, porque a página atrás dela não rola.
     *
     * `true` é a regra do **conteúdo da página**: um cartão de 1273 px numa tela de 900 é
     * normal — a pessoa rola. Aqui o que importa é o topo estar visível e a altura ser
     * útil; exigir que o fundo caiba reprovaria metade das telas do produto.
     */
    podeRolar = false,
  }: { alturaMinima?: number; podeRolar?: boolean } = {},
): Promise<Caixa> {
  await expect(alvo, `${nome}: não está no DOM`).toBeVisible()
  await alvo.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)))

  const caixa = await alvo.boundingBox()
  expect(caixa, `${nome}: sem caixa de layout`).not.toBeNull()
  const janela = page.viewportSize()
  expect(janela, 'viewport não definida').not.toBeNull()
  const { x, y, width, height } = caixa!
  const { width: largura, height: altura } = janela!

  expect(y, `${nome}: topo acima da tela (${y} px)`).toBeGreaterThanOrEqual(0)
  expect(x, `${nome}: borda esquerda fora da tela (${x} px)`).toBeGreaterThanOrEqual(0)
  if (!podeRolar) {
    expect(
      y + height,
      `${nome}: fundo abaixo da tela (${y + height} > ${altura})`,
    ).toBeLessThanOrEqual(altura + 1)
  }
  expect(x + width, `${nome}: borda direita fora da tela (${x + width} > ${largura})`).toBeLessThanOrEqual(
    largura + 1,
  )
  expect(height, `${nome}: altura colapsada (${height} px)`).toBeGreaterThanOrEqual(
    Math.min(alturaMinima, altura),
  )
  expect(width, `${nome}: largura colapsada (${width} px)`).toBeGreaterThan(0)
  return caixa!
}

/**
 * **A sentinela da causa raiz.** Nenhum ancestral pode virar containing block de `fixed`.
 *
 * `animation: … both` com apenas o keyframe `from` deixa `matrix(1, 0, 0, 1, 0, 0)`
 * residual — identidade, mas diferente de `none`, e isso basta para o navegador ancorar
 * todo `position: fixed` descendente no ancestral em vez de na tela. Antes do portal de
 * 7d16b24 esta função devolvia `DIV.rota-entra` na Ficha e `LI.linha-entra` no Radar.
 *
 * Ela existe para que o vermelho de daqui a seis meses **nomeie o mecanismo**, em vez de
 * dizer só "o topo está em -1344".
 */
export async function exigirSemAncestralQueAncora(alvo: Locator, nome: string): Promise<void> {
  const culpado = await alvo.evaluate((el) => {
    for (let pai = el.parentElement; pai; pai = pai.parentElement) {
      const estilo = getComputedStyle(pai)
      const marca =
        (estilo.transform !== 'none' && 'transform') ||
        (estilo.filter !== 'none' && 'filter') ||
        (estilo.backdropFilter !== 'none' && 'backdrop-filter') ||
        (estilo.perspective !== 'none' && 'perspective') ||
        (/paint|layout|strict|content/.test(estilo.contain) && 'contain') ||
        (estilo.willChange.includes('transform') && 'will-change')
      if (marca) {
        const classe = typeof pai.className === 'string' ? pai.className : '(sem classe)'
        return `${pai.tagName}.${classe || '(sem classe)'} → ${marca}: ${estilo.getPropertyValue(marca)}`
      }
    }
    return null
  })
  expect(culpado, `${nome}: um ancestral virou containing block do position:fixed`).toBeNull()
}

/** O painel pinta por cima de verdade no ponto em que a pessoa olha. */
export async function exigirNoTopo(alvo: Locator, nome: string): Promise<void> {
  const noTopo = await alvo.evaluate((el) => {
    const r = el.getBoundingClientRect()
    const noPonto = document.elementFromPoint(r.x + r.width / 2, r.y + Math.min(40, r.height / 2))
    return !!noPonto && el.contains(noPonto)
  })
  expect(noTopo, `${nome}: outro elemento pinta por cima`).toBe(true)
}

/** As telas da barra lateral: o rótulo do link e o título que a tela mostra. */
export const TELAS = {
  consulta: { nome: /^Consulta/, titulo: 'Consulta' },
  radar: { nome: /^Radar/, titulo: 'Radar competitivo' },
  matriz: { nome: /^Matriz/, titulo: 'Matriz de paridade' },
  saude: { nome: /^Saúde/, titulo: 'Saúde do conhecimento' },
  showroom: { nome: /^Showroom/, titulo: 'Showroom' },
  insights: { nome: /^Insights/, titulo: 'Insights de win/loss' },
  simulador: { nome: /^Simulador/, titulo: 'Simulador de cenário' },
  benchmark: { nome: /^Benchmark/, titulo: 'Benchmark competitivo' },
} as const

/**
 * Vai para uma tela **clicando na barra lateral**, que é o que uma pessoa faz.
 *
 * Use `abrir()` quando o teste for justamente sobre recarregar (F5) ou entrar por link
 * profundo: `page.goto` recarrega o aplicativo inteiro, e a diferença entre navegar e
 * recarregar é exatamente o que alguns destes testes medem.
 */
export async function irPara(page: Page, tela: keyof typeof TELAS): Promise<void> {
  const { nome, titulo } = TELAS[tela]
  const link = page.getByRole('navigation').getByRole('link', { name: nome }).first()
  if (!(await link.isVisible().catch(() => false))) {
    await page.goto(`/app/${tela}`)
    await expect(page.getByRole('heading', { level: 1, name: titulo })).toBeVisible()
    return
  }

  // Já estando na tela, clicar no próprio link não faz nada e o teste herdaria o estado
  // do teste anterior (um filtro aplicado, uma gaveta aberta). Passar pela Consulta
  // desmonta e remonta a tela — e é barato, porque o React Query já tem o dado dela.
  if (new URL(page.url()).pathname === `/app/${tela}`) {
    await page
      .getByRole('navigation')
      .getByRole('link', { name: TELAS.consulta.nome })
      .first()
      .click()
    await expect(page.getByRole('heading', { level: 1, name: TELAS.consulta.titulo })).toBeVisible()
  }

  await link.click()
  await expect(page.getByRole('heading', { level: 1, name: titulo })).toBeVisible()
}

/** Coleta erros de console e falhas de página durante o teste. */
export function vigiarConsole(page: Page): { erros: string[] } {
  const erros: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error') erros.push(m.text())
  })
  page.on('pageerror', (e) => erros.push(String(e)))
  return { erros }
}

/** Faz uma consulta pela única entrada do produto, como uma pessoa faria. */
export async function consultarVeiculo(
  page: Page,
  marca: string,
  modelo: string,
  versao: string,
): Promise<void> {
  // A conversa sobrevive a F5 por projeto. Cada caso de QA, porém, precisa começar sem
  // mensagens de outro teste para não clicar numa ficha antiga nem herdar uma pesquisa ativa.
  await page.evaluate(() => sessionStorage.removeItem('specradar.pesquisa.conversa.v1'))
  await page.reload()
  await expect(page.getByRole('heading', { level: 1, name: 'Consulta' })).toBeVisible()
  const caixa = page.getByTestId('pesquisa-caixa')
  await caixa.fill(`${marca} ${modelo} ${versao}`.trim())
  await page.getByTestId('pesquisa-enviar').click()
}
