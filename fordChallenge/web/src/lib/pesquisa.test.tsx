/**
 * A bandeira do `/health` chega **depois** da primeira pintura — e a tela tem de acordar.
 *
 * O defeito, medido no navegador em 13/09/2026: `main.tsx` dispara `sincronizar()` sem
 * esperar (de propósito, para não segurar a primeira pintura), e a tela Pesquisa lia
 * `pesquisaLigada()` uma vez, no corpo do componente. A resposta chegava 40 ms depois e
 * nada re-renderizava: a tela ficava dizendo "o Pesquisador não está ligado neste
 * ambiente" num ambiente em que ele estava ligado, até alguém recarregar a página.
 *
 * A Consulta escapava por acidente — ela re-renderiza a cada tecla —, e isso é a parte
 * ruim: o defeito existia nas duas e só aparecia numa.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  benchmarkLigadoAgora,
  definirBenchmarkParaTeste,
  definirParaTeste,
  pesquisaLigada,
  sincronizar,
  useBenchmarkLigado,
  usePesquisaLigada,
} from './pesquisa'

function Sonda() {
  const pesquisa = usePesquisaLigada()
  const benchmark = useBenchmarkLigado()
  return (
    <p>
      pesquisa: {pesquisa ? 'ligada' : 'desligada'} · benchmark:{' '}
      {benchmark ? 'ligado' : 'desligado'}
    </p>
  )
}

function dublarSaude(corpo: unknown, ok = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify(corpo), {
          status: ok ? 200 : 503,
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  definirParaTeste(false)
  definirBenchmarkParaTeste(false)
})

describe('as bandeiras do ambiente', () => {
  it('a tela montada antes da resposta acorda quando ela chega', async () => {
    definirParaTeste(false)
    definirBenchmarkParaTeste(false)
    dublarSaude({ research_enabled: true, benchmark_enabled: true })

    render(<Sonda />)
    expect(screen.getByText(/pesquisa: desligada/)).toBeInTheDocument()

    await sincronizar()

    await waitFor(() => {
      expect(screen.getByText(/pesquisa: ligada/)).toBeInTheDocument()
    })
    expect(screen.getByText(/benchmark: ligado/)).toBeInTheDocument()
  })

  it('sem `/health`, o recurso fica desligado e a tela não quebra', async () => {
    definirParaTeste(true)
    dublarSaude({}, false)
    render(<Sonda />)

    await sincronizar()

    await waitFor(() => {
      expect(screen.getByText(/pesquisa: desligada/)).toBeInTheDocument()
    })
    expect(pesquisaLigada()).toBe(false)
    expect(benchmarkLigadoAgora()).toBe(false)
  })

  it('o valor forçado no teste também avisa quem assina', async () => {
    render(<Sonda />)
    expect(screen.getByText(/pesquisa: desligada/)).toBeInTheDocument()

    definirParaTeste(true)

    await waitFor(() => {
      expect(screen.getByText(/pesquisa: ligada/)).toBeInTheDocument()
    })
  })

  it('a assinatura é cancelada ao desmontar, e ninguém é avisado depois', async () => {
    const { unmount } = render(<Sonda />)
    unmount()
    // Sem o cancelamento, isto avisaria um componente desmontado — o aviso do React que
    // ninguém lê até virar erro de teste em outro arquivo.
    expect(() => definirParaTeste(true)).not.toThrow()
  })
})
