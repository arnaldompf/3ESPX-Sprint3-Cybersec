/**
 * Os ícones, num lugar só. **Phosphor Regular, nunca lucide** (`030_ANTI_PADROES.md` §2).
 *
 * Por que um módulo em vez de importar direto em cada tela: o conjunto fica fechado e
 * auditável. Um ícone só entra aqui quando **carrega significado** — o de "consulta" é a
 * lupa porque a ação é procurar; não há ícone decorativo ao lado de título, e não há
 * nenhuma estrelinha de IA em lugar nenhum.
 *
 * Todos são importados por nome, o que deixa o `tree-shaking` levar só estes para o
 * pacote: o `@phosphor-icons/react` inteiro tem alguns milhares de arquivos.
 *
 * Tamanho: 20 px na navegação, 16 px em linha. Peso `regular` em tudo — o traço único é o
 * que faz um conjunto de ícones parecer um conjunto.
 */

import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Binoculars,
  Broadcast,
  Check,
  ChartBar,
  CaretDown,
  CaretRight,
  ClipboardText,
  Copy,
  CurrencyCircleDollar,
  DotsSixVertical,
  DownloadSimple,
  Equals,
  FileText,
  Flag,
  Funnel,
  Gauge,
  Info,
  Link as LinkIcone,
  MagnifyingGlass,
  MinusCircle,
  PlusCircle,
  Prohibit,
  Question,
  SignOut,
  Sliders,
  Storefront,
  Table,
  TrendDown,
  TrendUp,
  User,
  Warning,
  Wrench,
  X,
} from '@phosphor-icons/react'

export {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Binoculars,
  Broadcast,
  Check,
  ChartBar,
  CaretDown,
  CaretRight,
  ClipboardText,
  Copy,
  CurrencyCircleDollar,
  DotsSixVertical,
  DownloadSimple,
  Equals,
  FileText,
  Flag,
  Funnel,
  Gauge,
  Info,
  LinkIcone,
  MagnifyingGlass,
  MinusCircle,
  PlusCircle,
  Prohibit,
  Question,
  SignOut,
  Sliders,
  Storefront,
  Table,
  TrendDown,
  TrendUp,
  User,
  Warning,
  Wrench,
  X,
}

/** O tipo de um ícone Phosphor, para as tabelas de navegação e de estado vazio. */
export type Icone = typeof MagnifyingGlass

/**
 * O ícone de cada tipo de alerta (`docs/12` §6.1).
 *
 * Até a v1 este mapa era de **emoji** — 💰, 🔧 e, pior, um ✨ para "versão nova". Emoji é
 * anti-padrão §6 e a estrelinha de IA é o §18: além de datar a tela, o desenho muda de
 * aparelho para aparelho e não herda a cor do texto. Phosphor Regular resolve os três
 * problemas de uma vez.
 */
export const ICONE_DO_ALERTA: Record<string, Icone> = {
  preco_oficial: CurrencyCircleDollar,
  preco_fipe: ChartBar,
  versao_nova: PlusCircle,
  versao_removida: MinusCircle,
  campo_alterado: Wrench,
  fonte_bloqueada: Prohibit,
  referencia_interna_divergente: Flag,
}

/** Os ícones da navegação lateral, na ordem do passeio guiado. */
export const ICONE_DA_PAGINA: Record<string, Icone> = {
  '/consulta': MagnifyingGlass,
  // A Pesquisa procura fora do catálogo: binóculo, e não lupa, para não se confundir com
  // a Consulta.
  '/pesquisa': Binoculars,
  '/radar': Broadcast,
  '/matriz': Table,
  '/showroom': Storefront,
  '/saude': Gauge,
  '/insights': ChartBar,
  '/simulador': Sliders,
  '/ficha': FileText,
}
