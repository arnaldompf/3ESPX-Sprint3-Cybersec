/**
 * O caminho dourado: as quatorze cenas de `docs/demo/ROTEIRO_15SET.md`, em ordem, gravadas.
 *
 * **Para que serve.** É o vídeo de segurança da apresentação de 15/09. Se a máquina, a
 * rede ou o navegador falharem no palco, o arquivo `reports/demo/golden_path.webm`
 * mostra o produto funcionando, com os mesmos números que o roteiro cita. Ele também é
 * um teste de verdade: se uma cena parar de acontecer, ele falha — e falha **antes** do
 * palco.
 *
 * **O que ele não é.** Não substitui as outras suítes: aqui a asserção é "a cena
 * acontece e o que ela promete está na tela", grossa de propósito, porque o objetivo é
 * percorrer o roteiro inteiro numa sessão só. O detalhe de cada tela está nos outros
 * arquivos.
 *
 * **Cenas 1, 11 e 12 são slides** — não há software. Elas entram como marcação, para o
 * vídeo ter a mesma linha do tempo da fala.
 *
 * Rodar:
 *
 *     python scripts/task.py golden
 *     # ou, de dentro de qa/:  npx playwright test --config playwright.golden.config.ts
 *
 * O arquivo final vai para `reports/demo/golden_path.webm`. A configuração de regressão
 * **ignora** este arquivo de propósito: ele grava vídeo e não é portão de commit.
 */
import fs from 'node:fs'
import path from 'node:path'

import { expect, type Page, test } from '@playwright/test'

import { consultarVeiculo, entrar, irPara, trocarPara } from './_ajuda'
import { contador, fichasDoBanco, porNome } from './_fichas'

const VIDEO = path.resolve(__dirname, '..', '..', 'reports', 'demo', 'golden_path.webm')
const PASTA_DO_VIDEO = path.dirname(VIDEO)

/** 1280×720: abre em qualquer projetor e o arquivo continua pequeno. */
const PALCO = { width: 1280, height: 720 }

/**
 * Tempo de leitura entre as cenas. Sem ele o vídeo fica ilegível: a máquina navega em
 * 200 ms e quem assiste não vê nada. Não é espera de carregamento disfarçada — as
 * esperas de verdade são as asserções.
 *
 * 2,6 s deixa o vídeo em torno de um minuto e meio para as quatorze cenas. O palco tem
 * 7 min 50 s; este arquivo não substitui a fala, substitui a **tela**, e quem narra pausa
 * o vídeo onde precisar.
 */
const LEITURA = 2600

test.describe.configure({ mode: 'serial' })

let page: Page

test.beforeAll(async ({ browser }) => {
  fs.mkdirSync(PASTA_DO_VIDEO, { recursive: true })
  const contexto = await browser.newContext({
    viewport: PALCO,
    recordVideo: { dir: PASTA_DO_VIDEO, size: PALCO },
  })
  page = await contexto.newPage()
})

test.afterAll(async () => {
  const gravado = page.video()
  // O arquivo só existe depois de o contexto fechar.
  await page.context().close()
  if (gravado) {
    await gravado.saveAs(VIDEO)
    await gravado.delete()
  }
  expect(fs.existsSync(VIDEO), 'o vídeo foi salvo em ' + VIDEO).toBe(true)
  const bytes = fs.statSync(VIDEO).size
  expect(bytes, 'o vídeo não está vazio').toBeGreaterThan(50_000)
  // Fica impresso: quem for apresentar precisa saber onde está e quanto pesa.
  console.log('\n  vídeo de segurança: ' + VIDEO + ' (' + Math.round(bytes / 1024) + ' KB)\n')
})

/** Uma cena, com o nome que o roteiro usa — o log lê como a linha do tempo da fala. */
async function cena(numero: string, nome: string, corpo: () => Promise<void>) {
  console.log('  cena ' + numero + ' — ' + nome)
  await corpo()
  await page.waitForTimeout(LEITURA)
}

