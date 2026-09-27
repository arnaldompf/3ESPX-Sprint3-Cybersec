/**
 * Dois defeitos de tela, presos por teste.
 *
 * 1. **"Chevrolet S10 S10 High Country"**: o rótulo concatena marca, modelo e versão, e o
 *    catálogo guardava o modelo dentro do nome da versão.
 * 2. **o seletor abrindo numa versão vazia**: `lista[0]` é a primeira em ordem alfabética,
 *    e no catálogo real isso dava a S10 sem ficha — o Simulador abria mostrando um defeito
 *    que não existia.
 */

import { describe, expect, it } from 'vitest'

import type { Veiculo } from './tipos'
import {
  AMAROK,
  HILUX,
  PADRAO_CONCORRENTE,
  PADRAO_DA_MATRIZ,
  PADRAO_FORD,
  escolherPadrao,
  escolherPadroes,
  nomeCurto,
  nomeDoVeiculo,
  versaoSemOModelo,
} from './veiculos'

function veiculo(id: string, marca: string, modelo: string, versao: string): Veiculo {
  return { id, marca, modelo, versao, ano_modelo: 2026, in_lineup: true }
}

const CATALOGO: Veiculo[] = [
  veiculo('s10', 'Chevrolet', 'S10', 'High Country'),
  veiculo('s10-ltz', 'Chevrolet', 'S10', 'LTZ'),
  veiculo('limited', 'Ford', 'Ranger', 'Limited 3.0 V6 Diesel 4WD AT'),
  veiculo('raptor', 'Ford', 'Ranger', 'Raptor 3.0 V6 Bi-turbo 4WD AT'),
  veiculo('hilux', 'Toyota', 'Hilux', 'SRX Plus AT'),
  veiculo('amarok', 'Volkswagen', 'Amarok', 'V6 Extreme'),
]

describe('versaoSemOModelo', () => {
  it('tira o modelo repetido no começo', () => {
    expect(versaoSemOModelo('S10', 'S10 High Country')).toBe('High Country')
  })

  it('não mexe no que já está certo', () => {
    expect(versaoSemOModelo('Ranger', 'Raptor 3.0 V6 Bi-turbo 4WD AT')).toBe(
      'Raptor 3.0 V6 Bi-turbo 4WD AT',
    )
  })

  it('só corta token inteiro: "S10X Sport" não é uma S10 com nome "X Sport"', () => {
    expect(versaoSemOModelo('S10', 'S10X Sport')).toBe('S10X Sport')
  })

  it('não esvazia o nome de uma versão chamada como o modelo', () => {
    expect(versaoSemOModelo('S10', 'S10')).toBe('S10')
  })
})

describe('nomeDoVeiculo', () => {
  it('não repete o modelo', () => {
    expect(nomeDoVeiculo(veiculo('x', 'Chevrolet', 'S10', 'S10 High Country'))).toBe(
      'Chevrolet S10 High Country',
    )
  })

  it('o caso já correto continua igual', () => {
    expect(nomeDoVeiculo(veiculo('x', 'Toyota', 'Hilux', 'SRX Plus AT'))).toBe(
      'Toyota Hilux SRX Plus AT',
    )
  })

  it('o nome curto deixa a marca de fora', () => {
    expect(nomeCurto(veiculo('x', 'Chevrolet', 'S10', 'S10 High Country'))).toBe('S10 High Country')
  })
})

describe('escolherPadrao', () => {
  it('a Ford padrão é a diesel de topo, não a primeira em ordem alfabética', () => {
    expect(escolherPadrao(CATALOGO, PADRAO_FORD)).toBe('limited')
  })

  it('o concorrente padrão é a Hilux', () => {
    expect(escolherPadrao(CATALOGO, PADRAO_CONCORRENTE)).toBe('hilux')
  })

  it('sem a preferida no catálogo, cai para a primeira da lista', () => {
    const semHilux = CATALOGO.filter((v) => v.id !== 'hilux')
    expect(escolherPadrao(semHilux, [HILUX])).toBe('s10')
  })

  it('lista vazia devolve vazio, e nenhuma consulta é disparada', () => {
    expect(escolherPadrao([], PADRAO_FORD)).toBe('')
  })

  it('acha mesmo com o modelo repetido no nome do catálogo', () => {
    const naoMigrado = [veiculo('s10', 'Chevrolet', 'S10', 'S10 High Country')]
    expect(escolherPadrao(naoMigrado, PADRAO_CONCORRENTE)).toBe('s10')
  })
})

describe('escolherPadroes', () => {
  it('a Matriz abre com os três concorrentes que têm ficha', () => {
    expect(escolherPadroes(CATALOGO, PADRAO_DA_MATRIZ, 3)).toEqual(['hilux', 'amarok', 's10'])
  })

  it('completa com o começo da lista quando faltam preferidas', () => {
    const escolhidos = escolherPadroes(CATALOGO, [AMAROK], 3)
    expect(escolhidos[0]).toBe('amarok')
    expect(escolhidos).toHaveLength(3)
    expect(new Set(escolhidos).size).toBe(3)
  })

  it('nunca devolve mais do que o pedido', () => {
    expect(escolherPadroes(CATALOGO, PADRAO_DA_MATRIZ, 2)).toHaveLength(2)
  })
})
