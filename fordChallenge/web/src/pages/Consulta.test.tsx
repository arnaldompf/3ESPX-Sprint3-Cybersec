/** A Consulta como porta única: banco primeiro, pesquisa automática quando faltar. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { Consulta } from './Consulta'
import { limpar } from '@/lib/conversa'
import { definirParaTeste } from '@/lib/pesquisa'
import type { Campo, Ficha, Grupo, Identificacao } from '@/lib/tipos'

function campo(value: unknown, unit: string | null = null): Campo {
  return {
    value,
    unit,
    status: 'verificado',
    confidence: 0.9,
    evidences: [
      {
        evidence_id: 'e1',
        source_url: 'https://fabricante.example/ficha',
        tier: 1,
        quote: 'trecho literal',
        captured_at: '2026-09-05T10:00:00Z',
      },
    ],
    conflicts: [],
    sources_checked: [],
  }
}

function ficha(): Ficha {
  const grupos: Record<Grupo, Record<string, Campo>> = {
    identificacao: {},
    motorizacao: {},
    transmissao: {},
    tracao: {},
    chassi: {},
    desempenho: {},
    modos: {},
    exterior: {},
    dimensoes: {},
    seguranca: {},
    comercial: {},
  }
  return {
    ...grupos,
    motorizacao: { potencia_cv: campo(204, 'cv'), torque_nm: campo(470, 'N·m') },
    extras: {},
    schema_version: '1',
    meta: {
      generated_at: '2026-09-14T00:00:00Z',
      job_id: 'j1',
      version_resolution: { status: 'encontrada', alternatives: [] },
      sources_checked: [],
    },
  }
}

function identificacao(extra: Partial<Identificacao> = {}): Identificacao {
  return {
    texto: 'Ranger Raptor',
    estado: 'resolvido',
    marca: 'Ford',
    modelo: 'Ranger',
    versao: 'Raptor',
    ano: 2026,
    ano_origem: 'catalogo',
    nome: 'Ford Ranger Raptor',
    pergunta: '',
    opcoes: [],
    origem: 'catalogo',
    consultas: [],
    fontes: [],
    motivo: '',
    uso: {},
    no_catalogo: {
      version_id: 'v-1',
      ano_modelo: 2026,
      tem_ficha: true,
      campos_com_valor: 2,
      coletado_em: '2026-09-05T10:00:00Z',
    },
    gasto_rodada: {},
    ...extra,
  }
}

function dublarApi(ident: Identificacao) {
  const chamadas: Array<{ url: string; metodo: string }> = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const metodo = init?.method ?? 'GET'
      chamadas.push({ url, metodo })
      let corpo: unknown = []
      let status = 200
      if (url.endsWith('/research/identify')) corpo = ident
      else if (url.endsWith('/research') && metodo === 'POST') {
        corpo = { run_id: 'run-1', job_id: 'job-1', status: 'pendente', events_url: '' }
        status = 202
      } else if (url.endsWith('/research/run-1/events')) {
        corpo = {
          run_id: 'run-1',
          status: 'concluida',
          veiculo: `${ident.marca} ${ident.modelo} ${ident.versao}`,
          motivo_da_parada: 'cobertura',
          campos_com_valor: 2,
          campos_alvo: 54,
          paginas: 2,
          rodadas: 1,
          segundos: 8,
          version_id: 'v-nova',
          erro: null,
          eventos: [
            {
              ordem: 1,
              tipo: 'fim',
              texto: 'Pesquisa concluída.',
              etiqueta: 'FATO',
              rodada: 1,
              decorrido: 8,
              dados: { motivo: 'cobertura', cobertura: { total: 54, com_valor: 2 } },
            },
          ],
        }
      } else if (/\/vehicles\/[^/]+\/specs/.test(url)) corpo = ficha()
      return new Response(JSON.stringify(corpo), {
        status,
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
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Consulta intervaloMs={5} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function consultar(texto: string) {
  await userEvent.type(screen.getByTestId('pesquisa-caixa'), `${texto}{Enter}`)
}

beforeEach(() => definirParaTeste(true))
afterEach(() => {
  vi.unstubAllGlobals()
  definirParaTeste(false)
  limpar()
})

it('veículo existente carrega dados do banco e oferece atualizar', async () => {
  const chamadas = dublarApi(identificacao())
  montar()
  await consultar('Ranger Raptor')

  expect(await screen.findByTestId('ja-temos')).toHaveTextContent('Já temos a ficha')
  expect(await screen.findByTestId('dados-do-catalogo')).toHaveTextContent('204 cv')
  expect(screen.getByTestId('pesquisar-de-novo')).toBeEnabled()
  expect(chamadas.filter((c) => c.metodo === 'POST' && c.url.endsWith('/research'))).toHaveLength(0)
})

it('veículo sem ficha inicia pesquisa automaticamente, persiste e mostra o resultado', async () => {
  const chamadas = dublarApi(
    identificacao({
      texto: 'Mitsubishi Triton HPE-S',
      marca: 'Mitsubishi',
      modelo: 'Triton',
      versao: 'HPE-S',
      nome: 'Mitsubishi Triton HPE-S',
      origem: 'busca',
      no_catalogo: null,
    }),
  )
  montar()
  await consultar('Triton HPE-S')

  await waitFor(() =>
    expect(chamadas.filter((c) => c.metodo === 'POST' && c.url.endsWith('/research'))).toHaveLength(1),
  )
  expect(await screen.findByTestId('cartao-da-ficha', {}, { timeout: 3000 })).toHaveTextContent(
    'Pesquisa concluída',
  )
  expect(screen.getByTestId('abrir-ficha')).toHaveAttribute('href', '/ficha/v-nova')
})

it('os atalhos são consultas prontas, não uma segunda funcionalidade', async () => {
  const chamadas = dublarApi(identificacao())
  montar()
  const atalho = screen.getByTestId('atalhos-da-consulta').querySelector('button')
  expect(atalho).not.toBeNull()
  await userEvent.click(atalho!)
  await waitFor(() =>
    expect(chamadas.some((c) => c.metodo === 'POST' && c.url.endsWith('/research/identify'))).toBe(true),
  )
})
