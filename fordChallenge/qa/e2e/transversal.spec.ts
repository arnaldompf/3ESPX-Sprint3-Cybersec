/**
 * O que vale para **todas** as telas: recarregar, voltar, trocar de papel, 390 px,
 * teclado, console limpo, nenhum texto técnico e carga abaixo de 2 s.
 */
import { expect, type Page, test } from '@playwright/test'

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { consultarVeiculo, entrar, irPara, trocarPara, vigiarConsole } from './_ajuda'

/**
 * A lista de vocabulário interno vive em `web/src/lib/termos-internos.json`, e é lida com
 * `readFileSync` porque `qa/` é um pacote npm separado, sem o alias `@/` do web. Duplicar
 * a lista aqui seria garantir que as duas divirjam.
 */
const VOCABULARIO = JSON.parse(
  readFileSync(resolve(__dirname, '../../web/src/lib/termos-internos.json'), 'utf-8'),
) as {
  proibidos: { termo: string; regex: string; sensivel_a_maiuscula?: boolean; porque: string }[]
  seletores_isentos: { seletor: string; porque: string }[]
  rotas_isentas: { rota: string; porque: string }[]
}

const ROTAS_ISENTAS = new Set(VOCABULARIO.rotas_isentas.map((r) => r.rota))

/**
 * Procura vocabulário de dentro no **texto renderizado**.
 *
 * É a metade que a varredura estática de `.tsx` não alcança: o pior vazamento de
 * 12/09/2026 ("é o caso negativo do resolvedor… status pendente_coleta no gabarito v1")
 * não estava em nenhum `.tsx` — entrou como **dado**, vindo da API, de uma nota de
 * proveniência escrita para quem mantém o pipeline.
 */
function vocabularioDeDentro(texto: string): string[] {
  return VOCABULARIO.proibidos
    .filter((p) => new RegExp(p.regex, p.sensivel_a_maiuscula ? 'u' : 'iu').test(texto))
    .map((p) => `${p.termo} (${p.porque})`)
}

/** O `innerText` de `main` sem o que é evidência por desenho (citação, URL, snapshot). */
async function textoDeUsuario(page: Page): Promise<string> {
  return page.evaluate((isentos) => {
    const principal = document.querySelector('main')
    if (!principal) return ''
    const copia = principal.cloneNode(true) as HTMLElement
    for (const seletor of isentos) {
      for (const no of copia.querySelectorAll(seletor)) no.remove()
    }
    return copia.innerText
  }, VOCABULARIO.seletores_isentos.map((s) => s.seletor))
}

const ROTAS = [
  { tela: 'consulta', caminho: '/app/consulta', titulo: 'Consulta' },
  { tela: 'radar', caminho: '/app/radar', titulo: 'Radar competitivo' },
  { tela: 'matriz', caminho: '/app/matriz', titulo: 'Matriz de paridade' },
  { tela: 'saude', caminho: '/app/saude', titulo: 'Saúde do conhecimento' },
  { tela: 'showroom', caminho: '/app/showroom', titulo: 'Showroom' },
  { tela: 'insights', caminho: '/app/insights', titulo: 'Insights de win/loss' },
  { tela: 'simulador', caminho: '/app/simulador', titulo: 'Simulador de cenário' },
  { tela: 'benchmark', caminho: '/app/benchmark', titulo: 'Benchmark competitivo' },
] as const

const CELULAR = { width: 390, height: 844 }

test('uma volta pelas oito telas: F5 mantém, carrega em menos de 2 s, sem texto técnico nem erro de console', async ({
  page,
}) => {
  // Uma volta só, e não duas: oito telas recarregadas do zero já respondem a pergunta
  // deste teste, e a segunda volta mediria a mesma coisa custando o dobro do tempo.
  const { erros } = vigiarConsole(page)
  await entrar(page, 'admin')

  // "Traceback"/"None" e os termos de dentro vêm da lista compartilhada; estes quatro são
  // sintomas de JavaScript, não de vocabulário, e por isso ficam aqui.
  const proibidos = ['undefined', 'NaN', 'Internal Server Error', '[object Object]']

  for (const rota of ROTAS) {
    const comecou = Date.now()
    await page.goto(rota.caminho)
    await expect(page.getByRole('heading', { level: 1, name: rota.titulo })).toBeVisible()
    const levou = Date.now() - comecou

    expect(levou, `${rota.caminho} carregou em ${levou} ms`).toBeLessThan(2000)
    expect(page.url(), `${rota.caminho} depois do F5`).toContain(rota.caminho)

    await page.waitForTimeout(600)
    const texto = await textoDeUsuario(page)
    for (const termo of proibidos) {
      expect(texto, `"${termo}" na tela ${rota.caminho}`).not.toContain(termo)
    }
    if (!ROTAS_ISENTAS.has(rota.caminho)) {
      expect(vocabularioDeDentro(texto), `vocabulário de dentro em ${rota.caminho}`).toEqual([])
    }
  }

  // **Console limpo, sem exceção.** Havia duas, e as duas caíram nesta rodada:
  //
  // * **429** era a cota de 60 requisições por minuto do próprio produto (QA-17). O limite
  //   saiu do caminho de execução (D-206);
  // * **422** era o Simulador abrindo no par cujo concorrente não tem preço sugerido, e
  //   pedindo variação percentual sobre um valor que não existe (QA-24). O par padrão
  //   passou a ser Ranger Limited x Amarok V6 Extreme, que têm preço dos dois lados
  //   (D-208).
  expect(erros, `erros de console: ${erros.join(' | ')}`).toEqual([])
})

