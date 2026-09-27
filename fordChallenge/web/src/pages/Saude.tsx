/**
 * Saúde do Conhecimento: **quão confiável está a informação usada para decidir**.
 *
 * A tela tem uma regra que a torna diferente de um dashboard qualquer: **nenhum número
 * aparece sozinho**. Cada indicador vem com o denominador, cada contagem abre a lista dos
 * campos com o motivo de cada um, e o status traz o nome da regra que o decidiu — clicável,
 * com todas as regras à vista. Um painel que diz "saúde: 72%" faz o usuário confiar num
 * número que ninguém consegue auditar; este diz "12 de 30 campos coletados há mais de 30
 * dias, e são estes".
 *
 * O texto fixo de `docs/13` §3 ("indicador operacional do MVP, não probabilidade de
 * verdade") aparece em **todo** cartão, e a etiqueta é INFERÊNCIA: os campos são fatos com
 * evidência, mas a leitura "esta ficha está boa para decidir" é inferência por regra.
 *
 * **A forma, na v2** (`020_BRIEF_PRODUTO.md` §06). A v1 dava um cartão enorme por versão,
 * com o mesmo parágrafo repetido cinco vezes e cinco métricas empilhadas em linhas iguais:
 * nada era escaneável, e comparar duas versões exigia rolar. Agora é uma **grade**: uma
 * linha por versão, as cinco métricas como células em mono, e a régua (regras, explicação,
 * texto fixo) abrindo na própria linha. Cobertura vira barra horizontal com o denominador
 * por escrito, e divergência vira tabela com os dois valores lado a lado.
 */
import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'

import { Badge } from '@/components/Badge'
import { BarraDeCobertura } from '@/components/Barras'
import { Card, TituloDeSecao } from '@/components/Card'
import { Selecao } from '@/components/Campo'
import { Erro, EsqueletoDeLista, Recusa, Vazio, useEsqueleto } from '@/components/Estados'
import { CaretDown, CaretRight, Gauge } from '@/components/Icones'
import {
  Cabecalho,
  Celula,
  CelulaDeRotulo,
  Coluna,
  Corpo,
  Linha,
  Tabela,
} from '@/components/Tabela'
import { api } from '@/lib/api'
import { mensagemDeErro } from '@/lib/erros'
import { usePapel } from '@/lib/papel'
import { ACAO_DA_TELA, papeisQuePodem, pode } from '@/lib/permissoes'
import { formatarValor, rotularCampo } from '@/lib/formato'
import type { Divergencia, Indicador, Saude as SaudeDaVersao, StatusDeSaude } from '@/lib/tipos'

const APARENCIA: Record<string, { classe: string; ponto: string; simbolo: string }> = {
  OK: { classe: 'bg-ganhamos-fundo text-ganhamos', ponto: 'bg-ganhamos', simbolo: '✓' },
  REVISAR: { classe: 'bg-naoSabemos-fundo text-naoSabemos', ponto: 'bg-naoSabemos', simbolo: '!' },
  INSUFICIENTE: { classe: 'bg-perdemos-fundo text-perdemos', ponto: 'bg-perdemos', simbolo: '×' },
}

/** As cinco métricas da grade, na ordem em que aparecem. O rótulo curto vai no cabeçalho. */
const METRICAS = [
  { chave: 'verificados', curto: 'verificados', longo: 'campos com valor verificado' },
  { chave: 'desatualizados', curto: 'desatualizados', longo: 'campos desatualizados' },
  { chave: 'conflitos', curto: 'conflitos', longo: 'conflitos entre fontes' },
  { chave: 'nao_confirmados', curto: 'não confirmados', longo: 'não confirmados pela montadora' },
  { chave: 'fontes_bloqueadas', curto: 'bloqueadas', longo: 'fontes bloqueadas' },
] as const

const ROTULO_DO_ESCOPO: Record<string, string> = {
  official_vs_press: 'oficial × imprensa',
  internal_vs_public: 'material interno × fonte pública',
}

