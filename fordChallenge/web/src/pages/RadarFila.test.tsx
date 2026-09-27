/**
 * WP-34 na tela: a **fila de prioridade do radar** e o botão **"Por quê?"**.
 *
 * Todo `describe` deste arquivo cita "radar" ou "porque" porque o `verify` da WP-34 roda
 * `npx vitest run -t "radar|porque"` — o filtro casa com o nome do teste, e um teste que
 * não casa não roda no portão que deveria protegê-lo.
 *
 * Os dois critérios de aceite visuais estão aqui: **ALTA primeiro com o ruído colapsado**
 * e **a cadeia inteira em dois cliques, com etiquetas FATO/INFERÊNCIA**. O terceiro — a
 * cadeia sem elo vazio — aparece do lado difícil: sem evidência gravada, o elo tem de
 * mostrar o motivo em vez de não mostrar nada.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Radar } from './Radar'
import type { Alerta, Cadeia, EventoCompetitivo, Materialidade } from '@/lib/tipos'

const SIGNIFICADO: Record<string, string> = {
  ALTA: 'Mudança que altera a posição competitiva. Alguém precisa olhar hoje.',
  MEDIA: 'Mudança real, sem inverter nada. Entra na revisão da semana.',
  BAIXA: 'Mudança pequena e sem efeito na comparação. Fica registrada, com evidência.',
  RUIDO: 'Variação dentro do que a fonte muda sozinha. Não interrompe ninguém.',
}

/** Base do rank do motor: os degraus de 1000 impedem a soma de cruzar a faixa. */
const BASE_DO_RANK: Record<string, number> = { ALTA: 0, MEDIA: 1000, BAIXA: 2000, RUIDO: 3000 }

function alerta(extra: Partial<Alerta> = {}): Alerta {
  return {
    id: 'a1',
    type: 'preco_oficial',
    version_id: 'v-srx',
    field: 'preco_sugerido_brl',
    old: 420000,
    new: 395000,
    created_at: '2026-09-05T12:00:00Z',
    lido: false,
    tratado: false,
    is_simulated: false,
    ...extra,
  }
}

function evento(
  faixa: Materialidade,
  pontos: number,
  extra: Partial<Alerta> = {},
): EventoCompetitivo {
  const linha = alerta({ id: `a-${faixa.toLowerCase()}`, ...extra })
  return {
    id: `ev-${linha.id}`,
    alert_id: linha.id,
    version_id: linha.version_id ?? null,
    comparable_version_id: 'v-ranger',
    materiality: faixa,
    significado: SIGNIFICADO[faixa] ?? '',
    pontos,
    rules_fired: [
      {
        id: 'magnitude_alta',
        peso: 45,
        descricao: 'Variação de 5% ou mais no valor.',
        detalhe: '|Δ| de 5.95%',
      },
    ],
    parity_flips: [],
    priority_rank: (BASE_DO_RANK[faixa] ?? 3000) + Math.max(0, 999 - pontos),
    versao_das_regras: '2026-09-09',
    is_simulated: Boolean(linha.is_simulated),
    criado_em: linha.created_at,
    alerta: linha,
  }
}

