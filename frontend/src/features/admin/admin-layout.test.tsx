/**
 * AdminLayout tests
 *
 * Verifies:
 * - Renders admin header with "QORA Admin" text
 * - Renders "Internal management panel" subtitle
 * - Renders Outlet content
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AdminLayout } from './admin-layout'

function renderAdminLayout(outletContent: React.ReactNode = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [
      {
        path: '/admin',
        element: <AdminLayout />,
        children: [
          {
            index: true,
            element: <>{outletContent}</>,
          },
        ],
      },
    ],
    { initialEntries: ['/admin'] },
  )
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('AdminLayout', () => {
  it('renders admin header with "QORA Admin" text', () => {
    renderAdminLayout()
    expect(screen.getByTestId('admin-header')).toBeInTheDocument()
    expect(screen.getByText('QORA Admin')).toBeInTheDocument()
  })

  it('renders "Internal management panel" subtitle', () => {
    renderAdminLayout()
    expect(screen.getByText('Internal management panel')).toBeInTheDocument()
  })

  it('renders Outlet content', () => {
    renderAdminLayout(<span data-testid="outlet-child">Hello from Outlet</span>)
    expect(screen.getByTestId('outlet-child')).toBeInTheDocument()
    expect(screen.getByText('Hello from Outlet')).toBeInTheDocument()
  })
})
