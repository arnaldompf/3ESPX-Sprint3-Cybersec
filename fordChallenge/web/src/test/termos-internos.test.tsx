/**
 * **O vocabulário de dentro não chega à tela.**
 *
 * Em 12/09/2026 um avaliador usou o sistema como duas pessoas da Ford e leu, na recusa da
 * Hilux GR-Sport, que a versão "é o caso negativo do resolvedor" e tem "status
 * pendente_coleta no gabarito v1"; e, quando o documento do cliente não saiu, que "quem
 * cuida da máquina precisa religar o processador de fila".
 *
 * As duas frases eram verdadeiras e estavam no lugar errado. Uma nasceu como nota de
 * proveniência para quem mantém o pipeline e viajou até a tela como dado; a outra foi
 * escrita à mão num ramo que só aparece com o worker parado — caro de alcançar num
 * navegador, e por isso meses sem ninguém ver.
 *
 * **Este arquivo é a metade estática do portão.** Ele lê os literais de string dos `.tsx`
 * e os confronta com `lib/termos-internos.json`. É rápido (milissegundos, sem navegador),
 * cabe no orçamento de dois minutos do `verify-quick`, e alcança ramos que o e2e só
 * alcançaria derrubando serviços.
 *
 * A outra metade está em `qa/e2e/transversal.spec.ts`, que lê o `innerText` das telas. Ela
 * pega o que entra por **dado**, vindo da API — o vazamento da GR-Sport não aparece em
 * nenhum `.tsx`. Nenhuma das duas alcança o que a outra alcança; por isso são duas.
 *
 * **Duas decisões de projeto, e as duas importam:**
 *
 * 1. varre **literais de string**, não o arquivo bruto. Metade dos arquivos deste web
 *    documenta em comentário o que vem do worker, do gabarito e do resolvedor — e faz bem.
 *    Um teste que reprovasse comentários seria desligado no PR seguinte;
 * 2. só considera literal que **pareça frase** (tem espaço ou acento). É o que separa o
 *    texto de quem lê a tela de `className`, `data-testid`, chave de objeto e caminho de
 *    snapshot — e é o que torna a regra de `snake_case` viável.
 */
import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import termos from '@/lib/termos-internos.json'

const SRC = resolve(__dirname, '..')

function arquivosTsx(pasta: string): string[] {
  const achados: string[] = []
  for (const entrada of readdirSync(pasta, { withFileTypes: true })) {
    const caminho = join(pasta, entrada.name)
    if (entrada.isDirectory()) achados.push(...arquivosTsx(caminho))
    else if (entrada.name.endsWith('.tsx') && !entrada.name.includes('.test.'))
      achados.push(caminho)
  }
  return achados
}

const FONTES = arquivosTsx(SRC).map((caminho) => ({
  caminho: caminho.replace(SRC, 'src').replaceAll('\\', '/'),
  texto: readFileSync(caminho, 'utf-8'),
}))

const ISENTOS = new Set(termos.arquivos_isentos.map((a) => a.caminho))

/**
 * Os literais de string do arquivo, **sem os comentários**.
 *
 * Tirar comentário antes é o que permite a lista ser dura: `Consulta.tsx`, `Radar.tsx` e
 * `Showroom.tsx` explicam em prosa, e corretamente, de onde vem o dado do worker e do
 * gabarito. Documentar bem não pode reprovar.
 */
function literais(texto: string): string[] {
  const semComentarios = texto
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .split('\n')
    .map((linha) => linha.replace(/(^|[^:])\/\/.*$/, '$1'))
    .join('\n')

  const achados: string[] = []
  const LITERAL = /'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`/g
  for (const achado of semComentarios.matchAll(LITERAL)) {
    achados.push(achado[1] ?? achado[2] ?? achado[3] ?? '')
  }
  return achados
}

/**
 * Uma lista de classes utilitárias, e não uma frase.
 *
 * `"flex cursor-pointer list-none flex-col gap-1"` tem espaços e passaria por frase. O que
 * a separa de texto humano é que **todo** token é um identificador CSS (sem acento, sem
 * maiúscula) e **algum** deles tem hífen ou dois-pontos, que é a forma do Tailwind.
 */
