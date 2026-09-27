/**
 * A tela Pesquisa — a conversa guiada da WP-42, com o servidor dublado.
 *
 * Os casos são os da spec: escolher entre versões pelos chips (com o domínio da fonte),
 * confirmar o ano assumido (INFERÊNCIA) e ver a pesquisa até o cartão da ficha, receber
 * "já temos" sem disparar pesquisa, o "não entendi", a cota que acaba e para a conversa,
 * e o vendedor que vê a recusa.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Conversa } from './Conversa'
import { CHAVE_DA_CONVERSA, limpar, type EstadoDaConversa } from '@/lib/conversa'
import { definirPapel } from '@/lib/papel'
import { definirParaTeste } from '@/lib/pesquisa'
import {
  GRUPOS,
  type Campo,
  type EventoDePesquisa,
  type Ficha,
  type Identificacao,
  type OpcaoDeVeiculo,
  type TrilhaDePesquisa,
} from '@/lib/tipos'

/* ------------------------------------------------------------------ fixtures */

function identificacao(extra: Partial<Identificacao> = {}): Identificacao {
  return {
    texto: 'Triton',
    estado: 'resolvido',
    marca: 'Mitsubishi',
    modelo: 'Triton',
    versao: 'HPE-S',
    ano: 2026,
    ano_origem: 'vigente',
    nome: 'Mitsubishi Triton HPE-S',
    pergunta: '',
    opcoes: [],
    origem: 'busca',
    consultas: [],
    fontes: ['https://www.mitsubishimotors.com.br/triton'],
    motivo: '',
    uso: {},
    no_catalogo: null,
    gasto_rodada: {},
    ...extra,
  }
}

function opcao(valor: string, fonte: string, extra: Partial<OpcaoDeVeiculo> = {}): OpcaoDeVeiculo {
  return {
    valor,
    detalhe: '2.4 diesel 4x4 AT',
    fontes: [fonte],
    tipo: 'versao',
    marca: 'Mitsubishi',
    modelo: 'Triton',
    ano: null,
    ...extra,
  }
}

function evento(
  ordem: number,
  tipo: string,
  dados: Record<string, unknown> = {},
  texto = `evento ${tipo}`,
): EventoDePesquisa {
  return { ordem, tipo, texto, etiqueta: 'FATO', rodada: 1, decorrido: ordem * 2, dados }
}

const PASSOS = [
  evento(1, 'inicio', { veiculo: 'Mitsubishi Triton HPE-S' }),
  evento(2, 'consulta', { consulta: 'ficha técnica Triton HPE-S', tier: 1 }),
  evento(3, 'resultados', { quantos: 5 }),
  evento(4, 'fonte_escolhida', {
    url: 'https://www.mitsubishimotors.com.br/triton/hpe-s',
    dominio: 'mitsubishimotors.com.br',
    tier: 1,
    motivo: 'site oficial',
  }),
  evento(5, 'baixada', { url: 'https://www.mitsubishimotors.com.br/triton/hpe-s', caracteres: 9000 }),
]

function fim(motivo: string, texto: string): EventoDePesquisa {
  return evento(6, 'fim', { motivo, cobertura: { total: 40, com_valor: 9 }, bloqueadas: 0 }, texto)
}

function trilha(eventos: EventoDePesquisa[], extra: Partial<TrilhaDePesquisa> = {}): TrilhaDePesquisa {
  return {
    run_id: 'run-1',
    status: 'rodando',
    veiculo: 'Mitsubishi Triton HPE-S',
    motivo_da_parada: '',
    campos_com_valor: 9,
    campos_alvo: 40,
    paginas: 1,
    rodadas: 1,
    segundos: 12,
    version_id: null,
    erro: null,
    eventos,
    ...extra,
  }
}

function campo(value: unknown, unit: string | null = null): Campo {
  return {
    value,
    unit,
    status: 'verificado',
    confidence: 0.9,
    evidences: [
      {
        evidence_id: 'e1',
        source_url: 'https://www.mitsubishimotors.com.br/triton/hpe-s',
        tier: 1,
        quote: 'trecho',
        captured_at: '2026-09-05T10:00:00Z',
      },
    ],
    conflicts: [],
    sources_checked: [],
  }
}

