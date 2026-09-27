/**
 * A gaveta do **"Por quê?"**: a cadeia inteira, do "e daí?" até o snapshot.
 *
 * A cadeia é lida de cima para baixo e responde, em ordem, às perguntas que alguém faz ao
 * ver um alerta marcado ALTA:
 *
 * 1. **o que eu faço?** — a ação sugerida, que é a resposta a "e daí?";
 * 2. **por que ALTA?** — as regras que somaram, com o peso de cada uma;
 * 3. **o que mudou?** — o antes e o depois, no campo canônico;
 * 4. **contra quem?** — a versão Ford comparável;
 * 5. **como vocês sabem?** — a citação literal e o snapshot com hash e data.
 *
 * Duas decisões carregam o valor da tela:
 *
 * * **etiqueta em cada elo.** A mudança é FATO (o valor mudou, e há evidência); a
 *   materialidade e a ação são INFERÊNCIA — vêm de uma régua de pesos que é hipótese
 *   declarada. Misturar as duas coisas sob a mesma cor faria a tela prometer sobre a
 *   régua o que ela só pode prometer sobre a evidência;
 * * **nenhum elo em branco.** Onde o dado não existe, o elo mostra o motivo que a API
 *   manda. Um elo vazio parece prova; um elo que diz "sem evidência gravada para este
 *   lado da mudança" é conferível.
 *
 * **A forma, na v2:** os cinco elos são uma **linha do tempo vertical** com marcador
 * numerado. Um fio de 1 px liga os círculos, e a leitura desce sozinha da conclusão até a
 * prova. O modal centralizado virou painel lateral, pela mesma razão da gaveta de
 * evidência: a fila fica à vista enquanto a cadeia é lida.
 *
 * Acessibilidade fica com a `Gaveta`: `role="dialog"` com `aria-modal`, foco que entra e
 * volta, `Escape` que fecha e página que não rola atrás.
 */

import { useQuery } from '@tanstack/react-query'

import { Badge, FaixaDeSimulacao } from '@/components/Badge'
import { BlocoDeEvidencia } from '@/components/EvidenceDrawer'
import { Erro } from '@/components/Estados'
import { Gaveta } from '@/components/Gaveta'
import { api } from '@/lib/api'
import { mensagemDeErro } from '@/lib/erros'
import { formatarValor, rotularCampo } from '@/lib/formato'
import {
  CLASSES_DA_FAIXA,
  ICONE_DA_FAIXA,
  PONTO_DA_FAIXA,
  ROTULO_DA_FAIXA,
  formatarPontos,
  frasearInversao,
} from '@/lib/materialidade'
import { ROTULO_DO_TIPO } from '@/lib/radar'
import type { Cadeia, Etiqueta } from '@/lib/tipos'

/**
 * Um elo da linha do tempo.
 *
 * O fio vertical é um pseudo-elemento (`before:`) que liga o círculo deste elo ao do
 * próximo e some no último. Ligar os cinco é o que transforma cinco cartões empilhados
 * numa **cadeia**, e a cadeia é o argumento.
 *
 * O número não é enfeite: deixa a ordem explícita, inclusive em leitor de tela.
 */
function Elo({
  numero,
  titulo,
  etiqueta,
  children,
}: {
  numero: number
  titulo: string
  etiqueta?: Etiqueta
  children: React.ReactNode
}) {
  return (
    <li
      data-testid={`elo-${numero}`}
      className="relative pb-6 pl-10 last:pb-0 before:absolute before:left-[13px] before:top-8 before:h-[calc(100%-24px)] before:w-px before:bg-borda last:before:hidden"
    >
      <span
        aria-hidden="true"
        className="absolute left-0 top-0 flex h-7 w-7 items-center justify-center rounded-full bg-superficie-2 text-rotulo font-semibold text-tinta-2"
      >
        {numero}
      </span>
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <h4 className="text-meta font-semibold uppercase tracking-[0.06em] text-tinta-2">
          {titulo}
        </h4>
        {etiqueta ? <Badge etiqueta={etiqueta} /> : null}
      </div>
      <div className="mt-2 text-corpo text-tinta">{children}</div>
    </li>
  )
}

/**
 * Data e hora em **UTC**, pela mesma razão de `EvidenceDrawer`: o back-end grava em UTC, e
 * renderizar no fuso de quem olha muda o dia de uma coleta feita à meia-noite.
 */
