import { useEffect, useState } from 'react'

/**
 * O valor, mas só depois de a pessoa parar de digitar.
 *
 * A caixa única da Consulta consulta o servidor a cada tecla. Sem esta espera, digitar
 * "high country" dispara **doze** requisições e a décima segunda é a única que importa —
 * e as onze anteriores podem chegar fora de ordem, fazendo a lista piscar com o resultado
 * de "high count" depois do de "high country".
 *
 * 180 ms é o intervalo: abaixo disso a economia some, acima a lista parece travada.
 */
export function useEspera<T>(valor: T, ms = 180): T {
  const [esperado, setEsperado] = useState(valor)

  useEffect(() => {
    const id = setTimeout(() => setEsperado(valor), ms)
    return () => clearTimeout(id)
  }, [valor, ms])

  return esperado
}
