/**
 * A trilha de uma pesquisa, como a conversa a mostra.
 *
 * Passos **agrupados por rodada** e recolhíveis (abertos enquanto roda, recolhidos ao
 * terminar), a **linha em gerúndio** do que o último passo está fazendo — é o que separa
 * "pesquisando" de "travou" —, os cartões das fontes escolhidas e as **descartadas
 * recolhidas com o motivo**. O descarte é metade da prova: mostrar só o que deu certo
 * faria a tela mais limpa e a pesquisa menos conferível.
 *
 * `Passo`, `Contadores`, `MARCA_DO_PASSO` e `TOM_DO_PASSO` moravam em
 * `pages/Pesquisador.tsx` e vieram para cá sem mudar de comportamento: o painel da
 * Consulta e do Benchmark continua importando daqui.
 *
 * Cada evento carrega a etiqueta de `docs/13` §2: **FATO** para o que se observou
 * acontecer (uma consulta foi feita, uma página foi baixada), **INFERÊNCIA** para o que o
 * sistema decidiu por regra (o tier de um domínio, o descarte de uma fonte).
 */

import { useState } from 'react'

import { Badge } from '@/components/Badge'
import { CaretRight } from '@/components/Icones'
import { dominioDe, etiquetaDoEvento, linhaDeEstado } from '@/lib/conversa'
import { formatarValor, rotularCampo } from '@/lib/formato'
import type { EventoDePesquisa, TrilhaDePesquisa } from '@/lib/tipos'

import { CartoesDeFonte } from './CartoesDeFonte'

export type { EventoDePesquisa, TrilhaDePesquisa }
export { etiquetaDoEvento }

/**
 * O ícone de cada passo. Texto, e não SVG: a trilha é uma lista de linhas curtas, e um
 * ícone desenhado em cada uma competiria com a informação em vez de organizá-la.
 */
export const MARCA_DO_PASSO: Record<string, string> = {
  inicio: '▸',
  rodada: '↻',
  consulta: '?',
  resultados: '≡',
  fonte_escolhida: '✓',
  fonte_descartada: '×',
  baixando: '↓',
  baixada: '✓',
  fonte_bloqueada: '⚠',
  lendo: '◷',
  modelo: '◆',
  espera: '⏲',
  campo: '•',
  cobertura: '%',
  lacuna: '…',
  aviso: '!',
  fim: '■',
}

/** A cor de cada passo, no vocabulário que a tela já usa. */
export const TOM_DO_PASSO: Record<string, string> = {
  fonte_descartada: 'text-tinta-3',
  fonte_bloqueada: 'text-naoSabemos',
  aviso: 'text-naoSabemos',
  espera: 'text-naoSabemos',
  baixada: 'text-ganhamos',
  fonte_escolhida: 'text-marca-700',
  campo: 'text-tinta',
  fim: 'text-tinta font-medium',
  cobertura: 'text-tinta font-medium',
}

/**
 * O texto de um passo. Só o evento `campo` é remontado aqui: "campo: valor unidade ·
 * domínio (tier N)", com o rótulo do campo como a pessoa o lê. Os demais vêm prontos.
 */
export function textoDoPasso(evento: EventoDePesquisa): string {
  if (evento.tipo !== 'campo') return evento.texto
  const dados = evento.dados ?? {}
  if (typeof dados.campo !== 'string') return evento.texto
  const unidade = typeof dados.unit === 'string' ? dados.unit : undefined
  const dominio = typeof dados.dominio === 'string' ? dados.dominio : dominioDe(dados.url)
  const tier = dados.tier !== undefined && dados.tier !== null ? ` (tier ${String(dados.tier)})` : ''
  const origem = dominio ? ` · ${dominio}${tier}` : ''
  return `${rotularCampo(dados.campo)}: ${formatarValor(dados.valor, unidade, dados.campo)}${origem}`
}

/** Uma linha da trilha. */
export function Passo({ evento }: { evento: EventoDePesquisa }) {
  const tom = TOM_DO_PASSO[evento.tipo] ?? 'text-tinta-2'
  return (
    <li
      data-testid={`passo-${evento.tipo}`}
      className="flex items-start gap-3 border-b border-borda py-2 last:border-b-0"
    >
      <span aria-hidden="true" className={`mono w-4 shrink-0 text-center text-meta ${tom}`}>
        {MARCA_DO_PASSO[evento.tipo] ?? '·'}
      </span>
      <span className="mono w-12 shrink-0 text-right text-meta text-tinta-3">
        {evento.decorrido.toFixed(1)}s
      </span>
      <span className={`min-w-0 flex-1 break-words text-corpo ${tom}`}>{textoDoPasso(evento)}</span>
      <Badge etiqueta={etiquetaDoEvento(evento.etiqueta)} />
    </li>
  )
}

