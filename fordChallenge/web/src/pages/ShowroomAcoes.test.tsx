/**
 * Os painéis de **argumentos** e de **resultado**.
 *
 * Dois testes carregam o peso: o **ponto de atenção com o mesmo destaque** dos três a favor
 * (um aviso em letra miúda cumpriria `docs/12` §3 no código e a quebraria na tela), e o
 * **formulário sem nenhum campo sobre o cliente** — o que não existe no formulário não vira
 * PII no banco.
 *
 * Os `describe` dizem "argumentos" e "resultado" porque é o que o verify da WP-27 seleciona.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { MOTIVOS_DE_PERDA, PainelDeArgumentos, PainelDeResultado } from './ShowroomAcoes'
import type { Argumentario, PontoDoArgumentario, SessaoDeShowroom } from '@/lib/tipos'

function ponto(extra: Partial<PontoDoArgumentario> = {}): PontoDoArgumentario {
  return {
    dimensao: 'desempenho',
    rotulo_da_dimensao: 'desempenho',
    peso: 35,
    campo: 'potencia_cv',
    valor_ford: 397,
    valor_concorrente: 204,
    unidade: 'cv',
    texto:
      'Para quem prioriza desempenho: a Ford Ranger Raptor tem potencia cv de 397 cv contra ' +
      '204 cv da Toyota Hilux SRX Plus (https://www.ford.com.br/ranger-raptor, 01/09/2026).',
    fonte_por_ponto: ['ev-ford', 'ev-conc'],
    a_favor: true,
    ...extra,
  }
}

function argumentario(extra: Partial<Argumentario> = {}): Argumentario {
  return {
    pontos: [
      ponto(),
      ponto({ dimensao: 'seguranca', campo: 'camera_360', peso: 25, texto: 'Segurança: 7 airbags.' }),
      ponto({
        dimensao: 'conforto_tecnologia',
        campo: 'farois_tipo',
        peso: 20,
        texto: 'Conforto: faróis Matrix LED.',
      }),
    ],
    ponto_forte_concorrente: ponto({
      dimensao: 'capacidade',
      campo: 'capacidade_carga_kg',
      peso: 12,
      a_favor: false,
      texto:
        'Onde a Toyota Hilux SRX Plus leva vantagem: capacidade carga kg — 1.005 kg contra ' +
        '620 kg da Ford Ranger Raptor (https://www.toyota.com.br/hilux, 01/09/2026).',
    }),
    fonte_por_ponto: [
      ['ev-ford', 'ev-conc'],
      ['ev-ford-2', 'ev-conc-2'],
      ['ev-ford-3', 'ev-conc-3'],
    ],
    gerado_por: 'template',
    aprovado: false,
    travado: false,
    avisos: [],
    comparison_id: 'v-raptor:v-srx',
    ford: { version_id: 'v-raptor', rotulo: 'Ford Ranger Raptor' },
    concorrente: { version_id: 'v-srx', rotulo: 'Toyota Hilux SRX Plus' },
    pesos: { desempenho: 35, seguranca: 25, conforto_tecnologia: 20 },
    selo: '',
    ...extra,
  }
}

function sessao(extra: Partial<SessaoDeShowroom> = {}): SessaoDeShowroom {
  return {
    id: 's1',
    ford_version_id: 'v-raptor',
    competitor_version_ids: ['v-srx'],
    outcome: 'em_andamento',
    motivos: [],
    is_simulated: false,
    created_at: '2026-09-09T12:00:00',
    ...extra,
  }
}

describe('argumentos: os três pontos e o de atenção', () => {
  it('mostra os três pontos com peso e contagem de evidências', () => {
    render(
      <PainelDeArgumentos argumentario={argumentario()} aoGerar={() => {}} carregando={false} />,
    )
    const lista = screen.getByTestId('pontos')
    expect(lista.querySelectorAll('li').length).toBe(3)
    expect(lista.textContent).toContain('397 cv')
    expect(lista.textContent).toContain('peso 35%')
    expect(lista.textContent).toContain('2 evidência(s)')
  })

  it('argumentos: o ponto de atenção aparece em bloco próprio e destacado', () => {
    render(
      <PainelDeArgumentos argumentario={argumentario()} aoGerar={() => {}} carregando={false} />,
    )
    const atencao = screen.getByTestId('ponto-de-atencao')
    expect(atencao.textContent).toContain('leva vantagem')
    expect(atencao.textContent).toContain('1.005 kg')
    // Fundo próprio, ícone de aviso e o mesmo tamanho de corpo dos três a favor: é o que
    // "mesmo peso visual" significa na v2. A borda de 2 px saiu porque borda grossa é um
    // dos traços que datavam a tela (`030_ANTI_PADROES.md`); o destaque agora vem da
    // superfície, e a área ocupada é a mesma dos pontos a favor.
    expect(atencao.className).toContain('bg-naoSabemos-fundo')
    expect(atencao.querySelector('svg')).toBeTruthy()
  })

  it('argumentos: explica por que dizer o ponto de atenção é do interesse do vendedor', () => {
    render(
      <PainelDeArgumentos argumentario={argumentario()} aoGerar={() => {}} carregando={false} />,
    )
    expect(screen.getByText(/ele já sabe/)).toBeTruthy()
  })

  it('argumentos: sem argumentário, convida a gerar em vez de mostrar vazio', () => {
    render(<PainelDeArgumentos argumentario={undefined} aoGerar={() => {}} carregando={false} />)
    expect(screen.getByText(/Gere o argumentário depois de comparar/)).toBeTruthy()
  })

  it('argumentos: mostra de onde o texto veio', () => {
    render(
      <PainelDeArgumentos argumentario={argumentario()} aoGerar={() => {}} carregando={false} />,
    )
    expect(screen.getByTestId('gerado-por').textContent).toBe('template')
  })

  it('argumentos: o selo do Product Marketing aparece quando aprovado', () => {
    render(
      <PainelDeArgumentos
        argumentario={argumentario({
          aprovado: true,
          selo: 'aprovado pelo Product Marketing',
        })}
        aoGerar={() => {}}
        carregando={false}
      />,
    )
    expect(screen.getByTestId('selo-pmm').textContent).toBe('aprovado pelo Product Marketing')
  })

  it('argumentos: sem aprovação, nenhum selo', () => {
    render(
      <PainelDeArgumentos argumentario={argumentario()} aoGerar={() => {}} carregando={false} />,
    )
    expect(screen.queryByTestId('selo-pmm')).toBeNull()
  })

  it('argumentos: os avisos do motor aparecem', () => {
    render(
      <PainelDeArgumentos
        argumentario={argumentario({
          avisos: ['menos de 3 dimensões com vantagem e dado comparável dos dois lados'],
        })}
        aoGerar={() => {}}
        carregando={false}
      />,
    )
    expect(screen.getByText(/menos de 3 dimensões/)).toBeTruthy()
  })

  it('argumentos: o botão chama o gerador', async () => {
    const aoGerar = vi.fn()
    render(<PainelDeArgumentos argumentario={undefined} aoGerar={aoGerar} carregando={false} />)
    await userEvent.click(screen.getByRole('button', { name: /gerar argumentos/ }))
    expect(aoGerar).toHaveBeenCalledOnce()
  })
})

describe('resultado: a numeração e o vocabulário', () => {
  const montar = () =>
    render(
      <PainelDeResultado
        sessao={sessao()}
        aoAbrir={() => {}}
        aoFechar={() => {}}
        salvando={false}
      />,
    )

  it('sem perda, o atributo decisivo é o passo 2 — a tela não pula do 1 para o 3', async () => {
    // QA-22: os números eram literais ("1.", "2.", "3.") e o passo 2 é condicional, então
    // com desfecho "fechou" (ou nenhum) a tela mostrava 1 e depois 3.
    montar()
    expect(screen.getByText(/^1\. Desfecho$/)).toBeTruthy()
    expect(screen.queryByText(/^3\. /)).toBeNull()
    expect(screen.getByLabelText('atributo decisivo')).toBeTruthy()
    expect(screen.getByText(/^2\. Atributo decisivo$/)).toBeTruthy()

    await userEvent.click(screen.getByRole('button', { name: 'fechou' }))
    expect(screen.queryByText(/^3\. /)).toBeNull()
    expect(screen.getByText(/^2\. Atributo decisivo$/)).toBeTruthy()
  })

  it('na perda, os motivos entram como 2 e o atributo vira 3', async () => {
    montar()
    await userEvent.click(screen.getByRole('button', { name: 'perdeu' }))
    expect(screen.getByText(/^2\. Por que perdeu$/)).toBeTruthy()
    expect(screen.getByText(/^3\. Atributo decisivo$/)).toBeTruthy()
    expect(screen.queryByText(/^2\. Atributo decisivo$/)).toBeNull()
  })

  it('o atributo decisivo não mostra nome de coluna do banco', () => {
    // O exemplo dizia `ex.: preco_sugerido_brl…` — nome de coluna na tela de quem vende.
    // Trocar só o exemplo por português quebraria o contador de Insights, que agrega por
    // string exata; por isso virou um seletor, que resolve os dois.
    montar()
    const seletor = screen.getByLabelText('atributo decisivo') as HTMLSelectElement
    const rotulos = [...seletor.options].map((o) => o.textContent ?? '')
    expect(rotulos.join(' ')).not.toMatch(/_/)
    expect(rotulos.some((r) => /Preço sugerido/i.test(r))).toBe(true)
    // …e o VALOR continua canônico, que é o que a API e o painel esperam.
    expect([...seletor.options].map((o) => o.value)).toContain('preco_sugerido_brl')
  })
})

describe('resultado: três toques e nenhum campo de cliente', () => {
  it('não tem campo de nome, telefone ou e-mail', () => {
    render(
      <PainelDeResultado
        sessao={sessao()}
        aoAbrir={() => {}}
        aoFechar={() => {}}
        salvando={false}
      />,
    )
    for (const proibido of ['nome', 'telefone', 'e-mail', 'email', 'CPF', 'cliente:']) {
      expect(screen.queryByLabelText(new RegExp(proibido, 'i'))).toBeNull()
    }
    // Os únicos controles são os três toques.
    expect(screen.getByTestId('resultado')).toBeTruthy()
    expect(screen.getByLabelText('atributo decisivo')).toBeTruthy()
  })

  it('resultado: diz na tela que a API recusa campo extra', () => {
    render(
      <PainelDeResultado
        sessao={sessao()}
        aoAbrir={() => {}}
        aoFechar={() => {}}
        salvando={false}
      />,
    )
    expect(screen.getByText(/recusa qualquer campo que não seja destes/)).toBeTruthy()
  })

  it('resultado: os motivos só aparecem quando o desfecho é perda', async () => {
    render(
      <PainelDeResultado
        sessao={sessao()}
        aoAbrir={() => {}}
        aoFechar={() => {}}
        salvando={false}
      />,
    )
    expect(screen.queryByTestId('motivos')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'perdeu' }))
    expect(screen.getByTestId('motivos')).toBeTruthy()

    await userEvent.click(screen.getByRole('button', { name: 'fechou' }))
    expect(screen.queryByTestId('motivos')).toBeNull()
  })

  it('resultado: os dez motivos do vocabulário estão na tela', async () => {
    render(
      <PainelDeResultado
        sessao={sessao()}
        aoAbrir={() => {}}
        aoFechar={() => {}}
        salvando={false}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'perdeu' }))
    const motivos = screen.getByTestId('motivos')
    expect(MOTIVOS_DE_PERDA.length).toBe(10)
    for (const motivo of MOTIVOS_DE_PERDA) {
      expect(motivos.textContent).toContain(motivo.rotulo)
    }
  })

  it('resultado: registra desfecho, motivos e atributo em três toques', async () => {
    const aoFechar = vi.fn()
    render(
      <PainelDeResultado
        sessao={sessao()}
        aoAbrir={() => {}}
        aoFechar={aoFechar}
        salvando={false}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'perdeu' }))
    await userEvent.click(screen.getByLabelText('preço'))
    // O atributo decisivo é um seletor desde 12/09/2026: o vendedor lê "Preço sugerido
    // (R$)" e o que viaja para a API continua sendo o nome canônico, que é o que o painel
    // de Insights conta por string exata.
    await userEvent.selectOptions(
      screen.getByLabelText('atributo decisivo'),
      'preco_sugerido_brl',
    )
    await userEvent.click(screen.getByRole('button', { name: /registrar resultado/ }))

    expect(aoFechar).toHaveBeenCalledWith({
      outcome: 'perdeu',
      motivos: ['preco'],
      atributo_decisivo: 'preco_sugerido_brl',
    })
  })

  it('resultado: fechou não manda motivos', async () => {
    const aoFechar = vi.fn()
    render(
      <PainelDeResultado
        sessao={sessao()}
        aoAbrir={() => {}}
        aoFechar={aoFechar}
        salvando={false}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'perdeu' }))
    await userEvent.click(screen.getByLabelText('preço'))
    await userEvent.click(screen.getByRole('button', { name: 'fechou' }))
    await userEvent.click(screen.getByRole('button', { name: /registrar resultado/ }))
    expect(aoFechar).toHaveBeenCalledWith({
      outcome: 'fechou',
      motivos: [],
      atributo_decisivo: undefined,
    })
  })

  it('resultado: sem desfecho o botão fica desabilitado', () => {
    render(
      <PainelDeResultado
        sessao={sessao()}
        aoAbrir={() => {}}
        aoFechar={() => {}}
        salvando={false}
      />,
    )
    expect(screen.getByRole('button', { name: /registrar resultado/ })).toBeDisabled()
  })

  it('resultado: sem sessão aberta, só o botão de abrir', async () => {
    const aoAbrir = vi.fn()
    render(
      <PainelDeResultado
        sessao={undefined}
        aoAbrir={aoAbrir}
        aoFechar={() => {}}
        salvando={false}
      />,
    )
    expect(screen.queryByTestId('resultado')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /abrir sessão/ }))
    expect(aoAbrir).toHaveBeenCalledOnce()
  })

  it('resultado: confirma o registro depois de salvar', () => {
    render(
      <PainelDeResultado
        sessao={sessao({
          outcome: 'perdeu',
          motivos: ['preco'],
          updated_at: '2026-09-09T12:30:00',
        })}
        aoAbrir={() => {}}
        aoFechar={() => {}}
        salvando={false}
      />,
    )
    const salvo = screen.getByTestId('resultado-salvo')
    expect(salvo.textContent).toContain('perdeu')
    expect(salvo.textContent).toContain('preco')
  })
})

describe('resultado: a recusa do servidor aparece na tela', () => {
  it('403 ao abrir sessão mostra o motivo em vez de nada acontecer', () => {
    /* O defeito: o **analista** não atende no salão e recebe 403 em
     * `criar_sessao_showroom` (matriz de `docs/12` §6.6). A regra está certa; o que
     * faltava era o aviso. Quem clicava em "abrir sessão" com o perfil errado via
     * **nada acontecer** — indistinguível de tela quebrada. O `ONBOARDING.md` tinha um
     * item de risco só para dizer isso ao vivo. */
    render(
      <PainelDeResultado
        sessao={undefined}
        aoAbrir={() => {}}
        aoFechar={() => {}}
        salvando={false}
        erroAoAbrir="Seu perfil não pode abrir a sessão de showroom. criar_sessao_showroom exige vendedor, gestor ou admin."
      />,
    )
    const recusa = screen.getByTestId('recusa-ao-abrir')
    expect(recusa.getAttribute('role')).toBe('alert')
    expect(recusa.textContent).toContain('Seu perfil não pode abrir a sessão')
    expect(recusa.textContent).toContain('vendedor, gestor ou admin')
    // O botão continua ali: a recusa informa, não esconde o caminho.
    expect(screen.getByRole('button', { name: 'abrir sessão' })).toBeTruthy()
  })

  it('sem erro, nenhuma faixa de recusa aparece', () => {
    render(
      <PainelDeResultado
        sessao={undefined}
        aoAbrir={() => {}}
        aoFechar={() => {}}
        salvando={false}
      />,
    )
    expect(screen.queryByTestId('recusa-ao-abrir')).toBeNull()
  })

  it('403 ao registrar o resultado também aparece', () => {
    render(
      <PainelDeResultado
        sessao={sessao()}
        aoAbrir={() => {}}
        aoFechar={() => {}}
        salvando={false}
        erroAoFechar="Seu perfil não pode registrar o resultado. registrar_desfecho exige vendedor, gestor ou admin."
      />,
    )
    expect(screen.getByTestId('recusa-ao-fechar').textContent).toContain(
      'não pode registrar o resultado',
    )
  })
})
