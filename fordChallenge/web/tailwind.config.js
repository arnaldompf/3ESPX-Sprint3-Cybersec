/** @type {import('tailwindcss').Config} */

/*
 * Os tokens de `design-kit/010_DESIGN.md`, uma vez.
 *
 * Cada cor aqui aponta para a variável CSS declarada em `src/index.css` — e não repete o
 * hexadecimal. Duas cópias do mesmo valor divergem na primeira correção, e a divergência
 * entre "a cor do Tailwind" e "a cor da variável" é invisível até alguém ver dois azuis
 * levemente diferentes na mesma tela.
 *
 * A escala de espaçamento é a padrão do Tailwind, que já é múltipla de 4; a regra de 8 é
 * de disciplina (usar 2, 3, 4, 6, 8, 12 = 8, 12, 16, 24, 32, 48 px) e está no teste de
 * anti-padrões, não no config: proibir `p-2.5` aqui quebraria o `gap-1.5` legítimo de um
 * ponto ao lado de uma palavra dentro de um pill de 22 px.
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'var(--canvas)',
        superficie: {
          DEFAULT: 'var(--surface)',
          2: 'var(--surface-2)',
        },
        borda: {
          DEFAULT: 'var(--border)',
          forte: 'var(--border-strong)',
        },
        tinta: {
          DEFAULT: 'var(--ink)',
          2: 'var(--ink-2)',
          3: 'var(--ink-3)',
        },
        marca: {
          950: 'var(--brand-950)',
          700: 'var(--brand-700)',
          600: 'var(--brand-600)',
          hover: 'var(--brand-600-hover)',
          50: 'var(--brand-50)',
        },
        // As tres etiquetas de `docs/13`. Cor E icone E texto: cor sozinha nao serve a
        // quem nao distingue verde de laranja, e a etiqueta e a informacao mais
        // importante da tela.
        fato: { DEFAULT: 'var(--fato)', fundo: 'var(--fato-fundo)' },
        inferencia: { DEFAULT: 'var(--inferencia)', fundo: 'var(--inferencia-fundo)' },
        simulacao: { DEFAULT: 'var(--simulacao)', fundo: 'var(--simulacao-fundo)' },
        // A quarta marca: ausencia de valor. Cinza, neutra, sempre com o motivo ao lado.
        semdado: { DEFAULT: 'var(--sem-dado)', fundo: 'var(--sem-dado-fundo)' },
        // A quinta: identidade vinda do nosso cadastro, nao de uma fonte externa.
        catalogo: { DEFAULT: 'var(--catalogo)', fundo: 'var(--catalogo-fundo)' },
        // Os quatro estados da matriz. `naoSabemos` tem o mesmo peso dos outros tres.
        ganhamos: { DEFAULT: 'var(--ganhamos)', fundo: 'var(--ganhamos-fundo)' },
        empate: { DEFAULT: 'var(--empate)', fundo: 'var(--empate-fundo)' },
        perdemos: { DEFAULT: 'var(--perdemos)', fundo: 'var(--perdemos-fundo)' },
        naoSabemos: { DEFAULT: 'var(--nao-sabemos)', fundo: 'var(--nao-sabemos-fundo)' },
        alta: 'var(--alta)',
        media: 'var(--media)',
        baixa: 'var(--baixa)',
        ruido: 'var(--ruido)',
      },
      fontFamily: {
        sans: ['var(--fonte-ui)'],
        mono: ['var(--fonte-mono)'],
      },
      fontSize: {
        // A escala de `010_DESIGN.md` §3. Nomes em portugues porque sao papeis, nao
        // tamanhos: trocar o valor de `corpo` nao deveria exigir renomear nada.
        meta: ['12px', { lineHeight: '16px' }],
        rotulo: ['13px', { lineHeight: '20px' }],
        corpo: ['14px', { lineHeight: '22px' }],
        destaque: ['16px', { lineHeight: '24px' }],
        cartao: ['18px', { lineHeight: '26px', fontWeight: '600' }],
        pagina: ['28px', { lineHeight: '34px', letterSpacing: '-0.01em', fontWeight: '600' }],
        numerao: ['40px', { lineHeight: '44px', fontWeight: '500' }],
        // Modo showroom: tipografia >= 18 pt (`docs/12` 6.6).
        showroom: ['1.25rem', { lineHeight: '1.75rem' }],
      },
      borderRadius: {
        controle: 'var(--raio-controle)',
        cartao: 'var(--raio-cartao)',
      },
      boxShadow: {
        cartao: 'var(--sombra-cartao)',
        flutuante: 'var(--sombra-flutuante)',
      },
      spacing: {
        sidebar: 'var(--sidebar)',
        'sidebar-recolhida': 'var(--sidebar-recolhida)',
        barra: 'var(--barra-superior)',
        gaveta: 'var(--gaveta)',
      },
      maxWidth: {
        conteudo: 'var(--conteudo)',
      },
      zIndex: {
        barra: 'var(--z-barra)',
        sidebar: 'var(--z-sidebar)',
        veu: 'var(--z-veu)',
        gaveta: 'var(--z-gaveta)',
      },
      transitionDuration: {
        // 150 ms em cor, opacidade e transform. Nada mais se move.
        DEFAULT: '150ms',
      },
    },
  },
  plugins: [],
}
