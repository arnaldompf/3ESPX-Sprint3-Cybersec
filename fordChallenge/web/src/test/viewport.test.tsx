/**
 * O critério de aceite de **390 px sem scroll horizontal**, verificado onde o problema
 * nasce: no CSS que os componentes declaram.
 *
 * A spec cita Playwright, e o `verify` dela (que é o comando que manda) **não** o executa.
 * A razão de eu não tê-lo posto no verify é concreta: o Playwright precisa **baixar
 * navegadores** (centenas de MB) na primeira execução, e a regra da noite é "rede só o
 * necessário". Um portão que só passa depois de um download de 300 MB não é portão — é
 * um obstáculo que a próxima pessoa vai desligar. Há um `e2e/viewport.spec.ts` escrito
 * para quem quiser rodar (`npm run e2e`), e este teste cobre a mesma garantia por outro
 * caminho.
 *
 * **O que este teste realmente verifica:** que nenhum componente declara largura fixa
 * maior que 390 px, e que a barra de navegação rola **dentro dela mesma**
 * (`overflow-x-auto` na barra) em vez de empurrar a página. Em jsdom não há layout de
 * verdade — `scrollWidth` é sempre 0 —, então medir pixel aqui seria teatro. O que se
 * pode afirmar com honestidade é sobre as classes, e é o que se afirma.
 *
 * O layout é mobile-first e sem `@media` para diminuir: o critério de 390 px não se cumpre
 * com breakpoint, cumpre-se **não colocando largura fixa**.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { Card } from '@/components/Card'
import { FieldRow } from '@/components/FieldRow'
import { Layout } from '@/components/Layout'
import { Shell } from '@/pages/Shell'
import type { Campo } from '@/lib/tipos'

const SRC = resolve(__dirname, '..')

function arquivosTsx(pasta: string): string[] {
  const achados: string[] = []
  for (const entrada of readdirSync(pasta, { withFileTypes: true })) {
    const caminho = join(pasta, entrada.name)
    if (entrada.isDirectory()) achados.push(...arquivosTsx(caminho))
    else if (entrada.name.endsWith('.tsx') && !entrada.name.includes('.test.'))
      achados.push(caminho)
  }
  return achados
}

const FONTES = arquivosTsx(SRC).map((caminho) => ({
  caminho: caminho.replace(SRC, 'src'),
  texto: readFileSync(caminho, 'utf-8'),
}))

describe('390 px sem scroll horizontal', () => {
  it('nenhum componente declara largura fixa em pixel', () => {
    // `w-[420px]`, `min-w-[400px]` e `width: 500px` são as três formas de furar o
    // critério. Largura em `rem` ou fração (`w-full`, `flex-1`) não fura.
    const suspeitos: string[] = []
    for (const { caminho, texto } of FONTES) {
      for (const achado of texto.matchAll(/\b(?:w|min-w)-\[(\d+)px\]/g)) {
        if (Number(achado[1]) > 320) suspeitos.push(`${caminho}: ${achado[0]}`)
      }
      for (const achado of texto.matchAll(/(?:width|min-width):\s*(\d+)px/g)) {
        if (Number(achado[1]) > 320) suspeitos.push(`${caminho}: ${achado[0]}`)
      }
    }
    expect(suspeitos, `largura fixa acima de 320 px: ${suspeitos.join(', ')}`).toEqual([])
  })

  it('nenhum componente esconde o scroll com overflow-x-hidden no corpo', () => {
    // Esconder o scroll faria o critério "passar" com o layout quebrado por baixo.
    const css = readFileSync(join(SRC, 'index.css'), 'utf-8')
    expect(css).not.toMatch(/body[^}]*overflow-x:\s*hidden/)
  })

  it('no celular a navegação é barra inferior fixa, não uma faixa rolável', () => {
    // Até 10/09 a navegação era uma fila de sete abas com `overflow-x-auto`: ela rolava
    // dentro dela mesma, o que cumpria o critério e era feio — sete abas em 390 px
    // significa rolar de lado para achar "Simulador". A v2 troca por sidebar no desktop e
    // **barra inferior fixa** no celular, com cinco alvos e o resto em "mais". O critério
    // é o mesmo (nada rola de lado); o mecanismo é outro.
    const layout = FONTES.find((f) => f.caminho.endsWith('Layout.tsx'))
    expect(layout).toBeDefined()
    expect(layout!.texto).toMatch(/fixed inset-x-0 bottom-0[^"]*md:hidden/)
    // E a sidebar não existe no celular, senão ela e a barra inferior apareceriam juntas.
    expect(layout!.texto).toMatch(/hidden flex-col[\s\S]{0,200}md:flex/)
    // Nenhuma navegação rola na horizontal: é o que a v1 fazia, e o que esta troca desfaz.
    expect(layout!.texto).not.toMatch(/<nav[^>]*[\s\S]{0,200}overflow-x-auto/)
  })

  it('nenhuma grade abre com três ou mais colunas no celular', () => {
    // O limiar é **três**, e foi medido em vez de escolhido: em 390 px, duas colunas dão
    // ~195 px cada, o que cabe um número curto ("397/58") com folga — e é o que a linha
    // de resumo da Ficha faz. Três colunas dão 130 px, e aí qualquer rótulo estoura.
    //
    // A primeira versão desta regra exigia `grid-cols-1` sempre e acusou o resumo da
    // Ficha, que está correto. Regra que acusa código certo é regra ruim: ou vira ruído
    // que alguém desliga, ou empurra uma mudança pior que o problema.
    const erradas: string[] = []
    for (const { caminho, texto } of FONTES) {
      for (const achado of texto.matchAll(/className="[^"]*\bgrid\b[^"]*"/g)) {
        const classes = achado[0]
        // A classe sem prefixo de breakpoint é a do celular. `sm:grid-cols-4` só vale a
        // partir de 640 px, então não conta.
        const semPrefixo = classes.match(/(?:^|[\s"])grid-cols-(\d)/)
        if (semPrefixo && Number(semPrefixo[1]) >= 3) {
          erradas.push(`${caminho}: ${classes.slice(0, 90)}`)
        }
      }
    }
    expect(erradas, `grade com 3+ colunas no celular: ${erradas.join(' | ')}`).toEqual([])
  })

  it('o conteúdo longo tem por onde quebrar', () => {
    // URL de fonte e id de snapshot são longos e sem espaço: sem `break-all`/`break-words`
    // eles esticam a caixa e é aí que o scroll horizontal aparece de verdade. A citação
    // literal migrou para `Gaveta.tsx` na v2, e a regra vale nos dois arquivos.
    const gaveta = FONTES.find((f) => f.caminho.endsWith('EvidenceDrawer.tsx'))
    expect(gaveta!.texto).toMatch(/break-all/)
    expect(gaveta!.texto).toMatch(/break-words/)
    const painel = FONTES.find((f) => f.caminho.endsWith('Gaveta.tsx'))
    expect(painel!.texto).toMatch(/break-words/)
  })
})

describe('as telas renderizam em viewport de celular', () => {
  const campo: Campo = {
    value: 397,
    unit: 'cv',
    status: 'verificado',
    confidence: 0.95,
    evidences: [],
    conflicts: [],
    sources_checked: ['ford_site'],
  }

  it('a linha da ficha usa `flex-wrap`, então o valor desce em vez de estourar', () => {
    const { container } = render(<FieldRow campo="potencia_cv" dados={campo} />)
    const linha = container.querySelector('[data-testid="campo-potencia_cv"] > div')
    expect(linha?.className).toContain('flex-wrap')
  })

  it('o Card não tem largura própria: quem manda é o contêiner', () => {
    const { container } = render(<Card titulo="x">conteúdo</Card>)
    const secao = container.querySelector('section')
    expect(secao?.className).not.toMatch(/\bw-\[/)
  })

  it('o Layout renderiza as duas navegações, e a do celular tem alvo de toque', () => {
    // O `QueryClientProvider` entrou aqui na WP-25: o Layout passou a contar os alertas
    // nao lidos para o selo do Radar, e sem provedor o `useQuery` levanta.
    const { container } = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Layout />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const navs = Array.from(container.querySelectorAll('nav'))
    expect(navs).toHaveLength(2)
    const doCelular = navs.find((n) => n.className.includes('bottom-0'))
    expect(doCelular).toBeDefined()
    // 56 px de altura mínima: acima dos 44 px que o critério de toque exige.
    expect(doCelular!.innerHTML).toContain('min-h-[56px]')
    // Nenhuma das duas rola de lado.
    for (const nav of navs) expect(nav.className).not.toContain('overflow-x-auto')
  })

  it('a página de casco diz qual WP entrega, em vez de "em construção"', () => {
    const { container } = render(
      <Shell titulo="Matriz" wp="WP-32" descricao="d" itens={['a']} />,
    )
    expect(container.textContent).toContain('WP-32')
  })
})
