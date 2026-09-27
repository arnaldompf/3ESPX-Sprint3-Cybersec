/**
 * Campos de formulário: rótulo, entrada, seleção e busca.
 *
 * O defeito da v1 que este arquivo existe para não repetir: os controles tinham
 * **aparência padrão do navegador** — altura do sistema, seta de `<select>` nativa, sem
 * foco visível. Aqui todos têm 40 px de altura, raio de 6 px, borda de 1 px e o mesmo anel
 * de foco; o `<select>` recebe a seta desenhada e `appearance: none`.
 *
 * O rótulo fica **acima** e a 6 px do controle, em 13 px `--ink-2`, sem caixa alta: rótulo
 * em versalete cansa a leitura de formulário longo, e o Showroom tem formulário longo.
 */

import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { useId } from 'react'

import { CaretDown, MagnifyingGlass } from './Icones'

const BASE_DO_CONTROLE = [
  'h-10 w-full rounded-controle border border-borda-forte bg-superficie px-3',
  'text-corpo text-tinta placeholder:text-tinta-3',
  'transition-colors duration-150 ease-out hover:border-tinta-3',
  'disabled:cursor-not-allowed disabled:bg-superficie-2 disabled:text-tinta-3',
].join(' ')

function Rotulo({ children, para }: { children: ReactNode; para: string }) {
  return (
    <label htmlFor={para} className="mb-1.5 block text-rotulo font-medium text-tinta-2">
      {children}
    </label>
  )
}

interface PropsDeEntrada extends InputHTMLAttributes<HTMLInputElement> {
  rotulo: string
  /** Linha de 12 px abaixo do campo: unidade, exemplo ou a razão de um limite. */
  apoio?: string
}

export function Entrada({ rotulo, apoio, className = '', id, ...resto }: PropsDeEntrada) {
  const gerado = useId()
  const identificador = id ?? gerado
  const apoioId = apoio ? `${identificador}-apoio` : undefined
  return (
    <div className={className}>
      <Rotulo para={identificador}>{rotulo}</Rotulo>
      <input
        id={identificador}
        aria-describedby={apoioId}
        className={BASE_DO_CONTROLE}
        {...resto}
      />
      {apoio ? (
        <p id={apoioId} className="mt-1.5 text-meta text-tinta-3">
          {apoio}
        </p>
      ) : null}
    </div>
  )
}

interface PropsDeSelecao extends SelectHTMLAttributes<HTMLSelectElement> {
  rotulo: string
  apoio?: string
  children: ReactNode
}

export function Selecao({
  rotulo,
  apoio,
  className = '',
  id,
  children,
  ...resto
}: PropsDeSelecao) {
  const gerado = useId()
  const identificador = id ?? gerado
  const apoioId = apoio ? `${identificador}-apoio` : undefined
  return (
    <div className={className}>
      <Rotulo para={identificador}>{rotulo}</Rotulo>
      <div className="relative">
        <select
          id={identificador}
          aria-describedby={apoioId}
          // `appearance-none` + seta própria: a seta nativa do Windows é de 2012 e não
          // combina com nenhum outro controle da tela.
          className={`${BASE_DO_CONTROLE} appearance-none pr-9`}
          {...resto}
        >
          {children}
        </select>
        <CaretDown
          size={16}
          aria-hidden="true"
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-tinta-3"
        />
      </div>
      {apoio ? (
        <p id={apoioId} className="mt-1.5 text-meta text-tinta-3">
          {apoio}
        </p>
      ) : null}
    </div>
  )
}

/**
 * Busca compacta da barra de filtros. Sem rótulo acima: o `placeholder` diz o que é e a
 * barra tem 56 px, não 96 — o dado é o herói, o filtro é coadjuvante.
 */
export function Busca({
  rotulo,
  className = '',
  id,
  ...resto
}: InputHTMLAttributes<HTMLInputElement> & { rotulo: string }) {
  const gerado = useId()
  const identificador = id ?? gerado
  return (
    <div className={`relative ${className}`}>
      <label htmlFor={identificador} className="sr-only">
        {rotulo}
      </label>
      <MagnifyingGlass
        size={16}
        aria-hidden="true"
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-tinta-3"
      />
      <input
        id={identificador}
        type="search"
        className={`${BASE_DO_CONTROLE} pl-9`}
        {...resto}
      />
    </div>
  )
}

/**
 * Caixa de marcação com alvo de 44 px no celular.
 *
 * O `<input>` nativo com `accent-color` em vez de um desenho próprio: o controle nativo
 * já é acessível por teclado e por leitor de tela, e recriá-lo em `<div>` é como se
 * perdem as duas coisas. O que muda é a cor e o tamanho.
 */
export function Marcacao({
  rotulo,
  className = '',
  id,
  ...resto
}: InputHTMLAttributes<HTMLInputElement> & { rotulo: ReactNode }) {
  const gerado = useId()
  const identificador = id ?? gerado
  return (
    <label
      htmlFor={identificador}
      className={[
        'flex min-h-[44px] cursor-pointer items-center gap-2 rounded-controle px-2 py-1',
        'text-corpo text-tinta transition-colors duration-150 ease-out hover:bg-superficie-2',
        'sm:min-h-0 sm:py-1.5',
        className,
      ].join(' ')}
    >
      <input
        id={identificador}
        type="checkbox"
        className="h-4 w-4 shrink-0 rounded-[4px] border-borda-forte accent-[var(--brand-600)]"
        {...resto}
      />
      <span>{rotulo}</span>
    </label>
  )
}
