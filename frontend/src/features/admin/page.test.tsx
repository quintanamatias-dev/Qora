/**
 * AdminPage tests
 *
 * Verifies:
 * - Renders tabs (Clients, Agents)
 * - Default tab is Clients
 * - Switching tabs shows correct panel
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
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
    ],
    { initialEntries: ['/admin'] },
  )
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('AdminPage', () => {
  it('renders Clients and Agents tabs', () => {
    renderAdminPage()
    expect(screen.getByRole('tab', { name: 'Clients' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Agents' })).toBeInTheDocument()
  })

  it('default tab is Clients (aria-selected=true)', () => {
    renderAdminPage()
    const clientsTab = screen.getByRole('tab', { name: 'Clients' })
    const agentsTab = screen.getByRole('tab', { name: 'Agents' })
    expect(clientsTab).toHaveAttribute('aria-selected', 'true')
    expect(agentsTab).toHaveAttribute('aria-selected', 'false')
  })

  it('renders Create Client form by default (Clients tab)', () => {
    renderAdminPage()
    // "Create Client" appears as heading and button — use heading role to disambiguate
    expect(screen.getByRole('heading', { name: 'Create Client' })).toBeInTheDocument()
  })

  it('switching to Agents tab shows AgentsPanel', async () => {
    renderAdminPage()
    const agentsTab = screen.getByRole('tab', { name: 'Agents' })
    await userEvent.click(agentsTab)
    expect(screen.getByText('Select Client')).toBeInTheDocument()
  })

  it('switching back to Clients tab shows ClientsPanel', async () => {
    renderAdminPage()
    const agentsTab = screen.getByRole('tab', { name: 'Agents' })
    await userEvent.click(agentsTab)
    const clientsTab = screen.getByRole('tab', { name: 'Clients' })
    await userEvent.click(clientsTab)
    // "Create Client" appears as heading and button — use heading role to disambiguate
    expect(screen.getByRole('heading', { name: 'Create Client' })).toBeInTheDocument()
  })
})
