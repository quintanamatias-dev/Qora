/**
 * AgentsPanel tests
 *
 * Verifies:
 * - Renders client selector
 * - Shows agents section when client selected
 * - Renders create agent form when client selected
 * - New fields: elevenlabs_agent_id, knowledge_base, temperature, max_tokens
 * - Readiness checklist reflects agent state
 * - Custom LLM URL copy button writes to clipboard
 * - Voice ID explainer is visible
 * - Not-ready agents display missing ElevenLabs ID / missing prompt indicators
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { AgentsPanel, computeReadinessChecklist } from './agents-panel'
import type { Agent } from '@/api/types'

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

// ──────────────────────────────────────────────────────────────────────────────
// computeReadinessChecklist — pure function unit tests
// ──────────────────────────────────────────────────────────────────────────────

describe('computeReadinessChecklist', () => {
  const readyAgent: Agent = {
    agent_id: 'a1',
    client_id: 'c1',
    slug: 'qora-explainer',
    name: 'Qora Explainer',
    voice_id: 'v1',
    model: 'gpt-4o',
    system_prompt: 'You are Sofia, an insurance agent.',
    tools_enabled: [],
    is_active: true,
    is_default: true,
    created_at: '2026-01-01T00:00:00Z',
    // New fields
    elevenlabs_agent_id: 'el_abc123',
    knowledge_base: null,
    temperature: 0.7,
    max_tokens: 512,
    custom_llm_url: '/api/v1/voice/c1/custom-llm/chat/completions',
    has_prompt: true,
    has_elevenlabs_agent_id: true,
    is_conversation_ready: true,
  }

  it('returns all checks passing when agent is fully configured', () => {
    const checks = computeReadinessChecklist(readyAgent)
    expect(checks).toHaveLength(3)
    expect(checks.every((c) => c.ready)).toBe(true)
    // Each check has a label
    expect(checks[0].label).toBeTruthy()
    expect(checks[1].label).toBeTruthy()
    expect(checks[2].label).toBeTruthy()
  })

  it('returns ElevenLabs agent ID check as not ready when elevenlabs_agent_id is null', () => {
    const notReadyAgent: Agent = {
      ...readyAgent,
      elevenlabs_agent_id: null,
      has_elevenlabs_agent_id: false,
      is_conversation_ready: false,
    }
    const checks = computeReadinessChecklist(notReadyAgent)
    const elCheck = checks.find((c) => c.label.toLowerCase().includes('elevenlabs'))
    expect(elCheck).toBeDefined()
    expect(elCheck!.ready).toBe(false)
    // Overall: system_prompt check should still be ready
    const promptCheck = checks.find((c) => c.label.toLowerCase().includes('prompt'))
    expect(promptCheck!.ready).toBe(true)
  })

  it('returns prompt check as not ready when system_prompt is empty', () => {
    const noPromptAgent: Agent = {
      ...readyAgent,
      system_prompt: '',
      has_prompt: false,
      is_conversation_ready: false,
    }
    const checks = computeReadinessChecklist(noPromptAgent)
    const promptCheck = checks.find((c) => c.label.toLowerCase().includes('prompt'))
    expect(promptCheck).toBeDefined()
    expect(promptCheck!.ready).toBe(false)
    // EL check should still be ready
    const elCheck = checks.find((c) => c.label.toLowerCase().includes('elevenlabs'))
    expect(elCheck!.ready).toBe(true)
  })

  it('returns all checks failing when both prompt and elevenlabs_agent_id are missing', () => {
    const emptyAgent: Agent = {
      ...readyAgent,
      system_prompt: null,
      elevenlabs_agent_id: null,
      has_prompt: false,
      has_elevenlabs_agent_id: false,
      is_conversation_ready: false,
      // custom_llm_url is always present (server-computed)
    }
    const checks = computeReadinessChecklist(emptyAgent)
    const promptCheck = checks.find((c) => c.label.toLowerCase().includes('prompt'))
    const elCheck = checks.find((c) => c.label.toLowerCase().includes('elevenlabs'))
    const urlCheck = checks.find((c) => c.label.toLowerCase().includes('url'))
    expect(promptCheck!.ready).toBe(false)
    expect(elCheck!.ready).toBe(false)
    // custom_llm_url is always computed by server, should be ready
    expect(urlCheck!.ready).toBe(true)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Edit form — new fields and readiness UI
// ──────────────────────────────────────────────────────────────────────────────

describe('AgentsPanel edit form — new fields', () => {
  async function openEditPanel() {
    renderAgentsPanel()
    await waitFor(() => {
      expect(screen.getByText('Demo Broker (demo-client)')).toBeInTheDocument()
    })
    const select = screen.getByRole('combobox')
    await userEvent.selectOptions(select, 'demo-client')
    // Wait for agents to load
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    // Click Edit on the first agent
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    await userEvent.click(editButtons[0])
  }

  it('shows ElevenLabs Agent ID field in the edit form', async () => {
    await openEditPanel()
    expect(screen.getByLabelText(/ElevenLabs Agent ID/i)).toBeInTheDocument()
  })

  it('shows Knowledge Base field in the edit form', async () => {
    await openEditPanel()
    expect(screen.getByLabelText(/Knowledge Base/i)).toBeInTheDocument()
  })

  it('shows Temperature field in the edit form', async () => {
    await openEditPanel()
    expect(screen.getByLabelText(/Temperature/i)).toBeInTheDocument()
  })

  it('shows Max Tokens field in the edit form', async () => {
    await openEditPanel()
    expect(screen.getByLabelText(/Max Tokens/i)).toBeInTheDocument()
  })

  it('shows a copy button for the Custom LLM URL', async () => {
    await openEditPanel()
    expect(screen.getByRole('button', { name: /copy/i })).toBeInTheDocument()
  })

  it('shows voice ID explainer note in the edit form', async () => {
    await openEditPanel()
    // "ElevenLabs dashboard" appears at least once (voice explainer note)
    const notes = screen.getAllByText(/ElevenLabs dashboard/i)
    expect(notes.length).toBeGreaterThanOrEqual(1)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Readiness checklist UI
// ──────────────────────────────────────────────────────────────────────────────

describe('AgentsPanel readiness checklist', () => {
  it('shows readiness section heading in the edit form', async () => {
    renderAgentsPanel()
    await waitFor(() => {
      expect(screen.getByText('Demo Broker (demo-client)')).toBeInTheDocument()
    })
    const select = screen.getByRole('combobox')
    await userEvent.selectOptions(select, 'demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    await userEvent.click(editButtons[0])

    expect(screen.getByText(/readiness/i)).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Copy button — clipboard behavior
// ──────────────────────────────────────────────────────────────────────────────

describe('AgentsPanel copy URL button', () => {
  // jsdom does not implement navigator.clipboard — mock it per test block
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

  it('calls navigator.clipboard.writeText with the custom_llm_url when Copy is clicked', async () => {
    renderAgentsPanel()
    await waitFor(() => {
      expect(screen.getByText('Demo Broker (demo-client)')).toBeInTheDocument()
    })
    const select = screen.getByRole('combobox')
    await userEvent.selectOptions(select, 'demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    // Open edit panel for primary-agent (agent-001) — has custom_llm_url set
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    await userEvent.click(editButtons[0])

    // The URL from the fixture for agent-001
    const expectedUrl = '/api/v1/voice/demo-client/custom-llm/chat/completions'

    const copyButton = screen.getByRole('button', { name: /copy/i })
    await userEvent.click(copyButton)

    expect(writeTextMock).toHaveBeenCalledOnce()
    expect(writeTextMock).toHaveBeenCalledWith(expectedUrl)
  })

  it('shows a toast confirmation after copying the URL', async () => {
    renderAgentsPanel()
    await waitFor(() => {
      expect(screen.getByText('Demo Broker (demo-client)')).toBeInTheDocument()
    })
    const select = screen.getByRole('combobox')
    await userEvent.selectOptions(select, 'demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    await userEvent.click(editButtons[0])

    const copyButton = screen.getByRole('button', { name: /copy/i })
    await userEvent.click(copyButton)

    // Toast should appear confirming the copy
    await waitFor(() => {
      expect(screen.getByText(/custom llm url copied/i)).toBeInTheDocument()
    })
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Not-ready agent readiness UI — missing indicators
// ──────────────────────────────────────────────────────────────────────────────

describe('AgentsPanel not-ready readiness UI', () => {
  async function openSecondAgentEditPanel() {
    renderAgentsPanel()
    await waitFor(() => {
      expect(screen.getByText('Demo Broker (demo-client)')).toBeInTheDocument()
    })
    const select = screen.getByRole('combobox')
    await userEvent.selectOptions(select, 'demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    // Click Edit on the second agent (secondary-agent: no prompt, no EL ID)
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    await userEvent.click(editButtons[1])
  }

  it('displays ElevenLabs agent ID check as not-ready (✗) for an agent missing the ID', async () => {
    await openSecondAgentEditPanel()

    // The readiness list items are present — find the ElevenLabs ID row
    // The label text is "ElevenLabs agent ID bound"
    const elLabel = screen.getByText(/ElevenLabs agent ID bound/i)
    expect(elLabel).toBeInTheDocument()

    // The not-ready indicator (✗) should be present alongside the label
    // The ✗ icon and label are siblings inside a <li>
    const listItem = elLabel.closest('li')
    expect(listItem).not.toBeNull()
    expect(listItem!.textContent).toContain('✗')
  })

  it('displays system prompt check as not-ready (✗) for an agent with no prompt', async () => {
    await openSecondAgentEditPanel()

    // The label "System prompt configured" should show ✗
    const promptLabel = screen.getByText(/system prompt configured/i)
    expect(promptLabel).toBeInTheDocument()

    const listItem = promptLabel.closest('li')
    expect(listItem).not.toBeNull()
    expect(listItem!.textContent).toContain('✗')
  })

  it('displays Custom LLM URL check as ready (✓) even for not-ready agent (URL is always computed)', async () => {
    await openSecondAgentEditPanel()

    // custom_llm_url is server-computed and always present even for not-ready agents
    const urlLabel = screen.getByText(/Custom LLM URL available/i)
    expect(urlLabel).toBeInTheDocument()

    const listItem = urlLabel.closest('li')
    expect(listItem).not.toBeNull()
    expect(listItem!.textContent).toContain('✓')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Overall readiness indicator — is_conversation_ready banner
// ──────────────────────────────────────────────────────────────────────────────

describe('AgentsPanel overall readiness indicator', () => {
  async function openFirstAgentEditPanel() {
    renderAgentsPanel()
    await waitFor(() => {
      expect(screen.getByText('Demo Broker (demo-client)')).toBeInTheDocument()
    })
    const select = screen.getByRole('combobox')
    await userEvent.selectOptions(select, 'demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    // agent-001: is_conversation_ready=true
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    await userEvent.click(editButtons[0])
  }

  async function openSecondAgentEditPanel() {
    renderAgentsPanel()
    await waitFor(() => {
      expect(screen.getByText('Demo Broker (demo-client)')).toBeInTheDocument()
    })
    const select = screen.getByRole('combobox')
    await userEvent.selectOptions(select, 'demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    // agent-002: is_conversation_ready=false
    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    await userEvent.click(editButtons[1])
  }

  it('shows "Ready for conversation" when agent is_conversation_ready=true', async () => {
    await openFirstAgentEditPanel()
    expect(screen.getByText(/ready for conversation/i)).toBeInTheDocument()
  })

  it('shows "Not ready for conversation" when agent is_conversation_ready=false', async () => {
    await openSecondAgentEditPanel()
    expect(screen.getByText(/not ready for conversation/i)).toBeInTheDocument()
  })
})
