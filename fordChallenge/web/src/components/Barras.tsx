/**
 * As barras: aderência, peso de prioridade, cobertura por montadora e win/loss empilhado.
 *
 * Uma regra atravessa as quatro: **o número em texto fica ao lado da barra**, sempre. A
 * barra dá a comparação num relance; o número dá o valor exato; e quem usa leitor de tela
 * só tem o número. Barra sem número é decoração.
 *
 * Nenhuma delas anima ao entrar. Barra que cresce da esquerda é o tipo de movimento que
 * `030_ANTI_PADROES.md` §19 e §20 proíbem, e numa tela de dado ela ainda atrapalha a
 * leitura: o valor muda enquanto a pessoa lê.
 *
 * A largura vai em `style` (não em classe) porque é um número contínuo: 101 classes de
 * porcentagem é o que a CSP do app já documenta como a razão de `'unsafe-inline'` em
 * `style-src`.
 */

import type { ReactNode } from 'react'

function percentual(valor: number, total: number): number {
  if (!Number.isFinite(valor) || !Number.isFinite(total) || total <= 0) return 0
  return Math.max(0, Math.min(100, (valor / total) * 100))
}

/**
 * Barra de cobertura: "28 de 58 campos".
 *
 * O denominador aparece por escrito porque percentual sem denominador é anti-padrão §24 —
 * "48%" de 58 campos e "48%" de 4 campos não são a mesma afirmação.
 */
export function BarraDeCobertura({
  rotulo,
  valor,
  total,
  cor = 'bg-marca-600',
  sufixo = '',
}: {
  rotulo: ReactNode
  valor: number
  total: number
  cor?: string
  /** Palavra depois do denominador: "campos", "versões". */
  sufixo?: string
}) {
  const largura = percentual(valor, total)
  return (
    <div className="flex items-center gap-3">
      <div className="w-44 shrink-0 truncate text-rotulo text-tinta-2">{rotulo}</div>
      <div
        className="h-2 flex-1 overflow-hidden rounded-full bg-superficie-2"
        role="img"
        aria-label={`${valor} de ${total}${sufixo ? ` ${sufixo}` : ''}`}
      >
        <div className={`h-full rounded-full ${cor}`} style={{ width: `${largura}%` }} />
      </div>
      <div className="mono w-24 shrink-0 text-right text-rotulo text-tinta">
        {valor} de {total}
      </div>
    </div>
  )
}

/**
 * As duas barras de aderência, empilhadas: Ford em `--brand-600`, concorrente em
 * `--ink-3`.
 *
 * O rótulo obrigatório ("aderência ao perfil informado, não é um ranking de qualidade")
 * não mora aqui: ele vem da API em `rotulo_obrigatorio` e a tela o exibe uma vez, acima
 * do par. Duplicá-lo por barra faria a frase virar textura.
 */
export function BarrasDeAderencia({
  ford,
  concorrente,
  maximo = 100,
}: {
  // `valor: number | null` de propósito. O motor devolve `null` quando nenhuma dimensão
  // com peso teve dado comparável — e diz, no aviso: "um zero aqui seria invenção". Com a
  // prop tipada como `number`, o único jeito de chamar era inventar esse zero, e era o que
  // o Showroom fazia (`?? 0`): o cartão dizia "sem nota" e a barra, logo abaixo, desenhava
  // "0 de 10" para os dois lados. `docs/12` §6.2 proíbe exatamente isso.
  ford: { rotulo: string; valor: number | null }
  concorrente: { rotulo: string; valor: number | null }
  maximo?: number
}) {
  return (
    <div className="space-y-3">
      {[
        { ...ford, cor: 'bg-marca-600' },
        { ...concorrente, cor: 'bg-tinta-3' },
      ].map((lado) => (
        <div key={lado.rotulo} className="flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="mb-1.5 flex items-baseline justify-between gap-2">
              <span className="truncate text-corpo font-medium text-tinta">{lado.rotulo}</span>
              <span className="mono shrink-0 text-rotulo text-tinta">
                {lado.valor === null
                  ? 'sem nota'
                  : `${lado.valor.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} de ${maximo}`}
              </span>
            </div>
            {/* Barra AUSENTE, e não barra de largura zero: uma barra vazia é
                indistinguível de nota 0,0 para quem só olha. */}
            {lado.valor === null ? null : (
              <div
                className="h-2 overflow-hidden rounded-full bg-superficie-2"
                role="img"
                aria-label={`${lado.rotulo}: ${lado.valor} de ${maximo}`}
              >
                <div
                  className={`h-full rounded-full ${lado.cor}`}
                  style={{ width: `${percentual(lado.valor, maximo)}%` }}
                />
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * A barra fina de peso, no ranking de prioridades do Showroom.
 *
 * O `%` fica escrito ao lado. Sem ele, "35" ao lado de uma barra se lê como posição, nota
 * ou quantidade — e o que ele é, é a fração do peso do perfil que aquela prioridade leva.
 */
export function BarraDePeso({ peso }: { peso: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-superficie-2">
        <div
          className="h-full rounded-full bg-marca-600"
          style={{ width: `${percentual(peso, 100)}%` }}
        />
      </div>
      <span className="mono w-10 shrink-0 text-right text-meta text-tinta-2">{peso}%</span>
    </div>
  )
}

export interface FatiaEmpilhada {
  readonly rotulo: string
  readonly valor: number
  readonly cor: string
}

/**
 * Barra empilhada de win/loss: fechou, perdeu, em andamento.
 *
 * As contagens vão ao lado por extenso. **Percentual só com n ≥ 20** é regra de produto
 * (`030_ANTI_PADROES.md` §24), e quem decide isso é a tela que chama — aqui só entram
 * contagens, que são sempre honestas.
 */
export function BarraEmpilhada({
  fatias,
  total,
}: {
  fatias: readonly FatiaEmpilhada[]
  total: number
}) {
  const descricao = fatias.map((f) => `${f.rotulo}: ${f.valor}`).join(', ')
  return (
    <div className="space-y-1.5">
      <div
        className="flex h-2.5 w-full overflow-hidden rounded-full bg-superficie-2"
        role="img"
        aria-label={`${descricao} (de ${total})`}
      >
        {fatias.map((fatia) => (
          <div
            key={fatia.rotulo}
            className={fatia.cor}
            style={{ width: `${percentual(fatia.valor, total)}%` }}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-meta text-tinta-2">
        {fatias.map((fatia) => (
          <span key={fatia.rotulo} className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${fatia.cor}`} />
            {fatia.rotulo}
            <span className="mono text-tinta">{fatia.valor}</span>
          </span>
        ))}
      </div>
    </div>
  )
}
