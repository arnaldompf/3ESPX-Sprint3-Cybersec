/**
 * O Benchmark: da versão Ford ao conjunto de concorrentes que vale comparar.
 *
 * A tela propõe e **não decide**: quem confirma quem entra é quem vende. Por isso os
 * testes aqui não medem só "renderizou" — medem as promessas que o produto faz:
 *
 * * a lista chega inteira, com a Toro por último e **dita** como carro de outra categoria;
 * * comparabilidade aparece como `k/n`, nunca como porcentagem;
 * * quem não tem cópia no ano-modelo mostra o porquê e o caminho para resolver;
 * * os quatro contadores somam as colunas, e **"não sabemos" tem o mesmo tamanho dos
 *   outros três** — rebaixá-lo faria a comparação parecer mais completa do que é;
 * * sem lista escrita, a tela não inventa concorrente: mostra a busca a fazer.
 *
 * A rede é dublada (`fetch`): o portão não depende de servidor de pé.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Benchmark } from './Benchmark'
import { definirBenchmarkParaTeste } from '@/lib/pesquisa'
import { ORDEM_DOS_ESTADOS } from '@/components/Paridade'
import type {
  CandidatoDoBenchmark,
  ComparabilidadeDoCandidato,
  Paridade,
  PropostaDeBenchmark,
  Veiculo,
} from '@/lib/tipos'

const VEICULOS: Veiculo[] = [
  {
    id: 'ford-limited',
    marca: 'Ford',
    modelo: 'Ranger',
    versao: 'Limited 3.0 V6 Diesel 4WD AT',
    ano_modelo: 2027,
    in_lineup: true,
  },
  {
    id: 'toyota-srx',
    marca: 'Toyota',
    modelo: 'Hilux',
    versao: 'SRX Plus AT',
    ano_modelo: 2027,
    in_lineup: true,
  },
]

function comparabilidade(
  atendidos: number,
  avaliaveis: number,
  comparavel: boolean,
  aviso = '',
): ComparabilidadeDoCandidato {
  return {
    comparavel,
    criterios_atendidos: atendidos,
    criterios_avaliaveis: avaliaveis,
    total_de_criterios: 7,
    resumo: `${atendidos}/${avaliaveis} critérios atendidos`,
    nao_atendidos: comparavel ? [] : ['faixa de preço'],
    sem_dados: [],
    detalhes: [],
    aviso,
    versao_dos_criterios: '2026-09-13',
  }
}

function candidato(extra: Partial<CandidatoDoBenchmark>): CandidatoDoBenchmark {
  return {
    marca: '',
    modelo: '',
    rotulo_do_modelo: '',
    categoria_diferente: false,
    motivo_da_categoria: '',
    no_catalogo: false,
    version_id: null,
    rotulo: null,
    ano_modelo: null,
    comparabilidade: null,
    precisa_pesquisa: false,
    motivo_da_pesquisa: '',
    ...extra,
  }
}

function semCopia(marca: string, modelo: string): CandidatoDoBenchmark {
  return candidato({
    marca,
    modelo,
    rotulo_do_modelo: `${marca} ${modelo}`,
    precisa_pesquisa: true,
    motivo_da_pesquisa: `nenhuma versão de ${marca} ${modelo} no ano-modelo 2027 está no catálogo`,
  })
}

/** Os sete concorrentes da Ranger, na ordem da lista escrita. */
function propostaDaRanger(): PropostaDeBenchmark {
  return {
    ford: {
      version_id: 'ford-limited',
      marca: 'Ford',
      modelo: 'Ranger',
      versao: 'Limited 3.0 V6 Diesel 4WD AT',
      ano_modelo: 2027,
      rotulo: 'Ford Ranger Limited 3.0 V6 Diesel 4WD AT',
    },
    segmento: {
      id: 'picape_media',
      rotulo: 'picape média',
      descricao: 'Cabine dupla, diesel de 2,0 a 3,0 litros e uso misto entre trabalho e família.',
      origem: 'mapa',
    },
    versao_do_mapa: '2026-09-13',
    candidatos: [
      candidato({
        marca: 'Toyota',
        modelo: 'Hilux',
        rotulo_do_modelo: 'Toyota Hilux',
        no_catalogo: true,
        version_id: 'toyota-srx',
        rotulo: 'Toyota Hilux SRX Plus AT',
        ano_modelo: 2027,
        comparabilidade: comparabilidade(6, 6, true),
      }),
      candidato({
        marca: 'Volkswagen',
        modelo: 'Amarok',
        rotulo_do_modelo: 'Volkswagen Amarok',
        no_catalogo: true,
        version_id: 'vw-extreme',
        rotulo: 'Volkswagen Amarok V6 Extreme',
        ano_modelo: 2027,
        comparabilidade: comparabilidade(5, 5, true),
      }),
      candidato({
        marca: 'Chevrolet',
        modelo: 'S10',
        rotulo_do_modelo: 'Chevrolet S10',
        no_catalogo: true,
        version_id: 'chevrolet-high',
        rotulo: 'Chevrolet S10 High Country',
        ano_modelo: 2027,
        comparabilidade: comparabilidade(
          4,
          6,
          false,
          'faixa de preço distante: a comparação sai enviesada a favor do carro mais caro.',
        ),
      }),
      semCopia('RAM', 'Rampage'),
      semCopia('Mitsubishi', 'Triton'),
      semCopia('Nissan', 'Frontier'),
      candidato({
        marca: 'Fiat',
        modelo: 'Toro',
        rotulo_do_modelo: 'Fiat Toro',
        categoria_diferente: true,
        motivo_da_categoria:
          'A Toro é monobloco e de porte menor, e entra porque aparece na conversa do salão.',
        precisa_pesquisa: true,
        motivo_da_pesquisa: 'nenhuma versão de Fiat Toro no ano-modelo 2027 está no catálogo',
      }),
    ],
    prontos: 3,
    a_pesquisar: 4,
    consulta_de_descoberta: null,
    aviso: '4 de 7 concorrentes não têm versão no ano-modelo 2027 no catálogo.',
  }
}

