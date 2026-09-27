/**
 * Insights de win/loss: **o `n` antes do percentual, sempre**.
 *
 * A regra de `docs/12` §6.5 é a espinha desta tela: percentual só com `n ≥ 20`. Abaixo
 * disso a tela mostra "5 de 15" e o motivo — porque "33% de perda" sobre 15 conversas é o
 * tipo de número que vira slide, depois vira meta, e ninguém volta para perguntar qual era
 * o denominador.
 *
 * **Simulado em bloco separado, com a faixa.** A demo tem 40 sessões semeadas contra as
 * poucas reais; uma média das duas apagaria o real, e o rótulo SIMULAÇÃO deixaria de dizer
 * a verdade sobre a linha. Os dois blocos vêm da API já separados
 * (`api/app/services/winloss.py`) — a tela não os junta em lugar nenhum.
 *
 * **A forma, na v2** (`020_BRIEF_PRODUTO.md` §07). A v1 era só texto: contagens em linhas
 * iguais, sem nenhuma comparação visível entre concorrentes, e o bloco real vazio parecia
 * erro. Agora cada concorrente tem uma **barra empilhada** (fechou / perdeu / em andamento)
 * com as contagens ao lado, os três "top 3" em colunas, e o bloco real vazio é um estado
 * vazio digno, que diz o que fazer para preenchê-lo.
 */
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Badge, FaixaDeSimulacao } from '@/components/Badge'
import { BarraEmpilhada } from '@/components/Barras'
import { Card, TituloDeSecao } from '@/components/Card'
import { Entrada } from '@/components/Campo'
import { Erro, EsqueletoDeLista, Vazio, useEsqueleto } from '@/components/Estados'
import { ChartBar } from '@/components/Icones'
import { api, mensagemDeRecusa } from '@/lib/api'
import { usePapel } from '@/lib/papel'
import { ACAO_DA_TELA, escopoDe, papeisQuePodem } from '@/lib/permissoes'
import { mensagemDeErro } from '@/lib/erros'
import { rotularCampo } from '@/lib/formato'
import type { BlocoDeResumo, ContagemDeWinLoss, Etiqueta, PorConcorrente } from '@/lib/tipos'

const ROTULO_DO_MOTIVO: Record<string, string> = {
  preco: 'preço',
  consumo: 'consumo',
  capacidade: 'capacidade',
  seguranca: 'segurança',
  desempenho: 'desempenho',
  conforto: 'conforto',
  marca_confianca: 'marca / confiança',
  prazo_entrega: 'prazo de entrega',
  financiamento: 'financiamento',
  outro: 'outro',
}

const ROTULO_DO_USO: Record<string, string> = {
  rural_carga: 'trabalho rural / carga',
  familia: 'família',
  cidade: 'cidade',
  off_road: 'fora de estrada',
  frota: 'frota',
}

/** As três fatias da barra, sempre nesta ordem e com estas cores. */
const CORES = {
  fechou: 'bg-ganhamos',
  perdeu: 'bg-perdemos',
  em_andamento: 'bg-tinta-3',
} as const

/** `valor/de`, e o percentual **só** quando a API o mandou. Ver o docstring. */
function Numero({ contagem, rotulo }: { contagem: ContagemDeWinLoss; rotulo: string }) {
  return (
    <div>
      <p className="text-meta font-semibold uppercase tracking-[0.06em] text-tinta-3">
        {rotulo}
      </p>
      <p className="mono mt-0.5 text-corpo text-tinta">
        {contagem.valor}
        <span className="text-tinta-3">/{contagem.de}</span>
        {contagem.percentual !== null ? (
          <span className="ml-1.5 font-sans text-rotulo text-tinta-2">
            ({contagem.percentual.toFixed(1)}%)
          </span>
        ) : null}
      </p>
    </div>
  )
}

