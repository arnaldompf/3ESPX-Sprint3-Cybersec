/**
 * A matriz de `docs/12` §6.6 do lado da tela — porque agora é a tela quem decide.
 *
 * **Por que ela existe aqui.** Até 11/09/2026 quem recusava era o servidor: o vendedor
 * pedia `/alerts`, tomava 403, e a tela transformava o 403 num cartão explicando de quem
 * era a tela. Sem autenticação (D-204) o servidor não recusa mais nada — ele lê `X-Role`
 * só para *filtrar* o que é por papel. Se a tela não soubesse a matriz, o vendedor
 * passaria a ver a fila do analista, que é justamente o defeito que QA-BUG-16 pegou.
 *
 * **O que ela não é.** Não é segurança, e nada aqui finge ser. É a mesma decisão de
 * produto de sempre — "esta tela é do analista" — aplicada onde ela sempre foi visível:
 * na tela. Com `AUTH_ENABLED=1` o servidor volta a recusar e as duas camadas concordam,
 * porque são transcrição da mesma tabela.
 *
 * **Por que transcrita e não buscada da API.** Uma chamada a mais no carregamento de cada
 * tela, para uma tabela de doze linhas que muda junto com `docs/12`, não se paga. O que
 * se paga é um teste: `tests/api/test_matriz_da_tela.py` lê este literal e o compara com
 * `api/app/permissions.py`, ação por ação e escopo por escopo. Duas cópias da mesma tabela
 * divergem; esta não pode divergir em silêncio.
 */

import type { Papel } from './papel'

/** As ações que a matriz nomeia. Uma linha da tabela de `docs/12` §6.6 cada. */
export type Acao =
  | 'consultar_fichas'
  | 'criar_sessao_showroom'
  | 'criar_extracoes'
  | 'ver_alertas'
  | 'ver_evidencias_brutas'
  | 'ver_insights'
  | 'aprovar_argumentos'
  | 'gerir_referencia_interna'
  | 'gerir_equivalencias'
  | 'publicar'
  | 'gerir_usuarios'
  | 'gerir_fontes'

/** Quanto de uma ação o papel alcança. */
export type Escopo = 'nenhum' | 'proprios' | 'todos'

/**
 * Ação → papel → escopo. Papel ausente numa ação significa `nenhum`: negar por omissão é
 * o único default que não surpreende.
 *
 * `ver_insights` é o caso interessante, e o motivo de o escopo não ser um booleano: o
 * vendedor vê **as próprias** sessões. Tratar "só as minhas" como "pode ver" mostraria a
 * taxa de fechamento do colega.
 */
export const MATRIZ: Record<Acao, Partial<Record<Papel, Escopo>>> = {
  consultar_fichas: { vendedor: 'todos', analista: 'todos', gestor: 'todos', admin: 'todos' },
  criar_sessao_showroom: { vendedor: 'todos', gestor: 'todos', admin: 'todos' },
  criar_extracoes: { analista: 'todos', gestor: 'todos', admin: 'todos' },
  ver_alertas: { analista: 'todos', gestor: 'todos', admin: 'todos' },
  ver_evidencias_brutas: { analista: 'todos', gestor: 'todos', admin: 'todos' },
  ver_insights: { vendedor: 'proprios', analista: 'todos', gestor: 'todos', admin: 'todos' },
  aprovar_argumentos: { gestor: 'todos', admin: 'todos' },
  gerir_referencia_interna: { gestor: 'todos', admin: 'todos' },
  gerir_equivalencias: { gestor: 'todos', admin: 'todos' },
  publicar: { gestor: 'todos', admin: 'todos' },
  gerir_usuarios: { admin: 'todos' },
  gerir_fontes: { admin: 'todos' },
}

/** O alcance deste papel nesta ação. */
export function escopoDe(papel: Papel, acao: Acao): Escopo {
  return MATRIZ[acao][papel] ?? 'nenhum'
}

/**
 * Este papel alcança esta ação de alguma forma?
 *
 * Cuidado em listagem: `proprios` também responde `true` aqui, e quem lista tem de dizer
 * que está vendo um recorte. Para saber *quanto*, use `escopoDe`.
 */
export function pode(papel: Papel, acao: Acao): boolean {
  return escopoDe(papel, acao) !== 'nenhum'
}

const NOME_NA_FRASE: Record<Papel, string> = {
  vendedor: 'vendedor',
  analista: 'analista',
  gestor: 'gestor',
  admin: 'administrador',
}

function emPortugues(quais: readonly Papel[]): string {
  const nomes = quais.map((p) => NOME_NA_FRASE[p])
  const ultimo = nomes.pop()
  if (ultimo === undefined) return 'ninguém'
  if (nomes.length === 0) return ultimo
  return `${nomes.join(', ')} e ${ultimo}`
}

/**
 * Quem alcança a ação, por extenso e em português — "analista, gestor e administrador".
 *
 * É o texto do cartão de recusa. Escrito aqui, e não em cada tela, porque três telas
 * mostravam a mesma frase e uma delas já divergiu.
 *
 * `escopo` restringe a quem alcança **daquele jeito**. `papeisQuePodem('ver_insights')`
 * inclui o vendedor, que vê só as próprias sessões; `papeisQuePodem('ver_insights',
 * 'todos')` é quem vê o agregado da concessionária, e é essa a frase do cartão "Resumo".
 */
export function papeisQuePodem(acao: Acao, escopo?: Escopo): string {
  const quais = (Object.keys(MATRIZ[acao]) as Papel[]).filter(
    (papel) => escopo === undefined || escopoDe(papel, acao) === escopo,
  )
  return emPortugues(quais)
}

/**
 * A tela do Radar e a da Saúde são **internas**: o vendedor não entra nelas.
 *
 * `ver_alertas` cobre o Radar. A Saúde do Conhecimento não tem ação própria na matriz —
 * é leitura de dado interno da Ford, e D-103 decidiu que ela é de analista para cima;
 * `ver_evidencias_brutas` é a linha que expressa isso, porque é exatamente a evidência
 * crua que a tela mostra.
 */
export const ACAO_DA_TELA = {
  radar: 'ver_alertas',
  saude: 'ver_evidencias_brutas',
  insights: 'ver_insights',
  showroom: 'criar_sessao_showroom',
  // A Pesquisa (WP-42) sai para a internet e gasta chamada de modelo: é a mesma ação de
  // disparar uma extração, e o vendedor não a tem.
  pesquisa: 'criar_extracoes',
} as const satisfies Record<string, Acao>
