/**
 * A tela da matriz de paridade.
 *
 * Os testes que carregam o peso são os três que impedem a tabela de virar um slide de
 * vendas: **o gap sempre visível**, **`desconhecido` com a mesma proeminência dos outros
 * três**, e **o aviso de par não comparável na tela** quando a API o manda.
 *
 * Todo `describe` diz "matriz" porque o verify da WP-32 seleciona por esse nome
 * (`vitest run -t matriz`), como o comando da spec pede.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Matriz } from './Matriz'
import type { CelulaDeParidade, Comparabilidade, Paridade, Veiculo } from '@/lib/tipos'

const VEICULOS: Veiculo[] = [
  {
    id: 'v-raptor',
    marca: 'Ford',
    modelo: 'Ranger',
    versao: 'Raptor 3.0 V6 Bi-turbo 4WD AT',
    ano_modelo: 2026,
    in_lineup: true,
  },
  {
    id: 'v-srx',
    marca: 'Toyota',
    modelo: 'Hilux',
    versao: 'SRX Plus AT',
    ano_modelo: 2026,
    in_lineup: true,
  },
]

function celula(extra: Partial<CelulaDeParidade> = {}): CelulaDeParidade {
  return {
    campo: 'potencia_cv',
    grupo: 'motorizacao',
    estado: 'vantagem',
    valor_ford: 397,
    valor_concorrente: 204,
    unidade: 'cv',
    motivo: '397 contra 204 — quanto maior, melhor',
    motivo_tipo: '',
    diferenca: 193,
    evidence_id_ford: 'e1',
    evidence_id_concorrente: 'e2',
    ...extra,
  }
}

function comparabilidade(extra: Partial<Comparabilidade> = {}): Comparabilidade {
  return {
    version_id: 'v-srx',
    rotulo: 'Toyota Hilux SRX Plus AT',
    comparavel: false,
    criterios_atendidos: 4,
    criterios_avaliaveis: 7,
    total_de_criterios: 7,
    resumo: '4/7 critérios atendidos',
    nao_atendidos: ['combustível', 'faixa de preço', 'finalidade'],
    sem_dados: [],
    detalhes: [
      {
        id: 'combustivel',
        rotulo: 'combustível',
        estado: 'nao_atendido',
        valor_ford: 'gasolina',
        valor_concorrente: 'diesel',
        motivo: 'gasolina contra diesel',
      },
      {
        id: 'segmento',
        rotulo: 'segmento',
        estado: 'atendido',
        valor_ford: 'picape media',
        valor_concorrente: 'picape media',
        motivo: '',
      },
    ],
    aviso:
      'Par não comparável pelos critérios de 2026-09-09: 4/7 atendidos (mínimo 4). ' +
      'Não atendidos: combustível, faixa de preço, finalidade. Combustível diferente é ' +
      'eliminatório. A comparação abaixo continua válida campo a campo, com esta ressalva.',
    versao_dos_criterios: '2026-09-09',
    ...extra,
  }
}

function paridade(extra: Partial<Paridade> = {}): Paridade {
  return {
    ford_version: 'v-raptor',
    ford_rotulo: 'Ford Ranger Raptor 3.0 V6 Bi-turbo 4WD AT',
    colunas: [
      {
        version_id: 'v-srx',
        rotulo: 'Toyota Hilux SRX Plus AT',
        celulas: [
          celula(),
          celula({
            campo: 'preco_sugerido_brl',
            grupo: 'comercial',
            estado: 'gap',
            valor_ford: 499000,
            valor_concorrente: 348790,
            unidade: 'BRL',
            motivo: '499000 contra 348790 — quanto menor, melhor',
          }),
          celula({
            campo: 'torque_nm',
            grupo: 'motorizacao',
            estado: 'paridade',
            valor_ford: 583,
            valor_concorrente: 583,
            unidade: 'Nm',
            motivo: 'diferença dentro da tolerância de ±1',
          }),
          celula({
            campo: 'potencia_rpm',
            grupo: 'motorizacao',
            estado: 'desconhecido',
            valor_ford: 5650,
            valor_concorrente: null,
            unidade: 'rpm',
            motivo: 'o concorrente não tem valor verificado para este campo',
            motivo_tipo: 'sem_dado_concorrente',
            diferenca: null,
          }),
        ],
        contagem: {
          vantagem: 1,
          paridade: 1,
          gap: 1,
          desconhecido: 1,
          total: 4,
          comparados: 3,
        },
        comparabilidade: comparabilidade(),
        flag_de_carga: {
          aplicavel: true,
          valor: true,
          capacidade_kg: 1005,
          texto:
            'Capacidade de carga ≥ 1.000 kg (https://www.toyota.com.br/hilux/ficha.pdf). ' +
            'Critério comumente associado à classificação como veículo de carga; ' +
            'confirmar enquadramento fiscal com a Ford.',
          etiqueta: 'INFERENCIA',
          motivo: '1005 kg ≥ 1000 kg',
        },
      },
    ],
    legenda: {
      vantagem: 'A Ford é melhor neste campo, pelos valores verificados dos dois lados.',
      paridade: 'Empate: a diferença está dentro da tolerância de medição do campo.',
      gap: 'O concorrente é melhor neste campo. Aparece sempre, sem exceção.',
      desconhecido:
        'Não sabemos: falta valor verificado de um dos lados, ou o campo não tem um lado ' +
        'melhor definido. Nunca é exibido como empate.',
    },
    flag_de_carga_ford: {
      aplicavel: false,
      valor: null,
      capacidade_kg: null,
      texto: '',
      etiqueta: 'INFERENCIA',
      motivo:
        'sem valor de capacidade de carga: a regra dos 1.000 kg não é avaliável, e não ' +
        'avaliada é diferente de não atingida',
    },
    versao_dos_criterios: '2026-09-09',
    ...extra,
  }
}

function dublarApi(dados: Paridade = paridade()) {
  const chamadas: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      chamadas.push(url)
      const corpo = url.includes('/vehicles') ? VEICULOS : dados
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
      <Matriz />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('matriz: os quatro estados', () => {
  it('mostra os quatro na tabela, cada um com palavra e símbolo', async () => {
    dublarApi()
    montar()
    await waitFor(() => expect(screen.getByTestId('linha-potencia_cv')).toBeTruthy())
    // Um de cada dentro da tabela, mais um de cada na legenda.
    expect(screen.getAllByTestId('estado-vantagem').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByTestId('estado-gap').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByTestId('estado-paridade').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByTestId('estado-desconhecido').length).toBeGreaterThanOrEqual(2)
  })

  it('matriz: o gap aparece sempre, e não há como escondê-lo', async () => {
    dublarApi()
    montar()
    await waitFor(() => expect(screen.getByTestId('linha-preco_sugerido_brl')).toBeTruthy())
    const linha = screen.getByTestId('linha-preco_sugerido_brl')
    expect(linha.querySelector('[data-testid="estado-gap"]')).toBeTruthy()
    expect(linha.textContent).toContain('perdemos')
    // Nenhum controle da tela filtra por estado: o filtro é por dimensão, e só.
    const seletores = screen.getAllByRole('combobox')
    for (const seletor of seletores) {
      expect(seletor.textContent?.toLowerCase()).not.toContain('perdemos')
      expect(seletor.textContent?.toLowerCase()).not.toContain('vantagens')
    }
  })

  it('matriz: desconhecido é exibido como "não sabemos", nunca como empate', async () => {
    dublarApi()
    montar()
    await waitFor(() => expect(screen.getByTestId('linha-potencia_rpm')).toBeTruthy())
    const linha = screen.getByTestId('linha-potencia_rpm')
    expect(linha.textContent).toContain('não sabemos')
    expect(linha.textContent).not.toContain('empate')
    // E o motivo diz de qual lado falta o dado.
    expect(linha.textContent).toContain('o concorrente não tem valor verificado')
  })

  it('matriz: a legenda diz o que cada estado significa', async () => {
    dublarApi()
    montar()
    const legenda = await screen.findByTestId('legenda')
    expect(legenda.textContent).toContain('Aparece sempre')
    expect(legenda.textContent).toContain('Nunca é exibido como empate')
  })

  it('matriz: o estado não depende só da cor', async () => {
    dublarApi()
    montar()
    await waitFor(() => expect(screen.getByTestId('linha-potencia_cv')).toBeTruthy())
    const selo = screen.getAllByTestId('estado-vantagem')[0]
    // Símbolo (▲) e palavra ("ganhamos") viajam juntos com a cor.
    expect(selo?.textContent).toContain('ganhamos')
    expect(selo?.textContent).toMatch(/[▲=▼?]/)
  })
})

describe('matriz: comparabilidade', () => {
  it('mostra o aviso de par não comparável, com role de alerta', async () => {
    dublarApi()
    montar()
    const aviso = await screen.findByTestId('comparabilidade-v-srx')
    expect(aviso).toHaveAttribute('role', 'alert')
    expect(aviso.textContent).toContain('não comparável')
    expect(aviso.textContent).toContain('combustível')
  })

  it('matriz: o resumo é k/n e nunca porcentagem', async () => {
    dublarApi()
    montar()
    const aviso = await screen.findByTestId('comparabilidade-v-srx')
    expect(aviso.textContent).toContain('4/7 critérios atendidos')
    expect(aviso.textContent).not.toMatch(/\d+%/)
  })

  it('matriz: par comparável não vira alerta na tela', async () => {
    const dados = paridade()
    dados.colunas[0]!.comparabilidade = comparabilidade({
      comparavel: true,
      criterios_atendidos: 7,
      resumo: '7/7 critérios atendidos',
      nao_atendidos: [],
      aviso: '',
    })
    dublarApi(dados)
    montar()
    const aviso = await screen.findByTestId('comparabilidade-v-srx')
    expect(aviso).not.toHaveAttribute('role', 'alert')
    expect(aviso.textContent).toContain('7/7')
  })

  it('matriz: abre o critério por critério', async () => {
    dublarApi()
    montar()
    const aviso = await screen.findByTestId('comparabilidade-v-srx')
    // Clica no `summary` e não num texto fixo: o rótulo do chip mudou na v2 (o par não
    // comparável agora diz "par não comparável: ver critérios"), e o que o teste garante
    // é que **abrir** mostra o critério a critério, não qual palavra abre.
    const gatilho = aviso.querySelector('summary')
    expect(gatilho).toBeTruthy()
    await userEvent.click(gatilho!)
    expect(aviso.textContent).toContain('gasolina contra diesel')
    expect(aviso.textContent).toContain('atendido')
  })

  it('matriz: mostra a versão dos critérios usados', async () => {
    dublarApi()
    montar()
    const aviso = await screen.findByTestId('comparabilidade-v-srx')
    expect(aviso.textContent).toContain('2026-09-09')
  })
})

describe('matriz: a regra dos 1.000 kg', () => {
  it('mostra o texto fixo com a etiqueta INFERÊNCIA', async () => {
    dublarApi()
    montar()
    const flag = await screen.findByTestId('flag-1000kg')
    expect(flag.textContent).toContain('Capacidade de carga ≥ 1.000 kg')
    expect(flag.textContent).toContain('confirmar enquadramento fiscal com a Ford')
    expect(flag.querySelector('[data-testid="badge-INFERENCIA"]')).toBeTruthy()
  })

  it('matriz: o texto não fala de imposto', async () => {
    dublarApi()
    montar()
    const flag = await screen.findByTestId('flag-1000kg')
    for (const proibido of ['IPI', 'ICMS', 'imposto', 'isento']) {
      expect(flag.textContent?.toLowerCase()).not.toContain(proibido.toLowerCase())
    }
  })

  it('matriz: sem carga a tela diz "não avaliável", não "não atinge"', async () => {
    dublarApi()
    montar()
    const indeterminada = await screen.findByTestId('carga-indeterminada')
    expect(indeterminada.textContent).toContain('não avaliável')
    expect(indeterminada.textContent).not.toContain('não atinge')
  })
})

describe('matriz: filtro por dimensão', () => {
  it('manda o grupo escolhido na consulta', async () => {
    const chamadas = dublarApi()
    montar()
    await waitFor(() => expect(screen.getByTestId('linha-potencia_cv')).toBeTruthy())
    await userEvent.selectOptions(
      screen.getByLabelText('filtrar por dimensão'),
      'motorizacao',
    )
    await waitFor(() =>
      expect(chamadas.some((url) => url.includes('grupos=motorizacao'))).toBe(true),
    )
  })

  it('matriz: o denominador honesto aparece no cabeçalho', async () => {
    dublarApi()
    montar()
    expect(
      await screen.findByText(/3 de 4 campos com os dois lados conhecidos/),
    ).toBeTruthy()
  })
})