function cadeia(extra: Partial<Cadeia> = {}): Cadeia {
  return {
    alert_id: 'a-alta',
    materiality: 'ALTA',
    significado: SIGNIFICADO.ALTA!,
    pontos: 125,
    priority_rank: 874,
    is_simulated: false,
    versao_das_regras: '2026-09-09',
    acao_sugerida:
      'Revisar hoje o battlecard e o argumentário deste par, e conferir a faixa de preço com o gestor comercial.',
    regras: [
      {
        id: 'price_band_entry',
        peso: 40,
        descricao: 'O preço do concorrente entrou na faixa de ±5% da versão Ford comparável.',
        detalhe: 'entrou na faixa de ±5% de R$ 390.000',
      },
      {
        id: 'par_nao_comparavel',
        peso: -15,
        descricao: 'O par não passa nos critérios de comparabilidade.',
        detalhe: 'o par não passa nos critérios',
      },
    ],
    mudanca: {
      campo_canonico: 'preco_sugerido_brl',
      before: 420000,
      after: 395000,
      tipo_de_alerta: 'preco_oficial',
      detectado_em: '2026-09-05T12:00:00Z',
    },
    parity_flips: [{ campo: 'potencia_cv', antes: 'vantagem', depois: 'gap', motivo: '' }],
    comparavel: { version_id: 'v-ranger', rotulo: 'Ford Ranger Limited 3.0 V6', motivo: '' },
    evidencias: [
      {
        evidence_id: 'e1',
        source_url: 'https://www.toyota.com.br/hilux',
        tier: 1,
        quote: 'A partir de R$ 420.000',
        captured_at: '2026-08-05T00:00:00Z',
        lado: 'antes',
      },
      {
        evidence_id: 'e2',
        source_url: 'https://www.toyota.com.br/hilux',
        tier: 1,
        quote: 'A partir de R$ 395.000',
        captured_at: '2026-09-05T00:00:00Z',
        lado: 'depois',
      },
    ],
    motivo_sem_evidencia: '',
    snapshots: [
      {
        snapshot_id: 's1',
        url: 'https://www.toyota.com.br/hilux',
        sha256: 'abc123def456',
        captured_at: '2026-09-05T00:00:00Z',
        http_status: 200,
      },
    ],
    motivo_sem_snapshot: '',
    nota_dos_pesos: 'Pesos são hipótese do MVP e configuráveis em `rules.yaml`.',
    gerado_em: '2026-09-09T12:00:00Z',
    ...extra,
  }
}

