/**
 * O cartão do que a pesquisa achou: "N de M campos com prova", quanto custou, os
 * primeiros campos da ficha gravada, a data das fontes e os dois caminhos que seguem
 * (abrir a ficha, comparar).
 *
 * Nenhum número aqui é da tela: as contagens vêm do evento `fim`, os campos vêm de
 * `GET /vehicles/{id}/specs` — a mesma ficha que a tela Ficha mostra —, e a data é a
 * maior `captured_at` entre as evidências. Sem `version_id` não há ficha gravada, e o
 * cartão diz por quê em vez de oferecer um botão que abriria o nada.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '@/components/Badge'
import { Erro, EsqueletoDeLista } from '@/components/Estados'
import { api } from '@/lib/api'
import { formatarDataBR } from '@/lib/conversa'
import { mensagemDeErro } from '@/lib/erros'
import { etiquetaDe } from '@/lib/etiqueta'
import { formatarValor, rotularCampo } from '@/lib/formato'
import { GRUPOS, type Campo, type Ficha, type TrilhaDePesquisa } from '@/lib/tipos'

import { CLASSE_DO_LINK_PRIMARIO, CLASSE_DO_LINK_SECUNDARIO } from './Mensagem'

const CAMPOS_A_MOSTRAR = 6

export interface CampoDaFicha {
  nome: string
  grupo: string
  campo: Campo
}

function todosOsCampos(ficha: Ficha): CampoDaFicha[] {
  const lista: CampoDaFicha[] = []
  for (const grupo of GRUPOS) {
    for (const [nome, campo] of Object.entries(ficha[grupo] ?? {})) {
      lista.push({ nome, grupo, campo })
    }
  }
  for (const [nome, campo] of Object.entries(ficha.extras ?? {})) {
    lista.push({ nome, grupo: 'extras', campo })
  }
  return lista
}

/** Os campos com valor, na ordem dos grupos do schema. `0` e `false` são valores. */
export function camposComValor(ficha: Ficha): CampoDaFicha[] {
  return todosOsCampos(ficha).filter(
    ({ campo }) => campo.value !== null && campo.value !== undefined,
  )
}

/** A maior `captured_at` entre todas as evidências da ficha, ou `null` sem nenhuma. */
export function ultimaColeta(ficha: Ficha): string | null {
  let maior: string | null = null
  let maiorEmMs = Number.NEGATIVE_INFINITY
  for (const { campo } of todosOsCampos(ficha)) {
    const evidencias = [...campo.evidences, ...campo.conflicts.map((c) => c.evidence)]
    for (const evidencia of evidencias) {
      const ms = Date.parse(evidencia.captured_at)
      if (!Number.isNaN(ms) && ms > maiorEmMs) {
        maiorEmMs = ms
        maior = evidencia.captured_at
      }
    }
  }
  return maior
}

/** `2 min 15 s`, ou `48 s` abaixo de um minuto. */
export function formatarDuracao(segundos: number): string {
  const s = Math.max(0, Math.round(Number(segundos) || 0))
  const minutos = Math.floor(s / 60)
  const resto = s % 60
  return minutos > 0 ? `${minutos} min ${resto} s` : `${resto} s`
}

/** Uma contagem que a API pode mandar como número ou como lista. */
export function contar(valor: unknown): number {
  if (Array.isArray(valor)) return valor.length
  const n = Number(valor)
  return Number.isFinite(n) ? n : 0
}

const usd = (n: number) =>
  n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 4 })

/**
 * "K chamada(s) ao modelo · US$ C (rodada: US$ G de US$ T)". `null` quando o `fim` não
 * trouxe medição: sem número, não se inventa linha.
 */
export function linhaDeCusto(dados: Record<string, unknown>): string | null {
  const medicao = dados.medicao
  if (!medicao || typeof medicao !== 'object') return null
  const m = medicao as Record<string, unknown>
  const chamadas = contar(m.chamadas)
  const custo = Number(m.custo_usd ?? 0) || 0
  let texto = `${chamadas} chamada${chamadas === 1 ? '' : 's'} ao modelo · US$ ${usd(custo)}`
  const gasto = dados.gasto_rodada_usd
  const teto = dados.teto_usd
  if (typeof gasto === 'number') {
    const limite = typeof teto === 'number' ? `US$ ${usd(teto)}` : 'sem teto'
    texto += ` (rodada: US$ ${usd(gasto)} de ${limite})`
  }
  return texto
}

interface Props {
  trilha: TrilhaDePesquisa
  aoContinuar?: () => void
  continuando?: boolean
}