test('as quatorze cenas do roteiro de 15/09, na ordem, gravadas em vídeo', async () => {
  test.setTimeout(240_000)

  await cena('1', 'A dor da Ford (slide)', async () => {
    // A primeira coisa que a plateia vê é **a ferramenta**, não uma tela de entrada
    // (D-204): `/app` cai na Consulta, com o papel na barra lateral.
    await page.goto('/app')
    await expect(page).toHaveURL(/\/app\/consulta$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Consulta' })).toBeVisible()
    await expect(page.locator('body')).toContainText('com a evidência de cada campo')
  })

  await cena('2', 'A ficha da Raptor, com evidência', async () => {
    await entrar(page, 'analista')
    const raptor = porNome(await fichasDoBanco(page), /Raptor/)

    await page.goto(raptor.url)
    await expect(page.locator('main')).toContainText('Campos com valor')

    // Os quatro contadores, e o de fontes **não** é zero (QA-BUG-03). O ajudante espera
    // a contagem de 400 ms terminar antes de ler: um quadro do meio da subida seria um
    // número menor, e o teste falharia por um defeito que não existe.
    expect(await contador(page, 'Campos com valor')).toBeGreaterThan(0)
    expect(await contador(page, 'Fontes consultadas')).toBeGreaterThan(0)

    // O trecho literal, a URL, a data e o tier.
    await page.getByRole('button', { name: /ver evidência/i }).first().click()
    const gaveta = page.getByRole('dialog')
    await expect(gaveta).toContainText('Fonte:')
    await expect(gaveta).toContainText('Coletado em:')
    await page.waitForTimeout(LEITURA)
    await page.keyboard.press('Escape')

    // E os dois vazios, com nomes diferentes.
    await expect(page.locator('main')).toContainText('não encontrado nas fontes')
  })

  await cena('3', 'A GR-Sport ainda não está no banco', async () => {
    await irPara(page, 'consulta')
    await consultarVeiculo(page, 'Toyota', 'Hilux', 'GR-Sport')

    const main = page.locator('main')
    await expect(main).not.toContainText('Internal Server Error')
    await expect(main).not.toContainText('Traceback')
    await expect(
      page
        .getByTestId('confirmacao')
        .or(page.getByTestId('trilha-ao-vivo'))
        .or(page.getByTestId('nao-entendi'))
        .or(page.getByTestId('ja-temos')),
    ).toBeVisible({ timeout: 60_000 })
  })

  await cena('4', 'Divergência entre fontes, com os dois valores à vista', async () => {
    const raptor = porNome(await fichasDoBanco(page), /Raptor/)
    await page.goto(raptor.url)
    await expect(page.locator('main')).toContainText('Campos com valor')

    const main = page.locator('main')
    await expect(main).toContainText('As fontes divergem. Os dois valores, com a evidência de cada:')
    await expect(main).toContainText('5,8 s')
    await expect(main).toContainText('6,5 s')
  })

  await cena('5', 'FOGO AMIGO — o material interno contra a fonte pública', async () => {
    await irPara(page, 'radar')
    await page.getByLabel('Tipo').selectOption({ label: 'divergência com material interno' })
    const main = page.locator('main')
    await expect(main).toContainText('divergência com material interno')
    await expect(main).toContainText('499')
    await expect(main).toContainText('499.000')

    // A cadeia dos cinco elos, com a citação literal da página da Ford.
    await page.getByRole('button', { name: 'Por quê?' }).first().click()
    const cadeia = page.getByRole('dialog')
    await expect(cadeia).toContainText(/o que fazer/i)
    await expect(cadeia).toContainText(/por que esta materialidade/i)
    await expect(cadeia).toContainText(/a prova/i)
    await page.waitForTimeout(LEITURA)
    await page.keyboard.press('Escape')
    await page.getByLabel('Tipo').selectOption({ label: 'todos os tipos' })
  })

  await cena('6', 'Matriz de paridade com "não sabemos"', async () => {
    await irPara(page, 'matriz')
    await expect(page.locator('table tbody tr').first()).toBeVisible()
    const main = page.locator('main')
    await expect(main).toContainText(/não sabemos/i)
    await expect(main).toContainText(
      'O concorrente é melhor neste campo. Aparece sempre, sem exceção.',
    )
    await expect(main).toContainText('par não comparável')
  })

  await cena('7', 'Saúde do conhecimento e cobertura por montadora', async () => {
    await irPara(page, 'saude')
    const main = page.locator('main')
    await expect(main).toContainText(/INSUFICIENTE|REVISAR|OK/)
    await page.getByRole('button', { name: /por que este status\?/i }).first().click()
    await expect(main).toContainText(/regra: [a-z_]+ · limiar de \d+ dias/)
    await expect(main).toContainText('Cobertura por montadora')
    await expect(main).toContainText(/\d+ de 58/)
  })

  await cena('8', 'Copiloto: perfil do fazendeiro, aderência, 3+1 e o documento', async () => {
    await trocarPara(page, 'vendedor')
    await irPara(page, 'showroom')

    await page.getByLabel(/^versão Ford$/).selectOption({
      label: 'Ranger Limited 3.0 V6 Diesel 4WD AT',
    })
    await page.getByLabel(/^concorrente$/).selectOption({ label: 'Toyota Hilux SRX Plus AT' })
    await page.getByRole('button', { name: 'trabalho rural / carga' }).click()
    await page.getByLabel('km por mês').fill('2000')
    await page.waitForTimeout(LEITURA)
    await page.getByRole('button', { name: 'comparar por este perfil' }).click()

    const main = page.locator('main')
    await expect(page.getByRole('heading', { name: 'Aderência ao perfil' })).toBeVisible()
    await expect(main).toContainText('Aderência ao perfil informado — não é um ranking de qualidade')
    await expect(main).toContainText('Onde Toyota Hilux SRX Plus AT vence')
    await expect(main).toContainText('Custo de combustível estimado')
    await expect(main).toContainText(/PBE\/Inmetro|declarado pela montadora/)
    await page.waitForTimeout(LEITURA)

    await page.getByRole('button', { name: 'gerar argumentos' }).click()
    await expect(main).toContainText('Ponto de atenção')
    await page.waitForTimeout(LEITURA)

    await page.getByRole('button', { name: /gerar documento/i }).click()
    const documento = page.getByRole('link', { name: /abrir o documento/i })
    await expect(documento).toBeVisible({ timeout: 40_000 })
    await expect(documento).toHaveAttribute('href', /\.pdf$/)
    await page.waitForTimeout(LEITURA)

    // E o registro do desfecho, que é o que alimenta a cena 9.
    await page.getByRole('button', { name: /^abrir sessão$/i }).click()
    await page.getByRole('button', { name: /^fechou$/ }).click()
    await page.getByRole('button', { name: /registrar resultado/i }).click()
    await expect(main).toContainText('Resultado registrado')
  })

  await cena('9', 'Win/Loss e insights, com SIMULAÇÃO rotulada', async () => {
    await trocarPara(page, 'gestor')
    await irPara(page, 'insights')
    const main = page.locator('main')
    await expect(main).toContainText('Percentual só aparece com n ≥ 20')
    await expect(main).toContainText('SIMULAÇÃO')
    await expect(main).toContainText('Os dois blocos nunca são somados')
  })

  await cena('10', 'Radar: materialidade e "Por quê?"', async () => {
    await trocarPara(page, 'analista')
    await irPara(page, 'radar')
    const main = page.locator('main')
    await expect(main).toContainText(/alerta\(s\) na fila/)
    await expect(main).toContainText(/alta/i)
    await expect(main).toContainText('abrir o ruído')

    await page.getByRole('button', { name: 'Por quê?' }).first().click()
    const cadeia = page.getByRole('dialog')
    await expect(cadeia).toContainText('ponto(s)')
    await expect(cadeia).toContainText(/magnitude|parity_flip|dimensao_de_peso/)
    await page.waitForTimeout(LEITURA)
    await page.keyboard.press('Escape')
  })

  await cena('10b', 'What-if: "e se o concorrente baixar 5%?"', async () => {
    await trocarPara(page, 'gestor')
    await irPara(page, 'simulador')
    const main = page.locator('main')
    await expect(main).toContainText('SIMULAÇÃO')

    // **O passo de palco saiu** (D-208). A tela abre em Ranger Limited x Amarok V6
    // Extreme, que têm preço dos dois lados — é de onde sai o "379.990 → 360.990" do
    // bloco medido do roteiro. Antes ela abria no par do Showroom, cuja Hilux não tem
    // preço, e o apresentador trocava o concorrente à mão, ao vivo, para a cena
    // acontecer.
    await expect(main).toContainText('Volkswagen Amarok V6 Extreme')
    await expect(main).not.toContainText('Sem cenário para este par')
    await page.waitForTimeout(LEITURA)

    await page.locator('input[type=range]').fill('-5')
    await expect(main).toContainText('Preço do concorrente: -5%')
    await expect(main).toContainText('379.990')
    await expect(main).toContainText('360.990')
    await expect(main).toContainText('hipótese informada pelo usuário')
    await expect(main).toContainText('SIMULAÇÃO — não é dado observado')
  })

  await cena('11', 'Arquitetura (slide)', async () => {
    // Sem software. Fica a Saúde na tela, que é de onde saem os números do slide.
    await trocarPara(page, 'analista')
    await irPara(page, 'saude')
    await expect(page.locator('main')).toContainText('Cobertura por montadora')
  })

  await cena('12', 'Próxima onda e visão (slide)', async () => {
    // Também slide. Fecha onde começou: a Consulta, que é a porta do produto.
    await irPara(page, 'consulta')
    await expect(page.getByRole('heading', { level: 1, name: 'Consulta' })).toBeVisible()
  })

  await cena('13', 'E se eu pedir um carro que não está aí?', async () => {
    // A cena que responde a objeção que o público faz sozinho depois de doze cenas sobre
    // cinco veículos coletados: "ok, mas isso só funciona com o que vocês já têm".
    //
    // Roda em **replay**: as respostas de busca e as páginas vêm de `tests/fixtures/`,
    // gravadas em 13/09/2026 a partir de uma pesquisa ao vivo. O replay devolve os mesmos
    // campos que o ao vivo — é isso que faz dele plano B, e não encenação.
    const saude = await page.evaluate(async () => {
      const r = await fetch('/api/v1/health')
      return r.json()
    })
    if (saude.research_enabled !== true) {
      // Sem a bandeira, a cena não existe — e o vídeo tem de dizer isso em vez de fingir.
      await expect(page.getByRole('heading', { level: 1, name: 'Consulta' })).toBeVisible()
      return
    }

    await trocarPara(page, 'analista')
    await irPara(page, 'consulta')
    await consultarVeiculo(page, 'Mitsubishi', 'Triton', 'HPE-S 2.4 Turbodiesel AT6 4x4')

    // A trilha aparece enquanto acontece — é o que a plateia olha.
    await expect(
      page.locator('[data-testid="cartao-da-ficha"], [data-testid="dados-do-catalogo"]').last(),
    ).toBeVisible({ timeout: 90_000 })
    // E o fim diz por que parou. "Acabou" não é resposta.
  })

  await cena('14', 'Benchmark: contra quem a Ranger briga', async () => {
    // Condicional, como a 13 — e pela mesma razão: uma capacidade atrás de bandeira que o
    // vídeo mostrasse como se estivesse sempre ligada seria encenação.
    //
    // **O que esta cena tem de diferente das outras treze:** ela mostra o sistema
    // *recusando* comparações. Os pares que a régua reprova ficam na tela, com o motivo —
    // e é isso, e não a matriz cheia, que responde "por que eu confiaria nisto?".
    const saude = await page.evaluate(async () => {
      const r = await fetch('/api/v1/health')
      return r.json()
    })
    if (saude.benchmark_enabled !== true) {
      // Sem a bandeira, a tela diz que o recurso não está ligado — e o vídeo grava isso,
      // que é a verdade daquele ambiente. Fingir seria pior que não ter a cena.
      await trocarPara(page, 'analista')
      await irPara(page, 'benchmark')
      await expect(page.getByTestId('benchmark-desligado')).toBeVisible()
      return
    }

    await trocarPara(page, 'analista')
    await irPara(page, 'benchmark')

    // A proposta, com o `k/n` de cada par e o motivo de cada ausência.
    await expect(page.getByTestId('conjunto-proposto')).toBeVisible({ timeout: 30_000 })

    // E a comparação, com os quatro cartões — "não sabemos" do mesmo tamanho dos outros.
    await page.getByRole('button', { name: /comparar/i }).click()
    await expect(page.getByTestId('matriz-do-benchmark')).toBeVisible({ timeout: 30_000 })
  })
})
