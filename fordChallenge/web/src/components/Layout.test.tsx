/**
 * O selo de não lidos na aba do Radar.
 *
 * A regra que importa é a de **não** aparecer: o vendedor recebe 403 em `/alerts` por
 * decisão de produto (`docs/12` §6.1), e um selo de erro na aba anunciaria falha onde a
 * regra é proposital. O outro caso é o zero — um selo "0" permanente vira parte do desenho
 * da barra e para de ser aviso.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Layout } from './Layout'
import { PAGINAS, paginaDoCaminho } from '@/lib/paginas'
import { NOME_DO_PAPEL, O_QUE_FAZ, PAPEIS, PAPEL_INICIAL, definirPapel } from '@/lib/papel'
import type { Alerta } from '@/lib/tipos'

function alerta(extra: Partial<Alerta> = {}): Alerta {
  return {
    id: 'a1',
    type: 'preco_oficial',
    field: 'preco_sugerido_brl',
    old: 1,
    new: 2,
    created_at: '2026-09-05T12:00:00Z',
    lido: false,
    tratado: false,
    is_simulated: false,
    ...extra,
  }
}

function montar(resposta: () => Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn(resposta))
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Layout />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function json(corpo: unknown, status = 200) {
  return async () =>
    new Response(JSON.stringify(corpo), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('o selo da aba do Radar', () => {
  it('conta só os não lidos', async () => {
    montar(json([alerta({ id: 'a' }), alerta({ id: 'b' }), alerta({ id: 'c', lido: true })]))
    const selo = await screen.findByTestId('contador-radar')
    expect(selo.textContent).toBe('2')
    expect(selo).toHaveAttribute('aria-label', expect.stringContaining('2 alerta'))
  })

  it('não aparece quando tudo está lido: selo que nunca zera deixa de ser aviso', async () => {
    montar(json([alerta({ lido: true })]))
    // `findAll`: desde a v2 a navegação aparece duas vezes no DOM — a sidebar (desktop) e
    // a barra inferior (celular). Só uma delas é visível de cada vez, mas o jsdom não
    // aplica media query, então as duas existem na árvore.
    await screen.findAllByText('Radar')
    await waitFor(() => expect(screen.queryByTestId('contador-radar')).toBeNull())
  })

  it('não aparece para quem recebe 403: a regra não é falha a anunciar', async () => {
    montar(json({ title: 'Acesso negado', detail: 'Ação não permitida ao seu papel' }, 403))
    await screen.findAllByText('Radar')
    await waitFor(() => expect(screen.queryByTestId('contador-radar')).toBeNull())
    // E o item continua lá: quem tenta entrar recebe a explicação na própria tela.
    expect(screen.getAllByText('Radar').length).toBeGreaterThan(0)
  })
})

describe('a barra não promete tela que não existe', () => {
  it('não tem aba "Copiloto": a página era só um aviso', () => {
    /* Uma aba na navegação promete tela pronta. Quem clicava em "Copiloto" chegava a
     * uma página de aviso, e o `ONBOARDING.md` precisava de um item de risco só para
     * dizer isso no palco. A rota continua existindo (para não dar link quebrado a
     * quem tem o endereço) e aponta para o Showroom, que é onde o fluxo está. */
    montar(json([]))
    expect(screen.queryByRole('link', { name: 'Copiloto' })).toBeNull()
    expect(screen.getAllByRole('link', { name: 'Showroom' }).length).toBeGreaterThan(0)
  })
})


// ------------------------------------------------------ o cabecalho e o papel na barra
/** `fetch` que responde por caminho: a barra consulta alertas e `/health`. */
function servidor() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const corpo = url.endsWith('/health')
        ? {
            status: 'ok',
            version: '0.1.0',
            db: { ok: true, dialeto: 'sqlite', nome: 'x.db', erro: null },
            etiqueta: 'FATO',
            auth_enabled: false,
          }
        : []
      return new Response(JSON.stringify(corpo), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

function montarEm(caminho: string) {
  servidor()
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter
        initialEntries={[caminho]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Layout />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('toda tela tem titulo e descricao, com dado ou sem', () => {
  it.each(PAGINAS.map((p) => [p.para, p.titulo, p.descricao]))(
    '%s mostra "%s"',
    async (caminho, titulo, descricao) => {
      montarEm(String(caminho))
      const cabecalho = await screen.findByTestId('cabecalho-da-pagina')
      expect(cabecalho.textContent).toContain(titulo)
      expect(cabecalho.textContent).toContain(descricao)
      // `h1` e nao `div` com fonte grande: leitor de tela precisa do nivel.
      expect(cabecalho.querySelector('h1')?.textContent).toBe(titulo)
    },
  )

  it('o cabecalho nao depende do estado da pagina: ele mora no casco', async () => {
    /* O motivo de ele estar aqui e nao dentro de cada tela. As paginas tem retornos
     * antecipados (carregando, erro, 403, sem dado); um titulo escrito la dentro
     * apareceria no caminho feliz e sumiria justamente nos outros. */
    montarEm('/radar')
    const cabecalho = await screen.findByTestId('cabecalho-da-pagina')
    expect(cabecalho.textContent).toContain('Radar competitivo')
  })

  it('deep link de ficha herda o cabecalho da ficha', () => {
    expect(paginaDoCaminho('/ficha/abc123').titulo).toBe('Ficha técnica')
  })

  it('endereco desconhecido tambem tem cabecalho — nunca tela muda', () => {
    expect(paginaDoCaminho('/nao-existe').titulo).toBe('Página não encontrada')
  })

  it('uma rota parecida nao herda o cabecalho de outra', () => {
    /* `/fichario` nao pode virar "Ficha tecnica" so por comecar igual. */
    expect(paginaDoCaminho('/fichario').titulo).toBe('Página não encontrada')
  })
})

describe('o papel de quem olha fica na barra, e troca ali mesmo', () => {
  it('abre no papel inicial', async () => {
    montarEm('/consulta')
    const selo = await screen.findByTestId('papel-atual')
    expect(selo.textContent).toBe(PAPEL_INICIAL)
  })

  it('mostra o papel guardado no navegador', async () => {
    definirPapel('vendedor')
    montarEm('/consulta')
    expect((await screen.findByTestId('papel-atual')).textContent).toBe('vendedor')
  })

  it('o menu abre com os quatro papeis e o que cada um faz', async () => {
    montarEm('/consulta')
    await userEvent.click(await screen.findByTestId('trocar-papel'))
    const menu = await screen.findByTestId('lista-de-papeis')
    for (const papel of PAPEIS) {
      expect(menu.textContent).toContain(NOME_DO_PAPEL[papel])
      expect(menu.textContent).toContain(O_QUE_FAZ[papel])
    }
  })

  it('escolher um papel troca o que a barra mostra, sem sair da tela', async () => {
    /* Trocar de papel deixou de ser "sair e entrar de novo" (D-204): a tela aberta
     * continua aberta e passa a responder de outro jeito. */
    montarEm('/radar')
    await userEvent.click(await screen.findByTestId('trocar-papel'))
    await userEvent.click(await screen.findByTestId('papel-gestor'))
    await waitFor(() => expect(screen.getByTestId('papel-atual').textContent).toBe('gestor'))
    expect(screen.getByTestId('cabecalho-da-pagina').textContent).toContain('Radar competitivo')
  })

  it('nao ha "sair": nao ha sessao para encerrar', async () => {
    montarEm('/consulta')
    await screen.findByTestId('papel-atual')
    expect(screen.queryByRole('button', { name: 'sair' })).toBeNull()
  })
})
