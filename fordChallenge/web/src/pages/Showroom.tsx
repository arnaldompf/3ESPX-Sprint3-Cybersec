/**
 * Showroom: o perfil do cliente e a comparação ponderada por ele.
 *
 * Duas telas num fluxo (`docs/12` §6.2): o vendedor monta o perfil — uso, ranking de
 * prioridades, km/mês, preços de combustível — e a comparação aparece ponderada por aquele
 * perfil, com **os pesos à vista**.
 *
 * Três regras da tela, e nenhuma é estética:
 *
 * * **o rótulo obrigatório aparece junto do número**, sempre: "Aderência ao perfil
 *   informado, não é um ranking de qualidade". Sem ele, "7,8" se lê como nota do carro, e
 *   trocar o perfil muda o número sem nada mudar no veículo;
 * * **"sem dado comparável: X" fica na dimensão**, com o nome dos campos. A dimensão
 *   excluída do total aparece marcada em vez de sumir: falta de dado não pode virar nota
 *   baixa nem silêncio;
 * * **"ver como foi calculado" abre a conta**: peso, campos usados, nota por campo e a
 *   faixa que produziu cada nota. O vendedor vai defender esse número na frente do cliente.
 *
 * O ranking usa **botões de subir/descer** em vez de arrastar. A spec diz "arrastável", e a
 * troca é deliberada: arrastar não funciona com teclado nem com leitor de tela, e a
 * semântica de reordenar é idêntica. Está registrado em `DECISOES_NOITE.md`.
 *
 * **O stepper, e por que só no celular** (v2). A v1 era uma coluna vertical longa: dois
 * seletores, cinco caixas de uso, sete prioridades com setas de 12 px e três campos de
 * preço, tudo antes do botão. Num celular isso é rolagem cega. O stepper de cinco passos
 * resolve — e vale **até 768 px**, que é onde o vendedor está. Em tela larga os cinco
 * blocos aparecem empilhados, porque cinco cliques para preencher o que cabe inteiro numa
 * tela é burocracia, e a régua do topo vira índice. `lib/tela.ts` explica o mecanismo.
 */
import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { Badge } from '@/components/Badge'
import { BarrasDeAderencia, BarraDePeso } from '@/components/Barras'
import { Botao } from '@/components/Botao'
import { Card, CartaoDeMetrica, TituloDeSecao } from '@/components/Card'
import { Entrada, Selecao } from '@/components/Campo'
import { Chip } from '@/components/Chip'
import { Erro } from '@/components/Estados'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp } from '@/components/Icones'
import { BarraDoStepper, Stepper } from '@/components/Stepper'
import type { Passo } from '@/components/Stepper'
import { FotoDoVeiculo } from '@/components/Foto'
import { CREDITO_DAS_FOTOS, fotoDoRotulo } from '@/lib/fotos'
import { ErroDaApi, api, mensagemDeRecusa } from '@/lib/api'
import { usePapel } from '@/lib/papel'
import { ACAO_DA_TELA, papeisQuePodem, pode } from '@/lib/permissoes'
import { mensagemDeErro } from '@/lib/erros'
import { gravarFluxo, lerFluxo } from '@/lib/fluxoShowroom'
import { rotularCampo } from '@/lib/formato'
import { E_CELULAR, useMediaQuery } from '@/lib/tela'
import {
  PADRAO_CONCORRENTE,
  PADRAO_FORD,
  escolherPadrao,
  nomeCurto,
  nomeDoVeiculo,
} from '@/lib/veiculos'
import { PainelDeArgumentos, PainelDeResultado } from '@/pages/ShowroomAcoes'
import { PainelDeRelatorio } from '@/pages/ShowroomRelatorio'
import type {
  Aderencia,
  ConcorrenteComFit,
  CustoDeUso,
  DimensaoAvaliada,
  Dimensoes,
  NeedsProfile,
  Veiculo,
} from '@/lib/tipos'

const ROTULO_DO_USO: Record<string, string> = {
  rural_carga: 'trabalho rural / carga',
  familia: 'família',
  cidade: 'cidade',
  off_road: 'fora de estrada',
  frota: 'frota',
}

const PASSOS: Passo[] = [
  { id: 'veiculos', rotulo: 'Veículos' },
  { id: 'uso', rotulo: 'Uso' },
  { id: 'prioridades', rotulo: 'Prioridades' },
  { id: 'custos', rotulo: 'Custo de uso' },
  { id: 'comparar', rotulo: 'Comparar' },
]

/**
 * De quanto em quanto tempo a tela pergunta pelo documento, e por quantas vezes.
 *
 * Pergunta de 1,5 em 1,5 s e desiste em 30 s. Passado isso sem o job sair de `pendente`,
 * a tela para de perguntar e diz o que houve: sem o worker de pé o job nunca anda, e
 * antes disto a tela ficava escrito "Gerando… (pendente)" indefinidamente (QA-BUG-12).
 */
