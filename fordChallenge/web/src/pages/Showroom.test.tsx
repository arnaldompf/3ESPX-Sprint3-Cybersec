/**
 * As telas de showroom: perfil e comparação ponderada.
 *
 * Os três testes que carregam o peso: **o rótulo obrigatório junto do número**, **os pesos
 * visíveis**, e **"sem dado comparável: X" na dimensão** — sem eles a tela vira um ranking
 * de qualidade com aparência de objetividade.
 *
 * Todo `describe` diz "showroom" porque o verify da WP-26 seleciona por esse nome
 * (`vitest run -t showroom`), como o comando da spec pede.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Showroom } from './Showroom'
import type { Comparacao, Dimensoes, Veiculo } from '@/lib/tipos'

const ROTULO = 'Aderência ao perfil informado — não é um ranking de qualidade'

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

const DIMENSOES: Dimensoes = {
  versao: '2026-09-09',
  versao_das_faixas: '2026-09-09',
  pesos_por_rank: [35, 25, 20, 12, 8],
  cobertura_minima: 0.5,
  usos: ['rural_carga', 'familia', 'cidade', 'off_road', 'frota'],
  rotulo_obrigatorio: ROTULO,
  dimensoes: [
    {
      id: 'economia',
      rotulo: 'economia de combustível',
      campos: [
        {
          campo: 'consumo_urbano_kml',
          tipo: 'numerico',
          direcao: 'maior',
          faixa: {
            minimo: 7,
            maximo: 11,
            amostras: 3,
            de_onde: 'gabarito (3)',
            insuficiente: false,
          },
        },
      ],
    },
    { id: 'capacidade', rotulo: 'capacidade de carga e reboque', campos: [] },
    { id: 'desempenho', rotulo: 'desempenho', campos: [] },
  ],
}

function comparacao(): Comparacao {
  return {
    cells: [],
    fit: {
      rotulo: ROTULO,
      versao_das_dimensoes: '2026-09-09',
      versao_das_faixas: '2026-09-09',
      perfil: {},
      pesos: { economia: 35, capacidade: 25, desempenho: 0 },
      base: { version_id: 'v-raptor', rotulo: 'Ford Ranger Raptor' },
      usage_cost_base: {
        version_id: 'v-raptor',
        rotulo: 'Ford Ranger Raptor',
        combustivel: 'gasolina',
        consumo: {
          valor_kml: 8.0,
          origem: 'oficial',
          rotulo_da_origem: 'declarado pela montadora',
          campo: 'consumo_urbano_kml',
        },
        preco_por_litro: 6.0,
        km_mes: 2500,
        litros_mes: 312.5,
        custo_mes: 1875,
        custo_ano: 22500,
        frase:
          'Estimativa de combustível baseada em consumo declarado pela montadora e preços ' +
          'informados em 09/09/2026. Não inclui seguro, manutenção ou depreciação.',
        motivo_sem_custo: '',
      },
      concorrentes: [
        {
          version_id: 'v-srx',
          rotulo: 'Toyota Hilux SRX Plus',
          aderencia: {
            aderencia_ford: 3.8,
            aderencia_concorrente: 7.8,
            pesos: { economia: 35, capacidade: 25, desempenho: 0 },
            dimensoes: [
              {
                dimensao: 'economia',
                rotulo: 'economia de combustível',
                peso: 35,
                nota_ford: 1.6,
                nota_concorrente: 8.4,
                campos_usados: ['consumo_urbano_kml'],
                campos_sem_dado: [],
                cobertura: 1,
                insuficiente: false,
                aviso: '',
                detalhe_ford: [
                  {
                    campo: 'consumo_urbano_kml',
                    nota: 1.6,
                    valor: 7.2,
                    motivo: 'faixa 7..11 (gabarito (3))',
                  },
                ],
                detalhe_concorrente: [
                  {
                    campo: 'consumo_urbano_kml',
                    nota: 8.4,
                    valor: 9.7,
                    motivo: 'faixa 7..11 (gabarito (3))',
                  },
                ],
              },
              {
                dimensao: 'capacidade',
                rotulo: 'capacidade de carga e reboque',
                peso: 25,
                nota_ford: null,
                nota_concorrente: null,
                campos_usados: [],
                campos_sem_dado: [
                  { campo: 'capacidade_reboque_kg', motivo: 'sem valor verificado: Ford' },
                ],
                cobertura: 0,
                insuficiente: true,
                aviso:
                  'cobertura de 0 de 1 campos, abaixo do mínimo de 50%: dimensão ' +
                  '**excluída do total**. Sem dado comparável em: capacidade_reboque_kg.',
                detalhe_ford: [],
                detalhe_concorrente: [],
              },
            ],
            vence_em: { ford: ['desempenho'], concorrente: ['economia'] },
            peso_considerado: 35,
            avisos: ['a aderência foi calculada sobre 35% do peso do perfil'],
            rotulo: ROTULO,
            versao_das_dimensoes: '2026-09-09',
            versao_das_faixas: '2026-09-09',
          },
          usage_cost: {
            version_id: 'v-srx',
            rotulo: 'Toyota Hilux SRX Plus',
            combustivel: 'diesel',
            consumo: {
              valor_kml: 10.1,
              origem: 'pbe',
              rotulo_da_origem: 'medido pelo PBE/Inmetro',
              campo: 'consumo_urbano_kml + consumo_rodoviario_kml (55/45, ponderação do PBE)',
            },
            preco_por_litro: 6.2,
            km_mes: 2500,
            litros_mes: 247.52,
            custo_mes: 1534.65,
            custo_ano: 18415.8,
            frase:
              'Estimativa de combustível baseada em consumo medido pelo PBE/Inmetro e preços ' +
              'informados em 09/09/2026. Não inclui seguro, manutenção ou depreciação.',
            motivo_sem_custo: '',
          },
          custo_comparado: {
            ford: {} as never,
            concorrente: {} as never,
            diferenca_mes: 340.35,
            diferenca_ano: 4084.2,
            quem_gasta_menos: 'concorrente',
            motivo_sem_diferenca: '',
          },
        },
      ],
    },
  }
}

function dublarApi(resposta: Comparacao = comparacao()) {
  const chamadas: { url: string; corpo?: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      chamadas.push({
        url,
        corpo: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      let corpo: unknown = []
      if (url.includes('/dimensions')) corpo = DIMENSOES
      else if (url.includes('/vehicles')) corpo = VEICULOS
      else if (url.includes('/comparisons')) corpo = resposta
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
      <Showroom />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/** Espera o ranking **com itens**: o `<ol>` existe antes de as dimensões chegarem. */