/** O resumo de cima: o que já fechou, quanto custou até agora. */
export function Contadores({ trilha }: { trilha: TrilhaDePesquisa }) {
  const eventos = trilha.eventos
  const baixadas = eventos.filter((e) => e.tipo === 'baixada').length
  const consultas = eventos.filter((e) => e.tipo === 'consulta').length
  const descartadas = eventos.filter((e) => e.tipo === 'fonte_descartada').length
  const bloqueadas = eventos.filter((e) => e.tipo === 'fonte_bloqueada').length
  const ultimaCobertura = [...eventos].reverse().find((e) => e.tipo === 'cobertura')
  const respondidos = Number(ultimaCobertura?.dados?.respondidos ?? trilha.campos_com_valor)
  const total = Number(ultimaCobertura?.dados?.total ?? trilha.campos_alvo) || 0
  const decorrido = eventos.length ? eventos[eventos.length - 1]!.decorrido : 0

  const itens: { rotulo: string; valor: string; testid: string }[] = [
    { rotulo: 'campos', valor: total ? `${respondidos} de ${total}` : '—', testid: 'campos' },
    { rotulo: 'consultas', valor: String(consultas), testid: 'consultas' },
    { rotulo: 'páginas lidas', valor: String(baixadas), testid: 'paginas' },
    { rotulo: 'descartadas', valor: String(descartadas), testid: 'descartadas' },
    { rotulo: 'bloqueadas', valor: String(bloqueadas), testid: 'bloqueadas' },
    { rotulo: 'tempo', valor: `${decorrido.toFixed(0)}s`, testid: 'tempo' },
  ]

  return (
    <dl
      data-testid="contadores-da-pesquisa"
      className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-6"
    >
      {itens.map((item) => (
        <div key={item.rotulo} data-metrica={item.testid} className="min-w-0">
          <dt className="text-meta uppercase tracking-[0.06em] text-tinta-3">{item.rotulo}</dt>
          <dd className="mono mt-0.5 whitespace-nowrap text-cartao text-tinta">{item.valor}</dd>
        </div>
      ))}
    </dl>
  )
}

/** O ponto que pulsa enquanto algo acontece. Só decoração: o texto ao lado diz o quê. */
export function Pulso() {
  return (
    <span aria-hidden="true" className="relative flex h-2 w-2 shrink-0">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-marca-600 opacity-75" />
      <span className="relative inline-flex h-2 w-2 rounded-full bg-marca-700" />
    </span>
  )
}

/* ------------------------------------------------------------------ rodadas */

export interface GrupoDeRodada {
  rodada: number
  eventos: EventoDePesquisa[]
}

/** Os eventos em blocos consecutivos por rodada, na ordem em que chegaram. */
export function agruparPorRodada(eventos: EventoDePesquisa[]): GrupoDeRodada[] {
  const grupos: GrupoDeRodada[] = []
  for (const evento of eventos) {
    const ultimo = grupos[grupos.length - 1]
    if (ultimo && ultimo.rodada === evento.rodada) ultimo.eventos.push(evento)
    else grupos.push({ rodada: evento.rodada, eventos: [evento] })
  }
  return grupos
}

