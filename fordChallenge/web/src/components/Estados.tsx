/**
 * Os quatro estados que toda tela precisa ter desenhados: carregando, vazio, erro e
 * recusa por papel.
 *
 * Estes não são casos de canto. Numa demonstração, três dos quatro aparecem: o vendedor
 * recebe **recusa** no Radar (`docs/12` §6.1), o bloco de win/loss real está **vazio**
 * porque ninguém registrou sessão ainda, e toda tela passa por **carregando**. Um estado
 * não desenhado é uma tela em branco na frente de quem está avaliando o produto.
 *
 * **O skeleton tem atraso e piso** (`030_ANTI_PADROES.md` §15): só aparece depois de
 * 200 ms — resposta rápida não deve piscar um esqueleto — e, tendo aparecido, fica no
 * mínimo 400 ms, porque um esqueleto que some em 50 ms é um flash, não um aviso.
 */

import type { ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'

import { Botao } from './Botao'
import type { Icone } from './Icones'
import { Info, Warning } from './Icones'

const ATRASO_MS = 200
const PISO_MS = 400

/**
 * `true` quando o esqueleto deve estar na tela.
 *
 * A regra dos dois tempos num hook, e não espalhada: qualquer tela que mostre skeleton
 * precisa das duas metades, e metade da regra dá exatamente o defeito que a outra metade
 * existe para evitar.
 */
export function useEsqueleto(carregando: boolean): boolean {
  const [visivel, setVisivel] = useState(false)
  const desde = useRef<number | null>(null)

  useEffect(() => {
    if (carregando) {
      const entrada = setTimeout(() => {
        desde.current = Date.now()
        setVisivel(true)
      }, ATRASO_MS)
      return () => clearTimeout(entrada)
    }
    if (!visivel) return undefined
    // O piso conta do momento em que o esqueleto apareceu, e não de agora: uma resposta
    // que chega em 250 ms deixaria o esqueleto 400 ms a mais na tela se fosse "de agora".
    const restante = Math.max(0, PISO_MS - (Date.now() - (desde.current ?? 0)))
    const saida = setTimeout(() => {
      desde.current = null
      setVisivel(false)
    }, restante)
    return () => clearTimeout(saida)
  }, [carregando, visivel])

  return visivel
}

/** Um bloco cinza com brilho, no formato do que vai ocupar o lugar. */
export function Esqueleto({ className = '' }: { className?: string }) {
  return <div aria-hidden="true" className={`skeleton ${className}`} />
}

/**
 * Esqueleto de linhas de tabela ou de lista.
 *
 * `aria-busy` no contêiner e um texto só para leitor de tela: quem não vê a animação
 * precisa ser avisado de que a tela está trabalhando.
 */
export function EsqueletoDeLista({ linhas = 5 }: { linhas?: number }) {
  return (
    <div aria-busy="true" className="space-y-2">
      <span className="sr-only">carregando</span>
      {Array.from({ length: linhas }, (_, i) => (
        <Esqueleto key={i} className="h-12 w-full" />
      ))}
    </div>
  )
}

/**
 * Estado vazio digno: ícone, título, uma frase e — quando existe — a ação que o resolve.
 *
 * A frase diz **por que** está vazio, não que está vazio. "Nenhuma sessão registrada"
 * informa; "quando os vendedores registrarem o desfecho, os números aparecem aqui"
 * ensina o que fazer.
 */
export function Vazio({
  icone: IconeDoVazio = Info,
  titulo,
  children,
  acao,
}: {
  icone?: Icone
  titulo: string
  children: ReactNode
  acao?: { rotulo: string; aoClicar: () => void }
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <IconeDoVazio size={32} aria-hidden="true" className="text-tinta-3" />
      <p className="text-destaque font-semibold text-tinta">{titulo}</p>
      <p className="max-w-md text-corpo text-tinta-2">{children}</p>
      {acao ? (
        <Botao tom="secundario" onClick={acao.aoClicar}>
          {acao.rotulo}
        </Botao>
      ) : null}
    </div>
  )
}

/**
 * Erro: frase clara em português, sem stack trace e sem nome de campo cru.
 *
 * A tradução das mensagens conhecidas está em `lib/erros.ts`; aqui é só a moldura. O que
 * não casa nenhuma regra aparece como veio — esconder erro desconhecido atrás de "algo
 * deu errado" é pior do que mostrar o texto do servidor.
 */
export function Erro({
  titulo = 'Não deu para carregar',
  children,
  acao,
}: {
  titulo?: string
  children: ReactNode
  acao?: { rotulo: string; aoClicar: () => void }
}) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 px-6 py-8">
      <div className="flex items-center gap-2">
        <Warning size={20} aria-hidden="true" className="text-perdemos" />
        <p className="text-destaque font-semibold text-tinta">{titulo}</p>
      </div>
      <p className="text-corpo text-tinta-2">{children}</p>
      {acao ? (
        <Botao tom="secundario" onClick={acao.aoClicar}>
          {acao.rotulo}
        </Botao>
      ) : null}
    </div>
  )
}

/**
 * Recusa por papel. **Não é erro**, e a tela não pode dizer que é.
 *
 * O vendedor recebe 403 no Radar por decisão de produto (`docs/12` §6.1). Mostrar "erro
 * 403" ali faria o vendedor achar que o sistema quebrou; o que ele precisa saber é de
 * quem é a tela e o que ele pode fazer no lugar dela.
 */
export function Recusa({
  papeis,
  children,
  alternativa,
}: {
  /** Quem pode ver, por extenso: "analista, gestor e administrador". */
  papeis: string
  children?: ReactNode
  alternativa?: ReactNode
}) {
  return (
    <div
      data-testid="recusa-por-papel"
      className="rounded-cartao border border-borda bg-superficie p-6 shadow-cartao"
    >
      <div className="flex items-start gap-3">
        <Info size={20} aria-hidden="true" className="mt-0.5 shrink-0 text-tinta-3" />
        <div className="min-w-0">
          <p className="text-destaque font-semibold text-tinta">
            Esta tela é de {papeis}
          </p>
          {children ? <p className="mt-1.5 text-corpo text-tinta-2">{children}</p> : null}
          {alternativa ? <div className="mt-4">{alternativa}</div> : null}
        </div>
      </div>
    </div>
  )
}
