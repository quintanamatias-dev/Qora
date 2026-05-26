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
  Client,
  Agent,
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
// Admin Fixtures
// ──────────────────────────────────────────────────────────────────────────────

const clientsFixture: Client[] = [
  {
    client_id: 'demo-client',
    name: 'Demo Broker',
    agent_name: 'Jaumpablo',
    voice_id: 'voice-001',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    agent_count: 2,
  },
  {
    client_id: 'acme-motors',
    name: 'Acme Motors',
    agent_name: 'Jaumpablo',
    voice_id: 'voice-002',
    is_active: true,
    created_at: '2026-01-15T00:00:00Z',
    agent_count: 1,
  },
  {
    client_id: 'old-client',
    name: 'Old Corp',
    agent_name: 'Jaumpablo',
    voice_id: 'voice-003',
    is_active: false,
    created_at: '2025-06-01T00:00:00Z',
    agent_count: 0,
  },
]

const agentsFixture: Agent[] = [
  {
    agent_id: 'agent-001',
    client_id: 'demo-client',
    slug: 'primary-agent',
    name: 'Primary Agent',
    voice_id: 'voice-001',
    model: 'gpt-4o',
    system_prompt: 'You are a helpful insurance agent.',
    tools_enabled: ['get_lead_details', 'register_interest'],
    is_active: true,
    is_default: true,
    created_at: '2026-01-01T00:00:00Z',
    // ElevenLabs binding + readiness
    elevenlabs_agent_id: 'el_demo_abc123',
    knowledge_base: null,
    temperature: 0.7,
    max_tokens: 512,
    custom_llm_url: '/api/v1/voice/demo-client/custom-llm/chat/completions',
    has_prompt: true,
    has_elevenlabs_agent_id: true,
    is_conversation_ready: true,
    // Voice tuning
    tts_speed: 0.95,
    tts_stability: 0.4,
    tts_similarity_boost: 0.75,
  },
  {
    agent_id: 'agent-002',
    client_id: 'demo-client',
    slug: 'secondary-agent',
    name: 'Secondary Agent',
    voice_id: 'voice-002',
    model: 'gpt-4o-mini',
    system_prompt: null,
    tools_enabled: ['get_lead_details'],
    is_active: true,
    is_default: false,
    created_at: '2026-01-10T00:00:00Z',
    // Not yet configured
    elevenlabs_agent_id: null,
    knowledge_base: null,
    temperature: 0.7,
    max_tokens: 512,
    custom_llm_url: '/api/v1/voice/demo-client/custom-llm/chat/completions',
    has_prompt: false,
    has_elevenlabs_agent_id: false,
    is_conversation_ready: false,
    // Voice tuning — defaults
    tts_speed: 0.95,
    tts_stability: 0.4,
    tts_similarity_boost: 0.75,
  },
]

// ──────────────────────────────────────────────────────────────────────────────
// Handlers
// ──────────────────────────────────────────────────────────────────────────────

export const handlers = [
  // ── Admin: Clients ────────────────────────────────────────────────────────

  // GET /api/v1/clients — returns all clients fixture
  // NOTE: must come BEFORE /api/v1/clients/:clientId to avoid ambiguity
  http.get('/api/v1/clients', () => {
    return HttpResponse.json(clientsFixture)
  }),

  // POST /api/v1/clients — creates a client and returns it
  http.post('/api/v1/clients', async ({ request }) => {
    const body = await request.json() as Partial<Client>
    const newClient: Client = {
      client_id: body.client_id ?? 'new-client',
      name: body.name ?? 'New Broker',
      agent_name: body.agent_name ?? 'Jaumpablo',
      voice_id: '',
      is_active: true,
      created_at: new Date().toISOString(),
      agent_count: 0,
    }
    return HttpResponse.json(newClient, { status: 201 })
  }),

  // PATCH /api/v1/clients/:clientId — updates a client
  http.patch('/api/v1/clients/:clientId', async ({ params, request }) => {
    const client = clientsFixture.find((c) => c.client_id === params.clientId)
    if (!client) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const body = await request.json() as Partial<Client>
    return HttpResponse.json({ ...client, ...body })
  }),

  // DELETE /api/v1/clients/:clientId — deactivates a client
  http.delete('/api/v1/clients/:clientId', ({ params }) => {
    const client = clientsFixture.find((c) => c.client_id === params.clientId)
    if (!client) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    return HttpResponse.json({ ...client, is_active: false })
  }),

  // ── Admin: Agents ─────────────────────────────────────────────────────────

  // GET /api/v1/clients/:clientId/agents — returns agents for client
  http.get('/api/v1/clients/:clientId/agents', ({ params }) => {
    const filtered = agentsFixture.filter((a) => a.client_id === params.clientId)
    return HttpResponse.json(filtered)
  }),

  // POST /api/v1/clients/:clientId/agents — creates an agent
  http.post('/api/v1/clients/:clientId/agents', async ({ params, request }) => {
    const body = await request.json() as Partial<Agent>
    const newAgent: Agent = {
      agent_id: `agent-${Date.now()}`,
      client_id: params.clientId as string,
      slug: body.slug ?? 'new-agent',
      name: body.name ?? 'New Agent',
      voice_id: body.voice_id ?? '',
      model: body.model ?? 'gpt-4o',
      system_prompt: body.system_prompt ?? null,
      tools_enabled: body.tools_enabled ?? [],
      is_active: true,
      is_default: false,
      created_at: new Date().toISOString(),
      elevenlabs_agent_id: body.elevenlabs_agent_id ?? null,
      knowledge_base: body.knowledge_base ?? null,
      temperature: body.temperature ?? 0.7,
      max_tokens: body.max_tokens ?? 512,
      custom_llm_url: `/api/v1/voice/${params.clientId}/custom-llm/chat/completions`,
      has_prompt: Boolean(body.system_prompt),
      has_elevenlabs_agent_id: Boolean(body.elevenlabs_agent_id),
      is_conversation_ready: Boolean(body.system_prompt) && Boolean(body.elevenlabs_agent_id),
      tts_speed: body.tts_speed ?? 0.95,
      tts_stability: body.tts_stability ?? 0.4,
      tts_similarity_boost: body.tts_similarity_boost ?? 0.75,
    }
    return HttpResponse.json(newAgent, { status: 201 })
  }),

  // PATCH /api/v1/clients/:clientId/agents/:agentId — updates an agent
  http.patch('/api/v1/clients/:clientId/agents/:agentId', async ({ params, request }) => {
    const agent = agentsFixture.find((a) => a.agent_id === params.agentId)
    if (!agent) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const body = await request.json() as Partial<Agent>
    return HttpResponse.json({ ...agent, ...body })
  }),

  // POST /api/v1/clients/:clientId/agents/:agentId/deactivate
  http.post('/api/v1/clients/:clientId/agents/:agentId/deactivate', ({ params }) => {
    const agent = agentsFixture.find((a) => a.agent_id === params.agentId)
    if (!agent) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    return HttpResponse.json({ ...agent, is_active: false })
  }),

  // POST /api/v1/clients/:clientId/agents/:agentId/make-default
  http.post('/api/v1/clients/:clientId/agents/:agentId/make-default', ({ params }) => {
    const agent = agentsFixture.find((a) => a.agent_id === params.agentId)
    if (!agent) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    return HttpResponse.json({ ...agent, is_default: true })
  }),

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
