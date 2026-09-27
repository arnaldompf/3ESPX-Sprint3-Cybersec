/**
 * O Pesquisador está ligado neste ambiente?
 *
 * **Por que uma bandeira, e não sempre ligado.** O Pesquisador sai para a internet e gasta
 * chamada de LLM. A demonstração de 15/09 tem de poder rodar sem nenhum dos dois — e o
 * `verify-quick`, o CI e o clone recém-feito também. Com `RESEARCH_ENABLED` desligado, a
 * API **não monta a rota** (não é uma rota que recusa: é uma rota que não existe), e a tela
 * não oferece um botão que levaria a 404.
 *
 * **Como o front sabe.** Pela própria API: `/health` diz o que está ligado. A alternativa
 * — uma variável de build no Vite — obrigaria a reconstruir o bundle para ligar o recurso,
 * e o bundle da demo é gerado antes de a máquina do dia estar configurada.
 *
 * A leitura é síncrona e otimista: o valor vem de um cache que `sincronizar()` preenche
 * quando o aplicativo sobe. Antes disso, o padrão é **desligado** — oferecer um botão que
 * não funciona é pior que oferecer um botão a menos.
 */

import { useSyncExternalStore } from 'react'

let ligada = false
let benchmarkLigado = false

/**
 * Quem quer saber quando a resposta do `/health` chegar.
 *
 * **Existe por um defeito medido em 13/09/2026, no navegador.** `main.tsx` dispara
 * `sincronizar()` sem esperar — de propósito, para não segurar a primeira pintura. Uma
 * tela que lê a bandeira **uma vez**, no corpo do componente, e nunca mais re-renderiza
 * fica com o valor de antes da resposta: a Pesquisa abria dizendo "o Pesquisador não está
 * ligado neste ambiente" num ambiente em que ele estava ligado. A Consulta escapava por
 * acidente (ela re-renderiza a cada tecla), o que é pior — o defeito existia e não
 * aparecia.
 *
 * Mesmo padrão de `papel.ts`: `useSyncExternalStore` sobre um punhado de ouvintes.
 */
const ouvintes = new Set<() => void>()

function avisar(): void {
  for (const ouvinte of [...ouvintes]) ouvinte()
}

/** Assina mudanças de bandeira. Devolve como cancelar. */
export function assinarBandeiras(ouvinte: () => void): () => void {
  ouvintes.add(ouvinte)
  return () => {
    ouvintes.delete(ouvinte)
  }
}

/** O Pesquisador está ligado? Re-renderiza quando o `/health` responder. */
export function usePesquisaLigada(): boolean {
  return useSyncExternalStore(assinarBandeiras, pesquisaLigada, () => false)
}

/** O Benchmark está montado? Mesma história, mesma correção. */
export function useBenchmarkLigado(): boolean {
  return useSyncExternalStore(assinarBandeiras, benchmarkLigadoAgora, () => false)
}

/** O valor conhecido agora. Falso até `sincronizar()` dizer o contrário. */
export function pesquisaLigada(): boolean {
  return ligada
}

/**
 * O Benchmark competitivo está montado neste ambiente?
 *
 * Mesma bandeira, mesmo motivo — e um motivo a mais que só o Benchmark tem: ele é uma
 * **tela inteira**, não um botão. Sem esta leitura, a tela chamaria a rota, receberia 404
 * e o navegador registraria um erro de console em toda visita. Erro de console é
 * indistinguível de defeito para quem está olhando, e o portão `qa/e2e` reprova — com razão.
 */
export function benchmarkLigadoAgora(): boolean {
  return benchmarkLigado
}

/** Lê o `/health` e guarda se o Pesquisador está montado. Chamado uma vez, na subida.
 *
 * **Um ponto de saída, e ele avisa.** A versão anterior tinha um `return` no meio, para o
 * caso de o `/health` responder com erro — e aquele caminho não zerava as bandeiras nem
 * avisava ninguém: um `/health` fora do ar deixava a tela com o valor que estivesse na
 * memória, exatamente ao contrário do que o docstring deste módulo promete. Toda saída
 * passa por aqui embaixo.
 */
export async function sincronizar(): Promise<boolean> {
  try {
    const resposta = await fetch('/api/v1/health')
    const saude = resposta.ok
      ? ((await resposta.json()) as {
          research_enabled?: boolean
          benchmark_enabled?: boolean
        })
      : {}
    ligada = saude.research_enabled === true
    benchmarkLigado = saude.benchmark_enabled === true
  } catch {
    // Sem `/health`, o recurso fica desligado. Degradação certa: a tela some, não quebra.
    ligada = false
    benchmarkLigado = false
  }
  avisar()
  return ligada
}

/** Só para teste: força o estado sem passar pela rede. */
export function definirParaTeste(valor: boolean): void {
  ligada = valor
  avisar()
}

/** Só para teste: força o estado do Benchmark sem passar pela rede. */
export function definirBenchmarkParaTeste(valor: boolean): void {
  benchmarkLigado = valor
  avisar()
}
