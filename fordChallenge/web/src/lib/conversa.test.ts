/**
 * A conversa da Pesquisa como dado: o reducer e as funções puras que a tela só desenha.
 *
 * O que está em jogo aqui não é layout, é a **máquina de estados** que impede a tela de
 * mandar duas pesquisas ao mesmo tempo, de perder o `run_id` num F5, ou de continuar a
 * conversa depois que a cota do modelo acabou.
 */
import { afterEach, describe, expect, it } from 'vitest'

import {
  CHAVE_DA_CONVERSA,
  ESTADO_INICIAL,
  carregar,
  dominioDe,
  formatarDataBR,
  formatarHora,
  limpar,
  linhaDeEstado,
  reduzir,
  salvar,
  ultimaFicha,
  type EstadoDaConversa,
} from './conversa'
import type { EventoDePesquisa, Identificacao, TrilhaDePesquisa } from './tipos'

const HORA = '2026-09-13T14:03:07.000Z'

function identificacao(extra: Partial<Identificacao> = {}): Identificacao {
  return {
    texto: 'Triton',
    estado: 'resolvido',
    marca: 'Mitsubishi',
    modelo: 'Triton',
    versao: 'HPE-S',
    ano: 2026,
    ano_origem: 'vigente',
    nome: 'Mitsubishi Triton HPE-S',
    pergunta: '',
    opcoes: [],
    origem: 'busca',
    consultas: [],
    fontes: [],
    motivo: '',
    uso: {},
    no_catalogo: null,
    gasto_rodada: {},
    ...extra,
  }
}

function evento(tipo: string, dados: Record<string, unknown> = {}, texto = ''): EventoDePesquisa {
  return { ordem: 1, tipo, texto, etiqueta: 'FATO', rodada: 1, decorrido: 1.5, dados }
}

function trilha(eventos: EventoDePesquisa[], extra: Partial<TrilhaDePesquisa> = {}): TrilhaDePesquisa {
  return {
    run_id: 'run-1',
    status: 'concluida',
    veiculo: 'Mitsubishi Triton HPE-S',
    motivo_da_parada: 'cobertura',
    campos_com_valor: 12,
    campos_alvo: 40,
    paginas: 3,
    rodadas: 1,
    segundos: 90,
    version_id: 'v-1',
    eventos,
    ...extra,
  }
}

afterEach(() => limpar())

