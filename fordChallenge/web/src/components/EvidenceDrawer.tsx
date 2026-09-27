/**
 * A gaveta de evidência: **URL, trecho verbatim, data e tier**.
 *
 * É o componente que transforma a promessa do produto em algo conferível. O trecho
 * aparece como **citação literal**, com aspas e fonte monoespaçada, porque a diferença
 * entre "o site diz 397 cv" e "achamos que são 397 cv" é exatamente essa citação —
 * parafrasear aqui destruiria o valor da tela.
 *
 * **Painel lateral, não modal** (v2). Quem está lendo 58 campos quer ver a prova de um
 * deles sem perder o lugar: o modal centralizado cobria a ficha e obrigava a fechar para
 * continuar. A gaveta encosta na direita, o contexto fica à vista, e em ≤ 640 px ela
 * ocupa a tela inteira — 440 px numa tela de 390 px seria um modal disfarçado.
 *
 * A ordem dos blocos é a de `010_DESIGN.md` §5, e não é arbitrária: **valor → etiqueta →
 * tier por extenso → trecho literal → URL → data → hash**. Ela desce da conclusão para a
 * prova, que é a ordem em que a pergunta "de onde veio isso?" se responde.
 *
 * No **modo showroom** o tier, o snapshot e a confiança não aparecem (`docs/12` §6.6:
 * nenhuma informação interna visível ao cliente). Ficam a fonte e a data, que é o que o
 * cliente precisa para conferir sozinho depois.
 */

import { Badge } from '@/components/Badge'
import { BlocoDaGaveta, Gaveta, TrechoLiteral } from '@/components/Gaveta'
import { etiquetaDe } from '@/lib/etiqueta'
import { formatarValor } from '@/lib/formato'
import type { Campo, Evidencia } from '@/lib/tipos'

/** O que cada tier significa. Sem isso, "tier 3" não diz nada a quem lê. */
const SIGNIFICADO_DO_TIER: Record<number, string> = {
  1: 'fonte oficial da montadora',
  2: 'FIPE ou PBE/Inmetro',
  3: 'imprensa especializada',
  4: 'referência interna, sem verificação editorial',
  5: 'fórum ou fonte não verificada',
}

/**
 * A data da coleta, formatada em **UTC**.
 *
 * `timeZone: 'UTC'` nao e detalhe: o back-end grava `captured_at` em UTC, e
 * `2026-09-01T00:00:00Z` renderizado no fuso de Brasilia (UTC-3) sai como **31/08/2026**.
 * Num produto cuja premissa e "evidencia com data", exibir a data errada da coleta seria
 * errar exatamente onde ele promete acertar — e por um dia, que e o suficiente para uma
 * discussao sobre qual preco valia na semana passada.
 *
 * A data de coleta e uma **data**, nao um instante. O fuso de quem olha a tela nao muda o
 * dia em que a pagina foi capturada.
 */