async function esperarRanking() {
  await screen.findByRole('button', { name: /descer economia/ })
  return screen.getByTestId('ranking')
}

async function comparar() {
  await esperarRanking()
  await userEvent.click(screen.getByRole('button', { name: /comparar por este perfil/ }))
  await waitFor(() => expect(screen.getByTestId('rotulo-obrigatorio')).toBeTruthy())
}

describe('showroom: o perfil', () => {
  it('mostra os usos que a API declara, e diz que o perfil é anônimo', async () => {
    dublarApi()
    montar()
    expect(await screen.findByText(/trabalho rural \/ carga/)).toBeTruthy()
    expect(screen.getByText(/anônimo/)).toBeTruthy()
  })

  it('showroom: o ranking mostra o peso de cada posição', async () => {
    dublarApi()
    montar()
    const ranking = await esperarRanking()
    expect(ranking.textContent).toContain('35%')
    expect(ranking.textContent).toContain('25%')
    expect(ranking.textContent).toContain('20%')
  })

  it('showroom: reordenar com botão muda o peso da dimensão', async () => {
    dublarApi()
    montar()
    const ranking = await esperarRanking()
    const primeiro = ranking.querySelectorAll('li')[0]
    expect(primeiro?.textContent).toContain('economia')

    await userEvent.click(screen.getByRole('button', { name: /descer economia/ }))
    const depois = screen.getByTestId('ranking').querySelectorAll('li')
    expect(depois[0]?.textContent).toContain('capacidade')
    expect(depois[1]?.textContent).toContain('economia')
    // E o peso acompanha a posição: 35% na primeira, 25% na segunda.
    expect(depois[1]?.textContent).toContain('25%')
  })

  it('showroom: o ranking é operável por teclado (botões, não arrastar)', async () => {
    dublarApi()
    montar()
    await esperarRanking()
    const subir = screen.getAllByRole('button', { name: /subir/ })
    expect(subir.length).toBeGreaterThan(0)
    // O primeiro item não sobe: nada de botão que finge funcionar.
    expect(subir[0]).toBeDisabled()
  })

  it('showroom: manda o perfil na chamada, com km/mês e preços', async () => {
    const chamadas = dublarApi()
    montar()
    await comparar()
    const chamada = chamadas.find((c) => c.url.includes('/comparisons'))
    const corpo = chamada?.corpo as { needs_profile?: Record<string, unknown> }
    expect(corpo?.needs_profile).toBeTruthy()
    expect(corpo?.needs_profile?.km_mes).toBe(2500)
    expect(corpo?.needs_profile?.combustivel_preco).toEqual({ diesel: 6.2, gasolina: 6 })
  })
})

