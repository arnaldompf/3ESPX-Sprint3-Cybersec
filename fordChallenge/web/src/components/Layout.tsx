/**
 * O casco v2: **navegação lateral**, barra superior de 56 px e conteúdo de 1200 px.
 *
 * O que mudou e por quê. A v1 tinha abas em pílula branca sobre uma barra azul cheia —
 * sete abas que já não cabiam em 390 px e roláveis na horizontal. Era o traço mais datado
 * da tela ("site de 2012") e, pior, o azul saturado de ponta a ponta competia com o único
 * azul que devia significar alguma coisa: o da ação. A sidebar resolve os dois: a
 * navegação cabe verticalmente, o item ativo se marca com fundo `--brand-50` e texto
 * `--brand-700`, e a barra azul sai da tela.
 *
 * **Três formas, um componente** (`010_DESIGN.md` §8):
 *
 * * ≥ 1280 px: sidebar de 248 px com ícone e rótulo;
 * * 769–1279 px: sidebar recolhida a 64 px, só ícones (o rótulo vira `title` e `sr-only`);
 * * ≤ 768 px: a sidebar vira **barra inferior** com cinco alvos de 44 px, e o resto entra
 *   em "mais".
 *
 * **O cabeçalho da tela mora aqui, e não dentro de cada página.** Cada página tem retornos
 * antecipados — carregando, erro, sem permissão, sem dado —, e um título escrito lá dentro
 * apareceria no caminho feliz e sumiria justamente nos outros. Desenhado acima do
 * `<Outlet />`, ele **não depende do estado da página**: tela que falhou continua dizendo
 * o que é. É o que "nunca uma tela em branco" quer dizer na prática. A tabela está em
 * `lib/paginas.ts`, e é a mesma que desenha a navegação — item e título não divergem.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { api } from '@/lib/api'
import { PAGINAS, paginaDoCaminho } from '@/lib/paginas'
import {
  NOME_DO_PAPEL,
  O_QUE_FAZ,
  PAPEIS,
  definirPapel,
  usePapel,
  type Papel,
} from '@/lib/papel'
import { ICONE_DA_PAGINA } from './Icones'
import { CaretDown, Check, User } from './Icones'

/** As cinco que cabem na barra inferior do celular; o resto entra em "mais". */
const NO_CELULAR = ['/consulta', '/radar', '/matriz', '/showroom']

/**
 * O contador de alertas nao lidos no item do Radar.
 *
 * Duas coisas deliberadas: **conta so os nao lidos**, porque um numero que nunca zera
 * vira parte do desenho da barra e para de ser aviso; e **erro nao aparece**, porque o
 * vendedor recebe 403 em `/alerts` (`docs/12` §6.1) e um "!" vermelho anunciaria uma
 * falha onde a regra e proposital.
 */
function useNaoLidos(): number | null {
  const consulta = useQuery({
    queryKey: ['alertas', 'contador'],
    queryFn: () => api.alertas(),
    // Sem permissao nao ha contador, e nao ha erro a mostrar: `null` some com o selo.
    retry: false,
  })
  if (consulta.error || !consulta.data) return null
  const naoLidos = consulta.data.filter((alerta) => !alerta.lido).length
  return naoLidos > 0 ? naoLidos : null
}

/**
 * As ações contextuais da barra superior.
 *
 * Um portal, e não uma prop atravessando o `Outlet`: a ação pertence à página (só a Matriz
 * sabe que tem um "exportar"), mas o lugar dela é a barra. Passar por props exigiria que o
 * Layout conhecesse todas as páginas, que é exatamente o acoplamento que o roteador existe
 * para evitar.
 */
const DestinoDasAcoes = createContext<HTMLElement | null>(null)

export function AcoesDaPagina({ children }: { children: ReactNode }) {
  const destino = useContext(DestinoDasAcoes)
  if (!destino) return null
  return createPortal(children, destino)
}

function Wordmark() {
  return (
    <div className="flex h-barra shrink-0 items-center justify-center gap-2 px-4 xl:justify-start">
      {/* O quadrado com a inicial é o wordmark, não um logotipo da Ford: `020_BRIEF` é
          explícito em não usar nem redesenhar a marca da Ford dentro do produto. */}
      <span
        aria-hidden="true"
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] bg-marca-950 text-rotulo font-bold text-white"
      >
        S
      </span>
      <span className="min-w-0 max-xl:sr-only">
        <span className="block truncate text-corpo font-semibold leading-tight text-tinta">
          SpecRadar
        </span>
        <span className="block truncate text-meta leading-tight text-tinta-3">
          ficha técnica com evidência
        </span>
      </span>
    </div>
  )
}

