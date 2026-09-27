import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from '@/App'
import { sincronizar } from '@/lib/pesquisa'
import './index.css'

// Uma leitura do `/health` na subida, para saber o que está ligado neste ambiente. Não
// bloqueia a renderização: o padrão é desligado, e o botão do Pesquisador aparece quando
// a resposta chegar. Oferecer um botão que leva a 404 seria pior que oferecer um a menos.
void sincronizar()

// `basename="/app"` porque o FastAPI serve o build ali. Sem isso, o roteador trataria
// `/app/consulta` como rota desconhecida e cairia no 404 da propria SPA.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter
      basename={import.meta.env.BASE_URL}
      // As flags do v7 ligadas agora: o aviso aparecia em toda rodada de teste, e
      // aviso que se aprende a ignorar e pior que aviso nenhum.
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <App />
    </BrowserRouter>
  </StrictMode>,
)
