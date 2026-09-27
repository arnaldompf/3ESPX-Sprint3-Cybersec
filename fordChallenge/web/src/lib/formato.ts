/**
 * Formatação de valor e de nome de campo. Fica em `lib/` e não no componente porque é
 * função pura usada por três telas (ficha, radar, matriz) — e porque exportar utilitário
 * do mesmo arquivo de um componente quebra o hot reload do Vite.
 */

/**
 * O valor canônico como se lê.
 *
 * O cuidado que importa: **`false` e `0` não são vazio**. Um `if (!valor)` transformaria
 * "não tem teto solar" em "não sabemos se tem teto solar", que é exatamente a confusão
 * entre os dois vazios que o projeto existe para acabar. Só `null` e `undefined` viram
 * VAZIO.
 *
 * `VAZIO` é a palavra "sem valor", e não o travessão que estava aqui até a v2. Duas razões:
 * travessão é proibido no texto da interface (`030_ANTI_PADROES.md` §8), e — a que pesa
 * mais — numa célula de tabela ele é indistinguível do hífen de um valor que existe. A
 * palavra não é.
 */
export const VAZIO = 'sem valor'

/**
 * Campos cujo número **não** leva separador de milhar.
 *
 * Ano é o caso, e ele apareceu na tela em 13/09/2026: a ficha da Frontier pesquisada ao
 * vivo mostrava `Ano modelo 2.025`. `toLocaleString('pt-BR')` está certo para 1.234 kg e
 * errado para um ano — ninguém escreve "2.026" para dizer 2026, e o ponto ali faz o
 * número parecer outro. A lista é de campo, não de faixa de valor: adivinhar pelo
 * intervalo (1900–2100) transformaria uma carga de 2.000 kg em "2000 kg" no dia em que
 * alguém esquecesse a unidade.
 */
const SEM_SEPARADOR = new Set(['ano_modelo', 'ano'])

export function formatarValor(
  valor: unknown,
  unidade?: string | null,
  campo?: string,
): string {
  if (valor === null || valor === undefined) return VAZIO
  if (typeof valor === 'boolean') return valor ? 'sim' : 'não'
  if (Array.isArray(valor)) {
    return valor.map((v) => String(v).replace(/_/g, ' ')).join(' · ')
  }
  // Texto sozinho segue a **mesma** regra da lista acima: o valor canônico é
  // `snake_case` e o `_` é separador de palavra, não conteúdo. Sem isto, a ficha da
  // Raptor — a tela da cena 2 — mostrava `motor_descricao` como "3.0l_v6_bi_turbo" e
  // `amortecedores` como um parágrafo inteiro em snake_case, cortado no meio de uma
  // palavra (QA-BUG-05). Número e booleano não passam por aqui.
  const semSeparador = campo !== undefined && SEM_SEPARADOR.has(campo)
  const texto =
    typeof valor === 'number'
      ? semSeparador
        ? String(valor)
        : valor.toLocaleString('pt-BR')
      : String(valor).replace(/_/g, ' ')
  return unidade ? `${texto} ${unidade}` : texto
}

/**
 * Palavras do vocabulário canônico que **perdem acento** por serem `snake_case`.
 *
 * O nome do campo no schema é ASCII por necessidade: ele é chave de JSON, de coluna e de
 * URL. O rótulo na tela é português, e português leva acento. Sem esta tabela, o Radar
 * anunciava "Preco sugerido brl" e "Modos direcao" — que não são nomes de campo crus, mas
 * lêem como se fossem, e é isso que o anti-padrão §29 chama de texto técnico na tela.
 *
 * **Isto não é um dicionário de rótulos bonitos**, e a diferença importa. Um dicionário
 * mapearia `potencia_cv` para "Potência máxima" e criaria um segundo vocabulário para
 * manter em sincronia com os 58 campos — a primeira divergência entre os dois seria
 * invisível. Aqui o mapa é de **palavra**, não de campo: um campo novo que use "pressao"
 * ganha o acento sozinho, e um que use uma palavra nova aparece sem acento, que é o
 * comportamento de hoje. Há teste cobrindo as 58 do schema.
 */
const COM_ACENTO: Record<string, string> = {
  aceleracao: 'aceleração',
  aspiracao: 'aspiração',
  camera: 'câmera',
  codigo: 'código',
  combustivel: 'combustível',
  conducao: 'condução',
  descricao: 'descrição',
  dimensoes: 'dimensões',
  direcao: 'direção',
  farois: 'faróis',
  identificacao: 'identificação',
  maxima: 'máxima',
  motorizacao: 'motorização',
  numero: 'número',
  potencia: 'potência',
  preco: 'preço',
  referencia: 'referência',
  rodoviario: 'rodoviário',
  seguranca: 'segurança',
  suspensao: 'suspensão',
  tracao: 'tração',
  versao: 'versão',
}

/** Nomes próprios e siglas que se escrevem em caixa alta. */
const SIGLAS: Record<string, string> = { adas: 'ADAS', fipe: 'FIPE' }

/**
 * Unidades, como se escrevem de verdade — e só quando são o **último** pedaço do nome.
 *
 * `preco_sugerido_brl` acabava em "brl", que na tela lia como resto de nome de coluna. A
 * unidade entra entre parênteses, no fim, onde quem lê espera encontrá-la: "Preço sugerido
 * (R$)". Só no fim porque é lá que o vocabulário canônico a põe; `kml` no meio de um nome
 * seria outra coisa, e adivinhar seria inventar.
 */
const UNIDADES: Record<string, string> = {
  brl: 'R$',
  cv: 'cv',
  kg: 'kg',
  kmh: 'km/h',
  kml: 'km/l',
  l: 'L',
  mm: 'mm',
  nm: 'N·m',
  pol: 'pol',
  qtd: 'quantidade',
  rpm: 'rpm',
  s: 's',
}

/**
 * O nome do campo como rótulo: `_` vira espaço, a palavra recebe o acento que o
 * `snake_case` não comporta, sigla fica em caixa alta, e a primeira letra sobe.
 *
 * O nome canônico continua sendo o contrato; a unidade continua aparecendo ao lado do
 * valor. O que muda é só a grafia do que a pessoa lê.
 */
export function rotularCampo(campo: string): string {
  const pedacos = campo.split('_')
  const ultimo = pedacos[pedacos.length - 1] ?? ''
  const unidade = pedacos.length > 1 ? UNIDADES[ultimo] : undefined
  const nome = (unidade ? pedacos.slice(0, -1) : pedacos)
    .map((palavra) => SIGLAS[palavra] ?? COM_ACENTO[palavra] ?? palavra)
    .join(' ')
  const texto = nome.charAt(0).toUpperCase() + nome.slice(1)
  return unidade ? `${texto} (${unidade})` : texto
}
