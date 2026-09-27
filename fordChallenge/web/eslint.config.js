import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  // `e2e/` fica fora: importa `@playwright/test`, que nao esta instalado de
  // proposito (o Playwright baixa navegadores, e a regra da noite e rede so o
  // necessario). Ver o cabecalho de `e2e/viewport.spec.ts`.
  { ignores: ['dist', 'node_modules', 'coverage', 'e2e'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.node },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // `any` desliga a checagem exatamente onde os dados vem de fora (a resposta da API),
      // que e onde ela mais serve. Erro, nao aviso.
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
)
