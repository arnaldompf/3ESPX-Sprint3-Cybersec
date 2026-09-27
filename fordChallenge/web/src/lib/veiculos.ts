/**
 * Como um veículo se chama na tela, e qual vem escolhido quando a tela abre.
 *
 * **O nome.** O rótulo é `marca + modelo + versão`. Quando o catálogo guarda a versão com o
 * modelo dentro do nome, sai "Chevrolet S10 S10 High Country". A migração `0006` resolve
 * isso na origem; esta função é o cinto de segurança para um banco que ainda não migrou —
 * e é barata: compara tokens, não adivinha nada.
 *
 * **O padrão.** Os seletores abriam em `lista[0]`, que é a primeira em ordem alfabética.
 * No catálogo real isso dava a S10 "High Country" **sem ficha nenhuma**, e o Simulador
 * abria com um painel de cenário sem preço — a tela mostrava um defeito que não existia.
 * A regra passa a ser: abrir numa versão que **tem ficha**, e as preferidas estão
 * declaradas aqui, por nome, uma lista por tela. Não havendo nenhuma delas no banco, cai
 * para a primeira da lista, que é o comportamento antigo.
 */

import type { Veiculo } from './tipos'

/** Minúsculas, sem acento, espaços colapsados. A mesma ideia do `normalize` do back-end. */
function normalizar(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * O nome da versão sem o modelo repetido no começo.
 *
 * Token a token, e não `startsWith`: "S10X Sport" começa com as letras de "S10" e não é
 * uma S10 — cortar por prefixo de texto inventaria a versão "X Sport".
 */
export function versaoSemOModelo(modelo: string, versao: string): string {
  const tokensModelo = normalizar(modelo).split(' ').filter(Boolean)
  const palavras = versao.trim().split(/\s+/).filter(Boolean)
  if (tokensModelo.length === 0 || palavras.length <= tokensModelo.length) return versao.trim()
  const inicio = palavras.slice(0, tokensModelo.length).map(normalizar)
  if (inicio.join(' ') !== tokensModelo.join(' ')) return versao.trim()
  return palavras.slice(tokensModelo.length).join(' ')
}

/** "Ford Ranger Limited 3.0 V6 Diesel 4WD AT". Sem repetir o modelo. */
export function nomeDoVeiculo(veiculo: Pick<Veiculo, 'marca' | 'modelo' | 'versao'>): string {
  return [veiculo.marca, veiculo.modelo, versaoSemOModelo(veiculo.modelo, veiculo.versao)]
    .filter(Boolean)
    .join(' ')
}

/**
 * A versão que o resolvedor casou vai para o **primeiro** lugar da lista.
 *
 * A tela pede uma versão, o resolvedor responde `matched_version`, e a lista abaixo do
 * cartão "Versão encontrada" é a de **todas** as versões daquele modelo — para trocar sem
 * digitar de novo. Ordenadas pelo catálogo, a casada caía no meio: pedindo a Raptor, o
 * primeiro botão era a Limited, e quem clica no primeiro abre a ficha errada. Era assim
 * que a cena 2 do roteiro chegava à ficha (QA-BUG-02).
 *
 * Compara pelo nome normalizado, e também pelo nome sem o modelo repetido na frente —
 * `matched_version` vem como "Raptor 3.0 V6 Bi-turbo 4WD AT" e o catálogo pode guardar
 * "Ranger Raptor 3.0 V6 Bi-turbo 4WD AT". Sem casar nada, a ordem fica como estava.
 */
export function casadaPrimeiro<T extends Pick<Veiculo, 'modelo' | 'versao'>>(
  veiculos: readonly T[],
  matchedVersion: string | null | undefined,
): T[] {
  const alvo = normalizar(matchedVersion ?? '')
  if (!alvo) return [...veiculos]
  const casa = (v: T) =>
    normalizar(v.versao) === alvo || normalizar(versaoSemOModelo(v.modelo, v.versao)) === alvo
  const casadas = veiculos.filter(casa)
  if (casadas.length === 0) return [...veiculos]
  return [...casadas, ...veiculos.filter((v) => !casa(v))]
}

/** "Ranger Limited 3.0 V6 Diesel 4WD AT": sem a marca, para listas de uma marca só. */
export function nomeCurto(veiculo: Pick<Veiculo, 'modelo' | 'versao'>): string {
  return [veiculo.modelo, versaoSemOModelo(veiculo.modelo, veiculo.versao)].filter(Boolean).join(' ')
}

/** Um veículo preferido, escrito como o catálogo o nomeia. */
export interface Preferida {
  readonly marca: string
  readonly modelo: string
  readonly versao: string
}

/**
 * As cinco versões com ficha coletada (`scripts/demo/preparar_base.py`).
 *
 * Elas estão aqui por nome porque `/vehicles` não diz quantos campos cada versão tem, e
 * inventar uma rota para isso mudaria a API — o que esta rodada não faz. Uma versão que
 * saia desta lista continua funcionando: a tela cai para a primeira do catálogo.
 */
export const FORD_DIESEL_DE_TOPO: Preferida = {
  marca: 'Ford',
  modelo: 'Ranger',
  versao: 'Limited 3.0 V6 Diesel 4WD AT',
}
export const FORD_RAPTOR: Preferida = {
  marca: 'Ford',
  modelo: 'Ranger',
  versao: 'Raptor 3.0 V6 Bi-turbo 4WD AT',
}
export const HILUX: Preferida = { marca: 'Toyota', modelo: 'Hilux', versao: 'SRX Plus AT' }
export const AMAROK: Preferida = { marca: 'Volkswagen', modelo: 'Amarok', versao: 'V6 Extreme' }
export const S10: Preferida = { marca: 'Chevrolet', modelo: 'S10', versao: 'High Country' }

/** Ford da comparação: a diesel de topo, que é a que tem par entre as picapes de trabalho. */
export const PADRAO_FORD: readonly Preferida[] = [FORD_DIESEL_DE_TOPO, FORD_RAPTOR]
/**
 * Concorrente do **Showroom**: a Hilux, o par declarado em `docs/12` §6.1 e na cena 8.
 *
 * Lá a ausência de preço da Hilux é parte do que a tela mostra ("este veículo não tem
 * preço verificado"), e não um defeito a contornar.
 */
export const PADRAO_CONCORRENTE: readonly Preferida[] = [HILUX, AMAROK, S10]

/**
 * Concorrente do **Simulador**: a Amarok V6 Extreme. Diferente do Showroom, e agora de
 * propósito (D-208).
 *
 * A instrução de `design-kit/000_LEIA_PRIMEIRO.md` §2.1 era "Simulador = mesmo par do
 * Showroom", e D-198 e D-202 mantiveram a Hilux por isso — a segunda vez revertendo uma
 * troca feita durante o ensaio de QA. O que mudou não foi a opinião sobre o par: foi a
 * instrução. O par do Simulador passa a ser **Ranger Limited × Amarok V6 Extreme porque
 * os dois têm `preco_sugerido_brl`**, e sem preço dos dois lados a pergunta da tela ("e se
 * o concorrente baixar 5%?") não tem sobre o que incidir.
 *
 * O que isso conserta, medido: a tela abria com "Sem cenário para este par" e um **422 no
 * console** a cada carregamento (QA-24), porque a primeira consulta pedia variação
 * percentual sobre um valor que não existe. E a cena 10 do roteiro exigia que o
 * apresentador trocasse o concorrente à mão, ao vivo, para a cena acontecer.
 *
 * Como reverter: apagar esta constante e voltar a `PADRAO_CONCORRENTE` no `Simulador.tsx`.
 */
export const PADRAO_DO_SIMULADOR: readonly Preferida[] = [AMAROK, S10, HILUX]

/** Matriz: os três concorrentes com ficha, que é o que enche a tabela de verdade. */
export const PADRAO_DA_MATRIZ: readonly Preferida[] = [HILUX, AMAROK, S10]

function mesmaVersao(veiculo: Veiculo, preferida: Preferida): boolean {
  return (
    normalizar(veiculo.marca) === normalizar(preferida.marca) &&
    normalizar(veiculo.modelo) === normalizar(preferida.modelo) &&
    normalizar(versaoSemOModelo(veiculo.modelo, veiculo.versao)) ===
      normalizar(versaoSemOModelo(preferida.modelo, preferida.versao))
  )
}

/**
 * O id da primeira preferida que existir no catálogo; senão, o primeiro da lista.
 *
 * `""` quando a lista está vazia — a tela ainda está carregando, e uma consulta com id
 * vazio não é disparada (todas as chamadas ficam atrás de `enabled`).
 */
export function escolherPadrao(lista: readonly Veiculo[], preferidas: readonly Preferida[]): string {
  for (const preferida of preferidas) {
    const achado = lista.find((veiculo) => mesmaVersao(veiculo, preferida))
    if (achado) return achado.id
  }
  return lista[0]?.id ?? ''
}

/**
 * Os ids das preferidas que existem, na ordem em que foram pedidas, completando com o
 * começo da lista até `quantidade`.
 */
export function escolherPadroes(
  lista: readonly Veiculo[],
  preferidas: readonly Preferida[],
  quantidade: number,
): string[] {
  const escolhidos: string[] = []
  for (const preferida of preferidas) {
    const achado = lista.find((veiculo) => mesmaVersao(veiculo, preferida))
    if (achado && !escolhidos.includes(achado.id)) escolhidos.push(achado.id)
  }
  for (const veiculo of lista) {
    if (escolhidos.length >= quantidade) break
    if (!escolhidos.includes(veiculo.id)) escolhidos.push(veiculo.id)
  }
  return escolhidos.slice(0, quantidade)
}
