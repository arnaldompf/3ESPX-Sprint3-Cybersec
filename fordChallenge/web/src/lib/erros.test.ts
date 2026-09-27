/**
 * O erro do Simulador que parecia defeito do sistema e era escolha de seletor.
 *
 * O print do brief mostra a frase crua do back-end na tela: `preco_sugerido_brl não é
 * número neste veículo (valor atual: None)`. Quem lê entende que o produto quebrou. O que
 * houve foi outra coisa: o veículo aberto por padrão não tinha preço verificado.
 */

import { describe, expect, it } from 'vitest'

import { ErroDaApi } from './api'
import { limpar, mensagemDeErro, traduzir } from './erros'

describe('traduzir', () => {
  it('preço sem valor vira frase em português com o que fazer', () => {
    const detalhe =
      'preco_sugerido_brl não é número neste veículo (valor atual: None); ' +
      'variação percentual não se aplica. Use `novo_valor`.'
    expect(traduzir(detalhe)).toBe(
      'Este veículo não tem preço verificado. Escolha outro veículo ou informe um valor.',
    )
  })

  it('não inventa tradução para mensagem que não conhece', () => {
    expect(traduzir('a fonte respondeu 500')).toBeUndefined()
  })
})

describe('mensagemDeErro', () => {
  it('sem erro, não há frase', () => {
    expect(mensagemDeErro(null, 'simular o cenário')).toBeUndefined()
  })

  it('403 diz que é o perfil, não uma falha', () => {
    const erro = new ErroDaApi(403, 'Sem permissão', 'Esta tela é de gestor e administrador.')
    expect(mensagemDeErro(erro, 'ver o simulador')).toBe(
      'Seu perfil não pode ver o simulador. Esta tela é de gestor e administrador.',
    )
  })

  it('erro conhecido usa a tradução, sem a moldura genérica', () => {
    const erro = new ErroDaApi(422, 'Override inválido', 'preco_sugerido_brl não é número neste veículo (valor atual: None)')
    expect(mensagemDeErro(erro, 'simular o cenário')).toBe(
      'Este veículo não tem preço verificado. Escolha outro veículo ou informe um valor.',
    )
  })

  it('erro desconhecido mostra o texto do servidor, sem esconder nada', () => {
    const erro = new ErroDaApi(500, 'Erro', 'o banco não respondeu')
    expect(mensagemDeErro(erro, 'simular o cenário')).toBe(
      'Não foi possível simular o cenário: o banco não respondeu',
    )
  })

  it('erro que não é da API ainda assim dá uma frase, não um objeto', () => {
    expect(mensagemDeErro(new Error('boom'), 'comparar')).toBe(
      'Não foi possível comparar. Tente de novo.',
    )
  })
})

describe('limpar', () => {
  it('None não aparece na tela', () => {
    expect(limpar('valor atual: None')).toBe('valor atual: nenhum')
    expect(limpar('recebeu None do servidor')).toBe('recebeu nenhum valor do servidor')
  })
})
