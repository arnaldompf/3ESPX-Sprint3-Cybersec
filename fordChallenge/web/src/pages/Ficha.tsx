/**
 * A Ficha: a tela que o produto existe para mostrar.
 *
 * Regras que a página impõe, todas de `docs/13` e do schema canônico:
 *
 * * **os 11 grupos aparecem sempre**, na ordem do schema. Grupo sem nenhum valor não
 *   desaparece: ele mostra quantos campos foram consultados em vão. Um grupo omitido
 *   faria a ficha parecer menor do que é;
 * * **nenhum valor sem etiqueta** (a `FieldRow` cuida disso);
 * * **onde o concorrente vence fica visível** — nesta tela isso aparece como o contador de
 *   divergências no topo, que leva direto aos campos em que as fontes discordam;
 * * **modo showroom** esconde tier, confiança e custo (`docs/12` §6.6) e sobe a
 *   tipografia. É um interruptor, não outra página: duas telas divergiriam.
 *
 * O que mudou na v2 (`020_BRIEF_PRODUTO.md` §02): **índice lateral dos 11 blocos**, para
 * uma ficha de 58 campos não exigir rolar às cegas; **quatro cartões de métrica** no topo
 * em vez de quatro números soltos; e a evidência numa **gaveta lateral**, que deixa a
 * ficha à vista enquanto a prova é lida.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'

import { Badge, FaixaDeSimulacao } from '@/components/Badge'
import { Card, CartaoDeMetrica } from '@/components/Card'
import { Contador } from '@/components/Contador'
import { FotoDoVeiculo } from '@/components/Foto'
import { CREDITO_DAS_FOTOS, fotoDe } from '@/lib/fotos'
import { Erro, Esqueleto } from '@/components/Estados'
import { FieldRow } from '@/components/FieldRow'
import { Marcacao } from '@/components/Campo'
import { api } from '@/lib/api'
import { mensagemDeErro } from '@/lib/erros'
import { rotularCampo } from '@/lib/formato'
import { GRUPOS } from '@/lib/tipos'
import type { Campo, Ficha as FichaDados, Grupo, ValidacaoEdital } from '@/lib/tipos'
import { nomeDoVeiculo } from '@/lib/veiculos'

const TITULO_DO_GRUPO: Record<Grupo, string> = {
  identificacao: 'Identificação',
  motorizacao: 'Motorização',
  transmissao: 'Transmissão',
  tracao: 'Tração',
  chassi: 'Chassi e suspensão',
  desempenho: 'Desempenho',
  modos: 'Modos de condução',
  exterior: 'Exterior, rodas e pneus',
  dimensoes: 'Dimensões e capacidades',
  seguranca: 'Segurança e ADAS',
  comercial: 'Comercial',
}

function contar(ficha: FichaDados) {
  let comValor = 0
  let divergentes = 0
  let simulados = 0
  let total = 0
  for (const grupo of GRUPOS) {
    for (const campo of Object.values(ficha[grupo] ?? {})) {
      total += 1
      if (campo.value !== null && campo.value !== undefined) comValor += 1
      if (campo.status === 'divergente') divergentes += 1
      if (campo.is_simulated) simulados += 1
    }
  }
  return { comValor, divergentes, simulados, total }
}

/**
 * O índice dos 11 blocos.
 *
 * Âncoras `<a href="#bloco">` e não rolagem por JavaScript: o link funciona com o teclado,
 * pode ser copiado, e o `scroll-behavior: smooth` da folha global cuida da suavidade. Cada
 * item traz a contagem do bloco, que é o que permite escolher onde olhar antes de rolar.
 */
