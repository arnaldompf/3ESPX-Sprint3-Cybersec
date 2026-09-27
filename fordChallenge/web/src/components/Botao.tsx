/**
 * Botões. Três tons, e **um primário por área da tela** (`010_DESIGN.md` §7).
 *
 * O que a v1 errava e este componente corrige: os botões tinham a aparência padrão do
 * navegador, altura variável e nenhum estado de foco visível. Aqui a altura é 40 px em
 * todos (44 no toque), o raio é 6 px, o foco é um anel de 2 px com deslocamento, e o hover
 * muda **só a cor** — nada cresce, nada se move (`030_ANTI_PADROES.md` §20).
 *
 * `disabled` não some com o botão: fica em 60% de opacidade e com `cursor: not-allowed`.
 * Botão que desaparece deixa a pessoa procurando o que sumiu.
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react'

export type TomDoBotao = 'primario' | 'secundario' | 'terciario'

const TONS: Record<TomDoBotao, string> = {
  primario:
    'bg-marca-600 text-white hover:bg-marca-hover border border-transparent font-medium',
  secundario:
    'bg-superficie text-tinta border border-borda-forte hover:bg-superficie-2 font-medium',
  // Terciário não sublinha em repouso e sublinha no hover: em meio a texto, o sublinhado
  // permanente compete com os links de evidência, que são o que a pessoa precisa achar.
  terciario:
    'bg-transparent text-marca-700 border border-transparent hover:underline font-medium px-0',
}

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  tom?: TomDoBotao
  /** Ícone Phosphor à esquerda do texto. Só onde ele carrega significado. */
  icone?: ReactNode
  /** Ocupa a largura toda. Usado no celular, onde o alvo precisa ser generoso. */
  largo?: boolean
  /**
   * Estado **processando**: o botão continua na tela, no mesmo lugar e do mesmo tamanho,
   * e diz que está trabalhando.
   *
   * Ele não troca o rótulo por "carregando…" de propósito: o rótulo é o que a pessoa
   * clicou, e trocá-lo faz o botão mudar de largura no instante do clique — o layout
   * pula e o próximo alvo se move. O que muda é o cursor, a opacidade e um `aria-busy`,
   * mais um traço girando à esquerda do texto.
   */
  carregando?: boolean
  children: ReactNode
}

export function Botao({
  tom = 'secundario',
  icone,
  largo = false,
  carregando = false,
  className = '',
  type = 'button',
  disabled,
  children,
  ...resto
}: Props) {
  return (
    <button
      type={type}
      disabled={disabled || carregando}
      aria-busy={carregando || undefined}
      className={[
        'inline-flex h-10 items-center justify-center gap-2 rounded-controle text-corpo',
        'transition-colors duration-150 ease-out',
        'disabled:cursor-not-allowed disabled:opacity-60',
        carregando ? 'cursor-progress' : '',
        tom === 'terciario' ? '' : 'px-4',
        largo ? 'w-full' : '',
        TONS[tom],
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...resto}
    >
      {carregando ? (
        <Girando />
      ) : icone ? (
        <span aria-hidden="true" className="flex shrink-0 items-center">
          {icone}
        </span>
      ) : null}
      {children}
    </button>
  )
}

/**
 * O traço que gira enquanto o botão processa. 16 px, a mesma caixa de um ícone Phosphor
 * em linha — assim o botão não muda de largura ao entrar e sair do estado.
 *
 * Desenhado com borda e `animate-spin` em vez de um GIF ou de um ícone de biblioteca:
 * herda a cor do texto do botão, que é o que o faz funcionar nos três tons.
 */
function Girando() {
  return (
    <span
      aria-hidden="true"
      data-testid="processando"
      className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent opacity-70"
    />
  )
}

/**
 * Botão só de ícone. **Exige `titulo`**, que vira `aria-label` e `title`: ícone sozinho não
 * é rótulo, e um botão sem nome acessível é um botão que o leitor de tela anuncia como
 * "botão".
 */
export function BotaoIcone({
  titulo,
  className = '',
  children,
  ...resto
}: ButtonHTMLAttributes<HTMLButtonElement> & { titulo: string; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={titulo}
      title={titulo}
      className={[
        'inline-flex h-9 w-9 items-center justify-center rounded-controle text-tinta-2',
        'transition-colors duration-150 ease-out hover:bg-superficie-2 hover:text-tinta',
        'disabled:cursor-not-allowed disabled:opacity-60',
        className,
      ].join(' ')}
      {...resto}
    >
      {children}
    </button>
  )
}
