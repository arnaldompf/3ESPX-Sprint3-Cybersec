/**
 * O contador que sobe, a foto que não empurra o layout, e o botão que diz que trabalha.
 *
 * As três coisas têm a mesma justificativa: movimento e imagem só entram quando explicam
 * alguma coisa, e nunca à custa do dado. O que estes testes travam é justamente o custo —
 * que o valor final esteja no DOM desde o primeiro quadro, que a moldura da foto reserve
 * o espaço antes da imagem chegar, e que o botão não mude de tamanho ao processar.
 */

import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Botao } from './Botao'
import { Contador } from './Contador'
import { FotoDoVeiculo } from './Foto'
import { atrasoDaLinha, MAXIMO_ESCALONADO, PASSO_DO_ESCALONAMENTO_MS } from '@/lib/movimento'
import { fotoDe, fotoDoRotulo } from '@/lib/fotos'

/** `matchMedia` do jsdom não existe: quem pergunta por movimento precisa de resposta. */
function preferencia(menosMovimento: boolean) {
  vi.stubGlobal('matchMedia', (consulta: string) => ({
    matches: menosMovimento && consulta.includes('reduce'),
    media: consulta,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('o contador', () => {
  it('carrega o valor final em data-valor desde o primeiro quadro', () => {
    /* É disto que o teste de tela lê. Sem o atributo, quem lê o texto no meio da subida
     * compara "12 campos" com "30 botões de evidência" e falha por um defeito que não
     * existe — a contagem termina em 400 ms e o número é o mesmo. */
    preferencia(false)
    const { container } = render(<Contador valor={58} />)
    expect(container.querySelector('[data-valor="58"]')).toBeTruthy()
  })

  it('com prefers-reduced-motion o numero aparece pronto, sem subir', () => {
    preferencia(true)
    render(<Contador valor={42} />)
    expect(screen.getByText('42')).toBeTruthy()
  })

  it('respeita o formatador: separador de milhar e nao "1234"', () => {
    preferencia(true)
    render(<Contador valor={379990} formatar={(n) => n.toLocaleString('pt-BR')} />)
    expect(screen.getByText('379.990')).toBeTruthy()
  })
})

describe('o escalonamento das linhas', () => {
  it('30 ms por linha', () => {
    expect(atrasoDaLinha(0)).toBe('0ms')
    expect(atrasoDaLinha(3)).toBe(`${3 * PASSO_DO_ESCALONAMENTO_MS}ms`)
  })

  it('para de crescer na decima: a quadragesima linha e dado, nao cortina', () => {
    const teto = `${MAXIMO_ESCALONADO * PASSO_DO_ESCALONAMENTO_MS}ms`
    expect(atrasoDaLinha(MAXIMO_ESCALONADO)).toBe(teto)
    expect(atrasoDaLinha(40)).toBe(teto)
  })
})

describe('a foto do veiculo', () => {
  it('acha a foto pelos tres campos do catalogo', () => {
    expect(fotoDe({ marca: 'Ford', modelo: 'Ranger', versao: 'Raptor 3.0 V6 Bi-turbo 4WD AT' }))
      .toBe('/app/img/veiculos/ranger-raptor.webp')
    expect(fotoDe({ marca: 'Chevrolet', modelo: 'S10', versao: 'High Country' })).toBe(
      '/app/img/veiculos/s10-high-country.webp',
    )
  })

  it('acha a foto tambem pelo rotulo ja montado', () => {
    expect(fotoDoRotulo('Volkswagen Amarok V6 Extreme')).toBe(
      '/app/img/veiculos/amarok-v6-extreme.webp',
    )
  })

  it('veiculo sem foto nao desenha moldura nenhuma', () => {
    /* Um quadro vazio anunciando "sem ilustração" ocuparia espaço para dizer nada. */
    expect(fotoDe({ marca: 'Fiat', modelo: 'Toro', versao: 'Ranch' })).toBeUndefined()
    const { container } = render(<FotoDoVeiculo src={undefined} alt="Fiat Toro" />)
    expect(container.innerHTML).toBe('')
  })

  it('a moldura reserva o espaco antes de a imagem chegar', () => {
    /* Sem `aspect-ratio` na moldura, a chegada da foto empurra o que está embaixo e a
     * pessoa clica no lugar errado. */
    const { container } = render(
      <FotoDoVeiculo src="/app/img/veiculos/ranger-raptor.webp" alt="Ford Ranger Raptor" />,
    )
    const imagem = container.querySelector('img')
    expect(imagem?.className).toContain('aspect-[16/9]')
    expect(imagem?.getAttribute('loading')).toBe('lazy')
  })

  it('a foto leva credito, sempre', () => {
    render(<FotoDoVeiculo src="/app/img/veiculos/hilux-srx-plus.webp" alt="Toyota Hilux" />)
    expect(screen.getByText(/Divulgação oficial das montadoras/)).toBeTruthy()
  })
})

describe('o botao que processa', () => {
  it('mostra que trabalha, sem trocar o rotulo', () => {
    /* Trocar "gerar documento" por "carregando…" muda a largura do botão no instante do
     * clique: o layout pula e o próximo alvo se move. */
    render(
      <Botao tom="primario" carregando>
        gerar documento
      </Botao>,
    )
    const botao = screen.getByRole('button', { name: /gerar documento/ })
    expect(botao.getAttribute('aria-busy')).toBe('true')
    expect(botao).toBeDisabled()
    expect(screen.getByTestId('processando')).toBeTruthy()
  })

  it('sem carregando, nenhum traco girando e o botao clica', () => {
    render(<Botao tom="primario">gerar documento</Botao>)
    expect(screen.queryByTestId('processando')).toBeNull()
    expect(screen.getByRole('button')).not.toBeDisabled()
  })
})
