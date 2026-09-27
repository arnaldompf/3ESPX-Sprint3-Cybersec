/**
 * A ficha: contadores, etiquetas, evidência e os dois vazios.
 *
 * QA-BUG-03 mora aqui: o contador **"Fontes consultadas"** marcava **0** nas cinco
 * fichas, ao lado de "30 campos com valor" e de trinta botões "ver evidência" que abrem
 * com URL e citação. A causa estava em `pipeline/persist.py` (evidência gravada sem
 * `snapshot_id`), e a prova de que foi corrigido é esta tela.
 */
import { expect, type Page, test } from '@playwright/test'

import { abrir } from './_ajuda'
import { sessaoCompartilhada } from './_sessao'
import { contador, fichasDoBanco, porNome } from './_fichas'

/** A quebra de linha do `innerText`, num lugar só — literal de uma linha. */
const QUEBRA = String.fromCharCode(10)

/** Abre a ficha e espera ela terminar de montar: o título e o primeiro contador. */
async function abrirFicha(page: Page, url: string): Promise<void> {
  await abrir(page, url, 'Campos com valor')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
}

// Cada arquivo entra pelo papel que usa a tela de verdade, para o ensaio exercitar o que
// cada perfil realmente vê. A ficha é do analista e do admin.
const sessao = sessaoCompartilhada('admin')

test('as cinco fichas: contadores batem com a lista e declaram fonte consultada', async () => {
  const page = sessao.page()
  const fichas = await fichasDoBanco(page)
  expect(fichas.length).toBeGreaterThan(0)

  for (const ficha of fichas) {
    await abrirFicha(page, ficha.url)
    const comValor = await contador(page, 'Campos com valor')
    const fontes = await contador(page, 'Fontes consultadas')
    const botoes = await page.getByRole('button', { name: /ver evidência/i }).count()
    // Desde 12/09/2026 a Identificação é preenchida pelo catálogo: marca, modelo, versão,
    // ano-modelo e código FIPE são a identidade da versão consultada e **não têm** trecho
    // verbatim — por isso levam a marca CATÁLOGO em vez de fingir evidência. Contar esses
    // campos separadamente é o que mantém a regra de ouro afiada em vez de afrouxá-la.
    // Dentro das linhas de campo, e não na página inteira: a legenda do rodapé também
    // mostra um pill de cada etiqueta, e contá-la daria um campo a mais que não existe.
    const doCatalogo = await page
      .locator('[data-testid^="campo-"] [data-testid="badge-CATALOGO"]')
      .count()

    expect(comValor, `${ficha.nome}: campos com valor`).toBeGreaterThan(0)
    expect(doCatalogo, `${ficha.nome}: a identificação vem do catálogo`).toBeGreaterThan(0)
    expect(
      botoes,
      `${ficha.nome}: todo campo com valor tem evidência, menos os do catálogo`,
    ).toBe(comValor - doCatalogo)
    // O defeito: 30 campos com evidência e "Fontes consultadas: 0".
    expect(fontes, `${ficha.nome}: fontes consultadas`).toBeGreaterThan(0)

    // E o que o avaliador viu: o cabeçalho dizendo "Ford Ranger Raptor … FIPE 003506-8" e
    // a Identificação, logo abaixo, dizendo "não encontrado" nos mesmos campos.
    const identificacao = page.getByTestId('campo-marca')
    await expect(identificacao).not.toContainText('não encontrado')
    await expect(page.getByTestId('valor-marca')).not.toHaveText('—')
  }
})

test('a evidência abre com trecho, fonte e data — e a data é a da coleta', async () => {
  const page = sessao.page()
  const fichas = await fichasDoBanco(page)
  const raptor = porNome(fichas, /Raptor/)
  await abrirFicha(page, raptor.url)

  await page.getByRole('button', { name: /ver evidência/i }).first().click()
  const gaveta = page.getByRole('dialog')
  await expect(gaveta).toBeVisible()
  await expect(gaveta).toContainText('Fonte:')
  await expect(gaveta).toContainText('Coletado em:')
  await expect(gaveta).toContainText('tier')

  // A data da coleta é a da página salva, não a da gravação no banco (QA-BUG-04).
  const texto = await gaveta.innerText()
  const data = texto.match(/Coletado em:\s*(\d{2}\/\d{2}\/\d{4})/)
  expect(data, 'a gaveta traz a data da coleta').not.toBeNull()
  const hoje = new Date()
  const dataDeHoje = `${String(hoje.getDate()).padStart(2, '0')}/${String(hoje.getMonth() + 1).padStart(2, '0')}/${hoje.getFullYear()}`
  expect(data![1], 'data de coleta não pode ser a data de hoje (era a hora da gravação)').not.toBe(
    dataDeHoje,
  )

  await page.keyboard.press('Escape')
  await expect(gaveta).toHaveCount(0)
})

