/**
 * A mensagem de erro como a pessoa lê, não como o servidor escreve.
 *
 * O back-end fala a língua dele, e faz bem: `"preco_sugerido_brl não é número neste veículo
 * (valor atual: None)"` diz ao desenvolvedor exatamente o que houve. Na tela do Simulador,
 * a mesma frase diz ao vendedor que alguma coisa quebrou — e nada quebrou: o veículo
 * escolhido simplesmente não tem preço verificado.
 *
 * Esta camada **traduz, não inventa**: cada regra abaixo casa uma mensagem conhecida da
 * API e devolve a mesma informação em português, com o que fazer a seguir. O que não casa
 * nenhuma regra passa como veio, porque esconder um erro desconhecido atrás de "algo deu
 * errado" é pior do que mostrar o texto do servidor.
 *
 * O contrato da API não muda: quem traduz é a tela.
 */

import { ErroDaApi } from './api'
import { rotularCampo } from './formato'

/**
 * O campo como a pessoa o chama.
 *
 * A família `preco_*` vira a palavra "preço" e pronto: é a única que a variação percentual
 * do Simulador alcança, e escrever "preco sugerido" (sem cedilha, porque o nome canônico
 * não tem acento) numa frase em português é pior do que não nomear. Os demais usam o
 * `rotularCampo` de sempre — **nenhum dicionário novo de rótulos bonitos**, que é regra do
 * projeto: um segundo vocabulário divergiria do primeiro sem ninguém ver.
 */
function campoComoSeLe(campo: string): string {
  if (campo.startsWith('preco')) return 'preço'
  const rotulo = rotularCampo(campo.replace(/_brl$/, '').replace(/_kml$/, ''))
  return rotulo.charAt(0).toLowerCase() + rotulo.slice(1)
}

interface Regra {
  readonly casa: RegExp
  readonly escreve: (achado: RegExpMatchArray) => string
}

const REGRAS: readonly Regra[] = [
  {
    // "preco_sugerido_brl não é número neste veículo (valor atual: None); variação..."
    casa: /^(\w+) não é número neste veículo/,
    escreve: (achado) =>
      `Este veículo não tem ${campoComoSeLe(achado[1] ?? '')} verificado. ` +
      'Escolha outro veículo ou informe um valor.',
  },
  {
    casa: /^campo (\w+) não existe/i,
    escreve: (achado) => `O campo ${campoComoSeLe(achado[1] ?? '')} não existe na ficha padrão.`,
  },
]

/**
 * A frase para a tela. `acao` completa a orientação ("simular o cenário", "comparar").
 *
 * Devolve `undefined` quando não há erro, para a tela poder usar direto num `&&`.
 */
export function mensagemDeErro(erro: unknown, acao: string): string | undefined {
  if (!erro) return undefined
  if (!(erro instanceof ErroDaApi)) return `Não foi possível ${acao}. Tente de novo.`
  if (erro.semPermissao) return `Seu perfil não pode ${acao}. ${limpar(erro.detalhe)}`
  const traduzida = traduzir(erro.detalhe)
  if (traduzida) return traduzida
  return `Não foi possível ${acao}: ${limpar(erro.detalhe)}`
}

/** A tradução isolada, quando a tela já tem a própria moldura de frase. */
export function traduzir(detalhe: string): string | undefined {
  const texto = (detalhe || '').trim()
  for (const regra of REGRAS) {
    const achado = texto.match(regra.casa)
    if (achado) return regra.escreve(achado)
  }
  return undefined
}

/**
 * Tira do texto os restos de Python que escapam para a tela.
 *
 * `None` não é palavra do idioma, e quem lê a tela não tem por que saber que o valor
 * ausente do outro lado se chama assim.
 */
export function limpar(detalhe: string): string {
  return (detalhe || '')
    .replace(/\bvalor atual: None\b/g, 'valor atual: nenhum')
    .replace(/\bNone\b/g, 'nenhum valor')
    .trim()
}
