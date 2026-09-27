/**
 * Configuração dos testes de regressão do QA (11/09/2026).
 *
 * Estes testes rodam contra o **sistema de pé**, subido por `scripts/demo/up.ps1`
 * (ou `up.sh`). Não sobem servidor sozinhos de propósito: o alvo é a mesma máquina
 * e a mesma base que a apresentação vai usar, não um ambiente paralelo que passa
 * verde enquanto a demo quebra.
 *
 * Rodar:
 *   cd web && npx playwright test --config ../qa/playwright.config.ts
 *
 * Se a API não estiver no ar, a suíte falha na primeira navegação com o endereço
 * na mensagem — que é a informação certa para quem estiver rodando.
 */
import { defineConfig, devices } from '@playwright/test'

const BASE = process.env.SPECRADAR_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  testDir: './e2e',
  /**
   * O caminho dourado fica **fora** da rodada padrão.
   *
   * Ele grava vídeo, percorre as treze cenas e leva perto de dois minutos — é o ensaio de
   * palco, não portão de commit. `verify-quick` roda a regressão; o vídeo se regera com
   * `python scripts/task.py golden`, que usa `playwright.golden.config.ts`.
   */
  testIgnore: ['**/golden_path.spec.ts'],
  // Um worker só: a base é compartilhada e alguns cenários escrevem nela
  // (registrar fechou/perdeu). Paralelismo aqui trocaria bug real por flaky.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  // 120 s: quando a cota de 60 requisições por minuto estoura no meio da suíte, o
  // ajudante espera a janela virar (~62 s) e tenta de novo. Com 60 s o teste morria
  // esperando — e o defeito relatado seria o do ensaio, não o do produto.
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { outputFolder: '../reports/qa-html', open: 'never' }]],
  outputDir: '../reports/qa-artefatos',
  use: {
    baseURL: BASE,
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    locale: 'pt-BR',
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],
})
