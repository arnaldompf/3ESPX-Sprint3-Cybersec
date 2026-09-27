/**
 * O valor como se lê — e os dois casos em que "como se lê" já esteve errado na tela.
 *
 * `formatarValor` é usada pela ficha, pelo radar, pela matriz e pelo cartão da Pesquisa.
 * Ela não tinha teste próprio: a garantia vivia espalhada nos testes das telas, que a
 * exercitam de passagem e não cobrem os cantos.
 */

import { describe, expect, it } from 'vitest'

import { VAZIO, formatarValor } from './formato'

describe('formatarValor', () => {
  it('`false` e `0` não são vazio', () => {
    // Um `if (!valor)` transformaria "não tem teto solar" em "não sabemos se tem" — a
    // confusão entre os dois vazios que o projeto existe para acabar.
    expect(formatarValor(false)).toBe('não')
    expect(formatarValor(0)).toBe('0')
    expect(formatarValor(null)).toBe(VAZIO)
    expect(formatarValor(undefined)).toBe(VAZIO)
  })

  it('o `_` do valor canônico é separador de palavra, não conteúdo', () => {
    expect(formatarValor('3.0l_v6_bi_turbo')).toBe('3.0l v6 bi turbo')
    expect(formatarValor(['4x4', 'reduzida_sob_demanda'])).toBe('4x4 · reduzida sob demanda')
  })

  it('a unidade vem depois do valor', () => {
    expect(formatarValor(397, 'cv')).toBe('397 cv')
    expect(formatarValor(1234, 'kg')).toBe('1.234 kg')
  })
})

describe('ano não leva separador de milhar', () => {
  it('o ano-modelo sai inteiro, e não "2.026"', () => {
    // Visto na tela em 13/09/2026, no cartão da Frontier pesquisada ao vivo: "Ano modelo
    // 2.025". Ninguém escreve "2.026" para dizer 2026, e o ponto faz o número parecer
    // outro — numa ficha cujo produto é o número estar certo.
    expect(formatarValor(2026, null, 'ano_modelo')).toBe('2026')
    expect(formatarValor(2025, undefined, 'ano')).toBe('2025')
  })

  it('a exceção é por campo, não por faixa de valor', () => {
    // Adivinhar pelo intervalo (1900–2100) transformaria uma carga de 2.000 kg em
    // "2000 kg" no dia em que alguém esquecesse a unidade.
    expect(formatarValor(2000, 'kg', 'capacidade_carga_kg')).toBe('2.000 kg')
    expect(formatarValor(2026, null)).toBe('2.026')
  })
})
