/**
 * O papel: onde ele fica, como ele viaja e o que acontece quando ele muda.
 *
 * Estes testes substituem `sessao.test.ts`, que travava a renovação de token depois do
 * Ctrl+F5 (D-186). Aquele mecanismo inteiro deixou de existir quando a entrada deixou de
 * pedir credencial (D-204) — o que sobrou para travar é mais simples e mais visível: o
 * papel sobrevive ao recarregamento, vai em `X-Role` em **toda** chamada, e quem o
 * escolhe é a barra lateral.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from './api'
import {
  CABECALHO_PAPEL,
  PAPEIS,
  PAPEL_INICIAL,
  assinar,
  definirPapel,
  esquecerPapel,
  papelAtual,
} from './papel'

function servidor() {
  const cabecalhos: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      cabecalhos.push(new Headers(init?.headers as HeadersInit).get(CABECALHO_PAPEL) ?? '')
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return cabecalhos
}

beforeEach(() => {
  esquecerPapel()
})

afterEach(() => {
  vi.unstubAllGlobals()
  esquecerPapel()
})

describe('onde o papel fica', () => {
  it('sem nada guardado, abre no papel inicial', () => {
    expect(papelAtual()).toBe(PAPEL_INICIAL)
  })

  it('sobrevive ao fechar o navegador: fica em localStorage, nao em sessionStorage', () => {
    definirPapel('gestor')
    // Simula a aba nova: a memória do módulo some, o `localStorage` fica.
    esquecerPapelSoDaMemoria()
    expect(papelAtual()).toBe('gestor')
  })

  it('valor estranho no armazenamento nao derruba a tela: cai no inicial', () => {
    localStorage.setItem('specradar.papel', 'sindico')
    esquecerPapelSoDaMemoria()
    expect(papelAtual()).toBe(PAPEL_INICIAL)
  })

  it('armazenamento bloqueado nao quebra nada', () => {
    const guardar = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('armazenamento bloqueado')
    })
    expect(() => definirPapel('admin')).not.toThrow()
    expect(papelAtual()).toBe('admin')
    guardar.mockRestore()
  })
})

describe('quem muda avisa', () => {
  it('chama quem assinou, uma vez por troca', () => {
    const visto: string[] = []
    const cancelar = assinar((papel) => visto.push(papel))
    definirPapel('gestor')
    definirPapel('gestor') // trocar para o mesmo nao e troca
    definirPapel('vendedor')
    cancelar()
    definirPapel('admin')
    expect(visto).toEqual(['gestor', 'vendedor'])
  })
})

describe('o papel viaja em X-Role', () => {
  it('vai em toda chamada, e acompanha a troca', async () => {
    const cabecalhos = servidor()
    await api.veiculos()
    definirPapel('gestor')
    await api.veiculos()
    expect(cabecalhos).toEqual([PAPEL_INICIAL, 'gestor'])
  })

  it('os quatro papeis viajam escritos como a API os espera', async () => {
    const cabecalhos = servidor()
    for (const papel of PAPEIS) {
      definirPapel(papel)
      await api.veiculos()
    }
    expect(cabecalhos).toEqual([...PAPEIS])
  })

  it('nao ha Authorization: nao ha token para mandar', async () => {
    const cabecalhos: (string | null)[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        cabecalhos.push(new Headers(init?.headers as HeadersInit).get('Authorization'))
        return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
      }),
    )
    await api.veiculos()
    expect(cabecalhos).toEqual([null])
  })
})

/** Esquece só a memória do módulo, mantendo o que está no navegador. */
function esquecerPapelSoDaMemoria() {
  const guardado = localStorage.getItem('specradar.papel')
  esquecerPapel()
  if (guardado !== null) localStorage.setItem('specradar.papel', guardado)
}
