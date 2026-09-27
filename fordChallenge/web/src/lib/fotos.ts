/**
 * Qual foto é de qual veículo. Cinco arquivos, e nenhum palpite.
 *
 * **Por que um mapa por nome, e não um campo na API.** A foto não é dado do produto: ela
 * não tem evidência, não tem data de coleta e não entra em nenhuma comparação. Guardá-la
 * no banco a colocaria ao lado de coisas que o SpecRadar afirma, e o SpecRadar só afirma o
 * que tem prova. Aqui ela é o que é: ilustração, do lado da tela.
 *
 * **Veículo sem foto não quebra nada.** `fotoDe` devolve `undefined` e o componente não
 * desenha moldura nenhuma — o mesmo espaço fica para o dado. Uma sexta picape entra no
 * catálogo sem ninguém precisar tocar aqui.
 */

import type { Veiculo } from './tipos'
import { versaoSemOModelo } from './veiculos'

/** Minúsculas, sem acento, espaços colapsados. A mesma ideia do `normalize` do back-end. */
function normalizar(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
}

interface Foto {
  readonly arquivo: string
  readonly marca: string
  readonly modelo: string
  /** Começo do nome da versão, sem o modelo. "Raptor" casa "Raptor 3.0 V6 Bi-turbo 4WD AT". */
  readonly versao: string
}

/**
 * As cinco fotos de `web/public/img/veiculos/`, preparadas por
 * `scripts/design/preparar_imagens.py`.
 *
 * O casamento é por **começo** do nome da versão porque o catálogo escreve a versão
 * inteira ("Limited 3.0 V6 Diesel 4WD AT") e a foto é da linha ("Limited"). Exigir o nome
 * completo faria a foto sumir no dia em que a montadora acrescentasse um sufixo.
 */
const FOTOS: readonly Foto[] = [
  { arquivo: 'ranger-raptor', marca: 'Ford', modelo: 'Ranger', versao: 'Raptor' },
  { arquivo: 'ranger-limited', marca: 'Ford', modelo: 'Ranger', versao: 'Limited' },
  { arquivo: 'hilux-srx-plus', marca: 'Toyota', modelo: 'Hilux', versao: 'SRX Plus' },
  { arquivo: 'amarok-v6-extreme', marca: 'Volkswagen', modelo: 'Amarok', versao: 'V6 Extreme' },
  { arquivo: 's10-high-country', marca: 'Chevrolet', modelo: 'S10', versao: 'High Country' },
]

/** O crédito, em 12 px, embaixo de toda foto. Uma frase, a mesma em todas. */
export const CREDITO_DAS_FOTOS = 'Divulgação oficial das montadoras'

/** O caminho da foto deste veículo, ou `undefined` se não houver. */
export function fotoDe(
  veiculo: Pick<Veiculo, 'marca' | 'modelo' | 'versao'> | undefined | null,
): string | undefined {
  if (!veiculo) return undefined
  const marca = normalizar(veiculo.marca)
  const modelo = normalizar(veiculo.modelo)
  const versao = normalizar(versaoSemOModelo(veiculo.modelo, veiculo.versao))
  const achada = FOTOS.find(
    (foto) =>
      normalizar(foto.marca) === marca &&
      normalizar(foto.modelo) === modelo &&
      versao.startsWith(normalizar(foto.versao)),
  )
  return achada ? `/app/img/veiculos/${achada.arquivo}.webp` : undefined
}

/** O caminho da foto a partir de um rótulo já montado ("Ford Ranger Raptor 3.0 V6..."). */
export function fotoDoRotulo(rotulo: string | undefined | null): string | undefined {
  if (!rotulo) return undefined
  const alvo = normalizar(rotulo)
  const achada = FOTOS.find((foto) =>
    alvo.startsWith(normalizar(`${foto.marca} ${foto.modelo} ${foto.versao}`)),
  )
  return achada ? `/app/img/veiculos/${achada.arquivo}.webp` : undefined
}
