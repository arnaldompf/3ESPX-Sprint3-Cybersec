/**
 * WP-35 na tela: o **simulador**.
 *
 * Todo `describe` cita "simulador" porque o `verify` da WP-35 roda
 * `npx vitest run -t simulador` — teste que não casa com o filtro não roda no portão que
 * deveria protegê-lo (mesma disciplina da WP-32 com `-t matriz`).
 *
 * O critério de aceite visual é um só, e é o mais importante da tela: **a faixa
 * "SIMULAÇÃO — não é dado observado" está visível em todos os painéis do cenário**. Um
 * número que ninguém observou passando por dado real é o pior defeito que este produto
 * pode ter — pior que um erro, porque ninguém percebe.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Simulador } from './Simulador'
import type { CamposDoSimulador, Simulacao, Veiculo } from '@/lib/tipos'

const VEICULOS: Veiculo[] = [
  {
    id: 'v-ranger',
    marca: 'Ford',
    modelo: 'Ranger',
    versao: 'Limited 3.0 V6',
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

const CAMPOS: CamposDoSimulador = {
  delta_pct: {
    campos: ['capacidade_carga_kg', 'preco_sugerido_brl', 'torque_nm'],
    minimo: -50,
    maximo: 50,
    descricao: 'variação percentual sobre o valor atual',
  },
  novo_valor: { descricao: 'valor absoluto' },
  remover: { descricao: 'o item deixa de existir na versão' },
  rotulo: 'SIMULAÇÃO — não é dado observado',
  origem_dos_numeros: 'hipótese informada pelo usuário',
  maximo_de_overrides: 10,
}

function contagem(vantagem: number, gap: number) {
  return {
    vantagem,
    paridade: 3,
    gap,
    desconhecido: 2,
    total: vantagem + gap + 5,
    comparados: vantagem + gap + 3,
  }
}

function painel(is_simulation: boolean, vantagem: number, gap: number) {
  return {
    version_id: 'v-srx',
    rotulo: 'Toyota Hilux SRX Plus AT',
    coluna: {
      version_id: 'v-srx',
      rotulo: 'Toyota Hilux SRX Plus AT',
      celulas: [],
      contagem: contagem(vantagem, gap),
      comparabilidade: {
        version_id: 'v-srx',
        rotulo: 'Toyota Hilux SRX Plus AT',
        comparavel: true,
        criterios_atendidos: 6,
        criterios_avaliaveis: 7,
        total_de_criterios: 7,
        resumo: '6/7 critérios atendidos',
        aviso: 'compare com atenção: os dois têm finalidades diferentes',
        nao_atendidos: ['finalidade'],
        sem_dados: [],
        detalhes: [],
        versao_dos_criterios: '2026-09-09',
        escopo: 'avaliado sobre os valores reais dos dois veículos',
      },
      // A flag mora na COLUNA, não na comparabilidade — e é recalculada por painel: o
      // cenário que remove a carga deixa a regra dos 1.000 kg indeterminada.
      flag_de_carga: is_simulation
        ? {
            aplicavel: false,
            valor: null,
            texto: '',
            etiqueta: 'INFERENCIA',
            motivo:
              'sem valor de capacidade de carga: a regra dos 1.000 kg não é avaliável, e ' +
              'não avaliada é diferente de não atingida',
          }
        : {
            aplicavel: true,
            valor: true,
            capacidade_kg: 1000,
            texto: 'capacidade de carga de 1.000 kg ou mais (fonte: ficha de Toyota Hilux)',
            etiqueta: 'INFERENCIA',
            motivo: '1000 kg ≥ 1000 kg',
          },
    },
    aderencia: null,
    is_simulation,
    rotulo_simulacao: is_simulation ? 'SIMULAÇÃO — não é dado observado' : '',
  }
}

function simulacao(extra: Partial<Simulacao> = {}): Simulacao {
  return {
    is_simulation: true,
    rotulo: 'SIMULAÇÃO — não é dado observado',
    ford: { version_id: 'v-ranger', rotulo: 'Ford Ranger Limited 3.0 V6' },
    atual: [painel(false, 5, 2)],
    cenario: [painel(true, 4, 3)],
    diffs: [
      {
        version_id: 'v-srx',
        rotulo: 'Toyota Hilux SRX Plus AT',
        paridade: [
          {
            campo: 'preco_sugerido_brl',
            antes: 'vantagem',
            depois: 'gap',
            motivo_antes: 'a Ford é mais barata',
            motivo_depois: 'o concorrente é mais barato',
          },
        ],
        aderencia: [],
        materialidade: {
          materiality: 'ALTA',
          pontos: 125,
          significado: 'Mudança que altera a posição competitiva.',
          rules_fired: [
            {
              id: 'price_band_entry',
              peso: 40,
              descricao: 'O preço entrou na faixa de ±5% da Ford comparável.',
              detalhe: 'entrou na faixa de ±5% de R$ 410.000',
            },
          ],
          parity_flips: [],
          is_simulated: true,
          nota_de_hipotese: 'SIMULAÇÃO — a cadeia abaixo é uma hipótese.',
          campo_avaliado: 'preco_sugerido_brl',
        },
        motivo_sem_materialidade: '',
      },
    ],
    overrides_aplicados: [
      {
        version_id: 'v-srx',
        campo: 'preco_sugerido_brl',
        antes: 420000,
        depois: 399000,
        descricao: 'hipótese: preco_sugerido_brl −5%',
        origem: 'hipótese informada pelo usuário',
      },
    ],
    motivo_sem_aderencia: 'aderência não recalculada: nenhum perfil de necessidades informado',
    origem_dos_numeros: 'hipótese informada pelo usuário',
    ...extra,
  }
}

/** Responde `/vehicles`, `/scenarios/fields` e `POST /scenarios`. */
function dublarApi(resposta: Simulacao = simulacao()) {
  const corpos: string[] = []
  const buscar = vi.fn(async (url: string, opcoes?: RequestInit) => {
    if (opcoes?.body) corpos.push(String(opcoes.body))
    let corpo: unknown = VEICULOS
    if (url.includes('/scenarios/fields')) corpo = CAMPOS
    else if (url.includes('/scenarios')) corpo = resposta
    return new Response(JSON.stringify(corpo), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', buscar)
  return corpos
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={cliente}>
      <Simulador />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('critério de aceite do simulador: a faixa SIMULAÇÃO em todo painel', () => {
  it('o painel do cenário leva a faixa e a etiqueta SIMULAÇÃO', async () => {
    dublarApi()
    montar()
    const cenario = await screen.findByTestId('painel-cenario')
    expect(cenario.querySelector('[data-testid="faixa-simulacao"]')).toBeTruthy()
    expect(cenario.querySelector('[data-testid="badge-SIMULACAO"]')).toBeTruthy()
  })

  it('o painel da realidade é FATO, e não leva faixa de simulação', async () => {
    dublarApi()
    montar()
    const realidade = await screen.findByTestId('painel-realidade')
    expect(realidade.querySelector('[data-testid="badge-FATO"]')).toBeTruthy()
    expect(realidade.querySelector('[data-testid="faixa-simulacao"]')).toBeNull()
  })

  it('a faixa do topo aparece antes de qualquer resultado', async () => {
    // Sem esperar a resposta: quem chega na tela já lê o que ela é.
    dublarApi()
    montar()
    const faixas = await screen.findAllByTestId('faixa-simulacao')
    expect(faixas[0]?.textContent).toContain('não é informação sobre veículo real')
    expect(faixas[0]?.textContent).toContain('hipótese informada por você')
  })

  it('a faixa do painel usa o texto da API, palavra por palavra', async () => {
    /* O critério de aceite pede a frase "SIMULAÇÃO — não é dado observado", que é
       diferente do texto padrão da faixa ("dado de demonstração"). São duas simulações
       diferentes: uma é semente do banco, a outra é a hipótese de quem está olhando —
       e chamar o cenário do usuário de "dado de demonstração" seria impreciso
       justamente na tela em que a precisão importa mais. */
    dublarApi()
    montar()
    const cenario = await screen.findByTestId('painel-cenario')
    const faixa = cenario.querySelector('[data-testid="faixa-simulacao"]')
    expect(faixa?.textContent).toContain('SIMULAÇÃO — não é dado observado')
    expect(faixa?.textContent).not.toContain('dado de demonstração')
  })
})

describe('o slider do simulador', () => {
  it('começa em −5%, que é o cenário do critério de aceite', async () => {
    dublarApi()
    montar()
    const slider = await screen.findByTestId('slider-de-preco')
    expect((slider as HTMLInputElement).value).toBe('-5')
    expect(screen.getByText(/Preço do concorrente: -5%/)).toBeTruthy()
  })

  it('vai de −10% a +10%, como pede a spec', async () => {
    dublarApi()
    montar()
    const slider = (await screen.findByTestId('slider-de-preco')) as HTMLInputElement
    expect(slider.min).toBe('-10')
    expect(slider.max).toBe('10')
  })

  it('manda o override no corpo da chamada, com a versão do concorrente', async () => {
    const corpos = dublarApi()
    montar()
    await screen.findByTestId('painel-cenario')
    const corpo = JSON.parse(corpos[0]!)
    expect(corpo.base_version_ids).toEqual(['v-ranger', 'v-srx'])
    expect(corpo.overrides).toEqual([
      { version_id: 'v-srx', campo: 'preco_sugerido_brl', delta_pct: -5 },
    ])
  })

  it('mover o slider refaz a chamada com o novo percentual', async () => {
    // `fireEvent.change` e nao `userEvent.type`: input de faixa nao recebe texto, e
    // `clear`/`type` num range nao produzem o `change` que o React escuta.
    const corpos = dublarApi()
    montar()
    const slider = await screen.findByTestId('slider-de-preco')
    fireEvent.change(slider, { target: { value: '8' } })
    await waitFor(() =>
      expect(corpos.some((c) => JSON.parse(c).overrides[0]?.delta_pct === 8)).toBe(true),
    )
  })

  it('em 0% não manda override de preço: "sem hipótese" é uma opção', async () => {
    const corpos = dublarApi()
    montar()
    const slider = await screen.findByTestId('slider-de-preco')
    fireEvent.change(slider, { target: { value: '0' } })
    await waitFor(() => expect(corpos.some((c) => JSON.parse(c).overrides.length === 0)).toBe(true))
  })
})

describe('o "e se perdesse" do simulador', () => {
  it('oferece os campos que a API aceita, sem lista própria', async () => {
    dublarApi()
    montar()
    // `preco_sugerido_brl` fica fora das caixas: ele é o slider.
    expect(await screen.findByLabelText(/Capacidade carga/i)).toBeTruthy()
    expect(screen.getByText(/o item deixa de existir na versão/)).toBeTruthy()
  })

  it('marcar um item manda o override de remover', async () => {
    const corpos = dublarApi()
    montar()
    const caixa = await screen.findByLabelText(/Capacidade carga/i)
    await userEvent.click(caixa)
    await waitFor(() =>
      expect(
        corpos.some((c) =>
          JSON.parse(c).overrides.some(
            (o: { campo: string; remover?: boolean }) =>
              o.campo === 'capacidade_carga_kg' && o.remover === true,
          ),
        ),
      ).toBe(true),
    )
  })
})

describe('o "Realidade × Cenário" do simulador', () => {
  it('mostra os dois painéis, com a contagem dos quatro estados em cada', async () => {
    dublarApi()
    montar()
    const realidade = await screen.findByTestId('painel-realidade')
    const cenario = screen.getByTestId('painel-cenario')
    for (const painel of [realidade, cenario]) {
      for (const rotulo of ['ganhamos', 'empate', 'perdemos', 'não sabemos']) {
        expect(painel.textContent).toContain(rotulo)
      }
    }
    // 5 vantagens na realidade, 4 no cenário: o "antes" continua na tela.
    expect(realidade.textContent).toContain('5')
    expect(cenario.textContent).toContain('4')
  })

  it('cita a hipótese com o antes e o depois, e de onde ela veio', async () => {
    dublarApi()
    montar()
    const hipoteses = await screen.findByTestId('hipoteses')
    expect(hipoteses.textContent).toContain('420.000')
    expect(hipoteses.textContent).toContain('399.000')
    expect(hipoteses.textContent).toContain('hipótese informada pelo usuário')
  })

  it('a flag dos 1.000 kg é por painel: remover a carga deixa a regra indeterminada', async () => {
    /* O erro que este teste impede é o pior possível nesta frase: afirmar "não atinge
       1.000 kg" a partir de uma ausência. O texto fala de enquadramento fiscal. */
    dublarApi()
    montar()
    const realidade = await screen.findByTestId('painel-realidade')
    const cenario = screen.getByTestId('painel-cenario')
    expect(realidade.querySelector('[data-testid="flag-1000kg"]')).toBeTruthy()
    expect(cenario.querySelector('[data-testid="flag-1000kg"]')).toBeNull()
    expect(cenario.querySelector('[data-testid="carga-indeterminada"]')?.textContent).toContain(
      'não avaliável',
    )
  })

  it('o aviso de comparabilidade aparece nos dois painéis', async () => {
    dublarApi()
    montar()
    const avisos = await screen.findAllByText(/6\/7 critérios atendidos/)
    expect(avisos.length).toBe(2)
  })
})

describe('o diff do simulador', () => {
  it('mostra o estado que mudaria, com as duas etiquetas', async () => {
    dublarApi()
    montar()
    const mudancas = await screen.findByTestId('mudancas')
    expect(mudancas.textContent).toContain('ganhamos')
    expect(mudancas.textContent).toContain('perdemos')
  })

  it('mostra a materialidade que a mudança teria, marcada INFERÊNCIA', async () => {
    dublarApi()
    montar()
    const bloco = await screen.findByTestId('materialidade-do-cenario')
    expect(bloco.textContent).toContain('seria Alta')
    expect(bloco.textContent).toContain('+125 ponto(s)')
    expect(bloco.querySelector('[data-testid="badge-INFERENCIA"]')).toBeTruthy()
  })

  it('mostra as regras que produziram a faixa', async () => {
    dublarApi()
    montar()
    const diff = await screen.findByTestId('diff')
    expect(diff.textContent).toContain('price_band_entry')
    expect(diff.textContent).toContain('+40')
  })

  it('diz que a cadeia é hipótese', async () => {
    dublarApi()
    montar()
    const diff = await screen.findByTestId('diff')
    expect(diff.textContent).toContain('hipótese')
  })

  it('nada mudaria é resposta, não tela vazia', async () => {
    const nada = simulacao()
    nada.diffs[0]!.paridade = []
    dublarApi(nada)
    montar()
    expect((await screen.findByTestId('sem-mudanca')).textContent).toContain(
      'Silêncio aqui é resposta',
    )
  })

  it('sem override, diz por que não há materialidade', async () => {
    const vazio = simulacao()
    vazio.diffs[0]!.materialidade = null
    vazio.diffs[0]!.motivo_sem_materialidade =
      'nenhum override neste concorrente: sem mudança hipotética não há materialidade'
    vazio.overrides_aplicados = []
    dublarApi(vazio)
    montar()
    expect((await screen.findByTestId('sem-materialidade')).textContent).toContain(
      'nenhum override',
    )
    expect(screen.getByText(/Nenhuma hipótese ativa/)).toBeTruthy()
  })
})

describe('o simulador quando algo falha', () => {
  it('mostra o problem+json em vez de tela branca', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/vehicles')) {
          return new Response(JSON.stringify(VEICULOS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        if (url.includes('/scenarios/fields')) {
          return new Response(JSON.stringify(CAMPOS), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        return new Response(
          JSON.stringify({
            title: 'Requisição inválida',
            detail: 'delta_pct 900% fora da faixa: use um valor entre -50% e +50%',
          }),
          { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
        )
      }),
    )
    montar()
    expect(await screen.findByText(/fora da faixa/)).toBeTruthy()
    // E os controles continuam na tela: o usuário corrige e tenta de novo.
    expect(screen.getByTestId('slider-de-preco')).toBeTruthy()
  })
})
