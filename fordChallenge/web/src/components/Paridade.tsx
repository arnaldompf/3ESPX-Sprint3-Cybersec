/**
 * Os quatro estados da matriz: ganhamos, empate, perdemos, **não sabemos**.
 *
 * A regra de produto que o desenho carrega: `desconhecido` tem o **mesmo peso visual** dos
 * outros três (`030_ANTI_PADROES.md` §27). Rebaixá-lo a cinza pequeno faria a matriz
 * parecer mais completa do que é, e a honestidade sobre o que não se sabe é metade do que
 * este produto vende.
 *
 * Cor **e** símbolo **e** palavra, sempre os três: a célula mostra o símbolo, o `title` e o
 * `aria-label` trazem a palavra e os dois valores. Numa matriz de 17 colunas, cor sozinha
 * não seria lida nem por quem enxerga todas as cores.
 */

import { Celula as CelulaDaTabela } from '@/components/Tabela'
import { formatarValor, rotularCampo } from '@/lib/formato'
import type { CelulaDeParidade, EstadoDeParidade } from '@/lib/tipos'

interface Aparencia {
  readonly simbolo: string
  readonly rotulo: string
  readonly celula: string
  readonly pill: string
  readonly ponto: string
}

export const APARENCIA: Record<EstadoDeParidade, Aparencia> = {
  vantagem: {
    simbolo: '▲',
    rotulo: 'ganhamos',
    celula: 'bg-ganhamos-fundo text-ganhamos',
    pill: 'bg-ganhamos-fundo text-ganhamos',
    ponto: 'bg-ganhamos',
  },
  paridade: {
    simbolo: '=',
    rotulo: 'empate',
    celula: 'bg-empate-fundo text-empate',
    pill: 'bg-empate-fundo text-empate',
    ponto: 'bg-empate',
  },
  gap: {
    simbolo: '▼',
    rotulo: 'perdemos',
    celula: 'bg-perdemos-fundo text-perdemos',
    pill: 'bg-perdemos-fundo text-perdemos',
    ponto: 'bg-perdemos',
  },
  desconhecido: {
    simbolo: '?',
    rotulo: 'não sabemos',
    celula: 'bg-naoSabemos-fundo text-naoSabemos',
    pill: 'bg-naoSabemos-fundo text-naoSabemos',
    ponto: 'bg-naoSabemos',
  },
}

export const ORDEM_DOS_ESTADOS: EstadoDeParidade[] = [
  'vantagem',
  'paridade',
  'gap',
  'desconhecido',
]

/**
 * A célula da matriz: 32×32, raio 6, símbolo em 14/600.
 *
 * `descricao` vira `title` e `aria-label`, e é onde moram a palavra e os dois valores —
 * "peso de reboque: perdemos. Ford 3.500 kg, Hilux 3.500 kg". Sem ela a célula seria um
 * triângulo colorido sem significado para quem usa leitor de tela.
 */
export function CelulaDeEstado({
  estado,
  descricao,
  onClick,
}: {
  estado: EstadoDeParidade
  descricao: string
  onClick?: () => void
}) {
  const aparencia = APARENCIA[estado]
  const conteudo = (
    <>
      <span aria-hidden="true">{aparencia.simbolo}</span>
      <span className="sr-only">{descricao}</span>
    </>
  )
  const classe = [
    'inline-flex h-8 w-8 items-center justify-center rounded-controle',
    'text-corpo font-semibold',
    aparencia.celula,
  ].join(' ')

  if (onClick) {
    return (
      <button
        type="button"
        data-testid={`estado-${estado}`}
        title={descricao}
        onClick={onClick}
        className={`${classe} transition-opacity duration-150 ease-out hover:opacity-80`}
      >
        {conteudo}
      </button>
    )
  }
  return (
    <span data-testid={`estado-${estado}`} title={descricao} className={classe}>
      {conteudo}
    </span>
  )
}

/** O pill com a palavra, para a legenda e para o resumo por coluna. */
export function PillDeEstado({
  estado,
  children,
}: {
  estado: EstadoDeParidade
  children?: React.ReactNode
}) {
  const aparencia = APARENCIA[estado]
  return (
    <span
      data-testid={`estado-${estado}`}
      className={[
        'inline-flex h-[22px] shrink-0 items-center gap-1.5 rounded-full px-2',
        'text-meta font-semibold uppercase tracking-[0.06em]',
        aparencia.pill,
      ].join(' ')}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${aparencia.ponto}`} />
      {children ?? aparencia.rotulo}
      <span className="sr-only">{aparencia.simbolo}</span>
    </span>
  )
}

/**
 * A legenda, em linha.
 *
 * Em linha e não em cartão: a legenda é referência, e um cartão de legenda no topo empurra
 * a tabela — que é o herói — para baixo da dobra (`010_DESIGN.md` §4).
 */
export function LegendaDeParidade({ legenda }: { legenda: Record<string, string> }) {
  return (
    <dl
      data-testid="legenda"
      className="flex flex-wrap items-center gap-x-6 gap-y-2 text-meta text-tinta-2"
    >
      {ORDEM_DOS_ESTADOS.map((estado) => (
        <div key={estado} className="flex items-center gap-2">
          <dt>
            <PillDeEstado estado={estado} />
          </dt>
          <dd>{legenda[estado]}</dd>
        </div>
      ))}
    </dl>
  )
}

/**
 * A célula da matriz: símbolo, valor do concorrente em mono e o motivo em 12 px.
 *
 * Mora aqui, e não dentro de uma página: a Matriz e o Benchmark desenham a **mesma**
 * tabela, e duas cópias da mesma célula divergiriam na primeira correção de layout — que
 * é como uma tela passa a mostrar o dado de um jeito e a outra de outro.
 */
export function CelulaDeParidadeNaTabela({ celula }: { celula: CelulaDeParidade }) {
  const descricao = [
    rotularCampo(celula.campo),
    `${celula.estado === 'vantagem' ? 'ganhamos' : celula.estado === 'gap' ? 'perdemos' : celula.estado === 'paridade' ? 'empate' : 'não sabemos'}`,
    `Ford ${formatarValor(celula.valor_ford, celula.unidade, celula.campo)}`,
    `concorrente ${formatarValor(celula.valor_concorrente, celula.unidade, celula.campo)}`,
  ].join(': ')
  return (
    <CelulaDaTabela className="align-middle">
      {/* `truncate` com `title`: um valor como a descrição do motor tem 60 caracteres e,
          sem corte, uma coluna estica e empurra as outras duas para fora da tela. O valor
          inteiro continua acessível no `title` e na descrição da célula de estado. */}
      <div className="flex w-[200px] items-center gap-2">
        <CelulaDeEstado estado={celula.estado} descricao={descricao} />
        <span className="min-w-0 flex-1">
          <span
            title={formatarValor(celula.valor_concorrente, celula.unidade, celula.campo)}
            className="mono block truncate text-rotulo text-tinta"
          >
            {formatarValor(celula.valor_concorrente, celula.unidade, celula.campo)}
          </span>
          {celula.motivo ? (
            <span
              title={celula.motivo}
              className="block truncate text-meta leading-tight text-tinta-3"
            >
              {celula.motivo}
            </span>
          ) : null}
        </span>
      </div>
    </CelulaDaTabela>
  )
}
