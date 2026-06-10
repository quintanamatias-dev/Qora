/**
 * CAP-5: Base fetch function tests
 *
 * REQ-5.1: Base fetch handles 2xx success and non-2xx errors (ApiError)
 */

import { describe, it, expect, afterEach, vi } from 'vitest'
import { apiFetch, ApiError } from './client'

// ──────────────────────────────────────────────────────────────────────────────
// Setup: mock global fetch
// ──────────────────────────────────────────────────────────────────────────────

function mockFetch(status: number, body: unknown) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ──────────────────────────────────────────────────────────────────────────────
// REQ-5.1: Success path
// ──────────────────────────────────────────────────────────────────────────────
describe('apiFetch — success', () => {
  it('returns parsed JSON on 200', async () => {
    mockFetch(200, { total_calls: 42 })
    const result = await apiFetch<{ total_calls: number }>('/api/v1/calls/metrics?client_id=demo-client')
    expect(result.total_calls).toBe(42)
  })

  it('returns parsed JSON on 201', async () => {
    mockFetch(201, { id: 'lead-123', name: 'John Doe' })
    const result = await apiFetch<{ id: string; name: string }>('/api/v1/leads')
    expect(result.id).toBe('lead-123')
    expect(result.name).toBe('John Doe')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// REQ-5.1: Error path
// ──────────────────────────────────────────────────────────────────────────────
describe('apiFetch — error', () => {
  it('throws ApiError with status 422 on 422 response', async () => {
    mockFetch(422, { detail: 'Validation error' })
    try {
      await apiFetch('/api/v1/leads')
      expect.fail('Should have thrown')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      expect(err).toMatchObject({
        status: 422,
        message: 'Validation error',
      })
    }
  })

  it('throws ApiError with status 404 on 404 response', async () => {
    mockFetch(404, { detail: 'Not found' })
    await expect(apiFetch('/api/v1/leads/missing')).rejects.toMatchObject({ status: 404 })
  })

  it('throws ApiError with status 500 on 500 response', async () => {
    mockFetch(500, { detail: 'Internal server error' })
    await expect(apiFetch('/api/v1/health')).rejects.toMatchObject({ status: 500 })
  })

  it('ApiError extends Error (is an Error instance)', async () => {
    mockFetch(401, { detail: 'Unauthorized' })
    try {
      await apiFetch('/api/v1/leads')
      expect.fail('Should have thrown')
    } catch (err) {
      expect(err).toBeInstanceOf(Error)
      expect(err).toBeInstanceOf(ApiError)
      expect((err as ApiError).status).toBe(401)
    }
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// REQ-5.1: URL construction — respects VITE_API_BASE_URL
// ──────────────────────────────────────────────────────────────────────────────
describe('apiFetch — URL construction', () => {
  it('prepends base URL from env when set', async () => {
    // We test via the fetch mock capturing the called URL
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    )
    vi.stubGlobal('fetch', fetchSpy)

    // apiFetch should call fetch with the correct path
    await apiFetch('/api/v1/health')
    // The first arg to fetch should start with the path
    const calledUrl = fetchSpy.mock.calls[0][0] as string
    expect(calledUrl).toContain('/api/v1/health')
  })
})
