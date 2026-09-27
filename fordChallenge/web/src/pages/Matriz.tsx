/**
 * Matriz de paridade: onde ganhamos, empatamos, perdemos — e onde **ainda não sabemos**.
 *
 * As regras de produto que a tela carrega:
 *
 * * **`desconhecido` tem o mesmo peso visual dos outros três.** Rebaixá-lo a cinza pequeno
 *   faria a matriz parecer mais completa do que é (`030_ANTI_PADROES.md` §27);
 * * **o denominador honesto** aparece no cabeçalho de cada coluna: "comparados" exclui o
 *   que ninguém mediu, e é ele que dá sentido aos quatro contadores;
 * * **par não comparável é dito, não escondido.** O chip de comparabilidade fica ao lado do
 *   nome da coluna, e o critério a critério abre num clique;
 * * **a regra dos 1.000 kg não afirma o negativo** a partir de uma ausência: sem valor de
 *   carga, a tela diz que a regra não é avaliável, e não que o veículo não atinge.
 *
 * **A forma, na v2** (`020_BRIEF_PRODUTO.md` §04). A v1 punha 17 caixas de seleção soltas,
 * três cartões de texto repetido e a legenda em cima — e a tabela, que é o herói, começava
 * abaixo da dobra. Agora: filtros numa barra compacta (busca, chips por marca, três
 * concorrentes por padrão), legenda em linha, chips de comparabilidade curtos com expansão,
 * e a tabela ocupando a tela com a primeira coluna fixa e célula de 32 px.
 */
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { Badge } from '@/components/Badge'
import { Card, TituloDeSecao } from '@/components/Card'
import { Busca, Selecao } from '@/components/Campo'
import { Erro, Esqueleto, Vazio, useEsqueleto } from '@/components/Estados'
import { Chip } from '@/components/Chip'
import { Table as IconeDeTabela } from '@/components/Icones'
import { CelulaDeParidadeNaTabela, LegendaDeParidade } from '@/components/Paridade'
import {
  Cabecalho,
  Celula as CelulaDaTabela,
  CelulaDeRotulo,
  Coluna,
  Corpo,
  Linha,
  Tabela,
} from '@/components/Tabela'
import { api } from '@/lib/api'
import { mensagemDeErro } from '@/lib/erros'
import { formatarValor, rotularCampo } from '@/lib/formato'
import {
  PADRAO_DA_MATRIZ,
  PADRAO_FORD,
  escolherPadrao,
  escolherPadroes,
  nomeCurto,
  nomeDoVeiculo,
} from '@/lib/veiculos'
import type { ColunaDeParidade, Veiculo } from '@/lib/tipos'

const ROTULO_DO_GRUPO: Record<string, string> = {
  identificacao: 'identificação',
  motorizacao: 'motorização',
  transmissao: 'transmissão',
  tracao: 'tração',
  chassi: 'chassi',
  desempenho: 'desempenho',
  modos: 'modos',
  exterior: 'exterior',
  dimensoes: 'dimensões',
  seguranca: 'segurança',
  comercial: 'comercial',
}

/**
 * O chip de comparabilidade: **"3/4 critérios"** em mono, verde quando o par é comparável e
 * âmbar quando não. O resumo por extenso, o aviso e o critério a critério ficam dentro do
 * `<details>`, a um clique.
 *
 * A v1 imprimia o aviso inteiro, repetido por concorrente, num cartão acima da tabela: três
 * parágrafos quase idênticos que empurravam o dado para baixo e que ninguém lia. O chip
 * curto diz a mesma coisa em quatro caracteres, e quem precisa do porquê abre.
 */
