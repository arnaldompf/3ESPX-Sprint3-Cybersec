/**
 * O Pesquisador na tela: o botão, o painel ao vivo e a trilha que se lê.
 *
 * A cena que estes testes guardam é a que faltava na demonstração: alguém pede um veículo
 * que não está no catálogo e, em vez de "não encontrado", vê o sistema procurar — com a
 * consulta exata, a fonte escolhida com o tier e **a fonte descartada com o motivo**.
 *
 * A visibilidade real vale aqui como vale nas gavetas: `toBeVisible()` responde true para
 * um painel fora da tela, e o painel do Pesquisador é o que a plateia vai olhar por três
 * minutos.
 */
import { expect, test } from '@playwright/test'

import { consultarVeiculo, exigirNoTopo, exigirVisivelDeVerdade, irPara } from './_ajuda'
import { sessaoCompartilhada } from './_sessao'

const sessao = sessaoCompartilhada('analista')

function fichaExibida(page) {
  return page.locator('[data-testid="cartao-da-ficha"], [data-testid="dados-do-catalogo"]').last()
}

/** O painel só existe com `RESEARCH_ENABLED=1`; sem isso, estes testes não se aplicam. */
async function pesquisaLigada(page): Promise<boolean> {
  const saude = await page.evaluate(async () => {
    const r = await fetch('/api/v1/health')
    return r.json()
  })
  return saude.research_enabled === true
}

async function abrirTrilhaConcluida(page) {
  const trilha = page.getByTestId('trilha-ao-vivo')
  const cabecalho = trilha.getByRole('button').first()
  // Na atualização de uma ficha, o cartão anterior permanece visível enquanto o
  // novo run trabalha. Portanto ele não é um sinal de término; o estado da própria
  // trilha é a fonte de verdade.
  await expect(cabecalho).toContainText(/Concluída/, { timeout: 60_000 })
  await expect(fichaExibida(page)).toBeVisible()
  if ((await cabecalho.getAttribute('aria-expanded')) === 'false') await cabecalho.click()

  const rodadas = trilha.locator('section[data-testid^="rodada-"]')
  for (let i = 0; i < (await rodadas.count()); i++) {
    const botao = rodadas.nth(i).getByRole('button').first()
    if ((await botao.getAttribute('aria-expanded')) === 'false') await botao.click()
  }
  return trilha
}

test('a entrada única para consultar ou pesquisar está sempre à vista', async () => {
  const page = sessao.page()
  await irPara(page, 'consulta')
  test.skip(!(await pesquisaLigada(page)), 'RESEARCH_ENABLED desligado neste ambiente')

  // **Sempre visível**, e não só depois de a consulta falhar: quem já sabe que o veículo é
  // novo não deveria ter de consultar, levar "não encontrado" e só então descobrir a saída.
  const caixa = page.getByTestId('pesquisa-caixa')
  await exigirVisivelDeVerdade(page, caixa, 'entrada da consulta', {
    alturaMinima: 30,
  })
  await exigirNoTopo(caixa, 'entrada da consulta')
})

test('veículo fora do banco inicia a pesquisa, em vez de um beco sem saída', async () => {
  const page = sessao.page()
  await irPara(page, 'consulta')
  test.skip(!(await pesquisaLigada(page)), 'RESEARCH_ENABLED desligado neste ambiente')

  await consultarVeiculo(page, 'Mitsubishi', 'Triton', 'HPE-S 2.4 Turbodiesel AT6 4x4 2026')
  await expect(fichaExibida(page)).toBeVisible({ timeout: 60_000 })
})

test('o painel ao vivo mostra a consulta, a fonte escolhida e a descartada', async () => {
  const page = sessao.page()
  await irPara(page, 'consulta')
  test.skip(!(await pesquisaLigada(page)), 'RESEARCH_ENABLED desligado neste ambiente')

  await consultarVeiculo(page, 'Ford', 'Ranger', 'Raptor 3.0 V6 Bi-turbo 4WD AT')
  await expect(page.getByTestId('ja-temos')).toBeVisible({ timeout: 60_000 })
  await page.getByTestId('pesquisar-de-novo').click()

  // A trilha aparece **enquanto acontece**: três minutos de tela parada é uma tela que
  // travou, e quem está com o cliente ao lado desiste antes.
  const trilha = page.getByTestId('trilha-ao-vivo')
  await expect(trilha).toBeVisible({ timeout: 30_000 })

  // Só então se mede: medir no primeiro quadro mediria o painel vazio.
  // `podeRolar`: o painel é conteúdo da página, e não uma gaveta. Um cartão de 1200 px
  // numa tela de 900 é normal — a pessoa rola. O que se exige é o topo à vista e altura
  // útil.
  await exigirVisivelDeVerdade(page, trilha, 'painel do Pesquisador', {
    // Em replay a pesquisa pode terminar antes da medição; o resumo concluído tem
    // ~197 px e continua plenamente legível. O piso protege contra colapso sem
    // transformar três pixels de tipografia numa falsa regressão funcional.
    alturaMinima: 180,
    podeRolar: true,
  })

  // O fim chega, e diz por que parou. "Acabou" não é resposta.
  await abrirTrilhaConcluida(page)
  const fim = trilha.getByTestId('passo-fim')
  await expect(fim).toBeVisible()
  expect((await fim.innerText()).length).toBeGreaterThan(20)

  // A consulta aparece **verbatim**, e não parafraseada: é o que permite repetir a busca.
  await expect(page.getByTestId('passo-consulta').first()).toContainText(/ficha técnica/i)

  // E os contadores dizem o que custou.
  const contadores = page.getByTestId('contadores-da-pesquisa')
  await contadores.scrollIntoViewIfNeeded()
  await exigirVisivelDeVerdade(page, contadores, 'contadores', { alturaMinima: 40 })
  await expect(contadores).toContainText('campos')
  await expect(contadores).toContainText('páginas lidas')
})

test('todo passo da trilha leva etiqueta, e nenhum mostra vocabulário de dentro', async () => {
  const page = sessao.page()
  await irPara(page, 'consulta')
  test.skip(!(await pesquisaLigada(page)), 'RESEARCH_ENABLED desligado neste ambiente')

  await consultarVeiculo(page, 'Ford', 'Ranger', 'Raptor 3.0 V6 Bi-turbo 4WD AT')
  await expect(page.getByTestId('ja-temos')).toBeVisible({ timeout: 60_000 })
  await page.getByTestId('pesquisar-de-novo').click()
  const trilha = await abrirTrilhaConcluida(page)

  // `docs/13` §2 vale no painel como vale na ficha: nenhuma informação sem etiqueta.
  const linhas = trilha.locator('li[data-testid^="passo-"]')
  const quantas = await linhas.count()
  expect(quantas).toBeGreaterThan(5)
  for (let i = 0; i < Math.min(quantas, 12); i++) {
    const texto = await linhas.nth(i).innerText()
    expect(texto).toMatch(/FATO|INFERÊNCIA|SIMULAÇÃO/)
  }
})
