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
  // refetching on every mount. refetchOnWindowFocus/Reconnect are ON so changes
  // made by another user/account/tab surface when this tab regains focus or the
  // network reconnects — it only refetches once data is older than staleTime, so
  // the perf win on quick navigation is preserved.
  defaultOptions: {
    queries: { refetchOnWindowFocus: true, refetchOnReconnect: true, retry: 1, staleTime: 30_000 },
  },
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
