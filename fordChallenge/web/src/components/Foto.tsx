/**
 * A foto de um veículo. Pequena, com crédito, e **nunca** como fundo.
 *
 * Três decisões, e as três são sobre não deixar a foto competir com o dado:
 *
 * * **espaço reservado antes de carregar.** A moldura tem `aspect-ratio: 16/9` e cor de
 *   fundo desde o primeiro quadro, então a chegada da imagem não empurra o que está
 *   embaixo. Salto de layout é o defeito que mais se sente e o menos atribuído — a pessoa
 *   clica no lugar errado e acha que errou a mira;
 * * **crédito em 12 px, sempre.** As fotos são divulgação das montadoras, e quem apresenta
 *   precisa poder dizer isso sem procurar. Está em `web/public/img/CREDITOS.md` por
 *   escrito e aqui na tela por obrigação;
 * * **`loading="lazy"` e `decoding="async"`.** No Showroom são duas fotos ao lado de uma
 *   comparação de 58 campos; a comparação é o que a pessoa veio ver.
 *
 * Sem foto, o componente não desenha nada — nem moldura, nem "imagem indisponível". Um
 * quadro vazio anunciando ausência de ilustração ocuparia espaço para dizer nada.
 */

import { CREDITO_DAS_FOTOS } from '@/lib/fotos'

export function FotoDoVeiculo({
  src,
  alt,
  className = '',
  credito = true,
}: {
  src: string | undefined
  /** O rótulo do veículo. `alt` de foto ilustrativa diz **o que é**, não o que ela prova. */
  alt: string
  className?: string
  /** Desliga o crédito quando outra foto na mesma seção já o carrega. */
  credito?: boolean
}) {
  if (!src) return null
  return (
    <figure className={`m-0 ${className}`}>
      <div className="overflow-hidden rounded-cartao border border-borda bg-superficie-2">
        {/* `width` e `height` explícitos além do `aspect-ratio`: os dois reservam o
            espaço, e o navegador usa o primeiro que tiver antes de o CSS ser aplicado.
            São as dimensões que `preparar_imagens.py` produz. */}
        <img
          src={src}
          alt={alt}
          width={1600}
          height={900}
          loading="lazy"
          decoding="async"
          className="block aspect-[16/9] w-full object-cover"
        />
      </div>
      {credito ? (
        <figcaption className="mt-1.5 text-meta text-tinta-3">{CREDITO_DAS_FOTOS}</figcaption>
      ) : null}
    </figure>
  )
}
