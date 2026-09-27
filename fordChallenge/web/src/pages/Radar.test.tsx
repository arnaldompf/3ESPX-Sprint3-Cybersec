/**
 * A tela do Radar, onde mora o critério de aceite visual da WP-25.
 *
 * "Dado alerta `is_simulated=true`, então a tela mostra o rótulo SIMULAÇÃO" é o teste que
 * não pode faltar: um número de demonstração passando por dado real na tela do tablet
 * durante a apresentação é o pior defeito que este produto pode ter — pior que um erro,
 * porque ninguém percebe.
 *
 * O `fetch` é dublado aqui em vez de subir a API: o que está sob teste é a **leitura** do
 * alerta (o sentido do impacto, as quatro reações, a faixa), e a fidelidade ao contrato da
 * API já é garantida por `contrato.test.ts`, que lê o `openapi.json` de verdade.
 *
 * A **WP-34** trocou a fonte da lista: a tela lê `/events` (a fila com materialidade) em
 * vez de `/alerts`. O dublê passou a envelopar cada alerta num evento, e é por isso que
 * `evento()` existe aqui — a leitura sob teste continua a mesma. A fila em si, o
 * agrupamento e o "Por quê?" estão em `RadarFila.test.tsx`.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Radar } from './Radar'
import { formatarValor } from '@/lib/formato'
import { definirPapel } from '@/lib/papel'
import type { Alerta, AlertaDetalhado, EventoCompetitivo } from '@/lib/tipos'

function alerta(extra: Partial<Alerta> = {}): Alerta {
  return {
    id: 'a1',
    type: 'preco_oficial',
    version_id: 'v-srx',
    field: 'preco_sugerido_brl',
    old: 348790,
    new: 329990,
    created_at: '2026-09-05T12:00:00Z',
    lido: false,
    tratado: false,
    is_simulated: false,
    ...extra,
  }
}

function detalhe(extra: Partial<AlertaDetalhado> = {}): AlertaDetalhado {
  return {
    ...alerta(),
    impact: {
      delta: -18800,
      delta_pct: -5.39,
      gap_antes: -8790,
      gap_depois: 10010,
      dimensoes_afetadas: ['preco'],
      direcao: 'desfavorece_ford',
      material: true,
      motivo_sem_delta: '',
      motivo_sem_gap: '',
    },
    reactions: {
      marketing: 'Revisar o battlecard.',
      vendas: 'Reforçar onde a Ford ganha.',
      produto: 'Avaliar o novo gap.',
      ci: 'Confirmar na tabela oficial.',
    },
    evidence_before: {
      evidence_id: 'e1',
      source_url: 'https://www.toyota.com.br/hilux',
      tier: 1,
      quote: 'A partir de R$ 348.790',
      captured_at: '2026-08-01T00:00:00Z',
    },
    evidence_after: {
      evidence_id: 'e2',
      source_url: 'https://www.toyota.com.br/hilux',
      tier: 1,
      quote: 'A partir de R$ 329.990',
      captured_at: '2026-09-05T00:00:00Z',
    },
    ...extra,
  }
}

/**
 * Envelopa um alerta como evento da fila.
 *
 * `materiality` é `ALTA` por padrão de propósito: `RUIDO` entra no grupo colapsado, e um
 * teste que só quer ver o cartão não deveria ter de abrir o bloco primeiro.
 */
function evento(alerta: Alerta, extra: Partial<EventoCompetitivo> = {}): EventoCompetitivo {
  return {
    id: `ev-${alerta.id}`,
    alert_id: alerta.id,
    version_id: alerta.version_id ?? null,
    comparable_version_id: 'v-ranger',
    materiality: 'ALTA',
    significado: 'Mudança que altera a posição competitiva. Alguém precisa olhar hoje.',
    pontos: 105,
    rules_fired: [
      {
        id: 'price_band_entry',
        peso: 40,
        descricao: 'O preço do concorrente entrou na faixa de ±5% da versão Ford comparável.',
        detalhe: 'entrou na faixa de ±5% de R$ 390.000',
      },
    ],
    parity_flips: [],
    priority_rank: 894,
    versao_das_regras: '2026-09-09',
    is_simulated: alerta.is_simulated,
    criado_em: alerta.created_at,
    alerta,
    ...extra,
  }
}

