/**
 * CAP-5: TanStack Query hooks tests
 *
 * REQ-5.3: Hooks exist, use correct queryKeys, return loading state initially
 *
 * Strategy: wrap hooks in QueryClientProvider, use vi.mock to stub the
 * endpoint fetchers so we test hook contract (queryKey, enabled, return shape)
 * without making real network calls.
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useMetrics, useLeads, useLead, useLeadContextPreview, useCallSessions, useTranscript, useClient, useCallAnalysis } from './hooks'
import type { CallMetricsResponse, Lead, CallSession, SessionTranscript, Client, LeadContextPreview } from './types'
import { ApiError } from './client'

// ──────────────────────────────────────────────────────────────────────────────
// Mocks — stub the fetchers so hooks don't make real HTTP calls
// ──────────────────────────────────────────────────────────────────────────────

vi.mock('./calls', () => ({
  fetchMetrics: vi.fn(),
  fetchCallSessions: vi.fn(),
  fetchTranscript: vi.fn(),
  fetchCallAnalysis: vi.fn(),
}))

vi.mock('./leads', () => ({
  fetchLeads: vi.fn(),
  fetchLead: vi.fn(),
  createLead: vi.fn(),
  fetchLeadContextPreview: vi.fn(),
}))

vi.mock('./clients', () => ({
  fetchClient: vi.fn(),
}))

import * as callsApi from './calls'
import * as leadsApi from './leads'
import * as clientsApi from './clients'

// ──────────────────────────────────────────────────────────────────────────────
// Fixtures
// ──────────────────────────────────────────────────────────────────────────────
const mockMetrics: CallMetricsResponse = {
  total_calls: 42,
  completed_calls: 35,
  abandoned_calls: 7,
  total_duration_seconds: 2100,
  average_duration_seconds: 60,
  total_billable_minutes: 35,
  period: { date_from: null, date_to: null },
}

const mockLead: Lead = {
  id: 'lead-1',
  client_id: 'demo-client',
  name: 'Jane Smith',
  phone: '+1-555-0200',
  status: 'new',
  notes: null,
  call_count: 0,
  last_called_at: null,
  created_at: null,
  updated_at: null,
  // Phase 2 fields
  summary_last_call: null,
  objections_heard: null,
  interest_level: null,
  extracted_facts: null,
  do_not_call: false,
  next_action: null,
  next_action_at: null,
  // Phase 7
  next_scheduled_call_at: null,
  // WU-6: custom fields
  custom_fields: {},
  // Phase A
  email: null,
  external_crm_id: null,
  external_lead_id: null,
}

const mockContextPreview: LeadContextPreview = {
  lead_id: 'lead-1',
  system_prompt_present: true,
  lead_profile: '[CONTEXTO DEL LEAD]\nNombre: Jane Smith',
  call_history: 'Llamada del 10/01/2026: "Interested"',
  misc_notes: 'Prefers afternoon callbacks.',
  skills_index: '## Available Skills\n- quote_assistant',
  tools: ['get_lead_details', 'capture_data'],
  model: 'gpt-4o',
  temperature: 0.7,
  max_tokens: 300,
  is_returning_caller: true,
  call_number: 3,
  error: null,
}

const mockSession: CallSession = {
  id: 'session-1',
  client_id: 'demo-client',
  lead_id: 'lead-1',
  status: 'completed',
  started_at: null,
  ended_at: null,
  duration_seconds: 60,
  summary: null,
  // Phase 2 fields
  outcome: null,
  closed_reason: null,
  billable_minutes: null,
  total_user_turns: null,
  total_agent_turns: null,
  extracted_facts: null,
}

const mockTranscript: SessionTranscript = {
  session_id: 'session-1',
  turn_count: 1,
  turns: [{ id: 't1', role: 'agent', content: 'Hi!', timestamp: '2026-01-01T00:00:00Z', filler_detected: false }],
}

const mockClient: Client = {
  client_id: 'demo-client',
  name: 'Demo Broker',
  agent_name: 'Demo Agent',
  voice_id: 'voice-1',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function createTestClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,     // don't retry in tests
        gcTime: 0,
      },
    },
  })
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = createTestClient()
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

afterEach(() => {
  vi.clearAllMocks()
})

// ──────────────────────────────────────────────────────────────────────────────
// useMetrics
// ──────────────────────────────────────────────────────────────────────────────
describe('useMetrics', () => {
  it('returns data from fetchMetrics when resolved', async () => {
    vi.mocked(callsApi.fetchMetrics).mockResolvedValue(mockMetrics)

    function Comp() {
      const { data, isLoading } = useMetrics('demo-client')
      if (isLoading) return <span>loading</span>
      return <span data-testid="total">{data?.total_calls}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)

    expect(screen.getByText('loading')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('total')).toHaveTextContent('42'))
    expect(callsApi.fetchMetrics).toHaveBeenCalledWith('demo-client', undefined)
  })

  it('calls fetchMetrics with correct clientId (acme-motors)', async () => {
    vi.mocked(callsApi.fetchMetrics).mockResolvedValue({ ...mockMetrics, total_calls: 7 })

    function Comp() {
      const { data, isLoading } = useMetrics('acme-motors')
      if (isLoading) return <span>loading</span>
      return <span data-testid="total">{data?.total_calls}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('total')).toHaveTextContent('7'))
    expect(callsApi.fetchMetrics).toHaveBeenCalledWith('acme-motors', undefined)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// useLeads
// ──────────────────────────────────────────────────────────────────────────────
describe('useLeads', () => {
  it('returns lead list from fetchLeads', async () => {
    vi.mocked(leadsApi.fetchLeads).mockResolvedValue([mockLead])

    function Comp() {
      const { data, isLoading } = useLeads('demo-client')
      if (isLoading) return <span>loading</span>
      return <span data-testid="count">{data?.length}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
    expect(leadsApi.fetchLeads).toHaveBeenCalledWith('demo-client')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// useLead
// ──────────────────────────────────────────────────────────────────────────────
describe('useLead', () => {
  it('returns single lead from fetchLead', async () => {
    vi.mocked(leadsApi.fetchLead).mockResolvedValue(mockLead)

    function Comp() {
      const { data, isLoading } = useLead('demo-client', 'lead-1')
      if (isLoading) return <span>loading</span>
      return <span data-testid="name">{data?.name}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('name')).toHaveTextContent('Jane Smith'))
    expect(leadsApi.fetchLead).toHaveBeenCalledWith('demo-client', 'lead-1')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// useLeadContextPreview — Phase A: lazy-loaded next-call context preview
// ──────────────────────────────────────────────────────────────────────────────
describe('useLeadContextPreview', () => {
  it('returns the context preview from fetchLeadContextPreview when enabled', async () => {
    vi.mocked(leadsApi.fetchLeadContextPreview).mockResolvedValue(mockContextPreview)

    function Comp() {
      const { data, isLoading } = useLeadContextPreview('demo-client', 'lead-1', true)
      if (isLoading) return <span>loading</span>
      return <span data-testid="model">{data?.model}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('model')).toHaveTextContent('gpt-4o'))
    expect(leadsApi.fetchLeadContextPreview).toHaveBeenCalledWith('demo-client', 'lead-1')
  })

  it('does not fetch while disabled (lazy load gate)', async () => {
    vi.mocked(leadsApi.fetchLeadContextPreview).mockResolvedValue(mockContextPreview)

    function Comp() {
      const { fetchStatus } = useLeadContextPreview('demo-client', 'lead-1', false)
      return <span data-testid="status">{fetchStatus}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('idle'))
    // The fetcher must NOT be called while the preview is gated off.
    expect(leadsApi.fetchLeadContextPreview).not.toHaveBeenCalled()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// useCallSessions — REQ-5.3: must accept optional leadId
// ──────────────────────────────────────────────────────────────────────────────
describe('useCallSessions', () => {
  it('fetches call sessions for clientId only (no leadId)', async () => {
    vi.mocked(callsApi.fetchCallSessions).mockResolvedValue([mockSession])

    function Comp() {
      const { data, isLoading } = useCallSessions('demo-client')
      if (isLoading) return <span>loading</span>
      return <span data-testid="session-id">{data?.[0]?.id}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('session-id')).toHaveTextContent('session-1'))
    expect(callsApi.fetchCallSessions).toHaveBeenCalledWith('demo-client', undefined)
  })

  it('fetches call sessions filtered by leadId when provided', async () => {
    vi.mocked(callsApi.fetchCallSessions).mockResolvedValue([mockSession])

    function Comp() {
      const { data, isLoading } = useCallSessions('demo-client', 'lead-1')
      if (isLoading) return <span>loading</span>
      return <span data-testid="session-id">{data?.[0]?.id}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('session-id')).toHaveTextContent('session-1'))
    // Verify leadId is forwarded to the fetcher
    expect(callsApi.fetchCallSessions).toHaveBeenCalledWith('demo-client', 'lead-1')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// useClient — REQ-5.3: hook must exist for client resource
// ──────────────────────────────────────────────────────────────────────────────
describe('useClient', () => {
  it('returns client data from fetchClient', async () => {
    vi.mocked(clientsApi.fetchClient).mockResolvedValue(mockClient)

    function Comp() {
      const { data, isLoading } = useClient('demo-client')
      if (isLoading) return <span>loading</span>
      return <span data-testid="broker">{data?.name}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('broker')).toHaveTextContent('Demo Broker'))
    expect(clientsApi.fetchClient).toHaveBeenCalledWith('demo-client')
  })

  it('calls fetchClient with different clientId (acme-motors)', async () => {
    vi.mocked(clientsApi.fetchClient).mockResolvedValue({ ...mockClient, client_id: 'acme-motors', name: 'Acme Broker' })

    function Comp() {
      const { data, isLoading } = useClient('acme-motors')
      if (isLoading) return <span>loading</span>
      return <span data-testid="broker">{data?.name}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('broker')).toHaveTextContent('Acme Broker'))
    expect(clientsApi.fetchClient).toHaveBeenCalledWith('acme-motors')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// useMetrics — staleTime (REQ: staleTime: 60_000 prevents hammering backend)
// ──────────────────────────────────────────────────────────────────────────────
describe('useMetrics — staleTime', () => {
  it('does not refetch within 60s when data is already cached (staleTime = 60_000)', async () => {
    let fetchCount = 0
    vi.mocked(callsApi.fetchMetrics).mockImplementation(() => {
      fetchCount++
      return Promise.resolve({ ...mockMetrics, total_calls: fetchCount })
    })

    // Create a shared QueryClient to test staleTime across renders
    const sharedQC = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 300_000 } },
    })

    function Comp() {
      const { data, isLoading } = useMetrics('demo-client', { date_from: '2026-01-01', date_to: '2026-01-07' })
      if (isLoading) return <span>loading</span>
      return <span data-testid="fetch-count">{data?.total_calls}</span>
    }

    function SharedWrapper({ children }: { children: React.ReactNode }) {
      return <QueryClientProvider client={sharedQC}>{children}</QueryClientProvider>
    }

    const { unmount } = render(<SharedWrapper><Comp /></SharedWrapper>)
    await waitFor(() => expect(screen.getByTestId('fetch-count')).toHaveTextContent('1'))

    // Unmount and remount — with staleTime=60_000, data is still fresh → no refetch
    unmount()
    render(<SharedWrapper><Comp /></SharedWrapper>)
    await waitFor(() => expect(screen.getByTestId('fetch-count')).toBeInTheDocument())

    // fetchCount must still be 1 — staleTime prevented the second fetch
    expect(fetchCount).toBe(1)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// useCallAnalysis — must distinguish "no analysis" (404) from real server errors
//
// Bug: when the backend 500'd (e.g. a missing DB column), the hook swallowed the
// error and returned null, so the UI rendered "No analysis available" even though
// analysis data existed. A 404 means no analysis; any other status is a real error
// and must surface as isError instead of masquerading as empty.
// ──────────────────────────────────────────────────────────────────────────────
describe('useCallAnalysis', () => {
  it('returns analysis data when the fetch resolves', async () => {
    vi.mocked(callsApi.fetchCallAnalysis).mockResolvedValue({
      session_id: 'session-1',
      summary: 'Lead is interested',
      analysis_status: 'ok',
      analyzed_at: '2026-01-01T00:00:00Z',
    } as never)

    function Comp() {
      const { data, isLoading } = useCallAnalysis('session-1')
      if (isLoading) return <span>loading</span>
      return <span data-testid="summary">{data?.summary}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('summary')).toHaveTextContent('Lead is interested'))
    expect(callsApi.fetchCallAnalysis).toHaveBeenCalledWith('session-1')
  })

  it('returns null (not an error) when the session has no analysis (404)', async () => {
    vi.mocked(callsApi.fetchCallAnalysis).mockRejectedValue(
      new ApiError(404, { detail: 'No analysis available for this call session' })
    )

    function Comp() {
      const { data, isError, isLoading } = useCallAnalysis('session-1')
      if (isLoading) return <span>loading</span>
      return (
        <span data-testid="state">
          {isError ? 'error' : data === null ? 'null' : 'data'}
        </span>
      )
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('null'))
  })

  it('surfaces a real server error (500) instead of masquerading as empty', async () => {
    vi.mocked(callsApi.fetchCallAnalysis).mockRejectedValue(
      new ApiError(500, { detail: 'no such column: call_analyses.primary_objection_category' })
    )

    function Comp() {
      const { data, isError, isLoading } = useCallAnalysis('session-1')
      if (isLoading) return <span>loading</span>
      return (
        <span data-testid="state">
          {isError ? 'error' : data === null ? 'null' : 'data'}
        </span>
      )
    }

    render(<Wrapper><Comp /></Wrapper>)
    // A 500 must NOT be swallowed into null — it must surface as an error state.
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('error'))
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// useTranscript
// ──────────────────────────────────────────────────────────────────────────────
describe('useTranscript', () => {
  it('returns transcript from fetchTranscript', async () => {
    vi.mocked(callsApi.fetchTranscript).mockResolvedValue(mockTranscript)

    function Comp() {
      const { data, isLoading } = useTranscript('session-1')
      if (isLoading) return <span>loading</span>
      return <span data-testid="turn-count">{data?.turn_count}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('turn-count')).toHaveTextContent('1'))
    expect(callsApi.fetchTranscript).toHaveBeenCalledWith('session-1')
  })
})