/**
 * Um item da sidebar, numa cópia só.
 *
 * O rótulo aparece e some por media query (`hidden xl:block`) em vez de duas árvores
 * alternadas por JavaScript. Duas cópias no DOM dariam dois `data-testid` iguais e dois
 * links com o mesmo nome acessível — e, mais importante, exigiriam medir a janela e
 * re-renderizar a cada `resize` para fazer o que o CSS faz de graça.
 */
function ItemDeNavegacao({
  para,
  rotulo,
  contador,
}: {
  para: string
  rotulo: string
  contador: number | null
}) {
  const Icone = ICONE_DA_PAGINA[para]
  return (
    <NavLink
      to={para}
      title={rotulo}
      className={({ isActive }) =>
        [
          'relative flex h-10 items-center gap-3 rounded-controle text-corpo',
          'justify-center px-0 xl:justify-start xl:px-3',
          'transition-colors duration-150 ease-out',
          isActive
            ? 'bg-marca-50 font-medium text-marca-700'
            : 'text-tinta-2 hover:bg-superficie-2 hover:text-tinta',
        ].join(' ')
      }
    >
      {Icone ? <Icone size={20} aria-hidden="true" className="shrink-0" /> : null}
      <span className="min-w-0 flex-1 truncate text-left max-xl:sr-only">{rotulo}</span>
      {contador !== null ? (
        <span
          data-testid="contador-radar"
          aria-label={`${contador} alerta(s) nao lido(s)`}
          className={[
            'mono inline-flex h-5 min-w-[20px] shrink-0 items-center justify-center rounded-full',
            'bg-marca-600 px-1 text-meta font-semibold text-white',
            'absolute right-1.5 top-1 xl:static',
          ].join(' ')}
        >
          {contador}
        </span>
      ) : null}
    </NavLink>
  )
}

/**
 * O rodapé da sidebar: **quem está olhando, e o seletor que troca**.
 *
 * Antes daqui saía "sair" (ou "trocar papel" no modo demonstração), e o destino era a tela
 * de entrada. Não há mais tela de entrada (D-204): trocar de papel virou trocar de ponto
 * de vista, sem sair de onde se está — quem troca de vendedor para gestor no meio do Radar
 * vê a mesma tela responder de outro jeito, que é exatamente a cena do roteiro.
 *
 * **Menu, e não `<select>` do navegador**: `010_DESIGN.md` §7 proíbe controle com
 * aparência padrão, e o menu ainda cabe a linha que diz o que cada papel faz — o texto que
 * morava na tela de entrada e não podia se perder.
 *
 * Na sidebar recolhida (769–1279 px) sobra o avatar; o nome do papel continua no DOM como
 * `sr-only`, porque um botão sem nome acessível é um botão que o leitor de tela anuncia
 * como "botão".
 */
