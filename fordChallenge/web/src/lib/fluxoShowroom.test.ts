/**
 * O fluxo do Showroom sobrevive à troca de tela — e não vaza para a conversa seguinte.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { FLUXO_PADRAO, gravarFluxo, lerFluxo, limparFluxo } from './fluxoShowroom'

describe('fluxo do showroom', () => {
  beforeEach(() => {
    limparFluxo()
  })

  it('sem nada guardado, devolve o padrão', () => {
    expect(lerFluxo()).toEqual(FLUXO_PADRAO)
  })

  it('grava e lê de volta o mesmo fluxo', () => {
    const fluxo = {
      ...FLUXO_PADRAO,
      base: 'v-ford',
      concorrente: 'v-conc',
      usos: ['rural_carga'],
      ranking: ['capacidade', 'preco'],
      passo: 2,
    }
    gravarFluxo(fluxo)
    expect(lerFluxo()).toEqual(fluxo)
  })

  it('formato de versão anterior é descartado, não migrado', () => {
    // Migrar meio estado traria de volta um par que talvez nem exista mais no catálogo, e
    // a tela abriria com um seletor apontando para o nada.
    sessionStorage.setItem('specradar.showroom.fluxo', JSON.stringify({ v: 0, fluxo: { base: 'x' } }))
    expect(lerFluxo()).toEqual(FLUXO_PADRAO)
  })

  it('JSON corrompido não derruba a tela', () => {
    sessionStorage.setItem('specradar.showroom.fluxo', '{isto não é json')
    expect(lerFluxo()).toEqual(FLUXO_PADRAO)
  })

  it('campo de tipo errado cai no padrão, campo a campo', () => {
    sessionStorage.setItem(
      'specradar.showroom.fluxo',
      JSON.stringify({ v: 1, fluxo: { base: 42, usos: 'rural', passo: 'dois', kmMes: '900' } }),
    )
    const fluxo = lerFluxo()
    expect(fluxo.base).toBe('')
    expect(fluxo.usos).toEqual([])
    expect(fluxo.passo).toBe(0)
    expect(fluxo.kmMes).toBe('900')
  })

  it('armazenamento bloqueado degrada em vez de quebrar', () => {
    const erro = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('bloqueado')
    })
    expect(() => lerFluxo()).not.toThrow()
    expect(lerFluxo()).toEqual(FLUXO_PADRAO)
    erro.mockRestore()

    const gravar = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('bloqueado')
    })
    expect(() => gravarFluxo(FLUXO_PADRAO)).not.toThrow()
    gravar.mockRestore()
  })

  it('usa sessionStorage, e não localStorage: o fluxo é de UMA conversa', () => {
    // `localStorage` faria o próximo cliente herdar o perfil do anterior.
    gravarFluxo({ ...FLUXO_PADRAO, base: 'v-ford' })
    expect(sessionStorage.getItem('specradar.showroom.fluxo')).toContain('v-ford')
    expect(localStorage.getItem('specradar.showroom.fluxo')).toBeNull()
  })
})