function Lista({
  titulo,
  itens,
  rotulos,
}: {
  titulo: string
  itens: { chave: string; n: number }[]
  rotulos?: Record<string, string>
}) {
  if (itens.length === 0) {
    return (
      <div>
        <p className="text-meta font-semibold uppercase tracking-[0.06em] text-tinta-3">
          {titulo}
        </p>
        <p className="mt-1 text-meta text-tinta-3">
          nada registrado ainda: silêncio aqui é ausência de registro, não ausência de motivo.
        </p>
      </div>
    )
  }
  return (
    <div>
      <p className="text-meta font-semibold uppercase tracking-[0.06em] text-tinta-3">
        {titulo}
      </p>
      <ul className="mt-1 space-y-1">
        {itens.map((item) => (
          <li key={item.chave} className="flex items-baseline justify-between gap-2 text-rotulo">
            <span className="min-w-0 truncate text-tinta">
              {rotulos?.[item.chave] ?? rotularCampo(item.chave)}
            </span>
            <span className="mono shrink-0 text-meta text-tinta-2">{item.n}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Um concorrente no painel de win/loss.
 *
 * A **etiqueta vem de fora** e não tem valor padrão, por defeito medido em 09/09/2026:
 * o cartão marcava `FATO` fixo e é usado nos **dois** blocos — o real e o de
 * demonstração. No bloco de demonstração isso punha um `FATO` debaixo da faixa
 * `SIMULAÇÃO`, que é a contradição mais direta possível da convenção de `docs/13` §2:
 * a mesma informação declarada observada e hipotética ao mesmo tempo.
 *
 * Sem valor padrão de propósito: quem monta o cartão **tem** de dizer de onde o dado
 * vem. Um padrão `FATO` é exatamente como o defeito nasceu.
 */
function CartaoDoConcorrente({ dados, etiqueta }: { dados: PorConcorrente; etiqueta: Etiqueta }) {
  return (
    <li
      data-testid={`concorrente-${dados.version_id}`}
      className="border-b border-borda px-4 py-4 last:border-b-0"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-tinta">{dados.rotulo}</span>
        <span className="mono rounded-[4px] bg-superficie-2 px-2 py-0.5 text-meta text-tinta-2">
          n = {dados.n}
        </span>
        <Badge etiqueta={etiqueta} />
      </div>

      <div className="mt-3">
        <BarraEmpilhada
          total={dados.n}
          fatias={[
            { rotulo: 'fechou', valor: dados.fechou.valor, cor: CORES.fechou },
            { rotulo: 'perdeu', valor: dados.perdeu.valor, cor: CORES.perdeu },
            { rotulo: 'em andamento', valor: dados.em_andamento.valor, cor: CORES.em_andamento },
          ]}
        />
      </div>

      {/* Uma coluna no celular: em 390 px, três colunas dão ~130 px, e "em andamento"
          com o número embaixo não cabe. A regra está medida em `viewport.test.tsx`. */}
      <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Numero contagem={dados.fechou} rotulo="fechou" />
        <Numero contagem={dados.perdeu} rotulo="perdeu" />
        <Numero contagem={dados.em_andamento} rotulo="em andamento" />
      </dl>

      {dados.aviso ? (
        <p data-testid={`aviso-${dados.version_id}`} className="mt-3 text-meta text-naoSabemos">
          {dados.aviso}
        </p>
      ) : null}

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Lista titulo="motivos de perda" itens={dados.top_motivos} rotulos={ROTULO_DO_MOTIVO} />
        <Lista titulo="atributos decisivos" itens={dados.top_atributos_decisivos} />
        <Lista titulo="perfis" itens={dados.perfis} rotulos={ROTULO_DO_USO} />
      </div>
    </li>
  )
}

function Resumo({ bloco, titulo }: { bloco: BlocoDeResumo; titulo: string }) {
  return (
    <div
      data-testid={`resumo-${titulo}`}
      className="rounded-controle border border-borda p-4"
    >
      <p className="font-medium text-tinta">
        {titulo} <span className="mono text-rotulo text-tinta-2">n = {bloco.n}</span>
      </p>
      <div className="mt-3">
        <BarraEmpilhada
          total={bloco.n}
          fatias={[
            { rotulo: 'fechou', valor: bloco.fechou.valor, cor: CORES.fechou },
            { rotulo: 'perdeu', valor: bloco.perdeu.valor, cor: CORES.perdeu },
            { rotulo: 'em andamento', valor: bloco.em_andamento.valor, cor: CORES.em_andamento },
          ]}
        />
      </div>
      <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Numero contagem={bloco.fechou} rotulo="fechou" />
        <Numero contagem={bloco.perdeu} rotulo="perdeu" />
        <Numero contagem={bloco.em_andamento} rotulo="em andamento" />
      </dl>
      {bloco.aviso ? <p className="mt-3 text-meta text-naoSabemos">{bloco.aviso}</p> : null}
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Lista titulo="motivos de perda" itens={bloco.top_motivos} rotulos={ROTULO_DO_MOTIVO} />
        <Lista titulo="atributos decisivos" itens={bloco.top_atributos_decisivos} />
      </div>
    </div>
  )
}

export function Insights() {
  const [desde, setDesde] = useState('')

  const papel = usePapel()
  // O **painel por concorrente** é de todo mundo: o vendedor entra e vê o próprio
  // recorte (escopo `proprios` na matriz), com o aviso que o servidor manda junto.
  const painel = useQuery({
    queryKey: ['winloss', papel, desde],
    queryFn: () => api.winLossPorConcorrente(undefined, desde || undefined),
  })
  // O **resumo** é o agregado da concessionária, e esse não é do vendedor (D-103). Sai
  // da matriz, não de um `if` com o nome do papel escrito: quem tem escopo `todos` em
  // `ver_insights` vê o agregado; quem tem `proprios` vê só o próprio recorte, acima.
  const podeVerResumo = escopoDe(papel, ACAO_DA_TELA.insights) === 'todos'
  const resumo = useQuery({
    queryKey: ['winloss-resumo', papel, desde],
    queryFn: () => api.winLossResumo(desde || undefined),
    enabled: podeVerResumo,
  })
  const carregando = useEsqueleto(painel.isPending)

  const recusaDoResumo = podeVerResumo
    ? mensagemDeRecusa(resumo.error, 'ver o resumo de win/loss')
    : `O resumo agrega as sessões da concessionária inteira, e é de ${papeisQuePodem(
        ACAO_DA_TELA.insights,
        'todos',
      )}. Acima, no painel por concorrente, você vê as sessões que registrou.`

  if (painel.error) {
    return (
      <Card>
        <Erro>{mensagemDeErro(painel.error, 'carregar o win/loss')}</Erro>
      </Card>
    )
  }

  const dados = painel.data

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <TituloDeSecao
          descricao={`Percentual só aparece com n ≥ ${
            dados?.n_minimo_para_percentual ?? 20
          }. Abaixo disso, contagens: um percentual sobre poucos casos pareceria estatística e seria ruído.`}
          acao={
            <Entrada
              rotulo="desde"
              aria-label="desde"
              type="date"
              className="w-48"
              value={desde.slice(0, 10)}
              onChange={(e) => setDesde(e.target.value ? `${e.target.value}T00:00:00` : '')}
            />
          }
        >
          Win/Loss por concorrente
        </TituloDeSecao>

        {dados?.aviso_de_escopo ? (
          <p data-testid="aviso-de-escopo" className="text-corpo font-medium text-tinta-2">
            {dados.aviso_de_escopo}
          </p>
        ) : null}

        <div className="overflow-hidden rounded-cartao border border-borda bg-superficie shadow-cartao">
          {carregando ? (
            <div className="p-4">
              <EsqueletoDeLista linhas={3} />
            </div>
          ) : dados && dados.real.length === 0 ? (
            <Vazio icone={ChartBar} titulo="Nenhuma sessão real registrada ainda">
              Quando os vendedores fecharem uma sessão de showroom com o desfecho, os números
              aparecem aqui. O bloco de demonstração abaixo está rotulado SIMULAÇÃO e não se
              mistura com este.
            </Vazio>
          ) : (
            <ul>
              {dados?.real.map((concorrente) => (
                <CartaoDoConcorrente
                  key={concorrente.version_id}
                  dados={concorrente}
                  etiqueta="FATO"
                />
              ))}
            </ul>
          )}
        </div>
      </section>

      {dados && dados.simulado.length > 0 ? (
        <section className="space-y-3">
          <TituloDeSecao descricao="Sessões semeadas para a demonstração. Elas nunca entram na conta do bloco real.">
            Win/Loss, dados de demonstração
          </TituloDeSecao>
          {/* Uma faixa por seção: dentro da lista, cada item leva só o pill. */}
          <FaixaDeSimulacao>
            ({dados.n_simulado} sessão(ões) semeada(s), separadas das {dados.n_real} reais)
          </FaixaDeSimulacao>
          <ul className="overflow-hidden rounded-cartao border border-borda bg-superficie shadow-cartao">
            {dados.simulado.map((concorrente) => (
              <CartaoDoConcorrente
                key={concorrente.version_id}
                dados={concorrente}
                etiqueta="SIMULACAO"
              />
            ))}
          </ul>
        </section>
      ) : null}

      {resumo.data ? (
        <Card
          titulo="Resumo"
          descricao="Os dois blocos nunca são somados: com 40 sessões semeadas contra poucas reais, a média apagaria o real."
        >
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Resumo bloco={resumo.data.real} titulo="real" />
            <Resumo bloco={resumo.data.simulado} titulo="simulado" />
          </div>
        </Card>
      ) : recusaDoResumo ? (
        /* O cartão **não** desaparece em silêncio. O agregado não é do vendedor (D-103),
           e um cartão que some é indistinguível de tela quebrada. */
        <Card titulo="Resumo">
          <p
            data-testid="recusa-do-resumo"
            role="alert"
            className="rounded-controle bg-naoSabemos-fundo px-4 py-3 text-corpo text-naoSabemos"
          >
            {recusaDoResumo}
          </p>
        </Card>
      ) : null}
    </div>
  )
}
