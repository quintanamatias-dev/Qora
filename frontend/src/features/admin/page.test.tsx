/**
 * AdminClientsListPage tests
 *
 * Verifies:
 * - Renders "Clients" heading
 * - Shows client list from MSW
 * - "New Client" form appears on toggle
 * - Client rows are clickable → navigate to /admin/clients/:clientId
 * - Preserves edit and deactivate actions
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AdminPage } from './page'

function renderAdminPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [
      {
        path: '/admin',
        element: <AdminPage />,
      },
      {
        path: '/admin/clients/:clientId',
        element: <div data-testid="mock-detail-page">Detail Page</div>,
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

describe('AdminClientsListPage', () => {
  it('renders a "Clients" heading', () => {
    renderAdminPage()
    expect(screen.getByRole('heading', { name: /clients/i })).toBeInTheDocument()
  })

  it('renders "Manage your Qora clients" subtitle', () => {
    renderAdminPage()
    expect(screen.getByText(/manage your qora clients/i)).toBeInTheDocument()
  })

  it('shows loading state initially', () => {
    renderAdminPage()
    expect(screen.getByTestId('clients-loading')).toBeInTheDocument()
  })

  it('renders All Clients table after loading', async () => {
    renderAdminPage()
    await waitFor(() => {
      expect(screen.queryByTestId('clients-loading')).not.toBeInTheDocument()
    })
    expect(screen.getByText('All Clients')).toBeInTheDocument()
  })

  it('shows client IDs and names from MSW data', async () => {
    renderAdminPage()
    await waitFor(() => {
      expect(screen.queryByTestId('clients-loading')).not.toBeInTheDocument()
    })
    expect(screen.getByText('demo-client')).toBeInTheDocument()
    expect(screen.getByText('Demo Broker')).toBeInTheDocument()
    expect(screen.getByText('acme-motors')).toBeInTheDocument()
  })

  it('does NOT render old tab navigation', () => {
    renderAdminPage()
    expect(screen.queryByRole('tab', { name: /agents/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /clients/i })).not.toBeInTheDocument()
  })

  it('shows + New Client button', () => {
    renderAdminPage()
    expect(screen.getByRole('button', { name: /new client/i })).toBeInTheDocument()
  })

  it('clicking + New Client button shows the create form', async () => {
    renderAdminPage()
    const newBtn = screen.getByRole('button', { name: /new client/i })
    await userEvent.click(newBtn)
    // "New Client" is the ALL-CAPS card section title in the create form
    expect(screen.getByText('New Client')).toBeInTheDocument()
    expect(screen.getByLabelText(/client id/i)).toBeInTheDocument()
  })

  it('shows Edit and Deactivate buttons for active clients', async () => {
    renderAdminPage()
    await waitFor(() => {
      expect(screen.queryByTestId('clients-loading')).not.toBeInTheDocument()
    })
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    expect(editButtons.length).toBeGreaterThan(0)
    const deactivateButtons = screen.getAllByRole('button', { name: /deactivate/i })
    expect(deactivateButtons.length).toBeGreaterThan(0)
  })

  it('clicking a client row navigates to /admin/clients/:clientId', async () => {
    renderAdminPage()
    await waitFor(() => {
      expect(screen.queryByTestId('clients-loading')).not.toBeInTheDocument()
    })
    // Click the demo-client row
    const row = screen.getByTestId('client-row-demo-client')
    await userEvent.click(row)
    // Should navigate to the detail page mock
    await waitFor(() => {
      expect(screen.getByTestId('mock-detail-page')).toBeInTheDocument()
    })
  })
})
