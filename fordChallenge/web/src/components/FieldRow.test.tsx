/**
 * A linha da ficha, que é onde as regras invioláveis viram pixel.
 *
 * O critério de aceite da WP-31 está em `descreve o vazio`: `nao_encontrado` tem de
 * mostrar **as fontes consultadas**. Sem isso, a tela diz "não achamos" sem dizer onde
 * procurou — e a diferença entre "procuramos em quatro fontes oficiais e nenhuma diz" e
 * "não achamos" é a diferença entre um produto sério e um chute.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { FieldRow } from './FieldRow'
import { formatarValor, rotularCampo } from '@/lib/formato'
import type { Campo, Evidencia } from '@/lib/tipos'

function evidencia(extra: Partial<Evidencia> = {}): Evidencia {
  return {
    evidence_id: 'e1',
    source_url: 'https://www.ford.com.br/picapes/ranger-raptor/',
    tier: 1,
    quote: 'Potência 397cv',
    captured_at: '2026-09-01T00:00:00Z',
    ...extra,
  }
}

function campo(extra: Partial<Campo> = {}): Campo {
  return {
    value: 397,
    unit: 'cv',
    status: 'verificado',
    confidence: 0.95,
    evidences: [evidencia()],
    conflicts: [],
    sources_checked: ['ford_site_versao'],
    ...extra,
  }
}

describe('formatarValor', () => {
  it('número sai com separador brasileiro e unidade', () => {
    expect(formatarValor(499000, 'BRL')).toBe('499.000 BRL')
  })

  it('booleano sai como sim/não, não como true/false', () => {
    expect(formatarValor(true)).toBe('sim')
    expect(formatarValor(false)).toBe('não')
  })

  it('lista sai legível, sem os underscores do valor canônico', () => {
    expect(formatarValor(['normal', 'off_road'])).toBe('normal · off road')
  })

  it('texto sozinho segue a mesma regra da lista: sem underscore na tela (QA-BUG-05)', () => {
    // Medido em 11/09/2026 na ficha da Raptor, a tela da cena 2: `motor_descricao` saía
    // como "3.0l_v6_bi_turbo" e `amortecedores` como um parágrafo inteiro em snake_case,
    // cortado no meio de uma palavra. A lista já era tratada; o texto sozinho, não.
    expect(formatarValor('3.0l_v6_bi_turbo')).toBe('3.0l v6 bi turbo')
    expect(formatarValor('4x4_sob_demanda')).toBe('4x4 sob demanda')
  })

  it('texto sem underscore fica como está, e a unidade continua ao lado', () => {
    expect(formatarValor('Full LED')).toBe('Full LED')
    expect(formatarValor('4x4', undefined)).toBe('4x4')
    expect(formatarValor('normal_sport', 'modos')).toBe('normal sport modos')
  })

  it('vazio sai como travessão', () => {
    expect(formatarValor(null)).toBe('sem valor')
    expect(formatarValor(undefined)).toBe('sem valor')
  })

  it('false NÃO é tratado como vazio', () => {
    // O erro clássico: `if (!valor)` transformaria "não tem teto solar" em "não sabemos".
    expect(formatarValor(false)).not.toBe('sem valor')
  })

  it('zero NÃO é tratado como vazio', () => {
    expect(formatarValor(0)).toBe('0')
  })
})

describe('rotularCampo', () => {
  it('troca underscore por espaço e capitaliza', () => {
    expect(rotularCampo('modos_escapamento')).toBe('Modos escapamento')
  })

  it('devolve o acento que o snake_case não comporta', () => {
    /* O nome do campo é ASCII por necessidade — é chave de JSON, de coluna e de URL. O
     * rótulo na tela é português. Sem isto, o Radar anunciava "Preco sugerido brl" e
     * "Modos direcao", que não são nomes de campo crus mas lêem como se fossem. */
    expect(rotularCampo('modos_direcao')).toBe('Modos direção')
    expect(rotularCampo('aspiracao')).toBe('Aspiração')
    expect(rotularCampo('consumo_rodoviario_kml')).toBe('Consumo rodoviário (km/l)')
  })

  it('a unidade do fim vira parênteses, escrita como se escreve', () => {
    expect(rotularCampo('preco_sugerido_brl')).toBe('Preço sugerido (R$)')
    expect(rotularCampo('potencia_cv')).toBe('Potência (cv)')
    expect(rotularCampo('torque_nm')).toBe('Torque (N·m)')
    expect(rotularCampo('airbags_qtd')).toBe('Airbags (quantidade)')
  })

  it('sigla fica em caixa alta', () => {
    expect(rotularCampo('codigo_fipe')).toBe('Código FIPE')
    expect(rotularCampo('adas_itens')).toBe('ADAS itens')
  })

  it('campo de uma palavra só nunca perde a palavra por ser unidade', () => {
    /* `tipo` e `direcao` são campos inteiros; se a regra de unidade valesse para o nome
     * todo, um campo chamado `s` viraria "(s)" e sumiria. */
    expect(rotularCampo('tipo')).toBe('Tipo')
    expect(rotularCampo('direcao')).toBe('Direção')
  })

  it('palavra que ninguém mapeou passa como veio, sem inventar acento', () => {
    expect(rotularCampo('carroceria_nova')).toBe('Carroceria nova')
  })
})

