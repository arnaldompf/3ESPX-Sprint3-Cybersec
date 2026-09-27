/**
 * Radar: os alertas de mudança, com o **antes e o depois** à vista.
 *
 * O alerta só vale se disser o que mudou de que para que. Um "houve mudança em preço" faz
 * o usuário ir conferir na mão — e a essa altura ele não precisava do alerta.
 *
 * Três decisões desta tela, e nenhuma é estética:
 *
 * * **o detalhe abre em linha, não em outra rota.** O que o usuário quer saber ao ver um
 *   alerta é "isso me afeta?", e a resposta é o impacto — que já veio na mesma listagem.
 *   Uma navegação no meio faz perder a lista de onde ele estava;
 * * **"sentido não determinado" é exibido como tal.** O impacto neutro não é escondido nem
 *   pintado de bom: o Radar existe para mostrar também onde o concorrente ganha
 *   (`docs/12` §1), e sumir com o alerta neutro seria escolher o que o usuário vê;
 * * **o ruído não sai do sistema.** Ele sai da *fila* — fica num bloco fechado, com a
 *   contagem à vista e um clique para abrir. Esconder por completo transformaria "não
 *   interromper ninguém" em "decidir o que o usuário pode ver".
 *
 * **A faixa de SIMULAÇÃO é uma por seção, não uma por alerta** (v2). A v1 repetia a faixa
 * laranja dentro de cada cartão e o efeito era o oposto do pretendido: sete faixas iguais
 * viram textura de fundo e param de avisar (`030_ANTI_PADROES.md` §26). Dentro da fila,
 * cada item leva só o pill SIMULAÇÃO.
 *
 * **A fila não recalcula nada.** A faixa, os pontos e a ordem vêm de `/events`; a tela
 * agrupa e traduz. O `significado` de cada faixa vem de `rules.yaml` pela API, para não
 * existir uma segunda definição do que é "ALTA" escrita em TypeScript.
 */
import { useState } from 'react'
import type { CSSProperties } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Badge, FaixaDeSimulacao } from '@/components/Badge'
import { BlocoDeEvidencia } from '@/components/EvidenceDrawer'
import { Card } from '@/components/Card'
import { Marcacao, Selecao } from '@/components/Campo'
import { Erro, EsqueletoDeLista, Recusa, Vazio, useEsqueleto } from '@/components/Estados'
import {
  Broadcast,
  CaretDown,
  CaretRight,
  Check,
  ICONE_DO_ALERTA,
  Question,
} from '@/components/Icones'
import { PorQueDrawer } from '@/components/PorQueDrawer'
import { api } from '@/lib/api'
import { mensagemDeErro } from '@/lib/erros'
import { atrasoDaLinha } from '@/lib/movimento'
import { usePapel } from '@/lib/papel'
import { ACAO_DA_TELA, papeisQuePodem, pode } from '@/lib/permissoes'
import { formatarValor, rotularCampo } from '@/lib/formato'
import {
  CLASSES_DA_FAIXA,
  ICONE_DA_FAIXA,
  ORDEM_DAS_FAIXAS,
  PONTO_DA_FAIXA,
  ROTULO_DA_FAIXA,
  formatarPontos,
} from '@/lib/materialidade'
import {
  AREAS,
  ROTULO_DA_DIMENSAO,
  ROTULO_DO_TIPO,
  formatarDelta,
  formatarPct,
  frasearGap,
  sentidoDe,
} from '@/lib/radar'
import type { EventoCompetitivo, Impacto, Materialidade } from '@/lib/tipos'

/** Os filtros da barra. `''` significa "todos", não "nenhum". */
const TIPOS_PARA_FILTRAR = [
  { valor: '', rotulo: 'todos os tipos' },
  ...Object.entries(ROTULO_DO_TIPO).map(([valor, rotulo]) => ({ valor, rotulo })),
]

