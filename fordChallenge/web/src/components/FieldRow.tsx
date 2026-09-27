/**
 * Uma linha da ficha: nome do campo, valor, etiqueta, e o caminho para a evidência.
 *
 * É onde as regras invioláveis do projeto viram pixel:
 *
 * * **nenhum valor sem etiqueta** — a `Badge` é irremovível, não condicional;
 * * **os dois vazios não se confundem.** `nao_disponivel` mostra *"a fonte afirma que
 *   esta versão não tem"*; `nao_encontrado` mostra *"nenhuma das N fontes menciona"*, com
 *   **a lista das fontes consultadas**. Exibir "—" nos dois casos apagaria a distinção
 *   que o schema canônico existe para manter, e é o critério de aceite da WP-31;
 * * **divergência mostra os dois valores**, cada um com a sua fonte. Não há valor
 *   "principal" em destaque e outro escondido atrás de um clique: quem decide é quem lê.
 *
 * **A forma, na v2.** A linha é uma grade de três colunas em telas largas — rótulo, valor
 * em mono à direita, etiqueta — e empilha em ≤ 640 px, com a etiqueta abaixo do valor
 * (`010_DESIGN.md` §8). O valor em mono com `tabular-nums` é o que faz 58 campos lidos em
 * sequência formarem uma coluna, e não uma serpente. "ver evidência" e o status aparecem
 * numa linha de 12 px embaixo, que some no hover de ninguém: ela está sempre lá, porque é
 * o clique que o produto existe para oferecer.
 */

import { useState } from 'react'

import { EvidenceDrawer } from '@/components/EvidenceDrawer'
import { Badge } from '@/components/Badge'
import { LinkIcone } from '@/components/Icones'
import { sufixoDoTipo, textoDaDivergencia } from '@/lib/divergencia'
import { ROTULO_DE_STATUS, etiquetaDe, explicacaoDoVazio } from '@/lib/etiqueta'
import { formatarValor, rotularCampo } from '@/lib/formato'
import type { Campo } from '@/lib/tipos'

interface Props {
  campo: string
  dados: Campo
  /** Modo showroom: tipografia maior e **sem** tier nem confiança (`docs/12` §6.6). */
  showroom?: boolean
}