describe('showroom: a aderência', () => {
  it('mostra o rótulo obrigatório junto do número', async () => {
    dublarApi()
    montar()
    await comparar()
    expect(screen.getByTestId('rotulo-obrigatorio').textContent).toBe(ROTULO)
    expect(screen.getByTestId('aderencia-ford').textContent).toContain('3.8')
    expect(screen.getByTestId('aderencia-concorrente').textContent).toContain('7.8')
  })

  it('showroom: diz sobre quanto do peso a nota foi calculada', async () => {
    dublarApi()
    montar()
    await comparar()
    expect(screen.getByText(/calculado sobre 35% do peso do perfil/)).toBeTruthy()
  })

  it('showroom: a aderência leva etiqueta INFERÊNCIA', async () => {
    dublarApi()
    montar()
    await comparar()
    // `getAll`: na v2 são **duas** notas em dois cartões, e cada número leva a sua
    // etiqueta. "Nenhum número sem etiqueta" é por número, não por bloco.
    const etiquetas = screen.getAllByTestId('badge-INFERENCIA')
    expect(etiquetas.length).toBeGreaterThanOrEqual(2)
  })

  it('showroom: o aviso de peso parcial aparece', async () => {
    dublarApi()
    montar()
    await comparar()
    expect(screen.getByText(/35% do peso do perfil$/)).toBeTruthy()
  })

  it('o selo diz quem está à frente e por quanto', async () => {
    // Os dois números apareciam soltos, um em cada cartão, e quem olhava fazia a
    // subtração de cabeça — com o cliente ao lado.
    dublarApi()
    montar()
    await comparar()
    const selo = screen.getByTestId('selo-de-resultado').textContent ?? ''
    // 3.8 x 7.8 no dublê: o concorrente está à frente por 4,0.
    expect(selo).toContain('à frente por 4,0')
    expect(selo).toContain('Toyota')
    // "à frente", e nunca "melhor": docs/12 §3 — o score é aderência ao perfil informado.
    expect(selo).not.toMatch(/melhor|ganha|vence/i)
  })

  it('diferença abaixo de 0,3 é empate técnico, não vitória', async () => {
    // A nota é média ponderada sobre faixas de quatro veículos: uma diferença de 0,2 não
    // sobrevive a um veículo novo na amostra, e anunciá-la como vitória afirmaria mais do
    // que a régua sustenta.
    const resposta = comparacao()
    const aderencia = resposta.fit!.concorrentes[0]!.aderencia
    aderencia.aderencia_ford = 7.8
    aderencia.aderencia_concorrente = 7.6
    dublarApi(resposta)
    montar()
    await comparar()
    expect(screen.getByTestId('selo-de-resultado').textContent).toContain('empate técnico')
  })

  it('sem nota dos dois lados, não há selo — não há o que comparar', async () => {
    const resposta = comparacao()
    const aderencia = resposta.fit!.concorrentes[0]!.aderencia
    aderencia.aderencia_ford = null
    aderencia.aderencia_concorrente = null
    dublarApi(resposta)
    montar()
    await comparar()
    expect(screen.queryByTestId('selo-de-resultado')).toBeNull()
  })

  it('sem dimensão comparável, a barra não desenha 0 de 10 — diz "sem nota"', async () => {
    // `docs/12` §6.2: nota ausente não é zero. O motor devolve `null` e escreve, no
    // aviso, "um zero aqui seria invenção" — e a tela convertia esse `null` em `0`
    // (`?? 0`), desenhando "0 de 10" para os dois lados logo abaixo de um cartão que
    // dizia "sem nota". As duas coisas na mesma tela, contradizendo-se.
    const resposta = comparacao()
    const aderencia = resposta.fit!.concorrentes[0]!.aderencia
    aderencia.aderencia_ford = null
    aderencia.aderencia_concorrente = null
    aderencia.peso_considerado = 0
    aderencia.avisos = [
      'nenhuma dimensão com peso teve dado comparável suficiente: não há aderência a ' +
        'calcular, e um zero aqui seria invenção',
    ]
    dublarApi(resposta)
    montar()
    await comparar()

    expect(screen.queryByText(/0 de 10/)).toBeNull()
    expect(screen.queryByLabelText(/: 0 de 10$/)).toBeNull()
    expect(screen.getByText(/um zero aqui seria invenção/)).toBeTruthy()
    // "sem nota" aparece nos dois lados da barra, além do cartão.
    expect(screen.getAllByText('sem nota').length).toBeGreaterThanOrEqual(2)
  })

  it('nota no piso da faixa vem com a régua escrita, não sozinha', async () => {
    // Uma nota 0,1 ao lado de um 10,0 comunica "este carro não tem o item". O carro do
    // parecer tem 204 cv — é o menor dos quatro da amostra, que é outra frase.
    const resposta = comparacao()
    const dimensao = resposta.fit!.concorrentes[0]!.aderencia.dimensoes[0]!
    dimensao.nota_concorrente = 0.06
    dimensao.nota_no_piso = ['concorrente']
    dimensao.aviso_da_escala =
      'a nota é posição na faixa observada, não ausência do item: em potencia cv, a ' +
      'concorrente está no menor valor entre os 4 veículos comparados (de 204 a 397).'
    dublarApi(resposta)
    montar()
    await comparar()

    const aviso = screen.getByTestId(`escala-${dimensao.dimensao}`)
    expect(aviso.textContent).toContain('não ausência do item')
    expect(aviso.textContent).toContain('4 veículos comparados')
  })
})

