/**
 * A trilha da conversa: agrupada por rodada, com a linha em gerúndio, as descartadas
 * recolhidas com o motivo e os cartões de fonte com o estado que os eventos deram.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { fontesDaTrilha } from './CartoesDeFonte'
import { Trilha, agruparPorRodada, textoDoPasso } from './Trilha'
import type { EventoDePesquisa, TrilhaDePesquisa } from '@/lib/tipos'

let ordem = 0
function evento(
  tipo: string,
  dados: Record<string, unknown> = {},
  extra: Partial<EventoDePesquisa> = {},
): EventoDePesquisa {
  ordem += 1
  return {
    ordem,
    tipo,
    texto: extra.texto ?? `evento ${tipo}`,
    etiqueta: tipo === 'fonte_escolhida' || tipo === 'fonte_descartada' ? 'INFERENCIA' : 'FATO',
    rodada: 1,
    decorrido: ordem * 1.5,
    dados,
    ...extra,
  }
}

const FORD = 'https://www.ford.com.br/picapes/ranger/'
const BLOG = 'https://blog-qualquer.com/ranger'
const REVISTA = 'https://quatrorodas.abril.com.br/ranger'

function eventos(): EventoDePesquisa[] {
  ordem = 0
  return [
    evento('inicio', { veiculo: 'Ford Ranger Raptor' }, { rodada: 0 }),
    evento('rodada', { consultas: ['ficha técnica Ranger Raptor'] }),
    evento('consulta', { consulta: 'ficha técnica Ranger Raptor', tier: 1 }),
    evento('resultados', { quantos: 7 }),
    evento('fonte_escolhida', { url: FORD, dominio: 'ford.com.br', tier: 1, motivo: 'site oficial da montadora' }),
    evento('fonte_escolhida', { url: REVISTA, dominio: 'quatrorodas.abril.com.br', tier: 2, motivo: 'imprensa especializada' }),
    evento('fonte_descartada', { url: BLOG, dominio: 'blog-qualquer.com', tier: 4, motivo: 'domínio sem reputação' }, { texto: 'descartada blog-qualquer.com: domínio sem reputação' }),
    evento('baixando', { url: FORD, dominio: 'ford.com.br' }),
    evento('baixada', { url: FORD, caracteres: 12345 }),
    evento('fonte_bloqueada', { url: REVISTA, tier: 2 }, { texto: 'quatrorodas.abril.com.br bloqueou a coleta' }),
    evento('campo', { campo: 'potencia_cv', valor: 397, unit: 'cv', url: FORD, tier: 1 }),
    evento('cobertura', { total: 40, respondidos: 12 }, { rodada: 2 }),
    evento('lacuna', { faltando: ['torque_nm', 'peso_kg', 'preco_sugerido_brl'] }, { rodada: 2 }),
  ]
}

function trilha(lista: EventoDePesquisa[], extra: Partial<TrilhaDePesquisa> = {}): TrilhaDePesquisa {
  return {
    run_id: 'run-1',
    status: 'rodando',
    veiculo: 'Ford Ranger Raptor',
    motivo_da_parada: '',
    campos_com_valor: 12,
    campos_alvo: 40,
    paginas: 1,
    rodadas: 2,
    segundos: 20,
    eventos: lista,
    ...extra,
  }
}

describe('agrupar por rodada', () => {
  it('junta eventos consecutivos da mesma rodada, na ordem', () => {
    const grupos = agruparPorRodada(eventos())
    expect(grupos.map((g) => g.rodada)).toEqual([0, 1, 2])
    expect(grupos[1]!.eventos).toHaveLength(10)
  })
})

describe('o texto do passo', () => {
  it('o evento campo vira "campo: valor unidade · domínio (tier)"', () => {
    const [campo] = eventos().filter((e) => e.tipo === 'campo')
    expect(textoDoPasso(campo!)).toBe('Potência (cv): 397 cv · ford.com.br (tier 1)')
  })

  it('os demais vêm prontos do servidor', () => {
    const [consulta] = eventos().filter((e) => e.tipo === 'consulta')
    expect(textoDoPasso(consulta!)).toBe('evento consulta')
  })
})

describe('as fontes escolhidas', () => {
  it('dá a cada URL o estado que os eventos seguintes disseram', () => {
    const fontes = fontesDaTrilha(eventos())
    expect(fontes).toHaveLength(2)
    expect(fontes[0]).toMatchObject({ dominio: 'ford.com.br', tier: 1, estado: 'baixada' })
    expect(fontes[0]!.detalhe).toContain('12.345')
    expect(fontes[1]).toMatchObject({ dominio: 'quatrorodas.abril.com.br', estado: 'bloqueada' })
  })

  it('a descartada não vira cartão', () => {
    expect(fontesDaTrilha(eventos()).some((f) => f.url === BLOG)).toBe(false)
  })
})

describe('a trilha rodando', () => {
  it('agrupa por rodada, abre os grupos e diz o que está fazendo agora', () => {
    render(<Trilha trilha={trilha(eventos())} rodando />)

    expect(screen.getByTestId('trilha-ao-vivo')).toHaveTextContent('Pesquisando · 13 passos')
    expect(screen.getByTestId('linha-de-estado')).toHaveTextContent(
      'Faltam 3 campos; procurando torque (N·m), peso (kg)…',
    )
    expect(screen.getByTestId('rodada-0')).toBeInTheDocument()
    expect(screen.getByTestId('rodada-1')).toBeInTheDocument()
    expect(screen.getByTestId('rodada-2')).toBeInTheDocument()
    // Aberto enquanto roda: os passos estão na tela.
    expect(screen.getByTestId('passo-consulta')).toBeInTheDocument()
    expect(screen.getByTestId('passo-campo')).toHaveTextContent('Potência (cv): 397 cv')
    // Todo passo leva etiqueta.
    const rodada1 = screen.getByTestId('rodada-1')
    expect(within(rodada1).getAllByTestId(/^badge-/).length).toBeGreaterThan(5)
  })

  it('as descartadas ficam recolhidas, com o motivo a um clique', async () => {
    render(<Trilha trilha={trilha(eventos())} rodando />)

    expect(screen.queryByTestId('passo-fonte_descartada')).toBeNull()
    const botao = screen.getByTestId('ver-descartadas')
    expect(botao).toHaveTextContent('1 fonte descartada (por quê)')

    await userEvent.click(botao)
    expect(screen.getByTestId('passo-fonte_descartada')).toHaveTextContent('domínio sem reputação')
  })

  it('os cartões de fonte mostram domínio, tier, motivo e o estado observado', () => {
    render(<Trilha trilha={trilha(eventos())} rodando />)

    const cartoes = screen.getAllByTestId('cartao-de-fonte')
    expect(cartoes).toHaveLength(2)
    expect(cartoes[0]).toHaveTextContent('ford.com.br')
    expect(cartoes[0]).toHaveTextContent('tier 1')
    expect(cartoes[0]).toHaveTextContent('site oficial da montadora')
    expect(cartoes[0]).toHaveAttribute('data-estado', 'baixada')
    expect(within(cartoes[0]!).getByTestId('badge-INFERENCIA')).toBeInTheDocument()
    expect(within(cartoes[0]!).getByRole('link', { name: 'abrir a página' })).toHaveAttribute('href', FORD)
    expect(cartoes[1]).toHaveAttribute('data-estado', 'bloqueada')
  })

  it('sem trilha ainda, diz que está começando', () => {
    render(<Trilha trilha={null} rodando />)
    expect(screen.getByTestId('linha-de-estado')).toHaveTextContent('Começando…')
    expect(screen.getByTestId('trilha-ao-vivo')).toHaveTextContent('0 passos')
  })
})

describe('a trilha concluída', () => {
  it('recolhe tudo e reabre ao clicar no cabeçalho', async () => {
    render(<Trilha trilha={trilha(eventos(), { status: 'concluida' })} rodando={false} />)

    const cabecalho = screen.getByRole('button', { name: /Concluída · 13 passos/ })
    expect(cabecalho).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('linha-de-estado')).toBeNull()
    expect(screen.queryByTestId('passo-consulta')).toBeNull()

    await userEvent.click(cabecalho)
    expect(screen.getByTestId('contadores-da-pesquisa')).toBeInTheDocument()
    // Os grupos também nascem recolhidos quando a pesquisa acabou.
    expect(screen.queryByTestId('passo-consulta')).toBeNull()
    await userEvent.click(within(screen.getByTestId('rodada-1')).getByRole('button'))
    expect(screen.getByTestId('passo-consulta')).toBeInTheDocument()
  })
})
