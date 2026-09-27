/**
 * O papel de quem está olhando — escolhido na barra lateral, guardado no navegador.
 *
 * Não há login nesta fase (D-204). A ferramenta abre direto na Consulta, e o papel deixou
 * de ser credencial: é **um ponto de vista**. Trocar de papel é trocar o que a tela
 * mostra, como trocar de aba — nada é autenticado, nada é negado pelo servidor.
 *
 * Três decisões:
 *
 * * **`localStorage`, não `sessionStorage`.** A escolha tem de sobreviver a fechar o
 *   navegador: quem abre a ferramenta de manhã não quer reescolher o papel todo dia. O
 *   argumento que justificava `sessionStorage` — o tablet compartilhado do showroom —
 *   valia para *token*, e não há mais token para vazar;
 * * **o papel viaja em `X-Role`**, num cabeçalho e não numa query string, para não entrar
 *   em log de proxy nem em link copiado;
 * * **quem muda avisa**. `assinar()` existe porque o React Query precisa esquecer o que o
 *   papel anterior viu — sem isso o vendedor herda a fila do analista, que foi um defeito
 *   real (QA-BUG-16).
 */

import { useSyncExternalStore } from 'react'

export type Papel = 'vendedor' | 'analista' | 'gestor' | 'admin'

/** Os quatro, na ordem em que a barra lateral os oferece. */
export const PAPEIS: readonly Papel[] = ['vendedor', 'analista', 'gestor', 'admin']

/** O que cada papel faz, em meia linha. É o texto da matriz de `docs/12` §6.6. */
export const O_QUE_FAZ: Record<Papel, string> = {
  vendedor: 'atende no salão e abre sessão de showroom',
  analista: 'confere evidência e resolve divergência',
  gestor: 'vê a matriz, o win/loss e o simulador',
  admin: 'tudo, mais os usuários',
}

/** Como o papel aparece escrito na tela. */
export const NOME_DO_PAPEL: Record<Papel, string> = {
  vendedor: 'Vendedor',
  analista: 'Analista',
  gestor: 'Gestor',
  admin: 'Admin',
}

const CHAVE = 'specradar.papel'

/**
 * O papel inicial é o **analista**.
 *
 * Não é "o mais poderoso", é o que faz a primeira tela ficar completa sem ninguém tocar no
 * seletor: a Consulta lista as versões com ficha, e essa lista mostra saúde do
 * conhecimento, que é dado interno e não é do vendedor (D-103). Abrindo como vendedor, a
 * primeira coisa que alguém vê ao abrir a ferramenta seria meia tela.
 *
 * É também por onde o roteiro começa (`docs/demo/ROTEIRO_15SET.md`, cenas 2 a 5: ficha,
 * evidência, divergência e Fogo Amigo são trabalho de analista), e o Showroom troca para
 * vendedor na cena 8 — com um clique na barra lateral, à vista de todos.
 *
 * Reverter é trocar esta constante.
 */
export const PAPEL_INICIAL: Papel = 'analista'

function ehPapel(valor: string | null): valor is Papel {
  return valor !== null && (PAPEIS as readonly string[]).includes(valor)
}

let emMemoria: Papel | null = null

/** O papel atual. Lê o navegador na primeira vez e guarda em memória depois. */
export function papelAtual(): Papel {
  if (emMemoria) return emMemoria
  try {
    const guardado = localStorage.getItem(CHAVE)
    emMemoria = ehPapel(guardado) ? guardado : PAPEL_INICIAL
  } catch {
    // Navegador com armazenamento bloqueado: o papel vive só nesta aba. Degradação
    // aceitável — a pessoa reescolhe ao recarregar.
    emMemoria = PAPEL_INICIAL
  }
  return emMemoria
}

const ouvintes = new Set<(papel: Papel) => void>()

/** Avisa quando o papel muda. Devolve a função que cancela a assinatura. */
export function assinar(ouvinte: (papel: Papel) => void): () => void {
  ouvintes.add(ouvinte)
  return () => {
    ouvintes.delete(ouvinte)
  }
}

/** Troca o papel, grava e avisa quem assinou. Trocar para o mesmo não faz nada. */
export function definirPapel(papel: Papel): void {
  if (papelAtual() === papel) return
  emMemoria = papel
  try {
    localStorage.setItem(CHAVE, papel)
  } catch {
    /* armazenamento bloqueado: vale só nesta aba */
  }
  for (const ouvinte of ouvintes) ouvinte(papel)
}

/** Só para teste: esquece o que está em memória e no navegador. */
export function esquecerPapel(): void {
  emMemoria = null
  try {
    localStorage.removeItem(CHAVE)
  } catch {
    /* nada a limpar */
  }
}

/** O cabeçalho que vai em toda chamada à API. O contrato está em `docs/04`. */
export const CABECALHO_PAPEL = 'X-Role'

/**
 * O papel atual, dentro de um componente — e re-renderiza quando ele muda.
 *
 * `useSyncExternalStore` e não um `useState` por tela: o papel vive fora do React (ele
 * sobrevive ao recarregamento), e sete telas com sete cópias do mesmo estado divergiriam
 * na primeira em que alguém esquecesse de assinar. Com a fonte única, trocar o papel na
 * barra lateral repinta a tela aberta no mesmo quadro.
 */
export function usePapel(): Papel {
  return useSyncExternalStore(assinar, papelAtual, () => PAPEL_INICIAL)
}