/** Responde `/events` com a fila e `/alerts/{id}` com o detalhe. */
function dublarApi(lista: Alerta[], detalhado: AlertaDetalhado | null = detalhe()) {
  const chamadas: string[] = []
  const buscar = vi.fn(async (url: string) => {
    chamadas.push(url)
    const corpo = /\/alerts\/[^?]+$/.test(url) ? detalhado : lista.map((a) => evento(a))
    return new Response(JSON.stringify(corpo), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', buscar)
  return chamadas
}

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={cliente}>
      <Radar />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('critério de aceite: o rótulo SIMULAÇÃO', () => {
  it('mostra a faixa quando o alerta é de demonstração', async () => {
    dublarApi([alerta({ id: 'sim', is_simulated: true })])
    montar()

    // **Uma** faixa, a do grupo. Até a v1 eram duas — uma no topo da lista e outra
    // dentro do cartão do alerta —, e `030_ANTI_PADROES.md` §26 mandou parar com isso:
    // faixa repetida vira textura de fundo e deixa de avisar. A garantia que importa
    // continua exigida abaixo: dado simulado **nunca** aparece sem faixa e sem pill.
    const faixas = await screen.findAllByTestId('faixa-simulacao')
    expect(faixas.length).toBe(1)
    const [primeira] = faixas
    expect(primeira).toBeDefined()
    expect(primeira).toHaveAttribute('role', 'alert')
    expect(primeira?.textContent).toContain('não é informação sobre veículo real')
    // E a etiqueta do valor também muda: SIMULAÇÃO, não FATO.
    expect(screen.getByTestId('badge-SIMULACAO')).toBeTruthy()
    expect(screen.queryByTestId('badge-FATO')).toBeNull()
  })

  it('não mostra faixa nenhuma quando todos os alertas são reais', async () => {
    dublarApi([alerta()])
    montar()
    await screen.findByTestId('alerta-a1')
    expect(screen.queryByTestId('faixa-simulacao')).toBeNull()
    expect(screen.getByTestId('badge-FATO')).toBeTruthy()
  })

  it('a faixa do topo diz quantos da lista são simulados', async () => {
    dublarApi([alerta({ id: 'real' }), alerta({ id: 'sim', is_simulated: true })])
    montar()
    const faixas = await screen.findAllByTestId('faixa-simulacao')
    expect(faixas[0]?.textContent).toContain('1 de 2 alerta(s)')
  })
})

describe('o antes e o depois', () => {
  it('mostra os dois valores, nunca só o novo', async () => {
    dublarApi([alerta()])
    montar()
    await screen.findByTestId('alerta-a1')
    // Via `formatarValor` de proposito: o teste nao repete a regra de formatacao, ele
    // afirma que os dois valores estao na tela como a tela os escreve.
    expect(screen.getByText(formatarValor(348790))).toBeTruthy()
    expect(screen.getByText(formatarValor(329990))).toBeTruthy()
  })

  it('traduz o tipo do alerta para português', async () => {
    dublarApi([alerta({ type: 'referencia_interna_divergente' })])
    montar()
    expect(await screen.findByText(/divergência com material interno/)).toBeTruthy()
  })

  it('tipo desconhecido aparece como veio, sem quebrar a tela', async () => {
    dublarApi([alerta({ type: 'tipo_do_futuro' })])
    montar()
    expect(await screen.findByText('tipo_do_futuro')).toBeTruthy()
  })
})

describe('o impacto', () => {
  it('só busca o detalhe quando o usuário abre', async () => {
    const chamadas = dublarApi([alerta()])
    montar()
    await screen.findByTestId('alerta-a1')
    expect(chamadas.some((url) => url.includes('/alerts/a1'))).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: /ver impacto/ }))
    await waitFor(() => expect(screen.getByTestId('impacto')).toBeTruthy())
    expect(chamadas.some((url) => url.includes('/alerts/a1'))).toBe(true)
  })

  it('diz o sentido em texto, não só em cor', async () => {
    dublarApi([alerta()])
    montar()
    await screen.findByTestId('alerta-a1')
    await userEvent.click(screen.getByRole('button', { name: /ver impacto/ }))
    const direcao = await screen.findByTestId('direcao')
    expect(direcao.textContent).toContain('desfavorece a Ford')
  })

  it('mostra a variação com sinal e a porcentagem', async () => {
    dublarApi([alerta()])
    montar()
    await screen.findByTestId('alerta-a1')
    await userEvent.click(screen.getByRole('button', { name: /ver impacto/ }))
    const impacto = await screen.findByTestId('impacto')
    expect(impacto.textContent).toContain('18.800')
    expect(impacto.textContent).toContain('5,39%')
  })

  it('diz de que lado está o gap, em palavras', async () => {
    dublarApi([alerta()])
    montar()
    await screen.findByTestId('alerta-a1')
    await userEvent.click(screen.getByRole('button', { name: /ver impacto/ }))
    const impacto = await screen.findByTestId('impacto')
    expect(impacto.textContent).toContain('a Ford está mais cara')
  })

  it('sem equivalente cadastrado, mostra o motivo em vez de gap zero', async () => {
    const semGap = detalhe({
      impact: {
        delta: -18800,
        delta_pct: -5.39,
        gap_antes: null,
        gap_depois: null,
        dimensoes_afetadas: ['preco'],
        direcao: 'desfavorece_ford',
        material: true,
        motivo_sem_delta: '',
        motivo_sem_gap: 'sem versão Ford equivalente cadastrada',
      },
    })
    dublarApi([alerta()], semGap)
    montar()
    await screen.findByTestId('alerta-a1')
    await userEvent.click(screen.getByRole('button', { name: /ver impacto/ }))
    const impacto = await screen.findByTestId('impacto')
    expect(impacto.textContent).toContain('sem versão Ford equivalente cadastrada')
    // O ponto do teste: nao inventa "R$ 0" onde nao ha conta.
    expect(impacto.textContent).not.toContain('R$ 0')
  })

  it('avisa quando a mudança está abaixo do limiar de materialidade', async () => {
    const ruido = detalhe()
    ruido.impact = { ...ruido.impact!, material: false, delta: -300, delta_pct: -0.09 }
    dublarApi([alerta()], ruido)
    montar()
    await screen.findByTestId('alerta-a1')
    await userEvent.click(screen.getByRole('button', { name: /ver impacto/ }))
    expect((await screen.findByTestId('nao-material')).textContent).toContain('0,5%')
  })
})