function Indice({ ficha }: { ficha: FichaDados }) {
  return (
    <nav aria-label="blocos da ficha" className="sticky top-[calc(var(--barra-superior)+24px)]">
      <p className="mb-2 px-3 text-meta font-semibold uppercase tracking-[0.06em] text-tinta-3">
        Blocos
      </p>
      <ul className="space-y-0.5">
        {GRUPOS.map((grupo) => {
          const campos = Object.values(ficha[grupo] ?? {}) as Campo[]
          if (campos.length === 0) return null
          const comValor = campos.filter((c) => c.value !== null && c.value !== undefined).length
          return (
            <li key={grupo}>
              <a
                href={`#bloco-${grupo}`}
                className="flex items-center justify-between gap-2 rounded-controle px-3 py-1.5 text-rotulo text-tinta-2 transition-colors duration-150 ease-out hover:bg-superficie-2 hover:text-tinta"
              >
                <span className="min-w-0 truncate">{TITULO_DO_GRUPO[grupo]}</span>
                <span className="mono shrink-0 text-meta text-tinta-3">
                  {comValor}/{campos.length}
                </span>
              </a>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

const ROTULO_DO_VAZIO: Record<string, string> = {
  nao_disponivel: 'não oferecido nesta versão',
  nao_encontrado: 'nenhuma fonte consultada menciona',
  nao_verificado: 'extraído, mas sem trecho localizado',
}

/**
 * `nao_encontrado` justificado (procuramos e nenhuma das fontes consultadas cita) ganha
 * a contagem de fontes na própria frase — é a prova de que o sistema procurou, não que
 * desistiu. Os outros vazios usam o rótulo fixo de `ROTULO_DO_VAZIO`.
 */
function rotuloDoVazio(item: ValidacaoEdital['campos_vazios'][number]): string {
  if (item.status === 'nao_encontrado' && item.vazio_justificado) {
    const n = item.sources_checked.length
    return `nenhuma das ${n} fonte${n === 1 ? '' : 's'} oficiais consultadas menciona este recurso`
  }
  return ROTULO_DO_VAZIO[item.status] ?? item.status
}

/**
 * O que o edital pede para validar (`docs/01_REQUISITOS_EDITAL.md`, slide da Ranger
 * Raptor) em destaque, separado dos outros ~40 campos do schema completo — sem excluí-los,
 * só mostrando primeiro o que foi pedido.
 *
 * `respondidos` (não `com_valor`) é o que conta para "campo respondido": um recurso
 * exclusivo de performance que esta versão não tem também é resposta, desde que o motivo
 * venha com a prova de que procuramos (`vazio_justificado`) — é a decisão do dono de que
 * vazio justificado não é fracasso do pipeline.
 */
function ResumoDoEdital({ resumo }: { resumo: ValidacaoEdital }) {
  const [aberto, setAberto] = useState(false)

  const partes = [`${resumo.com_valor} com valor`]
  if (resumo.vazio_justificado > 0) {
    partes.push(
      `${resumo.vazio_justificado} recurso${resumo.vazio_justificado === 1 ? '' : 's'} que este veículo não oferece`,
    )
  }
  if (resumo.sem_resposta > 0) {
    partes.push(`${resumo.sem_resposta} sem resposta ainda`)
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-cartao text-tinta">
            Requisito do edital:{' '}
            <span className="mono" data-testid="edital-contagem">
              {resumo.respondidos}/{resumo.total}
            </span>{' '}
            respondidos — {partes.join(', ')}
          </p>
          <p className="mt-0.5 text-rotulo text-tinta-3">
            Lista fixa do slide de validação da Ranger Raptor. Os demais campos do schema
            continuam na ficha completa, abaixo.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAberto((v) => !v)}
          className="shrink-0 rounded-controle border border-borda px-3 py-1.5 text-rotulo text-tinta-2 transition-colors duration-150 ease-out hover:bg-superficie-2"
          data-testid="edital-alternar-lista"
        >
          {aberto ? 'esconder lista' : 'ver lista detalhada'}
        </button>
      </div>
      {aberto ? (
        <ul className="mt-3 grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-2" data-testid="edital-lista">
          {resumo.campos_achados.map((campo) => (
            <li key={campo} className="flex items-baseline gap-2 text-rotulo text-tinta">
              <span aria-hidden className="text-fato">
                ✓
              </span>
              {rotularCampo(campo)}
            </li>
          ))}
          {resumo.campos_vazios.map((item) => (
            <li key={item.campo} className="flex items-baseline gap-2 text-rotulo text-tinta-3">
              <span aria-hidden>—</span>
              <span>
                {rotularCampo(item.campo)}{' '}
                <span className="text-meta">({rotuloDoVazio(item)})</span>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  )
}

export function Ficha() {
  const { versionId = '' } = useParams()
  const [busca] = useSearchParams()
  const [showroom, setShowroom] = useState(false)
  const atributos = busca.get('attributes')?.split(',').filter(Boolean)

  const veiculo = useQuery({
    queryKey: ['veiculo', versionId],
    queryFn: () => api.veiculo(versionId),
    enabled: Boolean(versionId),
  })

  const ficha = useQuery({
    queryKey: ['ficha', versionId, atributos?.join(',') ?? ''],
    queryFn: () => api.ficha(versionId, atributos),
    enabled: Boolean(versionId),
  })

  const validacaoEdital = useQuery({
    queryKey: ['validacao-edital', versionId],
    queryFn: () => api.validacaoEdital(versionId),
    enabled: Boolean(versionId),
  })

  const resumo = useMemo(() => (ficha.data ? contar(ficha.data) : null), [ficha.data])

  if (ficha.isPending) {
    return (
      <div className="space-y-4" aria-busy="true">
        <span className="sr-only">carregando a ficha</span>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Esqueleto key={i} className="h-[104px]" />
          ))}
        </div>
        <Esqueleto className="h-[400px]" />
      </div>
    )
  }

  if (ficha.error) {
    return (
      <Card>
        <Erro titulo="Não foi possível abrir a ficha">
          {mensagemDeErro(ficha.error, 'abrir esta ficha')}
        </Erro>
      </Card>
    )
  }

  const dados = ficha.data as FichaDados
  const resolucao = dados.meta.version_resolution
  const titulo = veiculo.data ? nomeDoVeiculo(veiculo.data) : 'Ficha técnica'
  const foto = fotoDe(veiculo.data)

  return (
    <div className="space-y-6">
      {/* ------------------------------------------------------------------ o topo
          A foto fica ao lado do nome, e não na grade de métricas: ali ela virava um
          quinto cartão numa grade de quatro, e a "Situação da versão" caía sozinha numa
          segunda linha com três colunas vazias ao lado. Aqui ela faz o que foto faz —
          dizer de que picape se está falando — em 176 px, sem tirar espaço de número. */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-4">
          <FotoDoVeiculo src={foto} alt={titulo} credito={false} className="w-44 shrink-0" />
          <div className="min-w-0">
            <h2 className="text-cartao text-tinta">{titulo}</h2>
            {veiculo.data ? (
              <p className="mono mt-0.5 text-rotulo text-tinta-3">
                ano-modelo {veiculo.data.ano_modelo}
                {veiculo.data.codigo_fipe ? ` · FIPE ${veiculo.data.codigo_fipe}` : ''}
              </p>
            ) : null}
            {foto ? (
              <p className="mt-1.5 text-meta text-tinta-3">{CREDITO_DAS_FOTOS}</p>
            ) : null}
          </div>
        </div>
        <Marcacao
          rotulo="modo showroom"
          checked={showroom}
          onChange={(e) => setShowroom(e.target.checked)}
          data-testid="modo-showroom"
        />
      </div>

      {resumo && resumo.simulados > 0 ? (
        <FaixaDeSimulacao>({resumo.simulados} campo(s) desta ficha)</FaixaDeSimulacao>
      ) : null}

      {validacaoEdital.data ? <ResumoDoEdital resumo={validacaoEdital.data} /> : null}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <CartaoDeMetrica
          rotulo="Campos com valor"
          valor={<Contador valor={resumo?.comValor ?? 0} className="inline-block" />}
          apoio={`de ${resumo?.total ?? 0} campos da ficha padrão`}
          testId="resumo-com-valor"
        />
        <CartaoDeMetrica
          rotulo="Divergências"
          valor={<Contador valor={resumo?.divergentes ?? 0} className="inline-block" />}
          apoio="campos em que duas fontes discordam"
          testId="resumo-divergencias"
        />
        <CartaoDeMetrica
          rotulo="Fontes consultadas"
          valor={<Contador valor={dados.meta.sources_checked.length} className="inline-block" />}
          apoio="nesta coleta"
          testId="resumo-fontes"
        />
        <CartaoDeMetrica
          rotulo="Situação da versão"
          testId="resumo-situacao"
          palavra
          valor={resolucao.status === 'encontrada' ? 'na linha vigente' : resolucao.status}
          apoio={
            resolucao.status === 'encontrada'
              ? 'conferido na linha da montadora'
              : 'esta versão saiu de linha'
          }
        />
      </div>

      {atributos?.length ? (
        <p className="rounded-controle bg-superficie-2 px-4 py-3 text-rotulo text-tinta-2">
          Filtro aplicado: <strong className="text-tinta">{atributos.join(', ')}</strong>. Os
          outros campos continuam na ficha, sem valor e marcados como não consultados.
          Omiti-los faria você não saber se o dado não existe ou se ninguém perguntou.
        </p>
      ) : null}

      {/* -------------------------------------------------- índice lateral + blocos */}
      <div className="lg:grid lg:grid-cols-[220px_minmax(0,1fr)] lg:gap-8">
        <div className="hidden lg:block">
          <Indice ficha={dados} />
        </div>

        <div className="space-y-4">
          {GRUPOS.map((grupo) => {
            const campos = Object.entries(dados[grupo] ?? {}) as [string, Campo][]
            if (campos.length === 0) return null
            const comValor = campos.filter(
              ([, campo]) => campo.value !== null && campo.value !== undefined,
            ).length

            return (
              <section
                key={grupo}
                id={`bloco-${grupo}`}
                // O deslocamento é a altura da barra fixa: sem ele, a âncora para debaixo
                // do cabeçalho e o título do bloco fica escondido.
                className="scroll-mt-[calc(var(--barra-superior)+16px)] overflow-hidden rounded-cartao border border-borda bg-superficie shadow-cartao"
              >
                <header className="flex flex-wrap items-center justify-between gap-2 border-b border-borda bg-superficie-2 px-4 py-2.5">
                  <h3 className="text-rotulo font-semibold text-tinta">
                    {TITULO_DO_GRUPO[grupo]}
                  </h3>
                  <span className="mono text-meta text-tinta-2">
                    {comValor} de {campos.length} com valor
                  </span>
                </header>

                {comValor === 0 ? (
                  <p className="border-b border-borda px-4 py-3 text-rotulo text-tinta-2">
                    Nenhum campo deste grupo foi confirmado nas fontes consultadas. Os campos
                    seguem listados com o motivo de cada vazio.
                  </p>
                ) : null}

                <div>
                  {campos.map(([nome, campo]) => (
                    <FieldRow key={nome} campo={nome} dados={campo} showroom={showroom} />
                  ))}
                </div>
              </section>
            )
          })}

          <Card titulo="Procedência desta ficha">
            <dl className="space-y-2 text-corpo">
              <div className="flex flex-wrap gap-2">
                <dt className="font-medium text-tinta-2">Gerada em:</dt>
                <dd className="mono text-tinta">{dados.meta.generated_at}</dd>
              </div>
              <div className="flex flex-wrap gap-2">
                <dt className="font-medium text-tinta-2">Job:</dt>
                <dd translate="no" className="mono break-all text-meta text-tinta">
                  {dados.meta.job_id}
                </dd>
              </div>
              <div>
                <dt className="font-medium text-tinta-2">Fontes consultadas:</dt>
                <dd className="mt-1.5 flex flex-wrap gap-1.5">
                  {dados.meta.sources_checked.length > 0 ? (
                    dados.meta.sources_checked.map((fonte) => (
                      <span
                        key={fonte}
                        className="mono break-all rounded-controle bg-superficie-2 px-2 py-1 text-meta text-tinta-2"
                      >
                        {fonte}
                      </span>
                    ))
                  ) : (
                    <span className="text-meta text-tinta-3">nenhuma registrada</span>
                  )}
                </dd>
              </div>
            </dl>
            {/* A legenda mostra as QUATRO, e separa o que elas qualificam: três falam
                sobre um valor, a quarta sobre a ausência dele. Até 12/09/2026 faltavam
                duas aqui, e um campo vazio saía marcado INFERÊNCIA — como se houvesse
                leitura nossa onde não há leitura nenhuma. */}
            <div
              data-testid="legenda-das-etiquetas"
              className="mt-4 grid gap-y-2 border-t border-borda pt-4 text-meta text-tinta-2"
            >
              <p className="text-tinta-3">Sobre um valor:</p>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <Badge etiqueta="FATO" />
                valor com trecho verbatim localizado na fonte
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <Badge etiqueta="INFERENCIA" />
                leitura nossa, sem afirmação direta da fonte
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <Badge etiqueta="SIMULACAO" />
                hipótese ou dado de demonstração
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <Badge etiqueta="CATALOGO" />
                identidade da versão, vinda do nosso cadastro
              </div>
              <p className="mt-1 text-tinta-3">Sobre a ausência de valor:</p>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <Badge etiqueta="SEM_DADO" />
                campo sem valor — o motivo aparece ao lado do campo
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