/**
 * **Os estados, e não só as rotas.**
 *
 * A recusa da GR-Sport não é uma tela: é um estado da Consulta depois de submeter um
 * veículo fora de linha. Uma varredura que percorre as sete rotas passa por cima dela — e
 * passou, por meses, enquanto o vendedor lia que a versão "é o caso negativo do
 * resolvedor" com "status pendente_coleta no gabarito v1".
 *
 * Este teste exercita os estados em que texto vindo de **dado** aparece na tela. É a
 * metade que a varredura estática de `.tsx` não alcança, porque essas frases não estão em
 * nenhum `.tsx`.
 */
test('os estados que trazem texto vindo de dado também falam português de quem vende', async ({
  page,
}) => {
  await entrar(page, 'analista')

  async function consultar(marca: string, modelo: string, versao: string) {
    await irPara(page, 'consulta')
    await consultarVeiculo(page, marca, modelo, versao)
  }

  // 1. versão fora do banco — a identificação/pesquisa não vaza vocabulário interno.
  await consultar('Mitsubishi', 'Triton', 'HPE-S 2.4 Turbodiesel AT6 4x4 2026')
  await expect(
    page.locator('[data-testid="cartao-da-ficha"], [data-testid="dados-do-catalogo"]').last(),
  ).toBeVisible({ timeout: 60_000 })
  expect(vocabularioDeDentro(await textoDeUsuario(page)), 'pesquisa da Triton').toEqual([])

  // 2. marca sem conector — nunca mostra exceção crua.
  await consultar('Fiat', 'Toro', 'Ultra 2.0 Diesel AT9')
  await expect(page.locator('main')).not.toContainText('Internal Server Error')
  await expect(page.locator('main')).not.toContainText('Traceback')
  expect(vocabularioDeDentro(await textoDeUsuario(page)), 'marca sem conector').toEqual([])

  // 3. nome parcial.
  await irPara(page, 'consulta')
  const caixa = page.getByTestId('pesquisa-caixa')
  await caixa.fill('Ranger Raptor')
  await caixa.press('Enter')
  await expect(page.getByTestId('ja-temos')).toBeVisible({ timeout: 60_000 })
  expect(vocabularioDeDentro(await textoDeUsuario(page)), 'nome parcial').toEqual([])

  // 4. a cadeia do "Por quê?" do Radar, que monta texto a partir de regras e de evidência.
  await irPara(page, 'radar')
  await page.getByRole('button', { name: 'Por quê?' }).first().click()
  const cadeia = page.getByTestId('gaveta-porque')
  await expect(cadeia.getByTestId('elo-1')).toBeVisible()
  // A gaveta mostra tier e snapshot de propósito — é evidência. O que se varre é o resto.
  const texto = await cadeia.evaluate((el) => {
    const copia = el.cloneNode(true) as HTMLElement
    for (const no of copia.querySelectorAll('[data-testid="trecho-literal"], [data-testid="snapshots"]'))
      no.remove()
    return copia.innerText
  })
  expect(
    vocabularioDeDentro(texto).filter((t) => !t.startsWith('LLM')),
    'cadeia do Por quê?',
  ).toEqual([])
  await page.keyboard.press('Escape')
})

