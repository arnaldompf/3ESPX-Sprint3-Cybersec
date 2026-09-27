/**
 * Uma mensagem da conversa: quem falou, a que hora, e o conteúdo.
 *
 * Quatro falas possíveis do sistema (qual carro é, qual versão você quer, o que estou
 * fazendo, o que achei), e todas saem de regra ou de fonte — nunca da memória do modelo.
 * A que mora aqui é a primeira: **a identificação**, com a etiqueta do ano (INFERÊNCIA
 * quando foi o vigente assumido; a pessoa pode trocar) e os botões que decidem o passo
 * seguinte. A trilha e a ficha têm componentes próprios.
 */

import type { ReactNode } from 'react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '@/components/Badge'
import { Botao } from '@/components/Botao'
import { ResumoDaFicha } from '@/components/pesquisa/ResumoDaFicha'
import {
  dominioDe,
  formatarDataBR,
  formatarHora,
  type Alvo,
  type Mensagem as MensagemDaConversa,
} from '@/lib/conversa'
import type { Etiqueta, Identificacao, OpcaoDeVeiculo } from '@/lib/tipos'

import { Opcoes } from './Opcoes'
import { Pulso } from './Trilha'

export const NOME_DO_AUTOR = { voce: 'você', specradar: 'SpecRadar' } as const

/** O link com cara de botão primário: mesma altura e raio de `Botao`. */
export const CLASSE_DO_LINK_PRIMARIO = [
  'inline-flex h-10 items-center justify-center gap-2 rounded-controle px-4 text-corpo font-medium',
  'bg-marca-600 text-white transition-colors duration-150 ease-out hover:bg-marca-hover',
].join(' ')

export const CLASSE_DO_LINK_SECUNDARIO = [
  'inline-flex h-10 items-center justify-center gap-2 rounded-controle px-4 text-corpo font-medium',
  'border border-borda-forte bg-superficie text-tinta transition-colors duration-150 ease-out hover:bg-superficie-2',
].join(' ')

/** A moldura: autor, hora `HH:MM:SS` e o conteúdo. */
export function Balao({
  mensagem,
  children,
}: {
  mensagem: MensagemDaConversa
  children: ReactNode
}) {
  const sua = mensagem.autor === 'voce'
  return (
    <article
      data-testid={`mensagem-${mensagem.tipo}`}
      data-autor={mensagem.autor}
      className={`flex flex-col gap-1 ${sua ? 'items-end' : 'items-start'}`}
    >
      <header className="flex items-baseline gap-2 px-1 text-meta text-tinta-3">
        <span className="font-medium">{NOME_DO_AUTOR[mensagem.autor]}</span>
        <time dateTime={mensagem.hora} className="mono" data-testid="hora-da-mensagem">
          {formatarHora(mensagem.hora)}
        </time>
      </header>
      <div
        className={
          sua
            ? 'max-w-[85%] rounded-cartao bg-marca-50 px-4 py-3 text-corpo text-marca-950'
            : 'w-full min-w-0'
        }
      >
        {children}
      </div>
    </article>
  )
}

/** O conteúdo das mensagens simples: o que a pessoa disse, um aviso, um erro. */
export function TextoDaMensagem({
  mensagem,
}: {
  mensagem: Extract<MensagemDaConversa, { tipo: 'texto' | 'sistema' | 'erro' }>
}) {
  if (mensagem.tipo === 'texto') {
    return <p className="whitespace-pre-wrap break-words">{mensagem.texto}</p>
  }
  if (mensagem.tipo === 'erro') {
    return (
      <p role="alert" className="text-corpo text-perdemos">
        {mensagem.texto}
      </p>
    )
  }
  if (mensagem.destaque) {
    return (
      <div
        data-testid="aviso-em-destaque"
        className="flex flex-wrap items-center gap-2 rounded-cartao border-l-[3px] border-naoSabemos bg-naoSabemos-fundo px-4 py-3 text-corpo text-tinta"
      >
        <span className="min-w-0 flex-1">{mensagem.texto}</span>
        <Badge etiqueta="FATO" motivo="o que a pesquisa registrou ao parar" />
      </div>
    )
  }
  return (
    <p aria-live={mensagem.pulso ? 'polite' : undefined} className="flex items-center gap-2 text-corpo text-tinta-2">
      {mensagem.pulso ? <Pulso /> : null}
      <span className={mensagem.pulso ? 'animate-pulse' : ''}>{mensagem.texto}</span>
    </p>
  )
}

/* ------------------------------------------------------------------ a identificação */

/** A etiqueta do ano-modelo, pela origem que o servidor declarou. */
const ETIQUETA_DO_ANO: Record<string, { etiqueta: Etiqueta; motivo: string }> = {
  vigente: { etiqueta: 'INFERENCIA', motivo: 'ano vigente assumido; você pode trocar' },
  pedido: { etiqueta: 'FATO', motivo: 'ano-modelo que você informou' },
  fontes: { etiqueta: 'FATO', motivo: 'ano-modelo lido nas fontes consultadas' },
  catalogo: { etiqueta: 'FATO', motivo: 'ano-modelo registrado no nosso catálogo' },
}

interface PropsDaIdentificacao {
  identificacao: Identificacao
  /** Só a última identificação da conversa aceita clique; as anteriores ficam de registro. */
  ativa: boolean
  aoPesquisar: (alvo: Alvo) => void
  aoEscolher: (opcao: OpcaoDeVeiculo) => void
  aoTrocarAno: (ano: number) => void
}

