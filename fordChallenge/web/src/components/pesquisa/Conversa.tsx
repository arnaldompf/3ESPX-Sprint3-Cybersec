/**
 * **A Pesquisa como conversa** (WP-42 §5): alguém digita "Triton" e, sem saber marca,
 * modelo ou versão, sai com a ficha no catálogo — tendo visto onde o sistema procurou, o
 * que descartou e por quê.
 *
 * **Não é um chatbot.** A caixa é única, mas o sistema só tem quatro falas: qual carro é
 * (`identificacao`), qual versão você quer (chips), o que estou fazendo agora (`trilha`)
 * e o que achei (`ficha`). Nenhuma delas é texto gerado: tudo vem da API, com a
 * etiqueta que a API deu. A máquina de estados que impede duas pesquisas ao mesmo tempo,
 * perde o `run_id` num F5 ou continua depois de a cota acabar mora em `lib/conversa.ts`,
 * e é testada sem tela.
 *
 * **O transporte é consulta a cada segundo, e não SSE** — o mesmo motivo do
 * `Pesquisador.tsx`: o `EventSource` não manda cabeçalho, e a API lê o papel de `X-Role`.
 *
 * **Quem decide é a tela** (D-204): `criar_extracoes` é a ação, e o vendedor vê a recusa,
 * não a caixa. E com `RESEARCH_ENABLED` desligado a tela diz isso em vez de oferecer uma
 * caixa que daria 404.
 */

import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'

import { Botao } from '@/components/Botao'
import { Card } from '@/components/Card'
import { CartaoDaFicha } from '@/components/pesquisa/CartaoDaFicha'
import { Balao, MensagemDeIdentificacao, TextoDaMensagem } from '@/components/pesquisa/Mensagem'
import { Trilha } from '@/components/pesquisa/Trilha'
import { api } from '@/lib/api'
import {
  carregar,
  reduzir,
  salvar,
  ultimaFicha,
  type Alvo,
  type Mensagem,
} from '@/lib/conversa'
import { mensagemDeErro } from '@/lib/erros'
import { usePesquisaLigada } from '@/lib/pesquisa'
import type { Identificacao, OpcaoDeVeiculo, TrilhaDePesquisa } from '@/lib/tipos'
import type { Preferida } from '@/lib/veiculos'

const agora = () => new Date().toISOString()

const FASES_QUE_TRAVAM_A_CAIXA = new Set(['identificando', 'pesquisando', 'parada'])

export interface PropsDaConversa {
  /**
   * O intervalo entre consultas à trilha. Um segundo em produção; o teste encurta para
   * não esperar de verdade. Não é `useFakeTimers` porque `userEvent` e timers falsos
   * brigam pelo mesmo relógio.
   */
  intervaloMs?: number
  atalhos?: readonly Preferida[]
  aoFichaGravada?: (versionId: string) => void
}