function ficha(): Ficha {
  const base = Object.fromEntries(GRUPOS.map((g) => [g, {}])) as Record<
    (typeof GRUPOS)[number],
    Record<string, Campo>
  >
  return {
    ...base,
    motorizacao: { potencia_cv: campo(204, 'cv'), torque_nm: campo(470, 'N·m') },
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

/* ------------------------------------------------------------------ o servidor dublado */

interface Chamada {
  url: string
  metodo: string
  corpo?: unknown
}

interface Rotas {
  identify?: Identificacao | Identificacao[]
  eventos?: TrilhaDePesquisa[]
  ficha?: Ficha
}

/**
 * Responde por rota. `identify` e `eventos` aceitam **sequências**: cada chamada avança
 * uma posição e a última fica repetindo — é assim que a tela vê a trilha crescer.
 */
function dublarApi(rotas: Rotas) {
  const chamadas: Chamada[] = []
  let identificacoes = 0
  let consultas = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const metodo = init?.method ?? 'GET'
      const corpo = init?.body ? JSON.parse(String(init.body)) : undefined
      chamadas.push({ url, metodo, corpo })
      let resposta: unknown = {}
      let status = 200
      if (url.endsWith('/research/identify')) {
        const lista = [rotas.identify ?? identificacao()].flat()
        resposta = lista[Math.min(identificacoes, lista.length - 1)]
        identificacoes += 1
      } else if (url.endsWith('/research') && metodo === 'POST') {
        resposta = { run_id: 'run-1', job_id: 'job-1', status: 'aceita', events_url: '' }
        status = 202
      } else if (url.endsWith('/continue') && metodo === 'POST') {
        resposta = { run_id: 'run-2', job_id: 'job-2', status: 'pendente', events_url: '' }
        status = 202
      } else if (/\/research\/[^/]+\/events$/.test(url)) {
        const lista = rotas.eventos ?? [trilha([fim('cobertura', 'Parou por cobertura.')], { status: 'concluida' })]
        resposta = lista[Math.min(consultas, lista.length - 1)]
        consultas += 1
      } else if (/\/vehicles\/[^/]+\/specs/.test(url)) {
        resposta = rotas.ficha ?? ficha()
      }
      return new Response(JSON.stringify(resposta), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return chamadas
}

function montar(aoFichaGravada?: (versionId: string) => void) {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Conversa intervaloMs={5} aoFichaGravada={aoFichaGravada} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function dizer(texto: string) {
  await userEvent.type(screen.getByTestId('pesquisa-caixa'), texto)
  await userEvent.click(screen.getByTestId('pesquisa-enviar'))
}

const posts = (chamadas: Chamada[], sufixo: string) =>
  chamadas.filter((c) => c.metodo === 'POST' && c.url.endsWith(sufixo))

beforeEach(() => {
  definirParaTeste(true)
})

afterEach(() => {
  vi.unstubAllGlobals()
  definirParaTeste(false)
  limpar()
})

/* ------------------------------------------------------------------ os casos */

describe('pesquisa: a conversa guiada', () => {
  it('continua na mesma conversa e avisa outra gravação da mesma versão', async () => {
    const concluida = trilha([fim('rodadas', 'Limite de rodadas.')], {
      status: 'concluida', version_id: 'v-1', continuacao_disponivel: true,
    })
    const chamadas = dublarApi({ eventos: [
      concluida,
      { ...concluida, run_id: 'run-2', continuacao_disponivel: false },
    ] })
    const avisar = vi.fn()
    montar(avisar)
    await dizer('Triton HPE-S 2026')
    const botao = await screen.findByRole('button', { name: 'continuar pesquisa em segundo plano' })
    await waitFor(() => expect(avisar).toHaveBeenCalledTimes(1))
    expect(screen.getByText(/Limite total de 15 minutos/)).toBeInTheDocument()
    await userEvent.click(botao)
    await waitFor(() => expect(avisar).toHaveBeenCalledTimes(2))
    expect(avisar).toHaveBeenLastCalledWith('v-1')
    expect(posts(chamadas, '/continue')[0]?.corpo).toEqual({ segundos: 900, rodadas: 5, paginas: 40 })
    expect(posts(chamadas, '/research')).toHaveLength(1)
  })

  it('(a) versão ambígua vira chips com o domínio da fonte, e o clique refaz a identificação', async () => {
    const chamadas = dublarApi({
      identify: [
        identificacao({
          estado: 'precisa_escolher',
          versao: '',
          pergunta: 'Qual versão da Triton?',
          opcoes: [
            opcao('HPE-S', 'https://www.mitsubishimotors.com.br/triton/hpe-s'),
            opcao('Sport', 'https://quatrorodas.abril.com.br/triton-sport'),
          ],
        }),
        identificacao({ ano_origem: 'fontes' }),
      ],
    })
    montar()
    await dizer('Triton')

    // O que a pessoa disse aparece, com hora.
    expect(screen.getByTestId('mensagem-texto')).toHaveTextContent('Triton')
    expect(screen.getAllByTestId('hora-da-mensagem')[0]).toHaveTextContent(/^\d{2}:\d{2}:\d{2}$/)

    const chips = await screen.findAllByTestId('opcao')
    expect(chips).toHaveLength(2)
    expect(chips[0]).toHaveTextContent('HPE-S')
    expect(chips[0]).toHaveTextContent('mitsubishimotors.com.br')
    expect(chips[1]).toHaveTextContent('quatrorodas.abril.com.br')
    expect(screen.getByTestId('precisa-escolher')).toHaveTextContent('Qual versão da Triton?')

    await userEvent.click(chips[0]!)

    await waitFor(() => expect(posts(chamadas, '/research/identify')).toHaveLength(2))
    expect(posts(chamadas, '/research/identify')[1]!.corpo).toEqual({ texto: 'Mitsubishi Triton HPE-S' })
    await waitFor(() => expect(posts(chamadas, '/research')).toHaveLength(1))
    // A escolha ficou registrada, mas os chips antigos não clicam mais.
    expect(screen.getAllByTestId('opcao')[0]).toBeDisabled()
  })

  it('(b) veículo sem ficha dispara o run automaticamente, acompanha e mostra a ficha', async () => {
    const chamadas = dublarApi({
      identify: identificacao({ ano_origem: 'vigente' }),
      eventos: [
        trilha(PASSOS.slice(0, 2)),
        trilha(PASSOS),
        trilha([...PASSOS, fim('cobertura', 'Parou por cobertura: 9 de 40 campos.')], {
          status: 'concluida',
          version_id: 'v-1',
        }),
      ],
    })
    montar()
    await userEvent.type(screen.getByTestId('pesquisa-caixa'), 'Triton{Enter}')

    const confirmacao = await screen.findByTestId('confirmacao')
    expect(confirmacao).toHaveTextContent('Entendi: Mitsubishi Triton HPE-S, ano-modelo 2026')
    const badge = within(confirmacao).getByTestId('badge-INFERENCIA')
    expect(badge).toHaveAttribute('title', 'ano vigente assumido; você pode trocar')

    await waitFor(() => expect(posts(chamadas, '/research')).toHaveLength(1))
    expect(posts(chamadas, '/research')[0]!.corpo).toEqual({
      marca: 'Mitsubishi',
      modelo: 'Triton',
      versao: 'HPE-S',
      ano: 2026,
    })

    const cartao = await screen.findByTestId('cartao-da-ficha', {}, { timeout: 4000 })
    expect(cartao).toHaveTextContent('Parou por cobertura: 9 de 40 campos.')
    expect(screen.getByTestId('resumo-da-ficha')).toHaveTextContent('9 de 40 campos com prova')
    expect(screen.getByTestId('abrir-ficha')).toHaveAttribute('href', '/ficha/v-1')
    expect(screen.getByTestId('comparar-com')).toHaveAttribute('href', '/matriz')
    await screen.findByText('fontes coletadas em 05/09/2026')

    // A trilha continua na conversa, recolhida, e a caixa volta a aceitar texto.
    expect(screen.getByTestId('trilha-ao-vivo')).toHaveAttribute('data-rodando', 'nao')
    expect(screen.getByTestId('trilha-ao-vivo')).toHaveTextContent('Concluída · 6 passos')
    expect(screen.getByTestId('pesquisa-caixa')).toBeEnabled()
    // O servidor foi consultado mais de uma vez: a trilha veio crescendo.
    expect(chamadas.filter((c) => /\/events$/.test(c.url)).length).toBeGreaterThanOrEqual(3)
  })

  it('(c) já temos a ficha: diz a data da coleta e oferece abrir, sem disparar pesquisa', async () => {
    const chamadas = dublarApi({
      identify: identificacao({
        marca: 'Ford',
        modelo: 'Ranger',
        versao: 'Raptor',
        nome: 'Ford Ranger Raptor',
        ano_origem: 'catalogo',
        origem: 'catalogo',
        fontes: [],
        no_catalogo: {
          version_id: 'v-9',
          ano_modelo: 2026,
          tem_ficha: true,
          campos_com_valor: 31,
          coletado_em: '2026-09-05T10:00:00Z',
        },
      }),
    })
    montar()
    await dizer('Ranger Raptor')

    const jaTemos = await screen.findByTestId('ja-temos')
    expect(jaTemos).toHaveTextContent('Já temos a ficha de Ford Ranger Raptor (2026). Dados coletados em 05/09/2026.')
    expect(screen.getByTestId('abrir-ficha')).toHaveAttribute('href', '/ficha/v-9')
    expect(screen.getByTestId('pesquisar-de-novo')).toBeEnabled()
    expect(await screen.findByTestId('dados-do-catalogo')).toHaveTextContent('Potência')
    expect(posts(chamadas, '/research')).toHaveLength(0)

    await userEvent.click(screen.getByTestId('pesquisar-de-novo'))
    await waitFor(() => expect(posts(chamadas, '/research')).toHaveLength(1))
  })

  it('(d) não entendi: o motivo aparece em português e a caixa continua livre', async () => {
    dublarApi({
      identify: identificacao({ estado: 'nao_entendi', motivo: 'não achei marca nem modelo no texto' }),
    })
    montar()
    await dizer('aquele carro')

    const aviso = await screen.findByTestId('nao-entendi')
    expect(aviso).toHaveTextContent('não achei marca nem modelo no texto')
    expect(screen.getByTestId('pesquisa-caixa')).toBeEnabled()
  })

  it('(e) fim por modelo_sem_saldo repete o aviso em destaque e para a conversa', async () => {
    dublarApi({
      identify: identificacao({ ano_origem: 'pedido' }),
      eventos: [
        trilha([...PASSOS, fim('modelo_sem_saldo', 'A cota do modelo acabou; a ficha saiu só com o que a regra leu.')], {
          status: 'concluida',
          version_id: 'v-1',
        }),
      ],
    })
    montar()
    await dizer('Triton 2026')

    const destaque = await screen.findByTestId('aviso-em-destaque', {}, { timeout: 4000 })
    expect(destaque).toHaveTextContent('A cota do modelo acabou')
    expect(screen.getByTestId('pesquisa-caixa')).toBeDisabled()
    expect(screen.getByTestId('aviso-de-cota')).toHaveTextContent('a cota do modelo acabou')
    // A ficha que saiu com o que a regra leu continua oferecida.
    expect(screen.getByTestId('cartao-da-ficha')).toBeInTheDocument()
  })

  it('(f) o vendedor usa a mesma Consulta', () => {
    dublarApi({})
    definirPapel('vendedor')
    montar()

    expect(screen.getByTestId('pesquisa-caixa')).toBeEnabled()
  })

  it('erro do servidor na identificação vira frase em português, e a caixa volta', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ type: 'about:blank', title: 'Erro', status: 502, detail: 'o buscador não respondeu', instance: '/x' }),
            { status: 502, headers: { 'Content-Type': 'application/problem+json' } },
          ),
      ),
    )
    montar()
    await dizer('Triton')

    const erro = await screen.findByTestId('mensagem-erro')
    expect(erro).toHaveTextContent('Não foi possível identificar o carro: o buscador não respondeu')
    expect(screen.getByTestId('pesquisa-caixa')).toBeEnabled()
  })

  it('com o Pesquisador desligado, o catálogo continua consultável', () => {
    dublarApi({})
    definirParaTeste(false)
    montar()

    expect(screen.getByTestId('pesquisa-desligada')).toHaveTextContent(
      'pesquisa externa está desligada',
    )
    expect(screen.getByTestId('pesquisa-caixa')).toBeEnabled()
  })

  it('um F5 no meio da pesquisa retoma o acompanhamento pelo run_id guardado', async () => {
    dublarApi({
      eventos: [
        trilha([...PASSOS, fim('cobertura', 'Parou por cobertura.')], { run_id: 'run-7', status: 'concluida', version_id: 'v-1' }),
      ],
    })
    const guardado: EstadoDaConversa = {
      fase: 'pesquisando',
      runId: 'run-7',
      mensagens: [
        { id: 'm1', autor: 'voce', hora: '2026-09-13T14:00:00.000Z', tipo: 'texto', texto: 'Triton' },
        { id: 'm2', autor: 'specradar', hora: '2026-09-13T14:00:20.000Z', tipo: 'trilha', runId: 'run-7' },
      ],
    }
    sessionStorage.setItem(CHAVE_DA_CONVERSA, JSON.stringify({ v: 1, estado: guardado }))
    montar()

    expect(screen.getByTestId('mensagem-texto')).toHaveTextContent('Triton')
    await screen.findByTestId('cartao-da-ficha', {}, { timeout: 4000 })
    expect(screen.getByTestId('abrir-ficha')).toHaveAttribute('href', '/ficha/v-1')
  })
})