function dataLegivel(iso: string): string {
  if (!iso) return 'data não registrada'
  // SQLite devolve o horário UTC sem sufixo. O navegador interpreta esse formato
  // como horário local e pode avançar o dia quando formatamos em UTC.
  const semFuso = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(iso)
  const data = new Date(semFuso ? `${iso.replace(' ', 'T')}Z` : iso)
  if (Number.isNaN(data.getTime())) return iso
  return data.toLocaleDateString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

/**
 * Um bloco de evidencia. **Exportado** porque o Radar (WP-25) mostra as evidencias do
 * antes e do depois de um alerta, e renderizar evidencia em dois lugares diferentes
 * levaria as duas telas a divergir no que exibem — no tier, na data, na citacao literal.
 * A citacao e a promessa do produto; ela tem de sair igual em toda tela.
 */
export function BlocoDeEvidencia({
  evidencia,
  valor,
  showroom = false,
}: {
  evidencia: Evidencia
  valor: string
  showroom?: boolean
}) {
  return (
    <li className="border-t border-borda py-4 first:border-t-0 first:pt-0">
      {/* `break-words`: `adas_itens` sai como uma lista de sete termos separados por
          ponto e, sem quebra, ela estica a gaveta e a página passa a rolar de lado. */}
      <p className="mono break-words text-[28px] font-medium leading-[34px] text-tinta">
        {valor}
      </p>

      {/* O tipo da afirmação aparece **inclusive no showroom**, ao contrário do tier:
          "declarado" x "medido" é informação sobre o dado que o cliente pode conferir na
          própria página, e é a diferença que explica por que há dois números. */}
      {evidencia.tipo_de_afirmacao ? (
        <p className="mt-1.5 text-rotulo text-tinta-2">
          valor <span className="font-medium text-tinta">{evidencia.tipo_de_afirmacao}</span>{' '}
          nesta fonte
        </p>
      ) : null}

      {!showroom ? (
        <p className="mt-1.5 text-rotulo text-tinta-2">
          tier {evidencia.tier}: {SIGNIFICADO_DO_TIER[evidencia.tier] ?? 'origem não mapeada'}
        </p>
      ) : null}

      {/* A citação LITERAL. É o que separa evidência de alegação. */}
      <div className="mt-3">
        <TrechoLiteral>“{evidencia.quote}”</TrechoLiteral>
      </div>

      {evidencia.raw_value && evidencia.raw_value !== valor ? (
        <p className="mt-1.5 text-meta text-tinta-2">
          como a fonte escreve: <span className="mono text-tinta">{evidencia.raw_value}</span>
        </p>
      ) : null}

      <dl className="mt-3 space-y-1.5 text-meta text-tinta-2">
        <div className="min-w-0">
          <dt className="inline font-semibold">Fonte: </dt>
          <dd className="inline break-all">
            {evidencia.source_url.startsWith('http') ? (
              <a
                href={evidencia.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="text-marca-700 hover:underline"
              >
                {evidencia.source_url}
              </a>
            ) : (
              evidencia.source_url
            )}
          </dd>
        </div>
        <div>
          <dt className="inline font-semibold">Coletado em: </dt>
          <dd className="mono inline">{dataLegivel(evidencia.captured_at)}</dd>
        </div>
        {evidencia.page ? (
          <div>
            <dt className="inline font-semibold">Página: </dt>
            <dd className="mono inline">{evidencia.page}</dd>
          </div>
        ) : null}
        {!showroom && evidencia.snapshot_id ? (
          <div className="min-w-0">
            <dt className="inline font-semibold">Snapshot: </dt>
            {/* `translate="no"`: hash e id não são texto; tradutor automático os garbleia. */}
            <dd translate="no" className="mono inline break-all">
              {evidencia.snapshot_id}
            </dd>
          </div>
        ) : null}
      </dl>
    </li>
  )
}

interface Props {
  /** A gaveta é controlada pela linha do campo: ela sabe se está aberta. */
  aberta: boolean
  campo: string
  dados: Campo
  onFechar: () => void
  showroom?: boolean
}

export function EvidenceDrawer({ aberta, campo, dados, onFechar, showroom = false }: Props) {
  const principal = formatarValor(dados.value, dados.unit, campo)
  const quantas = dados.evidences.length + dados.conflicts.length

  return (
    <Gaveta
      aberta={aberta}
      aoFechar={onFechar}
      titulo={campo}
      subtitulo={`${quantas} evidência(s)`}
      testId="gaveta-evidencia"
    >
      <BlocoDaGaveta rotulo="etiqueta">
        <Badge etiqueta={etiquetaDe(dados)} tamanho="md" />
      </BlocoDaGaveta>

      <ul>
        {dados.evidences.map((evidencia) => (
          <BlocoDeEvidencia
            key={evidencia.evidence_id}
            evidencia={evidencia}
            valor={principal}
            showroom={showroom}
          />
        ))}
        {dados.conflicts.map((conflito, indice) => (
          <BlocoDeEvidencia
            key={`${conflito.evidence.evidence_id}-c${indice}`}
            evidencia={conflito.evidence}
            valor={formatarValor(conflito.value, dados.unit, campo)}
            showroom={showroom}
          />
        ))}
      </ul>

      {quantas === 0 ? (
        <p className="text-corpo text-tinta-2">
          Este campo não tem valor afirmado, então não há trecho a citar. As fontes
          consultadas em vão estão na linha do campo.
        </p>
      ) : null}

      {dados.sources_checked.length > 0 ? (
        <p className="mt-4 border-t border-borda pt-4 text-meta text-tinta-3">
          Fontes consultadas nesta coleta: {dados.sources_checked.join(', ')}
        </p>
      ) : null}
    </Gaveta>
  )
}
