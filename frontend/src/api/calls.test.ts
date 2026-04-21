/**
 * CAP-5: Calls API endpoint function tests
 *
 * REQ-5.2: fetchMetrics, fetchCallSessions, fetchTranscript call correct URLs
 */

import { describe, it, expect, afterEach, vi } from 'vitest'
import { fetchMetrics, fetchCallSessions, fetchTranscript } from './calls'
import type { CallMetricsResponse, CallSession, SessionTranscript } from './types'

// ──────────────────────────────────────────────────────────────────────────────
// Fixtures
// ──────────────────────────────────────────────────────────────────────────────
const mockMetrics: CallMetricsResponse = {
  total_calls: 100,
  completed_calls: 80,
  abandoned_calls: 20,
  total_duration_seconds: 5000,
  average_duration_seconds: 62.5,
  total_billable_minutes: 83.3,
  period: { date_from: '2026-01-01', date_to: '2026-01-31' },
}

const mockSession: CallSession = {
  id: 'session-1',
  client_id: 'demo-client',
  lead_id: 'lead-1',
  status: 'completed',
  started_at: '2026-01-15T10:00:00Z',
  ended_at: '2026-01-15T10:05:00Z',
  duration_seconds: 300,
  summary: 'Customer interested in coverage.',
}

const mockTranscript: SessionTranscript = {
  session_id: 'session-1',
  turn_count: 2,
  turns: [
    { id: 't1', role: 'agent', content: 'Hello!', timestamp: '2026-01-15T10:00:01Z', filler_detected: false },
    { id: 't2', role: 'customer', content: 'Hi there.', timestamp: '2026-01-15T10:00:03Z', filler_detected: false },
  ],
}

function spyFetch(body: unknown, status = 200) {
  const spy = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  )
  vi.stubGlobal('fetch', spy)
  return spy
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ──────────────────────────────────────────────────────────────────────────────
// fetchMetrics
// ──────────────────────────────────────────────────────────────────────────────
describe('fetchMetrics', () => {
  it('calls /api/v1/calls/metrics?client_id=<clientId> and returns metrics', async () => {
    const spy = spyFetch(mockMetrics)

    const result = await fetchMetrics('demo-client')

    expect(result.total_calls).toBe(100)
    expect(result.completed_calls).toBe(80)
    expect(result.period.date_from).toBe('2026-01-01')
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('/api/v1/calls/metrics')
    expect(url).toContain('client_id=demo-client')
  })

  it('includes optional date range params when provided', async () => {
    const spy = spyFetch(mockMetrics)

    await fetchMetrics('demo-client', { date_from: '2026-01-01', date_to: '2026-01-31' })

    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('date_from=2026-01-01')
    expect(url).toContain('date_to=2026-01-31')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// fetchCallSessions
// ──────────────────────────────────────────────────────────────────────────────
describe('fetchCallSessions', () => {
  it('calls /api/v1/calls?client_id=<clientId> and returns array', async () => {
    const spy = spyFetch([mockSession])

    const result = await fetchCallSessions('demo-client')

    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('session-1')
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('/api/v1/calls')
    expect(url).toContain('client_id=demo-client')
  })

  it('includes lead_id param when leadId is provided', async () => {
    const spy = spyFetch([mockSession])

    await fetchCallSessions('demo-client', 'lead-1')

    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('client_id=demo-client')
    expect(url).toContain('lead_id=lead-1')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// fetchTranscript
// ──────────────────────────────────────────────────────────────────────────────
describe('fetchTranscript', () => {
  it('calls /api/v1/calls/:sessionId/transcript and returns transcript', async () => {
    const spy = spyFetch(mockTranscript)

    const result = await fetchTranscript('session-1')

    expect(result.session_id).toBe('session-1')
    expect(result.turn_count).toBe(2)
    expect(result.turns).toHaveLength(2)
    expect(result.turns[0].role).toBe('agent')
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('/api/v1/calls/session-1/transcript')
  })
})
