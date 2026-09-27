/**
 * Os dois painéis de ação do showroom: **argumentário** e **resultado**.
 *
 * Ficam num arquivo próprio porque a tela do Showroom já é grande, e porque estes dois têm
 * regras que valem ser lidas juntas:
 *
 * * **o ponto de atenção tem o mesmo destaque dos três a favor.** `docs/12` §3 exige que
 *   onde o concorrente ganha fique visível; um ponto de atenção em letra miúda cumpriria a
 *   regra no código e a quebraria na tela. Ele aparece em bloco próprio, com borda, e com a
 *   frase que explica **por que** dizê-lo é do interesse do vendedor;
 * * **o resultado tem três toques e nenhum campo de texto sobre o cliente.** Não há campo
 *   de nome, telefone ou "observações": o que não existe no formulário não vira PII no
 *   banco, e a API recusa qualquer campo extra (`docs/12` §6.5).
 */
import { useState } from 'react'

import { Badge } from '@/components/Badge'
import { Botao } from '@/components/Botao'
import { Card } from '@/components/Card'
import { Marcacao, Selecao } from '@/components/Campo'
import { Chip } from '@/components/Chip'
import { Warning } from '@/components/Icones'
import { rotularCampo } from '@/lib/formato'
import type { Argumentario, SessaoDeShowroom } from '@/lib/tipos'

/**
 * Os campos que costumam decidir uma conversa de showroom.
 *
 * **Por que uma lista, e não um campo de texto livre** (12/09/2026). O campo era livre e
 * o exemplo dizia `ex.: preco_sugerido_brl…` — nome de coluna do banco, na tela de quem
 * vende. Trocar só o exemplo por português quebraria o outro lado: `winloss` agrega o
 * atributo decisivo por **string exata**, e "preço", "preco" e "valor" virariam três
 * linhas diferentes no painel de Insights, onde hoje há uma.
 *
 * A lista resolve os dois: o vendedor lê "Preço sugerido (R$)" — `rotularCampo` já sabe
 * fazer isso, e é o mesmo rótulo que a Ficha usa — e o que viaja para a API continua sendo
 * o nome canônico. São os cinco de `api/app/seed.py`, que é o que o painel já conta.
 */
const ATRIBUTOS_DECISIVOS = [
  'preco_sugerido_brl',
  'consumo_urbano_kml',
  'capacidade_carga_kg',
  'potencia_cv',
  'garantia_meses',
  'adas_itens',
  'capacidade_reboque_kg',
  'garantia_km',
] as const

/** Os motivos de perda de `docs/12` §6.5, em português. Vocabulário fechado. */
export const MOTIVOS_DE_PERDA = [
  { chave: 'preco', rotulo: 'preço' },
  { chave: 'consumo', rotulo: 'consumo' },
  { chave: 'capacidade', rotulo: 'capacidade' },
  { chave: 'seguranca', rotulo: 'segurança' },
  { chave: 'desempenho', rotulo: 'desempenho' },
  { chave: 'conforto', rotulo: 'conforto' },
  { chave: 'marca_confianca', rotulo: 'marca / confiança' },
  { chave: 'prazo_entrega', rotulo: 'prazo de entrega' },
  { chave: 'financiamento', rotulo: 'financiamento' },
  { chave: 'outro', rotulo: 'outro' },
] as const

const DESFECHOS = [
  { chave: 'fechou', rotulo: 'fechou' },
  { chave: 'perdeu', rotulo: 'perdeu' },
  { chave: 'em_andamento', rotulo: 'em andamento' },
] as const

