/**
 * A regra visual mais importante do produto, testada: **nenhum número sem etiqueta**, e
 * cada status na etiqueta certa.
 *
 * O teste que mais importa aqui é o de `divergente` → FATO. É a escolha menos óbvia da
 * tabela: os dois valores têm evidência, e o que falta é concordância, não prova. Chamar
 * isso de inferência sugeriria que o sistema deduziu algo, quando na verdade duas fontes
 * oficiais discordam.
 */

import { describe, expect, it } from 'vitest'

import {
  CLASSES,
  COR_DO_PONTO,
  EXPLICACAO,
  ICONE,
  ROTULO,
  ROTULO_DE_STATUS,
  etiquetaDe,
  explicacaoDoVazio,
} from './etiqueta'
import type { Campo, Status } from './tipos'

const TODOS: Status[] = [
  'verificado',
  'nao_verificado',
  'nao_disponivel',
  'nao_encontrado',
  'divergente',
  'pendente',
]

/**
 * O mapa de status só decide quando **há valor**.
 *
 * Todo caso aqui passa um `value`, e isso não é cerimônia: desde 12/09/2026 a ausência de
 * valor vence o status (ver o bloco "SEM DADO" no fim do arquivo). Um teste que omitisse
 * o valor estaria medindo a outra regra sem dizer.
 */
const comValor = (status: Status, extra: Record<string, unknown> = {}) =>
  ({ status, value: 397, is_simulated: false, ...extra }) as Campo

describe('etiquetaDe, quando o campo TEM valor', () => {
  it('valor com evidência é FATO', () => {
    expect(etiquetaDe(comValor('verificado'))).toBe('FATO')
  })

  it('divergente é FATO, porque os dois valores têm evidência', () => {
    expect(etiquetaDe(comValor('divergente'))).toBe('FATO')
  })

  it('nao_disponivel COM valor é FATO: é fato negativo, a fonte afirma que não existe', () => {
    // Na prática `nao_disponivel` costuma vir vazio, e aí é SEM DADO com o motivo "não
    // disponível segundo a montadora". O mapa continua existindo para o caso em que a
    // fonte afirma a ausência **e** registra algo no lugar.
    expect(etiquetaDe(comValor('nao_disponivel'))).toBe('FATO')
  })

  it('nao_encontrado COM valor é INFERÊNCIA: a leitura é nossa', () => {
    expect(etiquetaDe(comValor('nao_encontrado'))).toBe('INFERENCIA')
  })

  it.each(['nao_verificado', 'pendente'] as const)('%s é INFERÊNCIA', (status) => {
    expect(etiquetaDe(comValor(status))).toBe('INFERENCIA')
  })

  it('is_simulated vence QUALQUER status', () => {
    for (const status of TODOS) {
      expect(etiquetaDe(comValor(status, { is_simulated: true }))).toBe('SIMULACAO')
    }
  })

  it('todo status conhecido tem etiqueta', () => {
    for (const status of TODOS) {
      expect(['FATO', 'INFERENCIA', 'SIMULACAO']).toContain(etiquetaDe(comValor(status)))
    }
  })

  it('status desconhecido cai em INFERÊNCIA, nunca em FATO', () => {
    // Nunca afirmar por omissão: um status novo no back-end não pode virar "FATO" só
    // porque a tela não o conhece.
    expect(etiquetaDe(comValor('algo_novo' as Status))).toBe('INFERENCIA')
  })
})

describe('cada etiqueta tem cor, ícone, texto e explicação', () => {
  const TODAS = ['FATO', 'INFERENCIA', 'SIMULACAO', 'SEM_DADO', 'CATALOGO'] as const

  it.each(TODAS)('%s', (etiqueta) => {
    // Ícone além da cor: verde e laranja são o par clássico de confusão em daltonismo, e
    // a etiqueta é a informação mais importante da tela.
    expect(ICONE[etiqueta]).toBeTruthy()
    expect(ROTULO[etiqueta]).toBeTruthy()
    expect(EXPLICACAO[etiqueta].length).toBeGreaterThan(20)
  })

  it('o rótulo sai acentuado, como se lê em português', () => {
    expect(ROTULO.INFERENCIA).toBe('INFERÊNCIA')
    expect(ROTULO.SIMULACAO).toBe('SIMULAÇÃO')
  })
})

describe('os dois vazios não se confundem', () => {
  it('nao_disponivel diz que a FONTE afirma a ausência', () => {
    const frase = explicacaoDoVazio('nao_disponivel', ['ford_site'])
    expect(frase).toMatch(/fonte oficial afirma/i)
  })

  it('nao_encontrado diz que NINGUÉM mencionou, e conta as fontes', () => {
    const frase = explicacaoDoVazio('nao_encontrado', ['a', 'b', 'c'])
    expect(frase).toMatch(/3 fonte/)
    expect(frase).toMatch(/menciona/i)
  })

  it('as duas frases são diferentes — é o ponto do schema canônico', () => {
    expect(explicacaoDoVazio('nao_disponivel', ['a'])).not.toBe(
      explicacaoDoVazio('nao_encontrado', ['a']),
    )
  })

  it('sem fonte consultada, a frase não inventa um número', () => {
    expect(explicacaoDoVazio('nao_encontrado', [])).not.toMatch(/\d/)
  })

  it('todo status tem rótulo humano', () => {
    for (const status of TODOS) {
      expect(ROTULO_DE_STATUS[status]).toBeTruthy()
    }
  })
})

