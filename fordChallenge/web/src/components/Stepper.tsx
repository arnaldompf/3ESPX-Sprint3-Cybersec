/**
 * O stepper de cinco passos do Showroom.
 *
 * A v1 empilhava o formulário inteiro numa coluna vertical longa: o vendedor rolava por
 * seletores, sete prioridades com setas minúsculas e três campos de preço antes de chegar
 * ao botão. O stepper troca "role tudo" por "um passo por vez", que é o que funciona num
 * celular segurado de pé na frente do cliente.
 *
 * Detalhes que importam no toque:
 *
 * * o número em círculo de 28 px; o passo atual em `--brand-600`, o concluído com ✓, o
 *   futuro em `--ink-3`;
 * * **os passos concluídos são clicáveis** — voltar para corrigir o uso informado não pode
 *   custar cinco toques em "voltar";
 * * o passo futuro **não** é clicável, e não porque seria difícil: pular para o resultado
 *   sem o perfil produziria uma comparação sem os pesos que a justificam;
 * * em ≤ 768 px a régua mostra só os números (o rótulo do passo atual fica embaixo), e os
 *   botões Voltar/Avançar ficam fixos no rodapé.
 */

import type { ReactNode } from 'react'

import { Check } from './Icones'

export interface Passo {
  readonly id: string
  readonly rotulo: string
}

export function Stepper({
  passos,
  atual,
  aoIr,
}: {
  passos: readonly Passo[]
  /** Índice do passo atual, base zero. */
  atual: number
  aoIr: (indice: number) => void
}) {
  return (
    <nav aria-label="passos da comparação">
      <ol className="flex items-center gap-1 sm:gap-2">
        {passos.map((passo, indice) => {
          const concluido = indice < atual
          const eAtual = indice === atual
          const circulo = eAtual
            ? 'bg-marca-600 text-white'
            : concluido
              ? 'bg-marca-50 text-marca-700'
              : 'bg-superficie-2 text-tinta-3'
          return (
            <li key={passo.id} className="flex min-w-0 flex-1 items-center gap-1 sm:gap-2">
              <button
                type="button"
                onClick={() => (concluido ? aoIr(indice) : undefined)}
                disabled={!concluido && !eAtual}
                aria-current={eAtual ? 'step' : undefined}
                className={[
                  'flex min-w-0 items-center gap-2 rounded-controle px-1 py-1',
                  'transition-colors duration-150 ease-out',
                  concluido ? 'hover:bg-superficie-2' : '',
                  !concluido && !eAtual ? 'cursor-default' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              >
                <span
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-rotulo font-semibold ${circulo}`}
                >
                  {concluido ? (
                    <Check size={14} weight="bold" aria-hidden="true" />
                  ) : (
                    indice + 1
                  )}
                </span>
                <span
                  className={[
                    'hidden truncate text-rotulo sm:inline',
                    eAtual ? 'font-medium text-tinta' : 'text-tinta-2',
                  ].join(' ')}
                >
                  {passo.rotulo}
                </span>
                <span className="sr-only">
                  {passo.rotulo}
                  {concluido ? ' (concluído)' : eAtual ? ' (passo atual)' : ''}
                </span>
              </button>
              {indice < passos.length - 1 ? (
                <span
                  aria-hidden="true"
                  className={`h-px flex-1 ${concluido ? 'bg-marca-50' : 'bg-borda'}`}
                />
              ) : null}
            </li>
          )
        })}
      </ol>
      {/* No celular a régua só mostra os números; o rótulo do passo atual vem aqui. */}
      <p className="mt-2 text-rotulo font-medium text-tinta sm:hidden">
        {passos[atual]?.rotulo}
      </p>
    </nav>
  )
}

/**
 * A barra de navegação do stepper: Voltar à esquerda, avançar à direita.
 *
 * Fixa no rodapé em ≤ 768 px (`sticky bottom-0`), porque um botão "avançar" que exige
 * rolar até o fim de um passo longo é um botão que o vendedor não acha com o cliente
 * esperando.
 */
export function BarraDoStepper({ children }: { children: ReactNode }) {
  return (
    <div
      className={[
        'sticky bottom-0 -mx-4 flex items-center justify-between gap-3 border-t border-borda',
        'bg-superficie px-4 py-3 sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:px-0 sm:py-0',
      ].join(' ')}
    >
      {children}
    </div>
  )
}
