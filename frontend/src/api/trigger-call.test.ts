/**
 * triggerCall API client tests — C2 outbound call trigger
 *
 * Spec: phase-c2-outbound-call-trigger / REQ: Frontend Call Trigger UX
 * Design: POST /api/v1/clients/{clientId}/leads/{leadId}/call
 *
 * TDD RED phase: these tests are written before the implementation.
 * They verify URL construction, method, success shape, and error propagation.
 * No live calls are made — fetch is mocked via vi.stubGlobal.
 */

import { describe, it, expect, afterEach, vi } from 'vitest'
import { triggerCall } from './leads'
import type { CallTriggerResponse } from './types'
import { ApiError } from './client'

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function mockFetchOk(body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    )
  )
}

function mockFetchError(status: number, detail: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail }), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    )
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ──────────────────────────────────────────────────────────────────────────────
// triggerCall — success
// ──────────────────────────────────────────────────────────────────────────────

describe('triggerCall', () => {
  it('calls POST /api/v1/clients/{clientId}/leads/{leadId}/call', async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ status: 'dialing', call_session_id: 'cs-abc' }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      )
    )
    vi.stubGlobal('fetch', spy)

    await triggerCall('demo-client', 'lead-1')

    const calledUrl = spy.mock.calls[0][0] as string
    expect(calledUrl).toContain('/api/v1/clients/demo-client/leads/lead-1/call')

    const calledInit = spy.mock.calls[0][1] as RequestInit
    expect(calledInit.method).toBe('POST')
  })

  it('returns CallTriggerResponse on success', async () => {
    const expected: CallTriggerResponse = {
      status: 'dialing',
      call_session_id: 'cs-xyz-001',
    }
    mockFetchOk(expected)

    const result = await triggerCall('demo-client', 'lead-1')

    expect(result.status).toBe('dialing')
    expect(result.call_session_id).toBe('cs-xyz-001')
  })

  it('encodes special characters in clientId and leadId', async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ status: 'dialing', call_session_id: 'cs-encoded' }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      )
    )
    vi.stubGlobal('fetch', spy)

    await triggerCall('client/with-slash', 'lead#1')

    const calledUrl = spy.mock.calls[0][0] as string
    // Both IDs must be URI-encoded — slash and hash must not appear raw
    expect(calledUrl).not.toContain('client/with-slash')
    expect(calledUrl).not.toContain('lead#1')
    expect(calledUrl).toContain('client%2Fwith-slash')
    expect(calledUrl).toContain('lead%231')
  })

  // ──────────────────────────────────────────────────────────────────────────
  // Error propagation — no live calls in any of these
  // ──────────────────────────────────────────────────────────────────────────

  it('throws ApiError with status 403 when feature flag is off', async () => {
    mockFetchError(403, 'Outbound calls are not enabled for this instance.')

    await expect(triggerCall('demo-client', 'lead-1')).rejects.toBeInstanceOf(ApiError)

    try {
      await triggerCall('demo-client', 'lead-1')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      expect((err as ApiError).status).toBe(403)
    }
  })

  it('throws ApiError with status 409 when concurrent call is active', async () => {
    mockFetchError(409, 'A call is already active for this lead.')

    // Primary assertion: promise must reject — if it resolves, the test fails
    await expect(triggerCall('demo-client', 'lead-1')).rejects.toBeInstanceOf(ApiError)

    // Secondary assertion: status code is exactly 409
    try {
      await triggerCall('demo-client', 'lead-1')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      expect((err as ApiError).status).toBe(409)
    }
  })

  it('throws ApiError with status 422 when phone number is invalid', async () => {
    mockFetchError(422, 'Lead phone number is not valid E.164.')

    // Primary assertion: promise must reject — if it resolves, the test fails
    await expect(triggerCall('demo-client', 'lead-bad-phone')).rejects.toBeInstanceOf(ApiError)

    // Secondary assertion: status code is exactly 422
    try {
      await triggerCall('demo-client', 'lead-bad-phone')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      expect((err as ApiError).status).toBe(422)
    }
  })

  it('throws ApiError with status 429 when cooldown is active', async () => {
    mockFetchError(429, 'Call attempt too soon after last attempt.')

    // Primary assertion: promise must reject — if it resolves, the test fails
    await expect(triggerCall('demo-client', 'lead-1')).rejects.toBeInstanceOf(ApiError)

    // Secondary assertion: status code is exactly 429
    try {
      await triggerCall('demo-client', 'lead-1')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      expect((err as ApiError).status).toBe(429)
    }
  })
})