describe('o reducer da conversa', () => {
  it('enviar registra o que a pessoa disse, avisa que está procurando e trava a caixa', () => {
    const estado = reduzir(ESTADO_INICIAL, { tipo: 'enviar', texto: 'Triton', hora: HORA })
    expect(estado.fase).toBe('identificando')
    expect(estado.mensagens).toHaveLength(2)
    expect(estado.mensagens[0]).toMatchObject({ autor: 'voce', tipo: 'texto', texto: 'Triton' })
    expect(estado.mensagens[1]).toMatchObject({ autor: 'specradar', tipo: 'sistema', pulso: true })
    // Cada mensagem tem id próprio e hora.
    expect(estado.mensagens[0]!.id).not.toBe(estado.mensagens[1]!.id)
    expect(estado.mensagens[0]!.hora).toBe(HORA)
  })

  it('o rótulo é o que aparece; o texto é o que vai ao servidor', () => {
    const estado = reduzir(ESTADO_INICIAL, {
      tipo: 'enviar',
      texto: 'Triton',
      ano: 2025,
      rotulo: 'ano-modelo 2025',
      hora: HORA,
    })
    expect(estado.mensagens[0]).toMatchObject({ texto: 'ano-modelo 2025' })
  })

  it('identificou tira o pulso, guarda o alvo e abre a confirmação', () => {
    const antes = reduzir(ESTADO_INICIAL, { tipo: 'enviar', texto: 'Triton', hora: HORA })
    const estado = reduzir(antes, { tipo: 'identificou', identificacao: identificacao(), hora: HORA })
    expect(estado.fase).toBe('confirmando')
    expect(estado.mensagens.some((m) => m.tipo === 'sistema' && m.pulso)).toBe(false)
    expect(estado.mensagens.at(-1)).toMatchObject({ tipo: 'identificacao' })
    expect(estado.alvo).toEqual({
      marca: 'Mitsubishi',
      modelo: 'Triton',
      versao: 'HPE-S',
      ano: 2026,
      ano_origem: 'vigente',
    })
  })

  it('precisa_escolher espera a escolha; nao_entendi devolve a caixa', () => {
    const antes = reduzir(ESTADO_INICIAL, { tipo: 'enviar', texto: 'Triton', hora: HORA })
    const escolha = reduzir(antes, {
      tipo: 'identificou',
      identificacao: identificacao({ estado: 'precisa_escolher', pergunta: 'Qual versão?' }),
      hora: HORA,
    })
    expect(escolha.fase).toBe('aguardando_escolha')
    expect(escolha.alvo).toBeUndefined()

    const perdido = reduzir(antes, {
      tipo: 'identificou',
      identificacao: identificacao({ estado: 'nao_entendi', motivo: 'não achei marca nem modelo' }),
      hora: HORA,
    })
    expect(perdido.fase).toBe('digitando')
  })

  it('falhou mostra o erro em português e devolve a caixa', () => {
    const antes = reduzir(ESTADO_INICIAL, { tipo: 'enviar', texto: 'Triton', hora: HORA })
    const estado = reduzir(antes, { tipo: 'falhou', texto: 'Não foi possível identificar.', hora: HORA })
    expect(estado.fase).toBe('digitando')
    expect(estado.mensagens.at(-1)).toMatchObject({ tipo: 'erro', texto: 'Não foi possível identificar.' })
    expect(estado.mensagens.some((m) => m.tipo === 'sistema' && m.pulso)).toBe(false)
  })

  it('a pesquisa aceita vira uma mensagem de trilha com o run_id, e o F5 retoma dali', () => {
    const iniciando = reduzir(ESTADO_INICIAL, { tipo: 'iniciandoPesquisa', hora: HORA })
    expect(iniciando.fase).toBe('pesquisando')
    const estado = reduzir(iniciando, { tipo: 'pesquisaAceita', runId: 'run-1', hora: HORA })
    expect(estado.runId).toBe('run-1')
    expect(estado.mensagens.at(-1)).toMatchObject({ tipo: 'trilha', runId: 'run-1' })
    expect(estado.mensagens.some((m) => m.tipo === 'sistema' && m.pulso)).toBe(false)
  })

  it('terminou acrescenta o cartão da ficha e libera a caixa', () => {
    const antes = reduzir(
      reduzir(ESTADO_INICIAL, { tipo: 'iniciandoPesquisa', hora: HORA }),
      { tipo: 'pesquisaAceita', runId: 'run-1', hora: HORA },
    )
    const estado = reduzir(antes, {
      tipo: 'terminou',
      trilha: trilha([evento('fim', { motivo: 'cobertura' }, 'Cobertura alcançada.')]),
      hora: HORA,
    })
    expect(estado.fase).toBe('pronto')
    expect(estado.runId).toBeUndefined()
    expect(estado.mensagens.at(-1)).toMatchObject({ tipo: 'ficha', runId: 'run-1' })
    expect(ultimaFicha(estado)?.runId).toBe('run-1')
  })

  it.each(['modelo_sem_saldo', 'teto_de_gasto'])(
    'o fim por %s para a conversa e repete o motivo em destaque',
    (motivo) => {
      const antes = reduzir(
        reduzir(ESTADO_INICIAL, { tipo: 'iniciandoPesquisa', hora: HORA }),
        { tipo: 'pesquisaAceita', runId: 'run-1', hora: HORA },
      )
      const estado = reduzir(antes, {
        tipo: 'terminou',
        trilha: trilha([evento('fim', { motivo }, 'A cota do modelo acabou.')]),
        hora: HORA,
      })
      expect(estado.fase).toBe('parada')
      const destaque = estado.mensagens.find((m) => m.tipo === 'sistema' && m.destaque)
      expect(destaque).toMatchObject({ texto: 'A cota do modelo acabou.' })
      // O cartão da ficha continua: a ficha saiu com o que a regex leu.
      expect(estado.mensagens.some((m) => m.tipo === 'ficha')).toBe(true)
    },
  )

  it('não aceita enviar enquanto identifica, pesquisa ou está parada', () => {
    const identificando = reduzir(ESTADO_INICIAL, { tipo: 'enviar', texto: 'Triton', hora: HORA })
    expect(reduzir(identificando, { tipo: 'enviar', texto: 'S10', hora: HORA })).toBe(identificando)

    const parada: EstadoDaConversa = { ...ESTADO_INICIAL, fase: 'parada' }
    expect(reduzir(parada, { tipo: 'enviar', texto: 'S10', hora: HORA })).toBe(parada)
  })

  it('ignora texto vazio', () => {
    expect(reduzir(ESTADO_INICIAL, { tipo: 'enviar', texto: '   ', hora: HORA })).toBe(ESTADO_INICIAL)
  })
})