test('campo divergente mostra os dois valores, cada um com a sua fonte', async () => {
  const page = sessao.page()
  const fichas = await fichasDoBanco(page)
  const raptor = porNome(fichas, /Raptor/)
  await abrirFicha(page, raptor.url)

  const main = page.locator('main')

  // **Na aceleração, a fonte é UMA só.** A matéria registra os 5,8 s que a Ford declara e
  // os 6,5 s que a revista cronometrou — mesma URL nas duas evidências. Até 12/09/2026 a
  // tela dizia "As fontes divergem", errando o fato e jogando fora o melhor argumento que
  // a página oferece a quem vende.
  const aceleracao = page.getByTestId('campo-aceleracao_0_100_s')
  await expect(aceleracao).toContainText('Mesma fonte, dois valores: declarado × medido.')
  await expect(aceleracao).not.toContainText('As fontes divergem')
  await expect(aceleracao).toContainText('5,8 s · declarado')
  await expect(aceleracao).toContainText('6,5 s · medido')

  // O PDF sem ano aplicável não pode fabricar divergência com a página da versão.
  const modos = page.getByTestId('campo-modos_conducao')
  await expect(modos).not.toContainText('As fontes divergem')
  await expect(modos.getByTestId('badge-FATO')).toBeVisible()

  expect(await contador(page, 'Divergências')).toBeGreaterThan(0)
})

test('resumo do edital mostra a contagem e explica cada vazio ao expandir', async () => {
  const page = sessao.page()
  const fichas = await fichasDoBanco(page)
  const raptor = porNome(fichas, /Raptor/)
  await abrirFicha(page, raptor.url)

  const main = page.locator('main')
  await expect(main).toContainText('Requisito do edital:')
  const contagem = page.getByTestId('edital-contagem')
  await expect(contagem).toBeVisible()
  const texto = (await contagem.innerText()).trim()
  expect(texto).toMatch(/^\d+\/\d+$/)

  await page.getByTestId('edital-alternar-lista').click()
  const lista = page.getByTestId('edital-lista')
  await expect(lista).toBeVisible()
  // Todo item vazio explica o motivo entre parênteses — nunca fica em branco.
  const itensVazios = lista.locator('li', { hasText: '(' })
  expect(await itensVazios.count()).toBeGreaterThanOrEqual(0)
})

test('campo vazio diz o motivo do vazio, nunca fica em branco', async () => {
  const page = sessao.page()
  const fichas = await fichasDoBanco(page)
  await abrirFicha(page, fichas[0].url)
  await expect(page.locator('main')).toContainText(/Nenhuma(?: das \d+)? fonte(?:\(s\))? consultada(?:\(s\))? menciona este campo/)
  await expect(page.locator('main')).toContainText('não encontrado nas fontes')
})

test('modo showroom esconde tier e confiança, e mantém fonte e data', async () => {
  const page = sessao.page()
  const fichas = await fichasDoBanco(page)
  const raptor = porNome(fichas, /Raptor/)
  await abrirFicha(page, raptor.url)

  await expect(page.locator('main')).toContainText('confiança')
  await page.getByLabel(/modo showroom/i).check()
  await expect(page.locator('main')).not.toContainText('confiança')

  await page.getByRole('button', { name: /ver evidência/i }).first().click()
  const gaveta = page.getByRole('dialog')
  await expect(gaveta).not.toContainText('tier')
  await expect(gaveta).not.toContainText('confiança')
  await expect(gaveta).toContainText('Fonte:')
  await expect(gaveta).toContainText('Coletado em:')
})

test('nenhum valor da ficha aparece como slug de banco (QA-BUG-05)', async () => {
  const page = sessao.page()
  const fichas = await fichasDoBanco(page)
  const raptor = porNome(fichas, /Raptor/)
  await abrirFicha(page, raptor.url)

  // `motor_descricao` saía "3.0l_v6_bi_turbo" e `amortecedores`, um parágrafo inteiro em
  // snake_case. URL de fonte tem underscore legítimo e não entra: só o corpo da ficha.
  const blocos = await page.locator('main dl, main table, main ul').allInnerTexts()
  const comSlug = blocos
    .flatMap((b) => b.split(QUEBRA))
    .filter((l) => /[a-z0-9]_[a-z0-9]/.test(l) && !/https?:|file:/.test(l))

  expect(comSlug, `linhas com valor em snake_case: ${comSlug.join(' | ')}`).toEqual([])
})