export function FieldRow({ campo, dados, showroom = false }: Props) {
  const [aberto, setAberto] = useState(false)
  const temValor = dados.value !== null && dados.value !== undefined
  const etiqueta = etiquetaDe(dados)
  // Em `SEM_DADO` o pill carrega o motivo específico no `title`, e não a frase genérica:
  // quem passa o mouse no pill lê a mesma coisa que está escrita logo abaixo.
  const motivo = temValor ? undefined : explicacaoDoVazio(dados.status, dados.sources_checked)
  const temEvidencia = dados.evidences.length > 0 || dados.conflicts.length > 0
  const divergente = dados.status === 'divergente'

  return (
    <div
      data-testid={`campo-${campo}`}
      className={[
        'border-b border-borda px-4 py-3 last:border-b-0',
        divergente ? 'bg-naoSabemos-fundo' : 'hover:bg-superficie-2',
        'transition-colors duration-150 ease-out',
      ].join(' ')}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 sm:flex-nowrap">
        <span
          data-testid={`rotulo-${campo}`}
          className={[
            // `min-w-[8rem]` e não `min-w-0`: com base 0 e sem piso, o rótulo era
            // esmagado a zero por um irmão `shrink-0` grande — o valor de `adas_itens`
            // da Raptor tem 11 itens juntados por " · " e mede 2763 px inquebráveis.
            // 8rem (128 px) passa do maior rótulo do catálogo e cabe folgado em 390 px.
            'min-w-[8rem] flex-1 text-tinta-2',
            showroom ? 'text-showroom' : 'text-corpo',
          ].join(' ')}
        >
          {rotularCampo(campo)}
        </span>

        <span
          data-testid={`valor-${campo}`}
          className={[
            // Sai o `shrink-0`, entra `break-words`: um valor longo passa a quebrar por
            // palavra dentro do cartão em vez de escapar 1664 px pela borda direita e
            // ser recortado pelo `overflow-hidden` da seção — o dado sumia sem aviso.
            'mono min-w-0 break-words font-medium',
            showroom ? 'text-showroom' : 'text-corpo',
            temValor ? 'text-tinta' : 'text-tinta-3',
          ].join(' ')}
        >
          {/* Um travessão, e não "sem valor". A palavra "valor" ao lado de um campo que
              não tem valor nenhum é ruído; o que a pessoa precisa ler é o motivo, e ele
              está na linha de baixo. O travessão é o mesmo glifo da etiqueta. */}
          {temValor ? formatarValor(dados.value, dados.unit, campo) : '—'}
        </span>

        <Badge etiqueta={etiqueta} motivo={motivo} tamanho={showroom ? 'md' : 'sm'} />
      </div>

      {/* Vazio: o motivo, por extenso, e a lista de fontes que foram em vão. */}
      {!temValor ? (
        <p data-testid={`vazio-${campo}`} className="mt-1 text-meta text-tinta-2">
          {explicacaoDoVazio(dados.status, dados.sources_checked)}
          {dados.sources_checked.length > 0 ? (
            <>
              {' '}
              <span data-testid={`fontes-${campo}`} className="text-tinta-3">
                Fontes: {dados.sources_checked.join(', ')}
              </span>
            </>
          ) : null}
        </p>
      ) : null}

      {/* Divergência: os DOIS valores, cada um com a sua fonte. */}
      {divergente ? (
        <div data-testid={`divergencia-${campo}`} className="mt-2 text-rotulo">
          {/* O texto não é fixo: "as fontes divergem" é falso quando a fonte é uma só.
              A matéria da Autoesporte sobre a Raptor traz os 5,8 s que a Ford declara e
              os 6,5 s que a revista mediu — mesma URL, duas afirmações. */}
          <p className="font-medium text-naoSabemos">{textoDaDivergencia(dados)}</p>
          <ul className="mt-1.5 space-y-1">
            <li className="flex flex-wrap items-baseline gap-2">
              <span className="mono font-medium text-tinta">
                {formatarValor(dados.value, dados.unit, campo)}
                {sufixoDoTipo(dados.evidences[0])}
              </span>
              <span className="min-w-0 break-all text-meta text-tinta-2">
                {dados.evidences[0]?.source_url ?? 'fonte não registrada'}
              </span>
            </li>
            {dados.conflicts.map((conflito, indice) => (
              <li
                key={`${conflito.evidence.evidence_id}-${indice}`}
                className="flex flex-wrap items-baseline gap-2"
              >
                <span className="mono font-medium text-tinta">
                  {formatarValor(conflito.value, dados.unit, campo)}
                  {sufixoDoTipo(conflito.evidence)}
                </span>
                <span className="min-w-0 break-all text-meta text-tinta-2">
                  {conflito.evidence.source_url}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-1.5 flex flex-wrap items-center gap-3">
        {/* Tier e confiança são informação INTERNA: `docs/12` §6.6 proíbe no showroom. */}
        {!showroom ? (
          <span className="text-meta text-tinta-3">
            {/* "não verificado" é verdade sobre um valor do catálogo, e é a verdade
                errada de dizer: sugere que alguém deveria tê-lo verificado numa fonte,
                quando ele É a identidade da versão consultada. */}
            {dados.origem === 'catalogo'
              ? 'do nosso cadastro'
              : ROTULO_DE_STATUS[dados.status]}
            {dados.confidence > 0 ? (
              <>
                {' · confiança '}
                <span className="mono">{dados.confidence.toFixed(2)}</span>
              </>
            ) : null}
          </span>
        ) : null}

        {temEvidencia ? (
          <button
            type="button"
            onClick={() => setAberto(true)}
            data-testid={`ver-evidencia-${campo}`}
            className="inline-flex items-center gap-1.5 text-meta font-medium text-marca-700 transition-colors duration-150 ease-out hover:underline"
          >
            <LinkIcone size={14} aria-hidden="true" />
            ver evidência
          </button>
        ) : null}
      </div>

      <EvidenceDrawer
        aberta={aberto}
        campo={rotularCampo(campo)}
        dados={dados}
        showroom={showroom}
        onFechar={() => setAberto(false)}
      />
    </div>
  )
}
