/**
 * Rotas. `/consulta` é a raiz porque é a primeira tela — **não há mais tela de entrada**.
 *
 * O que saiu, e por quê (D-204). Havia um portão de sessão (`Protegida`) que segurava as
 * páginas até a renovação do token terminar, e uma rota `/login` com quatro botões de
 * papel. Sem autenticação, as duas coisas deixaram de ter o que fazer: abrir o aplicativo
 * é abrir a Consulta, e o papel é um seletor na barra lateral. Uma tela a menos entre a
 * pessoa e o trabalho.
 *
 * `/login` continua **respondendo**, redirecionando para a Consulta: quem tem o endereço
 * antigo num favorito ou num slide não pode cair num 404.
 *
 * As páginas de casco que sobraram (Copiloto) existem como rota de verdade, com o escopo e
 * a WP declarados. Numa demo, rota vazia com plano à vista é diferente de link quebrado.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from '@/components/Layout'
import { Benchmark } from '@/pages/Benchmark'
import { Consulta } from '@/pages/Consulta'
import { Ficha } from '@/pages/Ficha'
import { Insights } from '@/pages/Insights'
import { Matriz } from '@/pages/Matriz'
import { Radar } from '@/pages/Radar'
import { Saude } from '@/pages/Saude'
import { Showroom } from '@/pages/Showroom'
import { Simulador } from '@/pages/Simulador'
import { Shell } from '@/pages/Shell'

// `retry: false` de proposito: um 404 nao melhora na segunda tentativa, e repetir esconde
// o erro do usuario por segundos. `staleTime` de 30 s porque ficha nao muda a cada clique.
const cliente = new QueryClient({
  defaultOptions: {
    queries: { retry: false, staleTime: 30_000, refetchOnWindowFocus: false },
  },
})

export function App() {
  return (
    <QueryClientProvider client={cliente}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/consulta" replace />} />
          {/* O endereço da tela de entrada que não existe mais. Redireciona em vez de
              devolver 404: ele está em slides, favoritos e no roteiro antigo. */}
          <Route path="/login" element={<Navigate to="/consulta" replace />} />
          <Route path="/consulta" element={<Consulta />} />
          <Route path="/pesquisa" element={<Navigate to="/consulta" replace />} />
          <Route path="/ficha/:versionId" element={<Ficha />} />
          <Route path="/radar" element={<Radar />} />
          <Route path="/showroom" element={<Showroom />} />
          <Route path="/matriz" element={<Matriz />} />
          <Route path="/benchmark" element={<Benchmark />} />
          <Route path="/saude" element={<Saude />} />
          {/* Fora da barra de navegação de propósito (ver `Layout.tsx`): a rota
              existe para não dar link quebrado a quem tem o endereço, e diz onde o
              fluxo realmente está. */}
          <Route
            path="/copiloto"
            element={
              <Shell
                titulo="Copiloto"
                wp="WP-27"
                descricao="O fluxo que os documentos chamam de Copiloto está no Showroom: perfil do cliente, comparação, custo de uso, argumentário e documento. Esta rota não é uma segunda tela: é um atalho para lá."
                itens={[
                  'abra Showroom na navegação lateral',
                  'o que falta aqui é a resposta em linguagem natural a pergunta livre, com a evidência de cada afirmação anexada',
                  'pergunta sem evidência recebe "não sabemos", não um chute',
                ]}
              />
            }
          />
          <Route path="/insights" element={<Insights />} />
          <Route path="/simulador" element={<Simulador />} />
          <Route
            path="*"
            element={
              <Shell
                titulo="Página não encontrada"
                wp="nenhuma"
                descricao="Este endereço não existe nesta versão do app."
                itens={['use a navegação lateral']}
              />
            }
          />
        </Route>
      </Routes>
    </QueryClientProvider>
  )
}
