/**
 * A etiqueta. O componente mais importante da tela, porque é a promessa do produto:
 * **nenhum número sem etiqueta**.
 *
 * Quatro coisas, e nenhuma é enfeite:
 *
 * * **cor + ponto + palavra.** Verde e laranja são o par clássico de confusão em
 *   daltonismo, e a etiqueta é a informação mais importante que a tela carrega — não pode
 *   depender de distinguir cor. O ponto de 6 px carrega a cor; a palavra carrega o sentido;
 * * **`title` com a explicação**, para quem passa o mouse, e `aria-label` completo, para
 *   quem usa leitor de tela. "FATO" sozinho não diz o que significa;
 * * **SIMULAÇÃO tem `role="alert"`**: é a única das três que muda o que a pessoa deve
 *   fazer com o número. As outras duas informam; essa avisa;
 * * **sem borda** (v2): a borda de 1 px em volta de um pill de 22 px engrossa o contorno e
 *   era metade do que fazia a v1 parecer de 2012. O fundo suave já separa do branco.
 */
import { CLASSES, COR_DO_PONTO, EXPLICACAO, ICONE, ROTULO } from '@/lib/etiqueta'
import type { Etiqueta } from '@/lib/tipos'

interface Props {
  etiqueta: Etiqueta
  /** `sm` na linha do campo; `md` no cabeçalho da ficha e no modo showroom. */
  tamanho?: 'sm' | 'md'
  /**
   * O motivo desta etiqueta neste campo, quando ele for mais específico que a explicação
   * genérica. Em `SEM_DADO` é o que separa os dois vazios — "a montadora afirma que esta
   * versão não tem" é outra coisa de "nenhuma fonte consultada menciona" — e é a diferença
   * que o schema canônico existe para manter.
   */
  motivo?: string
  className?: string
}

export function Badge({ etiqueta, tamanho = 'sm', motivo, className = '' }: Props) {
  const dimensao = tamanho === 'md' ? 'h-7 px-2.5 text-rotulo' : 'h-[22px] px-2 text-meta'
  const explicacao = motivo ?? EXPLICACAO[etiqueta]
  return (
    <span
      data-testid={`badge-${etiqueta}`}
      // `role="alert"` só para SIMULAÇÃO. SEM DADO informa, não alarma: numa ficha de 58
      // campos, dar alerta a cada vazio afogaria o leitor de tela e apagaria justamente o
      // aviso que importa.
      role={etiqueta === 'SIMULACAO' ? 'alert' : undefined}
      title={explicacao}
      aria-label={`${ROTULO[etiqueta]}: ${explicacao}`}
      className={[
        // `whitespace-nowrap`: "SEM DADO" e "INFERÊNCIA" não podem quebrar dentro do pill.
        'inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full font-semibold',
        'uppercase tracking-[0.06em]',
        dimensao,
        CLASSES[etiqueta],
        className,
      ].join(' ')}
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${COR_DO_PONTO[etiqueta]}`}
      />
      {ROTULO[etiqueta]}
      {/* O glifo fica fora do fluxo visual mas dentro do DOM: o teste que exige
          "cor E ícone E texto" continua encontrando os três, e o pill não fica com dois
          marcadores concorrendo. */}
      <span className="sr-only">{ICONE[etiqueta]}</span>
    </span>
  )
}

/** O texto padrão: dado de demonstração semeado no banco (`is_simulated`). */
export const TEXTO_DE_DEMONSTRACAO =
  'SIMULAÇÃO: dado de demonstração, não é informação sobre veículo real'

/**
 * A faixa de SIMULAÇÃO. `docs/13` exige que dado `is_simulated` nunca apareça sem ela —
 * e uma faixa larga no topo da seção é diferente de uma etiqueta por campo: quem olha de
 * longe (o cliente, na tela do tablet) tem de ver que aquilo não é dado real.
 *
 * **Uma por seção, nunca por item** (`030_ANTI_PADROES.md` §26). A v1 repetia a faixa
 * laranja dentro de cada cartão do Radar e o efeito era o oposto do pretendido: sete
 * faixas iguais viram textura de fundo e param de avisar. Dentro da seção, cada item leva
 * só o pill.
 *
 * **`texto` existe porque há duas simulações diferentes.** Uma é dado de demonstração
 * semeado no banco (o padrão desta faixa); a outra é a **hipótese do usuário** no
 * simulador (WP-35), cuja frase a API manda em `rotulo_simulacao`. As duas são SIMULAÇÃO
 * por `docs/13` §2, e dizer "dado de demonstração" sobre um cenário que o próprio usuário
 * acabou de montar seria impreciso justamente na tela em que a precisão importa mais.
 */
export function FaixaDeSimulacao({
  children,
  texto = TEXTO_DE_DEMONSTRACAO,
}: {
  children?: React.ReactNode
  texto?: string
}) {
  return (
    <div
      role="alert"
      data-testid="faixa-simulacao"
      className={[
        'flex min-h-10 flex-wrap items-center gap-2 rounded-controle bg-simulacao-fundo',
        'border-l-[3px] border-simulacao px-3 py-2 text-rotulo font-medium text-simulacao',
      ].join(' ')}
    >
      <span aria-hidden="true" className="text-corpo leading-none">
        ⚠
      </span>
      {texto}
      {children ? <span className="font-normal">{children}</span> : null}
    </div>
  )
}