describe('as reações sugeridas', () => {
  it('mostra as quatro áreas', async () => {
    dublarApi([alerta()])
    montar()
    await screen.findByTestId('alerta-a1')
    await userEvent.click(screen.getByRole('button', { name: /ver impacto/ }))
    const reacoes = await screen.findByTestId('reacoes')
    for (const area of ['Marketing', 'Vendas', 'Produto', 'Inteligência competitiva']) {
      expect(reacoes.textContent).toContain(area)
    }
  })

  it('vem etiquetada como INFERÊNCIA: é sugestão por regra, não fato', async () => {
    dublarApi([alerta()])
    montar()
    await screen.findByTestId('alerta-a1')
    await userEvent.click(screen.getByRole('button', { name: /ver impacto/ }))
    const reacoes = await screen.findByTestId('reacoes')
    expect(reacoes.querySelector('[data-testid="badge-INFERENCIA"]')).toBeTruthy()
  })
})

describe('a evidência dos dois lados', () => {
  it('mostra as duas citações literais', async () => {
    dublarApi([alerta()])
    montar()
    await screen.findByTestId('alerta-a1')
    await userEvent.click(screen.getByRole('button', { name: /ver impacto/ }))
    expect(await screen.findByText(/A partir de R\$ 348\.790/)).toBeTruthy()
    expect(screen.getByText(/A partir de R\$ 329\.990/)).toBeTruthy()
  })

  it('falta de evidência é dita, não escondida', async () => {
    dublarApi([alerta()], detalhe({ evidence_before: null }))
    montar()
    await screen.findByTestId('alerta-a1')
    await userEvent.click(screen.getByRole('button', { name: /ver impacto/ }))
    expect(await screen.findByText(/sem evidência registrada para o valor antes/)).toBeTruthy()
  })
})

describe('quando o papel não é desta tela', () => {
  it('explica de quem é o Radar, e não pede a fila ao servidor', async () => {
    /* **Quem decide é a tela** (D-204). Antes a decisão vinha de um 403 do servidor; sem
     * autenticação ele responde a todo mundo, e mostrar a fila ao vendedor seria
     * exatamente o vazamento que QA-BUG-16 pegou. O teste trava as duas metades: a
     * recusa aparece, e **nenhuma chamada sai** — pedir e jogar fora gastaria uma ida ao
     * servidor para desenhar um cartão que a tela já sabia desenhar. */
    definirPapel('vendedor')
    const chamadas = dublarApi([])
    montar()
    expect(await screen.findByTestId('recusa-por-papel')).toBeTruthy()
    expect(screen.getByText(/Esta tela é de analista, gestor e administrador/)).toBeTruthy()
    expect(chamadas.filter((url) => url.includes('/events'))).toHaveLength(0)
  })
})

describe('lista vazia', () => {
  it('diz que silêncio é resultado', async () => {
    dublarApi([])
    montar()
    expect(await screen.findByText(/Silêncio aqui é resultado/)).toBeTruthy()
  })
})

describe('os filtros', () => {
  it('esconder demonstração manda o parâmetro; o padrão não manda nada', async () => {
    const chamadas = dublarApi([alerta()])
    montar()
    await screen.findByTestId('alerta-a1')
    expect(chamadas[0]).not.toContain('incluir_simulados')

    await userEvent.click(screen.getByRole('checkbox'))
    await waitFor(() =>
      expect(chamadas.some((url) => url.includes('incluir_simulados=false'))).toBe(true),
    )
  })

  it('o tipo escolhido vai na consulta', async () => {
    const chamadas = dublarApi([alerta()])
    montar()
    await screen.findByTestId('alerta-a1')
    await userEvent.selectOptions(screen.getByRole('combobox'), 'preco_fipe')
    await waitFor(() =>
      expect(chamadas.some((url) => url.includes('type=preco_fipe'))).toBe(true),
    )
  })
})
