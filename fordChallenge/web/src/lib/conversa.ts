/**
 * A conversa da Pesquisa como dado — o que a tela `Pesquisa.tsx` só desenha.
 *
 * **Uma conversa guiada, não um chatbot.** Cada mensagem do sistema é de um tipo fechado
 * (`identificacao`, `trilha`, `ficha`, `sistema`, `erro`), e a fase diz o que a caixa de
 * texto pode fazer agora. Não há texto livre gerado por modelo em lugar nenhum desta
 * tela: o que aparece vem da API, com a etiqueta que a API deu.
 *
 * **Por que um reducer puro.** Três coisas precisam ser verdade ao mesmo tempo e são
 * fáceis de quebrar espalhadas em `useState`: nunca duas pesquisas em paralelo; o `run_id`
 * sobrevive a um F5 no meio dos três minutos (a trilha é lida de novo do servidor, que
 * tem tudo); e quando a cota do modelo acaba a conversa **para**, em vez de aceitar o
 * próximo carro e falhar de novo. Um reducer testa as três sem montar tela.
 *
 * **O que se guarda no `sessionStorage`** é a conversa — mensagens e fase — e **não** a
 * trilha: ela pode ter centenas de eventos e o servidor a devolve inteira a cada
 * consulta. Guardar só o `run_id` é o que basta para retomar.
 */

import type { Etiqueta, EventoDePesquisa, Identificacao, TrilhaDePesquisa } from './tipos'
import { rotularCampo } from './formato'

export type Autor = 'voce' | 'specradar'

export type Fase =
  | 'digitando'
  | 'identificando'
  | 'aguardando_escolha'
  | 'confirmando'
  | 'pesquisando'
  | 'pronto'
  | 'parada'

/** O carro confirmado: o que vai em `POST /research`. */
export interface Alvo {
  marca: string
  modelo: string
  versao: string
  ano: number | null
  ano_origem: string
}

interface Base {
  id: string
  autor: Autor
  /** ISO. A tela mostra `HH:MM:SS`. */
  hora: string
}

export type Mensagem =
  | (Base & { tipo: 'texto'; texto: string })
  | (Base & {
      tipo: 'sistema'
      texto: string
      /** Está acontecendo agora: a linha pulsa. Sai quando a resposta chega. */
      pulso?: boolean
      /** O aviso que muda o que a pessoa faz a seguir (a cota acabou). */
      destaque?: boolean
    })
  | (Base & { tipo: 'erro'; texto: string })
  | (Base & { tipo: 'identificacao'; identificacao: Identificacao })
  | (Base & { tipo: 'trilha'; runId: string })
  | (Base & { tipo: 'ficha'; runId: string })

export interface EstadoDaConversa {
  mensagens: Mensagem[]
  fase: Fase
  alvo?: Alvo
  /** O run em andamento. Só existe em `pesquisando`. */
  runId?: string
}

export type Acao =
  | {
      tipo: 'enviar'
      /** O que vai ao servidor. */
      texto: string
      ano?: number
      /** O que aparece como mensagem da pessoa, quando difere do texto ("ano-modelo 2025"). */
      rotulo?: string
      hora: string
    }
  | { tipo: 'identificou'; identificacao: Identificacao; hora: string }
  | { tipo: 'falhou'; texto: string; hora: string }
  | { tipo: 'iniciandoPesquisa'; hora: string }
  | { tipo: 'pesquisaAceita'; runId: string; hora: string }
  | { tipo: 'terminou'; trilha: TrilhaDePesquisa; hora: string }

export const ESTADO_INICIAL: EstadoDaConversa = { mensagens: [], fase: 'digitando' }

/** A ficha mais recente da conversa, inclusive depois de restaurar um F5. */
export function ultimaFicha(
  estado: EstadoDaConversa,
): Extract<Mensagem, { tipo: 'ficha' }> | undefined {
  return [...estado.mensagens].reverse().find(
    (mensagem): mensagem is Extract<Mensagem, { tipo: 'ficha' }> => mensagem.tipo === 'ficha',
  )
}

/** Os motivos de `fim` que significam "o modelo não entra mais": a conversa para. */
export const MOTIVOS_QUE_PARAM = ['modelo_sem_saldo', 'teto_de_gasto'] as const

const PROCURANDO = 'procurando de que carro você fala…'
const INICIANDO = 'abrindo a pesquisa…'

function novaMensagem<T extends Mensagem['tipo']>(
  estado: EstadoDaConversa,
  hora: string,
  corpo: Extract<Mensagem, { tipo: T }> extends infer M ? Omit<M, keyof Base> : never,
): Mensagem {
  // O id é derivado do estado, não de `Math.random`: o reducer fica determinístico e o
  // teste pode comparar estados inteiros.
  const id = `m${estado.mensagens.length + 1}-${hora}`
  const base: Base = { id, autor: 'specradar', hora }
  return { ...base, ...(corpo as object) } as Mensagem
}

function semPulso(mensagens: Mensagem[]): Mensagem[] {
  return mensagens.filter((m) => !(m.tipo === 'sistema' && m.pulso))
}