function SeloDeStatus({ status }: { status: StatusDeSaude | string }) {
  const aparencia = APARENCIA[status] ?? APARENCIA.INSUFICIENTE
  return (
    <span
      data-testid={`status-${status}`}
      className={[
        'inline-flex h-[22px] shrink-0 items-center gap-1.5 rounded-full px-2',
        'text-meta font-semibold uppercase tracking-[0.06em]',
        aparencia?.classe ?? '',
      ].join(' ')}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${aparencia?.ponto ?? ''}`} />
      {status}
      <span className="sr-only">{aparencia?.simbolo}</span>
    </span>
  )
}

/** Uma métrica da grade: `valor/de` em mono, com a lista dos campos sob demanda. */
function CelulaDeIndicador({ nome, indicador }: { nome: string; indicador: Indicador }) {
  return (
    <Celula numerica className="min-w-[128px] align-middle">
      <span data-testid={`indicador-${nome}`} className="inline-flex flex-col items-end">
        <span className="text-tinta">
          {indicador.valor}/{indicador.de}
        </span>
        {indicador.campos.length > 0 ? (
          <details className="text-right">
            <summary className="cursor-pointer font-sans text-meta text-marca-700 hover:underline">
              ver quais, e por quê
            </summary>
            <ul className="mt-1.5 w-[220px] space-y-1 text-left font-sans text-meta text-tinta-2">
              {indicador.campos.map((campo) => (
                <li key={`${nome}-${campo.campo}`}>
                  <span className="font-medium text-tinta">
                    {campo.campo.startsWith('http') ? campo.campo : rotularCampo(campo.campo)}
                  </span>
                  {': '}
                  {campo.motivo}
                  {campo.detalhe ? (
                    <span className="block text-tinta-3">{campo.detalhe}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </span>
    </Celula>
  )
}

/**
 * A linha da grade, e a régua que abre dentro dela.
 *
 * A régua fica **sempre no DOM**, escondida com `hidden` em vez de removida. `hidden` é
 * `display:none`: leitor de tela não lê, o `Tab` não entra, e o conteúdo continua
 * pesquisável pela página. Remover do DOM faria o botão "por que este status?" parecer que
 * carrega algo, quando o dado já chegou junto com a linha.
 */
function LinhaDaVersao({ saude }: { saude: SaudeDaVersao }) {
  const [aberta, setAberta] = useState(false)
  const idDaRegua = useId()
  return (
    <>
      <Linha testId={`saude-${saude.version_id}`}>
        {/* O gatilho da régua fica DENTRO da célula da versão, e não numa coluna própria:
            uma sexta coluna só para um link empurrava as cinco métricas para fora da
            largura do conteúdo, e a tabela passava a rolar de lado sem precisar. */}
        <CelulaDeRotulo fixa className="min-w-[280px]">
          <span className="flex flex-col gap-1.5 py-2">
            <span className="min-w-0 truncate">{saude.rotulo || saude.version_id}</span>
            <span className="flex flex-wrap items-center gap-1.5">
              <SeloDeStatus status={saude.status} />
              <Badge etiqueta="INFERENCIA" />
            </span>
            <button
              type="button"
              aria-expanded={aberta}
              aria-controls={idDaRegua}
              onClick={() => setAberta((v) => !v)}
              className="inline-flex w-fit items-center gap-1 whitespace-nowrap text-meta font-medium text-marca-700 hover:underline"
            >
              {aberta ? (
                <CaretDown size={14} aria-hidden="true" />
              ) : (
                <CaretRight size={14} aria-hidden="true" />
              )}
              por que este status?
            </button>
          </span>
        </CelulaDeRotulo>
        {METRICAS.map((metrica) => (
          <CelulaDeIndicador
            key={metrica.chave}
            nome={metrica.chave}
            indicador={saude[metrica.chave]}
          />
        ))}
      </Linha>

      <tr id={idDaRegua} hidden={!aberta} className="border-b border-borda bg-superficie-2">
        <td colSpan={METRICAS.length + 1} className="px-4 py-4">
          <p className="text-corpo text-tinta">{saude.explicacao_do_status}</p>
          <p className="mt-1 text-meta text-tinta-2">
            regra: <span className="mono">{saude.regra_do_status}</span> · limiar de{' '}
            <span className="mono">{saude.limiar_de_dias}</span> dias ·{' '}
            {saude.ultima_atualizacao
              ? `última coleta em ${new Date(saude.ultima_atualizacao).toLocaleDateString('pt-BR', {
                  timeZone: 'UTC',
                })}`
              : 'sem data de coleta registrada'}
          </p>
          <ol data-testid="regras" className="mt-3 space-y-1 text-meta text-tinta-2">
            {saude.regras.map((regra) => (
              <li
                key={regra.nome}
                className={
                  regra.nome === saude.regra_do_status ? 'font-semibold text-tinta' : undefined
                }
              >
                <span className="mono">{regra.nome}</span> → {regra.status}: {regra.explicacao}
              </li>
            ))}
          </ol>
          {/* O texto fixo, em toda versão. `docs/13` §3. */}
          <p data-testid="texto-fixo" className="mt-3 text-meta text-tinta-3">
            {saude.texto_fixo}
          </p>
        </td>
      </tr>
    </>
  )
}

function TabelaDeDivergencias({ linhas }: { linhas: Divergencia[] }) {
  if (linhas.length === 0) {
    return (
      <Vazio titulo="Nenhuma divergência neste escopo">
        Silêncio aqui é resultado: a divergência só aparece quando duas fontes com evidência
        discordam.
      </Vazio>
    )
  }
  return (
    <Tabela rotulo="divergências entre fontes, com os dois valores">
      <Cabecalho>
        <Coluna>Campo</Coluna>
        <Coluna>Versão</Coluna>
        <Coluna>Os dois valores, com a origem de cada</Coluna>
        <Coluna numerica>Diferença</Coluna>
      </Cabecalho>
      <Corpo>
        {linhas.map((linha, indice) => (
          <Linha key={`${linha.version_id}-${linha.campo}-${indice}`} testId="divergencia">
            <CelulaDeRotulo>
              <span className="flex flex-wrap items-center gap-2">
                {linha.campo ? rotularCampo(linha.campo) : 'campo não identificado'}
                <Badge etiqueta="FATO" />
              </span>
            </CelulaDeRotulo>
            <Celula className="text-rotulo text-tinta-2">{linha.rotulo}</Celula>
            <Celula>
              {/* Os DOIS valores, sempre. Nunca um vencedor escolhido. */}
              <ul className="space-y-1 py-2">
                {linha.valores.map((valor, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-2 text-meta">
                    <span className="mono rounded-[4px] bg-superficie-2 px-2 py-0.5 text-tinta">
                      {formatarValor(valor.valor)}
                    </span>
                    <span className="min-w-0 break-all text-tinta-2">{valor.origem}</span>
                    {valor.tier ? <span className="text-tinta-3">tier {valor.tier}</span> : null}
                  </li>
                ))}
              </ul>
            </Celula>
            <Celula numerica>
              {linha.gap !== null && linha.gap !== undefined
                ? formatarValor(linha.gap)
                : 'não calculável'}
            </Celula>
          </Linha>
        ))}
      </Corpo>
    </Tabela>
  )
}

export function Saude() {
  const [escopo, setEscopo] = useState<'official_vs_press' | 'internal_vs_public'>(
    'official_vs_press',
  )

  // Tela interna: mostra tier de fonte, fonte bloqueada e divergência com material da
  // casa. Quem decide é a tela (D-204), com a matriz de `docs/12` §6.6 — `enabled` evita
  // três chamadas cujo resultado não seria desenhado.
  const papel = usePapel()
  const podeVer = pode(papel, ACAO_DA_TELA.saude)
  const saude = useQuery({
    queryKey: ['saude', papel],
    queryFn: () => api.saude(),
    enabled: podeVer,
  })
  const cobertura = useQuery({
    queryKey: ['cobertura', papel],
    queryFn: () => api.cobertura(),
    enabled: podeVer,
  })
  const divergencias = useQuery({
    queryKey: ['divergencias', papel, escopo],
    queryFn: () => api.divergencias(escopo),
    enabled: podeVer,
  })
  const carregando = useEsqueleto(podeVer && saude.isPending)

  if (!podeVer) {
    return (
      <Recusa papeis={papeisQuePodem(ACAO_DA_TELA.saude)}>
        Este painel mostra tier de fonte, fonte bloqueada e divergência com material
        interno: informação que não vai para a tela virada ao cliente.
      </Recusa>
    )
  }

  const erro = saude.error ?? cobertura.error
  if (erro) {
    return (
      <Card>
        <Erro>{mensagemDeErro(erro, 'carregar a saúde do conhecimento')}</Erro>
      </Card>
    )
  }

  const versoes = saude.data ?? []
  const marcas = cobertura.data ?? []

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <TituloDeSecao
          descricao={`${versoes.length} versão(ões) com ficha. Cada célula traz o denominador, e "por que este status?" abre a régua inteira.`}
        >
          Saúde por versão
        </TituloDeSecao>

        <div className="overflow-hidden rounded-cartao border border-borda bg-superficie shadow-cartao">
          {carregando ? (
            <div className="p-4">
              <EsqueletoDeLista linhas={5} />
            </div>
          ) : versoes.length === 0 ? (
            <Vazio icone={Gauge} titulo="Nenhuma versão com ficha ainda">
              O que falta coletar está na cobertura por montadora, abaixo: versões mapeadas
              contra versões com ficha.
            </Vazio>
          ) : (
            <Tabela rotulo="saúde do conhecimento por versão, com denominador em cada métrica">
              <Cabecalho>
                <Coluna fixa>Versão</Coluna>
                {METRICAS.map((metrica) => (
                  <Coluna key={metrica.chave} numerica title={metrica.longo}>
                    {metrica.curto}
                  </Coluna>
                ))}
              </Cabecalho>
              <Corpo>
                {versoes.map((v) => (
                  <LinhaDaVersao key={v.version_id} saude={v} />
                ))}
              </Corpo>
            </Tabela>
          )}
        </div>
      </section>

      <Card
        titulo="Cobertura por montadora"
        descricao='"Versões com ficha" contra "versões mapeadas" diz o tamanho do trabalho que falta. É por isso que os dois números aparecem, em vez de uma porcentagem só.'
      >
        <div className="space-y-5">
          {marcas.map((marca) => (
            <div key={marca.marca} data-testid={`cobertura-${marca.marca}`} className="space-y-2">
              <p className="text-corpo font-medium text-tinta">{marca.marca}</p>
              <BarraDeCobertura
                rotulo="versões com ficha"
                valor={marca.versoes_com_ficha}
                total={marca.versoes_mapeadas}
                sufixo="versões"
              />
              <BarraDeCobertura
                rotulo="campos com fonte oficial"
                valor={marca.campos_com_fonte_oficial.valor}
                total={marca.campos_com_fonte_oficial.de}
                sufixo="campos"
              />
              <BarraDeCobertura
                rotulo="não encontrados"
                valor={marca.nao_encontrados.valor}
                total={marca.nao_encontrados.de}
                cor="bg-tinta-3"
                sufixo="campos"
              />
              {marca.por_campo['potencia_rpm'] ? (
                <BarraDeCobertura
                  rotulo="publica rotação (rpm)"
                  valor={marca.por_campo['potencia_rpm'].valor}
                  total={marca.por_campo['potencia_rpm'].de}
                  cor="bg-tinta-3"
                  sufixo="versões"
                />
              ) : null}
            </div>
          ))}
        </div>
      </Card>

      <section className="space-y-3">
        <TituloDeSecao
          descricao="Duas fontes com evidência que discordam. Os dois valores aparecem, sem vencedor escolhido."
          acao={
            <Selecao
              rotulo="escopo"
              aria-label="escopo das divergências"
              className="w-64"
              value={escopo}
              onChange={(e) =>
                setEscopo(e.target.value as 'official_vs_press' | 'internal_vs_public')
              }
            >
              {Object.entries(ROTULO_DO_ESCOPO).map(([valor, rotulo]) => (
                <option key={valor} value={valor}>
                  {rotulo}
                </option>
              ))}
            </Selecao>
          }
        >
          Divergências
        </TituloDeSecao>

        <div className="overflow-hidden rounded-cartao border border-borda bg-superficie shadow-cartao">
          {divergencias.isPending ? (
            <div className="p-4">
              <EsqueletoDeLista linhas={3} />
            </div>
          ) : (
            <TabelaDeDivergencias linhas={divergencias.data ?? []} />
          )}
        </div>
      </section>
    </div>
  )
}
