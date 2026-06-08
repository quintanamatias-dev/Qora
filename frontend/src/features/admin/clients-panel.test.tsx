/**
 * ClientsPanel tests
 *
 * Verifies:
 * - Renders Create Client form
 * - Renders clients table with data from MSW
 * - Shows loading state
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ClientsPanel } from './clients-panel'

function renderClientsPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ClientsPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ClientsPanel', () => {
  it('renders New Client form section', () => {
    renderClientsPanel()
    // "New Client" is the ALL-CAPS card section title in the updated admin design
    expect(screen.getByText('New Client')).toBeInTheDocument()
  })

  it('renders Client ID, Name, and Agent Name input fields', () => {
    renderClientsPanel()
    // Labels are uppercase
    expect(screen.getByLabelText(/client id/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^name$/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/agent name/i)).toBeInTheDocument()
  })

  it('shows loading state initially', () => {
    renderClientsPanel()
    expect(screen.getByTestId('clients-loading')).toBeInTheDocument()
  })

  it('renders clients table with data from MSW after loading', async () => {
    renderClientsPanel()
    // Wait for MSW to respond
    await waitFor(() => {
      expect(screen.queryByTestId('clients-loading')).not.toBeInTheDocument()
    })
    // Clients table should have data
    expect(screen.getByText('demo-client')).toBeInTheDocument()
    expect(screen.getByText('acme-motors')).toBeInTheDocument()
    expect(screen.getByText('Demo Broker')).toBeInTheDocument()
  })

  it('renders All Clients table heading', async () => {
    renderClientsPanel()
    // The "All Clients" card section title in the updated admin design
    await waitFor(() => {
      expect(screen.queryByTestId('clients-loading')).not.toBeInTheDocument()
    })
    expect(screen.getByText('All Clients')).toBeInTheDocument()
  })

  it('shows Edit and Deactivate buttons for active clients', async () => {
    renderClientsPanel()
    await waitFor(() => {
      expect(screen.queryByTestId('clients-loading')).not.toBeInTheDocument()
    })
    // Active clients have Edit buttons
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    expect(editButtons.length).toBeGreaterThan(0)
    // Active clients have Deactivate buttons
    const deactivateButtons = screen.getAllByRole('button', { name: /deactivate/i })
    expect(deactivateButtons.length).toBeGreaterThan(0)
  })
})
