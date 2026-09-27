/**
 * O cartão do resultado: contagens do `fim`, custo medido, os primeiros campos da ficha
 * gravada com etiqueta, a data das fontes e os dois caminhos que seguem.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  CartaoDaFicha,
  camposComValor,
  contar,
  formatarDuracao,
  linhaDeCusto,
  ultimaColeta,
} from './CartaoDaFicha'
import { MemoryRouter } from 'react-router-dom'
import { GRUPOS, type Campo, type EventoDePesquisa, type Ficha, type TrilhaDePesquisa } from '@/lib/tipos'

function campo(value: unknown, extra: Partial<Campo> = {}): Campo {
  return {
    value,
    unit: null,
    status: 'verificado',
    confidence: 0.9,
    evidences: [
      {
        evidence_id: 'e1',
        source_url: 'https://www.ford.com.br/ranger',
        tier: 1,
        quote: 'trecho',
        captured_at: '2026-09-05T10:00:00Z',
      },
    ],
    conflicts: [],
    sources_checked: ['https://www.ford.com.br/ranger'],
    ...extra,
  }
}

function ficha(): Ficha {
  const base = Object.fromEntries(GRUPOS.map((g) => [g, {}])) as Record<(typeof GRUPOS)[number], Record<string, Campo>>
  return {
    ...base,
    motorizacao: {
      potencia_cv: campo(397, { unit: 'cv' }),
      torque_nm: campo(583, { unit: 'N·m', evidences: [{ ...campo(0).evidences[0]!, captured_at: '2026-09-11T08:00:00Z' }] }),
      combustivel: campo(null, { status: 'nao_encontrado' }),
    },
    dimensoes: {
      comprimento_mm: campo(5370, { unit: 'mm' }),
      largura_mm: campo(2028, { unit: 'mm' }),
      altura_mm: campo(1922, { unit: 'mm' }),
      entre_eixos_mm: campo(3270, { unit: 'mm' }),
      peso_kg: campo(2454, { unit: 'kg' }),
    },
    extras: {},
    schema_version: '1',
    meta: {
      generated_at: '2026-09-13T00:00:00Z',
      job_id: 'j',
      version_resolution: { status: 'encontrada', alternatives: [] },
      sources_checked: [],
    },
  } as Ficha
}

function fim(dados: Record<string, unknown>, texto = 'Parou por cobertura.'): EventoDePesquisa {
  return { ordem: 9, tipo: 'fim', texto, etiqueta: 'FATO', rodada: 2, decorrido: 135.2, dados }
}

function trilha(extra: Partial<TrilhaDePesquisa> = {}): TrilhaDePesquisa {
  return {
    run_id: 'run-1',
    status: 'concluida',
    veiculo: 'Ford Ranger Raptor',
    motivo_da_parada: 'cobertura',
    campos_com_valor: 7,
    campos_alvo: 40,
    paginas: 3,
    rodadas: 2,
    segundos: 135,
    version_id: 'v-1',
    erro: null,
    eventos: [
      fim({
        motivo: 'cobertura',
        cobertura: { total: 40, com_valor: 7 },
        bloqueadas: 1,
        medicao: { chamadas: 3, custo_usd: 0.027 },
        gasto_rodada_usd: 0.31,
        teto_usd: 2,
      }),
    ],
    ...extra,
  }
}

function montar(t: TrilhaDePesquisa, resposta: unknown = ficha(), status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify(resposta), {
          status,
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  )
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CartaoDaFicha trilha={t} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('as funções puras', () => {
  it('camposComValor segue a ordem dos grupos e ignora o vazio', () => {
    const nomes = camposComValor(ficha()).map((c) => c.nome)
    expect(nomes).toEqual([
      'potencia_cv',
      'torque_nm',
      'comprimento_mm',
      'largura_mm',
      'altura_mm',
      'entre_eixos_mm',
      'peso_kg',
    ])
  })

  it('ultimaColeta é a maior captured_at entre as evidências', () => {
    expect(ultimaColeta(ficha())).toBe('2026-09-11T08:00:00Z')
  })

  it('formatarDuracao e contar', () => {
    expect(formatarDuracao(135.2)).toBe('2 min 15 s')
    expect(formatarDuracao(48)).toBe('48 s')
    expect(contar(['a', 'b'])).toBe(2)
    expect(contar(3)).toBe(3)
    expect(contar(undefined)).toBe(0)
  })

  it('linhaDeCusto só existe com medição', () => {
    expect(linhaDeCusto({})).toBeNull()
    expect(
      linhaDeCusto({ medicao: { chamadas: 1, custo_usd: 0.009 }, gasto_rodada_usd: 0.3, teto_usd: 2 }),
    ).toMatch(/^1 chamada ao modelo · US\$ 0,009 \(rodada: US\$ 0,30 de US\$ 2,00\)$/)
  })
})

describe('o cartão', () => {
  it('mostra as contagens, o custo, seis campos com etiqueta, a data e os dois botões', async () => {
    montar(trilha())

    const cartao = screen.getByTestId('cartao-da-ficha')
    expect(cartao).toHaveTextContent('Ford Ranger Raptor')
    expect(cartao).toHaveTextContent('Parou por cobertura.')
    expect(screen.getByTestId('resumo-da-ficha')).toHaveTextContent(
      '7 de 40 campos com prova · 1 fonte bloqueada · 2 min 15 s',
    )
    expect(screen.getByTestId('custo-da-pesquisa')).toHaveTextContent('3 chamadas ao modelo')

    const campos = await screen.findAllByTestId('campo-da-ficha')
    expect(campos).toHaveLength(6)
    expect(campos[0]).toHaveTextContent('Potência (cv)')
    expect(campos[0]).toHaveTextContent('397 cv')
    expect(campos[0]).toContainElement(screen.getAllByTestId('badge-FATO')[2]!)

    expect(screen.getByTestId('coletado-em')).toHaveTextContent('fontes coletadas em 11/09/2026')
    expect(screen.getByTestId('abrir-ficha')).toHaveAttribute('href', '/ficha/v-1')
    expect(screen.getByTestId('comparar-com')).toHaveAttribute('href', '/matriz')

    await userEvent.click(screen.getByTestId('ver-todos-os-campos'))
    expect(screen.getAllByTestId('campo-da-ficha')).toHaveLength(7)
  })

  it('sem version_id, mostra o erro em vez dos botões', () => {
    montar(trilha({ version_id: null, erro: 'nenhum campo fechou com prova' }))
    expect(screen.getByRole('alert')).toHaveTextContent('nenhum campo fechou com prova')
    expect(screen.queryByTestId('abrir-ficha')).toBeNull()
  })

  it('sem medição no fim, não inventa linha de custo', () => {
    montar(trilha({ eventos: [fim({ motivo: 'cobertura', cobertura: { total: 40, com_valor: 7 } })] }))
    expect(screen.queryByTestId('custo-da-pesquisa')).toBeNull()
  })
})
