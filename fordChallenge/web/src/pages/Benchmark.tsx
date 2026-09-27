/**
 * Benchmark: de uma versão Ford ao conjunto de concorrentes que vale comparar.
 *
 * A tela **propõe**; quem decide quem entra é quem vende. Essa separação é o desenho
 * inteiro, e ela aparece em quatro lugares:
 *
 * * **a lista vem com a origem à vista.** Uma lista escrita à mão, com data, e uma versão
 *   que veio do nosso cadastro não têm o mesmo peso — e o que ainda não existe aparece
 *   como o que é: uma busca a fazer, com o motivo escrito;
 * * **comparabilidade é `k/n`, nunca porcentagem.** "4 de 6 critérios" se discute critério
 *   a critério; "67% comparável" é um número que ninguém sabe contestar;
 * * **o par que a régua reprova continua na tela, selecionável.** Esconder o concorrente
 *   difícil de quem sabe o que está fazendo é decidir pela pessoa;
 * * **"não sabemos" tem o mesmo tamanho de "ganhamos".** Rebaixá-lo a cinza pequeno faria
 *   a comparação parecer mais completa do que é.
 *
 * Sem a capacidade ligada no servidor a rota devolve 404. Isso **não** é falha: a tela diz
 * que o recurso não está ligado neste ambiente e segue inteira, com título e explicação.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { Badge } from '@/components/Badge'
import { Botao } from '@/components/Botao'
import { Card, CartaoDeMetrica, TituloDeSecao } from '@/components/Card'
import { Marcacao, Selecao } from '@/components/Campo'
import { Chip } from '@/components/Chip'
import { Erro, Esqueleto, useEsqueleto } from '@/components/Estados'
import {
  APARENCIA,
  CelulaDeParidadeNaTabela,
  LegendaDeParidade,
  ORDEM_DOS_ESTADOS,
} from '@/components/Paridade'
import {
  Cabecalho,
  Celula as CelulaDaTabela,
  CelulaDeRotulo,
  Coluna,
  Corpo,
  Linha,
  Tabela,
} from '@/components/Tabela'
import { ErroDaApi, api } from '@/lib/api'
import { mensagemDeErro } from '@/lib/erros'
import { formatarValor, rotularCampo } from '@/lib/formato'
import { useBenchmarkLigado } from '@/lib/pesquisa'
import { PADRAO_FORD, escolherPadrao, nomeCurto } from '@/lib/veiculos'
import { PainelDoPesquisador } from '@/pages/Pesquisador'
import type { CandidatoDoBenchmark, EstadoDeParidade } from '@/lib/tipos'

/** Identificador estável do candidato, com ou sem versão no cadastro. */
function chaveDo(candidato: CandidatoDoBenchmark): string {
  return `${candidato.marca} ${candidato.modelo}`
    .toLowerCase()
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
}

/**
 * Já entra marcado quem tem versão do mesmo ano no cadastro **e** passa nos critérios.
 *
 * O resto entra desmarcado e continua clicável: a diferença entre "não recomendo" e
 * "não deixo" é a diferença entre uma ferramenta e uma coleira.
 */
function marcadoPorPadrao(candidato: CandidatoDoBenchmark): boolean {
  return Boolean(candidato.no_catalogo && candidato.comparabilidade?.comparavel)
}

/** `2026-09-13` como se lê em português. Sem `Date`: fuso não muda data de lista. */
function dataDaLista(iso: string): string {
  const partes = (iso || '').split('-')
  if (partes.length !== 3) return iso
  return `${partes[2]}/${partes[1]}/${partes[0]}`
}

/** O `k/n` em chip: verde quando o par se sustenta, âmbar quando pede ressalva. */
function ChipDeCriterios({ resumo, comparavel }: { resumo: string; comparavel: boolean }) {
  return (
    <span
      className={[
        'mono inline-flex h-[22px] items-center rounded-full px-2 text-meta',
        comparavel ? 'bg-ganhamos-fundo text-ganhamos' : 'bg-naoSabemos-fundo text-naoSabemos',
      ].join(' ')}
    >
      {resumo}
    </span>
  )
}

