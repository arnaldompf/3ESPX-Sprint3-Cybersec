/**
 * Tabela. Na Matriz e na Saúde ela **é** a tela, e não um bloco dentro dela.
 *
 * As decisões que fazem uma tabela de produto e não uma de 2012:
 *
 * * **cabeçalho em 12 px caixa alta** sobre `--surface-2`, com `tracking` de 0.06em. Ele
 *   é rótulo, não conteúdo, e precisa desaparecer assim que a pessoa entende as colunas;
 * * **linhas de 48 px** com borda inferior de 1 px e hover em `--surface-2`. A v1 apertava
 *   tudo em 32 px, que é o que faz uma tabela parecer planilha exportada;
 * * **números em mono, à direita**, com `tabular-nums`: uma coluna de preços só se lê
 *   quando os dígitos têm a mesma largura;
 * * **primeira coluna fixa** em telas largas (`fixarPrimeira`), porque uma matriz de 17
 *   colunas rolada para a direita sem o nome do campo à vista é ilegível;
 * * **rolagem só na tabela**, num contêiner próprio com `overflow-x`. O `body` nunca rola
 *   de lado — é a diferença entre "a tabela rola" e "a página quebrou".
 */

import type { CSSProperties, ReactNode, ThHTMLAttributes, TdHTMLAttributes } from 'react'

export function Tabela({
  children,
  rotulo,
  className = '',
}: {
  children: ReactNode
  /** O `<caption>` acessível: o que esta tabela lista. */
  rotulo: string
  className?: string
}) {
  return (
    <div className={`rolagem-discreta overflow-x-auto ${className}`}>
      <table className="w-full border-collapse text-corpo">
        <caption className="sr-only">{rotulo}</caption>
        {children}
      </table>
    </div>
  )
}

export function Cabecalho({ children }: { children: ReactNode }) {
  return (
    <thead className="bg-superficie-2">
      <tr>{children}</tr>
    </thead>
  )
}

interface PropsDeCabecalho extends ThHTMLAttributes<HTMLTableCellElement> {
  children: ReactNode
  /** Alinha à direita: colunas de número. */
  numerica?: boolean
  /** Gruda à esquerda em telas largas. Use na primeira coluna de tabela larga. */
  fixa?: boolean
}

export function Coluna({
  children,
  numerica = false,
  fixa = false,
  className = '',
  scope = 'col',
  ...resto
}: PropsDeCabecalho) {
  return (
    <th
      scope={scope}
      className={[
        'px-4 py-2.5 align-bottom text-meta font-semibold uppercase tracking-[0.06em]',
        'text-tinta-2',
        numerica ? 'text-right' : 'text-left',
        fixa ? 'sticky left-0 z-10 min-w-[180px] bg-superficie-2' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...resto}
    >
      {children}
    </th>
  )
}

export function Corpo({ children }: { children: ReactNode }) {
  return <tbody>{children}</tbody>
}

export function Linha({
  children,
  className = '',
  destaque = false,
  testId,
  style,
}: {
  children: ReactNode
  className?: string
  /** Fundo âmbar: é a linha divergente da ficha, e ela precisa saltar. */
  destaque?: boolean
  /** `data-testid` na `<tr>`: é a linha inteira que os testes inspecionam, não uma célula. */
  testId?: string
  /** Só para o `--atraso` do escalonamento (`lib/movimento.ts`). Não use para estilo. */
  style?: CSSProperties
}) {
  return (
    <tr
      data-testid={testId}
      style={style}
      className={[
        'border-b border-borda transition-colors duration-150 ease-out',
        destaque ? 'bg-naoSabemos-fundo' : 'hover:bg-superficie-2',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {children}
    </tr>
  )
}

interface PropsDeCelula extends TdHTMLAttributes<HTMLTableCellElement> {
  children: ReactNode
  numerica?: boolean
  fixa?: boolean
}

export function Celula({
  children,
  numerica = false,
  fixa = false,
  className = '',
  ...resto
}: PropsDeCelula) {
  return (
    <td
      className={[
        'h-12 px-4 align-middle text-tinta',
        numerica ? 'mono text-right' : '',
        // O fundo repetido na célula fixa não é redundância: sem ele, a coluna grudada
        // fica transparente e as outras colunas passam por baixo ao rolar.
        fixa ? 'sticky left-0 z-10 bg-superficie' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...resto}
    >
      {children}
    </td>
  )
}

/**
 * Cabeçalho de linha (primeira coluna com `scope="row"`).
 *
 * Separado da `Celula` porque leitor de tela usa o `<th scope="row">` para anunciar de que
 * linha é a célula que está lendo — numa matriz de paridade com 17 colunas, é a diferença
 * entre "▲" e "peso de reboque: ganhamos".
 */
export function CelulaDeRotulo({
  children,
  fixa = false,
  className = '',
}: {
  children: ReactNode
  fixa?: boolean
  className?: string
}) {
  return (
    <th
      scope="row"
      className={[
        'h-12 px-4 text-left align-middle font-medium text-tinta',
        fixa ? 'sticky left-0 z-10 bg-superficie' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {children}
    </th>
  )
}
