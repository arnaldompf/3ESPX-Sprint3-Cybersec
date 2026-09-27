/**
 * A regra visual mais importante do produto: **nenhum número sem etiqueta**.
 *
 * `docs/13` §2 define quatro. **Três qualificam um VALOR** — FATO, INFERÊNCIA e
 * SIMULAÇÃO — e a quarta, SEM DADO, marca a **ausência** de valor. O mapeamento é aqui,
 * num lugar só, porque é a decisão que sustenta a promessa do produto — e uma tela que
 * decidisse isso componente a componente acabaria com dois campos iguais exibindo
 * etiquetas diferentes.
 *
 * O mapa, em ordem de precedência:
 *
 * | condição | etiqueta | por quê |
 * |---|---|---|
 * | **`value` vazio** | **SEM DADO** | **vence tudo**: ausência não é afirmação sobre nada |
 * | (`is_simulated`) | SIMULAÇÃO | vence o status: dado de demonstração |
 * | `origem: "catalogo"` | CATÁLOGO | identidade da versão, vinda do nosso cadastro |
 * | `verificado` | FATO | valor com evidência localizada na fonte |
 * | `divergente` | FATO | **os dois** valores têm evidência; o que falta é concordância, não prova |
 * | `nao_disponivel` | FATO | é fato **negativo**: a fonte afirma que o item não existe |
 * | `nao_encontrado` | INFERÊNCIA | ninguém afirmou nada; a ausência é nossa leitura das fontes |
 * | `nao_verificado` | INFERÊNCIA | há valor sem evidência confirmada, ou ninguém procurou |
 * | `pendente` | INFERÊNCIA | coleta em andamento |
 *
 * **Por que o vazio vence tudo** (12/09/2026). Antes, o mapa olhava só o status, e a tela
 * imprimia literalmente "sem valor" ao lado de um pill azul INFERÊNCIA — como se houvesse
 * uma leitura nossa onde não há leitura nenhuma. Pior: um campo `nao_disponivel` sem valor
 * caía em FATO e saía **verde**, e vazio pintado de verde é a leitura mais perigosa
 * possível para quem está num showroom com o cliente ao lado. `nao_disponivel` continua
 * sendo fato negativo — o que ele não é, é um valor.
 *
 * E por que o vazio vence até `is_simulated`: pintar de laranja "SIMULAÇÃO" um campo sem
 * valor repete o mesmo erro de categoria, só com outra cor. A simulação seria de quê?
 *
 * `divergente` como FATO é a escolha menos óbvia da tabela, e a mais deliberada. A tela
 * mostra os dois valores com as duas evidências: chamar isso de inferência sugeriria que
 * o sistema deduziu algo, quando na verdade duas fontes oficiais discordam — e é o
 * usuário que decide.
 */

import type { Campo, Etiqueta, Status } from './tipos'

const POR_STATUS: Record<Status, Etiqueta> = {
  verificado: 'FATO',
  divergente: 'FATO',
  nao_disponivel: 'FATO',
  nao_encontrado: 'INFERENCIA',
  nao_verificado: 'INFERENCIA',
  pendente: 'INFERENCIA',
}

/**
 * A etiqueta de um campo. **Sem valor vence o status e a simulação**; depois disso,
 * `is_simulated` vence o status.
 *
 * `0` e `''` são valores, não ausências: capacidade de reboque de 0 kg é uma afirmação
 * sobre o veículo, e apagá-la seria inventar um vazio que a fonte não declarou.
 */
export function etiquetaDe(
  campo: Pick<Campo, 'status' | 'is_simulated' | 'value' | 'origem'>,
): Etiqueta {
  if (campo.value === null || campo.value === undefined) return 'SEM_DADO'
  if (campo.is_simulated) return 'SIMULACAO'
  // O valor existe e é nosso: marca, modelo, versão, ano-modelo, código FIPE. Chamá-lo de
  // INFERÊNCIA seria mentir sobre o método (nada foi inferido) e chamá-lo de FATO seria
  // mentir sobre a prova (não há trecho verbatim). A saída honesta é nomear a procedência.
  if (campo.origem === 'catalogo') return 'CATALOGO'
  return POR_STATUS[campo.status] ?? 'INFERENCIA'
}