function BlocoDeImpacto({ impacto }: { impacto: Impacto }) {
  const sentido = sentidoDe(impacto.direcao)
  const gap = frasearGap(impacto)

  return (
    <div
      data-testid="impacto"
      className="rounded-controle border border-borda bg-superficie p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-meta font-semibold uppercase tracking-[0.06em] text-tinta-2">
          Impacto
        </h4>
        <span
          data-testid="direcao"
          className={`inline-flex h-[22px] items-center gap-1.5 rounded-full px-2 text-meta font-semibold ${sentido.classe}`}
        >
          <span aria-hidden="true">{sentido.seta}</span>
          {sentido.rotulo}
        </span>
        <Badge etiqueta="FATO" />
      </div>

      <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-meta font-semibold uppercase tracking-[0.06em] text-tinta-3">
            Variação
          </dt>
          <dd className="mono mt-0.5 text-corpo text-tinta">
            {impacto.delta === null || impacto.delta === undefined ? (
              <span className="font-sans text-tinta-2">
                {impacto.motivo_sem_delta || 'não calculável'}
              </span>
            ) : (
              <>
                {formatarDelta(impacto.delta)}
                {impacto.delta_pct !== null && impacto.delta_pct !== undefined ? (
                  <span className="ml-1.5 text-tinta-2">({formatarPct(impacto.delta_pct)})</span>
                ) : null}
              </>
            )}
          </dd>
        </div>

        <div>
          <dt className="text-meta font-semibold uppercase tracking-[0.06em] text-tinta-3">
            Gap com a Ford
          </dt>
          <dd className={`mt-0.5 text-corpo ${gap.ehFato ? 'text-tinta' : 'text-tinta-2'}`}>
            {gap.texto}
          </dd>
        </div>
      </dl>

      {impacto.dimensoes_afetadas.length > 0 ? (
        <p className="mt-3 flex flex-wrap items-center gap-1.5 text-meta text-tinta-2">
          <span className="font-semibold">Dimensões afetadas:</span>
          {impacto.dimensoes_afetadas.map((dimensao) => (
            <span
              key={dimensao}
              className="rounded-[4px] bg-superficie-2 px-1.5 py-0.5 font-medium text-tinta"
            >
              {ROTULO_DA_DIMENSAO[dimensao] ?? dimensao}
            </span>
          ))}
        </p>
      ) : null}

      {!impacto.material ? (
        <p data-testid="nao-material" className="mt-3 text-meta text-tinta-2">
          Abaixo do limiar de materialidade (0,5%): variação pequena o bastante para ser
          ajuste de tabela. O alerta continua listado. Quem decide se importa é você.
        </p>
      ) : null}
    </div>
  )
}

