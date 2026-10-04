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
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { AgentsSection } from './agents-section'
import type { AgentConfigRevision, EffectiveConfig } from '@/api/types'

/** Minimal effective-config fixture — overridden per-test via server.use(). */
function effectiveConfigFixture(overrides?: Partial<EffectiveConfig['fields']>): EffectiveConfig {
  return {
    standard_version: '2026-10-02.1',
    config_incomplete: false,
    missing_required_fields: [],
    fields: {
      system_prompt: { value: 'You are a helpful insurance agent.', provenance: 'agent', policy: 'agent_required' },
      goal: { value: null, provenance: 'agent', policy: 'agent_required' },
      voice_id: { value: 'voice-001', provenance: 'agent', policy: 'agent_required' },
      temperature: { value: 0.7, provenance: 'standard', policy: 'overridable' },
      max_tokens: { value: 512, provenance: 'standard', policy: 'overridable' },
      tts_speed: { value: 0.95, provenance: 'standard', policy: 'overridable' },
      tts_stability: { value: 0.4, provenance: 'standard', policy: 'overridable' },
      tts_similarity_boost: { value: 0.75, provenance: 'standard', policy: 'overridable' },
      tools_enabled: { value: ['get_lead_details'], provenance: 'standard', policy: 'overridable' },
      ...overrides,
    },
  }
}

beforeEach(() => {
  // Default: no revisions yet — avoids noisy MSW "unmatched request" warnings
  // from tests outside the revisions-panel describe block below, which open
  // the same edit panel without caring about revision history.
  server.use(
    http.get('/api/v1/clients/:clientId/agents/:agentId/revisions', () => HttpResponse.json([])),
    http.get('/api/v1/clients/:clientId/agents/:agentId/effective-config', () =>
      HttpResponse.json(effectiveConfigFixture()),
    ),
  )
})

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
    expect(screen.getByLabelText('get_lead_profile')).toBeInTheDocument()
    expect(screen.getByLabelText('get_lead_history')).toBeInTheDocument()
    expect(screen.getByLabelText('get_lead_pain_points')).toBeInTheDocument()
    expect(screen.getByLabelText('capture_data')).toBeInTheDocument()
    expect(screen.queryByLabelText('register_interest')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('mark_not_interested')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('schedule_followup')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('load_skill')).not.toBeInTheDocument()
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

// ──────────────────────────────────────────────────────────────────────────────
// Default-agent removal (agent-config-revisions-routing Phase 6.1)
// ──────────────────────────────────────────────────────────────────────────────

describe('AgentsSection default-agent removal', () => {
  it('does not render a "Default" badge or button anywhere in the agents table', async () => {
    renderAgentsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })
    expect(screen.queryByText('Default')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /default/i })).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Config revisions panel + rollback (agent-config-revisions-routing Phase 6.2)
// ──────────────────────────────────────────────────────────────────────────────

const revisionsFixture: AgentConfigRevision[] = [
  {
    id: 'rev-2',
    agent_id: 'agent-001',
    revision_number: 2,
    config: { system_prompt: 'v2 prompt' },
    schema_version: 'v1',
    source: 'api',
    created_by: 'admin@qora.ai',
    created_at: '2026-01-20T00:00:00Z',
    note: 'Updated prompt',
    elevenlabs_sync_status: 'synced',
  },
  {
    id: 'rev-1',
    agent_id: 'agent-001',
    revision_number: 1,
    config: { system_prompt: 'v1 prompt' },
    schema_version: 'v1',
    source: 'import',
    created_by: 'system',
    created_at: '2026-01-01T00:00:00Z',
    note: null,
    elevenlabs_sync_status: 'synced',
  },
]

async function openFirstAgentEditPanel() {
  renderAgentsSection('demo-client')
  await waitFor(() => {
    expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
  })
  const editButtons = screen.getAllByRole('button', { name: /edit/i })
  await userEvent.click(editButtons[0])
}

