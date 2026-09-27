/** Dados já persistidos, mostrados dentro da Consulta sem exigir outra navegação. */
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Erro, EsqueletoDeLista } from '@/components/Estados'
import { camposComValor, ultimaColeta } from '@/components/pesquisa/CartaoDaFicha'
import { api } from '@/lib/api'
import { formatarDataBR } from '@/lib/conversa'
import { mensagemDeErro } from '@/lib/erros'
import { formatarValor, rotularCampo } from '@/lib/formato'

const LIMITE = 8

export function ResumoDaFicha({ versionId }: { versionId: string }) {
  const [todos, setTodos] = useState(false)
  const ficha = useQuery({
    queryKey: ['ficha', versionId],
    queryFn: () => api.ficha(versionId),
  })
  const campos = ficha.data ? camposComValor(ficha.data) : []
  const visiveis = todos ? campos : campos.slice(0, LIMITE)
  const coletadoEm = ficha.data ? ultimaColeta(ficha.data) : null

  if (ficha.isPending) return <EsqueletoDeLista linhas={4} />
  if (ficha.error) return <Erro>{mensagemDeErro(ficha.error, 'carregar a ficha')}</Erro>

  return (
    <div data-testid="dados-do-catalogo" className="space-y-3">
      <ul className="divide-y divide-borda rounded-cartao border border-borda">
        {visiveis.map(({ nome, campo }) => (
          <li key={nome} className="flex flex-wrap items-baseline gap-3 px-3 py-2">
            <span className="min-w-[10rem] flex-1 text-corpo text-tinta-2">
              {rotularCampo(nome)}
            </span>
            <span className="mono text-corpo font-medium text-tinta">
              {formatarValor(campo.value, campo.unit, nome)}
            </span>
          </li>
        ))}
      </ul>
      {campos.length > LIMITE ? (
        <button
          type="button"
          data-testid="alternar-todos-os-dados"
          onClick={() => setTodos((valor) => !valor)}
          className="text-rotulo font-medium text-marca-700 hover:underline"
        >
          {todos ? 'mostrar menos' : `mostrar todos os ${campos.length} campos`}
        </button>
      ) : null}
      {coletadoEm ? (
        <p className="text-meta text-tinta-3">fontes coletadas em {formatarDataBR(coletadoEm)}</p>
      ) : null}
    </div>
  )
}