function Detalhe({ id }: { id: string }) {
  const detalhe = useQuery({ queryKey: ['alerta', id], queryFn: () => api.alerta(id) })

  if (detalhe.isPending) {
    return (
      <p className="px-4 py-3 text-rotulo text-tinta-2" aria-busy="true">
        carregando detalhe…
      </p>
    )
  }
  if (detalhe.error) {
    return (
      <p role="alert" className="px-4 py-3 text-rotulo text-perdemos">
        {mensagemDeErro(detalhe.error, 'abrir este alerta')}
      </p>
    )
  }

  const dados = detalhe.data
  if (!dados) return null
  const evidencias = [
    { rotulo: 'antes', evidencia: dados.evidence_before, valor: formatarValor(dados.old) },
    { rotulo: 'depois', evidencia: dados.evidence_after, valor: formatarValor(dados.new) },
  ]

  return (
    <div className="space-y-4 border-t border-borda bg-superficie-2 px-4 py-4">
      {dados.impact ? <BlocoDeImpacto impacto={dados.impact} /> : null}

      {dados.reactions ? (
        <div
          data-testid="reacoes"
          className="rounded-controle border border-borda bg-superficie p-4"
        >
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-meta font-semibold uppercase tracking-[0.06em] text-tinta-2">
              O que fazer
            </h4>
            {/* Sugestão por regra, não por LLM: é INFERÊNCIA, e a etiqueta diz isso. */}
            <Badge etiqueta="INFERENCIA" />
          </div>
          <dl className="mt-3 space-y-3">
            {AREAS.map((area) => (
              <div key={area.chave}>
                <dt className="text-meta font-semibold uppercase tracking-[0.06em] text-tinta-3">
                  {area.rotulo}
                </dt>
                <dd className="mt-0.5 text-corpo text-tinta">{dados.reactions?.[area.chave]}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      <div className="rounded-controle border border-borda bg-superficie p-4">
        <h4 className="text-meta font-semibold uppercase tracking-[0.06em] text-tinta-2">
          Evidência
        </h4>
        <ul className="mt-2">
          {evidencias.map((item) =>
            item.evidencia ? (
              <BlocoDeEvidencia
                key={item.rotulo}
                evidencia={item.evidencia}
                valor={`${item.rotulo}: ${item.valor}`}
              />
            ) : (
              // Ausência de evidência é dita, não escondida: o alerta continua válido
              // (o valor mudou no banco), mas quem confere precisa saber que falta a ponta.
              <li
                key={item.rotulo}
                className="border-t border-borda py-3 text-rotulo text-tinta-2 first:border-t-0 first:pt-0"
              >
                sem evidência registrada para o valor {item.rotulo}
              </li>
            ),
          )}
        </ul>
      </div>
    </div>
  )
}

/** O pill de prioridade: ponto, palavra e os pontos em mono. Cor nunca sozinha. */
function PillDePrioridade({ evento }: { evento: EventoCompetitivo }) {
  return (
    <span
      data-testid={`faixa-${evento.materiality}`}
      title={evento.significado}
      className={[
        'inline-flex h-[22px] shrink-0 items-center gap-1.5 rounded-full px-2',
        'text-meta font-semibold uppercase tracking-[0.06em]',
        CLASSES_DA_FAIXA[evento.materiality] ?? CLASSES_DA_FAIXA.BAIXA,
      ].join(' ')}
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 rounded-full ${PONTO_DA_FAIXA[evento.materiality] ?? PONTO_DA_FAIXA.BAIXA}`}
      />
      {ROTULO_DA_FAIXA[evento.materiality] ?? evento.materiality}
      <span className="mono font-normal normal-case tracking-normal">
        {formatarPontos(evento.pontos)}
      </span>
      <span className="sr-only">{ICONE_DA_FAIXA[evento.materiality] ?? '·'}</span>
    </span>
  )
}

/**
 * Uma linha da fila.
 *
 * As ações aparecem no hover em telas com ponteiro (`group-hover`) e **sempre** no
 * celular: esconder ação atrás de hover num aparelho de toque é escondê-la de vez. Quem
 * usa teclado também as recebe, por `focus-within`.
 */
function LinhaDaFila({ evento, indice }: { evento: EventoCompetitivo; indice: number }) {
  const alerta = evento.alerta
  const cliente = useQueryClient()
  const [aberto, setAberto] = useState(false)
  const [porque, setPorque] = useState(false)
  const marcar = useMutation({
    mutationFn: () => api.marcarAlerta(alerta.id, { read: true }),
    onSuccess: () => cliente.invalidateQueries({ queryKey: ['eventos'] }),
  })
  const IconeDoTipo = ICONE_DO_ALERTA[alerta.type]

  return (
    <li
      data-testid={`alerta-${alerta.id}`}
      style={{ '--atraso': atrasoDaLinha(indice) } as CSSProperties}
      className="linha-entra group border-b border-borda last:border-b-0"
    >
      {/* Em ≤ 768 px a linha vira bloco: pill e tipo, campo, antes→depois, data, ações —
          cada um na sua linha. Espremer sete elementos em 390 px de largura foi o que
          fazia "Preço sugerido brl" quebrar em três linhas de uma palavra. */}
      <div
        className={[
          // `md:flex-wrap` carrega o peso da correção de 12/09/2026. Os cinco blocos
          // desta linha são todos `shrink-0` menos a coluna de informação, que é
          // `flex-1` com base 0: quando a soma dos rígidos passa da largura (1099 px
          // numa linha de 1094, em 1440), a coluna era espremida até ZERO e o rótulo
          // "divergência com material interno" saía empilhado em quatro linhas de uma
          // palavra. Com `flex-wrap`, as ações descem para a segunda linha em vez de
          // esmagar o texto — e nada é recortado.
          'flex flex-col gap-2 px-4 py-3 md:flex-row md:flex-wrap md:items-center md:gap-3',
          'transition-colors duration-150 ease-out',
          alerta.lido ? 'hover:bg-superficie-2' : 'bg-marca-50/40 hover:bg-marca-50',
        ].join(' ')}
      >
        <span className="flex flex-wrap items-center gap-2 md:contents">
          <PillDePrioridade evento={evento} />

          {/* `md:min-w-[12rem]`: o piso que faltava. Em `rem` e não em `px` porque
              `web/src/test/viewport.test.tsx` reprova `min-w-[Npx]` acima de 320. */}
          <span className="flex min-w-0 flex-col md:min-w-[12rem] md:flex-1">
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-tinta">
                {alerta.field ? rotularCampo(alerta.field) : 'campo não identificado'}
              </span>
              {/* A etiqueta é irremovível, não condicional: o antes→depois é um par de
                  valores, e nenhum valor aparece sem dizer de onde vem. */}
              <Badge etiqueta={alerta.is_simulated ? 'SIMULACAO' : 'FATO'} />
            </span>
            <span
              data-testid="tipo-do-alerta"
              title={ROTULO_DO_TIPO[alerta.type] ?? alerta.type}
              className="flex min-w-0 items-center gap-1 text-meta text-tinta-3"
            >
              {IconeDoTipo ? <IconeDoTipo size={14} aria-hidden="true" className="shrink-0" /> : null}
              {ROTULO_DO_TIPO[alerta.type] ?? alerta.type}
            </span>
          </span>
        </span>

        {/* O antes e o depois, sempre os dois. */}
        <span className="mono flex min-w-0 shrink-0 flex-wrap items-center gap-2 text-rotulo">
          <span className="text-tinta-3 line-through">{formatarValor(alerta.old)}</span>
          <span aria-hidden="true" className="text-tinta-3">
            →
          </span>
          <span className="font-medium text-tinta">{formatarValor(alerta.new)}</span>
        </span>

        <span className="mono shrink-0 text-meta text-tinta-3">
          {new Date(alerta.created_at).toLocaleDateString('pt-BR')}
          {alerta.tratado ? ' · tratado' : ''}
        </span>

        <span className="flex flex-wrap items-center gap-1 md:shrink-0 md:opacity-0 md:transition-opacity md:duration-150 md:ease-out md:group-focus-within:opacity-100 md:group-hover:opacity-100">
          <button
            type="button"
            aria-expanded={aberto}
            onClick={() => setAberto((valor) => !valor)}
            className="inline-flex h-8 items-center gap-1 rounded-controle px-2 text-meta font-medium text-tinta-2 transition-colors duration-150 ease-out hover:bg-superficie-2 hover:text-tinta"
          >
            {aberto ? (
              <CaretDown size={14} aria-hidden="true" />
            ) : (
              <CaretRight size={14} aria-hidden="true" />
            )}
            {aberto ? 'esconder impacto' : 'ver impacto'}
          </button>
          {/* Dois cliques até a prova: este botão é o primeiro (`specs/WP-34.md`). */}
          <button
            type="button"
            onClick={() => setPorque(true)}
            className="inline-flex h-8 items-center gap-1 rounded-controle border border-borda-forte px-2 text-meta font-medium text-tinta transition-colors duration-150 ease-out hover:bg-superficie-2"
          >
            <Question size={14} aria-hidden="true" />
            Por quê?
          </button>
          {!alerta.lido ? (
            <button
              type="button"
              onClick={() => marcar.mutate()}
              className="inline-flex h-8 items-center gap-1 rounded-controle px-2 text-meta font-medium text-tinta-2 transition-colors duration-150 ease-out hover:bg-superficie-2 hover:text-tinta"
            >
              <Check size={14} aria-hidden="true" />
              marcar como lido
            </button>
          ) : null}
        </span>
      </div>

      {aberto ? <Detalhe id={alerta.id} /> : null}
      {porque ? <PorQueDrawer alertaId={alerta.id} onFechar={() => setPorque(false)} /> : null}
    </li>
  )
}

/**
 * Um grupo da fila. `colapsado` fecha o bloco **sem** tirar os alertas da contagem: o
 * ruído continua listado, e o número dele fica à vista no cabeçalho do grupo.
 */
function GrupoDaFila({
  faixa,
  eventos,
  colapsado,
  onAlternar,
}: {
  faixa: Materialidade
  eventos: EventoCompetitivo[]
  colapsado: boolean
  onAlternar: () => void
}) {
  const significado = eventos[0]?.significado ?? ''
  const simulados = eventos.filter((evento) => evento.is_simulated).length
  return (
    <section data-testid={`grupo-${faixa}`} className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
        <h3
          className={[
            'inline-flex h-7 items-center gap-1.5 rounded-controle px-2.5',
            'text-rotulo font-semibold uppercase tracking-[0.06em]',
            CLASSES_DA_FAIXA[faixa],
          ].join(' ')}
        >
          <span
            aria-hidden="true"
            className={`h-1.5 w-1.5 rounded-full ${PONTO_DA_FAIXA[faixa]}`}
          />
          {ROTULO_DA_FAIXA[faixa]}
        </h3>
        <span className="mono text-rotulo text-tinta-2">{eventos.length} alerta(s)</span>
        {significado ? (
          <span className="w-full text-rotulo text-tinta-2 md:w-auto md:min-w-0 md:flex-1">
            {significado}
          </span>
        ) : null}
        {faixa === 'RUIDO' ? (
          <button
            type="button"
            aria-expanded={!colapsado}
            onClick={onAlternar}
            className="text-rotulo font-medium text-marca-700 hover:underline"
          >
            {colapsado ? 'abrir o ruído' : 'colapsar o ruído'}
          </button>
        ) : null}
      </div>

      {/* Uma faixa por SEÇÃO: dentro da lista, cada item leva só o pill. */}
      {!colapsado && simulados > 0 ? (
        <FaixaDeSimulacao>
          ({simulados} de {eventos.length} alerta(s) deste grupo)
        </FaixaDeSimulacao>
      ) : null}

      {colapsado ? null : (
        <ul className="overflow-hidden rounded-cartao border border-borda bg-superficie shadow-cartao">
          {eventos.map((evento, indice) => (
            <LinhaDaFila key={evento.id} evento={evento} indice={indice} />
          ))}
        </ul>
      )}
    </section>
  )
}

export function Radar() {
  const [tipo, setTipo] = useState('')
  const [incluirSimulados, setIncluirSimulados] = useState(true)
  const [ruidoColapsado, setRuidoColapsado] = useState(true)
  const papel = usePapel()
  // **Quem decide é a tela** (D-204). Antes o servidor devolvia 403 e a tela traduzia; sem
  // autenticação ele responde a todo mundo, e a decisão de produto ("o Radar é tela
  // interna") passou a ser aplicada aqui, com a mesma matriz de `docs/12` §6.6. `enabled`
  // e não só o retorno antecipado: sem isso a chamada sairia e voltaria com a fila que a
  // tela não vai mostrar.
  const podeVer = pode(papel, ACAO_DA_TELA.radar)
  const eventos = useQuery({
    queryKey: ['eventos', papel, tipo, incluirSimulados],
    queryFn: () => api.eventos({ tipo: tipo || undefined, incluirSimulados }),
    enabled: podeVer,
  })
  const carregando = useEsqueleto(podeVer && eventos.isPending)

  if (!podeVer) {
    return (
      <Recusa papeis={papeisQuePodem(ACAO_DA_TELA.radar)}>
        O Radar acompanha o que mudou no concorrente e o que isso muda aqui. Se você
        precisa desse acompanhamento, troque o papel na barra lateral. No Showroom você
        continua com a comparação e o argumentário.
      </Recusa>
    )
  }

  if (eventos.error) {
    return (
      <Card>
        <Erro>{mensagemDeErro(eventos.error, 'carregar a fila de alertas')}</Erro>
      </Card>
    )
  }

  const lista = eventos.data ?? []
  // A ordem dos grupos é a do motor (`BASE_DO_RANK`), e dentro do grupo é a da API, que já
  // vem por `priority_rank`. A tela agrupa; ela não reordena.
  const grupos = ORDEM_DAS_FAIXAS.map((faixa) => ({
    faixa,
    eventos: lista.filter((evento) => evento.materiality === faixa),
  })).filter((grupo) => grupo.eventos.length > 0)

  return (
    <div className="space-y-6">
      {/* A barra de filtros tem 56 px e não é um cartão: o dado é o herói. */}
      <div className="flex flex-wrap items-center gap-4 rounded-cartao border border-borda bg-superficie px-4 py-2.5 shadow-cartao">
        <Selecao
          rotulo="Tipo"
          className="w-full sm:w-64"
          value={tipo}
          onChange={(evento) => setTipo(evento.target.value)}
        >
          {TIPOS_PARA_FILTRAR.map((opcao) => (
            <option key={opcao.valor} value={opcao.valor}>
              {opcao.rotulo}
            </option>
          ))}
        </Selecao>

        <Marcacao
          rotulo="incluir dados de demonstração"
          checked={incluirSimulados}
          onChange={(evento) => setIncluirSimulados(evento.target.checked)}
          className="sm:mt-6"
        />

        <span className="mono ml-auto text-rotulo text-tinta-2 sm:mt-6">
          {lista.length} alerta(s) na fila
        </span>
      </div>

      {carregando ? (
        <div className="rounded-cartao border border-borda bg-superficie p-4 shadow-cartao">
          <EsqueletoDeLista linhas={6} />
        </div>
      ) : null}

      {!eventos.isPending && lista.length === 0 ? (
        <Card>
          <Vazio icone={Broadcast} titulo="Nenhuma mudança detectada">
            Silêncio aqui é resultado, não falta de dado: o diff só gera alerta quando um
            valor muda de verdade entre duas coletas.
          </Vazio>
        </Card>
      ) : null}

      {grupos.map((grupo) => (
        <GrupoDaFila
          key={grupo.faixa}
          faixa={grupo.faixa}
          eventos={grupo.eventos}
          colapsado={grupo.faixa === 'RUIDO' && ruidoColapsado}
          onAlternar={() => setRuidoColapsado((valor) => !valor)}
        />
      ))}
    </div>
  )
}
