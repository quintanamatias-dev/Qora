/**
 * Live Calls API endpoint function tests
 */

import { describe, it, expect, afterEach, vi } from 'vitest'
import { fetchActiveCalls } from './live'
import type { LiveCallsResponse } from './live'

const mockResponse: LiveCallsResponse = {
  server_time: '2026-01-15T10:00:00Z',
  calls: [
    {
      session_id: 'session-1',
      lead_id: 'lead-1',
      lead_first_name: 'Lucia',
      agent_id: 'agent-1',
      agent_name: 'Juanma',
      telephony_status: 'connected',
      started_at: '2026-01-15T09:58:00Z',
    },
  ],
  today: { calls_total: 5, completed: 3 },
  recent_facts: [{ text: 'Prefiere WhatsApp', lead_first_name: 'Lucia', duration_seconds: 160 }],
  memory_total: 42,
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

describe('fetchActiveCalls', () => {
  it('calls /api/v1/calls/active?client_id=<clientId> and returns the payload', async () => {
    const spy = spyFetch(mockResponse)

    const result = await fetchActiveCalls('demo-client')

    expect(result.calls).toHaveLength(1)
    expect(result.calls[0].telephony_status).toBe('connected')
    expect(result.today.calls_total).toBe(5)
    expect(result.memory_total).toBe(42)
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('/api/v1/calls/active')
    expect(url).toContain('client_id=demo-client')
  })
})
