/**
 * Porta única: identifica no catálogo, mostra a ficha existente imediatamente e só sai
 * para a pesquisa quando o veículo/ano ainda não tem dados. O mesmo histórico acompanha
 * identificação, coleta, merge e ficha persistida.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Botao } from '@/components/Botao'
import { TituloDeSecao } from '@/components/Card'
import { Erro, EsqueletoDeLista, Vazio } from '@/components/Estados'
import { Conversa } from '@/components/pesquisa/Conversa'
import { api } from '@/lib/api'
import { mensagemDeErro } from '@/lib/erros'
import { usePapel } from '@/lib/papel'
import { ACAO_DA_TELA, pode } from '@/lib/permissoes'
import type { Saude } from '@/lib/tipos'
import {
  AMAROK,
  FORD_DIESEL_DE_TOPO,
  FORD_RAPTOR,
  HILUX,
  S10,
} from '@/lib/veiculos'

const ATALHOS = [FORD_RAPTOR, FORD_DIESEL_DE_TOPO, HILUX, AMAROK, S10] as const

function ListaDeFichas({
  linhas,
  nova,
  aoAbrir,
}: {
  linhas: Saude[]
  nova: string
  aoAbrir: (id: string) => void
}) {
  return (
    <ul
      data-testid="fichas-do-banco"
      className="divide-y divide-borda overflow-hidden rounded-cartao border border-borda bg-superficie"
    >
      {linhas.map((linha) => (
        <li key={linha.version_id}>
          <button
            type="button"
            data-testid="ficha-do-banco"
            data-rotulo={linha.rotulo}
            onClick={() => aoAbrir(linha.version_id)}
            className={[
              'flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-left',
              'transition-colors hover:bg-superficie-2',
              linha.version_id === nova ? 'bg-marca-50' : '',
            ].join(' ')}
          >
            <span className="min-w-[14rem] flex-1 font-medium text-tinta">{linha.rotulo}</span>
            <span className="mono text-meta text-tinta-3">
              {linha.verificados.valor} de {linha.verificados.de} campos verificados
            </span>
            {linha.version_id === nova ? (
              <span data-testid="ficha-nova" className="text-meta font-medium text-marca-700">
                ficha recém-pesquisada
              </span>
            ) : null}
          </button>
        </li>
      ))}
    </ul>
  )
}

export function Consulta({ intervaloMs = 1000 }: { intervaloMs?: number }) {
  const navegar = useNavigate()
  const queryClient = useQueryClient()
  const papel = usePapel()
  const podeVerSaude = pode(papel, ACAO_DA_TELA.saude)
  const [fichaNova, setFichaNova] = useState('')

  const fichas = useQuery({
    queryKey: ['saude', papel],
    queryFn: () => api.saude(),
    retry: false,
    enabled: podeVerSaude,
  })

  function aoFichaGravada(versionId: string) {
    setFichaNova(versionId)
    void queryClient.invalidateQueries({ queryKey: ['saude'] })
    void queryClient.invalidateQueries({ queryKey: ['ficha', versionId] })
  }

  return (
    <div className="space-y-8">
      <Conversa
        intervaloMs={intervaloMs}
        atalhos={ATALHOS}
        aoFichaGravada={aoFichaGravada}
      />

      {podeVerSaude ? (
        <section className="space-y-4">
          <TituloDeSecao descricao="Abra uma ficha já coletada ou veja a nova pesquisa aparecer aqui.">
            Versões com ficha no banco
          </TituloDeSecao>
          {fichas.error ? (
            <Erro>{mensagemDeErro(fichas.error, 'listar as versões com ficha')}</Erro>
          ) : fichas.isPending ? (
            <EsqueletoDeLista linhas={5} />
          ) : (fichas.data ?? []).length > 0 ? (
            <ListaDeFichas
              linhas={fichas.data ?? []}
              nova={fichaNova}
              aoAbrir={(id) => navegar(`/ficha/${id}`)}
            />
          ) : (
            <Vazio titulo="Nenhuma ficha coletada ainda">
              Consulte um veículo acima; se ele não existir, a pesquisa o grava automaticamente.
            </Vazio>
          )}
        </section>
      ) : null}

      {fichaNova ? (
        <div className="flex justify-end">
          <Botao onClick={() => navegar(`/ficha/${fichaNova}`)}>abrir a ficha completa</Botao>
        </div>
      ) : null}
    </div>
  )
}
