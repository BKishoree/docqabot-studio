import '@fontsource/public-sans/400.css'
import '@fontsource/public-sans/500.css'
import '@fontsource/public-sans/600.css'
import '@fontsource/public-sans/700.css'
import '@fontsource/source-serif-4/400.css'
import '@fontsource/source-serif-4/600.css'
import './styles/tokens.css'
import './styles/app.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createQueryClient } from './api/queries'
import { App } from './App'

async function start() {
  // Optional: `VITE_MOCK_API=true npm run dev` serves the section 4 shapes from memory.
  if (import.meta.env.DEV && import.meta.env.VITE_MOCK_API === 'true') {
    const { createMockFetch, createMockState } = await import('./mocks/mockApi')
    const realFetch = window.fetch.bind(window)
    const mock = createMockFetch(createMockState({ latency: 400 }))
    window.fetch = (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      return url.includes('/api/v1/') ? mock(input, init) : realFetch(input, init)
    }
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App client={createQueryClient()} />
    </StrictMode>,
  )
}

void start()