const INTERVALO_DO_JOB = 1500
const ESPERA_DO_JOB = 30_000

const BRL = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  maximumFractionDigits: 0,
})

function reais(valor: number | null | undefined): string {
  return valor === null || valor === undefined ? 'sem valor' : BRL.format(valor)
}

/** A barra de uma nota 0–10. O número vai ao lado: barra sem número não é auditável. */
function BarraDeNota({ nota, rotulo }: { nota: number | null | undefined; rotulo: string }) {
  if (nota === null || nota === undefined) {
    return <span className="text-meta text-tinta-3">sem nota</span>
  }
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-2 min-w-[3rem] flex-1 overflow-hidden rounded-full bg-superficie-2"
        role="img"
        aria-label={`${rotulo}: nota ${nota.toFixed(1)} de 10`}
      >
        <div
          className="h-full rounded-full bg-marca-600"
          style={{ width: `${Math.max(0, Math.min(100, nota * 10))}%` }}
        />
      </div>
      <span className="mono w-10 shrink-0 text-right text-meta text-tinta">
        {nota.toFixed(1)}
      </span>
    </div>
  )
}

function LinhaDaDimensao({
  dimensao,
  rotuloFord,
  rotuloConcorrente,
}: {
  dimensao: DimensaoAvaliada
  rotuloFord: string
  rotuloConcorrente: string
}) {
  const [aberto, setAberto] = useState(false)
  return (
    <li
      data-testid={`dimensao-${dimensao.dimensao}`}
      className={[
        'border-b border-borda px-4 py-3 last:border-b-0',
        dimensao.insuficiente ? 'bg-naoSabemos-fundo' : '',
      ].join(' ')}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-tinta">{dimensao.rotulo}</span>
        {/* O peso é sempre exibido: `docs/12` §6.2. */}
        <span
          data-testid={`peso-${dimensao.dimensao}`}
          className="mono rounded-[4px] bg-superficie-2 px-1.5 py-0.5 text-meta text-tinta-2"
        >
          peso {dimensao.peso}%
        </span>
        {dimensao.insuficiente ? (
          <span className="inline-flex h-[22px] items-center rounded-full bg-naoSabemos-fundo px-2 text-meta font-semibold uppercase tracking-[0.06em] text-naoSabemos">
            insuficiente: fora do total
          </span>
        ) : null}
      </div>

      <dl className="mt-2 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2 text-rotulo">
          <dt className="w-40 shrink-0 truncate text-tinta-2">{rotuloFord}</dt>
          <dd className="min-w-0 flex-1">
            <BarraDeNota nota={dimensao.nota_ford} rotulo={rotuloFord} />
          </dd>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-rotulo">
          <dt className="w-40 shrink-0 truncate text-tinta-2">{rotuloConcorrente}</dt>
          <dd className="min-w-0 flex-1">
            <BarraDeNota nota={dimensao.nota_concorrente} rotulo={rotuloConcorrente} />
          </dd>
        </div>
      </dl>

      {dimensao.campos_sem_dado.length > 0 ? (
        <p data-testid={`sem-dado-${dimensao.dimensao}`} className="mt-2 text-meta text-naoSabemos">
          sem dado comparável:{' '}
          {dimensao.campos_sem_dado.map((c) => rotularCampo(c.campo)).join(', ')}
        </p>
      ) : null}

      {dimensao.aviso ? (
        <p className="mt-1 text-meta text-naoSabemos">{dimensao.aviso}</p>
      ) : null}

      {/* Uma nota quase zero ao lado de um dez comunica "este carro não tem o item", e
          `docs/12` §3 proíbe exagerar sobre o concorrente com a mesma força com que
          proíbe esconder onde ele vence. O número está certo — é o piso da faixa —, e o
          que faltava era nomear a régua e o tamanho da amostra. */}
      {dimensao.aviso_da_escala ? (
        <p
          data-testid={`escala-${dimensao.dimensao}`}
          className="mt-1 text-meta text-tinta-2"
        >
          {dimensao.aviso_da_escala}
        </p>
      ) : null}

      <button
        type="button"
        aria-expanded={aberto}
        onClick={() => setAberto((v) => !v)}
        className="mt-2 text-meta font-medium text-marca-700 hover:underline"
      >
        {aberto ? 'esconder o cálculo' : 'ver como foi calculado'}
      </button>

      {aberto ? (
        <div
          data-testid={`calculo-${dimensao.dimensao}`}
          className="mt-2 rounded-controle bg-superficie-2 p-3 text-meta"
        >
          <p className="text-tinta-2">
            campos usados: {dimensao.campos_usados.map(rotularCampo).join(', ') || 'nenhum'} ·
            cobertura:{' '}
            {dimensao.cobertura === null || dimensao.cobertura === undefined
              ? 'sem base'
              : `${Math.round(dimensao.cobertura * 100)}%`}
          </p>
          <table className="mt-2 w-full border-collapse">
            <thead>
              <tr className="text-left text-tinta-3">
                <th scope="col" className="py-1 font-semibold uppercase tracking-[0.06em]">
                  campo
                </th>
                <th scope="col" className="font-semibold uppercase tracking-[0.06em]">
                  nota Ford
                </th>
                <th scope="col" className="font-semibold uppercase tracking-[0.06em]">
                  nota conc.
                </th>
                <th scope="col" className="font-semibold uppercase tracking-[0.06em]">
                  como
                </th>
              </tr>
            </thead>
            <tbody>
              {dimensao.detalhe_ford.map((nota, indice) => (
                <tr key={nota.campo} className="border-t border-borda">
                  <th scope="row" className="py-1 text-left font-medium text-tinta">
                    {rotularCampo(nota.campo)}
                  </th>
                  <td className="mono text-tinta">{nota.nota ?? 'sem nota'}</td>
                  <td className="mono text-tinta">
                    {dimensao.detalhe_concorrente[indice]?.nota ?? 'sem nota'}
                  </td>
                  <td className="text-tinta-2">{nota.motivo || 'faixa do segmento'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </li>
  )
}

function BlocoDeCusto({ custo, rotulo }: { custo: CustoDeUso; rotulo: string }) {
  return (
    <div
      data-testid={`custo-${custo.version_id}`}
      className="rounded-controle border border-borda p-4"
    >
      <p className="font-medium text-tinta">{rotulo || custo.rotulo}</p>
      {custo.custo_mes === null || custo.custo_mes === undefined ? (
        <p className="mt-1 text-corpo text-tinta-2">{custo.motivo_sem_custo}</p>
      ) : (
        <>
          <p className="mono mt-1 text-[28px] font-medium leading-[34px] text-tinta">
            {reais(custo.custo_mes)}
            <span className="text-corpo font-normal text-tinta-2">/mês</span>
          </p>
          <p className="mono text-rotulo text-tinta-2">{reais(custo.custo_ano)} por ano</p>
          <p className="mt-2 text-meta text-tinta-2">
            {custo.consumo.valor_kml} km/l ({custo.consumo.rotulo_da_origem}) ·{' '}
            {custo.combustivel} a {reais(custo.preco_por_litro)}/L
          </p>
          <p className="mt-1.5 text-meta text-tinta-3">{custo.frase}</p>
        </>
      )}
    </div>
  )
}

function VenceEm({
  aderencia,
  rotuloFord,
  rotuloConcorrente,
  dimensoes,
}: {
  aderencia: Aderencia
  rotuloFord: string
  rotuloConcorrente: string
  dimensoes: Dimensoes | undefined
}) {
  const rotuloDe = (id: string) => dimensoes?.dimensoes.find((d) => d.id === id)?.rotulo ?? id
  return (
    <div data-testid="vence-em" className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div className="rounded-controle bg-ganhamos-fundo px-4 py-3">
        <p className="text-rotulo font-semibold text-ganhamos">Onde {rotuloFord} vence</p>
        <p className="mt-1 text-corpo text-tinta">
          {aderencia.vence_em.ford.map(rotuloDe).join(', ') || 'nenhuma dimensão comparável'}
        </p>
      </div>
      {/* Onde o concorrente vence aparece com o MESMO destaque. `docs/12` §3: o produto não
          esconde onde o concorrente ganha, e "mesmo destaque" é literal — mesmo tamanho,
          mesmo peso de fonte, mesma área. */}
      <div className="rounded-controle bg-perdemos-fundo px-4 py-3">
        <p className="text-rotulo font-semibold text-perdemos">Onde {rotuloConcorrente} vence</p>
        <p className="mt-1 text-corpo text-tinta">
          {aderencia.vence_em.concorrente.map(rotuloDe).join(', ') ||
            'nenhuma dimensão comparável'}
        </p>
      </div>
    </div>
  )
}

/**
 * O selo de resultado: **quem está à frente, e por quanto**.
 *
 * Os dois números apareciam soltos, um em cada cartão, e quem olhava tinha de fazer a
 * subtração de cabeça — com o cliente ao lado. O selo faz a conta e diz a diferença.
 *
 * **"Empate técnico" abaixo de 0,3** não é arredondamento preguiçoso: a nota é média
 * ponderada de notas de campo que já vêm arredondadas a duas casas, sobre faixas
 * construídas com quatro veículos. Uma diferença de 0,2 não sobrevive a um veículo novo na
 * amostra, e anunciá-la como vitória seria afirmar mais do que a régua sustenta.
 *
 * O texto diz **"à frente"**, e nunca "melhor": `docs/12` §3 — o score é aderência ao
 * perfil informado, não julgamento sobre qual carro é bom.
 */
const EMPATE_TECNICO = 0.3

export function seloDeResultado(
  ford: number | null,
  concorrente: number | null,
  rotuloFord: string,
  rotuloConcorrente: string,
): { texto: string; tom: 'ford' | 'concorrente' | 'empate' } | null {
  if (ford === null || concorrente === null) return null
  const diferenca = Math.round(Math.abs(ford - concorrente) * 10) / 10
  if (diferenca < EMPATE_TECNICO) {
    return { texto: 'empate técnico neste perfil', tom: 'empate' }
  }
  const numero = diferenca.toLocaleString('pt-BR', { minimumFractionDigits: 1 })
  return ford > concorrente
    ? { texto: `${rotuloFord} à frente por ${numero}`, tom: 'ford' }
    : { texto: `${rotuloConcorrente} à frente por ${numero}`, tom: 'concorrente' }
}

export function Showroom() {
  const dimensoes = useQuery({ queryKey: ['dimensoes'], queryFn: () => api.dimensoes() })
  const veiculos = useQuery({ queryKey: ['veiculos'], queryFn: () => api.veiculos() })

  const lista = veiculos.data ?? []
  const fords = lista.filter((v) => v.marca.toLowerCase() === 'ford')
  const outros = lista.filter((v) => v.marca.toLowerCase() !== 'ford')

  // O fluxo é restaurado de `sessionStorage` no primeiro render e regravado a cada
  // mudança. Sem isso, abrir a Ficha para conferir um campo e voltar custava seis toques
  // de novo — com o cliente ao lado. `useState(lerFluxo)` lê uma vez só; passar
  // `lerFluxo()` leria a cada render.
  const [inicial] = useState(lerFluxo)
  const [base, setBase] = useState(inicial.base)
  const [concorrente, setConcorrente] = useState(inicial.concorrente)
  const [usos, setUsos] = useState<string[]>(inicial.usos)
  const [ranking, setRanking] = useState<string[]>(inicial.ranking)
  const [kmMes, setKmMes] = useState(inicial.kmMes)
  const [precoDiesel, setPrecoDiesel] = useState(inicial.precoDiesel)
  const [precoGasolina, setPrecoGasolina] = useState(inicial.precoGasolina)
  const [passo, setPasso] = useState(inicial.passo)

  useEffect(() => {
    gravarFluxo({ base, concorrente, usos, ranking, kmMes, precoDiesel, precoGasolina, passo })
  }, [base, concorrente, usos, ranking, kmMes, precoDiesel, precoGasolina, passo])

  const umPassoPorVez = useMediaQuery(E_CELULAR)

  // O par declarado em `docs/12` 6.1: Ranger Limited diesel x Hilux SRX Plus. Abrir
  // em `lista[0]` dava a S10 sem ficha, e a comparacao nascia sem numero nenhum.
  const idBase = base || escolherPadrao(fords, PADRAO_FORD)
  const idConcorrente = concorrente || escolherPadrao(outros, PADRAO_CONCORRENTE)
  const ordemInicial = dimensoes.data?.dimensoes.map((d) => d.id) ?? []
  const prioridades = ranking.length > 0 ? ranking : ordemInicial

  const argumentos = useMutation({
    mutationFn: (comparisonId: string) =>
      api.argumentos(comparisonId, {
        uso: usos,
        prioridades_rank: prioridades,
        km_mes: numeroDe(kmMes),
      }),
  })

  // O job do relatorio: 202 na hora, e a tela acompanha. `refetchInterval` para de si
  // mesmo quando o job termina — nao ha polling eterno em segundo plano.
  const pedirRelatorio = useMutation({
    mutationFn: (comparisonId: string) =>
      api.pedirRelatorio(comparisonId, {
        uso: usos,
        prioridades_rank: prioridades,
        km_mes: numeroDe(kmMes),
        combustivel_preco: {
          diesel: numeroDe(precoDiesel),
          gasolina: numeroDe(precoGasolina),
        },
      }),
  })

  /**
   * O relógio do documento: passado `ESPERA_DO_JOB` sem o job sair de `pendente`, a tela
   * assume que a fila não está respondendo e diz isso. Reinicia a cada pedido novo.
   *
   * Declarado **antes** da consulta de propósito: `refetchInterval` é lido já na
   * montagem do observador, no mesmo render — com a declaração depois, a tela inteira
   * morria com "Cannot access before initialization" e o Showroom abria em branco.
   */
  const [relatorioTravou, setRelatorioTravou] = useState(false)

  const jobDoRelatorio = useQuery({
    queryKey: ['job', pedirRelatorio.data?.job_id],
    queryFn: () => api.job(pedirRelatorio.data?.job_id ?? ''),
    enabled: Boolean(pedirRelatorio.data?.job_id),
    refetchInterval: (consulta) => {
      const estado = consulta.state.data?.status
      if (estado === 'concluido' || estado === 'falhou') return false
      // Desiste quando o relógio abaixo estoura. Sem o worker de pé, o job **nunca** sai
      // de `pendente`, e a tela ficava perguntando para sempre, mostrando "Gerando…
      // (pendente)" e nada mais — medido em 11/09/2026 com o worker parado, 25 s depois a
      // mesma frase. O vendedor está na frente do cliente, e um relógio que não anda não
      // é resposta (QA-BUG-12). O job continua na fila do servidor: quem desiste é a
      // pergunta, não o trabalho.
      if (relatorioTravou) return false
      return INTERVALO_DO_JOB
    },
  })


  const jobPedido = pedirRelatorio.data?.job_id
  const jobTerminou =
    jobDoRelatorio.data?.status === 'concluido' || jobDoRelatorio.data?.status === 'falhou'
  useEffect(() => {
    setRelatorioTravou(false)
    if (!jobPedido || jobTerminou) return
    const relogio = setTimeout(() => setRelatorioTravou(true), ESPERA_DO_JOB)
    return () => clearTimeout(relogio)
  }, [jobPedido, jobTerminou])

  /**
   * Abrir sessão de showroom é do vendedor, do gestor e do admin. O **analista não atende
   * no salão** (`docs/12` §6.6) — e isso continua valendo agora que quem decide é a tela
   * (D-204), porque a decisão é de produto e não de segurança.
   *
   * A mensagem aparece **depois do clique**, e não no lugar do botão, de propósito: é a
   * cena do roteiro ("o analista clica em abrir sessão e a tela diz o papel que falta").
   * Um botão que some não ensina nada a quem estava procurando por ele.
   */
  const papel = usePapel()
  const podeAbrirSessao = pode(papel, ACAO_DA_TELA.showroom)
  const [tentouAbrirSemPapel, setTentouAbrirSemPapel] = useState(false)
  const recusaDaSessao =
    tentouAbrirSemPapel && !podeAbrirSessao
      ? `Seu perfil não pode abrir a sessão de showroom. Quem atende no salão é ${papeisQuePodem(
          ACAO_DA_TELA.showroom,
        )}. Troque o papel na barra lateral.`
      : undefined

  const abrirSessao = useMutation({
    mutationFn: () =>
      api.criarSessao({
        ford_version_id: idBase,
        competitor_version_ids: [idConcorrente],
        comparison_id: `${idBase}:${idConcorrente}`,
        needs_profile: { uso: usos, prioridades_rank: prioridades },
      }),
  })

  const fecharSessao = useMutation({
    mutationFn: (dados: { outcome: string; motivos: string[]; atributo_decisivo?: string }) =>
      api.fecharSessao(abrirSessao.data?.id ?? '', dados),
  })

  const comparar = useMutation({
    mutationFn: () => {
      const perfil: NeedsProfile = {
        uso: usos,
        prioridades_rank: prioridades,
        km_mes: numeroDe(kmMes),
        combustivel_preco: {
          diesel: numeroDe(precoDiesel),
          gasolina: numeroDe(precoGasolina),
        },
      }
      return api.comparar(idBase, [idConcorrente], perfil)
    },
  })

  function mover(indice: number, direcao: -1 | 1) {
    const alvo = indice + direcao
    if (alvo < 0 || alvo >= prioridades.length) return
    const nova = [...prioridades]
    const atual = nova[indice]
    const trocado = nova[alvo]
    if (atual === undefined || trocado === undefined) return
    nova[indice] = trocado
    nova[alvo] = atual
    setRanking(nova)
  }

  const pesos = dimensoes.data?.pesos_por_rank ?? []
  const fit = comparar.data?.fit
  const primeiro: ConcorrenteComFit | undefined = fit?.concorrentes[0]

  /** Um passo aparece quando é o atual, ou quando a tela é larga e mostra todos. */
  const mostra = (indice: number) => !umPassoPorVez || passo === indice

  return (
    <div className="space-y-6">
      <Stepper passos={PASSOS} atual={passo} aoIr={setPasso} />

      <p className="text-rotulo text-tinta-2">
        Perfil <span className="font-medium text-tinta">anônimo</span>: nada aqui identifica
        a pessoa, e a API recusa campo que não seja destes.
      </p>

      {/* ------------------------------------------------------------ 1. veículos */}
      {mostra(0) ? (
        <Card titulo="Veículos" descricao="O par que vai à comparação.">
          {/* Falha ao listar os veículos **fala**. `veiculos.data ?? []` sozinho engolia
              o erro: com a API fora, os dois seletores saíam sem uma opção, o botão de
              comparar não levava a lugar nenhum e a tela parecia normal — na frente do
              cliente (QA-BUG-14). */}
          {veiculos.error ? (
            <div className="mb-4">
              <Erro>{mensagemDeErro(veiculos.error, 'listar os veículos')}</Erro>
            </div>
          ) : null}
          <div className="grid gap-4 sm:grid-cols-2">
            <Selecao
              rotulo="Ford"
              aria-label="versão Ford"
              value={idBase}
              onChange={(e) => setBase(e.target.value)}
            >
              {fords.map((v: Veiculo) => (
                <option key={v.id} value={v.id}>
                  {nomeCurto(v)}
                </option>
              ))}
            </Selecao>
            <Selecao
              rotulo="Concorrente"
              aria-label="concorrente"
              value={idConcorrente}
              onChange={(e) => setConcorrente(e.target.value)}
            >
              {outros.map((v: Veiculo) => (
                <option key={v.id} value={v.id}>
                  {nomeDoVeiculo(v)}
                </option>
              ))}
            </Selecao>
          </div>
        </Card>
      ) : null}

      {/* ----------------------------------------------------------------- 2. uso */}
      {mostra(1) ? (
        <Card titulo="Uso" descricao="Para que o cliente vai usar a picape. Pode marcar mais de um.">
          <fieldset>
            <legend className="sr-only">uso do veículo</legend>
            <div className="flex flex-wrap gap-2">
              {(dimensoes.data?.usos ?? []).map((uso) => (
                <Chip
                  key={uso}
                  selecionado={usos.includes(uso)}
                  onAlternar={() =>
                    setUsos((atuais) =>
                      atuais.includes(uso) ? atuais.filter((u) => u !== uso) : [...atuais, uso],
                    )
                  }
                >
                  {ROTULO_DO_USO[uso] ?? uso}
                </Chip>
              ))}
            </div>
          </fieldset>
        </Card>
      ) : null}

      {/* -------------------------------------------------------- 3. prioridades */}
      {mostra(2) ? (
        <Card
          titulo="Prioridades, da mais importante para a menos"
          descricao={`Os cinco primeiros recebem ${pesos.join('%, ')}%. Do sexto em diante, peso zero, e a dimensão continua aparecendo com o peso à vista.`}
        >
          {/* Lista vazia enquanto as dimensões não chegam ficaria como um `<ol>` numerado
              sem itens — parece tela quebrada. Diz que está carregando. */}
          {prioridades.length === 0 ? (
            <p className="text-corpo text-tinta-2">carregando as dimensões…</p>
          ) : null}
          <ol data-testid="ranking" className="divide-y divide-borda">
            {prioridades.map((id, indice) => {
              const rotulo = dimensoes.data?.dimensoes.find((d) => d.id === id)?.rotulo ?? id
              const peso = pesos[indice] ?? 0
              return (
                <li key={id} className="flex items-center gap-3 py-2">
                  <span className="mono w-6 shrink-0 text-right text-rotulo text-tinta-3">
                    {indice + 1}º
                  </span>
                  <span className="min-w-0 flex-1 truncate text-corpo text-tinta">{rotulo}</span>
                  <BarraDePeso peso={peso} />
                  <span className="flex shrink-0 gap-1">
                    <button
                      type="button"
                      aria-label={`subir ${rotulo}`}
                      onClick={() => mover(indice, -1)}
                      disabled={indice === 0}
                      className="flex h-9 w-9 items-center justify-center rounded-controle border border-borda-forte text-tinta-2 transition-colors duration-150 ease-out hover:bg-superficie-2 disabled:opacity-30"
                    >
                      <ArrowUp size={14} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      aria-label={`descer ${rotulo}`}
                      onClick={() => mover(indice, 1)}
                      disabled={indice === prioridades.length - 1}
                      className="flex h-9 w-9 items-center justify-center rounded-controle border border-borda-forte text-tinta-2 transition-colors duration-150 ease-out hover:bg-superficie-2 disabled:opacity-30"
                    >
                      <ArrowDown size={14} aria-hidden="true" />
                    </button>
                  </span>
                </li>
              )
            })}
          </ol>
        </Card>
      ) : null}

      {/* ------------------------------------------------------------- 4. custos */}
      {mostra(3) ? (
        <Card
          titulo="Custo de uso"
          descricao="Entram na estimativa de combustível. Os preços são os que o cliente paga na região."
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <Entrada
              rotulo="km por mês"
              aria-label="km por mês"
              value={kmMes}
              onChange={(e) => setKmMes(e.target.value)}
              inputMode="numeric"
            />
            <Entrada
              rotulo="Diesel R$/L"
              aria-label="preço do diesel"
              value={precoDiesel}
              onChange={(e) => setPrecoDiesel(e.target.value)}
              inputMode="decimal"
            />
            <Entrada
              rotulo="Gasolina R$/L"
              aria-label="preço da gasolina"
              value={precoGasolina}
              onChange={(e) => setPrecoGasolina(e.target.value)}
              inputMode="decimal"
            />
          </div>
        </Card>
      ) : null}

      {/* ---------------------------------------------------------- 5. comparar */}
      {mostra(4) ? (
        <Card
          titulo="Comparar"
          descricao="A comparação é ponderada pelo perfil acima, e mostra onde cada um vence."
        >
          <Botao
            tom="primario"
            onClick={() => comparar.mutate()}
            disabled={!idBase || !idConcorrente || comparar.isPending}
          >
            {comparar.isPending ? 'calculando…' : 'comparar por este perfil'}
          </Botao>
        </Card>
      ) : null}

      {umPassoPorVez ? (
        <BarraDoStepper>
          <Botao
            onClick={() => setPasso((p) => Math.max(0, p - 1))}
            disabled={passo === 0}
            icone={<ArrowLeft size={16} />}
          >
            voltar
          </Botao>
          <Botao
            tom="primario"
            onClick={() => setPasso((p) => Math.min(PASSOS.length - 1, p + 1))}
            disabled={passo === PASSOS.length - 1}
            icone={<ArrowRight size={16} />}
          >
            avançar
          </Botao>
        </BarraDoStepper>
      ) : null}

      {comparar.error ? (
        <Card>
          <Erro
            titulo={
              comparar.error instanceof ErroDaApi ? comparar.error.titulo : 'Não deu para comparar'
            }
          >
            {mensagemDeErro(comparar.error, 'comparar por este perfil')}
          </Erro>
        </Card>
      ) : null}

      {/* =================================================== a página de resultado */}
      {fit && primeiro ? (
        <div className="space-y-6 border-t border-borda pt-6">
          <section className="space-y-4">
            <TituloDeSecao descricao={fit.rotulo}>Aderência ao perfil</TituloDeSecao>

            {/* A foto de cada lado, acima da nota. **É a cena mais vista da apresentação**
                e a única em que duas picapes aparecem lado a lado: sem foto, o vendedor
                aponta para dois nomes. Ela não afirma nada e não entra na conta — a nota
                continua sendo aderência ao perfil informado, com os pesos à vista. O
                crédito aparece uma vez, embaixo das duas. */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-3">
                <FotoDoVeiculo src={fotoDoRotulo(fit.base.rotulo)} alt={fit.base.rotulo} credito={false} />
                <CartaoDeMetrica
                  rotulo={fit.base.rotulo}
                  valor={
                    <span data-testid="aderencia-ford">
                      {primeiro.aderencia.aderencia_ford ?? 'sem nota'}
                    </span>
                  }
                  etiqueta={<Badge etiqueta="INFERENCIA" />}
                />
              </div>
              <div className="space-y-3">
                <FotoDoVeiculo
                  src={fotoDoRotulo(primeiro.rotulo)}
                  alt={primeiro.rotulo}
                  credito={false}
                />
                <CartaoDeMetrica
                  rotulo={primeiro.rotulo}
                  valor={
                    <span data-testid="aderencia-concorrente">
                      {primeiro.aderencia.aderencia_concorrente ?? 'sem nota'}
                    </span>
                  }
                  etiqueta={<Badge etiqueta="INFERENCIA" />}
                />
              </div>
            </div>

            {/* O selo faz a subtração que o vendedor faria de cabeça, com o cliente ao
                lado. "à frente", e nunca "melhor": `docs/12` §3. */}
            {(() => {
              const selo = seloDeResultado(
                primeiro.aderencia.aderencia_ford,
                primeiro.aderencia.aderencia_concorrente,
                fit.base.rotulo,
                primeiro.rotulo,
              )
              if (!selo) return null
              const cor =
                selo.tom === 'ford'
                  ? 'bg-ganhamos-fundo text-ganhamos'
                  : selo.tom === 'concorrente'
                    ? 'bg-perdemos-fundo text-perdemos'
                    : 'bg-empate-fundo text-empate'
              return (
                <p
                  data-testid="selo-de-resultado"
                  className={`inline-flex items-center gap-2 rounded-cartao px-3 py-2 text-corpo font-medium ${cor}`}
                >
                  {selo.texto}
                </p>
              )
            })()}
            {fotoDoRotulo(fit.base.rotulo) || fotoDoRotulo(primeiro.rotulo) ? (
              <p className="text-meta text-tinta-3">{CREDITO_DAS_FOTOS}</p>
            ) : null}

            {/* O rótulo obrigatório, junto do número. `docs/12` §6.2. */}
            <p
              data-testid="rotulo-obrigatorio"
              className="rounded-controle bg-superficie-2 px-4 py-3 text-corpo font-medium text-tinta"
            >
              {fit.rotulo}
            </p>
            <p className="text-meta text-tinta-3">
              calculado sobre {primeiro.aderencia.peso_considerado}% do peso do perfil ·
              dimensões de {fit.versao_das_dimensoes} · faixas de {fit.versao_das_faixas}
            </p>
            {primeiro.aderencia.avisos.map((aviso) => (
              <p key={aviso} className="text-meta text-naoSabemos">
                {aviso}
              </p>
            ))}

            {/* Sem `?? 0`, e não é esquecimento: `docs/12` §6.2 — nota ausente não é
                zero, e o próprio motor diz que "um zero aqui seria invenção". A barra sabe
                desenhar `null`. Se alguém "consertar" isto de volta, o cartão volta a
                dizer "sem nota" com uma barra de 0 de 10 embaixo. */}
            <BarrasDeAderencia
              maximo={10}
              ford={{ rotulo: fit.base.rotulo, valor: primeiro.aderencia.aderencia_ford }}
              concorrente={{
                rotulo: primeiro.rotulo,
                valor: primeiro.aderencia.aderencia_concorrente,
              }}
            />
          </section>

          <section className="space-y-3">
            <TituloDeSecao descricao="O produto não esconde onde o concorrente ganha.">
              Onde cada um vence
            </TituloDeSecao>
            <VenceEm
              aderencia={primeiro.aderencia}
              rotuloFord={fit.base.rotulo}
              rotuloConcorrente={primeiro.rotulo}
              dimensoes={dimensoes.data}
            />
          </section>

          <section className="space-y-3">
            <TituloDeSecao descricao="Cada dimensão com o peso, as duas notas e a conta aberta.">
              Por dimensão
            </TituloDeSecao>
            <ul className="overflow-hidden rounded-cartao border border-borda bg-superficie shadow-cartao">
              {primeiro.aderencia.dimensoes.map((dimensao) => (
                <LinhaDaDimensao
                  key={dimensao.dimensao}
                  dimensao={dimensao}
                  rotuloFord={fit.base.rotulo}
                  rotuloConcorrente={primeiro.rotulo}
                />
              ))}
            </ul>
          </section>

          <PainelDeArgumentos
            argumentario={argumentos.data}
            aoGerar={() => argumentos.mutate(`${idBase}:${idConcorrente}`)}
            carregando={argumentos.isPending}
          />

          <Card
            titulo="Custo de combustível estimado"
            descricao="Estimativa a partir do consumo medido e dos preços informados. Não é medição de uso real."
          >
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <BlocoDeCusto custo={fit.usage_cost_base} rotulo={fit.base.rotulo} />
              <BlocoDeCusto custo={primeiro.usage_cost} rotulo={primeiro.rotulo} />
            </div>
            {primeiro.custo_comparado.diferenca_ano !== null &&
            primeiro.custo_comparado.diferenca_ano !== undefined ? (
              <p data-testid="diferenca-anual" className="mt-4 text-corpo text-tinta">
                Diferença de{' '}
                <span className="mono font-medium">
                  {reais(Math.abs(primeiro.custo_comparado.diferenca_ano))}
                </span>{' '}
                por ano. Quem gasta menos:{' '}
                <span className="font-medium">
                  {primeiro.custo_comparado.quem_gasta_menos === 'ford'
                    ? fit.base.rotulo
                    : primeiro.custo_comparado.quem_gasta_menos === 'concorrente'
                      ? primeiro.rotulo
                      : 'empate'}
                </span>
                .
              </p>
            ) : (
              <p className="mt-4 text-corpo text-tinta-2">
                {primeiro.custo_comparado.motivo_sem_diferenca}
              </p>
            )}
          </Card>

          <PainelDeRelatorio
            job={jobDoRelatorio.data}
            rotuloFord={fit.base.rotulo}
            rotuloConcorrente={primeiro.rotulo}
            aoGerar={() => pedirRelatorio.mutate(`${idBase}:${idConcorrente}`)}
            gerando={pedirRelatorio.isPending}
            travou={relatorioTravou}
            erro={
              pedirRelatorio.error instanceof ErroDaApi ? pedirRelatorio.error.detalhe : undefined
            }
          />

          <PainelDeResultado
            sessao={fecharSessao.data ?? abrirSessao.data}
            aoAbrir={() =>
              podeAbrirSessao ? abrirSessao.mutate() : setTentouAbrirSemPapel(true)
            }
            aoFechar={(dados) => fecharSessao.mutate(dados)}
            salvando={fecharSessao.isPending}
            erroAoAbrir={
              recusaDaSessao ?? mensagemDeRecusa(abrirSessao.error, 'abrir a sessão de showroom')
            }
            erroAoFechar={mensagemDeRecusa(fecharSessao.error, 'registrar o resultado')}
          />
        </div>
      ) : null}
    </div>
  )
}

/** `"6,20"` → `6.2`. Vazio devolve `undefined`, não zero: preço zero seria um valor. */
function numeroDe(texto: string): number | undefined {
  const limpo = texto.replace(/\./g, '').replace(',', '.').trim()
  if (!limpo) return undefined
  const numero = Number(limpo)
  return Number.isFinite(numero) ? numero : undefined
}
