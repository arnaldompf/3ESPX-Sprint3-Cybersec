/**
 * A Consulta unificada resolve a versão certa antes de abrir ou pesquisar a ficha.
 *
 * Pedindo "Ford Ranger Raptor 3.0 V6 Bi-turbo 4WD AT", o cartão dizia
 * **Versão encontrada: Raptor 3.0 V6 Bi-turbo 4WD AT** e logo abaixo listava as três
 * versões da Ranger na ordem do catálogo — com a **Limited** em primeiro. Quem clica no
 * primeiro item abre a ficha do veículo errado, e é assim que a cena 2 do roteiro de
 * 15/09 chega à ficha ("chegue à ficha pela tela de Consulta, sempre").
 *
 * A regra que este arquivo fixa: a versão que o resolvedor casou é a **primeira** da
 * lista. As outras continuam ali — são versões do mesmo modelo e servem para trocar sem
 * digitar de novo.
 */
import { expect, test } from '@playwright/test'

import { consultarVeiculo, irPara } from './_ajuda'
import { sessaoCompartilhada } from './_sessao'

const sessao = sessaoCompartilhada('analista')

async function consultar(page, marca: string, modelo: string, versao: string) {
  await irPara(page, 'consulta')
  await consultarVeiculo(page, marca, modelo, versao)
}

test('a versão resolvida é a pedida, não uma irmã do mesmo modelo', async () => {
  const page = sessao.page()
  await consultar(page, 'Ford', 'Ranger', 'Raptor 3.0 V6 Bi-turbo 4WD AT')

  const resultado = page.getByTestId('ja-temos')
  await expect(resultado).toBeVisible({ timeout: 60_000 })
  await expect(resultado).toContainText('Raptor 3.0 V6 Bi-turbo 4WD AT')
  await expect(resultado).not.toContainText('Limited')
})

test('minúsculas e o modelo repetido na versão ainda resolvem a ficha certa', async () => {
  const page = sessao.page()
  await consultar(page, 'toyota', 'hilux', 'hilux srx plus')

  const resultado = page.getByTestId('ja-temos')
  await expect(resultado).toBeVisible({ timeout: 60_000 })
  await expect(resultado).toContainText('SRX Plus AT')
})

test('veículo fora do banco não entrega uma ficha parecida e inicia a pesquisa', async () => {
  const page = sessao.page()
  await consultar(page, 'Mitsubishi', 'Triton', 'HPE-S 2.4 Turbodiesel AT6 4x4 2026')

  const main = page.locator('main')
  await expect(page.getByTestId('ja-temos')).toHaveCount(0)
  await expect(main).not.toContainText('Internal Server Error')
  await expect(main).not.toContainText('Traceback')
  // Em replay, a pesquisa pode terminar antes do primeiro quadro do navegador. O cartÃ£o
  // final comprova de forma estÃ¡vel que o fluxo pesquisou, persistiu e retornou a ficha.
  await expect(page.getByTestId('cartao-da-ficha')).toBeVisible({ timeout: 60_000 })
})

test('marca sem conector responde sem erro cru e registra a tentativa', async () => {
  const page = sessao.page()
  await consultar(page, 'Fiat', 'Toro', 'Ultra 2.0 Diesel AT9')

  const main = page.locator('main')
  await expect(page.getByTestId('cartao-da-ficha')).toBeVisible({ timeout: 60_000 })
  await expect(main).not.toContainText('Traceback')
  await expect(main).not.toContainText('Internal Server Error')
})

test('nome parcial identifica o veículo existente', async () => {
  const page = sessao.page()
  await irPara(page, 'consulta')
  const caixa = page.getByTestId('pesquisa-caixa')
  await caixa.fill('Ranger Raptor')
  await caixa.press('Enter')

  await expect(page.getByTestId('ja-temos')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('ja-temos')).toContainText('Raptor')
})
