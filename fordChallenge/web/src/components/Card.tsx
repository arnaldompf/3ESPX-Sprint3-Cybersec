/**
 * Cartão e cartão de métrica.
 *
 * Superfície branca, borda de 1 px e sombra de **1 px** — a profundidade vem da superfície
 * e da borda, não de uma sombra difusa (`030_ANTI_PADROES.md` §5, `010_DESIGN.md` §6).
 * Raio de 8 px no cartão, contra os 4 px da v1, que era metade do ar de "site de 2012".
 *
 * Sem largura fixa em lugar nenhum: o layout é o mesmo em 390 px e no desktop.
 */
import type { ReactNode } from 'react'

interface Props {
  titulo?: string
  /** Uma linha abaixo do título dizendo para que o bloco serve. */
  descricao?: string
  acao?: ReactNode
  children: ReactNode
  className?: string
  /** Tira o padding interno: para o cartão que contém uma tabela de ponta a ponta. */
  semPadding?: boolean
}

export function Card({
  titulo,
  descricao,
  acao,
  children,
  className = '',
  semPadding = false,
}: Props) {
  return (
    <section
      className={`rounded-cartao border border-borda bg-superficie shadow-cartao ${className}`}
    >
      {titulo || acao ? (
        <header className="flex flex-wrap items-start justify-between gap-3 px-6 pb-4 pt-5">
          <div className="min-w-0">
            {titulo ? <h2 className="text-cartao text-tinta">{titulo}</h2> : null}
            {descricao ? <p className="mt-1 text-corpo text-tinta-2">{descricao}</p> : null}
          </div>
          {acao ? <div className="flex shrink-0 items-center gap-2">{acao}</div> : null}
        </header>
      ) : null}
      <div className={semPadding ? '' : titulo || acao ? 'px-6 pb-6' : 'p-6'}>{children}</div>
    </section>
  )
}

/**
 * Cartão de métrica: rótulo em cima, número grande em mono, linha de apoio embaixo.
 *
 * **O denominador é obrigatório** quando existe, e é por isso que `apoio` é a terceira
 * linha e não um `title`: "17" sozinho não diz nada; "17 de 58 campos" diz. Percentual sem
 * denominador é anti-padrão §24.
 */
export function CartaoDeMetrica({
  rotulo,
  valor,
  apoio,
  etiqueta,
  palavra = false,
  testId,
  className = '',
}: {
  rotulo: string
  valor: ReactNode
  apoio?: ReactNode
  /** A etiqueta epistêmica do número. Nenhum número aparece sem uma. */
  etiqueta?: ReactNode
  /**
   * O valor é **palavra**, não número: sai da mono e cai para 18 px.
   *
   * A mono existe para alinhar dígitos; aplicada a "na linha" ela só deixa o texto com
   * cara de saída de terminal — que é um dos anti-padrões (§12).
   */
  palavra?: boolean
  /**
   * `data-testid` do cartão inteiro, e `data-metrica` com o rótulo.
   *
   * Existe porque o número **sobe** em 400 ms na primeira renderização (`Contador`): um
   * teste que casa o texto por expressão regular na tela inteira pode ler um quadro do
   * meio da subida. Com o cartão localizável, o teste lê o `data-valor` que o contador
   * publica desde o primeiro quadro, e o que ele mede deixa de depender do instante.
   */
  testId?: string
  className?: string
}) {
  return (
    <div
      data-testid={testId}
      data-metrica={rotulo}
      className={[
        'rounded-cartao border border-borda bg-superficie p-4 shadow-cartao',
        className,
      ].join(' ')}
    >
      <p className="text-rotulo text-tinta-2">{rotulo}</p>
      <p
        className={
          palavra
            ? 'mt-1 text-destaque font-semibold leading-[34px] text-tinta'
            : 'mono mt-1 text-[28px] font-medium leading-[34px] text-tinta'
        }
      >
        {valor}
      </p>
      {apoio ? <p className="mt-1 text-meta text-tinta-3">{apoio}</p> : null}
      {etiqueta ? <div className="mt-2">{etiqueta}</div> : null}
    </div>
  )
}

/**
 * Cabeçalho de uma seção dentro da página, fora de cartão.
 *
 * Existe para as telas que empilham blocos: um `<h2>` de 18 px com a linha de apoio, e o
 * espaço de 24 px vem do `space-y` da página. Sem regra horizontal — a separação é o ar.
 */
export function TituloDeSecao({
  children,
  descricao,
  acao,
}: {
  children: ReactNode
  descricao?: string
  acao?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-cartao text-tinta">{children}</h2>
        {descricao ? <p className="mt-1 text-corpo text-tinta-2">{descricao}</p> : null}
      </div>
      {acao ? <div className="flex shrink-0 items-center gap-2">{acao}</div> : null}
    </div>
  )
}
