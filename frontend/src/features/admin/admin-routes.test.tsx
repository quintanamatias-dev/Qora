/**
 * Admin nested routes tests — T9 (RED phase)
 *
 * Asserts:
 * - /admin renders a client list (AdminClientsListPage)
 * - /admin/clients/:clientId renders client detail page with the correct clientId
 * - Back navigation from detail → list works
 *
 * These tests will FAIL until T10 (client list page) and T11 (detail page + route)
 * are implemented.
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { routes } from '@/router'

function renderAt(initialEntry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const r = createMemoryRouter(routes, { initialEntries: [initialEntry] })
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={r} />
    </QueryClientProvider>,
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Admin route structure
// ──────────────────────────────────────────────────────────────────────────────

describe('Admin nested routes', () => {
  it('/admin renders a client list page with a "Clients" heading', async () => {
    renderAt('/admin')
    // The new AdminClientsListPage must render a "Clients" heading
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /clients/i })).toBeInTheDocument()
    })
  })

  it('/admin renders the admin header', () => {
    renderAt('/admin')
    expect(screen.getByTestId('admin-header')).toBeInTheDocument()
  })

  it('/admin does NOT render old tab navigation (no "Agents & Voice Config" tab)', async () => {
    renderAt('/admin')
    // The old tab-based navigation must be gone
    await waitFor(() => {
      expect(screen.queryByRole('tab', { name: /agents/i })).not.toBeInTheDocument()
    })
  })

  it('/admin shows a list of clients (table rows or cards)', async () => {
    renderAt('/admin')
    // MSW returns demo-client and acme-motors as active clients
    await waitFor(() => {
      expect(screen.getByText('demo-client')).toBeInTheDocument()
    })
  })

  it('/admin/clients/:clientId renders a client detail page with the client ID', async () => {
    renderAt('/admin/clients/quintana-seguros')
    // The detail page must show the clientId
    await waitFor(() => {
      expect(screen.getByTestId('client-detail-page')).toBeInTheDocument()
    })
    expect(screen.getByText('quintana-seguros')).toBeInTheDocument()
  })

  it('/admin/clients/:clientId renders a back navigation link to /admin', async () => {
    renderAt('/admin/clients/demo-client')
    await waitFor(() => {
      expect(screen.getByTestId('client-detail-page')).toBeInTheDocument()
    })
    // Must have a "Back to clients" link
    expect(screen.getByRole('link', { name: /back/i })).toBeInTheDocument()
  })

  it('clicking the back link navigates from detail to list', async () => {
    renderAt('/admin/clients/demo-client')
    await waitFor(() => {
      expect(screen.getByTestId('client-detail-page')).toBeInTheDocument()
    })

    const backLink = screen.getByRole('link', { name: /back/i })
    await userEvent.click(backLink)

    // After navigating back, the Clients list should be visible
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /clients/i })).toBeInTheDocument()
    })
  })

  it('/admin child routes include clients/:clientId', () => {
    const adminRoute = routes.find((r) => r.path === '/admin')
    expect(adminRoute).toBeDefined()
    const childPaths = adminRoute!.children?.map((c) => c.path).filter(Boolean) ?? []
    expect(childPaths).toContain('clients/:clientId')
  })
})