function dataLegivel(iso: string): string {
  if (!iso) return 'data não registrada'
  const data = new Date(iso)
  if (Number.isNaN(data.getTime())) return iso
  return data.toLocaleString('pt-BR', { timeZone: 'UTC' })
}

/** O rótulo de um bloco de evidência do elo 5, a partir do lado que ela declara.
 *
 * `lado` ausente (contrato antigo, ou fonte que não diz) não vira "antes" por padrão:
 * vira "a prova", que é verdade sobre qualquer evidência do elo. Rotular por padrão foi
 * exatamente o defeito — dizer o lado errado é pior que não dizer o lado.
 */
function rotuloDoLado(
  lado: Cadeia['evidencias'][number]['lado'],
  mudanca: Cadeia['mudanca'],
): string {
  if (lado === 'antes') return `antes: ${formatarValor(mudanca.before)}`
  if (lado === 'depois') return `depois: ${formatarValor(mudanca.after)}`
  return 'a prova'
}

function Corpo({ cadeia }: { cadeia: Cadeia }) {
  const faixa = cadeia.materiality
  return (
    <>
      {/* A faixa de SIMULAÇÃO vem antes de tudo: quem olha de longe vê o aviso primeiro. */}
      {cadeia.is_simulated ? (
        <div className="mb-4">
          <FaixaDeSimulacao texto="SIMULAÇÃO: a cadeia abaixo é uma hipótese, não um fato observado" />
        </div>
      ) : null}

      <div
        data-testid="faixa-da-cadeia"
        className={`flex flex-wrap items-center gap-2 rounded-controle px-3 py-2 ${
          CLASSES_DA_FAIXA[faixa] ?? CLASSES_DA_FAIXA.BAIXA
        }`}
      >
        <span
          aria-hidden="true"
          className={`h-1.5 w-1.5 rounded-full ${PONTO_DA_FAIXA[faixa] ?? PONTO_DA_FAIXA.BAIXA}`}
        />
        <span className="text-rotulo font-semibold uppercase tracking-[0.06em]">
          materialidade {ROTULO_DA_FAIXA[faixa] ?? faixa}
        </span>
        <span className="mono text-meta">{formatarPontos(cadeia.pontos)}</span>
        <span className="sr-only">{ICONE_DA_FAIXA[faixa] ?? '·'}</span>
      </div>
      {cadeia.significado ? (
        <p className="mt-2 text-rotulo text-tinta-2">{cadeia.significado}</p>
      ) : null}

      <ol className="mt-6">
        <Elo numero={1} titulo="O que fazer" etiqueta="INFERENCIA">
          <p data-testid="acao-sugerida">{cadeia.acao_sugerida}</p>
        </Elo>

        <Elo numero={2} titulo="Por que esta materialidade" etiqueta="INFERENCIA">
          <ul data-testid="regras" className="space-y-2.5">
            {cadeia.regras.map((regra) => (
              <li key={regra.id} className="border-l-[3px] border-borda-forte pl-3">
                <p className="flex flex-wrap items-baseline gap-2">
                  <span className="mono text-meta text-tinta-3">{regra.id}</span>
                  <span className="mono font-medium text-tinta">
                    {regra.peso > 0 ? '+' : ''}
                    {regra.peso}
                  </span>
                  {regra.detalhe ? (
                    <span className="text-rotulo text-tinta-2">{regra.detalhe}</span>
                  ) : null}
                </p>
                <p className="text-rotulo text-tinta-2">{regra.descricao}</p>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-meta text-tinta-3">
            {cadeia.nota_dos_pesos}
            {cadeia.versao_das_regras ? ` Régua: ${cadeia.versao_das_regras}.` : ''}
          </p>
        </Elo>

        <Elo numero={3} titulo="O que mudou" etiqueta={cadeia.is_simulated ? 'SIMULACAO' : 'FATO'}>
          <p className="font-medium text-tinta">
            {cadeia.mudanca.campo_canonico
              ? rotularCampo(cadeia.mudanca.campo_canonico)
              : 'campo não identificado'}
          </p>
          <div className="mono mt-1.5 flex flex-wrap items-center gap-2">
            <span className="text-tinta-3 line-through">
              {formatarValor(cadeia.mudanca.before)}
            </span>
            <span aria-hidden="true" className="text-tinta-3">
              →
            </span>
            <span className="font-medium text-tinta">{formatarValor(cadeia.mudanca.after)}</span>
          </div>
          <p className="mt-1.5 text-meta text-tinta-3">
            {ROTULO_DO_TIPO[cadeia.mudanca.tipo_de_alerta ?? ''] ??
              cadeia.mudanca.tipo_de_alerta ??
              'tipo não informado'}
            {cadeia.mudanca.detectado_em
              ? ` · detectado em ${dataLegivel(cadeia.mudanca.detectado_em)}`
              : ''}
          </p>

          {cadeia.parity_flips.length > 0 ? (
            <ul data-testid="inversoes" className="mt-2 space-y-1 text-rotulo text-tinta-2">
              {cadeia.parity_flips.map((flip, indice) => (
                <li key={`${flip.campo}-${indice}`}>
                  <span className="font-medium text-tinta">
                    {flip.campo ? rotularCampo(flip.campo) : 'campo não informado'}:
                  </span>{' '}
                  {frasearInversao(flip.antes, flip.depois)}
                </li>
              ))}
            </ul>
          ) : null}
        </Elo>

        <Elo numero={4} titulo="Contra qual Ford" etiqueta="FATO">
          {cadeia.comparavel.rotulo ? (
            <p>{cadeia.comparavel.rotulo}</p>
          ) : (
            // O motivo em vez do branco: sem par não há como dizer o que a mudança faz
            // com a nossa posição, e isso é diferente de não ter olhado.
            <p data-testid="sem-comparavel" className="text-tinta-2">
              {cadeia.comparavel.motivo || 'par comparável não informado'}
            </p>
          )}
        </Elo>

        <Elo numero={5} titulo="A prova" etiqueta="FATO">
          {cadeia.evidencias.length > 0 ? (
            <ul>
              {/* O rótulo vem do LADO que a própria evidência declara, nunca do
                  índice na lista. O serviço filtra os `None` antes de montá-la, e com
                  só a evidência do "depois" — o caso do Fogo Amigo, que não grava
                  `evidence_before_id` — ela caía no índice 0 e a tela imprimia
                  "antes: 499" em cima da citação da página oficial da Ford. A citação
                  estava certa; o rótulo em cima dela era do lado errado (D-156). */}
              {cadeia.evidencias.map((evidencia) => (
                <BlocoDeEvidencia
                  key={evidencia.evidence_id}
                  evidencia={evidencia}
                  valor={rotuloDoLado(evidencia.lado, cadeia.mudanca)}
                />
              ))}
            </ul>
          ) : (
            <p
              data-testid="sem-evidencia"
              className="rounded-controle bg-superficie-2 px-3 py-2 text-rotulo text-tinta-2"
            >
              {cadeia.motivo_sem_evidencia}
            </p>
          )}

          {cadeia.snapshots.length > 0 ? (
            <dl data-testid="snapshots" className="mt-3 space-y-1 text-meta text-tinta-2">
              {cadeia.snapshots.map((snapshot) => (
                <div key={snapshot.snapshot_id} className="min-w-0">
                  <dt className="mono inline">{dataLegivel(snapshot.captured_at)}: </dt>
                  <dd className="mono inline break-all">
                    {snapshot.sha256 ?? 'sem hash gravado'}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p data-testid="sem-snapshot" className="mt-3 text-meta text-tinta-3">
              {cadeia.motivo_sem_snapshot}
            </p>
          )}
        </Elo>
      </ol>
    </>
  )
}

export function PorQueDrawer({
  alertaId,
  onFechar,
}: {
  alertaId: string
  onFechar: () => void
}) {
  const cadeia = useQuery({ queryKey: ['cadeia', alertaId], queryFn: () => api.cadeia(alertaId) })

  return (
    <Gaveta
      aberta
      aoFechar={onFechar}
      titulo="Por quê?"
      subtitulo="da ação sugerida até o trecho que a sustenta, em cinco elos"
      testId="gaveta-porque"
    >
      {cadeia.isPending ? (
        <p className="text-corpo text-tinta-2" aria-busy="true">
          carregando cadeia…
        </p>
      ) : null}
      {cadeia.error ? (
        <Erro>{mensagemDeErro(cadeia.error, 'abrir a cadeia deste alerta')}</Erro>
      ) : null}
      {cadeia.data ? <Corpo cadeia={cadeia.data} /> : null}
    </Gaveta>
  )
}