export function CartaoDaFicha({ trilha, aoContinuar, continuando = false }: Props) {
  const [todos, setTodos] = useState(false)
  const fim = trilha.eventos.find((e) => e.tipo === 'fim')
  const dados = fim?.dados ?? {}
  const cobertura = (dados.cobertura ?? {}) as Record<string, unknown>
  const comValor = contar(cobertura.com_valor ?? trilha.campos_com_valor)
  const total = contar(cobertura.total ?? trilha.campos_alvo)
  const bloqueadas = contar(dados.bloqueadas)
  const tempo = formatarDuracao(fim?.decorrido ?? trilha.segundos)
  const custo = linhaDeCusto(dados)
  const versionId = trilha.version_id ?? null

  const ficha = useQuery({
    queryKey: ['ficha', versionId],
    queryFn: () => api.ficha(versionId as string),
    enabled: Boolean(versionId),
  })
  const campos = ficha.data ? camposComValor(ficha.data) : []
  const visiveis = todos ? campos : campos.slice(0, CAMPOS_A_MOSTRAR)
  const coletadoEm = ficha.data ? ultimaColeta(ficha.data) : null

  return (
    <article
      data-testid="cartao-da-ficha"
      className="space-y-4 rounded-cartao border border-borda bg-superficie p-5 shadow-cartao"
    >
      <header>
        <h3 className="text-cartao text-tinta">{trilha.veiculo}</h3>
        {fim ? <p className="mt-1 text-corpo text-tinta-2">{fim.texto}</p> : null}
      </header>

      <div className="flex flex-wrap items-center gap-2 text-corpo text-tinta">
        <p data-testid="resumo-da-ficha" className="min-w-0">
          <strong className="mono">
            {comValor} de {total}
          </strong>{' '}
          campos com prova · {bloqueadas} {bloqueadas === 1 ? 'fonte bloqueada' : 'fontes bloqueadas'}{' '}
          · {tempo}
        </p>
        <Badge etiqueta="FATO" motivo="contagens medidas nesta pesquisa" />
      </div>

      {contar(cobertura.conflitos) > 0 || contar(cobertura.declarados_ausentes) > 0 ? (
        <p className="text-meta text-tinta-2">
          {contar(cobertura.conflitos)} campos em conflito ·{' '}
          {contar(cobertura.declarados_ausentes)} ausências comprovadas.
          Esses campos não entram na contagem de valores verificados.
        </p>
      ) : null}

      {custo ? (
        <p data-testid="custo-da-pesquisa" className="flex flex-wrap items-center gap-2 text-meta text-tinta-3">
          <span>{custo}</span>
          <Badge etiqueta="FATO" motivo="medido nas chamadas desta pesquisa" />
          <span>Busca e coleta não estão incluídas neste custo de IA.</span>
        </p>
      ) : null}

      {trilha.continuacao_disponivel && aoContinuar ? (
        <div className="space-y-2">
          <button type="button" disabled={continuando} onClick={aoContinuar}
            className={CLASSE_DO_LINK_SECUNDARIO}>
            continuar pesquisa em segundo plano
          </button>
          <p className="text-meta text-tinta-2">
            Aproveita as fontes já lidas. Limite total de 15 minutos, incluindo a pesquisa
            anterior; novas consultas podem gerar custo. Você pode navegar e voltar à Consulta.
          </p>
        </div>
      ) : null}

      {versionId ? (
        <>
          {ficha.isPending ? <EsqueletoDeLista linhas={3} /> : null}
          {ficha.error ? <Erro>{mensagemDeErro(ficha.error, 'abrir a ficha gravada')}</Erro> : null}
          {ficha.data ? (
            <div className="space-y-2">
              {campos.length === 0 ? (
                <p className="text-corpo text-tinta-2">
                  A ficha foi gravada, mas nenhum campo tem valor com prova.
                </p>
              ) : (
                <ul
                  data-testid="campos-da-ficha"
                  aria-label="campos da ficha"
                  className="divide-y divide-borda rounded-cartao border border-borda"
                >
                  {visiveis.map(({ nome, campo }) => (
                    <li
                      key={nome}
                      data-testid="campo-da-ficha"
                      className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2"
                    >
                      <span className="min-w-[8rem] flex-1 text-corpo text-tinta-2">
                        {rotularCampo(nome)}
                      </span>
                      <span className="mono min-w-0 break-words text-corpo font-medium text-tinta">
                        {formatarValor(campo.value, campo.unit, nome)}
                      </span>
                      <Badge etiqueta={etiquetaDe(campo)} />
                    </li>
                  ))}
                </ul>
              )}
              {campos.length > CAMPOS_A_MOSTRAR ? (
                <button
                  type="button"
                  data-testid="ver-todos-os-campos"
                  aria-expanded={todos}
                  onClick={() => setTodos((v) => !v)}
                  className="text-rotulo font-medium text-marca-700 hover:underline"
                >
                  {todos ? 'ver menos' : `ver todos os campos (${campos.length})`}
                </button>
              ) : null}
              {coletadoEm ? (
                <p data-testid="coletado-em" className="text-meta text-tinta-3">
                  fontes coletadas em {formatarDataBR(coletadoEm)}
                </p>
              ) : null}
            </div>
          ) : null}

          <div className="flex flex-wrap gap-2">
            <Link to={`/ficha/${versionId}`} data-testid="abrir-ficha" className={CLASSE_DO_LINK_PRIMARIO}>
              abrir ficha
            </Link>
            <Link to="/matriz" data-testid="comparar-com" className={CLASSE_DO_LINK_SECUNDARIO}>
              comparar com…
            </Link>
          </div>
        </>
      ) : trilha.erro ? (
        <Erro titulo="A ficha não foi gravada">{trilha.erro}</Erro>
      ) : (
        <p className="text-corpo text-tinta-2">
          A pesquisa terminou sem gravar ficha: nenhum campo fechou com prova.
        </p>
      )}
    </article>
  )
}
