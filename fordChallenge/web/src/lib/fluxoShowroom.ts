/**
 * O fluxo do Showroom sobrevive à troca de tela.
 *
 * **O defeito** (achado por um avaliador em 12/09/2026): o vendedor escolhia o par,
 * marcava os usos, ordenava as prioridades, comparava — e, ao abrir a Ficha para conferir
 * um campo, perdia tudo. `/showroom` é uma rota dentro do `Layout`, e navegar desmonta o
 * componente: os oito `useState` do fluxo morriam junto. Numa conversa com o cliente ao
 * lado, refazer seis toques para voltar ao mesmo lugar é o tipo de coisa que faz a pessoa
 * parar de usar a ferramenta.
 *
 * **`sessionStorage`, e não `localStorage`:** o fluxo é de uma conversa. Fechar a aba
 * encerra a conversa, e o próximo cliente não deve herdar o perfil do anterior — o que
 * `localStorage` faria. É a diferença deliberada em relação a `lib/papel.ts`, que usa
 * `localStorage` porque o papel de quem usa a ferramenta atravessa conversas.
 *
 * **LGPD.** O que se guarda é anônimo por construção, campo a campo: `base` e
 * `concorrente` são ids de versão; `usos` e `ranking` vêm de vocabulários fechados da API;
 * `kmMes` e os dois preços são números; `passo` é um índice. Nada aqui é sobre uma pessoa.
 *
 * **O que NÃO se guarda, e é a decisão que importa:** `atributo_decisivo` e o desfecho da
 * conversa. São o resultado do atendimento, não o formulário — pertencem à sessão, que a
 * API registra com as regras dela. Guardá-los aqui faria o próximo cliente começar com o
 * desfecho do anterior na tela, que é pior que perder o estado.
 *
 * Toda leitura e escrita em `try/catch`, como em `lib/papel.ts`: navegador com
 * armazenamento bloqueado degrada para "o fluxo vale só nesta montagem", e não para uma
 * tela quebrada.
 */

const CHAVE = 'specradar.showroom.fluxo'

/**
 * A versão do formato. Formato antigo é **descartado**, não migrado.
 *
 * Migrar meio estado de uma versão anterior traria de volta um par de veículos que talvez
 * nem exista mais no catálogo, e a tela abriria com um seletor apontando para o nada.
 */
const VERSAO = 1

export interface FluxoDoShowroom {
  /** Id da versão Ford escolhida. */
  base: string
  /** Id da versão concorrente. */
  concorrente: string
  /** Usos marcados, do vocabulário fechado de `/dimensions`. */
  usos: string[]
  /** Prioridades ordenadas, por id de dimensão. */
  ranking: string[]
  kmMes: string
  precoDiesel: string
  precoGasolina: string
  /** Em que passo do fluxo a pessoa estava. */
  passo: number
}

export const FLUXO_PADRAO: FluxoDoShowroom = {
  base: '',
  concorrente: '',
  usos: [],
  ranking: [],
  kmMes: '2500',
  precoDiesel: '6,20',
  precoGasolina: '6,00',
  passo: 0,
}

function ehTexto(valor: unknown): valor is string {
  return typeof valor === 'string'
}

/** Lê o fluxo guardado. Qualquer coisa estranha vira o padrão, sem exceção subindo. */
export function lerFluxo(): FluxoDoShowroom {
  try {
    const cru = sessionStorage.getItem(CHAVE)
    if (!cru) return FLUXO_PADRAO
    const dado = JSON.parse(cru) as { v?: number; fluxo?: Partial<FluxoDoShowroom> }
    if (dado?.v !== VERSAO || !dado.fluxo) return FLUXO_PADRAO
    const { base, concorrente, usos, ranking, kmMes, precoDiesel, precoGasolina, passo } =
      dado.fluxo
    return {
      base: ehTexto(base) ? base : FLUXO_PADRAO.base,
      concorrente: ehTexto(concorrente) ? concorrente : FLUXO_PADRAO.concorrente,
      usos: Array.isArray(usos) ? usos.filter(ehTexto) : FLUXO_PADRAO.usos,
      ranking: Array.isArray(ranking) ? ranking.filter(ehTexto) : FLUXO_PADRAO.ranking,
      kmMes: ehTexto(kmMes) ? kmMes : FLUXO_PADRAO.kmMes,
      precoDiesel: ehTexto(precoDiesel) ? precoDiesel : FLUXO_PADRAO.precoDiesel,
      precoGasolina: ehTexto(precoGasolina) ? precoGasolina : FLUXO_PADRAO.precoGasolina,
      passo: typeof passo === 'number' && Number.isFinite(passo) ? passo : FLUXO_PADRAO.passo,
    }
  } catch {
    // Armazenamento bloqueado ou JSON corrompido: o fluxo vale só nesta montagem.
    return FLUXO_PADRAO
  }
}

export function gravarFluxo(fluxo: FluxoDoShowroom): void {
  try {
    sessionStorage.setItem(CHAVE, JSON.stringify({ v: VERSAO, fluxo }))
  } catch {
    /* armazenamento bloqueado: nada a fazer, e nada a quebrar */
  }
}

/** Esquece o fluxo. Usado ao começar uma conversa nova e nos testes. */
export function limparFluxo(): void {
  try {
    sessionStorage.removeItem(CHAVE)
  } catch {
    /* nada guardado, nada a limpar */
  }
}