/** A fase depois de identificar, pelo estado que o servidor devolveu. */
function faseDaIdentificacao(identificacao: Identificacao): Fase {
  if (identificacao.estado === 'resolvido') return 'confirmando'
  if (identificacao.estado === 'precisa_escolher') return 'aguardando_escolha'
  return 'digitando'
}

export function reduzir(estado: EstadoDaConversa, acao: Acao): EstadoDaConversa {
  switch (acao.tipo) {
    case 'enviar': {
      const texto = acao.texto.trim()
      if (!texto) return estado
      // Trava dura: enquanto identifica ou pesquisa, e depois que a cota acabou, a caixa
      // não manda nada. A tela desabilita o controle; o reducer garante.
      if (
        estado.fase === 'identificando' ||
        estado.fase === 'pesquisando' ||
        estado.fase === 'parada'
      ) {
        return estado
      }
      const mensagens = [...semPulso(estado.mensagens)]
      const sua = novaMensagem<'texto'>({ ...estado, mensagens }, acao.hora, {
        tipo: 'texto',
        texto: acao.rotulo ?? texto,
      })
      mensagens.push({ ...sua, autor: 'voce' })
      mensagens.push(
        novaMensagem<'sistema'>({ ...estado, mensagens }, acao.hora, {
          tipo: 'sistema',
          texto: PROCURANDO,
          pulso: true,
        }),
      )
      return { mensagens, fase: 'identificando', alvo: undefined }
    }

    case 'identificou': {
      const mensagens = semPulso(estado.mensagens)
      mensagens.push(
        novaMensagem<'identificacao'>({ ...estado, mensagens }, acao.hora, {
          tipo: 'identificacao',
          identificacao: acao.identificacao,
        }),
      )
      const { marca, modelo, versao, ano, ano_origem } = acao.identificacao
      const alvo: Alvo | undefined =
        acao.identificacao.estado === 'resolvido'
          ? { marca, modelo, versao, ano, ano_origem }
          : undefined
      return { mensagens, fase: faseDaIdentificacao(acao.identificacao), alvo }
    }

    case 'falhou': {
      const mensagens = semPulso(estado.mensagens)
      mensagens.push(
        novaMensagem<'erro'>({ ...estado, mensagens }, acao.hora, {
          tipo: 'erro',
          texto: acao.texto,
        }),
      )
      return { ...estado, mensagens, fase: 'digitando', runId: undefined }
    }

    case 'iniciandoPesquisa': {
      const mensagens = semPulso(estado.mensagens)
      mensagens.push(
        novaMensagem<'sistema'>({ ...estado, mensagens }, acao.hora, {
          tipo: 'sistema',
          texto: INICIANDO,
          pulso: true,
        }),
      )
      return { ...estado, mensagens, fase: 'pesquisando' }
    }

    case 'pesquisaAceita': {
      const mensagens = semPulso(estado.mensagens)
      mensagens.push(
        novaMensagem<'trilha'>({ ...estado, mensagens }, acao.hora, {
          tipo: 'trilha',
          runId: acao.runId,
        }),
      )
      return { ...estado, mensagens, fase: 'pesquisando', runId: acao.runId }
    }

    case 'terminou': {
      const mensagens = semPulso(estado.mensagens)
      const fim = acao.trilha.eventos.find((e) => e.tipo === 'fim')
      const motivo = String(fim?.dados?.motivo ?? '')
      const parou = (MOTIVOS_QUE_PARAM as readonly string[]).includes(motivo)
      if (parou && fim) {
        mensagens.push(
          novaMensagem<'sistema'>({ ...estado, mensagens }, acao.hora, {
            tipo: 'sistema',
            texto: fim.texto,
            destaque: true,
          }),
        )
      }
      mensagens.push(
        novaMensagem<'ficha'>({ ...estado, mensagens }, acao.hora, {
          tipo: 'ficha',
          runId: acao.trilha.run_id,
        }),
      )
      return { ...estado, mensagens, fase: parou ? 'parada' : 'pronto', runId: undefined }
    }
  }
}

/* ------------------------------------------------------------------ a linha ao vivo */

/**
 * A etiqueta de um evento, no vocabulário fechado de `docs/13` §2. O que a API mandar
 * fora dele cai em INFERÊNCIA: é o rótulo que pede conferência, e é o mais seguro.
 */
export function etiquetaDoEvento(valor: string): Etiqueta {
  if (valor === 'FATO' || valor === 'SIMULACAO') return valor
  return 'INFERENCIA'
}

/** O host de uma URL, sem `www.`. Texto que não é URL volta como veio. */
export function dominioDe(url: unknown): string {
  const texto = typeof url === 'string' ? url.trim() : ''
  if (!texto) return ''
  try {
    return new URL(texto).hostname.replace(/^www\./, '')
  } catch {
    return texto
  }
}

function dominioDoEvento(evento: EventoDePesquisa): string {
  const dados = evento.dados ?? {}
  const direto = typeof dados.dominio === 'string' ? dados.dominio : ''
  return direto || dominioDe(dados.url)
}

