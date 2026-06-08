/**
 * ClientDetailPage tests — T11
 *
 * Verifies:
 * - Renders detail page with data-testid
 * - Shows client ID from route params
 * - Renders a back link to /admin
 * - Shows Agents section header
 * - Shows Integrations section header
 * - Clicking back navigates to /admin
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

describe('ClientDetailPage', () => {
  it('renders the client detail page container', async () => {
    renderAt('/admin/clients/quintana-seguros')
    await waitFor(() => {
      expect(screen.getByTestId('client-detail-page')).toBeInTheDocument()
    })
  })

  it('shows the client ID from the route parameter', async () => {
    renderAt('/admin/clients/demo-client')
    await waitFor(() => {
      expect(screen.getByTestId('client-detail-page')).toBeInTheDocument()
    })
    expect(screen.getByText('demo-client')).toBeInTheDocument()
  })

  it('shows the client name after data loads', async () => {
    renderAt('/admin/clients/demo-client')
    await waitFor(() => {
      // MSW returns 'Demo Broker' for demo-client
      expect(screen.getByText('Demo Broker')).toBeInTheDocument()
    })
  })

  it('renders a "Back to clients" link to /admin', async () => {
    renderAt('/admin/clients/demo-client')
    await waitFor(() => {
      expect(screen.getByTestId('client-detail-page')).toBeInTheDocument()
    })
    const backLink = screen.getByRole('link', { name: /back/i })
    expect(backLink).toBeInTheDocument()
    expect(backLink).toHaveAttribute('href', '/admin')
  })

  it('clicking the back link navigates to /admin', async () => {
    renderAt('/admin/clients/demo-client')
    await waitFor(() => {
      expect(screen.getByTestId('client-detail-page')).toBeInTheDocument()
    })
    const backLink = screen.getByRole('link', { name: /back/i })
    await userEvent.click(backLink)
    // Should now show the clients list
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /clients/i })).toBeInTheDocument()
    })
  })

  it('renders Agents section', async () => {
    renderAt('/admin/clients/demo-client')
    await waitFor(() => {
      expect(screen.getByTestId('client-detail-page')).toBeInTheDocument()
    })
    // The Disclosure button for Agents section
    expect(screen.getByRole('button', { name: /^agents$/i })).toBeInTheDocument()
  })

  it('renders Integrations section', async () => {
    renderAt('/admin/clients/demo-client')
    await waitFor(() => {
      expect(screen.getByTestId('client-detail-page')).toBeInTheDocument()
    })
    // The Disclosure button for Integrations section
    expect(screen.getByRole('button', { name: /^integrations$/i })).toBeInTheDocument()
  })

  it('shows agents for the client (section starts expanded by default)', async () => {
    renderAt('/admin/clients/demo-client')
    await waitFor(() => {
      // MSW returns agents for demo-client
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    // Should show primary-agent from fixture
    await waitFor(() => {
      expect(screen.getByText('primary-agent')).toBeInTheDocument()
    })
  })
})
