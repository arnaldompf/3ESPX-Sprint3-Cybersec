/**
 * Um número que **sobe** até o valor, em 400 ms, na primeira vez que aparece.
 *
 * Para que serve: o cartão de métrica é a primeira coisa que a pessoa olha ao abrir uma
 * ficha, e um número que chega subindo diz "isto foi apurado agora". Um número que já
 * está lá é indistinguível de um número escrito no layout.
 *
 * **Só na primeira renderização.** Trocar de filtro e ver os quatro contadores subirem de
 * novo cansa e atrasa a leitura; a animação é uma apresentação, não um efeito.
 *
 * **O valor final vive no DOM desde o primeiro quadro**, em `data-valor`, e é dele que os
 * testes de tela leem. Sem isso, um teste que lê o texto enquanto a contagem sobe compara
 * "12" com "30 botões de evidência" e falha por um defeito que não existe. O que a pessoa
 * vê e o que o teste mede continuam sendo o mesmo número; o que muda é que um deles não
 * depende do instante da leitura.
 *
 * `prefers-reduced-motion` desliga a contagem por inteiro: o número aparece pronto.
 */

import { useEffect, useRef, useState } from 'react'

import { usePrefereMenosMovimento } from '@/lib/movimento'

const DURACAO_MS = 400

/** Desaceleração: rápido no começo, assentando no fim. É o que parece "apurar". */
function suavizar(fracao: number): number {
  return 1 - (1 - fracao) ** 3
}

export function Contador({
  valor,
  formatar = (n: number) => String(n),
  className = '',
}: {
  valor: number
  /** Como o número aparece. O padrão é cru; a Ficha usa separador de milhar. */
  formatar?: (valor: number) => string
  className?: string
}) {
  const menosMovimento = usePrefereMenosMovimento()
  const [mostrado, setMostrado] = useState(() => (menosMovimento ? valor : 0))
  const jaSubiu = useRef(false)

  useEffect(() => {
    if (menosMovimento || jaSubiu.current || !Number.isFinite(valor)) {
      setMostrado(valor)
      jaSubiu.current = true
      return undefined
    }
    jaSubiu.current = true
    const inicio = performance.now()
    let quadro = 0
    const passo = (agora: number) => {
      const fracao = Math.min(1, (agora - inicio) / DURACAO_MS)
      setMostrado(Math.round(suavizar(fracao) * valor))
      if (fracao < 1) quadro = requestAnimationFrame(passo)
    }
    quadro = requestAnimationFrame(passo)
    return () => cancelAnimationFrame(quadro)
  }, [valor, menosMovimento])

  return (
    <span className={className} data-valor={valor}>
      {formatar(mostrado)}
    </span>
  )
}
