/**
 * Simulador: **"e se a Hilux baixar 5%?"** — com a resposta marcada como hipótese.
 *
 * A tela tem uma responsabilidade que nenhuma outra tem: mostrar um número que **ninguém
 * observou** sem que ele seja confundido com dado. Três decisões vêm disso:
 *
 * * **a faixa SIMULAÇÃO é permanente e por painel.** Não é um aviso no topo que sai de
 *   vista ao rolar: o painel de cenário carrega a sua, com o texto que a API manda
 *   (`rotulo_simulacao`). Se alguém recortar a tela para um slide, o recorte vem com o
 *   aviso dentro;
 * * **"Realidade" e "Cenário" ficam lado a lado, na mesma ordem de campos.** Um simulador
 *   que substitui os números no lugar deixaria o usuário sem o "antes" — e a pergunta é
 *   justamente o que **mudaria**;
 * * **o slider não decide nada.** Ele monta um `override` e a API recalcula tudo:
 *   paridade, aderência e materialidade saem dos mesmos motores do Radar e da Matriz. Uma
 *   conta local aqui produziria uma segunda verdade — e a divergência apareceria como "no
 *   cenário mudou" quando o que mudou foi a tela.
 *
 * **A forma, na v2** (`020_BRIEF_PRODUTO.md` §08). O slider era um `-5%` sem contexto:
 * cinco por cento de quanto? Agora ele mostra **o valor absoluto ao lado**
 * (R$ 379.990 → R$ 360.990), lido de `overrides_aplicados`, que é o que a API respondeu —
 * e não uma conta feita aqui. As hipóteses ativas viraram chips removíveis, e o erro
 * técnico que aparecia no painel vazio virou frase em português (`lib/erros.ts`).
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Badge, FaixaDeSimulacao } from '@/components/Badge'
import { Card, TituloDeSecao } from '@/components/Card'
import { Marcacao, Selecao } from '@/components/Campo'
import { Chip } from '@/components/Chip'
import { Erro, Esqueleto } from '@/components/Estados'
import { APARENCIA, PillDeEstado } from '@/components/Paridade'
import { api } from '@/lib/api'
import { mensagemDeErro } from '@/lib/erros'
import { formatarValor, rotularCampo } from '@/lib/formato'
import {
  PADRAO_DO_SIMULADOR,
  PADRAO_FORD,
  escolherPadrao,
  nomeCurto,
  nomeDoVeiculo,
} from '@/lib/veiculos'
import {
  CLASSES_DA_FAIXA,
  ICONE_DA_FAIXA,
  PONTO_DA_FAIXA,
  ROTULO_DA_FAIXA,
  formatarPontos,
} from '@/lib/materialidade'
import type {
  DiffDoCenario,
  EstadoDeParidade,
  OverrideDoCenario,
  PainelDoCenario,
  Simulacao,
} from '@/lib/tipos'

/** A faixa do slider. A API aceita mais; a tela oferece o que a spec pede. */
const MINIMO_DO_SLIDER = -10
const MAXIMO_DO_SLIDER = 10

const ORDEM_DOS_ESTADOS: EstadoDeParidade[] = ['vantagem', 'paridade', 'gap', 'desconhecido']