describe('a linha em gerúndio', () => {
  it.each([
    [evento('consulta'), 'Buscando fontes…'],
    [evento('resultados', { quantos: 7 }), 'Avaliando 7 resultados…'],
    [evento('fonte_escolhida'), 'Escolhendo fontes…'],
    [evento('baixando', { dominio: 'ford.com.br' }), 'Baixando ford.com.br…'],
    [evento('baixando', { url: 'https://www.mitsubishimotors.com.br/triton' }), 'Baixando mitsubishimotors.com.br…'],
    [evento('lendo', { quantos: 1 }), 'Lendo 1 documento…'],
    [evento('lendo', { quantos: 3 }), 'Lendo 3 documentos…'],
    [evento('modelo', { url: 'https://www.ford.com.br/x' }), 'Modelo lendo ford.com.br…'],
    [evento('espera', { segundos: 12.4 }), 'Aguardando 12 s pela cota do modelo…'],
    [
      evento('lacuna', { faltando: ['potencia_cv', 'torque_nm', 'peso_kg'] }),
      'Faltam 3 campos; procurando potência (cv), torque (N·m)…',
    ],
    [evento('cobertura', { respondidos: 12, total: 40 }), '12 de 40 campos com prova'],
    [evento('fim', {}, 'Parou por cobertura.'), 'Parou por cobertura.'],
    [evento('inicio'), 'Começando…'],
  ])('%o → %s', (ev, esperado) => {
    expect(linhaDeEstado(ev)).toBe(esperado)
  })

  it('sem evento, diz que está começando', () => {
    expect(linhaDeEstado(undefined)).toBe('Começando…')
  })
})

describe('as funções de formato', () => {
  it('dominioDe tira o protocolo, o www e o caminho', () => {
    expect(dominioDe('https://www.ford.com.br/picapes/ranger')).toBe('ford.com.br')
    expect(dominioDe('http://quatrorodas.abril.com.br/x?y=1')).toBe('quatrorodas.abril.com.br')
    expect(dominioDe('não é url')).toBe('não é url')
    expect(dominioDe('')).toBe('')
  })

  it('formatarHora dá HH:MM:SS', () => {
    expect(formatarHora(HORA)).toMatch(/^\d{2}:\d{2}:\d{2}$/)
    expect(formatarHora('lixo')).toBe('')
  })

  it('formatarDataBR dá dd/mm/aaaa a partir do dia da fonte, sem mexer no fuso', () => {
    expect(formatarDataBR('2026-09-05T23:30:00Z')).toBe('05/09/2026')
    expect(formatarDataBR('2026-09-05')).toBe('05/09/2026')
    expect(formatarDataBR(null)).toBe('')
    expect(formatarDataBR('lixo')).toBe('')
  })
})

describe('a conversa sobrevive ao F5', () => {
  it('salvar e carregar devolvem o mesmo estado', () => {
    const estado = reduzir(
      reduzir(ESTADO_INICIAL, { tipo: 'iniciandoPesquisa', hora: HORA }),
      { tipo: 'pesquisaAceita', runId: 'run-9', hora: HORA },
    )
    salvar(estado)
    expect(sessionStorage.getItem(CHAVE_DA_CONVERSA)).toBeTruthy()
    expect(carregar()).toEqual(estado)
  })

  it('sem nada guardado, ou com lixo guardado, começa do zero', () => {
    expect(carregar()).toEqual(ESTADO_INICIAL)
    sessionStorage.setItem(CHAVE_DA_CONVERSA, '{nao é json')
    expect(carregar()).toEqual(ESTADO_INICIAL)
    sessionStorage.setItem(CHAVE_DA_CONVERSA, JSON.stringify({ v: 99, estado: {} }))
    expect(carregar()).toEqual(ESTADO_INICIAL)
  })

  it('uma identificação a meio caminho volta como caixa livre: a chamada morreu com a aba', () => {
    salvar(reduzir(ESTADO_INICIAL, { tipo: 'enviar', texto: 'Triton', hora: HORA }))
    const estado = carregar()
    expect(estado.fase).toBe('digitando')
    expect(estado.mensagens.some((m) => m.tipo === 'sistema' && m.pulso)).toBe(false)
  })
})