export function MensagemDeIdentificacao({
  identificacao,
  ativa,
  aoPesquisar,
  aoEscolher,
  aoTrocarAno,
}: PropsDaIdentificacao) {
  const [trocandoAno, setTrocandoAno] = useState(false)
  const [anoDigitado, setAnoDigitado] = useState(
    identificacao.ano ? String(identificacao.ano) : String(new Date().getFullYear()),
  )
  const { estado, marca, modelo, versao, ano, ano_origem, nome, no_catalogo } = identificacao
  const alvo: Alvo = { marca, modelo, versao, ano, ano_origem }
  const fontes = [...new Set(identificacao.fontes.map(dominioDe).filter(Boolean))]

  if (estado === 'nao_entendi') {
    return (
      <div data-testid="nao-entendi" className="space-y-2 text-corpo text-tinta">
        <p>{identificacao.motivo || 'Não entendi de que carro você fala.'}</p>
        <p className="text-tinta-2">
          Tente de outro jeito, com marca e modelo: por exemplo, "Chevrolet S10 High Country"
          ou "Toyota Hilux SRX 2025".
        </p>
      </div>
    )
  }

  if (estado === 'precisa_escolher') {
    return (
      <div data-testid="precisa-escolher" className="space-y-3">
        <p className="text-corpo text-tinta">{identificacao.pergunta || `Qual ${modelo || 'versão'}?`}</p>
        <Opcoes opcoes={identificacao.opcoes} aoEscolher={aoEscolher} desabilitado={!ativa} />
        <p className="text-meta text-tinta-3">
          Cada opção mostra a fonte que a sustenta. Se nenhuma serve, escreva de outro jeito
          na caixa abaixo.
        </p>
      </div>
    )
  }

  // estado === 'resolvido'
  if (no_catalogo?.tem_ficha) {
    return (
      <div data-testid="ja-temos" className="space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-corpo text-tinta">
          <p className="min-w-0">
            Já temos a ficha de <strong>{nome || `${marca} ${modelo} ${versao}`.trim()}</strong>
            {no_catalogo.ano_modelo ? ` (${no_catalogo.ano_modelo})` : ''}.{' '}
            {no_catalogo.coletado_em
              ? `Dados coletados em ${formatarDataBR(no_catalogo.coletado_em)}.`
              : 'Sem data de coleta registrada.'}
            {no_catalogo.campos_com_valor
              ? ` ${no_catalogo.campos_com_valor} campos com valor.`
              : ''}
          </p>
          <Badge
            etiqueta="CATALOGO"
            motivo="versão e data de coleta lidas do nosso catálogo, não de uma página"
          />
        </div>
        <ResumoDaFicha versionId={no_catalogo.version_id} />
        <div className="flex flex-wrap gap-2">
          <Link
            to={`/ficha/${no_catalogo.version_id}`}
            data-testid="abrir-ficha"
            className={CLASSE_DO_LINK_PRIMARIO}
          >
            abrir ficha
          </Link>
          <Botao
            data-testid="pesquisar-de-novo"
            disabled={!ativa}
            onClick={() => aoPesquisar(alvo)}
          >
            pesquisar de novo
          </Botao>
        </div>
      </div>
    )
  }

  const etiquetaDoAno = ETIQUETA_DO_ANO[ano_origem] ?? {
    etiqueta: 'INFERENCIA' as Etiqueta,
    motivo: 'origem do ano não declarada; confira antes de pesquisar',
  }

  return (
    <div data-testid="confirmacao" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-corpo text-tinta">
        <p className="min-w-0">
          Entendi:{' '}
          <strong>
            {marca} {modelo} {versao}
          </strong>
          {ano ? (
            <>
              , ano-modelo <strong>{ano}</strong>
            </>
          ) : (
            <>, sem ano-modelo definido</>
          )}
        </p>
        {ano ? <Badge etiqueta={etiquetaDoAno.etiqueta} motivo={etiquetaDoAno.motivo} /> : null}
      </div>

      {fontes.length > 0 ? (
        <p className="text-meta text-tinta-3">identificado com: {fontes.join(', ')}</p>
      ) : identificacao.origem === 'catalogo' ? (
        <p className="text-meta text-tinta-3">identificado no nosso catálogo</p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Botao tom="primario" data-testid="pesquisar-agora" disabled={!ativa} onClick={() => aoPesquisar(alvo)}>
          pesquisar agora
        </Botao>
        <Botao data-testid="outro-ano" disabled={!ativa} onClick={() => setTrocandoAno((v) => !v)}>
          outro ano
        </Botao>
      </div>

      {trocandoAno && ativa ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            const n = Number(anoDigitado)
            if (Number.isInteger(n) && n >= 1990 && n <= 2100) {
              setTrocandoAno(false)
              aoTrocarAno(n)
            }
          }}
        >
          <label htmlFor="campo-ano" className="text-corpo text-tinta-2">
            ano-modelo
          </label>
          <input
            id="campo-ano"
            data-testid="campo-ano"
            type="number"
            min={1990}
            max={2100}
            value={anoDigitado}
            onChange={(e) => setAnoDigitado(e.target.value)}
            className="mono h-10 w-24 rounded-controle border border-borda-forte bg-superficie px-2 text-corpo text-tinta"
          />
          <Botao type="submit" data-testid="confirmar-ano">
            confirmar
          </Botao>
        </form>
      ) : null}
    </div>
  )
}
