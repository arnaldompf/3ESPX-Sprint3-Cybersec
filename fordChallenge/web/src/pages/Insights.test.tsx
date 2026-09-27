/**
 * A tela de Insights: **o `n` antes do percentual, e o simulado em bloco separado**.
 *
 * Os dois testes que carregam o peso vêm do critério de aceite: com 15 sessões reais a tela
 * mostra contagens e **nenhum** percentual; com 60 simuladas, os percentuais aparecem em
 * bloco próprio, com a faixa SIMULAÇÃO.
 *
 * Todo `describe` diz "insights" porque o verify da WP-27 seleciona por esse nome.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Insights } from './Insights'
import type { PainelDeWinLoss, PorConcorrente, ResumoDeWinLoss } from '@/lib/tipos'

function contagem(valor: number, de: number, comPercentual: boolean) {
  return {
    valor,
    de,
    percentual: comPercentual ? Number(((valor / de) * 100).toFixed(1)) : null,
  }
}

function concorrente(extra: Partial<PorConcorrente> = {}): PorConcorrente {
  const n = extra.n ?? 15
  const mostra = extra.mostra_percentual ?? false
  return {
    version_id: 'v-srx',
    rotulo: 'Toyota Hilux SRX Plus',
    n,
    fechou: contagem(10, n, mostra),
    perdeu: contagem(5, n, mostra),
    em_andamento: contagem(0, n, mostra),
    top_motivos: [
      { chave: 'preco', n: 3 },
      { chave: 'prazo_entrega', n: 2 },
    ],
    top_atributos_decisivos: [{ chave: 'preco_sugerido_brl', n: 8 }],
    perfis: [{ chave: 'rural_carga', n: 12 }],
    mostra_percentual: mostra,
    aviso: mostra
      ? ''
      : 'menos de 20 sessões: o painel mostra contagens, não percentuais. Um percentual ' +
        `sobre ${n} caso(s) pareceria estatística e seria ruído.`,
    ...extra,
  }
}

function painel(extra: Partial<PainelDeWinLoss> = {}): PainelDeWinLoss {
  return {
    real: [concorrente()],
    simulado: [],
    n_real: 15,
    n_simulado: 0,
    rotulo_simulacao: 'SIMULAÇÃO — dados de demonstração',
    n_minimo_para_percentual: 20,
    escopo: 'todos',
    aviso_de_escopo: '',
    ...extra,
  }
}

function resumo(extra: Partial<ResumoDeWinLoss> = {}): ResumoDeWinLoss {
  return {
    real: {
      n: 15,
      fechou: contagem(10, 15, false),
      perdeu: contagem(5, 15, false),
      em_andamento: contagem(0, 15, false),
      top_motivos: [{ chave: 'preco', n: 3 }],
      top_atributos_decisivos: [{ chave: 'preco_sugerido_brl', n: 8 }],
      mostra_percentual: false,
      aviso: 'menos de 20 sessões: o painel mostra contagens, não percentuais.',
    },
    simulado: {
      n: 60,
      fechou: contagem(27, 60, true),
      perdeu: contagem(24, 60, true),
      em_andamento: contagem(9, 60, true),
      top_motivos: [{ chave: 'preco', n: 8 }],
      top_atributos_decisivos: [{ chave: 'consumo_urbano_kml', n: 15 }],
      mostra_percentual: true,
      aviso: '',
    },
    rotulo_simulacao: 'SIMULAÇÃO — dados de demonstração',
    n_minimo_para_percentual: 20,
    escopo: 'todos',
    ...extra,
  }
}

function dublarApi(dadosDoPainel = painel(), dadosDoResumo = resumo()) {
  const chamadas: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      chamadas.push(url)
      const corpo = url.includes('/summary') ? dadosDoResumo : dadosDoPainel
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
      <Insights />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('insights: a regra do n', () => {
  it('com 15 sessões mostra contagem e nenhum percentual', async () => {
    dublarApi()
    montar()
    const cartao = await screen.findByTestId('concorrente-v-srx')
    expect(cartao.textContent).toContain('n = 15')
    expect(cartao.textContent).toContain('10/15')
    expect(cartao.textContent).not.toMatch(/\d+[.,]\d%/)
  })

  it('insights: o aviso explica por que não há percentual', async () => {
    dublarApi()
    montar()
    const aviso = await screen.findByTestId('aviso-v-srx')
    expect(aviso.textContent).toContain('menos de 20 sessões')
    expect(aviso.textContent).toContain('seria ruído')
  })

  it('insights: com n suficiente o percentual aparece', async () => {
    dublarApi(
      painel({
        real: [concorrente({ n: 22, mostra_percentual: true })],
        n_real: 22,
      }),
    )
    montar()
    const cartao = await screen.findByTestId('concorrente-v-srx')
    expect(cartao.textContent).toMatch(/\d+[.,]\d%/)
    expect(screen.queryByTestId('aviso-v-srx')).toBeNull()
  })

  it('insights: a tela declara o limiar que a API mandou', async () => {
    dublarApi()
    montar()
    expect(await screen.findByText(/n ≥ 20/)).toBeTruthy()
  })
})

describe('insights: o bloco simulado', () => {
  it('aparece separado, com a faixa SIMULAÇÃO', async () => {
    dublarApi(
      painel({
        simulado: [concorrente({ version_id: 'v-sim', n: 60, mostra_percentual: true })],
        n_simulado: 60,
      }),
    )
    montar()
    const faixa = await screen.findByTestId('faixa-simulacao')
    expect(faixa).toHaveAttribute('role', 'alert')
    expect(faixa.textContent).toContain('60 sessão(ões) semeada(s)')
    expect(screen.getByTestId('concorrente-v-sim')).toBeTruthy()
  })

  it('insights: sem simulado, nenhuma faixa aparece', async () => {
    dublarApi()
    montar()
    await screen.findByTestId('concorrente-v-srx')
    expect(screen.queryByTestId('faixa-simulacao')).toBeNull()
  })

  it('insights: o resumo mostra os dois blocos e diz que não os soma', async () => {
    dublarApi()
    montar()
    const real = await screen.findByTestId('resumo-real')
    const simulado = screen.getByTestId('resumo-simulado')
    expect(real.textContent).toContain('n = 15')
    expect(simulado.textContent).toContain('n = 60')
    expect(screen.getByText(/nunca são somados/)).toBeTruthy()
  })

  it('insights: o resumo real sem n suficiente não mostra percentual', async () => {
    dublarApi()
    montar()
    const real = await screen.findByTestId('resumo-real')
    expect(real.textContent).not.toMatch(/\d+[.,]\d%/)
    const simulado = screen.getByTestId('resumo-simulado')
    expect(simulado.textContent).toMatch(/\d+[.,]\d%/)
  })
})

describe('insights: o que o painel diz', () => {
  it('mostra motivos, atributos e perfis com a contagem', async () => {
    dublarApi()
    montar()
    const cartao = await screen.findByTestId('concorrente-v-srx')
    expect(cartao.textContent).toContain('preço')
    // A contagem perdeu os parênteses na v2: ela virou coluna alinhada à direita, em mono,
    // ao lado do motivo. O número continua obrigatório; o que muda é a forma.
    expect(cartao.textContent).toContain('3')
    expect(cartao.textContent).toContain('prazo de entrega')
    expect(cartao.textContent).toContain('trabalho rural / carga')
  })

  it('insights: lista vazia diz que é ausência de registro', async () => {
    dublarApi(
      painel({
        real: [concorrente({ top_motivos: [] })],
      }),
    )
    montar()
    expect(await screen.findByText(/ausência de registro, não ausência/)).toBeTruthy()
  })

  it('insights: sem sessão real, aponta para o bloco de demonstração', async () => {
    dublarApi(painel({ real: [], n_real: 0 }))
    montar()
    expect(await screen.findByText(/Nenhuma sessão real registrada/)).toBeTruthy()
  })
})

describe('insights: escopo do vendedor', () => {
  it('avisa quando o usuário vê apenas o que registrou', async () => {
    dublarApi(
      painel({
        escopo: 'proprios',
        aviso_de_escopo: 'você está vendo apenas as sessões que registrou',
      }),
    )
    montar()
    const aviso = await screen.findByTestId('aviso-de-escopo')
    expect(aviso.textContent).toContain('apenas as sessões que registrou')
  })

  it('insights: sem recorte, nenhum aviso de escopo', async () => {
    dublarApi()
    montar()
    await screen.findByTestId('concorrente-v-srx')
    expect(screen.queryByTestId('aviso-de-escopo')).toBeNull()
  })
})

describe('insights: filtro por data', () => {
  it('manda o since na consulta', async () => {
    const chamadas = dublarApi()
    montar()
    await screen.findByTestId('concorrente-v-srx')
    await userEvent.type(screen.getByLabelText('desde'), '2026-09-01')
    await waitFor(() =>
      expect(chamadas.some((u) => u.includes('since=2026-09-01'))).toBe(true),
    )
  })
})

describe('insights: erro da API', () => {
  it('mostra o problema em português', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ title: 'Papel insuficiente', detail: 'ação não permitida' }),
            { status: 403, headers: { 'Content-Type': 'application/problem+json' } },
          ),
      ),
    )
    montar()
    // A frase é a da pessoa, não o título cru do servidor (`lib/erros.ts`): 403 diz que é
    // o perfil, e não que o sistema quebrou.
    expect(await screen.findByText(/Seu perfil não pode carregar o win\/loss/)).toBeTruthy()
  })
})

describe('insights: os dois defeitos de etiqueta e de silêncio', () => {
  it('insights: o cartão de demonstração leva SIMULAÇÃO, nunca FATO', async () => {
    /* O defeito: `CartaoDoConcorrente` marcava `FATO` fixo e é usado nos **dois**
     * blocos. No bloco de demonstração isso punha um `✓ FATO` debaixo da faixa
     * `⚠ SIMULAÇÃO` — a mesma informação declarada observada e hipotética ao mesmo
     * tempo, que é a contradição mais direta da convenção de `docs/13` §2. */
    dublarApi(
      painel({
        real: [],
        simulado: [concorrente({ version_id: 'v-sim', rotulo: 'Hilux SRX Plus (demo)' })],
        n_real: 0,
        n_simulado: 60,
      }),
    )
    montar()

    const cartao = await screen.findByTestId('concorrente-v-sim')
    expect(cartao.textContent).toContain('SIMULAÇÃO')
    expect(cartao.textContent).not.toContain('FATO')
  })

  it('insights: o cartão real continua levando FATO', async () => {
    dublarApi(
      painel({
        real: [concorrente({ version_id: 'v-real', rotulo: 'Hilux SRX Plus' })],
        simulado: [],
        n_real: 15,
        n_simulado: 0,
      }),
    )
    montar()

    const cartao = await screen.findByTestId('concorrente-v-real')
    expect(cartao.textContent).toContain('FATO')
    expect(cartao.textContent).not.toContain('SIMULAÇÃO')
  })

  it('insights: 403 no resumo mostra a recusa em vez de sumir com o cartão', async () => {
    /* O vendedor recebe 403 em `/insights/summary` (D-103). O cartão "Resumo"
     * simplesmente desaparecia — e cartão que some é indistinguível de tela quebrada. */
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (entrada) => {
      const url = String(entrada)
      if (url.includes('/summary')) {
        return new Response(
          JSON.stringify({
            type: 'about:blank',
            title: 'Sem permissão',
            status: 403,
            detail: 'ver_insights exige analista, gestor ou admin.',
          }),
          { status: 403, headers: { 'content-type': 'application/problem+json' } },
        )
      }
      return new Response(JSON.stringify(painel()), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    })
    montar()

    const recusa = await screen.findByTestId('recusa-do-resumo')
    expect(recusa.textContent).toContain('Seu perfil não pode ver o resumo de win/loss')
    expect(recusa.textContent).toContain('analista, gestor ou admin')
  })
})
