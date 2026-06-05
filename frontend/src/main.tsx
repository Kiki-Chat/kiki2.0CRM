import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App.tsx'
import { AuthProvider } from './auth/AuthProvider'
import { ThemeProvider } from './lib/theme'
import './index.css'

const queryClient = new QueryClient({
  // staleTime 30s: navigating between pages reuses cached data instead of
  // refetching on every mount. Mutations invalidate explicitly and realtime
  // broadcasts still refetch ['calls'], so freshness is preserved where it matters.
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1, staleTime: 30_000 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
