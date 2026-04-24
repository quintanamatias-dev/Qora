/**
 * MSW Request Handlers
 *
 * REQ-6.2: Intercepts API calls in tests and returns fixture JSON.
 *
 * Handlers cover:
 * - GET /api/v1/calls/metrics?client_id=demo-client → CallMetricsResponse fixture
 * - GET /api/v1/calls/metrics?client_id=error-client → 500 error
 * - GET /api/v1/leads?client_id=demo-client → Lead[] fixture
 * - GET /api/v1/leads/:leadId → Lead fixture
 * - GET /api/v1/calls?client_id=demo-client → CallSession[] fixture
 * - GET /api/v1/calls/:sessionId/transcript → SessionTranscript fixture
 */

import { http, HttpResponse } from 'msw'
import type {
  CallMetricsResponse,
  Lead,
  CallSession,
  SessionTranscript,
} from '../../src/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Fixtures
// ──────────────────────────────────────────────────────────────────────────────

const metricsFixture: CallMetricsResponse = {
  total_calls: 150,
  completed_calls: 120,
  abandoned_calls: 30,
  total_duration_seconds: 9000,
  average_duration_seconds: 75,
  total_billable_minutes: 150,
  period: { date_from: null, date_to: null },
}

const leadsFixture: Lead[] = [
  {
    id: 'lead-1',
    client_id: 'demo-client',
    name: 'John Doe',
    phone: '+1-555-0100',
    car_make: 'Toyota',
    car_model: 'Camry',
    car_year: 2022,
    current_insurance: 'State Farm',
    status: 'new',
    notes: null,
    call_count: 2,
    last_called_at: '2026-01-10T10:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: null,
    // Phase 2 fields
    summary_last_call: 'Client interested in full coverage',
    objections_heard: null,
    interest_level: 75,
    extracted_facts: { budget: '50k ARS/month' },
    do_not_call: false,
    next_action: 'Send quote',
    next_action_at: null,
    // Phase 7
    next_scheduled_call_at: null,
  },
  {
    id: 'lead-2',
    client_id: 'demo-client',
    name: 'Jane Smith',
    phone: '+1-555-0200',
    car_make: null,
    car_model: null,
    car_year: null,
    current_insurance: null,
    status: 'interested',
    notes: 'Callback requested',
    call_count: 1,
    last_called_at: '2026-01-12T14:00:00Z',
    created_at: '2026-01-05T00:00:00Z',
    updated_at: '2026-01-12T14:05:00Z',
    // Phase 2 fields — all null
    summary_last_call: null,
    objections_heard: null,
    interest_level: null,
    extracted_facts: null,
    do_not_call: false,
    next_action: null,
    next_action_at: null,
    // Phase 7
    next_scheduled_call_at: null,
  },
]

const sessionsFixture: CallSession[] = [
  {
    id: 'session-abc',
    client_id: 'demo-client',
    lead_id: 'lead-1',
    status: 'completed',
    started_at: '2026-01-15T10:00:00Z',
    ended_at: '2026-01-15T10:05:00Z',
    duration_seconds: 300,
    summary: 'Customer interested in full coverage.',
    outcome: 'completed',
    closed_reason: 'agent_goodbye',
    billable_minutes: 5,
    total_user_turns: 5,
    total_agent_turns: 6,
    extracted_facts: null,
  },
  {
    id: 'session-def',
    client_id: 'demo-client',
    lead_id: 'lead-1',
    status: 'completed',
    started_at: '2026-01-16T11:00:00Z',
    ended_at: '2026-01-16T11:03:00Z',
    duration_seconds: 180,
    summary: 'Follow-up call completed.',
    outcome: 'completed',
    closed_reason: 'agent_goodbye',
    billable_minutes: 3,
    total_user_turns: 3,
    total_agent_turns: 4,
    extracted_facts: { policy: 'full' },
  },
]

const transcriptFixture: SessionTranscript = {
  session_id: 'session-abc',
  turn_count: 3,
  turns: [
    { id: 't1', role: 'agent', content: 'Hello, this is Qora calling.', timestamp: '2026-01-15T10:00:01Z', filler_detected: false },
    { id: 't2', role: 'customer', content: 'Yes, I was expecting your call.', timestamp: '2026-01-15T10:00:05Z', filler_detected: false },
    { id: 't3', role: 'agent', content: 'Great! Let me explain our coverage options.', timestamp: '2026-01-15T10:00:08Z', filler_detected: false },
  ],
}

// ──────────────────────────────────────────────────────────────────────────────
// Handlers
// ──────────────────────────────────────────────────────────────────────────────

export const handlers = [
  // GET /api/v1/calls/metrics — returns 500 for error-client, fixture for others
  http.get('/api/v1/calls/metrics', ({ request }) => {
    const url = new URL(request.url)
    const clientId = url.searchParams.get('client_id')
    if (clientId === 'error-client') {
      return HttpResponse.json({ detail: 'Internal server error' }, { status: 500 })
    }
    return HttpResponse.json(metricsFixture)
  }),

  // GET /api/v1/leads — returns fixture leads for demo-client
  http.get('/api/v1/leads', ({ request }) => {
    const url = new URL(request.url)
    const clientId = url.searchParams.get('client_id')
    if (!clientId) {
      return HttpResponse.json({ detail: 'client_id required' }, { status: 422 })
    }
    return HttpResponse.json(leadsFixture)
  }),

  // GET /api/v1/leads/:leadId — returns single lead fixture
  http.get('/api/v1/leads/:leadId', ({ params }) => {
    const lead = leadsFixture.find((l) => l.id === params.leadId)
    if (!lead) {
      return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    }
    return HttpResponse.json(lead)
  }),

  // GET /api/v1/calls — returns call sessions (filtered by lead_id if provided)
  http.get('/api/v1/calls', ({ request }) => {
    const url = new URL(request.url)
    const leadId = url.searchParams.get('lead_id')
    if (leadId) {
      return HttpResponse.json(sessionsFixture.filter(s => s.lead_id === leadId))
    }
    return HttpResponse.json(sessionsFixture)
  }),

  // GET /api/v1/calls/:sessionId/transcript — returns transcript
  http.get('/api/v1/calls/:sessionId/transcript', () => {
    return HttpResponse.json(transcriptFixture)
  }),
]
