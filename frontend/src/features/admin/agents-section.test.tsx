/**
 * AgentsSection tests — T12
 *
 * Verifies:
 * - Takes clientId as prop, NO client selector dropdown
 * - Lists agents for the given clientId
 * - Create agent form present
 * - Edit agent works (all existing functionality preserved)
 * - Voice tuning fields present
 * - Readiness checklist shown in edit
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { AgentsSection } from './agents-section'

function renderAgentsSection(clientId = 'demo-client') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AgentsSection clientId={clientId} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AgentsSection', () => {
  it('does NOT render a client selector dropdown', () => {
    renderAgentsSection()
    // No "Select Client" heading
    expect(screen.queryByText('Select Client')).not.toBeInTheDocument()
    // No combobox/select for client selection
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('shows loading state for agents initially', () => {
    renderAgentsSection()
    expect(screen.getByTestId('agents-loading')).toBeInTheDocument()
  })

  it('shows New Agent form section', async () => {
    renderAgentsSection()
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    expect(screen.getByText('New Agent')).toBeInTheDocument()
  })

  it('shows agents from MSW for the given clientId', async () => {
    renderAgentsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    expect(screen.getByText('primary-agent')).toBeInTheDocument()
  })

  it('shows the correct clientId header in the agents card', async () => {
    renderAgentsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    // The agents card shows the clientId
    expect(screen.getByText('demo-client')).toBeInTheDocument()
  })

  it('renders voice tuning column in agents table', async () => {
    renderAgentsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    expect(screen.getAllByText(/voice tuning/i).length).toBeGreaterThanOrEqual(1)
  })

  it('renders tools checkboxes in the create form', async () => {
    renderAgentsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('get_lead_details')).toBeInTheDocument()
    expect(screen.getByLabelText('register_interest')).toBeInTheDocument()
  })

  it('shows Edit button for each agent', async () => {
    renderAgentsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    expect(editButtons.length).toBeGreaterThan(0)
  })

  it('shows ElevenLabs Agent ID field when editing an agent', async () => {
    renderAgentsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    await userEvent.click(editButtons[0])
    expect(screen.getByLabelText(/ElevenLabs Agent ID/i)).toBeInTheDocument()
  })

  it('shows readiness checklist when editing an agent', async () => {
    renderAgentsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    await userEvent.click(editButtons[0])
    expect(screen.getByText(/readiness/i)).toBeInTheDocument()
  })

  it('shows "Ready for conversation" for a ready agent', async () => {
    renderAgentsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    // agent-001 is_conversation_ready=true
    await userEvent.click(editButtons[0])
    expect(screen.getByText(/ready for conversation/i)).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Copy URL behavior
// ──────────────────────────────────────────────────────────────────────────────

describe('AgentsSection copy URL button', () => {
  const writeTextMock = vi.fn().mockResolvedValue(undefined)

  beforeEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      writable: true,
      configurable: true,
    })
    writeTextMock.mockClear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('copy button calls clipboard.writeText with the custom_llm_url', async () => {
    renderAgentsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    await userEvent.click(editButtons[0])

    const copyButton = screen.getByRole('button', { name: /copy/i })
    await userEvent.click(copyButton)

    expect(writeTextMock).toHaveBeenCalledOnce()
    expect(writeTextMock).toHaveBeenCalledWith(
      '/api/v1/voice/demo-client/custom-llm/chat/completions',
    )
  })
})