describe('AgentsSection revisions panel', () => {
  let revisionsState: AgentConfigRevision[]

  beforeEach(() => {
    revisionsState = revisionsFixture.map((r) => ({ ...r }))
    server.use(
      http.get(
        '/api/v1/clients/:clientId/agents/:agentId/revisions',
        () => HttpResponse.json(revisionsState),
      ),
    )
  })

  it('shows the active revision number and its ElevenLabs sync status', async () => {
    await openFirstAgentEditPanel()
    await waitFor(() => {
      expect(screen.getByText(/active: revision 2/i)).toBeInTheDocument()
    })
    expect(screen.getAllByText(/synced/i).length).toBeGreaterThanOrEqual(1)
  })

  it('lists past revisions with source, created_by, created_at and note', async () => {
    await openFirstAgentEditPanel()
    await waitFor(() => {
      expect(screen.getByTestId('revisions-history')).toBeInTheDocument()
    })
    const historyText = screen.getByTestId('revisions-history').textContent ?? ''
    expect(historyText).toContain('Revision 1')
    expect(historyText).toContain('import')
    expect(historyText).toContain('system')
  })

  it('shows a "Roll back" button only for the non-active revision', async () => {
    await openFirstAgentEditPanel()
    await waitFor(() => {
      expect(screen.getByTestId('revisions-history')).toBeInTheDocument()
    })
    const rollbackButtons = screen.getAllByRole('button', { name: /roll back/i })
    expect(rollbackButtons).toHaveLength(1)
  })

  it('requires a confirm step before calling the rollback endpoint', async () => {
    let rollbackCalled = false
    server.use(
      http.post(
        '/api/v1/clients/:clientId/agents/:agentId/revisions/:revisionId/rollback',
        () => {
          rollbackCalled = true
          return HttpResponse.json({ ...revisionsFixture[1], revision_number: 3, source: 'rollback' })
        },
      ),
    )
    await openFirstAgentEditPanel()
    await waitFor(() => {
      expect(screen.getByTestId('revisions-history')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /roll back/i }))
    // Confirm step: rollback must NOT fire until explicitly confirmed.
    expect(rollbackCalled).toBe(false)
    expect(screen.getByRole('button', { name: /confirm rollback/i })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /confirm rollback/i }))
    await waitFor(() => {
      expect(rollbackCalled).toBe(true)
    })
  })

  it('refreshes the active revision after a successful rollback', async () => {
    server.use(
      http.post(
        '/api/v1/clients/:clientId/agents/:agentId/revisions/:revisionId/rollback',
        () => {
          const newRevision: AgentConfigRevision = {
            id: 'rev-3',
            agent_id: 'agent-001',
            revision_number: 3,
            config: { system_prompt: 'v1 prompt' },
            schema_version: 'v1',
            source: 'rollback',
            created_by: 'admin@qora.ai',
            created_at: '2026-01-21T00:00:00Z',
            note: 'rollback to revision 1',
            elevenlabs_sync_status: 'synced',
          }
          revisionsState = [newRevision, ...revisionsState]
          return HttpResponse.json(newRevision)
        },
      ),
    )
    await openFirstAgentEditPanel()
    await waitFor(() => {
      expect(screen.getByTestId('revisions-history')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /roll back/i }))
    await userEvent.click(screen.getByRole('button', { name: /confirm rollback/i }))

    await waitFor(() => {
      expect(screen.getByText(/active: revision 3/i)).toBeInTheDocument()
    })
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Phase 6 (agent-config-inheritance): effective config — provenance, locked
// fields, completeness, Goal field, reset-to-inherited
// ──────────────────────────────────────────────────────────────────────────────

describe('AgentsSection effective config', () => {
  it('requires a Goal field in the create form and includes it in the create payload', async () => {
    let capturedBody: Record<string, unknown> | null = null
    server.use(
      http.post('/api/v1/clients/:clientId/agents', async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          { ...capturedBody, agent_id: 'agent-new', client_id: 'demo-client' },
          { status: 201 },
        )
      }),
    )
    renderAgentsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('agents-loading')).not.toBeInTheDocument()
    })

    const goalInput = screen.getByLabelText(/^goal$/i)
    expect(goalInput).toBeRequired()

    await userEvent.type(screen.getByLabelText('Slug'), 'new-agent')
    await userEvent.type(screen.getByLabelText('Name'), 'New Agent')
    await userEvent.type(screen.getByLabelText('Voice ID'), 'voice-xyz')
    await userEvent.type(goalInput, 'Qualify leads for auto insurance')
    await userEvent.click(screen.getByRole('button', { name: /create agent/i }))

    await waitFor(() => {
      expect(capturedBody).not.toBeNull()
    })
    const body = capturedBody as Record<string, unknown> | null
    expect(body?.goal).toBe('Qualify leads for auto insurance')
  })

  it('renders a provenance badge per config field in the edit form', async () => {
    server.use(
      http.get('/api/v1/clients/:clientId/agents/:agentId/effective-config', () =>
        HttpResponse.json(
          effectiveConfigFixture({
            temperature: { value: 0.5, provenance: 'client', policy: 'overridable' },
            tts_speed: { value: 1.0, provenance: 'agent', policy: 'overridable' },
          }),
        ),
      ),
    )
    await openFirstAgentEditPanel()

    await waitFor(() => {
      expect(screen.getAllByText('Client').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText('Agent').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Qora standard').length).toBeGreaterThan(0)
  })

  it('renders a locked config field as read-only, not merely disabled', async () => {
    server.use(
      http.get('/api/v1/clients/:clientId/agents/:agentId/effective-config', () =>
        HttpResponse.json(
          effectiveConfigFixture({
            temperature: { value: 0.7, provenance: 'standard', policy: 'locked' },
          }),
        ),
      ),
    )
    await openFirstAgentEditPanel()

    await waitFor(() => {
      expect(screen.getByText(/locked by qora standard/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('spinbutton', { name: /temperature/i })).not.toBeInTheDocument()
  })

  it('shows an Incomplete badge and the missing fields when config_incomplete', async () => {
    server.use(
      http.get('/api/v1/clients/:clientId/agents/:agentId/effective-config', () =>
        HttpResponse.json({
          ...effectiveConfigFixture(),
          config_incomplete: true,
          missing_required_fields: ['goal'],
        }),
      ),
    )
    await openFirstAgentEditPanel()

    await waitFor(() => {
      expect(screen.getByText(/incomplete/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/missing required field.*goal/i)).toBeInTheDocument()
  })

  it('renders a Goal field in the edit form, populated from the effective config', async () => {
    server.use(
      http.get('/api/v1/clients/:clientId/agents/:agentId/effective-config', () =>
        HttpResponse.json(
          effectiveConfigFixture({
            goal: { value: 'Close more policies', provenance: 'agent', policy: 'agent_required' },
          }),
        ),
      ),
    )
    await openFirstAgentEditPanel()

    await waitFor(() => {
      expect(screen.getByLabelText(/^goal$/i)).toHaveValue('Close more policies')
    })
  })

  it('shows a Reset to inherited button for an agent-overridden overridable field, and it sends null for that field', async () => {
    let capturedBody: Record<string, unknown> | null = null
    server.use(
      http.get('/api/v1/clients/:clientId/agents/:agentId/effective-config', () =>
        HttpResponse.json(
          effectiveConfigFixture({
            tts_speed: { value: 1.1, provenance: 'agent', policy: 'overridable' },
          }),
        ),
      ),
      http.patch('/api/v1/clients/:clientId/agents/:agentId/config', async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          id: 'rev-x',
          agent_id: 'agent-001',
          revision_number: 5,
          config: {},
          schema_version: 'v2',
          source: 'api',
          created_by: 'admin@qora.ai',
          created_at: '2026-01-22T00:00:00Z',
          note: null,
          elevenlabs_sync_status: 'skipped',
        })
      }),
    )
    await openFirstAgentEditPanel()

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /reset to inherited/i }).length).toBeGreaterThan(0)
    })
    await userEvent.click(screen.getAllByRole('button', { name: /reset to inherited/i })[0])

    await waitFor(() => {
      expect(capturedBody).not.toBeNull()
    })
    expect(capturedBody).toMatchObject({ tts_speed: null })
  })
})
