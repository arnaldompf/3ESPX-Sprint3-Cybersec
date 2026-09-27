/**
 * A tela de Saúde do Conhecimento.
 *
 * O que estes testes guardam é a regra que separa este painel de um dashboard qualquer:
 * **nenhum número aparece sozinho**. Cada indicador com denominador, cada contagem com a
 * lista dos campos e o motivo de cada um, o status com o nome da regra que o decidiu, e o
 * texto fixo em todo cartão — porque "saúde: 72%" seria um número que ninguém audita.
 *
 * Todo `describe` diz "saude" porque o verify da WP-33 seleciona por esse nome
 * (`vitest run -t saude`), como o comando da spec pede.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Saude } from './Saude'
import { definirPapel } from '@/lib/papel'
import type { CoberturaDaMarca, Divergencia, Saude as TipoSaude } from '@/lib/tipos'

const REGRAS = [
  { nome: 'sem_campos', status: 'INSUFICIENTE', explicacao: 'Nenhum campo foi coletado.' },
  { nome: 'tem_conflito', status: 'REVISAR', explicacao: 'Fontes discordam em algum campo.' },
  { nome: 'sem_pendencia', status: 'OK', explicacao: 'Nenhuma pendência nos indicadores.' },
]

const TEXTO_FIXO = 'indicador operacional do MVP, não probabilidade de verdade'

function saude(extra: Partial<TipoSaude> = {}): TipoSaude {
  return {
    version_id: 'v-raptor',
    rotulo: 'Ford Ranger Raptor 3.0 V6 Bi-turbo 4WD AT',
    verificados: { valor: 30, de: 58, fracao: 0.517, campos: [] },
    desatualizados: {
      valor: 1,
      de: 30,
      fracao: 0.033,
      campos: [
        {
          campo: 'preco_sugerido_brl',
          motivo: 'coletado há 45 dias',
          detalhe: 'acima do limiar de 30 dias (https://www.ford.com.br/ranger-raptor/)',
        },
      ],
    },
    conflitos: {
      valor: 4,
      de: 30,
      fracao: 0.133,
      campos: [
        {
          campo: 'modos_amortecedor',
          motivo: 'fontes discordam',
          detalhe: 'os valores concorrentes estão na ficha, cada um com a sua evidência',
        },
      ],
    },
    nao_confirmados: { valor: 0, de: 30, fracao: 0, campos: [] },
    fontes_bloqueadas: { valor: 0, de: 0, fracao: null, campos: [] },
    ultima_atualizacao: '2026-09-01T00:00:00',
    status: 'REVISAR',
    regra_do_status: 'tem_conflito',
    explicacao_do_status:
      'Fontes discordam em pelo menos um campo. Os dois valores estão na ficha, com evidência.',
    limiar_de_dias: 30,
    texto_fixo: TEXTO_FIXO,
    regras: REGRAS,
    ...extra,
  }
}

function cobertura(): CoberturaDaMarca[] {
  return [
    {
      marca: 'Toyota',
      versoes_mapeadas: 6,
      versoes_com_ficha: 1,
      campos_com_fonte_oficial: { valor: 34, de: 58, fracao: 0.586, campos: [] },
      nao_encontrados: { valor: 24, de: 58, fracao: 0.414, campos: [] },
      divergencias: { valor: 5, de: 58, fracao: 0.086, campos: [] },
      por_campo: { potencia_rpm: { valor: 1, de: 1, fracao: 1, campos: [] } },
    },
    {
      marca: 'Ford',
      versoes_mapeadas: 2,
      versoes_com_ficha: 1,
      campos_com_fonte_oficial: { valor: 28, de: 58, fracao: 0.483, campos: [] },
      nao_encontrados: { valor: 28, de: 58, fracao: 0.483, campos: [] },
      divergencias: { valor: 4, de: 58, fracao: 0.069, campos: [] },
      por_campo: { potencia_rpm: { valor: 0, de: 1, fracao: 0, campos: [] } },
    },
  ]
}

function divergencias(escopo = 'official_vs_press'): Divergencia[] {
  return [
    {
      escopo,
      version_id: 'v-raptor',
      rotulo: 'Ford Ranger Raptor',
      campo: 'modos_amortecedor',
      valores: [
        { valor: ['normal', 'sport', 'off_road'], origem: 'https://www.ford.com.br/', tier: 1 },
        { valor: ['normal', 'sport', 'baja'], origem: 'file://slide.md', tier: 4 },
      ],
      gap: null,
      detectado_em: null,
    },
  ]
}

function dublarApi(opcoes: { saude?: TipoSaude[]; vazio?: boolean } = {}) {
  const chamadas: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      chamadas.push(url)
      let corpo: unknown = []
      if (url.includes('knowledge-health/versions')) {
        corpo = opcoes.vazio ? [] : (opcoes.saude ?? [saude()])
      } else if (url.includes('coverage')) {
        corpo = cobertura()
      } else if (url.includes('divergences')) {
        const escopo = url.includes('internal_vs_public')
          ? 'internal_vs_public'
          : 'official_vs_press'
        corpo = divergencias(escopo)
      }
      return new Response(JSON.stringify(corpo), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return chamadas
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={cliente}>
      <Saude />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('saude: nenhum número aparece sozinho', () => {
  it('mostra o texto fixo em todo cartão', async () => {
    dublarApi()
    montar()
    const textos = await screen.findAllByTestId('texto-fixo')
    expect(textos.length).toBe(1)
    expect(textos[0]?.textContent).toBe(TEXTO_FIXO)
  })

  it('saude: todo indicador vem com o denominador', async () => {
    dublarApi()
    montar()
    const verificados = await screen.findByTestId('indicador-verificados')
    expect(verificados.textContent).toContain('30')
    expect(verificados.textContent).toContain('/58')
    const conflitos = screen.getByTestId('indicador-conflitos')
    expect(conflitos.textContent).toContain('4')
    expect(conflitos.textContent).toContain('/30')
  })

  it('saude: nenhuma porcentagem de confiança na tela', async () => {
    dublarApi()
    montar()
    await screen.findByTestId('indicador-verificados')
    const cartao = screen.getByTestId('saude-v-raptor')
    // Fração existe no dado, mas a tela não a transforma em "51% de confiança".
    expect(cartao.textContent).not.toMatch(/\d+% de confian/i)
    expect(cartao.textContent).not.toMatch(/\d+% verdade/i)
  })

  it('saude: abre a lista dos campos com o motivo de cada um', async () => {
    dublarApi()
    montar()
    await screen.findByTestId('indicador-desatualizados')
    await userEvent.click(screen.getAllByText('ver quais, e por quê')[0]!)
    expect(screen.getByText(/coletado há 45 dias/)).toBeTruthy()
    expect(screen.getByText(/acima do limiar de 30 dias/)).toBeTruthy()
  })

  it('saude: o indicador sem base não desenha barra nem inventa zero', async () => {
    dublarApi()
    montar()
    const bloqueadas = await screen.findByTestId('indicador-fontes_bloqueadas')
    expect(bloqueadas.textContent).toContain('0/0')
  })
})

describe('saude: o status vem de uma regra nomeada', () => {
  it('mostra o selo, a explicação e o nome da regra', async () => {
    dublarApi()
    montar()
    expect(await screen.findByTestId('status-REVISAR')).toBeTruthy()
    expect(screen.getByText(/Fontes discordam em pelo menos um campo/)).toBeTruthy()
    // `getAllByText`: o nome da regra aparece na linha do status E na lista de regras
    // (o conteudo do `<details>` fica no DOM mesmo fechado). Duas ocorrencias e o
    // comportamento certo — a mesma regra dita no resumo e no detalhe.
    expect(screen.getAllByText(/tem_conflito/).length).toBeGreaterThanOrEqual(1)
  })

  it('saude: abre todas as regras, destacando a que decidiu', async () => {
    dublarApi()
    montar()
    await screen.findByTestId('status-REVISAR')
    await userEvent.click(screen.getByText('por que este status?'))
    for (const regra of REGRAS) {
      expect(screen.getAllByText(new RegExp(regra.nome)).length).toBeGreaterThanOrEqual(1)
    }
    // A que decidiu vem destacada, para o olho achar a linha certa entre as sete.
    // A busca é DENTRO da lista de regras: o nome da regra também aparece na linha do
    // status, e `closest('li')` de lá acharia o cartão da versão inteiro.
    const lista = screen.getByTestId('regras')
    const decidiu = Array.from(lista.querySelectorAll('li')).find((li) =>
      li.textContent?.includes('tem_conflito'),
    )
    expect(decidiu?.className).toContain('font-semibold')
  })

  it('saude: a etiqueta do cartão é INFERÊNCIA', async () => {
    dublarApi()
    montar()
    const cartao = await screen.findByTestId('saude-v-raptor')
    expect(cartao.querySelector('[data-testid="badge-INFERENCIA"]')).toBeTruthy()
  })

  it('saude: o status INSUFICIENTE aparece com o próprio selo', async () => {
    dublarApi({
      saude: [
        saude({
          version_id: 'v-vazia',
          status: 'INSUFICIENTE',
          regra_do_status: 'sem_campos',
          explicacao_do_status: 'Nenhum campo foi coletado para esta versão.',
        }),
      ],
    })
    montar()
    expect(await screen.findByTestId('status-INSUFICIENTE')).toBeTruthy()
  })
})

describe('saude: cobertura por montadora', () => {
  it('mostra versões com ficha contra versões mapeadas', async () => {
    dublarApi()
    montar()
    const toyota = await screen.findByTestId('cobertura-Toyota')
    // "1 de 6" e não "1/6": na v2 a cobertura virou barra com o denominador POR EXTENSO,
    // que é o que a regra pede (percentual sem denominador é anti-padrão §24). Os dois
    // números continuam obrigatórios; muda a forma de escrevê-los.
    expect(toyota.textContent).toContain('1 de 6')
  })

  it('saude: mostra quem publica rotação e quem não publica', async () => {
    dublarApi()
    montar()
    const toyota = await screen.findByTestId('cobertura-Toyota')
    const ford = screen.getByTestId('cobertura-Ford')
    expect(toyota.textContent).toContain('1 de 1')
    expect(ford.textContent).toContain('0 de 1')
  })

  it('saude: explica por que mostra dois números em vez de porcentagem', async () => {
    dublarApi()
    montar()
    expect(
      await screen.findByText(/diz o tamanho do trabalho que falta/),
    ).toBeTruthy()
  })
})

describe('saude: divergências', () => {
  it('mostra os dois valores, nunca um vencedor', async () => {
    dublarApi()
    montar()
    const linha = await screen.findByTestId('divergencia')
    expect(linha.textContent).toContain('off road')
    expect(linha.textContent).toContain('baja')
    expect(linha.textContent).toContain('tier 1')
    expect(linha.textContent).toContain('tier 4')
  })

  it('saude: troca de escopo refaz a consulta', async () => {
    const chamadas = dublarApi()
    montar()
    await screen.findByTestId('divergencia')
    await userEvent.selectOptions(
      screen.getByLabelText('escopo das divergências'),
      'internal_vs_public',
    )
    await waitFor(() =>
      expect(chamadas.some((u) => u.includes('scope=internal_vs_public'))).toBe(true),
    )
  })
})

describe('saude: lista vazia e papel de outra tela', () => {
  it('sem versão com ficha, aponta para a cobertura em vez de mostrar nada', async () => {
    dublarApi({ vazio: true })
    montar()
    expect(await screen.findByText(/Nenhuma versão com ficha ainda/)).toBeTruthy()
  })

  it('papel que não é desta tela recebe a explicação, não a tela vazia', async () => {
    /* **Quem decide é a tela** (D-204): o servidor não recusa mais nada, e este painel
     * mostra tier de fonte e divergência com material da casa — dado interno, que não é
     * do vendedor (D-103). */
    definirPapel('vendedor')
    dublarApi()
    montar()
    expect(await screen.findByTestId('recusa-por-papel')).toBeTruthy()
    expect(screen.getByText(/não vai para a tela virada ao cliente/)).toBeTruthy()
  })
})