function pareceClasseCss(literal: string): boolean {
  const tokens = literal.trim().split(/\s+/).filter(Boolean)
  if (tokens.length === 0) return false
  return (
    tokens.every((t) => /^[a-z0-9@:_\-[\]/.%(),#!*+&>~'"$]+$/.test(t)) &&
    tokens.some((t) => t.includes('-') || t.includes(':'))
  )
}

/** Parece frase de quem lê a tela, e não `className` nem chave de objeto. */
function pareceFrase(literal: string): boolean {
  if (pareceClasseCss(literal)) return false
  return /\s/.test(literal.trim()) || /[áéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ]/.test(literal)
}

/** A regex do termo, com a sensibilidade a maiúscula que ele declarar. */
function regexDe(proibido: { regex: string; sensivel_a_maiuscula?: boolean }): RegExp {
  return new RegExp(proibido.regex, proibido.sensivel_a_maiuscula ? 'u' : 'iu')
}

describe('vocabulário de dentro', () => {
  it('os arquivos isentos existem — exceção para arquivo apagado é exceção que cega', () => {
    const conhecidos = new Set(FONTES.map((f) => f.caminho))
    const orfaos = [...ISENTOS].filter((c) => c.endsWith('.tsx') && !conhecidos.has(c))
    expect(orfaos, `isenção apontando para arquivo que não existe mais: ${orfaos}`).toEqual([])
  })

  it('nenhum literal de interface usa vocabulário de dentro', () => {
    const suspeitos: string[] = []
    for (const { caminho, texto } of FONTES) {
      if (ISENTOS.has(caminho)) continue
      for (const literal of literais(texto)) {
        if (!pareceFrase(literal)) continue
        for (const proibido of termos.proibidos) {
          if (regexDe(proibido).test(literal)) {
            suspeitos.push(`${caminho}: "${literal.trim()}" → ${proibido.termo} (${proibido.porque})`)
          }
        }
      }
    }
    expect(suspeitos, `\n${suspeitos.join('\n')}\n`).toEqual([])
  })

  it('a própria lista está bem formada: regex válida e motivo escrito', () => {
    for (const proibido of termos.proibidos) {
      expect(() => regexDe(proibido), proibido.termo).not.toThrow()
      expect(proibido.porque.length, `${proibido.termo} sem motivo`).toBeGreaterThan(20)
    }
    for (const grupo of [termos.arquivos_isentos, termos.seletores_isentos, termos.rotas_isentas]) {
      for (const isento of grupo) {
        expect(isento.porque.length, JSON.stringify(isento)).toBeGreaterThan(20)
      }
    }
  })

  it('a lista pega as duas frases que chegaram ao avaliador em 12/09/2026', () => {
    // Um teste sobre o teste: se alguém abrandar a lista, isto acusa.
    const casos = [
      'é o caso negativo do resolvedor',
      'status pendente_coleta no gabarito v1',
      'Quem cuida da máquina precisa religar o processador de fila',
    ]
    for (const caso of casos) {
      const pegou = termos.proibidos.some((p) => regexDe(p).test(caso))
      expect(pegou, `a lista deixou passar: ${caso}`).toBe(true)
    }
  })

  it('classe do Tailwind com "-none" não é o None do Python', () => {
    for (const classe of ['text-corpo leading-none', 'pointer-events-none absolute right-3']) {
      expect(pareceFrase(classe), `classe tratada como frase: ${classe}`).toBe(false)
    }
  })

  it('"fila" sozinho continua permitido — é português comum, e a tela usa', () => {
    // Banir "fila" seco reprovaria "3 alerta(s) na fila" e "carregar a fila de alertas".
    // O que se proíbe é o jargão de operação, não a palavra.
    for (const permitido of ['3 alerta(s) na fila', 'carregar a fila de alertas', 'na fila']) {
      const pegou = termos.proibidos.some((p) => regexDe(p).test(permitido))
      expect(pegou, `falso positivo: ${permitido}`).toBe(false)
    }
  })
})
