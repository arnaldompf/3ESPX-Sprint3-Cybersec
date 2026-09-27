/**
 * Gaveta lateral: a evidência de um campo e a cadeia do "Por quê?".
 *
 * **Painel lateral e não modal** (`redesign-skill`: "modais para tudo"). A pessoa está
 * lendo uma ficha de 58 campos e quer ver a prova de um deles sem perder o lugar: um modal
 * centralizado esconde a ficha e obriga a fechar para continuar; a gaveta encosta na
 * direita e deixa o contexto à vista.
 *
 * O que ela precisa fazer certo, e que um `<div>` com `position: fixed` não faz sozinho:
 *
 * * **`Esc` fecha** e o clique no véu fecha;
 * * **o foco entra** no painel ao abrir e **volta** para quem a abriu ao fechar;
 * * **`role="dialog"` com `aria-modal`** e um `aria-labelledby` apontando para o título;
 * * **a página não rola atrás** enquanto ela está aberta;
 * * **em ≤ 768 px ela ocupa a tela inteira**, porque 440 px numa tela de 390 px é um modal
 *   disfarçado.
 */

import type { ReactNode } from 'react'
import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'

import { BotaoIcone } from './Botao'
import { X } from './Icones'

interface Props {
  aberta: boolean
  aoFechar: () => void
  titulo: string
  /** Uma linha abaixo do título: de que campo ou alerta é esta gaveta. */
  subtitulo?: string
  children: ReactNode
  /** `data-testid` do painel, para os testes de tela. */
  testId?: string
}

export function Gaveta({ aberta, aoFechar, titulo, subtitulo, children, testId }: Props) {
  const painel = useRef<HTMLDivElement>(null)
  const quemAbriu = useRef<HTMLElement | null>(null)
  const idDoTitulo = useId()

  useEffect(() => {
    if (!aberta) return undefined
    quemAbriu.current = document.activeElement as HTMLElement | null
    painel.current?.focus()

    function aoTeclar(evento: KeyboardEvent) {
      if (evento.key === 'Escape') aoFechar()
    }
    document.addEventListener('keydown', aoTeclar)

    const rolagemAnterior = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.removeEventListener('keydown', aoTeclar)
      document.body.style.overflow = rolagemAnterior
      // Devolver o foco é o que permite abrir a evidência de um campo, fechar, e continuar
      // a leitura pelo teclado de onde parou.
      quemAbriu.current?.focus?.()
    }
  }, [aberta, aoFechar])

  if (!aberta) return null

  // Portal para `document.body`: a gaveta usa `position: fixed` para se ancorar na
  // viewport, e `Layout.tsx` anima cada página com `.rota-entra` (`transform`, com
  // fill-mode `both` — o transform fica aplicado para sempre depois da animação). Um
  // ancestral com `transform` vira o containing block de todo `fixed` dentro dele: sem o
  // portal, a gaveta se ancorava no `.rota-entra` (a altura da página inteira) em vez da
  // tela, e "ver evidência" abria um painel fora da área visível — em branco para quem
  // olhava. Achado em produção em 12/09/2026.
  return createPortal(
    <>
      <div
        aria-hidden="true"
        data-testid="veu-da-gaveta"
        onClick={aoFechar}
        className="veu-entra fixed inset-0 z-veu bg-tinta/20"
      />
      <div
        ref={painel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={idDoTitulo}
        tabIndex={-1}
        data-testid={testId}
        className={[
          // A gaveta desliza da direita em 200 ms: o movimento diz de onde ela veio, e
          // é o que a separa de um modal que aparece do nada no meio da tela.
          'gaveta-entra',
          'fixed inset-y-0 right-0 z-gaveta flex w-full flex-col bg-superficie shadow-flutuante',
          'sm:w-gaveta',
          'focus:outline-none',
        ].join(' ')}
      >
        <header className="flex items-start justify-between gap-3 border-b border-borda px-5 py-4">
          <div className="min-w-0">
            <h2 id={idDoTitulo} className="text-cartao text-tinta">
              {titulo}
            </h2>
            {subtitulo ? <p className="mt-0.5 text-corpo text-tinta-2">{subtitulo}</p> : null}
          </div>
          <BotaoIcone titulo="fechar" onClick={aoFechar}>
            <X size={18} aria-hidden="true" />
          </BotaoIcone>
        </header>
        <div className="rolagem-discreta rolagem-presa flex-1 overflow-y-auto px-5 py-5">
          {children}
        </div>
      </div>
    </>,
    document.body,
  )
}

/**
 * Um bloco da gaveta: rótulo pequeno em cima, conteúdo embaixo.
 *
 * A gaveta de evidência é uma sequência destes — valor, etiqueta, tier por extenso, trecho
 * literal, URL, data, hash —, e a repetição do mesmo bloco é o que faz a leitura descer
 * sem esforço.
 */
export function BlocoDaGaveta({
  rotulo,
  children,
}: {
  rotulo: string
  children: ReactNode
}) {
  return (
    <div className="border-t border-borda py-4 first:border-t-0 first:pt-0">
      <p className="text-meta font-semibold uppercase tracking-[0.06em] text-tinta-3">
        {rotulo}
      </p>
      <div className="mt-1.5 text-corpo text-tinta">{children}</div>
    </div>
  )
}

/**
 * O trecho literal da fonte. Mono de 13 px sobre `--surface-2`, com barra esquerda de 3 px.
 *
 * A barra é citação, não decoração: é o recurso tipográfico que separa "o que a fonte
 * escreveu" de "o que nós dizemos sobre isso" — e essa separação é o produto.
 */
export function TrechoLiteral({ children }: { children: ReactNode }) {
  return (
    <blockquote
      data-testid="trecho-literal"
      className="mono break-words border-l-[3px] border-borda-forte bg-superficie-2 px-3 py-2 text-rotulo leading-[20px] text-tinta"
    >
      {children}
    </blockquote>
  )
}
