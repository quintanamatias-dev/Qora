import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { RequireAuth } from './require-auth'

function renderAt(initialEntry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const router = createMemoryRouter(
    [
      {
        path: '/protected',
        element: (
          <RequireAuth>
            <p>Protected content</p>
          </RequireAuth>
        ),
      },
      { path: '/login', element: <p>Login page</p> },
    ],
    { initialEntries: [initialEntry] },
  )
  const result = render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { ...result, router }
}

describe('RequireAuth', () => {
  it('shows a loading state before the identity check resolves', () => {
    renderAt('/protected')
    expect(screen.getByTestId('auth-loading')).toBeInTheDocument()
  })

  it('renders children once the identity check resolves', async () => {
    renderAt('/protected')
    expect(await screen.findByText('Protected content')).toBeInTheDocument()
  })

  it('redirects to /login with return_to on a 401', async () => {
    server.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({ error: { message: 'Session expired or invalid' } }, { status: 401 }),
      ),
    )
    const { router } = renderAt('/protected?tab=leads')
    expect(await screen.findByText('Login page')).toBeInTheDocument()
    expect(router.state.location.pathname + router.state.location.search).toBe(
      `/login?return_to=${encodeURIComponent('/protected?tab=leads')}`,
    )
  })
})
