import { describe, it, expect } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { superadminMeFixture } from '../../../tests/mocks/auth'
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
  return { ...result, router, qc }
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

  it('keeps rendering children when a background refetch fails with a non-401 error', async () => {
    const { qc } = renderAt('/protected')
    expect(await screen.findByText('Protected content')).toBeInTheDocument()

    server.use(http.get('/api/v1/auth/me', () => HttpResponse.json({}, { status: 503 })))
    await act(async () => {
      await qc.refetchQueries({ queryKey: ['auth', 'me'] })
    })

    expect(qc.getQueryState(['auth', 'me'])?.status).toBe('error')
    // Let React commit the post-error render before asserting.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    expect(screen.getByText('Protected content')).toBeInTheDocument()
  })

  it('shows a retryable error instead of crashing when the first identity check fails', async () => {
    let meAvailable = false
    server.use(
      http.get('/api/v1/auth/me', () =>
        meAvailable
          ? HttpResponse.json(superadminMeFixture)
          : HttpResponse.json({}, { status: 503 }),
      ),
    )
    renderAt('/protected')

    // useMe retries one non-401 failure before reporting the error.
    expect(await screen.findByTestId('auth-error', {}, { timeout: 3000 })).toBeInTheDocument()
    meAvailable = true
    await userEvent.setup().click(screen.getByRole('button', { name: 'Reintentar' }))

    expect(await screen.findByText('Protected content')).toBeInTheDocument()
  })
})
