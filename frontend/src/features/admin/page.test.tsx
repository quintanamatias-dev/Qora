/**
 * AdminPage tests
 *
 * Verifies:
 * - Renders tabs (Clients, Agents & Voice Config)
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
  it('renders Clients and Agents & Voice Config tabs', () => {
    renderAdminPage()
    expect(screen.getByRole('tab', { name: 'Clients' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Agents & Voice Config' })).toBeInTheDocument()
  })

  it('default tab is Clients (aria-selected=true)', () => {
    renderAdminPage()
    const clientsTab = screen.getByRole('tab', { name: 'Clients' })
    const agentsTab = screen.getByRole('tab', { name: 'Agents & Voice Config' })
    expect(clientsTab).toHaveAttribute('aria-selected', 'true')
    expect(agentsTab).toHaveAttribute('aria-selected', 'false')
  })

  it('renders New Client section by default (Clients tab)', () => {
    renderAdminPage()
    // "New Client" is the ALL-CAPS card title in the updated admin design
    expect(screen.getByText('New Client')).toBeInTheDocument()
  })

  it('switching to Agents & Voice Config tab shows AgentsPanel', async () => {
    renderAdminPage()
    const agentsTab = screen.getByRole('tab', { name: 'Agents & Voice Config' })
    await userEvent.click(agentsTab)
    expect(screen.getByText('Select Client')).toBeInTheDocument()
  })

  it('switching back to Clients tab shows ClientsPanel', async () => {
    renderAdminPage()
    const agentsTab = screen.getByRole('tab', { name: 'Agents & Voice Config' })
    await userEvent.click(agentsTab)
    const clientsTab = screen.getByRole('tab', { name: 'Clients' })
    await userEvent.click(clientsTab)
    // "New Client" is the ALL-CAPS card title in the updated admin design
    expect(screen.getByText('New Client')).toBeInTheDocument()
  })
})
