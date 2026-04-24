/**
 * AgentsPanel tests
 *
 * Verifies:
 * - Renders client selector
 * - Shows agents section when client selected
 * - Renders create agent form when client selected
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { AgentsPanel } from './agents-panel'

function renderAgentsPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AgentsPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AgentsPanel', () => {
  it('renders client selector heading', () => {
    renderAgentsPanel()
    expect(screen.getByText('Select Client')).toBeInTheDocument()
  })

  it('renders a select dropdown for client selection', () => {
    renderAgentsPanel()
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('does NOT show agents section before client is selected', () => {
    renderAgentsPanel()
    expect(screen.queryByText('Create Agent')).not.toBeInTheDocument()
  })

  it('populates client options from MSW data after loading', async () => {
    renderAgentsPanel()
    await waitFor(() => {
      // Active clients should appear in the dropdown
      expect(screen.getByText('Demo Broker (demo-client)')).toBeInTheDocument()
    })
  })

  it('shows agents section after selecting a client', async () => {
    renderAgentsPanel()
    // Wait for clients to load
    await waitFor(() => {
      expect(screen.getByText('Demo Broker (demo-client)')).toBeInTheDocument()
    })
    const select = screen.getByRole('combobox')
    await userEvent.selectOptions(select, 'demo-client')
    // "Create Agent" appears as heading and button — use heading role to disambiguate
    expect(screen.getByRole('heading', { name: 'Create Agent' })).toBeInTheDocument()
  })

  it('shows agent table after selecting a client and loading agents', async () => {
    renderAgentsPanel()
    await waitFor(() => {
      expect(screen.getByText('Demo Broker (demo-client)')).toBeInTheDocument()
    })
    const select = screen.getByRole('combobox')
    await userEvent.selectOptions(select, 'demo-client')
    // Wait for agents to load from MSW
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    // Agent data from MSW fixtures
    expect(screen.getByText('primary-agent')).toBeInTheDocument()
  })

  it('renders tools checkboxes in the Create Agent form', async () => {
    renderAgentsPanel()
    await waitFor(() => {
      expect(screen.getByText('Demo Broker (demo-client)')).toBeInTheDocument()
    })
    const select = screen.getByRole('combobox')
    await userEvent.selectOptions(select, 'demo-client')

    expect(screen.getByLabelText('get_lead_details')).toBeInTheDocument()
    expect(screen.getByLabelText('register_interest')).toBeInTheDocument()
    expect(screen.getByLabelText('mark_not_interested')).toBeInTheDocument()
    expect(screen.getByLabelText('schedule_followup')).toBeInTheDocument()
  })
})