export function Benchmark() {
  const [fordVersion, setFordVersion] = useState('')
  const [escolhas, setEscolhas] = useState<Record<string, boolean>>({})
  const [confirmados, setConfirmados] = useState<string[]>([])
  const [pesquisando, setPesquisando] = useState<{ marca: string; modelo: string } | null>(null)

  const veiculos = useQuery({ queryKey: ['veiculos'], queryFn: () => api.veiculos() })
  const fords = (veiculos.data ?? []).filter((v) => v.marca.toLowerCase() === 'ford')
  const referencia = fordVersion || escolherPadrao(fords, PADRAO_FORD)

  // **A bandeira é lida antes de chamar, e não depois de levar 404.** A tela já tratava
  // o 404 com elegância — mas o navegador registra um erro de console a cada visita, e
  // erro de console é indistinguível de defeito para quem está olhando. O `qa/e2e`
  // reprovou por isso em 13/09, e estava certo.
  const ligado = useBenchmarkLigado()
  const proposta = useQuery({
    queryKey: ['benchmark', referencia],
    queryFn: () => api.propostaDeBenchmark(referencia),
    enabled: Boolean(referencia) && ligado,
  })

  const paridade = useQuery({
    queryKey: ['benchmark-paridade', referencia, confirmados.join(',')],
    queryFn: () => api.paridade(referencia, confirmados),
    enabled: Boolean(referencia) && confirmados.length > 0 && ligado,
  })

  const dados = proposta.data
  const candidatos = dados?.candidatos ?? []
  const semSegmento = dados?.segmento.origem === 'desconhecido'
  // 404 aqui quer dizer bandeira desligada no servidor, e é o único caso em que a tela
  // explica em vez de acusar: não é falha, é recurso que este ambiente não subiu.
  // O 404 continua sendo tratado: é a segunda linha de defesa, para o caso de a bandeira
  // mudar no servidor depois de a tela ter subido.
  const desligado =
    !ligado || (proposta.error instanceof ErroDaApi && proposta.error.status === 404)
  const carregando = useEsqueleto(proposta.isPending && Boolean(referencia))

  function estaMarcado(candidato: CandidatoDoBenchmark): boolean {
    return escolhas[chaveDo(candidato)] ?? marcadoPorPadrao(candidato)
  }

  const marcados = candidatos.filter(estaMarcado)
  const paraComparar = marcados
    .filter((c) => c.no_catalogo && c.version_id)
    .map((c) => c.version_id as string)
  const marcadosSemCopia = marcados.filter((c) => !c.no_catalogo)

  const totais = useMemo(() => {
    const soma = { vantagem: 0, paridade: 0, gap: 0, desconhecido: 0, total: 0, comparados: 0 }
    for (const coluna of paridade.data?.colunas ?? []) {
      soma.vantagem += coluna.contagem.vantagem
      soma.paridade += coluna.contagem.paridade
      soma.gap += coluna.contagem.gap
      soma.desconhecido += coluna.contagem.desconhecido
      soma.total += coluna.contagem.total
      soma.comparados += coluna.contagem.comparados
    }
    return soma
  }, [paridade.data])

  const matriz = paridade.data
  const campos = matriz?.colunas[0]?.celulas.map((c) => c.campo) ?? []
  const comRessalva = (matriz?.colunas ?? []).filter((c) => !c.comparabilidade.comparavel)

  return (
    <div className="space-y-6">
      {/* ------------------------------------------------------- a versão que abre tudo */}
      <div className="rounded-cartao border border-borda bg-superficie p-4 shadow-cartao">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <Selecao
            rotulo="Versão Ford"
            aria-label="versão Ford de referência"
            apoio="A comparação parte daqui: é a nossa versão contra o mercado dela."
            value={referencia}
            onChange={(e) => {
              setFordVersion(e.target.value)
              setEscolhas({})
              setConfirmados([])
            }}
          >
            {fords.map((v) => (
              <option key={v.id} value={v.id}>
                {nomeCurto(v)}
              </option>
            ))}
          </Selecao>

          {dados && !semSegmento ? (
            <div className="min-w-0">
              <p className="text-rotulo font-medium text-tinta-2">Segmento</p>
              <p className="mt-1.5 text-corpo text-tinta">{dados.segmento.rotulo}</p>
              <p className="mt-1 text-meta text-tinta-3">{dados.segmento.descricao}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Badge etiqueta="CATALOGO" />
                <span className="text-meta text-tinta-3">
                  lista de concorrentes revisada em {dataDaLista(dados.versao_do_mapa)}
                </span>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {desligado ? (
        <Card titulo="Benchmark">
          <p data-testid="benchmark-desligado" className="text-corpo text-tinta-2">
            O Benchmark não está ligado neste ambiente. Não é falha: a proposta de
            concorrentes aparece aqui assim que ele estiver ligado.
          </p>
        </Card>
      ) : null}

      {proposta.error && !desligado ? (
        <Card>
          <Erro>{mensagemDeErro(proposta.error, 'montar a lista de concorrentes')}</Erro>
        </Card>
      ) : null}

      {carregando ? <Esqueleto className="h-[260px]" /> : null}

      {/* O painel ao vivo fica no topo: é o que está acontecendo agora. */}
      {pesquisando ? (
        <PainelDoPesquisador
          marca={pesquisando.marca}
          modelo={pesquisando.modelo}
          versao=""
          aoFechar={() => setPesquisando(null)}
        />
      ) : null}

      {/* ------------------------------------ sem lista escrita, não se inventa a lista */}
      {dados && semSegmento ? (
        <Card
          titulo="Ainda não sabemos contra quem esta Ford briga"
          descricao="Nenhum concorrente entra por palpite nosso."
        >
          <div data-testid="segmento-desconhecido" className="space-y-4">
            <p className="text-corpo text-tinta-2">{dados.aviso}</p>
            <div>
              <p className="text-rotulo font-medium text-tinta-2">A busca a fazer</p>
              <p
                data-testid="consulta-de-descoberta"
                className="mono mt-1 break-words text-corpo text-tinta"
              >
                {dados.consulta_de_descoberta}
              </p>
            </div>
            <Botao
              tom="primario"
              onClick={() => setPesquisando({ marca: dados.ford.marca, modelo: dados.ford.modelo })}
            >
              pesquisar em fontes de imprensa
            </Botao>
            <p className="text-meta text-tinta-3">
              O resultado vem com as fontes de cada nome, para você confirmar antes de virar
              comparação.
            </p>
          </div>
        </Card>
      ) : null}

      {/* -------------------------------------------------------- o conjunto proposto */}
      {dados && !semSegmento ? (
        <Card
          titulo={`Contra quem a ${dados.ford.modelo} briga`}
          descricao={`${dados.prontos} de ${candidatos.length} concorrentes já têm ficha do ano-modelo ${dados.ford.ano_modelo}. Marque quem entra na comparação.`}
          acao={
            <Botao
              tom="primario"
              data-testid="comparar"
              disabled={paraComparar.length === 0}
              onClick={() => setConfirmados(paraComparar)}
            >
              comparar ({paraComparar.length})
            </Botao>
          }
        >
          <div className="space-y-4">
            {dados.aviso ? (
              <p className="text-corpo text-tinta-2">{dados.aviso}</p>
            ) : null}

            <ul data-testid="conjunto-proposto" className="space-y-2">
              {candidatos.map((candidato) => {
                const chave = chaveDo(candidato)
                const comparabilidade = candidato.comparabilidade
                return (
                  <li
                    key={chave}
                    data-testid={`candidato-${chave}`}
                    className="rounded-cartao border border-borda bg-superficie-2 p-3"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <Marcacao
                        rotulo={
                          <span className="font-medium text-tinta">
                            {candidato.rotulo_do_modelo}
                          </span>
                        }
                        aria-label={`incluir ${candidato.rotulo_do_modelo} na comparação`}
                        checked={estaMarcado(candidato)}
                        onChange={() =>
                          setEscolhas((atuais) => ({
                            ...atuais,
                            [chave]: !estaMarcado(candidato),
                          }))
                        }
                      />
                      {candidato.no_catalogo ? <Badge etiqueta="CATALOGO" /> : null}
                    </div>

                    {candidato.no_catalogo && comparabilidade ? (
                      <div className="mt-1.5 space-y-1.5">
                        <p className="text-corpo text-tinta">
                          {candidato.rotulo} · ano-modelo {candidato.ano_modelo}
                        </p>
                        <div className="flex flex-wrap items-center gap-2">
                          <ChipDeCriterios
                            resumo={comparabilidade.resumo}
                            comparavel={comparabilidade.comparavel}
                          />
                          {comparabilidade.comparavel ? null : (
                            <span className="text-meta font-medium text-naoSabemos">
                              comparação com ressalva
                            </span>
                          )}
                        </div>
                        {comparabilidade.aviso ? (
                          <p role="alert" className="text-meta text-tinta-2">
                            {comparabilidade.aviso}
                          </p>
                        ) : null}
                      </div>
                    ) : null}

                    {candidato.precisa_pesquisa ? (
                      <div className="mt-1.5 space-y-2">
                        <p className="text-meta text-tinta-2">
                          Sem comparação por enquanto: {candidato.motivo_da_pesquisa}.
                        </p>
                        <Botao
                          onClick={() =>
                            setPesquisando({
                              marca: candidato.marca,
                              modelo: candidato.modelo,
                            })
                          }
                        >
                          pesquisar {candidato.rotulo_do_modelo}
                        </Botao>
                      </div>
                    ) : null}

                    {candidato.categoria_diferente ? (
                      <div className="mt-1.5 space-y-1">
                        <Chip>outra categoria</Chip>
                        <p className="text-meta text-tinta-2">{candidato.motivo_da_categoria}</p>
                      </div>
                    ) : null}
                  </li>
                )
              })}
            </ul>

            {marcadosSemCopia.length > 0 ? (
              <p className="text-meta text-tinta-2">
                {marcadosSemCopia.length} concorrente(s) marcado(s) ainda não têm ficha deste
                ano-modelo e ficam de fora desta comparação até serem pesquisados.
              </p>
            ) : null}
          </div>
        </Card>
      ) : null}

      {paridade.error ? (
        <Card>
          <Erro>{mensagemDeErro(paridade.error, 'montar a comparação')}</Erro>
        </Card>
      ) : null}

      {/* ------------------------------------------------------------- a comparação */}
      {matriz ? (
        <section className="space-y-4">
          <TituloDeSecao
            descricao={`${totais.comparados} de ${totais.total} campos com os dois lados conhecidos, somando ${matriz.colunas.length} concorrente(s). O resto entra como "não sabemos".`}
          >
            {matriz.ford_rotulo} contra {matriz.colunas.length} concorrente(s)
          </TituloDeSecao>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {ORDEM_DOS_ESTADOS.map((estado: EstadoDeParidade) => (
              <CartaoDeMetrica
                key={estado}
                testId={`resumo-${estado}`}
                rotulo={APARENCIA[estado].rotulo}
                valor={totais[estado]}
                apoio={`de ${totais.total} campos somados nas colunas`}
                etiqueta={<Badge etiqueta="INFERENCIA" />}
              />
            ))}
          </div>

          <LegendaDeParidade legenda={matriz.legenda} />

          <div
            data-testid="matriz-do-benchmark"
            className="overflow-hidden rounded-cartao border border-borda bg-superficie shadow-cartao"
          >
            <Tabela rotulo="Comparação campo a campo, com quatro estados: ganhamos, empate, perdemos e não sabemos.">
              <Cabecalho>
                <Coluna fixa>Campo</Coluna>
                <Coluna numerica className="max-w-[160px] normal-case">
                  {matriz.ford_rotulo}
                </Coluna>
                {matriz.colunas.map((coluna) => (
                  <Coluna key={coluna.version_id} className="w-[220px]">
                    <span className="flex flex-col gap-1 py-1">
                      <span className="normal-case">{coluna.rotulo}</span>
                      <span className="mono font-normal normal-case tracking-normal text-tinta-3">
                        ▲{coluna.contagem.vantagem} ={coluna.contagem.paridade} ▼
                        {coluna.contagem.gap} ?{coluna.contagem.desconhecido}
                      </span>
                      <ChipDeCriterios
                        resumo={coluna.comparabilidade.resumo}
                        comparavel={coluna.comparabilidade.comparavel}
                      />
                    </span>
                  </Coluna>
                ))}
              </Cabecalho>
              <Corpo>
                {campos.map((campo, indice) => {
                  const primeira = matriz.colunas[0]?.celulas[indice]
                  return (
                    <Linha key={campo} testId={`linha-${campo}`}>
                      <CelulaDeRotulo fixa>{rotularCampo(campo)}</CelulaDeRotulo>
                      <CelulaDaTabela numerica className="max-w-[160px]">
                        <span
                          title={formatarValor(primeira?.valor_ford, primeira?.unidade, campo)}
                          className="block truncate"
                        >
                          {formatarValor(primeira?.valor_ford, primeira?.unidade, campo)}
                        </span>
                      </CelulaDaTabela>
                      {matriz.colunas.map((coluna) => {
                        const celula = coluna.celulas[indice]
                        return celula ? (
                          <CelulaDeParidadeNaTabela key={coluna.version_id} celula={celula} />
                        ) : (
                          <CelulaDaTabela key={coluna.version_id}>
                            <span className="sr-only">sem célula</span>
                          </CelulaDaTabela>
                        )
                      })}
                    </Linha>
                  )
                })}
              </Corpo>
            </Tabela>
          </div>

          {comRessalva.length > 0 ? (
            <Card
              titulo="Onde a comparação pede ressalva"
              descricao="Estes pares não atendem a todos os critérios. Eles continuam na tabela, e o porquê fica aqui."
            >
              <ul data-testid="avisos-de-comparabilidade" className="space-y-3">
                {comRessalva.map((coluna) => (
                  <li key={coluna.version_id} role="alert" className="space-y-1">
                    <p className="text-corpo font-medium text-tinta">{coluna.rotulo}</p>
                    <ChipDeCriterios
                      resumo={coluna.comparabilidade.resumo}
                      comparavel={false}
                    />
                    {coluna.comparabilidade.aviso ? (
                      <p className="text-meta text-tinta-2">{coluna.comparabilidade.aviso}</p>
                    ) : null}
                    {coluna.comparabilidade.nao_atendidos.length > 0 ? (
                      <p className="text-meta text-tinta-3">
                        Critérios que faltam: {coluna.comparabilidade.nao_atendidos.join(', ')}.
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </section>
      ) : null}
    </div>
  )
}
