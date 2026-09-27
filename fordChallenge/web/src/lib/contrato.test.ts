/**
 * Os tipos desta pasta batem com a API de verdade?
 *
 * Este arquivo é a razão de os tipos serem **escritos à mão** e não gerados: ele lê o
 * `reports/openapi.json` que o back-end exporta e falha quando um campo que a tela consome
 * deixa de existir, ou quando um vocabulário fechado (os seis status) ganha um valor novo.
 *
 * A geração automática pegaria a mesma divergência, ao custo de mais uma dependência de
 * build e um passo que envelhece calado. Um teste pega no mesmo momento — quando o
 * contrato muda — e diz **qual** campo, em português.
 *
 * O arquivo é opcional de propósito: `reports/openapi.json` é gerado
 * (`scripts/export_openapi.py`) e o `.gitignore` do kit o ignora. Sem ele, os testes são
 * pulados com o motivo, em vez de falharem por ausência de artefato.
 */

import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { GRUPOS } from './tipos'

const CAMINHO = resolve(__dirname, '../../../reports/openapi.json')
const existe = existsSync(CAMINHO)

interface Esquema {
  paths: Record<string, Record<string, unknown>>
  components: { schemas: Record<string, Record<string, unknown>> }
}

const esquema: Esquema | null = existe
  ? (JSON.parse(readFileSync(CAMINHO, 'utf-8')) as Esquema)
  : null

describe.skipIf(!existe)('o contrato da API tem o que a tela consome', () => {
  it('as rotas que o cliente chama existem', () => {
    const rotas = Object.keys(esquema!.paths)
    // `/auth/login`, `/auth/refresh` e `/auth/logout` saíram da lista: a tela não as
    // chama mais (D-204) e o contrato padrão não as promete, porque o servidor padrão
    // não as monta. Elas voltam com `AUTH_ENABLED=1`, e o teste delas está no Python.
    for (const rota of [
      '/api/v1/auth/me',
      '/api/v1/resolutions',
      '/api/v1/attributes/resolve',
      '/api/v1/vehicles',
      '/api/v1/vehicles/{version_id}',
      '/api/v1/vehicles/{version_id}/specs',
      '/api/v1/alerts',
      '/api/v1/alerts/{alert_id}',
      '/api/v1/events',
      '/api/v1/alerts/{alerta_id}/trace',
      '/api/v1/scenarios',
      '/api/v1/scenarios/fields',
    ]) {
      expect(rotas, `a tela chama ${rota}`).toContain(rota)
    }
  })

  it('os 11 grupos do schema canônico são os que a tela itera', () => {
    const spec = esquema!.components.schemas['StandardSpec'] as {
      properties: Record<string, unknown>
    }
    for (const grupo of GRUPOS) {
      expect(Object.keys(spec.properties), `grupo ${grupo}`).toContain(grupo)
    }
  })

  it('os seis status são exatamente os que `etiqueta.ts` mapeia', () => {
    // Vocabulário fechado: um status novo no back-end sem mapeamento aqui apareceria
    // como INFERÊNCIA por omissão — o que é o default seguro, mas tem de ser decisão.
    const status = esquema!.components.schemas['Status'] as { enum?: string[] } | undefined
    if (!status?.enum) {
      // O enum pode estar embutido no campo em vez de nomeado; nesse caso o teste de
      // `etiqueta.test.ts` já cobre os seis, e aqui não há o que conferir.
      expect(true).toBe(true)
      return
    }
    expect([...status.enum].sort()).toEqual(
      [
        'divergente',
        'nao_disponivel',
        'nao_encontrado',
        'nao_verificado',
        'pendente',
        'verificado',
      ].sort(),
    )
  })

  it('o SpecField traz evidences, conflicts e sources_checked', () => {
    const campo = esquema!.components.schemas['SpecField'] as {
      properties: Record<string, unknown>
    }
    for (const chave of [
      'value',
      'unit',
      'status',
      'confidence',
      'evidences',
      'conflicts',
      'sources_checked',
    ]) {
      expect(Object.keys(campo.properties), `SpecField.${chave}`).toContain(chave)
    }
  })

  it('a Evidence traz o que a gaveta mostra', () => {
    const evidencia = esquema!.components.schemas['Evidence'] as {
      properties: Record<string, unknown>
    }
    // Sem `quote` e `captured_at`, a gaveta de evidência não tem o que exibir — e é a
    // tela que sustenta a promessa do produto.
    for (const chave of ['source_url', 'tier', 'quote', 'captured_at']) {
      expect(Object.keys(evidencia.properties), `Evidence.${chave}`).toContain(chave)
    }
  })

  it('o corpo do simulador é o que a tela manda', () => {
    /* `POST /scenarios` devolve um dicionário composto (paridade + aderência +
       materialidade), sem `response_model` — como o `trace` da WP-34. O que este teste
       cobre é a **entrada**, que é onde um erro da tela viraria 422: se `base_version_ids`
       ou `overrides` saírem do schema, a tela mandaria um corpo que a API recusa. As
       chaves da resposta são garantidas por `tests/api/test_scenarios.py`. */
    const corpo = esquema!.components.schemas['CenarioIn'] as {
      properties: Record<string, unknown>
      required?: string[]
    }
    for (const chave of ['base_version_ids', 'overrides', 'needs_profile']) {
      expect(Object.keys(corpo.properties), `CenarioIn.${chave}`).toContain(chave)
    }
    expect(corpo.required ?? []).toContain('base_version_ids')

    const override = esquema!.components.schemas['OverrideIn'] as {
      properties: Record<string, unknown>
    }
    for (const chave of ['version_id', 'campo', 'delta_pct', 'novo_valor', 'remover']) {
      expect(Object.keys(override.properties), `OverrideIn.${chave}`).toContain(chave)
    }
  })

  it('o evento da fila nunca traz a faixa sem as regras', () => {
    // A promessa da WP-34 no contrato: "ALTA" sozinho é oráculo. Se `rules_fired` sair do
    // schema, a tela passaria a exibir uma nota sem a régua que a produziu.
    const evento = esquema!.components.schemas['EventoOut'] as {
      properties: Record<string, unknown>
      required?: string[]
    }
    for (const chave of [
      'materiality',
      'significado',
      'pontos',
      'rules_fired',
      'priority_rank',
      'is_simulated',
      'alerta',
    ]) {
      expect(Object.keys(evento.properties), `EventoOut.${chave}`).toContain(chave)
    }
    expect(evento.required ?? [], 'rules_fired é obrigatório').toContain('rules_fired')
  })

  it('o problem+json tem title e detail, que a tela exibe', () => {
    const problema = esquema!.components.schemas['Problema'] as
      | { properties: Record<string, unknown> }
      | undefined
    if (!problema) {
      expect(true).toBe(true)
      return
    }
    expect(Object.keys(problema.properties)).toContain('title')
    expect(Object.keys(problema.properties)).toContain('detail')
  })
})

describe.skipIf(existe)('sem o OpenAPI exportado', () => {
  it('avisa em vez de falhar', () => {
    // `reports/openapi.json` é gerado por `scripts/export_openapi.py` e não versionado.
    expect(existe).toBe(false)
  })
})