describe('todo campo do schema tem rótulo legível', () => {
  /**
   * A lista é a do `pipeline/schema.py`, e o teste que a mantém em sincronia com este
   * arquivo é `tests/api/test_rotulos_da_ficha.py` — em Python, onde o schema mora.
   * Aqui ficam os casos que a regra precisa acertar, e o alarme de regressão deles.
   */
  it.each([
    ['combustivel', 'Combustível'],
    ['fipe_referencia', 'FIPE referência'],
    ['entre_eixos_mm', 'Entre eixos (mm)'],
    ['velocidade_maxima_kmh', 'Velocidade máxima (km/h)'],
    ['camera_360', 'Câmera 360'],
  ])('%s vira "%s"', (campo, esperado) => {
    expect(rotularCampo(campo)).toBe(esperado)
  })
})

describe('FieldRow', () => {
  it('todo valor sai com etiqueta', () => {
    render(<FieldRow campo="potencia_cv" dados={campo()} />)
    expect(screen.getByTestId('badge-FATO')).toBeInTheDocument()
    expect(screen.getByTestId('valor-potencia_cv')).toHaveTextContent('397 cv')
  })

  it('campo simulado sai com etiqueta SIMULAÇÃO, não FATO', () => {
    render(<FieldRow campo="potencia_cv" dados={campo({ is_simulated: true })} />)
    expect(screen.getByTestId('badge-SIMULACAO')).toBeInTheDocument()
    expect(screen.queryByTestId('badge-FATO')).not.toBeInTheDocument()
  })

  describe('descreve o vazio', () => {
    it('nao_encontrado LISTA as fontes consultadas em vão', () => {
      render(
        <FieldRow
          campo="capacidade_reboque_kg"
          dados={campo({
            value: null,
            status: 'nao_encontrado',
            evidences: [],
            sources_checked: ['ford_site_versao', 'ford_ficha_tecnica'],
          })}
        />,
      )
      expect(screen.getByTestId('vazio-capacidade_reboque_kg')).toHaveTextContent(/2 fonte/)
      expect(screen.getByTestId('fontes-capacidade_reboque_kg')).toHaveTextContent(
        'ford_site_versao',
      )
    })

    it('nao_disponivel diz que a fonte afirma a ausência', () => {
      render(
        <FieldRow
          campo="camera_360"
          dados={campo({ value: null, status: 'nao_disponivel', evidences: [] })}
        />,
      )
      expect(screen.getByTestId('vazio-camera_360')).toHaveTextContent(/fonte oficial afirma/i)
    })

    it('os dois vazios exibem textos diferentes', () => {
      const { unmount } = render(
        <FieldRow
          campo="x"
          dados={campo({ value: null, status: 'nao_disponivel', evidences: [] })}
        />,
      )
      const disponivel = screen.getByTestId('vazio-x').textContent
      unmount()
      render(
        <FieldRow
          campo="x"
          dados={campo({ value: null, status: 'nao_encontrado', evidences: [] })}
        />,
      )
      expect(screen.getByTestId('vazio-x').textContent).not.toBe(disponivel)
    })
  })

  describe('divergência', () => {
    const divergente = campo({
      status: 'divergente',
      value: ['normal', 'sport', 'off_road'],
      unit: null,
      conflicts: [
        {
          value: ['normal', 'sport', 'baja'],
          evidence: evidencia({
            evidence_id: 'e2',
            source_url: 'file://referencia_interna.md',
            tier: 4,
            quote: '3 modos de amortecedor selecionáveis – Normal, Sport, Baja',
          }),
        },
      ],
    })

    it('mostra OS DOIS valores', () => {
      render(<FieldRow campo="modos_amortecedor" dados={divergente} />)
      const bloco = screen.getByTestId('divergencia-modos_amortecedor')
      expect(bloco).toHaveTextContent('off road')
      expect(bloco).toHaveTextContent('baja')
    })

    it('mostra a fonte de cada valor', () => {
      render(<FieldRow campo="modos_amortecedor" dados={divergente} />)
      const bloco = screen.getByTestId('divergencia-modos_amortecedor')
      expect(bloco).toHaveTextContent('ford.com.br')
      expect(bloco).toHaveTextContent('referencia_interna')
    })

    it('divergência é FATO: os dois lados têm evidência', () => {
      render(<FieldRow campo="modos_amortecedor" dados={divergente} />)
      expect(screen.getByTestId('badge-FATO')).toBeInTheDocument()
    })
  })

  describe('evidência', () => {
    it.each([
      ['2026-09-14T23:44:15.337214', '14/09/2026'],
      ['2026-09-14T21:42:01.918938', '14/09/2026'],
      ['2026-09-14T23:44:15Z', '14/09/2026'],
      ['2026-09-14T23:44:15-03:00', '15/09/2026'],
    ])('preserva o dia UTC da captura %s', async (captura, esperado) => {
      const usuario = userEvent.setup()
      render(
        <FieldRow
          campo="potencia_cv"
          dados={campo({ evidences: [evidencia({ captured_at: captura })] })}
        />,
      )
      await usuario.click(screen.getByTestId('ver-evidencia-potencia_cv'))
      expect(screen.getByTestId('gaveta-evidencia')).toHaveTextContent(esperado)
    })

    it('o clique abre a gaveta com o trecho verbatim e a data', async () => {
      const usuario = userEvent.setup()
      render(<FieldRow campo="potencia_cv" dados={campo()} />)

      await usuario.click(screen.getByTestId('ver-evidencia-potencia_cv'))

      const gaveta = screen.getByTestId('gaveta-evidencia')
      expect(gaveta).toHaveTextContent('Potência 397cv')
      expect(gaveta).toHaveTextContent('01/09/2026')
      expect(gaveta).toHaveTextContent('ford.com.br')
    })

    it('a gaveta explica o que o tier significa', async () => {
      const usuario = userEvent.setup()
      render(<FieldRow campo="potencia_cv" dados={campo()} />)
      await usuario.click(screen.getByTestId('ver-evidencia-potencia_cv'))
      // "tier 1" sozinho não diz nada a quem lê.
      expect(screen.getByTestId('gaveta-evidencia')).toHaveTextContent(/fonte oficial/i)
    })

    it('campo sem evidência não oferece o botão', () => {
      render(
        <FieldRow
          campo="x"
          dados={campo({ value: null, status: 'nao_encontrado', evidences: [] })}
        />,
      )
      expect(screen.queryByTestId('ver-evidencia-x')).not.toBeInTheDocument()
    })

    it('a gaveta escapa de um ancestral com transform de troca de rota (regressão)', async () => {
      // `Layout.tsx` anima cada página com `.rota-entra` (`transform: translateY`), e o
      // fill-mode `both` deixa esse transform aplicado para sempre depois da animação.
      // Qualquer `position:fixed` dentro dele passa a se ancorar no `.rota-entra` (a
      // página inteira), não na viewport — "ver evidência" abria uma gaveta fora da tela,
      // em branco. Achado em produção em 12/09/2026. A gaveta tem de escapar via portal.
      const usuario = userEvent.setup()
      const { container } = render(
        <div className="rota-entra">
          <FieldRow campo="potencia_cv" dados={campo()} />
        </div>,
      )

      await usuario.click(screen.getByTestId('ver-evidencia-potencia_cv'))
      const gaveta = screen.getByTestId('gaveta-evidencia')

      expect(container.contains(gaveta)).toBe(false)
      expect(document.body.contains(gaveta)).toBe(true)
    })
  })

  describe('modo showroom', () => {
    it('esconde tier e confiança (docs/12 §6.6: nada interno ao cliente)', async () => {
      const usuario = userEvent.setup()
      render(<FieldRow campo="potencia_cv" dados={campo()} showroom />)

      expect(screen.queryByText(/confiança/)).not.toBeInTheDocument()
      await usuario.click(screen.getByTestId('ver-evidencia-potencia_cv'))
      expect(screen.getByTestId('gaveta-evidencia')).not.toHaveTextContent(/tier 1/)
    })

    it('mantém fonte e data, que é o que o cliente confere depois', async () => {
      const usuario = userEvent.setup()
      render(<FieldRow campo="potencia_cv" dados={campo()} showroom />)
      await usuario.click(screen.getByTestId('ver-evidencia-potencia_cv'))
      const gaveta = screen.getByTestId('gaveta-evidencia')
      expect(gaveta).toHaveTextContent('ford.com.br')
      expect(gaveta).toHaveTextContent('01/09/2026')
    })

    it('a etiqueta continua lá, e maior', () => {
      render(<FieldRow campo="potencia_cv" dados={campo()} showroom />)
      expect(screen.getByTestId('badge-FATO')).toBeInTheDocument()
    })
  })
})
