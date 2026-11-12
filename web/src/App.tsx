import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { createBrowserRouter, RouterProvider, useLocation, type RouteObject } from 'react-router'
import { Shell } from './components/Shell'
import { AskScreen } from './screens/AskScreen'
import { LibraryScreen } from './screens/LibraryScreen'
import { NotFoundScreen } from './screens/NotFoundScreen'
import { StatusScreen } from './screens/StatusScreen'

const TITLES: Record<string, string> = {
  '/': 'Ask',
  '/library': 'Library',
  '/status': 'System status',
}

/** Sets document.title per route. */
function TitleSync() {
  const { pathname } = useLocation()
  useEffect(() => {
    const name = TITLES[pathname] ?? (pathname.startsWith('/c/') ? 'Conversation' : 'Not found')
    document.title = `${name} · DocQABot Studio`
  }, [pathname])
  return null
}

function Root() {
  return (
    <>
      <TitleSync />
      <Shell />
    </>
  )
}

// Reserved by the server (DESIGN 2.4): /api /upload /documents /ask /docs /redoc /openapi.json /assets.
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Root />,
    children: [
      { index: true, element: <AskScreen /> },
      { path: 'c/:conversationId', element: <AskScreen /> },
      { path: 'library', element: <LibraryScreen /> },
      { path: 'status', element: <StatusScreen /> },
      { path: '*', element: <NotFoundScreen /> },
    ],
  },
]

export function App({ client }: { client: QueryClient }) {
  const [router] = useState(() => createBrowserRouter(routes))
  return (
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
