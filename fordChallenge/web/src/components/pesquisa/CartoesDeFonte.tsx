/**
 * Os cartões das fontes que a pesquisa escolheu — domínio, tier, motivo e o que
 * aconteceu com cada uma (baixada, bloqueada, falhou).
 *
 * O desenho é o de `tools/research/Simplicity/.../LinksPanel.tsx`: favicon + domínio em
 * cima, o texto no meio, e o cartão inteiro leva à página. O que é nosso, e não deles:
 * o **tier** e o **motivo** da escolha são regra (INFERÊNCIA), e o estado da coleta é o
 * que se observou acontecer (FATO). Um cartão sem isso seria uma lista de links.
 */

import { Badge } from '@/components/Badge'
import { dominioDe } from '@/lib/conversa'
import type { EventoDePesquisa } from '@/lib/tipos'

export type EstadoDaFonte = 'aguardando' | 'baixada' | 'bloqueada' | 'erro'

export interface Fonte {
  url: string
  dominio: string
  tier: number | null
  motivo: string
  estado: EstadoDaFonte
  /** O que a trilha disse sobre o estado: caracteres lidos, motivo do bloqueio. */
  detalhe: string
}

function numero(valor: unknown): number | null {
  const n = Number(valor)
  return valor === null || valor === undefined || valor === '' || Number.isNaN(n) ? null : n
}

/**
 * As fontes escolhidas, com o estado que os eventos seguintes deram a cada uma.
 *
 * A chave é a URL: o mesmo endereço pode ser escolhido de novo numa segunda rodada, e
 * dois cartões para a mesma página contariam a fonte duas vezes.
 */
export function fontesDaTrilha(eventos: EventoDePesquisa[]): Fonte[] {
  const porUrl = new Map<string, Fonte>()
  for (const evento of eventos) {
    const dados = evento.dados ?? {}
    const url = typeof dados.url === 'string' ? dados.url : ''
    if (!url) continue

    if (evento.tipo === 'fonte_escolhida') {
      if (porUrl.has(url)) continue
      const dominioDado = typeof dados.dominio === 'string' ? dados.dominio : ''
      porUrl.set(url, {
        url,
        dominio: dominioDado || dominioDe(url),
        tier: numero(dados.tier),
        motivo: typeof dados.motivo === 'string' ? dados.motivo : '',
        estado: 'aguardando',
        detalhe: '',
      })
      continue
    }

    const fonte = porUrl.get(url)
    if (!fonte) continue
    if (evento.tipo === 'baixada') {
      fonte.estado = 'baixada'
      const caracteres = numero(dados.caracteres)
      fonte.detalhe = caracteres !== null ? `${caracteres.toLocaleString('pt-BR')} caracteres` : ''
    } else if (evento.tipo === 'fonte_bloqueada') {
      fonte.estado = 'bloqueada'
      fonte.detalhe = evento.texto
    } else if (evento.tipo === 'aviso' && fonte.estado !== 'baixada') {
      fonte.estado = 'erro'
      fonte.detalhe = evento.texto
    }
  }
  return [...porUrl.values()]
}

const ROTULO_DO_ESTADO: Record<EstadoDaFonte, string> = {
  aguardando: 'aguardando',
  baixada: 'baixada',
  bloqueada: 'bloqueada',
  erro: 'falhou',
}

const GLIFO_DO_ESTADO: Record<EstadoDaFonte, string> = {
  aguardando: '…',
  baixada: '✓',
  bloqueada: '⚠',
  erro: '×',
}

const TOM_DO_ESTADO: Record<EstadoDaFonte, string> = {
  aguardando: 'text-tinta-3',
  baixada: 'text-ganhamos',
  bloqueada: 'text-naoSabemos',
  erro: 'text-perdemos',
}

/** Identificador local do domínio, compatível com a política de conteúdo da aplicação. */
export function Favicon({ dominio }: { dominio: string }) {
  if (!dominio) return null
  return <span aria-hidden="true" className="text-meta text-tinta-3">{dominio.charAt(0).toUpperCase()}</span>
}

export function CartoesDeFonte({ eventos }: { eventos: EventoDePesquisa[] }) {
  const fontes = fontesDaTrilha(eventos)
  if (fontes.length === 0) return null

  return (
    <section aria-label="fontes escolhidas" data-testid="cartoes-de-fonte" className="space-y-2">
      <h4 className="text-meta uppercase tracking-[0.06em] text-tinta-3">
        fontes escolhidas ({fontes.length})
      </h4>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {fontes.map((fonte) => (
          <article
            key={fonte.url}
            data-testid="cartao-de-fonte"
            data-estado={fonte.estado}
            className="flex h-full flex-col gap-2 rounded-cartao border border-borda bg-superficie-2 p-3"
          >
            <div className="flex min-w-0 items-center gap-1.5 text-meta text-tinta-3">
              <Favicon dominio={fonte.dominio} />
              <span className="truncate">{fonte.dominio}</span>
              {fonte.tier !== null ? (
                <span className="mono ml-auto shrink-0">tier {fonte.tier}</span>
              ) : null}
            </div>

            <div className="flex flex-wrap items-start gap-2">
              <p className="min-w-0 flex-1 text-rotulo text-tinta">
                {fonte.motivo || 'fonte escolhida pela regra de tier'}
              </p>
              <Badge
                etiqueta="INFERENCIA"
                motivo="o tier e o motivo da escolha são regra nossa, não afirmação da fonte"
              />
            </div>

            <div className="mt-auto flex flex-wrap items-center justify-between gap-2 text-meta">
              <span className={`flex items-center gap-1.5 ${TOM_DO_ESTADO[fonte.estado]}`}>
                <span aria-hidden="true" className="mono">
                  {GLIFO_DO_ESTADO[fonte.estado]}
                </span>
                <span>
                  {ROTULO_DO_ESTADO[fonte.estado]}
                  {fonte.detalhe ? ` · ${fonte.detalhe}` : ''}
                </span>
                {fonte.estado !== 'aguardando' ? (
                  <Badge etiqueta="FATO" motivo="o que aconteceu ao baixar esta página" />
                ) : null}
              </span>
              <a
                href={fonte.url}
                target="_blank"
                rel="noreferrer"
                className="text-marca-700 hover:underline"
              >
                abrir a página
              </a>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
