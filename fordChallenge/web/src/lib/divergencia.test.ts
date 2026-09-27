/**
 * "As fontes divergem" nem sempre é verdade — e quando não é, erra o fato e joga fora o
 * argumento. A matéria da Autoesporte sobre a Ranger Raptor traz os 5,8 s que a Ford
 * declara e os 6,5 s que a revista mediu: mesma URL, duas afirmações.
 */
import { describe, expect, it } from 'vitest'

import {
  FONTES_DIFERENTES,
  MESMA_FONTE_SEM_TIPO,
  sufixoDoTipo,
  textoDaDivergencia,
} from './divergencia'
import type { Campo, Evidencia } from './tipos'

const AUTOESPORTE =
  'https://autoesporte.globo.com/teste-ford-ranger-raptor-e-picape-que-acelera.ghtml'

function evidencia(extra: Partial<Evidencia> = {}): Evidencia {
  return {
    evidence_id: 'e1',
    source_url: AUTOESPORTE,
    tier: 3,
    quote: 'trecho',
    captured_at: '2026-09-01T00:00:00Z',
    ...extra,
  } as Evidencia
}

function campo(evidences: Evidencia[], conflitos: Evidencia[]): Campo {
  return {
    value: 5.8,
    unit: 's',
    status: 'divergente',
    confidence: 0.8,
    evidences,
    conflicts: conflitos.map((e, i) => ({ value: 6.5 + i, evidence: e })),
    sources_checked: [],
  } as Campo
}

describe('texto da divergência', () => {
  it('mesma fonte com os dois tipos: diz declarado × medido', () => {
    const texto = textoDaDivergencia(
      campo(
        [evidencia({ tipo_de_afirmacao: 'declarado' })],
        [evidencia({ evidence_id: 'e2', tipo_de_afirmacao: 'medido' })],
      ),
    )
    expect(texto).toBe('Mesma fonte, dois valores: declarado × medido.')
    expect(texto).not.toContain('fontes divergem')
  })

  it('URLs diferentes continuam sendo fontes que divergem', () => {
    const texto = textoDaDivergencia(
      campo(
        [evidencia({ source_url: 'https://www.ford.com.br/ranger', tipo_de_afirmacao: 'declarado' })],
        [evidencia({ evidence_id: 'e2', tipo_de_afirmacao: 'medido' })],
      ),
    )
    expect(texto).toBe(FONTES_DIFERENTES)
  })

  it('mesma fonte SEM os tipos não inventa "declarado × medido"', () => {
    // A igualdade de URL diz que a fonte é a mesma; ela não diz o que a fonte estava
    // fazendo. Evidência antiga tem `tipo_de_afirmacao` nulo, e a frase neutra é
    // verdadeira sem afirmar o que não se sabe.
    const texto = textoDaDivergencia(campo([evidencia()], [evidencia({ evidence_id: 'e2' })]))
    expect(texto).toBe(MESMA_FONTE_SEM_TIPO)
  })

  it('mesma fonte com UM tipo só também não arrisca', () => {
    const texto = textoDaDivergencia(
      campo([evidencia({ tipo_de_afirmacao: 'declarado' })], [evidencia({ evidence_id: 'e2' })]),
    )
    expect(texto).toBe(MESMA_FONTE_SEM_TIPO)
  })

  it('três evidências da mesma fonte com dois tipos ainda dizem os dois', () => {
    const texto = textoDaDivergencia(
      campo(
        [evidencia({ tipo_de_afirmacao: 'declarado' }), evidencia({ evidence_id: 'e3', tipo_de_afirmacao: 'declarado' })],
        [evidencia({ evidence_id: 'e2', tipo_de_afirmacao: 'medido' })],
      ),
    )
    expect(texto).toBe('Mesma fonte, dois valores: declarado × medido.')
  })

  it('o sufixo qualifica o valor na própria linha, e some quando não se sabe', () => {
    expect(sufixoDoTipo(evidencia({ tipo_de_afirmacao: 'medido' }))).toBe(' · medido')
    expect(sufixoDoTipo(evidencia())).toBe('')
    expect(sufixoDoTipo(undefined)).toBe('')
  })
})
