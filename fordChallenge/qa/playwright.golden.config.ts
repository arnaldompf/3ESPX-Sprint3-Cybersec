/**
 * O ensaio de palco: só o caminho dourado, com vídeo.
 *
 * Separado da configuração de regressão porque as duas coisas têm propósitos diferentes.
 * `playwright.config.ts` é portão de commit — rápido, sem vídeo, e **ignora** este
 * arquivo de teste. Este aqui existe para gerar `reports/demo/golden_path.webm`, o vídeo
 * de segurança da apresentação de 15/09, e leva perto de dois minutos.
 *
 * Rodar:
 *
 *     python scripts/task.py golden
 *     # ou, de dentro de qa/:  npx playwright test --config playwright.golden.config.ts
 */
import { defineConfig, devices } from '@playwright/test'

import base from './playwright.config'

export default defineConfig({
  ...base,
  testIgnore: [],
  testMatch: ['**/golden_path.spec.ts'],
  // O vídeo é gravado pelo próprio teste, que escolhe o tamanho de palco e salva o
  // arquivo no lugar certo. Aqui só não se atrapalha.
  reporter: [['list']],
  projects: [{ name: 'palco', use: { ...devices['Desktop Chrome'] } }],
})