function SeletorDePapel({
  papel,
  aoTrocar,
}: {
  papel: Papel
  aoTrocar: (papel: Papel) => void
}) {
  const [aberto, setAberto] = useState(false)
  const caixa = useRef<HTMLDivElement>(null)

  // Fecha ao clicar fora e no Esc. Sem isso o menu fica preso aberto por cima da
  // navegação, e o primeiro clique em outro item some em vez de navegar.
  useEffect(() => {
    if (!aberto) return
    function foraDaCaixa(evento: MouseEvent) {
      if (!caixa.current?.contains(evento.target as Node)) setAberto(false)
    }
    function noEsc(evento: KeyboardEvent) {
      if (evento.key === 'Escape') setAberto(false)
    }
    document.addEventListener('mousedown', foraDaCaixa)
    document.addEventListener('keydown', noEsc)
    return () => {
      document.removeEventListener('mousedown', foraDaCaixa)
      document.removeEventListener('keydown', noEsc)
    }
  }, [aberto])

  return (
    <div ref={caixa} className="relative border-t border-borda p-3">
      {aberto ? (
        <ul
          role="menu"
          aria-label="trocar de papel"
          data-testid="lista-de-papeis"
          className={[
            'absolute bottom-full left-3 right-3 mb-2 overflow-hidden rounded-cartao',
            'border border-borda bg-superficie shadow-flutuante',
            'max-xl:left-2 max-xl:right-auto max-xl:w-64',
          ].join(' ')}
        >
          {PAPEIS.map((opcao) => (
            <li key={opcao} role="none">
              <button
                type="button"
                role="menuitemradio"
                aria-checked={opcao === papel}
                data-testid={`papel-${opcao}`}
                onClick={() => {
                  setAberto(false)
                  aoTrocar(opcao)
                }}
                className={[
                  'flex w-full items-start gap-2.5 px-3 py-2.5 text-left',
                  'transition-colors duration-150 ease-out hover:bg-superficie-2',
                  opcao === papel ? 'bg-marca-50' : '',
                ].join(' ')}
              >
                <Check
                  size={16}
                  aria-hidden="true"
                  className={[
                    'mt-0.5 shrink-0',
                    opcao === papel ? 'text-marca-700' : 'invisible',
                  ].join(' ')}
                />
                <span className="min-w-0">
                  <span
                    className={[
                      'block truncate text-corpo',
                      opcao === papel ? 'font-medium text-marca-700' : 'text-tinta',
                    ].join(' ')}
                  >
                    {NOME_DO_PAPEL[opcao]}
                  </span>
                  <span className="block text-meta text-tinta-2">{O_QUE_FAZ[opcao]}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <button
        type="button"
        data-testid="trocar-papel"
        aria-haspopup="menu"
        aria-expanded={aberto}
        onClick={() => setAberto((a) => !a)}
        title={`papel: ${NOME_DO_PAPEL[papel]}. trocar papel`}
        className={[
          'flex h-11 w-full items-center gap-2.5 rounded-controle px-1 text-left',
          'transition-colors duration-150 ease-out hover:bg-superficie-2',
          'justify-center xl:justify-start xl:px-2',
        ].join(' ')}
      >
        <span
          aria-hidden="true"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-superficie-2 text-rotulo font-semibold uppercase text-tinta-2"
        >
          {papel.charAt(0)}
        </span>
        <span className="min-w-0 flex-1 max-xl:sr-only">
          <span
            data-testid="papel-atual"
            className="block truncate text-rotulo font-medium capitalize text-tinta"
          >
            {papel}
          </span>
          <span className="block truncate text-meta text-tinta-3">trocar papel</span>
        </span>
        <CaretDown size={14} aria-hidden="true" className="shrink-0 text-tinta-3 max-xl:sr-only" />
      </button>
    </div>
  )
}

/**
 * O rodapé de tudo: o logo da Ford e a linha do desafio.
 *
 * **De onde vem, e a ressalva.** `design-kit/020_BRIEF_PRODUTO.md` pede para não usar
 * logo da Ford dentro do produto; a instrução de 12/09/2026 pediu o contrário, e por
 * escrito. A instrução é posterior e do dono do produto, então o logo está aqui — uma vez
 * só, no rodapé, em 20 px de altura, sem competir com nada. O registro fica em
 * `DECISOES_NOITE.md` D-213 e em `web/public/img/CREDITOS.md`.
 *
 * Na sidebar recolhida (769–1279 px) sobra só o logo; a frase continua no DOM como
 * `sr-only`, porque ela é o que dá sentido ao símbolo.
 */
function AssinaturaDoDesafio() {
  return (
    <div className="flex items-center gap-2.5 border-t border-borda px-3 py-3 max-xl:justify-center">
      <img
        src={`${import.meta.env.BASE_URL}img/marca/ford.svg`}
        alt="Ford"
        width={40}
        height={15}
        className="shrink-0 opacity-80"
      />
      <span className="text-meta leading-tight text-tinta-3 max-xl:sr-only">
        Ford Challenge FIAP 2026
      </span>
    </div>
  )
}

export function Layout() {
  const { pathname } = useLocation()
  const naoLidos = useNaoLidos()
  const pagina = paginaDoCaminho(pathname)
  const [barraDeAcoes, setBarraDeAcoes] = useState<HTMLElement | null>(null)
  const [maisAberto, setMaisAberto] = useState(false)

  // Quem está olhando vem do navegador, não de `/auth/me`: a resposta do servidor seria
  // o eco do papel que acabamos de mandar em `X-Role`, e custaria uma chamada por tela.
  const papel = usePapel()
  const cache = useQueryClient()

  /**
   * Trocar de papel **esquece o que o papel anterior viu**.
   *
   * Sem `cache.clear()`, o React Query guardava as respostas do papel de saída, e a
   * página é a mesma — não há recarregamento entre um papel e o seguinte. Medido em
   * 11/09/2026: analista abre o Radar, troca para vendedor, abre o Radar e **vê a fila
   * inteira do analista**, sete alertas, no lugar do cartão de recusa (QA-BUG-16).
   *
   * Continua valendo, e por um motivo a mais: agora quem recorta por papel é a própria
   * tela, então um cache não limpo mostraria dado do papel errado sem nem uma chamada de
   * rede para desmenti-lo.
   */
  function trocarDePapel(novo: Papel) {
    definirPapel(novo)
    cache.clear()
  }

  const naBarraInferior = useMemo(
    () => PAGINAS.filter((p) => NO_CELULAR.includes(p.para)),
    [],
  )
  const noMenuMais = useMemo(() => PAGINAS.filter((p) => !NO_CELULAR.includes(p.para)), [])

  return (
    <div className="min-h-screen bg-canvas">
      <a href="#conteudo" className="pular-para-conteudo">
        pular para o conteúdo
      </a>

      {/* ------------------------------------------------------------------ sidebar
          `hidden md:flex`: em ≤ 768 px ela não existe, e a navegação é a barra inferior.
          A largura troca em `xl` — entre 769 e 1279 px ela fica em 64 px e só com ícones,
          que é o que deixa a matriz de 17 colunas respirar num notebook. */}
      <aside
        aria-label="seções"
        data-testid="barra-lateral"
        className={[
          'fixed inset-y-0 left-0 z-sidebar hidden flex-col border-r border-borda bg-superficie',
          'md:flex md:w-sidebar-recolhida xl:w-sidebar',
        ].join(' ')}
      >
        <Wordmark />
        <nav className="flex-1 overflow-y-auto px-3 py-2">
          <ul className="space-y-1">
            {PAGINAS.map((rota) => (
              <li key={rota.para}>
                <ItemDeNavegacao
                  para={rota.para}
                  rotulo={rota.aba}
                  contador={rota.contador ? naoLidos : null}
                />
              </li>
            ))}
          </ul>
        </nav>
        <SeletorDePapel papel={papel} aoTrocar={trocarDePapel} />
        <AssinaturaDoDesafio />
      </aside>

      {/* ------------------------------------------------------------------ conteúdo */}
      <div className="md:pl-sidebar-recolhida xl:pl-sidebar">
        <header
          data-testid="barra-superior"
          className={[
            'sticky top-0 z-barra flex h-barra items-center justify-between gap-3',
            'border-b border-borda bg-superficie px-4 md:px-8',
          ].join(' ')}
        >
          <div className="flex min-w-0 items-center gap-2">
            <span
              aria-hidden="true"
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px] bg-marca-950 text-meta font-bold text-white md:hidden"
            >
              S
            </span>
            <span className="truncate text-rotulo font-medium text-tinta-2">
              {pagina.titulo}
            </span>
          </div>
          <div ref={setBarraDeAcoes} className="flex shrink-0 items-center gap-2" />
        </header>

        <DestinoDasAcoes.Provider value={barraDeAcoes}>
          <main
            id="conteudo"
            className="mx-auto max-w-conteudo px-4 pb-24 pt-6 md:px-8 md:pb-12 md:pt-8"
          >
            {/* `key={pathname}`: sem ela o React reaproveita o nó e a animação não
                reinicia — a segunda troca de tela não teria fade nenhum. */}
            <div key={pathname} className="rota-entra">
              <div className="mb-6" data-testid="cabecalho-da-pagina">
                <h1 className="text-pagina text-tinta">{pagina.titulo}</h1>
                <p className="mt-1.5 text-corpo text-tinta-2">{pagina.descricao}</p>
              </div>
              <Outlet />
            </div>

            {/* A assinatura do desafio saiu daqui: ela mora no rodapé da barra lateral,
                ao lado do logo, e repetida em duas beiradas da mesma tela virava ruído.
                O que fica é a regra do produto, que é o que a pessoa precisa poder citar. */}
            <footer className="mt-12 border-t border-borda pt-6 text-meta text-tinta-3">
              Dados oficiais das montadoras, com data de coleta em cada campo. Nenhum valor
              é exibido sem etiqueta.
            </footer>
          </main>
        </DestinoDasAcoes.Provider>
      </div>

      {/* ----------------------------------------------------------- barra inferior
          Só em ≤ 768 px. Cinco alvos de 44 px: quatro telas e "mais". */}
      <nav
        aria-label="seções (celular)"
        data-testid="barra-inferior"
        // `pb-[env(safe-area-inset-bottom)]`: no iPhone, a barra de gestos do sistema come
        // os últimos ~34 px da tela, e sem isso o alvo de "Showroom" fica meio embaixo dela.
        className="fixed inset-x-0 bottom-0 z-sidebar border-t border-borda bg-superficie pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        <ul className="flex items-stretch">
          {naBarraInferior.map((rota) => {
            const Icone = ICONE_DA_PAGINA[rota.para]
            return (
              <li key={rota.para} className="flex-1">
                <NavLink
                  to={rota.para}
                  className={({ isActive }) =>
                    [
                      'relative flex min-h-[56px] flex-col items-center justify-center gap-0.5',
                      'text-meta transition-colors duration-150 ease-out',
                      isActive ? 'text-marca-700' : 'text-tinta-3',
                    ].join(' ')
                  }
                >
                  {Icone ? <Icone size={20} aria-hidden="true" /> : null}
                  {rota.aba}
                  {rota.contador && naoLidos !== null ? (
                    <span
                      aria-label={`${naoLidos} alerta(s) nao lido(s)`}
                      className="mono absolute right-[22%] top-1.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-marca-600 px-1 text-[10px] font-semibold text-white"
                    >
                      {naoLidos}
                    </span>
                  ) : null}
                </NavLink>
              </li>
            )
          })}
          <li className="flex-1">
            <button
              type="button"
              aria-expanded={maisAberto}
              onClick={() => setMaisAberto((a) => !a)}
              className="flex min-h-[56px] w-full flex-col items-center justify-center gap-0.5 text-meta text-tinta-3"
            >
              <User size={20} aria-hidden="true" />
              mais
            </button>
          </li>
        </ul>

        {maisAberto ? (
          <div data-testid="menu-mais" className="border-t border-borda px-3 py-2">
            <ul className="space-y-1">
              {noMenuMais.map((rota) => (
                <li key={rota.para}>
                  <NavLink
                    to={rota.para}
                    onClick={() => setMaisAberto(false)}
                    className={({ isActive }) =>
                      [
                        'flex min-h-[44px] items-center gap-3 rounded-controle px-3 text-corpo',
                        isActive ? 'bg-marca-50 font-medium text-marca-700' : 'text-tinta-2',
                      ].join(' ')
                    }
                  >
                    {rota.aba}
                  </NavLink>
                </li>
              ))}
              {/* No celular o papel é um bloco de opções, não um menu: um popover
                  sobre a barra inferior cobriria a navegação inteira em 390 px. */}
              <li className="border-t border-borda pt-2">
                <p className="px-3 pb-1 text-meta font-semibold uppercase tracking-[0.06em] text-tinta-3">
                  quem está olhando
                </p>
                <ul>
                  {PAPEIS.map((opcao) => (
                    <li key={opcao}>
                      <button
                        type="button"
                        data-testid={`papel-celular-${opcao}`}
                        aria-current={opcao === papel ? 'true' : undefined}
                        onClick={() => {
                          setMaisAberto(false)
                          trocarDePapel(opcao)
                        }}
                        className={[
                          'flex min-h-[44px] w-full items-center gap-3 rounded-controle px-3 text-corpo',
                          opcao === papel
                            ? 'bg-marca-50 font-medium text-marca-700'
                            : 'text-tinta-2',
                        ].join(' ')}
                      >
                        <Check
                          size={16}
                          aria-hidden="true"
                          className={opcao === papel ? '' : 'invisible'}
                        />
                        {NOME_DO_PAPEL[opcao]}
                      </button>
                    </li>
                  ))}
                </ul>
              </li>
            </ul>
          </div>
        ) : null}
      </nav>
    </div>
  )
}
