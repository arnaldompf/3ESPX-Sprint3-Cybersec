/**
 * Aba, título e descrição de cada tela, num lugar só.
 *
 * Por que uma fonte única, e por que o **Layout** é quem desenha o cabeçalho:
 *
 * cada página tem retornos antecipados — carregando, erro, sem permissão, sem dado. Se o
 * título morasse dentro delas, ele apareceria no caminho feliz e sumiria justamente nos
 * outros, que é quando a pessoa mais precisa saber onde está. Desenhado pelo Layout,
 * acima do `<Outlet />`, o título **não depende do estado da página**: uma tela que falhou
 * continua dizendo o que é, e é isso que "nunca uma tela em branco" significa.
 *
 * A mesma tabela alimenta a barra de navegação, então aba e cabeçalho não podem divergir.
 */

export interface Pagina {
  /** Caminho do React Router (sem o `basename`). */
  readonly para: string
  /** O texto da aba. Curto: a barra cabe em 390 px. */
  readonly aba: string
  /** O `<h1>` da tela. */
  readonly titulo: string
  /** Uma linha dizendo para que serve. Aparece sempre, com dado ou sem. */
  readonly descricao: string
  /** Mostra o contador de alertas não lidos (só o Radar). */
  readonly contador?: boolean
}

/** As abas, na ordem do passeio guiado de `docs/demo/ROTEIRO_15SET.md`. */
export const PAGINAS: readonly Pagina[] = [
  {
    para: '/consulta',
    aba: 'Consulta',
    titulo: 'Consulta',
    descricao:
      'Peça um veículo pelo nome e veja a ficha padronizada, com a evidência de cada campo.',
  },
  {
    para: '/radar',
    aba: 'Radar',
    contador: true,
    titulo: 'Radar competitivo',
    descricao:
      'A fila de alertas por materialidade: o que mudou no concorrente e o que isso muda aqui.',
  },
  {
    para: '/matriz',
    aba: 'Matriz',
    titulo: 'Matriz de paridade',
    descricao: 'Onde ganhamos, empatamos, perdemos, e onde ainda não sabemos.',
  },
  {
    para: '/benchmark',
    aba: 'Benchmark',
    titulo: 'Benchmark competitivo',
    descricao:
      'Contra quem esta Ford briga, quem já dá para comparar hoje e o que ainda falta procurar.',
  },
  {
    para: '/showroom',
    aba: 'Showroom',
    titulo: 'Showroom',
    descricao:
      'O perfil do cliente, a comparação e o argumentário, com o que o concorrente vence à vista.',
  },
  {
    para: '/saude',
    aba: 'Saúde',
    titulo: 'Saúde do conhecimento',
    descricao: 'Cobertura por montadora, evidência desatualizada e as divergências abertas.',
  },
  {
    para: '/insights',
    aba: 'Insights',
    titulo: 'Insights de win/loss',
    descricao: 'O que as conversas de showroom dizem sobre ganhar e perder venda.',
  },
  {
    para: '/simulador',
    aba: 'Simulador',
    titulo: 'Simulador de cenário',
    descricao: 'E se o concorrente baixar o preço? Hipótese sua, marcada como SIMULAÇÃO.',
  },
]

/** Telas que existem mas não têm aba (deep link, atalho, 404). */
const FORA_DA_BARRA: readonly Pagina[] = [
  {
    para: '/ficha',
    aba: 'Ficha',
    titulo: 'Ficha técnica',
    descricao: 'Cada campo com status, fonte, trecho citado e data de coleta.',
  },
  {
    para: '/copiloto',
    aba: 'Copiloto',
    titulo: 'Copiloto',
    descricao: 'O fluxo que os documentos chamam de Copiloto está no Showroom.',
  },
]

/** O cabeçalho de último caso: endereço que não é de nenhuma tela. */
export const PAGINA_DESCONHECIDA: Pagina = {
  para: '*',
  // Nunca desenhado: esta página não tem item na barra. O rótulo existe porque o tipo o
  // exige, e um travessão solto ali é anti-padrão §8 esperando alguém renderizá-lo.
  aba: 'Página não encontrada',
  titulo: 'Página não encontrada',
  descricao: 'Este endereço não existe nesta versão do app. Use a navegação acima.',
}

/**
 * A página de um caminho. Casa por prefixo para `/ficha/<id>` cair em `/ficha`.
 *
 * O prefixo é conferido com a barra (`/ficha/`) para que uma rota futura chamada
 * `/fichario` não herde o cabeçalho da ficha.
 */
export function paginaDoCaminho(caminho: string): Pagina {
  const todas = [...PAGINAS, ...FORA_DA_BARRA]
  const exata = todas.find((pagina) => pagina.para === caminho)
  if (exata) return exata
  const porPrefixo = todas.find((pagina) => caminho.startsWith(`${pagina.para}/`))
  return porPrefixo ?? PAGINA_DESCONHECIDA
}
