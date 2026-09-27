/**
 * Os chips de escolha da conversa: "qual Triton?" vira uma fila de versões, cada uma
 * com o **domínio da fonte** que a sustenta.
 *
 * Uma opção sem fonte nunca chega aqui — a política de `pipeline/research/identificar.py`
 * derruba antes —, então o domínio está sempre presente e é o que diz à pessoa de onde a
 * sugestão veio. `flex-wrap`: em 390 px os chips quebram linha em vez de rolar de lado.
 */

import { dominioDe } from '@/lib/conversa'
import type { OpcaoDeVeiculo } from '@/lib/tipos'

import { Favicon } from './CartoesDeFonte'

interface Props {
  opcoes: OpcaoDeVeiculo[]
  aoEscolher: (opcao: OpcaoDeVeiculo) => void
  /** A escolha já foi feita, ou a conversa seguiu: os chips ficam, mas não clicam. */
  desabilitado?: boolean
}

export function Opcoes({ opcoes, aoEscolher, desabilitado = false }: Props) {
  if (opcoes.length === 0) return null
  return (
    <ul data-testid="opcoes" aria-label="opções de veículo" className="flex flex-wrap gap-2">
      {opcoes.map((opcao) => {
        const dominio = dominioDe(opcao.fontes[0])
        return (
          <li key={`${opcao.tipo}-${opcao.marca}-${opcao.modelo}-${opcao.valor}`} className="max-w-full">
            <button
              type="button"
              data-testid="opcao"
              data-tipo={opcao.tipo}
              disabled={desabilitado}
              onClick={() => aoEscolher(opcao)}
              className={[
                'flex max-w-full flex-col items-start gap-0.5 rounded-controle border border-borda',
                'bg-superficie-2 px-3 py-2 text-left transition-colors duration-150 ease-out',
                'hover:border-marca-600 hover:bg-marca-50',
                'disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-borda disabled:hover:bg-superficie-2',
              ].join(' ')}
            >
              <span className="text-corpo font-medium text-tinta">
                {opcao.tipo === 'modelo' ? `${opcao.marca} ${opcao.valor}`.trim() : opcao.valor}
              </span>
              {opcao.detalhe ? (
                <span className="text-meta text-tinta-2">{opcao.detalhe}</span>
              ) : null}
              {dominio ? (
                <span className="flex items-center gap-1 text-meta text-tinta-3">
                  <Favicon dominio={dominio} />
                  {dominio}
                </span>
              ) : null}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
