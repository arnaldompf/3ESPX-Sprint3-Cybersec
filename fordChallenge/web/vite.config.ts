import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `base: '/app/'` porque o FastAPI serve o build estatico em /app (nao na raiz): sem isso
// os caminhos dos assets sairiam absolutos em `/assets/...` e o navegador pediria arquivo
// que nao existe ali.
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    // Em desenvolvimento o Vite serve a tela e repassa a API: sem o proxy, o navegador
    // barraria a chamada por CORS ainda que a API esteja no ar.
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    // O relatorio de tamanho existe para a decisao "sem bibliotecas de UI pesadas" ser
    // verificavel, e nao so declarada.
    reportCompressedSize: true,
  },
})