function propostaSemSegmento(): PropostaDeBenchmark {
  return {
    ...propostaDaRanger(),
    segmento: { id: '', rotulo: '', descricao: '', origem: 'desconhecido' },
    candidatos: [],
    prontos: 0,
    a_pesquisar: 0,
    consulta_de_descoberta: 'concorrentes da Ford Maverick 2027 ficha técnica',
    aviso: 'O segmento da Maverick não está na lista escrita.',
  }
}

function coluna(
  version_id: string,
  rotulo: string,
  contagem: { vantagem: number; paridade: number; gap: number; desconhecido: number },
  comparavel = true,
  aviso = '',
) {
  return {
    version_id,
    rotulo,
    celulas: [
      {
        campo: 'preco_sugerido_brl',
        grupo: 'comercial',
        estado: 'vantagem' as const,
        valor_ford: 379990,
        valor_concorrente: 410990,
        unidade: 'BRL',
        motivo: 'preço menor',
        motivo_tipo: 'comparado',
      },
    ],
    contagem: {
      ...contagem,
      total: 58,
      comparados: contagem.vantagem + contagem.paridade + contagem.gap,
    },
    comparabilidade: {
      version_id,
      rotulo,
      ...comparabilidade(comparavel ? 6 : 4, 6, comparavel, aviso),
    },
    flag_de_carga: { aplicavel: false, texto: '', etiqueta: '', motivo: 'sem valor de carga' },
  }
}