test('voltar e avançar do navegador andam pelas telas', async ({ page }) => {
  await entrar(page, 'analista')

  for (const tela of ['radar', 'matriz', 'saude'] as const) {
    await irPara(page, tela)
    await expect(page).toHaveURL(new RegExp(`/app/${tela}$`))
  }

  await page.goBack()
  await expect(page).toHaveURL(/\/app\/matriz$/)
  await page.goBack()
  await expect(page).toHaveURL(/\/app\/radar$/)
  await page.goForward()
  await expect(page).toHaveURL(/\/app\/matriz$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Matriz de paridade' })).toBeVisible()
})

test('trocar de papel no meio troca o que a tela deixa ver (QA-BUG-16)', async ({ page }) => {
  // O caminho de ida, que é o do roteiro: o vendedor tenta o Radar e recebe a recusa.
  await entrar(page, 'vendedor')
  await irPara(page, 'radar')
  await expect(page.locator('main')).toContainText('Esta tela é de analista, gestor e administrador')

  await trocarPara(page, 'gestor')
  await irPara(page, 'radar')
  await expect(page.locator('main')).toContainText('alerta(s) na fila')
  await expect(page.locator('main')).not.toContainText('Esta tela é de analista')

  // E o caminho de volta, que era o defeito: o cache do que o gestor viu ficava na
  // memória da página e **continuava na tela** depois de trocar para vendedor. A fila de
  // alertas inteira, para quem não devia vê-la. Trocar de papel tem de esquecer o papel
  // anterior — e isso ficou mais importante desde D-204, porque agora não há um 403 do
  // servidor para desmentir o cache.
  await trocarPara(page, 'vendedor')
  await irPara(page, 'radar')
  await expect(page.locator('main')).toContainText('Esta tela é de analista, gestor e administrador')
  await expect(page.locator('main')).not.toContainText('alerta(s) na fila')
})

test('390 px: nenhuma tela rola para o lado nem corta conteúdo', async ({ page }) => {
  await page.setViewportSize(CELULAR)
  // Gestor: é o papel que alcança as sete telas, e a matriz — a mais larga — o vendedor
  // não abre cheia.
  await entrar(page, 'gestor')

  /**
   * Duas medidas, e a segunda entrou em 12/09/2026 porque a primeira não bastava.
   *
   * A primeira pergunta "a página rola de lado?". A segunda pergunta "sobrou alguma coisa
   * **fora** da tela?", ignorando o que está dentro de um contêiner com rolagem própria —
   * a matriz de 17 colunas rola dentro da moldura dela, e isso é o desenho.
   *
   * O defeito que só a segunda pega, medido no Simulador: o chip de hipótese media 555 px
   * numa tela de 390, **e a página não rolava**. A origem do número e o botão de remover a
   * hipótese ficavam fora da tela e fora do alcance, sem nada indicando que faltava. É pior
   * que rolagem: rolagem pelo menos se vê.
   */
  const medir = async (onde: string) => {
    await page.waitForTimeout(600)
    const rolouX = await page.evaluate(() => {
      window.scrollTo(9999, 0)
      const x = window.scrollX
      window.scrollTo(0, 0)
      return x
    })
    expect(rolouX, `${onde} a 390 px rolou ${rolouX} px para o lado`).toBe(0)

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
        .map((e) => `${e.tagName}.${String(e.className).slice(0, 50)}`),
    )
    expect(cortados, `${onde} a 390 px deixou conteúdo fora da tela`).toEqual([])
  }

  await medir('/app/consulta')

  // Pela barra de navegação, como um humano faria. No celular a barra vira uma faixa
  // inferior com "mais".
  for (const rota of ROTAS.slice(1)) {
    await irPara(page, rota.tela)
    await medir(rota.caminho)
  }

  // O endereço da tela de entrada que não existe mais: ele redireciona para a Consulta
  // (D-204), e a medida vale igual.
  await page.goto('/app/login')
  await medir('/app/login')
})

test('teclado: Tab percorre com foco visível, Enter abre a gaveta e Esc fecha', async ({ page }) => {
  await entrar(page, 'analista')
  await irPara(page, 'radar')
  await expect(page.getByRole('button', { name: 'Por quê?' }).first()).toBeVisible()

  for (let i = 0; i < 8; i++) {
    await page.keyboard.press('Tab')
    const foco = await page.evaluate(() => {
      const alvo = document.activeElement
      if (!alvo || alvo === document.body) return null
      const estilo = getComputedStyle(alvo)
      return {
        tag: alvo.tagName,
        temAnel: estilo.outlineStyle !== 'none' || estilo.boxShadow !== 'none',
      }
    })
    expect(foco, `o foco existe depois de ${i + 1} Tab(s)`).not.toBeNull()
    expect(foco!.temAnel, `foco visível em ${foco!.tag}`).toBe(true)
  }

  await page.getByRole('button', { name: 'Por quê?' }).first().focus()
  await page.keyboard.press('Enter')
  const gaveta = page.getByRole('dialog')
  await expect(gaveta).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(gaveta).toHaveCount(0)
  // O foco volta para quem abriu: quem navega por teclado não fica perdido.
  const voltou = await page.evaluate(() => (document.activeElement as HTMLElement)?.innerText ?? '')
  expect(voltou).toContain('Por quê?')
})