export function Conversa({
  intervaloMs = 1000,
  atalhos = [],
  aoFichaGravada,
}: PropsDaConversa) {
  const ligada = usePesquisaLigada()

  const [estado, dispatch] = useReducer(reduzir, undefined, carregar)
  const [trilhas, setTrilhas] = useState<Record<string, TrilhaDePesquisa>>({})
  const [texto, setTexto] = useState('')
  const pedidas = useRef(new Set<string>())
  const fimDaLista = useRef<HTMLDivElement>(null)
  const fichaNotificada = useRef('')

  useEffect(() => {
    salvar(estado)
  }, [estado])

  useEffect(() => {
    const mensagem = ultimaFicha(estado)
    const versionId = mensagem ? trilhas[mensagem.runId]?.version_id : null
    if (!versionId || mensagem?.runId === fichaNotificada.current) return
    fichaNotificada.current = mensagem?.runId ?? ''
    aoFichaGravada?.(versionId)
  }, [aoFichaGravada, estado, trilhas])

  /* ---------------------------------------------------------------- a trilha ao vivo
     Consulta a cada `intervaloMs` enquanto houver `runId`. O laço para quando chega o
     `fim` (ou o status fecha), quando a chamada falha, ou quando o efeito é desmontado. */
  useEffect(() => {
    const runId = estado.runId
    if (!runId) return undefined
    let parar = false

    const acompanhar = async () => {
      while (!parar) {
        try {
          const atual = await api.trilhaDaPesquisa(runId)
          if (parar) return
          setTrilhas((antes) => ({ ...antes, [runId]: atual }))
          const acabou =
            atual.eventos.some((e) => e.tipo === 'fim') ||
            atual.status === 'concluida' ||
            atual.status === 'falhou'
          if (acabou) {
            dispatch({ tipo: 'terminou', trilha: atual, hora: agora() })
            return
          }
        } catch (causa) {
          if (parar) return
          dispatch({
            tipo: 'falhou',
            texto: mensagemDeErro(causa, 'acompanhar a pesquisa') ?? 'A pesquisa parou.',
            hora: agora(),
          })
          return
        }
        await new Promise((resolva) => setTimeout(resolva, intervaloMs))
      }
    }

    void acompanhar()
    return () => {
      parar = true
    }
  }, [estado.runId, intervaloMs])

  /* ---------------------------------------------------------------- depois do F5
     As trilhas de pesquisas passadas não ficam no `sessionStorage` (podem ter centenas
     de eventos); ficam no servidor, e são pedidas uma vez cada. */
  useEffect(() => {
    for (const m of estado.mensagens) {
      if (m.tipo !== 'trilha') continue
      if (m.runId === estado.runId || trilhas[m.runId] || pedidas.current.has(m.runId)) continue
      pedidas.current.add(m.runId)
      api
        .trilhaDaPesquisa(m.runId)
        .then((t) => setTrilhas((antes) => ({ ...antes, [m.runId]: t })))
        .catch(() => {
          /* a mensagem fica com o aviso de "recuperando"; o F5 seguinte tenta de novo */
        })
    }
  }, [estado.mensagens, estado.runId, trilhas])

  /* ---------------------------------------------------------------- rolar para o fim */
  const eventosAoVivo = estado.runId ? (trilhas[estado.runId]?.eventos.length ?? 0) : 0
  useEffect(() => {
    const alvo = fimDaLista.current
    if (alvo && typeof alvo.scrollIntoView === 'function') {
      alvo.scrollIntoView({ block: 'end', behavior: 'smooth' })
    }
  }, [estado.mensagens.length, eventosAoVivo])

  /* ---------------------------------------------------------------- as ações */
  // Identificar e consultar o catálogo funciona mesmo com a pesquisa externa desligada.
  const podeEnviar = !FASES_QUE_TRAVAM_A_CAIXA.has(estado.fase)

  const continuar = async (runId: string) => {
    dispatch({ tipo: 'iniciandoPesquisa', hora: agora() })
    try {
      const aceita = await api.continuarPesquisa(runId)
      setTrilhas((antes) => {
        const anterior = antes[runId]
        return anterior ? { ...antes, [runId]: { ...anterior, continuacao_disponivel: false } } : antes
      })
      dispatch({ tipo: 'pesquisaAceita', runId: aceita.run_id, hora: agora() })
    } catch (causa) {
      dispatch({ tipo: 'falhou', texto: mensagemDeErro(causa, 'continuar a pesquisa') ?? 'Não foi possível continuar a pesquisa.', hora: agora() })
    }
  }

  const pesquisar = useCallback(
    async (alvo: Alvo) => {
      if (!ligada) {
        dispatch({
          tipo: 'falhou',
          texto: 'Este veículo não está no catálogo e a pesquisa externa está desligada.',
          hora: agora(),
        })
        return
      }
      dispatch({ tipo: 'iniciandoPesquisa', hora: agora() })
      try {
        const aceita = await api.pesquisar({
          marca: alvo.marca,
          modelo: alvo.modelo,
          versao: alvo.versao,
          ano: alvo.ano ?? undefined,
        })
        dispatch({ tipo: 'pesquisaAceita', runId: aceita.run_id, hora: agora() })
      } catch (causa) {
        dispatch({
          tipo: 'falhou',
          texto:
            mensagemDeErro(causa, 'iniciar a pesquisa') ??
            'A pesquisa não está ligada neste ambiente.',
          hora: agora(),
        })
      }
    },
    [ligada],
  )

  const identificar = useCallback(
    async (paraOServidor: string, ano?: number, rotulo?: string) => {
      const limpo = paraOServidor.trim()
      if (!limpo) return
      dispatch({ tipo: 'enviar', texto: limpo, ano, rotulo, hora: agora() })
      try {
        const resposta = await api.identificar(limpo, ano)
        dispatch({ tipo: 'identificou', identificacao: resposta, hora: agora() })
        if (ligada && resposta.estado === 'resolvido' && !resposta.no_catalogo?.tem_ficha) {
          await pesquisar({
            marca: resposta.marca,
            modelo: resposta.modelo,
            versao: resposta.versao,
            ano: resposta.ano,
            ano_origem: resposta.ano_origem,
          })
        }
      } catch (causa) {
        dispatch({
          tipo: 'falhou',
          texto: mensagemDeErro(causa, 'identificar o carro') ?? 'Não deu para identificar o carro.',
          hora: agora(),
        })
      }
    },
    [ligada, pesquisar],
  )

  function escolher(opcao: OpcaoDeVeiculo, identificacao: Identificacao) {
    const base = `${opcao.marca || identificacao.marca} ${opcao.modelo || identificacao.modelo}`.trim()
    const textoDaEscolha = opcao.tipo === 'versao' ? `${base} ${opcao.valor}`.trim() : base
    // O ano só viaja quando alguém o disse: o da opção, ou o que a pessoa pediu. O ano
    // vigente assumido **não** vira pedido — senão perderia a etiqueta INFERÊNCIA.
    const ano =
      opcao.ano ?? (identificacao.ano_origem === 'pedido' ? identificacao.ano ?? undefined : undefined)
    void identificar(textoDaEscolha, ano ?? undefined)
  }

  function trocarAno(ano: number, identificacao: Identificacao) {
    const nome = `${identificacao.marca} ${identificacao.modelo} ${identificacao.versao}`.trim()
    void identificar(nome, ano, `ano-modelo ${ano}`)
  }

  function enviar() {
    const limpo = texto.trim()
    if (!limpo || !podeEnviar) return
    setTexto('')
    void identificar(limpo)
  }

  function aoTeclar(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      enviar()
    }
  }

  /* ---------------------------------------------------------------- a tela */
  const ultimaMensagem = estado.mensagens[estado.mensagens.length - 1]

  function conteudo(m: Mensagem): JSX.Element {
    switch (m.tipo) {
      case 'texto':
      case 'sistema':
      case 'erro':
        return <TextoDaMensagem mensagem={m} />
      case 'identificacao':
        return (
          <MensagemDeIdentificacao
            identificacao={m.identificacao}
            ativa={
              m.id === ultimaMensagem?.id &&
              (estado.fase === 'confirmando' || estado.fase === 'aguardando_escolha')
            }
            aoPesquisar={(alvo) => void pesquisar(alvo)}
            aoEscolher={(opcao) => escolher(opcao, m.identificacao)}
            aoTrocarAno={(ano) => trocarAno(ano, m.identificacao)}
          />
        )
      case 'trilha':
        return <Trilha trilha={trilhas[m.runId] ?? null} rodando={estado.runId === m.runId} />
      case 'ficha': {
        const trilha = trilhas[m.runId]
        return trilha ? (
          <CartaoDaFicha trilha={trilha} aoContinuar={ligada ? () => void continuar(m.runId) : undefined}
            continuando={!podeEnviar} />
        ) : (
          <p className="text-corpo text-tinta-3">recuperando o resultado desta pesquisa…</p>
        )
      }
    }
  }

  return (
    <div data-testid="pesquisa" className="flex min-h-[60vh] flex-col gap-4">
      {!ligada ? (
        <Card titulo="Pesquisa">
          <p data-testid="pesquisa-desligada" className="text-corpo text-tinta-2">
            A consulta ao catálogo está disponível. A pesquisa externa está desligada neste
            ambiente; veículos novos não serão buscados até ela ser ligada.
          </p>
        </Card>
      ) : null}

      <ol data-testid="mensagens" aria-label="conversa" className="flex-1 space-y-5">
        {estado.mensagens.length === 0 ? (
          <li data-testid="pesquisa-boas-vindas" className="text-corpo text-tinta-2">
            Diga o carro do jeito que você fala: "Triton", "S10 High" ou "Ranger Raptor".
            Se a ficha já existir, ela aparece imediatamente; se não existir, a pesquisa começa
            e mostra cada fonte consultada.
          </li>
        ) : null}
        {estado.mensagens.map((m) => (
          <li key={m.id}>
            <Balao mensagem={m}>{conteudo(m)}</Balao>
          </li>
        ))}
        <li aria-hidden="true">
          <div ref={fimDaLista} />
        </li>
      </ol>

      {atalhos.length > 0 && estado.fase !== 'pesquisando' ? (
        <div data-testid="atalhos-da-consulta" className="flex flex-wrap gap-2">
          {atalhos.map((atalho) => {
            const nome = `${atalho.marca} ${atalho.modelo} ${atalho.versao}`
            return (
              <Botao key={nome} onClick={() => void identificar(nome)}>
                {atalho.modelo} {atalho.versao}
              </Botao>
            )
          })}
        </div>
      ) : null}

      {/* A caixa fica presa embaixo enquanto a conversa cresce. `sticky` e não `fixed`:
          respeita a barra lateral e o `max-w` do conteúdo sem repetir as medidas do casco.
          No celular, sobe o tanto da barra inferior. */}
      <form
        data-testid="pesquisa-formulario"
        onSubmit={(e) => {
          e.preventDefault()
          enviar()
        }}
        className="sticky bottom-16 z-10 -mx-4 border-t border-borda bg-canvas px-4 py-3 md:bottom-0 md:-mx-8 md:px-8"
      >
        <div className="flex items-end gap-2">
          <label htmlFor="pesquisa-caixa" className="sr-only">
            o carro que você procura
          </label>
          <textarea
            id="pesquisa-caixa"
            data-testid="pesquisa-caixa"
            rows={1}
            value={texto}
            disabled={!podeEnviar}
            onChange={(e) => setTexto(e.target.value)}
            onKeyDown={aoTeclar}
            placeholder="ex.: Triton, S10 High, a picape nova da RAM"
            className={[
              'min-h-10 flex-1 resize-none rounded-controle border border-borda-forte bg-superficie px-3 py-2',
              'text-corpo text-tinta placeholder:text-tinta-3',
              'disabled:cursor-not-allowed disabled:opacity-60',
            ].join(' ')}
          />
          <Botao
            tom="primario"
            type="submit"
            data-testid="pesquisa-enviar"
            disabled={!podeEnviar || !texto.trim()}
            carregando={estado.fase === 'identificando'}
          >
            enviar
          </Botao>
        </div>
        {estado.fase === 'parada' ? (
          <p data-testid="aviso-de-cota" role="alert" className="mt-2 text-rotulo text-naoSabemos">
            a cota do modelo acabou; fale com quem administra as chaves. A conversa para aqui.
          </p>
        ) : (
          <p className="mt-2 text-meta text-tinta-3">
            Enter envia; Shift+Enter quebra linha. Nada é gravado sem a prova da fonte.
          </p>
        )}
      </form>
    </div>
  )
}
