import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'
import { createQueryClient } from '../api/queries'
import { routes } from '../App'
import { createMockFetch, createMockState, type MockState } from '../mocks/mockApi'

/** Render the whole app at `path` against an in-memory mock of the API. */
export function renderApp(path = '/', overrides: Partial<MockState> = {}) {
  const state = createMockState(overrides)
  const fetchMock = vi.fn(createMockFetch(state))
  vi.stubGlobal('fetch', fetchMock)
  const client = createQueryClient()
  client.setDefaultOptions({
    queries: { ...client.getDefaultOptions().queries, retry: false, refetchOnWindowFocus: false },
  })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const utils = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { ...utils, state, router, client, fetchMock }
}