/* ------------------------------------------------------ a quarta marca: SEM DADO
 *
 * Um avaliador usou o sistema em 12/09/2026 e viu, na ficha, campos que diziam
 * literalmente "sem valor" ao lado de um pill azul **INFERÊNCIA** — e, pior, campos
 * `nao_disponivel` vazios com o pill verde **FATO**. Um vazio pintado de verde é a leitura
 * mais perigosa possível para quem está num showroom com o cliente ao lado.
 *
 * A regra que estes testes fixam: **FATO, INFERÊNCIA e SIMULAÇÃO qualificam um VALOR.**
 * A ausência de valor tem marca própria, neutra, e vem acompanhada do motivo.
 */
describe('SEM DADO: ausência não é inferência', () => {
  const vazio = (status: Status, extra: Partial<Campo> = {}) =>
    ({ status, value: null, is_simulated: false, sources_checked: [], ...extra }) as Campo

  it('campo sem valor nunca recebe marca de valor, qualquer que seja o status', () => {
    for (const status of [
      'verificado',
      'divergente',
      'nao_disponivel',
      'nao_encontrado',
      'nao_verificado',
      'pendente',
    ] as Status[]) {
      expect(etiquetaDe(vazio(status)), `status ${status}`).toBe('SEM_DADO')
    }
  })

  it('nem quando o campo é simulado — vazio simulado continua vazio', () => {
    // Pintar de laranja "SIMULAÇÃO" um campo sem valor repete o mesmo erro de categoria,
    // só com outra cor: a simulação seria de quê, se não há valor nenhum?
    expect(etiquetaDe(vazio('nao_encontrado', { is_simulated: true }))).toBe('SEM_DADO')
  })

  it('valor `undefined` conta como vazio, e valor 0 ou "" não', () => {
    expect(etiquetaDe({ status: 'verificado', is_simulated: false } as Campo)).toBe('SEM_DADO')
    // Zero é um valor: capacidade de reboque 0 kg é uma afirmação, não uma ausência.
    expect(etiquetaDe({ status: 'verificado', value: 0, is_simulated: false } as Campo)).toBe(
      'FATO',
    )
  })

  it('campo COM valor continua decidindo pelo status, como antes', () => {
    const com = (status: Status, is_simulated = false) =>
      ({ status, value: 397, is_simulated }) as Campo
    expect(etiquetaDe(com('verificado'))).toBe('FATO')
    expect(etiquetaDe(com('divergente'))).toBe('FATO')
    expect(etiquetaDe(com('nao_verificado'))).toBe('INFERENCIA')
    expect(etiquetaDe(com('verificado', true))).toBe('SIMULACAO')
  })

  it('valor vindo do catálogo recebe CATÁLOGO, não INFERÊNCIA nem FATO', () => {
    // Marca, modelo, versão, ano-modelo e código FIPE são a identidade da versão
    // consultada. "INFERÊNCIA" mentiria sobre o método (nada foi inferido) e "FATO"
    // mentiria sobre a prova (não há trecho verbatim).
    const doCatalogo = {
      status: 'nao_verificado',
      value: 'Ford',
      is_simulated: false,
      origem: 'catalogo',
    } as Campo
    expect(etiquetaDe(doCatalogo)).toBe('CATALOGO')
    expect(ROTULO.CATALOGO).toBe('CATÁLOGO')
    expect(CLASSES.CATALOGO).toContain('catalogo')
  })

  it('catálogo sem valor continua SEM DADO — a origem não cria valor', () => {
    expect(
      etiquetaDe({ status: 'nao_encontrado', value: null, origem: 'catalogo' } as Campo),
    ).toBe('SEM_DADO')
  })

  it('evidência vence catálogo: campo verificado sem origem é FATO', () => {
    expect(etiquetaDe({ status: 'verificado', value: 2027, origem: null } as Campo)).toBe('FATO')
  })

  it('a marca nova tem rótulo, ícone, explicação e as duas classes de cor', () => {
    expect(ROTULO.SEM_DADO).toBe('SEM DADO')
    expect(ICONE.SEM_DADO).toBeTruthy()
    expect(ICONE.SEM_DADO).not.toBe(ICONE.FATO)
    expect(EXPLICACAO.SEM_DADO.length).toBeGreaterThan(20)
    expect(CLASSES.SEM_DADO).toContain('semdado')
    expect(COR_DO_PONTO.SEM_DADO).toContain('semdado')
  })

  it('o motivo do vazio distingue os dois vazios, que é o ponto', () => {
    expect(explicacaoDoVazio('nao_disponivel', [])).toContain('não tem este item')
    expect(explicacaoDoVazio('nao_encontrado', ['a', 'b'])).toContain('2 fonte(s)')
    // `nao_disponivel` (a montadora afirma que não tem) ≠ `nao_encontrado` (ninguém citou).
    expect(explicacaoDoVazio('nao_disponivel', [])).not.toBe(explicacaoDoVazio('nao_encontrado', []))
  })
})
