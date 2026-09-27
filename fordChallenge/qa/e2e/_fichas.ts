/**
 * As fichas do banco, descobertas pela tela e guardadas para a execução inteira.
 *
 * Os ids de versão são sorteados a cada `up.ps1 -Refazer` — o roteiro de 15/09 diz isso e
 * manda chegar à ficha pela Consulta. Os testes fazem o mesmo, e por isso precisam
 * descobrir os ids antes de usá-los.
 *
 * **Duas telas, não onze navegações.** A Consulta lista as versões **que têm ficha**, por
 * nome; o Showroom traz **todas** as versões do catálogo nos dois `<select>` (a Ford e a
 * concorrente), e ali o `value` de cada opção é o id da versão. Cruzando as duas, saem os
 * cinco endereços de ficha com duas navegações. Abrir ficha por ficha e voltar custava
 * onze, e cada uma é um carregamento de tela inteiro: a descoberta sozinha levava mais
 * tempo que as asserções que ela existe para permitir.
 *
 * Com `workers: 1` o processo é o mesmo para todos os arquivos, então esta memória vale
 * para a execução inteira.
 */
import { expect, type Page } from '@playwright/test'

import { irPara } from './_ajuda'

export interface FichaDoBanco {
  readonly nome: string
  readonly url: string
}

let cache: FichaDoBanco[] | null = null

/** Minúsculas e sem acento, para casar "Saúde" com "saude" e nomes com/sem marca. */
function chave(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
}

export async function fichasDoBanco(page: Page): Promise<FichaDoBanco[]> {
  if (cache) return cache

  await irPara(page, 'consulta')
  await expect(page.locator('main')).toContainText('Versões com ficha no banco')
  const linhas = page.getByTestId('ficha-do-banco')
  await expect(linhas.first()).toBeVisible()
  const nomes: string[] = []
  for (let i = 0; i < (await linhas.count()); i++) {
    nomes.push((await linhas.nth(i).getAttribute('data-rotulo'))?.trim() ?? '')
  }
  expect(nomes.length, 'a Consulta lista as versões com ficha').toBeGreaterThan(0)

  await irPara(page, 'showroom')
  // Os seletores são preenchidos por uma consulta à parte do título da tela.
  await expect(page.getByLabel(/^concorrente$/).locator('option').first()).toBeAttached()
  const opcoes = await page.evaluate(() =>
    [...document.querySelectorAll('select')].flatMap((s) =>
      [...s.options].map((o) => ({ id: o.value, rotulo: (o.textContent ?? '').trim() })),
    ),
  )

  const achadas: FichaDoBanco[] = []
  for (const nome of nomes) {
    const alvo = chave(nome)
    // O seletor Ford omite a marca ("Ranger Raptor…"); o de concorrente a inclui.
    const casou = opcoes.find((o) => o.rotulo && (alvo === chave(o.rotulo) || alvo.endsWith(chave(o.rotulo))))
    if (casou?.id) achadas.push({ nome, url: `/app/ficha/${casou.id}` })
  }

  expect(achadas.length, `ids encontrados para ${nomes.join(', ')}`).toBe(nomes.length)
  cache = achadas
  return cache
}

/** A ficha cujo nome casa, para os testes que falam de um veículo específico. */
export function porNome(fichas: readonly FichaDoBanco[], parte: RegExp): FichaDoBanco {
  const achada = fichas.find((f) => parte.test(f.nome))
  if (!achada) throw new Error(`nenhuma ficha casa com ${parte}: ${fichas.map((f) => f.nome)}`)
  return achada
}

/**
 * O valor de um cartão de métrica, **depois** de a contagem terminar.
 *
 * O número sobe em 400 ms na primeira renderização (`Contador`), e ler o texto da tela no
 * meio da subida compara "12 campos" com "30 botões de evidência": falha por um defeito
 * que não existe. O cartão publica o valor final em `data-valor` desde o primeiro quadro,
 * e o teste **também** espera o texto alcançá-lo — assim ele continua medindo o que a
 * pessoa vê, e não só o que o componente prometeu.
 *
 * Mora aqui, e não no arquivo de teste da ficha, porque o caminho dourado também o usa:
 * um `import` entre dois `*.spec.ts` faria a suíte de um rodar dentro do outro.
 */
export async function contador(page: Page, rotulo: string): Promise<number> {
  const numero = page.locator(`[data-metrica="${rotulo}"] [data-valor]`)
  await expect(numero).toHaveAttribute('data-valor', /\d+/)
  const alvo = (await numero.getAttribute('data-valor')) ?? ''
  await expect(numero).toHaveText(alvo)
  return Number(alvo)
}
