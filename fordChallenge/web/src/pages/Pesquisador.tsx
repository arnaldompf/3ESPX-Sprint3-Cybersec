/**
 * **O painel ao vivo do Pesquisador.**
 *
 * A pergunta que esta tela responde é a que faltava: *"e se eu pedir um carro que não está
 * aí?"* Até aqui a resposta era "não encontrado", o que é verdade e é inútil. Agora é "eu
 * vou procurar, e você vai ver onde eu procurei".
 *
 * **Por que mostrar a busca enquanto acontece, e não só o resultado.** Três minutos de tela
 * parada é uma tela que travou, e quem está com o cliente ao lado desiste antes. Mas o
 * motivo principal é outro: a trilha **é** o produto. Ver a consulta exata, a fonte
 * escolhida com o tier, e — principalmente — **a fonte descartada com o motivo** é o que
 * separa isto de um chatbot que devolve números. Mostrar só o que deu certo faria a tela
 * parecer mais limpa e a pesquisa, menos conferível.
 *
 * Cada evento carrega a etiqueta de `docs/13` §2: **FATO** para o que se observou
 * acontecer (uma consulta foi feita, uma página foi baixada), **INFERÊNCIA** para o que o
 * sistema decidiu por regra (o tier de um domínio, o descarte de uma fonte).
 *
 * **O transporte é consulta a cada segundo, e não SSE** — apesar de a API falar os dois.
 * O motivo é concreto: o `EventSource` do navegador não manda cabeçalho, e a API lê o
 * papel de `X-Role`. Passar o papel por query string colocaria autorização na URL, que
 * fica no histórico do navegador e no log do servidor. Um segundo de intervalo é
 * indistinguível de tempo real numa pesquisa de três minutos, e atravessa qualquer proxy.
 *
 * `Passo`, `Contadores` e as tabelas de ícone e tom moram em
 * `components/pesquisa/Trilha.tsx` desde a WP-42: a tela Pesquisa usa as mesmas linhas.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { Botao } from '@/components/Botao'
import { Card } from '@/components/Card'
import { Erro } from '@/components/Estados'
import { Contadores, Passo } from '@/components/pesquisa/Trilha'
import { api } from '@/lib/api'
import { mensagemDeErro } from '@/lib/erros'
import type { EventoDePesquisa, TrilhaDePesquisa } from '@/lib/tipos'

export type { EventoDePesquisa, TrilhaDePesquisa }

interface Props {
  marca: string
  modelo: string
  versao: string
  /** Chamado quando a pesquisa termina e há ficha para abrir. */
  aoTerminar?: (trilha: TrilhaDePesquisa) => void
  aoFechar: () => void
}

export function PainelDoPesquisador({ marca, modelo, versao, aoTerminar, aoFechar }: Props) {
  const [trilha, setTrilha] = useState<TrilhaDePesquisa | null>(null)
  const [erro, setErro] = useState('')
  const [rodando, setRodando] = useState(true)
  const runId = useRef('')
  const parar = useRef(false)

  const acompanhar = useCallback(async (id: string) => {
    // Consulta a cada segundo, e não SSE: o `EventSource` do navegador **não** manda
    // cabeçalho, e a API lê o papel de `X-Role`. Trocar o papel por query string
    // colocaria autorização na URL, que fica no histórico e no log do servidor. Um
    // segundo de intervalo é indistinguível de tempo real para uma pesquisa de três
    // minutos, e atravessa qualquer proxy.
    while (!parar.current) {
      try {
        const atual = await api.trilhaDaPesquisa(id)
        setTrilha(atual)
        const acabou = atual.eventos.some((e) => e.tipo === 'fim')
        if (acabou || atual.status === 'concluida' || atual.status === 'falhou') {
          setRodando(false)
          aoTerminar?.(atual)
          return
        }
      } catch (causa) {
        setErro(mensagemDeErro(causa, 'acompanhar a pesquisa') ?? 'A pesquisa parou.')
        setRodando(false)
        return
      }
      await new Promise((resolva) => setTimeout(resolva, 1000))
    }
  }, [aoTerminar])

  useEffect(() => {
    parar.current = false
    let cancelado = false

    api
      .pesquisar({ marca, modelo, versao })
      .then((aceita) => {
        if (cancelado) return
        runId.current = aceita.run_id
        void acompanhar(aceita.run_id)
      })
      .catch((causa) => {
        if (cancelado) return
        // 404 aqui quer dizer bandeira desligada, e é o único erro que a tela
        // precisa explicar de outro jeito: não é falha, é recurso não ligado.
        setErro(
          mensagemDeErro(causa, 'iniciar a pesquisa') ??
            'A pesquisa não está ligada neste ambiente.',
        )
        setRodando(false)
      })

    return () => {
      cancelado = true
      parar.current = true
    }
  }, [marca, modelo, versao, acompanhar])

  const fim = trilha?.eventos.find((e) => e.tipo === 'fim')

  return (
    <Card
      titulo={`Procurando ${[marca, modelo, versao].filter(Boolean).join(' ')}`}
      descricao="Fonte oficial primeiro. Nenhum valor entra na ficha sem o trecho da página onde ele aparece."
      acao={
        <Botao onClick={aoFechar}>{rodando ? 'parar de acompanhar' : 'fechar'}</Botao>
      }
    >
      <div data-testid="painel-do-pesquisador" className="space-y-4">
        {erro ? <Erro>{erro}</Erro> : null}

        {trilha ? <Contadores trilha={trilha} /> : null}

        {rodando ? (
          <p aria-live="polite" className="text-corpo text-tinta-2">
            procurando… as fontes aparecem aqui conforme são encontradas
          </p>
        ) : null}

        {fim ? (
          <p
            data-testid="fim-da-pesquisa"
            className="rounded-cartao bg-superficie-2 px-4 py-3 text-corpo text-tinta"
          >
            {fim.texto}
          </p>
        ) : null}

        {/* `min-h`: o painel nasce com a altura que vai ter, em vez de crescer a cada
            evento. Sem isso, os primeiros segundos são um cartão de 98 px que salta para
            500 px assim que a primeira consulta chega — e o salto rouba o lugar de quem
            estava lendo a linha de cima. */}
        <ol
          data-testid="trilha-da-pesquisa"
          aria-label="passos da pesquisa"
          className="rolagem-discreta min-h-[12rem] max-h-[28rem] overflow-y-auto"
        >
          {(trilha?.eventos ?? []).map((evento) => (
            <Passo key={evento.ordem} evento={evento} />
          ))}
        </ol>

        {!rodando && trilha && trilha.campos_com_valor > 0 ? (
          <p className="text-meta text-tinta-3">
            A ficha foi montada com o que as fontes acima afirmam. Cada campo abre a
            evidência: URL, trecho literal e data da coleta.
          </p>
        ) : null}
      </div>
    </Card>
  )
}