/**
 * A linha em gerúndio sob o cabeçalho da trilha: sempre o que o **último** passo está
 * fazendo. É o que separa "pesquisando" de "travou".
 */
export function linhaDeEstado(evento: EventoDePesquisa | undefined): string {
  if (!evento) return 'Começando…'
  const dados = evento.dados ?? {}
  switch (evento.tipo) {
    case 'consulta':
      return 'Buscando fontes…'
    case 'resultados':
      return `Avaliando ${Number(dados.quantos ?? 0)} resultados…`
    case 'fonte_escolhida':
    case 'fonte_descartada':
      return 'Escolhendo fontes…'
    case 'baixando':
      return `Baixando ${dominioDoEvento(evento)}…`
    case 'lendo': {
      const quantos = Number(dados.quantos ?? 1)
      return `Lendo ${quantos} documento${quantos === 1 ? '' : 's'}…`
    }
    case 'modelo':
      return `Modelo lendo ${dominioDoEvento(evento)}…`
    case 'espera':
      return `Aguardando ${Math.round(Number(dados.segundos ?? 0))} s pela cota do modelo…`
    case 'lacuna': {
      const faltando = Array.isArray(dados.faltando) ? dados.faltando.map(String) : []
      // Só a primeira letra desce: "Torque (N·m)" vira "torque (N·m)", e a unidade
      // continua escrita como se escreve.
      const primeiros = faltando
        .slice(0, 2)
        .map((c) => {
          const rotulo = rotularCampo(c)
          return rotulo.charAt(0).toLowerCase() + rotulo.slice(1)
        })
        .join(', ')
      return `Faltam ${faltando.length} campos; procurando ${primeiros}…`
    }
    case 'cobertura':
      return `${Number(dados.respondidos ?? 0)} de ${Number(dados.total ?? 0)} campos com prova`
    case 'fim':
      return evento.texto
    default:
      return 'Começando…'
  }
}

/* ------------------------------------------------------------------ formato */

const dois = (n: number) => String(n).padStart(2, '0')

/** `HH:MM:SS` no relógio de quem olha. Vazio para o que não é data. */
export function formatarHora(iso: string): string {
  const data = new Date(iso)
  if (Number.isNaN(data.getTime())) return ''
  return `${dois(data.getHours())}:${dois(data.getMinutes())}:${dois(data.getSeconds())}`
}

/**
 * `dd/mm/aaaa` a partir do **dia escrito na fonte**, sem passar por fuso: a data de coleta
 * é uma data, não um instante, e o relógio de quem olha não muda o dia em que a página
 * foi capturada.
 */
export function formatarDataBR(iso: string | null | undefined): string {
  if (!iso) return ''
  const casa = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (casa) return `${casa[3]}/${casa[2]}/${casa[1]}`
  const data = new Date(iso)
  if (Number.isNaN(data.getTime())) return ''
  return `${dois(data.getUTCDate())}/${dois(data.getUTCMonth() + 1)}/${data.getUTCFullYear()}`
}

/* ------------------------------------------------------------------ sessionStorage */

export const CHAVE_DA_CONVERSA = 'specradar.pesquisa.conversa.v1'
const VERSAO = 1

export function salvar(estado: EstadoDaConversa): void {
  try {
    sessionStorage.setItem(CHAVE_DA_CONVERSA, JSON.stringify({ v: VERSAO, estado }))
  } catch {
    /* armazenamento bloqueado: a conversa vive só nesta renderização */
  }
}

/**
 * A conversa guardada, ou o zero.
 *
 * Uma identificação a meio caminho **não** volta como "identificando": a chamada HTTP
 * morreu com a aba e ninguém vai respondê-la. A caixa volta livre. Uma pesquisa a meio
 * caminho volta como está, porque o `run_id` continua vivo no servidor.
 */
export function carregar(): EstadoDaConversa {
  try {
    const cru = sessionStorage.getItem(CHAVE_DA_CONVERSA)
    if (!cru) return ESTADO_INICIAL
    const dado = JSON.parse(cru) as { v?: number; estado?: Partial<EstadoDaConversa> }
    if (dado?.v !== VERSAO || !dado.estado || !Array.isArray(dado.estado.mensagens)) {
      return ESTADO_INICIAL
    }
    const estado: EstadoDaConversa = {
      mensagens: dado.estado.mensagens,
      fase: dado.estado.fase ?? 'digitando',
      alvo: dado.estado.alvo,
      runId: dado.estado.runId,
    }
    if (estado.fase === 'identificando') {
      return { ...estado, mensagens: semPulso(estado.mensagens), fase: 'digitando' }
    }
    if (estado.fase === 'pesquisando' && !estado.runId) {
      return { ...estado, mensagens: semPulso(estado.mensagens), fase: 'digitando' }
    }
    return estado
  } catch {
    return ESTADO_INICIAL
  }
}

export function limpar(): void {
  try {
    sessionStorage.removeItem(CHAVE_DA_CONVERSA)
  } catch {
    /* nada guardado, nada a limpar */
  }
}