function plural(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`
}

/** As fontes descartadas de uma rodada, recolhidas — com o motivo a um clique. */
function Descartadas({ eventos }: { eventos: EventoDePesquisa[] }) {
  const [aberto, setAberto] = useState(false)
  return (
    <div className="pt-2">
      <button
        type="button"
        data-testid="ver-descartadas"
        aria-expanded={aberto}
        onClick={() => setAberto((v) => !v)}
        className="flex items-center gap-1 text-rotulo font-medium text-marca-700 hover:underline"
      >
        <CaretRight
          size={12}
          aria-hidden="true"
          className={`transition-transform duration-150 ${aberto ? 'rotate-90' : ''}`}
        />
        {aberto
          ? 'esconder as descartadas'
          : `${plural(eventos.length, 'fonte descartada', 'fontes descartadas')} (por quê)`}
      </button>
      {aberto ? (
        <ol data-testid="descartadas" aria-label="fontes descartadas" className="mt-1">
          {eventos.map((evento) => (
            <Passo key={evento.ordem} evento={evento} />
          ))}
        </ol>
      ) : null}
    </div>
  )
}

function GrupoDaRodada({ grupo, rodando }: { grupo: GrupoDeRodada; rodando: boolean }) {
  // `manual` guarda o que a pessoa escolheu; sem escolha, o grupo segue a pesquisa:
  // aberto enquanto roda, recolhido quando termina.
  const [manual, setManual] = useState<boolean | null>(null)
  const aberto = manual ?? rodando
  const passos = grupo.eventos.filter((e) => e.tipo !== 'fonte_descartada')
  const descartadas = grupo.eventos.filter((e) => e.tipo === 'fonte_descartada')
  const titulo = grupo.rodada === 0 ? 'Preparação' : `Rodada ${grupo.rodada}`

  return (
    <section data-testid={`rodada-${grupo.rodada}`} className="rounded-cartao border border-borda">
      <button
        type="button"
        aria-expanded={aberto}
        onClick={() => setManual(!aberto)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-superficie-2"
      >
        <CaretRight
          size={14}
          aria-hidden="true"
          className={`shrink-0 text-tinta-3 transition-transform duration-150 ${aberto ? 'rotate-90' : ''}`}
        />
        <span className="text-corpo font-medium text-tinta">{titulo}</span>
        <span className="mono ml-auto text-meta text-tinta-3">
          {plural(passos.length, 'passo', 'passos')}
        </span>
      </button>
      {aberto ? (
        <div className="border-t border-borda px-3 pb-2">
          <ol aria-label={`passos da ${titulo.toLowerCase()}`}>
            {passos.map((evento) => (
              <Passo key={evento.ordem} evento={evento} />
            ))}
          </ol>
          {descartadas.length > 0 ? <Descartadas eventos={descartadas} /> : null}
        </div>
      ) : null}
    </section>
  )
}

/* ------------------------------------------------------------------ a trilha */

interface Props {
  /** `null` enquanto a primeira consulta ao servidor não voltou. */
  trilha: TrilhaDePesquisa | null
  rodando: boolean
  erro?: string
}

export function Trilha({ trilha, rodando, erro }: Props) {
  const [manual, setManual] = useState<boolean | null>(null)
  const aberta = manual ?? rodando
  const eventos = trilha?.eventos ?? []
  const ultimo = eventos[eventos.length - 1]
  const grupos = agruparPorRodada(eventos)
  const passos = plural(eventos.length, 'passo', 'passos')

  return (
    <div
      data-testid="trilha-ao-vivo"
      data-rodando={rodando ? 'sim' : 'nao'}
      className="overflow-hidden rounded-cartao border border-borda bg-superficie"
    >
      <button
        type="button"
        aria-expanded={aberta}
        onClick={() => setManual(!aberta)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-superficie-2"
      >
        <span className="flex min-w-0 items-center gap-2">
          {rodando ? (
            <Pulso />
          ) : (
            <span aria-hidden="true" className="mono text-meta text-tinta-3">
              ■
            </span>
          )}
          <span className="truncate text-corpo font-medium text-tinta">
            {rodando ? `Pesquisando · ${passos}` : `Concluída · ${passos}`}
          </span>
        </span>
        <CaretRight
          size={16}
          aria-hidden="true"
          className={`shrink-0 text-tinta-3 transition-transform duration-150 ${aberta ? 'rotate-90' : ''}`}
        />
      </button>

      {rodando ? (
        <p
          aria-live="polite"
          data-testid="linha-de-estado"
          className="flex items-center gap-2 px-4 pb-3 text-corpo text-marca-700"
        >
          <span className="animate-pulse">{linhaDeEstado(ultimo)}</span>
        </p>
      ) : null}

      {erro ? (
        <p role="alert" className="px-4 pb-3 text-corpo text-perdemos">
          {erro}
        </p>
      ) : null}

      {aberta ? (
        <div className="space-y-4 border-t border-borda px-4 py-4">
          {trilha ? <Contadores trilha={trilha} /> : null}

          {grupos.length === 0 ? (
            <p className="text-corpo text-tinta-2">
              os passos aparecem aqui conforme acontecem
            </p>
          ) : (
            <div className="space-y-2">
              {grupos.map((grupo) => (
                <GrupoDaRodada key={grupo.rodada} grupo={grupo} rodando={rodando} />
              ))}
            </div>
          )}

          <CartoesDeFonte eventos={eventos} />
        </div>
      ) : null}
    </div>
  )
}
