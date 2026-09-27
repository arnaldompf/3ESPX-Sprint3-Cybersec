/**
 * O painel do relatório para o cliente: gerar, acompanhar e compartilhar.
 *
 * Três decisões, e nenhuma é de estilo:
 *
 * * **o botão não trava a tela.** A API devolve 202 e um job; este painel acompanha o
 *   estado. Segurar a interface enquanto o servidor monta duas fichas, roda o motor de
 *   aderência e renderiza o documento é o caminho mais curto para o vendedor achar que
 *   travou — com o cliente olhando;
 * * **compartilhar não guarda contato.** O botão abre a folha de compartilhamento do
 *   sistema (`navigator.share`) ou o WhatsApp com o link; o produto **não** vê o
 *   destinatário e não tem campo para digitá-lo. Um "enviar para" com campo de telefone
 *   seria o primeiro lugar onde PII entraria no sistema;
 * * **o link é autenticado.** A rota do arquivo exige token, então o que se compartilha é
 *   um endereço que só quem tem acesso abre. A tela diz isso, para ninguém prometer ao
 *   cliente um link que ele não vai conseguir abrir sozinho.
 */
import { useState } from 'react'

import { Botao } from '@/components/Botao'
import { Card } from '@/components/Card'
import { Copy, DownloadSimple } from '@/components/Icones'
import { mensagemDeCompartilhamento } from '@/lib/compartilhar'
import type { EstadoDoJob } from '@/lib/tipos'

/** `true` quando o navegador tem a folha de compartilhamento do sistema. */
function temCompartilhamentoNativo(): boolean {
  return typeof navigator !== 'undefined' && typeof navigator.share === 'function'
}

/**
 * Os passos do documento, com o atual marcado. **Não é barra de porcentagem.**
 *
 * O worker informa o estágio por nome (`pipeline/worker.py`), e não uma fração: uma barra
 * de 0 a 100% teria de inventar o denominador, e número inventado numa tela cujo produto é
 * "nenhum valor sem evidência" seria a pior ironia possível. O que se mostra é o que se
 * sabe: quais passos existem, qual está acontecendo, quais já passaram.
 *
 * Estágio desconhecido (um passo novo no worker) não quebra nada: nenhum fica marcado como
 * atual e a lista continua dizendo o caminho.
 */
const PASSOS: { id: string; rotulo: string }[] = [
  { id: 'pendente', rotulo: 'na fila' },
  { id: 'executando', rotulo: 'montando a comparação' },
  { id: 'renderizando', rotulo: 'gerando o arquivo' },
]

/**
 * O nome do estágio **em português**, e nunca o nome cru do worker.
 *
 * `job.stage` chega como `pendente`, `executando`, `renderizando` — e, quando o trabalho
 * acaba ou falha, como `done` e `failed`, que são nomes de dentro. A tela mostrava
 * "Gerando… (done)" para quem vende picape. O mapa que traduz já existia dois blocos
 * acima; o que faltava era usá-lo aqui.
 */
function rotuloDoEstagio(estagio: string): string {
  return PASSOS.find((passo) => passo.id === estagio)?.rotulo ?? 'em andamento'
}