export function PainelDeArgumentos({
  argumentario,
  aoGerar,
  carregando,
}: {
  argumentario: Argumentario | undefined
  aoGerar: () => void
  carregando: boolean
}) {
  return (
    <Card
      titulo="Argumentário"
      acao={
        <Botao onClick={aoGerar} disabled={carregando}>
          {carregando ? 'gerando…' : 'gerar argumentos'}
        </Botao>
      }
    >
      {!argumentario ? (
        <p className="text-corpo text-tinta-2">
          Gere o argumentário depois de comparar: cada ponto sai com o valor dos dois lados,
          a fonte e a data.
        </p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <span
              data-testid="gerado-por"
              className="mono rounded-[4px] bg-superficie-2 px-2 py-0.5 text-meta text-tinta-2"
            >
              {argumentario.gerado_por}
            </span>
            {argumentario.selo ? (
              <span
                data-testid="selo-pmm"
                className="inline-flex h-[22px] items-center rounded-full bg-ganhamos-fundo px-2 text-meta font-semibold text-ganhamos"
              >
                {argumentario.selo}
              </span>
            ) : null}
            <Badge etiqueta="FATO" />
          </div>

          {/* Numerados: o vendedor decora a ordem, e "o primeiro ponto" precisa ser uma
              referência estável entre a tela e a conversa. */}
          <ol data-testid="pontos" className="space-y-2">
            {argumentario.pontos.map((ponto, indice) => (
              <li
                key={`${ponto.dimensao}-${ponto.campo}`}
                className="flex gap-3 rounded-controle border border-borda px-4 py-3"
              >
                <span
                  aria-hidden="true"
                  className="mono flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-superficie-2 text-meta font-medium text-tinta-2"
                >
                  {indice + 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-corpo text-tinta">{ponto.texto}</span>
                  <span className="mt-1 block text-meta text-tinta-3">
                    {ponto.rotulo_da_dimensao} · peso {ponto.peso}% ·{' '}
                    {argumentario.fonte_por_ponto[indice]?.length ?? 0} evidência(s)
                  </span>
                </span>
              </li>
            ))}
          </ol>

          {/* O ponto de atenção tem o MESMO destaque dos três a favor: `docs/12` §3 exige
              que onde o concorrente ganha fique visível, e letra miúda cumpriria a regra no
              código e a quebraria na tela. */}
          {argumentario.ponto_forte_concorrente ? (
            <div
              data-testid="ponto-de-atencao"
              className="flex gap-3 rounded-controle bg-naoSabemos-fundo px-4 py-3"
            >
              <Warning size={20} aria-hidden="true" className="mt-0.5 shrink-0 text-naoSabemos" />
              <div className="min-w-0">
                <p className="text-corpo font-medium text-naoSabemos">Ponto de atenção</p>
                <p className="mt-0.5 text-corpo text-tinta">
                  {argumentario.ponto_forte_concorrente.texto}
                </p>
                <p className="mt-1.5 text-meta text-tinta-2">
                  Diga isto antes que o cliente diga: ele já sabe, e quem não menciona perde a
                  credibilidade do resto.
                </p>
              </div>
            </div>
          ) : null}

          {argumentario.avisos.map((aviso) => (
            <p key={aviso} className="text-meta text-tinta-2">
              {aviso}
            </p>
          ))}
        </div>
      )}
    </Card>
  )
}

export function PainelDeResultado({
  sessao,
  aoAbrir,
  aoFechar,
  salvando,
  erroAoAbrir,
  erroAoFechar,
}: {
  sessao: SessaoDeShowroom | undefined
  aoAbrir: () => void
  aoFechar: (dados: {
    outcome: string
    motivos: string[]
    atributo_decisivo?: string
  }) => void
  salvando: boolean
  /** A recusa do servidor ao abrir a sessão, em português.
   *
   * Existe por defeito medido: o **analista** não atende no salão e recebe 403 em
   * `criar_sessao_showroom` (a matriz de `docs/12` §6.6). A regra está certa; o que
   * faltava era o aviso. Quem clicava em "abrir sessão" com o perfil errado via
   * **nada acontecer** — e "nada acontecer" é indistinguível de tela quebrada. */
  erroAoAbrir?: string
  /** Idem para o registro do desfecho, que também passa pela matriz de papéis. */
  erroAoFechar?: string
}) {
  const [desfecho, setDesfecho] = useState('')
  const [motivos, setMotivos] = useState<string[]>([])
  const [atributo, setAtributo] = useState('')

  // Os números saem dos passos **visíveis**. Escritos à mão, a tela pulava de "1." para
  // "3." sempre que o desfecho não era perda — o passo dos motivos é condicional, e só
  // faz sentido na perda (QA-22). Renumerar é mais honesto que tirar a numeração: o
  // produto chama isso de "três toques", e o vendedor conta os toques.
  const mostraMotivos = desfecho === 'perdeu'
  const numero = { desfecho: 1, motivos: 2, atributo: mostraMotivos ? 3 : 2 }

  return (
    <Card
      titulo="Resultado da conversa"
      descricao="Sem nome, telefone ou e-mail: a API recusa qualquer campo que não seja destes. O que se registra é o par comparado e o desfecho."
    >
      {!sessao ? (
        <>
          <Botao tom="primario" onClick={aoAbrir}>
            abrir sessão
          </Botao>
          {erroAoAbrir ? (
            <p
              data-testid="recusa-ao-abrir"
              role="alert"
              className="mt-3 rounded-controle bg-naoSabemos-fundo px-4 py-3 text-corpo text-naoSabemos"
            >
              {erroAoAbrir}
            </p>
          ) : null}
        </>
      ) : (
        <div data-testid="resultado" className="space-y-5">
          <fieldset>
            <legend className="mb-1.5 text-rotulo font-medium text-tinta-2">
              {numero.desfecho}. Desfecho
            </legend>
            <div className="flex flex-wrap gap-2">
              {DESFECHOS.map((opcao) => (
                <Chip
                  key={opcao.chave}
                  selecionado={desfecho === opcao.chave}
                  onAlternar={() => setDesfecho(opcao.chave)}
                >
                  {opcao.rotulo}
                </Chip>
              ))}
            </div>
          </fieldset>

          {/* Os motivos só fazem sentido na perda: registrar "por que perdeu" numa venda
              fechada misturaria o que pesou contra com o que o cliente comentou. */}
          {mostraMotivos ? (
            <fieldset data-testid="motivos">
              <legend className="mb-1.5 text-rotulo font-medium text-tinta-2">
                {numero.motivos}. Por que perdeu
              </legend>
              <div className="flex flex-wrap gap-x-4">
                {MOTIVOS_DE_PERDA.map((motivo) => (
                  <Marcacao
                    key={motivo.chave}
                    rotulo={motivo.rotulo}
                    checked={motivos.includes(motivo.chave)}
                    onChange={() =>
                      setMotivos((atuais) =>
                        atuais.includes(motivo.chave)
                          ? atuais.filter((m) => m !== motivo.chave)
                          : [...atuais, motivo.chave],
                      )
                    }
                  />
                ))}
              </div>
            </fieldset>
          ) : null}

          <Selecao
            rotulo={`${numero.atributo}. Atributo decisivo`}
            aria-label="atributo decisivo"
            className="max-w-sm"
            value={atributo}
            onChange={(e) => setAtributo(e.target.value)}
            apoio="o que pesou mais na conversa. Opcional."
          >
            <option value="">não registrar</option>
            {ATRIBUTOS_DECISIVOS.map((campo) => (
              <option key={campo} value={campo}>
                {rotularCampo(campo)}
              </option>
            ))}
          </Selecao>

          <Botao
            tom="primario"
            disabled={!desfecho || salvando}
            onClick={() =>
              aoFechar({
                outcome: desfecho,
                motivos: desfecho === 'perdeu' ? motivos : [],
                atributo_decisivo: atributo || undefined,
              })
            }
          >
            {salvando ? 'salvando…' : 'registrar resultado'}
          </Botao>

          {erroAoFechar ? (
            <p
              data-testid="recusa-ao-fechar"
              role="alert"
              className="rounded-controle bg-naoSabemos-fundo px-4 py-3 text-corpo text-naoSabemos"
            >
              {erroAoFechar}
            </p>
          ) : null}

          {sessao.updated_at ? (
            <p
              data-testid="resultado-salvo"
              className="rounded-controle bg-ganhamos-fundo px-4 py-3 text-corpo text-ganhamos"
            >
              Resultado registrado: {sessao.outcome}
              {sessao.motivos.length ? ` · ${sessao.motivos.join(', ')}` : ''}
            </p>
          ) : null}
        </div>
      )}
    </Card>
  )
}