function paridadeDeDuasColunas(): Paridade {
  return {
    ford_version: 'ford-limited',
    ford_rotulo: 'Ford Ranger Limited 3.0 V6 Diesel 4WD AT',
    colunas: [
      coluna('toyota-srx', 'Toyota Hilux SRX Plus AT', {
        vantagem: 12,
        paridade: 20,
        gap: 9,
        desconhecido: 8,
      }),
      coluna(
        'vw-extreme',
        'Volkswagen Amarok V6 Extreme',
        { vantagem: 9, paridade: 14, gap: 6, desconhecido: 9 },
        false,
        'faixa de preço distante: leia a coluna com ressalva.',
      ),
    ],
    legenda: {
      vantagem: 'a Ford leva',
      paridade: 'empate',
      gap: 'o concorrente leva',
      desconhecido: 'falta dado de um dos lados',
    },
    flag_de_carga_ford: { aplicavel: false, texto: '', etiqueta: '', motivo: 'sem valor de carga' },
    versao_dos_criterios: '2026-09-13',
  } as Paridade
}

function resposta(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function dublarApi(proposta: PropostaDeBenchmark, paridade?: Paridade) {
  const chamadas: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      chamadas.push(url)
      if (url.includes('/benchmark/proposta')) return resposta(proposta)
      if (url.includes('/parity')) return resposta(paridade ?? paridadeDeDuasColunas())
      if (url.includes('/vehicles')) return resposta(VEICULOS)
      return resposta([])
    }),
  )
  return chamadas
}

/** Sem a capacidade ligada no servidor, a rota não existe: 404. */
function dublarDesligado() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/benchmark/proposta')) {
        return resposta({ title: 'Não encontrado', detail: 'Not Found' }, 404)
      }
      if (url.includes('/vehicles')) return resposta(VEICULOS)
      return resposta([])
    }),
  )
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Benchmark />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function itens() {
  return within(screen.getByTestId('conjunto-proposto')).getAllByRole('listitem')
}

beforeEach(() => {
  // A tela só chama a rota com a bandeira ligada — ela é lida **antes** da chamada, para
  // não gerar 404 (e erro de console) em ambiente sem o Benchmark montado.
  definirBenchmarkParaTeste(true)
})

afterEach(() => {
  vi.unstubAllGlobals()
  definirBenchmarkParaTeste(false)
})

