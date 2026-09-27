/**
 * Chip: atributo livre na Consulta, filtro de marca na Matriz, hipótese no Simulador.
 *
 * 28 px de altura e raio de **6 px**, não pill: o pill é do domínio das etiquetas
 * epistêmicas, e usar a mesma forma para "filtro" e para "FATO" faria duas coisas
 * diferentes parecerem a mesma (`010_DESIGN.md` §5).
 *
 * `selecionado` é o estado de filtro ligado: fundo `--brand-50`, texto `--brand-700`. Sem
 * selecionado, o chip é neutro sobre `--surface-2`.
 */
import type { ReactNode } from 'react'

import { X } from './Icones'

interface Props {
  children: ReactNode
  onRemover?: () => void
  /** Clicável: vira `<button>` e alterna. Usado nos filtros por marca. */
  onAlternar?: () => void
  selecionado?: boolean
  className?: string
}

/**
 * `max-w-full` e `flex-wrap`, e não `shrink-0` sozinho — defeito medido a 390 px.
 *
 * O chip de hipótese do Simulador carrega o campo, o antes, o depois e a origem por
 * extenso: "Preço sugerido (R$): 379.990 → 360.990 (hipótese informada pelo usuário) ×".
 * Com `shrink-0` e sem altura flexível, ele media **555 px** numa tela de 390 e nenhum
 * ancestral rolava: a origem e o **botão de remover a hipótese** ficavam fora da tela e
 * fora do alcance. Não era rolagem horizontal (a página não rolava); era conteúdo cortado,
 * que é pior porque não se vê que falta.
 *
 * `h-7` vira `min-h-7` pelo mesmo motivo: quebrando em duas linhas, a altura fixa cortaria
 * a segunda.
 */
const BASE = [
  'inline-flex min-h-7 max-w-full flex-wrap items-center gap-1.5 rounded-controle px-2.5 py-1',
  'text-rotulo font-medium transition-colors duration-150 ease-out',
].join(' ')

export function Chip({
  children,
  onRemover,
  onAlternar,
  selecionado = false,
  className = '',
}: Props) {
  const cores = selecionado
    ? 'bg-marca-50 text-marca-700'
    : 'bg-superficie-2 text-tinta-2 hover:text-tinta'

  if (onAlternar) {
    return (
      <button
        type="button"
        onClick={onAlternar}
        aria-pressed={selecionado}
        className={`${BASE} ${cores} ${className}`}
      >
        {children}
      </button>
    )
  }

  return (
    <span className={`${BASE} ${cores} ${className}`}>
      {children}
      {onRemover ? (
        <button
          type="button"
          onClick={onRemover}
          aria-label={`remover ${typeof children === 'string' ? children : 'item'}`}
          className="-mr-1 flex h-5 w-5 items-center justify-center rounded-[4px] text-tinta-3 transition-colors duration-150 ease-out hover:bg-black/5 hover:text-tinta"
        >
          <X size={12} aria-hidden="true" />
        </button>
      ) : null}
    </span>
  )
}
