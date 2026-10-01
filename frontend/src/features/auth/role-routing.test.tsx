import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { makeClientMe, superadminMeFixture } from '../../../tests/mocks/auth'
import { RoleHome, AdminRoleGuard, AppRoleGuard } from './role-routing'

function useMe(role: 'superadmin' | 'client', clientIds: string[] = ['acme-motors']) {
  server.use(
    http.get('/api/v1/auth/me', () =>
      HttpResponse.json(role === 'superadmin' ? superadminMeFixture : makeClientMe({ client_ids: clientIds })),
    ),
  )
}

function renderAt(initialEntry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const router = createMemoryRouter(
    [
      { path: '/', element: <RoleHome /> },
      { path: '*', element: <RoleHome /> },
      {
        path: '/admin',
        element: (
          <AdminRoleGuard>
            <p>Admin home</p>
          </AdminRoleGuard>
        ),
      },
      {
        path: '/app/:clientId',
        element: (
          <AppRoleGuard>
            <p>App home</p>
          </AppRoleGuard>
        ),
      },
      { path: '/app/:clientId/dashboard', element: <p>Own dashboard</p> },
      { path: '/login', element: <p>Login page</p> },
    ],
    { initialEntries: [initialEntry] },
  )
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('RoleHome', () => {
  it('sends a superadmin to /admin', async () => {
    useMe('superadmin')
    renderAt('/')
    expect(await screen.findByText('Admin home')).toBeInTheDocument()
  })

  it('sends a client to their own dashboard', async () => {
    useMe('client', ['acme-motors'])
    renderAt('/')
    expect(await screen.findByText('Own dashboard')).toBeInTheDocument()
  })

  it('handles the catch-all the same way', async () => {
    useMe('superadmin')
    renderAt('/totally-unknown')
    expect(await screen.findByText('Admin home')).toBeInTheDocument()
  })
})

describe('AdminRoleGuard', () => {
  it('lets a superadmin through', async () => {
    useMe('superadmin')
    renderAt('/admin')
    expect(await screen.findByText('Admin home')).toBeInTheDocument()
  })

  it('redirects a client visiting /admin to their own dashboard', async () => {
    useMe('client', ['acme-motors'])
    renderAt('/admin')
    expect(await screen.findByText('Own dashboard')).toBeInTheDocument()
  })
})

describe('AppRoleGuard', () => {
  it('lets a superadmin visit any client', async () => {
    useMe('superadmin')
    renderAt('/app/acme-motors')
    expect(await screen.findByText('App home')).toBeInTheDocument()
  })

  it('lets a client visit their own client', async () => {
    useMe('client', ['acme-motors'])
    renderAt('/app/acme-motors')
    expect(await screen.findByText('App home')).toBeInTheDocument()
  })

  it('redirects a client visiting a foreign clientId to their own dashboard', async () => {
    useMe('client', ['acme-motors'])
    renderAt('/app/someone-elses-client')
    expect(await screen.findByText('Own dashboard')).toBeInTheDocument()
  })
})