describe('benchmark: o conjunto proposto', () => {
  it('com a bandeira desligada, nao chama a rota — e por isso nao gera erro de console', async () => {
    // O defeito que este teste fecha: a tela tratava o 404 com elegancia, mas **fazia a
    // chamada**. O navegador registra um erro de console a cada visita, e erro de console
    // e indistinguivel de defeito para quem esta olhando. O `qa/e2e` reprovou por isso.
    definirBenchmarkParaTeste(false)
    const chamadas = dublarApi(propostaDaRanger())
    montar()
    await screen.findByTestId('benchmark-desligado')
    expect(chamadas.filter((u) => u.includes('/benchmark/'))).toEqual([])
  })

  it('lista os sete concorrentes da Ranger, com a Toro por último e dita como outra categoria', async () => {
    dublarApi(propostaDaRanger())
    montar()

    await screen.findByTestId('conjunto-proposto')
    const lista = itens()
    expect(lista).toHaveLength(7)
    expect(lista[0]).toHaveTextContent('Toyota Hilux')

    const ultimo = lista[6]!
    expect(ultimo).toHaveTextContent('Fiat Toro')
    expect(ultimo).toHaveTextContent('outra categoria')
    expect(ultimo).toHaveTextContent('monobloco')
  })

  it('vem marcado o que já dá para comparar; o resto fica à sua escolha', async () => {
    dublarApi(propostaDaRanger())
    montar()

    await screen.findByTestId('conjunto-proposto')
    const [hilux, amarok, s10, rampage] = itens()
    expect(within(hilux!).getByRole('checkbox')).toBeChecked()
    expect(within(amarok!).getByRole('checkbox')).toBeChecked()
    // Incomparável e sem cópia entram desmarcados — mas continuam selecionáveis.
    expect(within(s10!).getByRole('checkbox')).not.toBeChecked()
    expect(within(rampage!).getByRole('checkbox')).not.toBeChecked()
    expect(within(rampage!).getByRole('checkbox')).toBeEnabled()
  })

  it('mostra k de n critérios, e nunca porcentagem', async () => {
    dublarApi(propostaDaRanger())
    montar()

    const lista = await screen.findByTestId('conjunto-proposto')
    expect(lista).toHaveTextContent('6/6 critérios')
    expect(lista).toHaveTextContent('4/6 critérios')
    expect(lista).toHaveTextContent('faixa de preço distante')
    expect(document.body.textContent ?? '').not.toContain('%')
  })

  it('quem não tem cópia do ano-modelo diz o porquê e oferece a busca', async () => {
    dublarApi(propostaDaRanger())
    montar()

    await screen.findByTestId('conjunto-proposto')
    const rampage = itens()[3]!
    expect(rampage).toHaveTextContent('no ano-modelo 2027 está no catálogo')
    expect(within(rampage).getByRole('button', { name: /pesquisar/i })).toBeEnabled()
  })

  it('sem lista escrita, a tela não inventa concorrente: mostra a busca a fazer', async () => {
    dublarApi(propostaSemSegmento())
    montar()

    const cartao = await screen.findByTestId('segmento-desconhecido')
    expect(screen.queryByTestId('conjunto-proposto')).toBeNull()
    expect(cartao).toHaveTextContent('não está na lista escrita')
    expect(screen.getByTestId('consulta-de-descoberta')).toHaveTextContent(
      'concorrentes da Ford Maverick 2027 ficha técnica',
    )
    expect(screen.getByRole('button', { name: /pesquisar/i })).toBeEnabled()
  })

  it('sem a capacidade ligada no servidor, a tela explica em vez de dar erro', async () => {
    dublarDesligado()
    montar()

    const aviso = await screen.findByTestId('benchmark-desligado')
    expect(aviso).toHaveTextContent('não está ligado neste ambiente')
    expect(screen.queryByTestId('conjunto-proposto')).toBeNull()
  })
})

describe('benchmark: a comparação', () => {
  async function comparar() {
    const chamadas = dublarApi(propostaDaRanger())
    montar()
    await screen.findByTestId('conjunto-proposto')
    await userEvent.click(screen.getByTestId('comparar'))
    await screen.findByTestId('matriz-do-benchmark')
    return chamadas
  }

  it('compara só quem você confirmou', async () => {
    const chamadas = await comparar()
    const pedido = decodeURIComponent(chamadas.find((u) => u.includes('/parity')) ?? '')
    expect(pedido).toContain('competitors=toyota-srx,vw-extreme')
    expect(pedido).not.toContain('chevrolet-high')
  })

  it('os quatro cartões somam as contagens de todas as colunas', async () => {
    await comparar()
    expect(screen.getByTestId('resumo-vantagem')).toHaveTextContent('21')
    expect(screen.getByTestId('resumo-paridade')).toHaveTextContent('34')
    expect(screen.getByTestId('resumo-gap')).toHaveTextContent('15')
    expect(screen.getByTestId('resumo-desconhecido')).toHaveTextContent('17')
  })

  it('"não sabemos" tem o mesmo destaque dos outros três', async () => {
    await comparar()
    const cartoes = ORDEM_DOS_ESTADOS.map((estado) => screen.getByTestId(`resumo-${estado}`))
    expect(new Set(cartoes.map((c) => c.className)).size).toBe(1)
    const numeros = cartoes.map((c) => c.querySelectorAll('p')[1]?.className)
    expect(new Set(numeros).size).toBe(1)
  })

  it('a coluna reprovada leva o aviso à vista, e não escondido', async () => {
    await comparar()
    const avisos = await screen.findByTestId('avisos-de-comparabilidade')
    expect(avisos).toHaveTextContent('Volkswagen Amarok V6 Extreme')
    expect(avisos).toHaveTextContent('leia a coluna com ressalva')
  })
})