function PassosDoJob({ estagio }: { estagio?: string | null }) {
  const atual = PASSOS.findIndex((passo) => passo.id === (estagio ?? 'pendente'))
  return (
    <ol
      data-testid="passos-do-job"
      aria-live="polite"
      className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2"
    >
      {PASSOS.map((passo, indice) => {
        const passou = atual > indice
        const agora = atual === indice
        return (
          <li key={passo.id} className="flex items-center gap-2 text-rotulo">
            <span
              aria-hidden="true"
              className={[
                'h-1.5 w-8 rounded-full transition-colors duration-150 ease-out',
                passou ? 'bg-marca-600' : agora ? 'bg-marca-600/50' : 'bg-superficie-2',
              ].join(' ')}
            />
            <span className={agora ? 'font-medium text-tinta' : 'text-tinta-3'}>
              {passo.rotulo}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

export function PainelDeRelatorio({
  job,
  rotuloFord,
  rotuloConcorrente,
  aoGerar,
  gerando,
  erro,
  travou = false,
}: {
  job: EstadoDoJob | undefined
  rotuloFord: string
  rotuloConcorrente: string
  aoGerar: () => void
  gerando: boolean
  erro?: string
  /** O job parou de responder: a tela desistiu de perguntar (QA-BUG-12). */
  travou?: boolean
}) {
  const [copiado, setCopiado] = useState(false)
  const pronto = job?.status === 'concluido' && Boolean(job.result_url)
  const endereco =
    pronto && job?.result_url
      ? `${typeof window === 'undefined' ? '' : window.location.origin}${job.result_url}`
      : ''
  const mensagem = mensagemDeCompartilhamento(rotuloFord, rotuloConcorrente)

  async function compartilhar() {
    if (!endereco) return
    if (temCompartilhamentoNativo()) {
      try {
        await navigator.share({ title: 'Comparativo técnico', text: mensagem, url: endereco })
        return
      } catch {
        // Cancelar o compartilhamento não é erro: o usuário desistiu. Cai para o copiar.
      }
    }
    try {
      await navigator.clipboard?.writeText(`${mensagem} ${endereco}`)
      setCopiado(true)
    } catch {
      setCopiado(false)
    }
  }

  return (
    <Card
      titulo="Documento para o cliente"
      acao={
        <Botao tom="primario" onClick={aoGerar} carregando={gerando}>
          gerar documento
        </Botao>
      }
    >
      <p className="text-corpo text-tinta-2">
        O documento traz a ficha comparada, o custo estimado, os argumentos, a seção de onde
        o concorrente leva vantagem e a lista de fontes com data. Sem tier, sem confiança
        numérica e sem nenhum dado do cliente.
      </p>

      {erro ? (
        <p role="alert" className="mt-3 text-corpo text-perdemos">
          {erro}
        </p>
      ) : null}

      {job && !pronto && job.status !== 'falhou' && !travou ? <PassosDoJob estagio={job.stage} /> : null}

      {job && !pronto ? (
        <p data-testid="estado-do-job" className="mt-3 text-corpo text-tinta-2">
          {/* Um job que FALHOU tem motivo, e o motivo é útil ("par sem ficha nos dois
              lados" diz o que fazer). Um job que TRAVOU não tem motivo nenhum — o
              processo que o executaria não respondeu —, e aí a frase é a do usuário, não
              a de quem opera a máquina. São dois casos, e só um deles é genérico. */}
          {job.status === 'falhou'
            ? `Não foi possível gerar: ${job.error ?? 'motivo não registrado'}`
            : travou
              ? 'Não foi possível gerar o documento agora; tente novamente em instantes. ' +
                'Para já, mostre a comparação na tela.'
              : `Gerando… (${rotuloDoEstagio(job.stage ?? job.status)})`}
        </p>
      ) : null}

      {pronto ? (
        <div data-testid="relatorio-pronto" className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={job?.result_url ?? '#'}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex h-10 items-center gap-2 rounded-controle bg-marca-600 px-4 text-corpo font-medium text-white transition-colors duration-150 ease-out hover:bg-marca-hover"
            >
              <DownloadSimple size={16} aria-hidden="true" />
              abrir o documento
            </a>
            <Botao onClick={compartilhar} icone={<Copy size={16} />}>
              {temCompartilhamentoNativo() ? 'compartilhar' : 'copiar o link'}
            </Botao>
            <a
              data-testid="whatsapp"
              href={`https://wa.me/?text=${encodeURIComponent(`${mensagem} ${endereco}`)}`}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex h-10 items-center rounded-controle border border-borda-forte px-4 text-corpo font-medium text-tinta transition-colors duration-150 ease-out hover:bg-superficie-2"
            >
              WhatsApp
            </a>
            {copiado ? (
              <span data-testid="copiado" className="text-rotulo text-ganhamos">
                link copiado
              </span>
            ) : null}
          </div>

          <p className="text-meta text-tinta-3">
            O link só abre de dentro da rede onde o SpecRadar está rodando. Não prometa ao
            cliente que ele abre sozinho: mande o arquivo.
          </p>
        </div>
      ) : null}
    </Card>
  )
}
