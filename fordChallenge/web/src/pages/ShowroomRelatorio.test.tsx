/**
 * O painel do relatório: gerar, acompanhar, compartilhar.
 *
 * O que estes testes guardam: **nenhum campo de contato do cliente** em lugar nenhum do
 * fluxo de compartilhamento, e a tela **dizendo** onde o link abre — para ninguém
 * prometer ao cliente um endereço que ele não abre sozinho.
 *
 * O `describe` diz "showroom" porque é o que o verify da WP-28 seleciona.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PainelDeRelatorio } from './ShowroomRelatorio'
import { mensagemDeCompartilhamento } from '@/lib/compartilhar'
import type { EstadoDoJob } from '@/lib/tipos'

function job(extra: Partial<EstadoDoJob> = {}): EstadoDoJob {
  return {
    id: 'j1',
    tipo: 'pdf',
    status: 'pendente',
    criado_em: '2026-09-09T12:00:00',
    ...extra,
  }
}

function montar(props: Partial<Parameters<typeof PainelDeRelatorio>[0]> = {}) {
  return render(
    <PainelDeRelatorio
      job={undefined}
      rotuloFord="Ford Ranger Raptor"
      rotuloConcorrente="Toyota Hilux SRX Plus"
      aoGerar={() => {}}
      gerando={false}
      {...props}
    />,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('showroom: o documento para o cliente', () => {
  it('diz o que o documento traz e o que ele não traz', () => {
    montar()
    expect(screen.getByText(/Sem tier, sem confiança numérica/)).toBeTruthy()
    expect(screen.getByText(/onde\s+o concorrente leva vantagem/)).toBeTruthy()
  })

  it('showroom: o botão pede o documento sem travar a tela', async () => {
    const aoGerar = vi.fn()
    montar({ aoGerar })
    await userEvent.click(screen.getByRole('button', { name: /gerar documento/ }))
    expect(aoGerar).toHaveBeenCalledOnce()
  })

  it('showroom: enquanto o job roda, a tela mostra o estágio', () => {
    montar({ job: job({ status: 'processando', stage: 'renderizando' }) })
    // O rótulo em português, e nunca o nome cru do estágio. Até 12/09/2026 a tela
    // imprimia "Gerando… (done)" — nome de dentro, em inglês, para quem vende picape.
    expect(screen.getByTestId('estado-do-job').textContent).toContain('gerando o arquivo')
    expect(screen.getByTestId('estado-do-job').textContent).not.toContain('renderizando')
    expect(screen.queryByTestId('relatorio-pronto')).toBeNull()
  })

  it('showroom: job que falhou mostra o motivo, não um link quebrado', () => {
    montar({ job: job({ status: 'falhou', error: 'par sem ficha nos dois lados' }) })
    expect(screen.getByTestId('estado-do-job').textContent).toContain(
      'par sem ficha nos dois lados',
    )
    expect(screen.queryByTestId('relatorio-pronto')).toBeNull()
  })

  it('showroom: pronto, oferece abrir e compartilhar', () => {
    montar({
      job: job({ status: 'concluido', result_url: '/api/v1/reports/relatorio-j1.html' }),
    })
    const bloco = screen.getByTestId('relatorio-pronto')
    expect(bloco).toBeTruthy()
    expect(screen.getByRole('link', { name: /abrir o documento/ })).toHaveAttribute(
      'href',
      '/api/v1/reports/relatorio-j1.html',
    )
  })

  it('showroom: avisa que o link so abre de dentro da rede', () => {
    montar({
      job: job({ status: 'concluido', result_url: '/api/v1/reports/relatorio-j1.html' }),
    })
    expect(screen.getByText(/só abre de dentro da rede/)).toBeTruthy()
    expect(screen.getByText(/mande o arquivo/)).toBeTruthy()
  })
})

describe('showroom: compartilhar sem guardar contato', () => {
  it('não há campo de telefone, e-mail ou nome em lugar nenhum', () => {
    montar({
      job: job({ status: 'concluido', result_url: '/api/v1/reports/relatorio-j1.html' }),
    })
    expect(screen.queryAllByRole('textbox')).toHaveLength(0)
    for (const proibido of ['telefone', 'e-mail', 'email', 'nome', 'destinatário']) {
      expect(screen.queryByLabelText(new RegExp(proibido, 'i'))).toBeNull()
    }
  })

  it('showroom: a mensagem descreve o documento, não o destinatário', () => {
    const mensagem = mensagemDeCompartilhamento('Ford Ranger Raptor', 'Toyota Hilux SRX Plus')
    expect(mensagem).toContain('Comparativo técnico')
    expect(mensagem).toContain('fonte e a data')
    for (const proibido of ['olá', 'prezado', 'sr.', 'sra.']) {
      expect(mensagem.toLowerCase()).not.toContain(proibido)
    }
  })

  it('showroom: usa a folha de compartilhamento do sistema quando existe', async () => {
    const share = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, share })
    montar({
      job: job({ status: 'concluido', result_url: '/api/v1/reports/relatorio-j1.html' }),
    })
    await userEvent.click(screen.getByRole('button', { name: /compartilhar/ }))
    expect(share).toHaveBeenCalledOnce()
    const argumento = share.mock.calls[0]?.[0] as { url?: string; text?: string }
    expect(argumento.url).toContain('/api/v1/reports/relatorio-j1.html')
    expect(argumento.text).toContain('Comparativo técnico')
  })

  it('showroom: sem a folha do sistema, copia o link', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    montar({
      job: job({ status: 'concluido', result_url: '/api/v1/reports/relatorio-j1.html' }),
    })
    await userEvent.click(screen.getByRole('button', { name: /copiar o link/ }))
    expect(writeText).toHaveBeenCalledOnce()
    expect(screen.getByTestId('copiado')).toBeTruthy()
  })

  it('showroom: o link do WhatsApp leva a mensagem e o endereço', () => {
    montar({
      job: job({ status: 'concluido', result_url: '/api/v1/reports/relatorio-j1.html' }),
    })
    const href = screen.getByTestId('whatsapp').getAttribute('href') ?? ''
    expect(href.startsWith('https://wa.me/?text=')).toBe(true)
    const texto = decodeURIComponent(href.replace('https://wa.me/?text=', ''))
    expect(texto).toContain('Comparativo técnico')
    expect(texto).toContain('/api/v1/reports/relatorio-j1.html')
    // Nenhum número de destino na URL: quem escolhe o contato é o WhatsApp.
    expect(href).not.toMatch(/wa\.me\/\d/)
  })

  it('showroom: cancelar o compartilhamento não é erro', async () => {
    const share = vi.fn().mockRejectedValue(new Error('AbortError'))
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { share, clipboard: { writeText } })
    montar({
      job: job({ status: 'concluido', result_url: '/api/v1/reports/relatorio-j1.html' }),
    })
    await userEvent.click(screen.getByRole('button', { name: /compartilhar/ }))
    // Desistir cai para o copiar, em vez de deixar a tela sem resposta.
    expect(writeText).toHaveBeenCalledOnce()
  })
})
