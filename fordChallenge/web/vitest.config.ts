import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

/**
 * A configuracao de teste vive num arquivo proprio, e nao dentro de `vite.config.ts`.
 *
 * Motivo tecnico, nao estetico: o `vitest` traz uma copia aninhada do `vite`, e um bloco
 * `test` dentro do `defineConfig` do vite faz o TypeScript ver **dois** tipos `Plugin`
 * incompativeis — o erro tem doze niveis de aninhamento e nao diz o que fazer. Dois
 * arquivos, cada um com o seu `defineConfig`, e o caminho suportado pelas duas
 * ferramentas.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