function Painel({ painel, titulo }: { painel: PainelDoCenario; titulo: string }) {
  const contagem = painel.coluna.contagem
  return (
    <section
      data-testid={`painel-${painel.is_simulation ? 'cenario' : 'realidade'}`}
      className={[
        'rounded-cartao border p-5 shadow-cartao',
        painel.is_simulation
          ? 'border-simulacao/30 bg-simulacao-fundo/40'
          : 'border-borda bg-superficie',
      ].join(' ')}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-cartao text-tinta">{titulo}</h3>
        <Badge etiqueta={painel.is_simulation ? 'SIMULACAO' : 'FATO'} />
      </div>

      {/* A faixa fica DENTRO do painel: recorte da tela vem com o aviso. O texto é o
          que a API manda — "não é dado observado" —, e não "dado de demonstração": o
          cenário é hipótese de quem está olhando, não semente do banco. */}
      {painel.is_simulation && painel.rotulo_simulacao ? (
        <div className="mt-3">
          <FaixaDeSimulacao texto={painel.rotulo_simulacao} />
        </div>
      ) : null}

      {/* `--surface-2` e não `--surface`: no painel da Realidade, que já é branco, as
          quatro caixas ficavam brancas sobre branco e sumiam — os números apareciam
          soltos, enquanto os do Cenário (sobre o fundo âmbar da simulação) tinham moldura.
          Dois painéis que mostram a mesma coisa têm de mostrá-la igual, senão a diferença
          de forma se lê como diferença de conteúdo. */}
      <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {ORDEM_DOS_ESTADOS.map((estado) => (
          <div key={estado} className="rounded-controle bg-superficie-2 px-3 py-2">
            <dt className="text-meta text-tinta-2">{APARENCIA[estado].rotulo}</dt>
            <dd className="mono mt-0.5 text-[22px] font-medium leading-7 text-tinta">
              {contagem[estado]}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-meta text-tinta-3">
        {contagem.comparados} de {contagem.total} campo(s) com os dois lados conhecidos
      </p>

      {/* A flag dos 1.000 kg **por painel**: um cenário que tira a capacidade de carga
          deixa a regra indeterminada, e "não avaliada" é diferente de "não atingida" —
          diferença que importa numa frase que fala de enquadramento fiscal. */}
      {painel.coluna.flag_de_carga?.aplicavel && painel.coluna.flag_de_carga.valor ? (
        <div
          data-testid="flag-1000kg"
          className="mt-4 flex flex-wrap items-start gap-2 rounded-controle bg-superficie px-3 py-2 text-rotulo"
        >
          <Badge etiqueta="INFERENCIA" />
          <p className="min-w-0 flex-1 text-tinta">{painel.coluna.flag_de_carga.texto}</p>
        </div>
      ) : null}
      {painel.coluna.flag_de_carga && !painel.coluna.flag_de_carga.aplicavel ? (
        <p data-testid="carga-indeterminada" className="mt-4 text-meta text-tinta-2">
          regra dos 1.000 kg não avaliável. {painel.coluna.flag_de_carga.motivo}
        </p>
      ) : null}

      {painel.coluna.comparabilidade?.aviso ? (
        <p className="mt-4 rounded-controle bg-naoSabemos-fundo px-3 py-2 text-meta text-naoSabemos">
          <span className="mono">{painel.coluna.comparabilidade.resumo}</span>.{' '}
          {painel.coluna.comparabilidade.aviso}
        </p>
      ) : null}

      {painel.aderencia ? (
        <p className="mt-4 text-corpo text-tinta-2">
          <span className="font-medium text-tinta">Aderência ao perfil:</span> Ford{' '}
          <span className="mono text-tinta">{painel.aderencia.aderencia_ford ?? 'sem nota'}</span>{' '}
          ×{' '}
          <span className="mono text-tinta">
            {painel.aderencia.aderencia_concorrente ?? 'sem nota'}
          </span>{' '}
          concorrente
        </p>
      ) : null}
    </section>
  )
}

function BlocoDoDiff({ diff }: { diff: DiffDoCenario }) {
  const materialidade = diff.materialidade
  return (
    <Card titulo={`O que mudaria: ${diff.rotulo}`}>
      <div data-testid="diff">
        {materialidade ? (
          <div>
            <div
              data-testid="materialidade-do-cenario"
              className={[
                'inline-flex flex-wrap items-center gap-2 rounded-controle px-3 py-2',
                CLASSES_DA_FAIXA[materialidade.materiality] ?? CLASSES_DA_FAIXA.BAIXA,
              ].join(' ')}
            >
              <span
                aria-hidden="true"
                className={`h-1.5 w-1.5 rounded-full ${PONTO_DA_FAIXA[materialidade.materiality] ?? PONTO_DA_FAIXA.BAIXA}`}
              />
              <span className="text-rotulo font-semibold uppercase tracking-[0.06em]">
                seria {ROTULO_DA_FAIXA[materialidade.materiality] ?? materialidade.materiality}
              </span>
              <span className="mono text-meta">{formatarPontos(materialidade.pontos)}</span>
              <Badge etiqueta="INFERENCIA" />
              <span className="sr-only">{ICONE_DA_FAIXA[materialidade.materiality] ?? '·'}</span>
            </div>
            <p className="mt-2 text-rotulo text-tinta-2">{materialidade.nota_de_hipotese}</p>
            <ul className="mt-2 space-y-1 text-meta text-tinta-2">
              {materialidade.rules_fired.map((regra) => (
                <li key={regra.id}>
                  <span className="mono">{regra.id}</span>{' '}
                  <span className="mono">
                    {regra.peso > 0 ? '+' : ''}
                    {regra.peso}
                  </span>{' '}
                  {regra.detalhe || regra.descricao}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p data-testid="sem-materialidade" className="text-corpo text-tinta-2">
            {diff.motivo_sem_materialidade}
          </p>
        )}

        {diff.paridade.length > 0 ? (
          <ul data-testid="mudancas" className="mt-5 space-y-2">
            {diff.paridade.map((mudanca) => (
              <li key={mudanca.campo} className="flex flex-wrap items-center gap-2 text-corpo">
                <span className="font-medium text-tinta">{rotularCampo(mudanca.campo)}:</span>
                <PillDeEstado estado={mudanca.antes as EstadoDeParidade} />
                <span aria-hidden="true" className="text-tinta-3">
                  →
                </span>
                <PillDeEstado estado={mudanca.depois as EstadoDeParidade} />
              </li>
            ))}
          </ul>
        ) : (
          <p data-testid="sem-mudanca" className="mt-5 text-corpo text-tinta-2">
            Nenhum estado de paridade mudaria. Silêncio aqui é resposta: a hipótese não é
            suficiente para inverter nenhum campo.
          </p>
        )}

        {diff.aderencia.length > 0 ? (
          <ul data-testid="mudancas-de-aderencia" className="mt-5 space-y-1 text-corpo">
            {diff.aderencia.map((linha) => (
              <li key={linha.dimensao}>
                <span className="font-medium text-tinta">{linha.rotulo}:</span> concorrente de{' '}
                <span className="mono">{linha.antes.concorrente ?? 'sem nota'}</span> para{' '}
                <span className="mono">{linha.depois.concorrente ?? 'sem nota'}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Card>
  )
}

export function Simulador() {
  const [fordVersion, setFordVersion] = useState('')
  const [concorrente, setConcorrente] = useState('')
  const [deltaPct, setDeltaPct] = useState(-5)
  const [removidos, setRemovidos] = useState<string[]>([])

  const veiculos = useQuery({ queryKey: ['veiculos'], queryFn: () => api.veiculos() })
  const campos = useQuery({
    queryKey: ['campos-do-simulador'],
    queryFn: () => api.camposDoSimulador(),
  })

  const lista = veiculos.data ?? []
  const fords = lista.filter((v) => v.marca === 'Ford')
  const outros = lista.filter((v) => v.marca !== 'Ford')
  // Par com preço dos dois lados (D-208): Ranger Limited x Amarok V6 Extreme. A
  // pergunta desta tela é "e se o concorrente baixar 5%?", e ela precisa de um preço
  // sobre o qual incidir. Com `lista[0]` o simulador abria na S10 sem ficha, e com a
  // Hilux abria sem preço: nos dois casos a tela mostrava um erro do seletor, não do dado.
  const referencia = fordVersion || escolherPadrao(fords, PADRAO_FORD)
  const escolhido = concorrente || escolherPadrao(outros, PADRAO_DO_SIMULADOR)

  const overrides = useMemo<OverrideDoCenario[]>(() => {
    if (!escolhido) return []
    const lista: OverrideDoCenario[] = []
    if (deltaPct !== 0) {
      lista.push({ version_id: escolhido, campo: 'preco_sugerido_brl', delta_pct: deltaPct })
    }
    for (const campo of removidos) {
      lista.push({ version_id: escolhido, campo, remover: true })
    }
    return lista
  }, [escolhido, deltaPct, removidos])

  const simulacao = useQuery({
    queryKey: ['cenario', referencia, escolhido, deltaPct, removidos.join(',')],
    queryFn: () => api.simular({ base_version_ids: [referencia, escolhido], overrides }),
    enabled: Boolean(referencia) && Boolean(escolhido),
  })

  /**
   * A realidade, sem hipótese nenhuma, quando a hipótese **não se aplica**.
   *
   * Acontece de verdade e não é defeito: a Hilux SRX Plus não tem preço verificado (a
   * Toyota bloqueia a coleta, e o bloqueio está registrado como estado), então a hipótese
   * "e se ela baixar 5%?" não tem de que baixar. Sem esta segunda consulta a tela ficaria
   * só com a mensagem, e o brief pede os **dois painéis sempre visíveis**: a Realidade
   * continua tendo o que mostrar, e o Cenário mostra por que não há cenário.
   */
  const realidade = useQuery({
    queryKey: ['cenario-sem-hipotese', referencia, escolhido],
    queryFn: () => api.simular({ base_version_ids: [referencia, escolhido], overrides: [] }),
    enabled: Boolean(simulacao.error) && Boolean(referencia) && Boolean(escolhido),
  })

  const dados: Simulacao | undefined = simulacao.data
  const removiveis = campos.data?.delta_pct.campos ?? []

  /**
   * O preço antes e depois, para o slider mostrar reais e não só porcentagem.
   *
   * Sai de `overrides_aplicados`, que é **o que a API respondeu**. Calcular aqui
   * (`preco * (1 + delta)`) produziria uma segunda conta que divergiria do painel na
   * primeira regra de arredondamento — e o produto inteiro existe para não ter duas contas.
   */
  const precoDoCenario = dados?.overrides_aplicados.find(
    (o) => o.campo === 'preco_sugerido_brl',
  )

  return (
    <div className="space-y-6">
      {/* O aviso vem ANTES dos controles: quem chega na tela lê o que ela é. O texto
          padrão fica (é o mesmo vocabulário do resto do produto) e a frase específica
          desta tela entra como complemento: aqui a SIMULAÇÃO não é semente do banco, é
          hipótese de quem está olhando. */}
      <FaixaDeSimulacao>
        (tudo nesta tela é hipótese informada por você, não dado observado)
      </FaixaDeSimulacao>

      <Card titulo="A hipótese" descricao="Escolha o par e o que mudaria no concorrente.">
        <div className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Selecao
              rotulo="Versão Ford"
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

            <Selecao
              rotulo="Concorrente"
              aria-label="concorrente do cenário"
              value={escolhido}
              onChange={(e) => setConcorrente(e.target.value)}
            >
              {outros.map((v) => (
                <option key={v.id} value={v.id}>
                  {nomeDoVeiculo(v)}
                </option>
              ))}
            </Selecao>
          </div>

          <div>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              {/* O texto sai como um nó só, sem `<span>` no meio: "Preço do concorrente:
                  -5%" partido em dois elementos não é encontrável por texto, nem por quem
                  lê a tela com leitor de tela. A mono vem do próprio `<label>`. */}
              <label
                htmlFor="slider-de-preco"
                className="text-rotulo font-medium text-tinta-2"
              >
                {`Preço do concorrente: ${deltaPct > 0 ? '+' : ''}${deltaPct}%`}
              </label>
              {precoDoCenario ? (
                <p className="mono text-rotulo text-tinta">
                  <span className="text-tinta-3 line-through">
                    {formatarValor(precoDoCenario.antes)}
                  </span>{' '}
                  <span aria-hidden="true" className="text-tinta-3">
                    →
                  </span>{' '}
                  <span className="font-medium">{formatarValor(precoDoCenario.depois)}</span>
                </p>
              ) : null}
            </div>
            <input
              id="slider-de-preco"
              data-testid="slider-de-preco"
              type="range"
              min={MINIMO_DO_SLIDER}
              max={MAXIMO_DO_SLIDER}
              step={1}
              value={deltaPct}
              onChange={(e) => setDeltaPct(Number(e.target.value))}
              className="mt-2 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-superficie-2 accent-[var(--brand-600)]"
            />
            <p className="mt-1.5 text-meta text-tinta-3">
              de {MINIMO_DO_SLIDER}% a +{MAXIMO_DO_SLIDER}%. Zero significa "sem hipótese de
              preço", e aí o cenário é igual à realidade.
            </p>
          </div>

          {removiveis.length > 0 ? (
            <fieldset>
              <legend className="mb-1.5 text-rotulo font-medium text-tinta-2">
                E se o concorrente perdesse…
              </legend>
              <div className="flex flex-wrap gap-x-4">
                {removiveis
                  .filter((campo) => campo !== 'preco_sugerido_brl')
                  .map((campo) => (
                    <Marcacao
                      key={campo}
                      rotulo={rotularCampo(campo)}
                      checked={removidos.includes(campo)}
                      onChange={() =>
                        setRemovidos((atuais) =>
                          atuais.includes(campo)
                            ? atuais.filter((c) => c !== campo)
                            : [...atuais, campo],
                        )
                      }
                    />
                  ))}
              </div>
              <p className="mt-1.5 text-meta text-tinta-3">{campos.data?.remover.descricao}</p>
            </fieldset>
          ) : null}

          {/* As hipóteses ativas como chips removíveis: elas dizem o que está valendo, e
              tirar uma não exige achar o controle que a ligou. */}
          {dados && dados.overrides_aplicados.length > 0 ? (
            <div>
              <p className="mb-1.5 text-rotulo font-medium text-tinta-2">Hipóteses ativas</p>
              <div data-testid="hipoteses" className="flex flex-wrap gap-2">
                {dados.overrides_aplicados.map((override) => (
                  <Chip
                    key={`${override.version_id}-${override.campo}`}
                    onRemover={
                      override.campo === 'preco_sugerido_brl'
                        ? () => setDeltaPct(0)
                        : () => setRemovidos((a) => a.filter((c) => c !== override.campo))
                    }
                  >
                    <span className="font-medium">{rotularCampo(override.campo)}:</span>
                    <span className="mono">{formatarValor(override.antes)}</span>
                    <span aria-hidden="true">→</span>
                    <span className="mono font-medium">{formatarValor(override.depois)}</span>
                    {/* A origem por extenso: o chip precisa dizer que o número é hipótese
                        de quem está olhando, e não um valor que alguém observou. */}
                    <span className="text-tinta-3">({override.origem})</span>
                  </Chip>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-rotulo text-tinta-2">
              Nenhuma hipótese ativa: mova o slider ou marque um item para simular.
            </p>
          )}
        </div>
      </Card>

      {simulacao.error ? (
        <section className="space-y-3">
          <TituloDeSecao descricao="A hipótese não se aplica a este par, e a realidade continua à vista.">
            Realidade × Cenário
          </TituloDeSecao>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {(realidade.data?.atual ?? []).map((painel) => (
              <Painel key={`real-${painel.version_id}`} painel={painel} titulo="Realidade" />
            ))}
            <div className="rounded-cartao border border-borda bg-superficie p-5 shadow-cartao">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-cartao text-tinta">Cenário</h3>
                <Badge etiqueta="SIMULACAO" />
              </div>
              {/* A frase é a da pessoa, não a do servidor: o texto cru dizia
                  "preco_sugerido_brl não é número neste veículo (valor atual: None)" e
                  parecia defeito do produto quando era o veículo escolhido que não tem
                  preço verificado. A tradução está em `lib/erros.ts`. */}
              <div className="-mx-5">
                <Erro titulo="Sem cenário para este par">
                  {mensagemDeErro(simulacao.error, 'simular o cenário')}
                </Erro>
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {simulacao.isPending && simulacao.fetchStatus !== 'idle' ? (
        <div aria-busy="true">
          <span className="sr-only">calculando o cenário</span>
          <Esqueleto className="h-[280px]" />
        </div>
      ) : null}

      {dados ? (
        <>
          <section className="space-y-3">
            <TituloDeSecao descricao="Os dois lado a lado, na mesma ordem de campos: a pergunta é o que mudaria.">
              Realidade × Cenário
            </TituloDeSecao>

            {/* Lado a lado no desktop, empilhados no celular: o critério de 390 px da
                WP-31 vale aqui também, e "Realidade" vem primeiro nas duas formas. */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {dados.atual.map((painel) => (
                <Painel key={`atual-${painel.version_id}`} painel={painel} titulo="Realidade" />
              ))}
              {dados.cenario.map((painel) => (
                <Painel key={`cenario-${painel.version_id}`} painel={painel} titulo="Cenário" />
              ))}
            </div>
          </section>

          {dados.diffs.map((diff) => (
            <BlocoDoDiff key={diff.version_id} diff={diff} />
          ))}
        </>
      ) : null}
    </div>
  )
}