describe('showroom: por dimensão', () => {
  it('mostra o peso de cada dimensão', async () => {
    dublarApi()
    montar()
    await comparar()
    expect(screen.getByTestId('peso-economia').textContent).toContain('35%')
    expect(screen.getByTestId('peso-capacidade').textContent).toContain('25%')
  })

  it('showroom: a dimensão insuficiente aparece marcada, não desaparece', async () => {
    dublarApi()
    montar()
    await comparar()
    const capacidade = screen.getByTestId('dimensao-capacidade')
    expect(capacidade.textContent).toContain('insuficiente')
    expect(capacidade.textContent).toContain('fora do total')
  })

  it('showroom: mostra "sem dado comparável" com o nome do campo', async () => {
    dublarApi()
    montar()
    await comparar()
    const sem = screen.getByTestId('sem-dado-capacidade')
    expect(sem.textContent).toContain('sem dado comparável')
    expect(sem.textContent).toContain('Capacidade reboque (kg)')
  })

  it('showroom: "ver como foi calculado" abre a nota por campo e a faixa', async () => {
    dublarApi()
    montar()
    await comparar()
    const dimensao = screen.getByTestId('dimensao-economia')
    const botao = dimensao.querySelector('button')
    expect(botao).toBeTruthy()
    await userEvent.click(botao!)
    const calculo = screen.getByTestId('calculo-economia')
    expect(calculo.textContent).toContain('Consumo urbano (km/l)')
    expect(calculo.textContent).toContain('faixa 7..11')
    expect(calculo.textContent).toContain('cobertura: 100%')
  })
})