function ChipDeComparabilidade({ coluna }: { coluna: ColunaDeParidade }) {
  const c = coluna.comparabilidade
  return (
    <details
      data-testid={`comparabilidade-${coluna.version_id}`}
      // `role="alert"` só no par NÃO comparável: é o caso em que a tela é obrigada a
      // avisar antes que alguém use a coluna como se fosse comparação válida.
      role={c.comparavel ? undefined : 'alert'}
      className="group font-normal normal-case tracking-normal"
    >
      <summary className="flex cursor-pointer list-none flex-col items-start gap-1">
        <span
          className={[
            'mono inline-flex h-[22px] items-center rounded-full px-2 text-meta',
            c.comparavel
              ? 'bg-ganhamos-fundo text-ganhamos'
              : 'bg-naoSabemos-fundo text-naoSabemos',
          ].join(' ')}
        >
          {c.criterios_atendidos}/{c.criterios_avaliaveis} critérios
        </span>
        <span className="text-meta text-marca-700 group-hover:underline">
          {c.comparavel ? 'ver critério por critério' : 'par não comparável: ver critérios'}
        </span>
      </summary>
      <div className="mt-2 w-[220px] rounded-controle bg-superficie-2 p-3 text-meta text-tinta-2">
        <p className="mb-2 font-medium text-tinta">{c.resumo}</p>
        {c.aviso ? <p className="mb-2 text-tinta">{c.aviso}</p> : null}
        {c.sem_dados.length > 0 && c.comparavel ? (
          <p className="mb-2">
            Sem dados para: {c.sem_dados.join(', ')}. Não contam no denominador.
          </p>
        ) : null}
        <ul className="space-y-1">
          {c.detalhes.map((d) => (
            <li key={d.id} className="flex flex-wrap items-baseline gap-1.5">
              <span className="font-medium text-tinta">{d.rotulo}:</span>
              <span
                className={
                  d.estado === 'atendido'
                    ? 'text-ganhamos'
                    : d.estado === 'nao_atendido'
                      ? 'text-perdemos'
                      : 'text-tinta-2'
                }
              >
                {d.estado === 'atendido'
                  ? 'atendido'
                  : d.estado === 'nao_atendido'
                    ? 'não atendido'
                    : 'sem dados'}
              </span>
              {d.motivo ? <span className="text-tinta-3">{d.motivo}</span> : null}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-tinta-3">critérios de {c.versao_dos_criterios}</p>
      </div>
    </details>
  )
}

function FaixaDeCarga({
  flag,
  rotulo,
}: {
  flag: ColunaDeParidade['flag_de_carga']
  rotulo: string
}) {
  // Flag não avaliável não vira "não atinge 1.000 kg": aparece com o motivo. Afirmar o
  // negativo a partir de uma ausência é o erro que o produto não comete.
  if (!flag.aplicavel) {
    return (
      <li data-testid="carga-indeterminada" className="text-rotulo text-tinta-2">
        <span className="font-medium text-tinta">{rotulo}:</span> regra dos 1.000 kg não
        avaliável. {flag.motivo}
      </li>
    )
  }
  if (!flag.valor) return null
  return (
    <li data-testid="flag-1000kg" className="flex flex-wrap items-start gap-2 text-rotulo">
      <Badge etiqueta="INFERENCIA" />
      <span className="min-w-0 flex-1 text-tinta">
        <span className="font-medium">{rotulo}:</span> {flag.texto}
      </span>
    </li>
  )
}

export function Matriz() {
  const [fordVersion, setFordVersion] = useState('')
  const [concorrentes, setConcorrentes] = useState<string[]>([])
  const [grupo, setGrupo] = useState('')
  const [busca, setBusca] = useState('')
  const [marca, setMarca] = useState('')

  const veiculos = useQuery({ queryKey: ['veiculos'], queryFn: () => api.veiculos() })
  const lista = veiculos.data ?? []
  const fords = lista.filter((v) => v.marca.toLowerCase() === 'ford')
  const outros = lista.filter((v) => v.marca.toLowerCase() !== 'ford')

  // Os padroes vem de `lib/veiculos`, e nao de `lista[0]`: a primeira em ordem
  // alfabetica e uma versao SEM ficha, e a tabela abria vazia (ver o modulo).
  const referencia = fordVersion || escolherPadrao(fords, PADRAO_FORD)
  const escolhidos =
    concorrentes.length > 0 ? concorrentes : escolherPadroes(outros, PADRAO_DA_MATRIZ, 3)

  const paridade = useQuery({
    queryKey: ['paridade', referencia, escolhidos.join(','), grupo],
    queryFn: () => api.paridade(referencia, escolhidos, grupo ? [grupo] : undefined),
    enabled: Boolean(referencia) && escolhidos.length > 0,
  })
  const carregando = useEsqueleto(paridade.isPending && Boolean(referencia))

  const marcas = useMemo(
    () => [...new Set(outros.map((v) => v.marca))].sort((a, b) => a.localeCompare(b, 'pt-BR')),
    [outros],
  )

  const candidatos = useMemo(() => {
    const alvo = busca.trim().toLowerCase()
    return outros.filter((v: Veiculo) => {
      if (marca && v.marca !== marca) return false
      if (!alvo) return true
      return nomeDoVeiculo(v).toLowerCase().includes(alvo)
    })
  }, [outros, marca, busca])

  function alternar(id: string) {
    setConcorrentes((atuais) => {
      const base = atuais.length > 0 ? atuais : escolhidos
      return base.includes(id) ? base.filter((x) => x !== id) : [...base, id]
    })
  }

  const dados = paridade.data
  const campos = dados?.colunas[0]?.celulas.map((c) => c.campo) ?? []

  return (
    <div className="space-y-6">
      {/* --------------------------------------------------------------- os filtros
          Barra compacta, não cartão gordo: o dado é o herói, o filtro é coadjuvante. */}
      <div className="space-y-3 rounded-cartao border border-borda bg-superficie p-4 shadow-cartao">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,240px)]">
          <Selecao
            rotulo="Versão Ford de referência"
            aria-label="versão Ford de referência"
            value={referencia}
            onChange={(e) => setFordVersion(e.target.value)}
          >
            {fords.map((v) => (
              <option key={v.id} value={v.id}>
                {nomeCurto(v)}
              </option>
            ))}
          </Selecao>

          <div>
            <p className="mb-1.5 text-rotulo font-medium text-tinta-2">
              Concorrentes ({escolhidos.length} de {outros.length})
            </p>
            <Busca
              rotulo="buscar concorrente"
              placeholder="buscar por nome…"
              autoComplete="off"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
          </div>

          <Selecao
            rotulo="Dimensão"
            aria-label="filtrar por dimensão"
            value={grupo}
            onChange={(e) => setGrupo(e.target.value)}
          >
            <option value="">todas as dimensões</option>
            {Object.entries(ROTULO_DO_GRUPO).map(([valor, rotulo]) => (
              <option key={valor} value={valor}>
                {rotulo}
              </option>
            ))}
          </Selecao>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <Chip selecionado={marca === ''} onAlternar={() => setMarca('')}>
            todas as marcas
          </Chip>
          {marcas.map((nome) => (
            <Chip key={nome} selecionado={marca === nome} onAlternar={() => setMarca(nome)}>
              {nome}
            </Chip>
          ))}
        </div>

        <fieldset className="flex flex-wrap gap-1.5">
          <legend className="sr-only">escolher concorrentes</legend>
          {candidatos.map((v) => (
            <Chip
              key={v.id}
              selecionado={escolhidos.includes(v.id)}
              onAlternar={() => alternar(v.id)}
            >
              {nomeDoVeiculo(v)}
            </Chip>
          ))}
          {candidatos.length === 0 ? (
            <p className="text-rotulo text-tinta-3">Nenhum concorrente com esse nome.</p>
          ) : null}
        </fieldset>
      </div>

      {paridade.error ? (
        <Card>
          <Erro>{mensagemDeErro(paridade.error, 'montar a matriz')}</Erro>
        </Card>
      ) : null}

      {carregando ? <Esqueleto className="h-[420px]" /> : null}

      {dados ? (
        <>
          <LegendaDeParidade legenda={dados.legenda} />

          <section className="space-y-3">
            <TituloDeSecao
              descricao={`${dados.colunas[0]?.contagem.comparados ?? 0} de ${
                dados.colunas[0]?.contagem.total ?? 0
              } campos com os dois lados conhecidos. O resto entra como "não sabemos".`}
            >
              {dados.ford_rotulo} contra {dados.colunas.length} concorrente(s)
            </TituloDeSecao>

            <div className="overflow-hidden rounded-cartao border border-borda bg-superficie shadow-cartao">
              <Tabela rotulo="Matriz de paridade por campo, com quatro estados: ganhamos, empate, perdemos e não sabemos.">
                <Cabecalho>
                  <Coluna fixa>Campo</Coluna>
                  {/* `max-w`: sem isso o nome inteiro da versão Ford, que tem 30
                      caracteres, empurra as colunas dos concorrentes para fora da tela. */}
                  <Coluna numerica className="max-w-[160px] normal-case">
                    {dados.ford_rotulo}
                  </Coluna>
                  {dados.colunas.map((coluna) => (
                    <Coluna key={coluna.version_id} className="w-[220px]">
                      <span className="flex flex-col gap-1 py-1">
                        <span className="normal-case">{coluna.rotulo}</span>
                        <span className="mono font-normal normal-case tracking-normal text-tinta-3">
                          ▲{coluna.contagem.vantagem} ={coluna.contagem.paridade} ▼
                          {coluna.contagem.gap} ?{coluna.contagem.desconhecido}
                        </span>
                        <ChipDeComparabilidade coluna={coluna} />
                      </span>
                    </Coluna>
                  ))}
                </Cabecalho>
                <Corpo>
                  {campos.map((campo, indice) => {
                    const primeira = dados.colunas[0]?.celulas[indice]
                    return (
                      <Linha key={campo} testId={`linha-${campo}`}>
                        <CelulaDeRotulo fixa>
                          <span className="block">{rotularCampo(campo)}</span>
                          <span className="block text-meta font-normal text-tinta-3">
                            {ROTULO_DO_GRUPO[primeira?.grupo ?? ''] ?? primeira?.grupo}
                          </span>
                        </CelulaDeRotulo>
                        <CelulaDaTabela numerica className="max-w-[160px]">
                          <span
                            title={formatarValor(primeira?.valor_ford, primeira?.unidade, campo)}
                            className="block truncate"
                          >
                            {formatarValor(primeira?.valor_ford, primeira?.unidade, campo)}
                          </span>
                        </CelulaDaTabela>
                        {dados.colunas.map((coluna) => {
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

              {campos.length === 0 ? (
                <Vazio icone={IconeDeTabela} titulo="Nenhum campo nesta dimensão">
                  Escolha outra dimensão, ou tire o filtro para ver os 58 campos.
                </Vazio>
              ) : null}
            </div>
          </section>

          <Card
            titulo="Regra dos 1.000 kg"
            descricao="Picape com carga útil de 1.000 kg ou mais tem isenção de IPI para produtor rural. É inferência a partir do valor de carga, e a etiqueta diz isso."
          >
            <ul className="space-y-2">
              <FaixaDeCarga flag={dados.flag_de_carga_ford} rotulo={dados.ford_rotulo} />
              {dados.colunas.map((coluna) => (
                <FaixaDeCarga
                  key={coluna.version_id}
                  flag={coluna.flag_de_carga}
                  rotulo={coluna.rotulo}
                />
              ))}
            </ul>
          </Card>
        </>
      ) : null}
    </div>
  )
}