/** Responde `/events` com a fila e `/alerts/{id}/trace` com a cadeia. */
function dublarApi(fila: EventoCompetitivo[], corrente: Cadeia = cadeia()) {
  const chamadas: string[] = []
  const buscar = vi.fn(async (url: string) => {
    chamadas.push(url)
    const corpo = url.includes('/trace') ? corrente : fila
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

describe('critério de aceite: a fila de prioridade do radar', () => {
  it('agrupa por faixa com ALTA primeiro', async () => {
    dublarApi([evento('BAIXA', 20), evento('ALTA', 125), evento('MEDIA', 45)])
    montar()
    await screen.findByTestId('grupo-ALTA')

    const grupos = Array.from(document.querySelectorAll('[data-testid^="grupo-"]')).map((no) =>
      no.getAttribute('data-testid'),
    )
    expect(grupos).toEqual(['grupo-ALTA', 'grupo-MEDIA', 'grupo-BAIXA'])
  })

  it('colapsa o ruído no fim, com a contagem à vista', async () => {
    dublarApi([evento('ALTA', 125), evento('RUIDO', 20)])
    montar()
    const grupo = await screen.findByTestId('grupo-RUIDO')

    // O bloco existe e diz quantos são; o cartão do alerta não está aberto.
    expect(grupo.textContent).toContain('1 alerta(s)')
    expect(screen.queryByTestId('alerta-a-ruido')).toBeNull()
    expect(screen.getByTestId('alerta-a-alta')).toBeTruthy()

    // E o ruído é o último grupo da fila.
    const grupos = Array.from(document.querySelectorAll('[data-testid^="grupo-"]'))
    expect(grupos[grupos.length - 1]?.getAttribute('data-testid')).toBe('grupo-RUIDO')
  })

  it('o ruído abre com um clique: sai da fila, não do sistema', async () => {
    dublarApi([evento('RUIDO', 20)])
    montar()
    const botao = await screen.findByRole('button', { name: /abrir o ruído/ })
    await userEvent.click(botao)
    expect(await screen.findByTestId('alerta-a-ruido')).toBeTruthy()
    expect(screen.getByRole('button', { name: /colapsar o ruído/ })).toBeTruthy()
  })

  it('cada linha do radar mostra a faixa com ícone e pontos, não só cor', async () => {
    dublarApi([evento('ALTA', 125)])
    montar()
    const selo = await screen.findByTestId('faixa-ALTA')
    expect(selo.textContent).toContain('Alta')
    expect(selo.textContent).toContain('+125 ponto(s)')
    expect(selo.getAttribute('title')).toContain('posição competitiva')
  })

  it('o significado da faixa vem da API, não escrito na tela', async () => {
    const fila = [evento('MEDIA', 45)]
    fila[0]!.significado = 'texto que só existe no rules.yaml'
    dublarApi(fila)
    montar()
    expect(await screen.findByText('texto que só existe no rules.yaml')).toBeTruthy()
  })

  it('a fila do radar não reordena o que a API mandou', async () => {
    // Dois ALTA: a ordem tem de ser a da resposta, que já vem por `priority_rank`. O
    // menos pontuado vem primeiro no dublê **de propósito** — se a tela ordenasse por
    // conta própria, ela inverteria estes dois e o teste pegaria.
    dublarApi([evento('ALTA', 70, { id: 'x1' }), evento('ALTA', 125, { id: 'x2' })])
    montar()
    await screen.findByTestId('grupo-ALTA')

    const linhas = Array.from(document.querySelectorAll('[data-testid^="alerta-"]')).map((no) =>
      no.getAttribute('data-testid'),
    )
    expect(linhas).toEqual(['alerta-x1', 'alerta-x2'])
  })
})

describe('critério de aceite: o "porque" abre a cadeia inteira', () => {
  async function abrir() {
    dublarApi([evento('ALTA', 125)])
    montar()
    await screen.findByTestId('alerta-a-alta')
    await userEvent.click(screen.getByRole('button', { name: 'Por quê?' }))
    return screen.findByTestId('gaveta-porque')
  }

  it('dois cliques: um no alerta, um no "Por quê?"', async () => {
    const gaveta = await abrir()
    expect(gaveta.getAttribute('role')).toBe('dialog')
    expect(gaveta.getAttribute('aria-modal')).toBe('true')
  })

  it('mostra os cinco elos, da ação até a prova', async () => {
    await abrir()
    for (const numero of [1, 2, 3, 4, 5]) {
      expect(screen.getByTestId(`elo-${numero}`)).toBeTruthy()
    }
  })

  it('o primeiro elo responde "e daí?": a ação sugerida', async () => {
    await abrir()
    expect((await screen.findByTestId('acao-sugerida')).textContent).toContain(
      'Revisar hoje o battlecard',
    )
  })

  it('a ação e a materialidade vêm etiquetadas INFERÊNCIA', async () => {
    await abrir()
    const acao = screen.getByTestId('elo-1')
    const regras = screen.getByTestId('elo-2')
    expect(acao.querySelector('[data-testid="badge-INFERENCIA"]')).toBeTruthy()
    expect(regras.querySelector('[data-testid="badge-INFERENCIA"]')).toBeTruthy()
  })

  it('a mudança e a prova vêm etiquetadas FATO', async () => {
    await abrir()
    for (const elo of ['elo-3', 'elo-4', 'elo-5']) {
      expect(screen.getByTestId(elo).querySelector('[data-testid="badge-FATO"]')).toBeTruthy()
    }
  })

  it('mostra cada regra com o peso, inclusive o negativo', async () => {
    await abrir()
    const regras = await screen.findByTestId('regras')
    expect(regras.textContent).toContain('price_band_entry')
    expect(regras.textContent).toContain('+40')
    // Peso negativo é parte da régua e aparece como é: subtraiu.
    expect(regras.textContent).toContain('par_nao_comparavel')
    expect(regras.textContent).toContain('-15')
  })

  it('diz que os pesos são hipótese e qual régua valia', async () => {
    await abrir()
    expect(screen.getByTestId('elo-2').textContent).toContain('hipótese do MVP')
    expect(screen.getByTestId('elo-2').textContent).toContain('2026-09-09')
  })

  it('mostra a inversão de paridade em palavras', async () => {
    await abrir()
    const inversoes = await screen.findByTestId('inversoes')
    expect(inversoes.textContent).toContain('vantagem da Ford → gap contra a Ford')
  })

  it('mostra a citação literal e o hash do snapshot', async () => {
    await abrir()
    expect(screen.getByText(/A partir de R\$ 420\.000/)).toBeTruthy()
    expect(screen.getByText(/A partir de R\$ 395\.000/)).toBeTruthy()
    expect(screen.getByTestId('snapshots').textContent).toContain('abc123def456')
  })

  it('fecha no Escape sem prender o teclado', async () => {
    await abrir()
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByTestId('gaveta-porque')).toBeNull())
  })

  it('só busca a cadeia quando alguém pergunta', async () => {
    const chamadas = dublarApi([evento('ALTA', 125)])
    montar()
    await screen.findByTestId('alerta-a-alta')
    expect(chamadas.some((url) => url.includes('/trace'))).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Por quê?' }))
    await waitFor(() => expect(chamadas.some((url) => url.includes('/trace'))).toBe(true))
  })
})

describe('critério de aceite: nenhum elo do "porque" fica vazio', () => {
  it('sem evidência gravada, mostra o motivo em vez do branco', async () => {
    dublarApi(
      [evento('ALTA', 125)],
      cadeia({
        evidencias: [],
        motivo_sem_evidencia:
          'sem evidência gravada para este lado da mudança. O alerta é real (o valor mudou no banco).',
        snapshots: [],
        motivo_sem_snapshot: 'nenhum snapshot gravado para as URLs desta evidência.',
      }),
    )
    montar()
    await screen.findByTestId('alerta-a-alta')
    await userEvent.click(screen.getByRole('button', { name: 'Por quê?' }))

    expect((await screen.findByTestId('sem-evidencia')).textContent).toContain(
      'sem evidência gravada',
    )
    expect(screen.getByTestId('sem-snapshot').textContent).toContain('nenhum snapshot gravado')
    // O elo continua lá: o que muda é o conteúdo, não a existência.
    expect(screen.getByTestId('elo-5')).toBeTruthy()
  })

  it('porque: com UMA evidência só, o rótulo é o lado que ela declara', async () => {
    /* O defeito D-156, agora coberto. A tela rotulava cada bloco **pelo índice**: o 0
     * levava "antes: …". O serviço filtra os `None` antes de montar a lista, e no Fogo
     * Amigo `evidence_before_id` nunca é gravado — a evidência do **depois** caía no
     * índice 0 e a tela imprimia "antes: 420.000" em cima da citação da página oficial.
     * A citação estava certa; o rótulo em cima dela era do lado errado.
     *
     * Este é o caso que `RadarFila.test.tsx` não tinha: só havia os de duas evidências e
     * o de zero. */
    dublarApi(
      [evento('ALTA', 125)],
      cadeia({
        evidencias: [
          {
            evidence_id: 'e2',
            source_url: 'https://www.ford.com.br/picapes/ranger-raptor/raptor-4wd-at/',
            tier: 1,
            quote: 'A partir de R$ 395.000',
            captured_at: '2026-09-05T00:00:00Z',
            lado: 'depois',
          },
        ],
      }),
    )
    montar()
    await screen.findByTestId('alerta-a-alta')
    await userEvent.click(screen.getByRole('button', { name: 'Por quê?' }))

    const elo = await screen.findByTestId('elo-5')
    expect(elo.textContent).toContain('depois: 395.000')
    expect(elo.textContent).not.toContain('antes:')
    // A citação continua sendo a da fonte, intacta.
    expect(elo.textContent).toContain('A partir de R$ 395.000')
  })

  it('porque: evidência sem lado declarado não é rotulada como "antes"', async () => {
    /* Contrato antigo, ou fonte que não diz de que lado é. Dizer o lado errado é pior
     * que não dizer o lado — o rótulo cai para "a prova", que é verdade sobre qualquer
     * evidência do elo 5. */
    dublarApi(
      [evento('ALTA', 125)],
      cadeia({
        evidencias: [
          {
            evidence_id: 'e9',
            source_url: 'https://www.ford.com.br/picapes/ranger-raptor/raptor-4wd-at/',
            tier: 1,
            quote: '4 modos de direção',
            captured_at: '2026-09-05T00:00:00Z',
          },
        ],
      }),
    )
    montar()
    await screen.findByTestId('alerta-a-alta')
    await userEvent.click(screen.getByRole('button', { name: 'Por quê?' }))

    const elo = await screen.findByTestId('elo-5')
    // "A prova" é o título do elo; o rótulo do bloco é o "a prova" minúsculo.
    expect(elo.textContent).toContain('a prova')
    expect(elo.textContent).not.toContain('antes:')
    expect(elo.textContent).not.toContain('depois:')
  })

  it('sem par comparável, mostra o motivo em vez de deixar o elo em branco', async () => {
    dublarApi(
      [evento('ALTA', 125)],
      cadeia({
        comparavel: {
          version_id: null,
          rotulo: '',
          motivo: 'nenhuma versão Ford equivalente cadastrada para este concorrente',
        },
      }),
    )
    montar()
    await screen.findByTestId('alerta-a-alta')
    await userEvent.click(screen.getByRole('button', { name: 'Por quê?' }))
    expect((await screen.findByTestId('sem-comparavel')).textContent).toContain(
      'nenhuma versão Ford equivalente cadastrada',
    )
  })
})

describe('critério de aceite: o radar simulado diz SIMULAÇÃO e a cadeia diz hipótese', () => {
  it('a linha da fila leva a faixa e a etiqueta SIMULAÇÃO', async () => {
    dublarApi([evento('ALTA', 125, { is_simulated: true })])
    montar()
    // **Uma** faixa, a do grupo — e o pill no item. Até a v1 eram duas faixas (uma no
    // topo, outra dentro do cartão); `030_ANTI_PADROES.md` §26 manda uma por seção, porque
    // faixa repetida vira textura e deixa de avisar. O que continua garantido é o que
    // importa: alerta simulado não aparece sem faixa **e** sem etiqueta.
    const faixas = await screen.findAllByTestId('faixa-simulacao')
    expect(faixas.length).toBe(1)
    expect(screen.getByTestId('badge-SIMULACAO')).toBeTruthy()
  })

  it('a cadeia do alerta simulado diz que é hipótese', async () => {
    dublarApi(
      [evento('ALTA', 125, { is_simulated: true })],
      cadeia({
        is_simulated: true,
        acao_sugerida:
          'SIMULAÇÃO — este alerta é dado de demonstração, e a cadeia abaixo é uma hipótese.',
      }),
    )
    montar()
    await screen.findByTestId('alerta-a-alta')
    await userEvent.click(screen.getByRole('button', { name: 'Por quê?' }))

    const gaveta = await screen.findByTestId('gaveta-porque')
    expect(gaveta.textContent).toContain('hipótese')
    expect(gaveta.querySelector('[data-testid="faixa-simulacao"]')).toBeTruthy()
    // A mudança de um alerta simulado não é FATO, e a etiqueta não finge que é.
    expect(
      screen.getByTestId('elo-3').querySelector('[data-testid="badge-SIMULACAO"]'),
    ).toBeTruthy()
  })
})

describe('a fila do radar quando algo falha', () => {
  it('erro na cadeia não derruba a tela', async () => {
    const fila = [evento('ALTA', 125)]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/trace')) {
          return new Response(
            JSON.stringify({ title: 'Erro interno', detail: 'falha ao montar a cadeia' }),
            { status: 500, headers: { 'Content-Type': 'application/problem+json' } },
          )
        }
        return new Response(JSON.stringify(fila), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
    montar()
    await screen.findByTestId('alerta-a-alta')
    await userEvent.click(screen.getByRole('button', { name: 'Por quê?' }))
    expect(await screen.findByText(/falha ao montar a cadeia/)).toBeTruthy()
    expect(screen.getByTestId('alerta-a-alta')).toBeTruthy()
  })
})