describe('showroom: onde cada um vence', () => {
  it('mostra os dois lados com o mesmo destaque', async () => {
    dublarApi()
    montar()
    await comparar()
    const bloco = screen.getByTestId('vence-em')
    expect(bloco.textContent).toContain('economia de combustível')
    expect(bloco.textContent).toContain('desempenho')
  })
})

describe('showroom: custo de combustível', () => {
  it('mostra o custo de cada um com a origem do consumo', async () => {
    dublarApi()
    montar()
    await comparar()
    const conc = screen.getByTestId('custo-v-srx')
    expect(conc.textContent).toContain('medido pelo PBE/Inmetro')
    expect(conc.textContent).toContain('diesel')
    const ford = screen.getByTestId('custo-v-raptor')
    expect(ford.textContent).toContain('declarado pela montadora')
  })

  it('showroom: mostra a frase fixa com o que não está incluído', async () => {
    dublarApi()
    montar()
    await comparar()
    expect(
      screen.getAllByText(/Não inclui seguro, manutenção ou depreciação/).length,
    ).toBeGreaterThanOrEqual(1)
  })

  it('showroom: mostra a diferença anual e quem gasta menos', async () => {
    dublarApi()
    montar()
    await comparar()
    const diferenca = screen.getByTestId('diferenca-anual')
    expect(diferenca.textContent).toContain('por ano')
    expect(diferenca.textContent).toContain('Toyota Hilux SRX Plus')
  })

  it('showroom: sem custo, mostra o motivo em vez de zero', async () => {
    const resposta = comparacao()
    const custo = resposta.fit!.concorrentes[0]!.usage_cost
    custo.custo_mes = null
    custo.custo_ano = null
    custo.motivo_sem_custo = 'sem custo estimado: falta km por mês'
    resposta.fit!.concorrentes[0]!.custo_comparado.diferenca_ano = null
    resposta.fit!.concorrentes[0]!.custo_comparado.motivo_sem_diferenca =
      'sem custo estimado para concorrente: não há diferença a calcular'
    dublarApi(resposta)
    montar()
    await comparar()
    expect(screen.getByText(/falta km por mês/)).toBeTruthy()
    expect(screen.getByText(/não há diferença a calcular/)).toBeTruthy()
  })
})

describe('showroom: erro da API', () => {
  it('mostra o problema em português', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/dimensions'))
          return new Response(JSON.stringify(DIMENSOES), { status: 200 })
        if (url.includes('/vehicles'))
          return new Response(JSON.stringify(VEICULOS), { status: 200 })
        return new Response(
          JSON.stringify({ title: 'Dados inválidos', detail: 'os pesos somam 93' }),
          { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
        )
      }),
    )
    montar()
    await esperarRanking()
    await userEvent.click(screen.getByRole('button', { name: /comparar por este perfil/ }))
    expect(await screen.findByText('Dados inválidos')).toBeTruthy()
    expect(screen.getByText(/somam 93/)).toBeTruthy()
  })
})