/** O texto que aparece na etiqueta. Com acento, que é como se lê em português. */
export const ROTULO: Record<Etiqueta, string> = {
  FATO: 'FATO',
  INFERENCIA: 'INFERÊNCIA',
  SIMULACAO: 'SIMULAÇÃO',
  SEM_DADO: 'SEM DADO',
  CATALOGO: 'CATÁLOGO',
}

/**
 * Ícone além da cor. Verde e laranja são o par mais comum de confusão em daltonismo, e a
 * etiqueta é a informação mais importante da tela — não pode depender de distinguir cor.
 */
export const ICONE: Record<Etiqueta, string> = {
  FATO: '✓',
  INFERENCIA: '≈',
  SIMULACAO: '⚠',
  // Travessão: distinto de ✓, ≈ e ⚠ também para quem lê por leitor de tela.
  SEM_DADO: '—',
  CATALOGO: '≡',
}

/** Explicação em uma frase, para o `title` e para o leitor de tela. */
export const EXPLICACAO: Record<Etiqueta, string> = {
  FATO: 'Valor com evidência: trecho verbatim localizado na fonte citada.',
  INFERENCIA: 'Leitura nossa das fontes, sem afirmação direta delas. Confira antes de usar.',
  SIMULACAO: 'Dado de demonstração. Não é informação sobre veículo real.',
  SEM_DADO: 'Campo sem valor. A ausência tem motivo, e o motivo está ao lado.',
  CATALOGO:
    'Identidade da versão que você consultou, vinda do nosso cadastro. Não foi lida de uma página do fabricante.',
}

/**
 * As classes Tailwind de cada etiqueta. Ficam aqui para o `Badge` só compor.
 *
 * Fundo suave e **sem borda** (`010_DESIGN.md` §5): a borda de 1 px em volta de um pill de
 * 22 px engrossa o contorno e é metade do que fazia a v1 parecer de 2012. O que separa a
 * etiqueta do fundo branco é a cor da superfície, não um traço.
 */
export const CLASSES: Record<Etiqueta, string> = {
  FATO: 'bg-fato-fundo text-fato',
  INFERENCIA: 'bg-inferencia-fundo text-inferencia',
  SIMULACAO: 'bg-simulacao-fundo text-simulacao',
  SEM_DADO: 'bg-semdado-fundo text-semdado',
  CATALOGO: 'bg-catalogo-fundo text-catalogo',
}

/** A cor do ponto de 6 px à esquerda do texto, dentro do pill. */
export const COR_DO_PONTO: Record<Etiqueta, string> = {
  FATO: 'bg-fato',
  INFERENCIA: 'bg-inferencia',
  SIMULACAO: 'bg-simulacao',
  SEM_DADO: 'bg-semdado',
  CATALOGO: 'bg-catalogo',
}

/** O rótulo humano de cada status, para a linha do campo. */
export const ROTULO_DE_STATUS: Record<Status, string> = {
  verificado: 'verificado',
  nao_verificado: 'não verificado',
  nao_disponivel: 'não disponível nesta versão',
  nao_encontrado: 'não encontrado nas fontes',
  divergente: 'fontes divergem',
  pendente: 'coleta pendente',
}

/**
 * Os dois vazios **não** se confundem, e a frase de cada um diz por quê.
 *
 * `nao_disponivel` é a fonte afirmando que o item não existe naquela versão.
 * `nao_encontrado` é ninguém ter dito nada. Exibir "—" nos dois casos apagaria a
 * distinção que o schema canônico existe para manter.
 */
export function explicacaoDoVazio(status: Status, fontes: string[]): string {
  if (status === 'nao_disponivel') {
    return 'A fonte oficial afirma que esta versão não tem este item.'
  }
  if (status === 'nao_encontrado') {
    const n = fontes.length
    return n > 0
      ? `Nenhuma das ${n} fonte(s) consultada(s) menciona este campo.`
      : 'Nenhuma fonte consultada menciona este campo.'
  }
  if (status === 'pendente') return 'Coleta em andamento.'
  return 'Sem valor confirmado.'
}
