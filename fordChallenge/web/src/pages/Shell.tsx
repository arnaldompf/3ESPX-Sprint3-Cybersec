/**
 * Página de casco para as rotas que as WPs seguintes preenchem.
 *
 * Diz **o que vai existir ali e qual WP entrega**, em vez de "em construção". A diferença
 * importa numa demo: uma rota vazia com o escopo declarado é um plano; um "em breve" é
 * uma promessa vaga.
 */
import { Card } from '@/components/Card'

interface Props {
  titulo: string
  wp: string
  descricao: string
  itens: string[]
}

export function Shell({ titulo, wp, descricao, itens }: Props) {
  return (
    <Card titulo={titulo}>
      <p className="text-corpo text-tinta-2">{descricao}</p>
      <p className="mt-3 text-meta font-semibold uppercase tracking-[0.06em] text-marca-700">
        entrega: {wp}
      </p>
      <ul className="mt-3 space-y-1.5 text-corpo text-tinta-2">
        {itens.map((item) => (
          <li key={item} className="flex gap-2">
            <span aria-hidden="true" className="mt-2 h-1 w-1 shrink-0 rounded-full bg-tinta-3" />
            <span className="min-w-0">{item}</span>
          </li>
        ))}
      </ul>
    </Card>
  )
}
