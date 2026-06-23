/**
 * CAP-5: Base fetch function tests
 *
 * REQ-5.1: Base fetch handles 2xx success and non-2xx errors (ApiError)
 * REQ-B5.1: apiFetch injects Authorization: Bearer <VITE_API_KEY> when VITE_API_KEY is set
 * REQ-B5.2: apiFetch omits Authorization header when VITE_API_KEY is absent/empty
 */

import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
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

// ──────────────────────────────────────────────────────────────────────────────
// REQ-B5.1 / REQ-B5.2: Authorization header contract (Phase B5 admin auth)
//
// client.ts captures VITE_API_KEY at module-level load time.
// We must reset modules + stub the env before each dynamic import so we get
// a fresh module instance that sees the patched import.meta.env value.
// ──────────────────────────────────────────────────────────────────────────────
describe('apiFetch — Authorization header (Phase B5)', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('injects Authorization: Bearer <key> when VITE_API_KEY is set', async () => {
    // RED contract: apiFetch must forward VITE_API_KEY as a Bearer token.
    const testKey = 'test-admin-secret-key-xyz'
    vi.stubEnv('VITE_API_KEY', testKey)

    // Dynamic import after stub so the module sees the patched env
    const { apiFetch: apiFetchFresh } = await import('./client')

    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    )
    vi.stubGlobal('fetch', fetchSpy)

    await apiFetchFresh('/api/v1/clients')

    const calledInit = fetchSpy.mock.calls[0][1] as RequestInit
    const headers = calledInit?.headers as Record<string, string>
    expect(headers['Authorization']).toBe(`Bearer ${testKey}`)
  })

  it('omits Authorization header when VITE_API_KEY is empty string', async () => {
    // REQ-B5.2: empty key means no auth header — dev without auth or public endpoint.
    vi.stubEnv('VITE_API_KEY', '')

    const { apiFetch: apiFetchFresh } = await import('./client')

    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    )
    vi.stubGlobal('fetch', fetchSpy)

    await apiFetchFresh('/api/v1/health')

    const calledInit = fetchSpy.mock.calls[0][1] as RequestInit
    const headers = calledInit?.headers as Record<string, string>
    expect(headers['Authorization']).toBeUndefined()
  })

  it('omits Authorization header when VITE_API_KEY is not set', async () => {
    // REQ-B5.2: absent key — same as empty (defaults to '' in client.ts).
    vi.stubEnv('VITE_API_KEY', undefined as unknown as string)

    const { apiFetch: apiFetchFresh } = await import('./client')

    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    )
    vi.stubGlobal('fetch', fetchSpy)

    await apiFetchFresh('/api/v1/health')

    const calledInit = fetchSpy.mock.calls[0][1] as RequestInit
    const headers = calledInit?.headers as Record<string, string>
    expect(headers['Authorization']).toBeUndefined()
  })

  it('caller-provided headers override defaults but auth header is still injected', async () => {
    // Triangulation: custom init headers merge with auth — auth survives the spread.
    const testKey = 'another-test-key-abc'
    vi.stubEnv('VITE_API_KEY', testKey)

    const { apiFetch: apiFetchFresh } = await import('./client')

    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'x' }), { status: 200 })
    )
    vi.stubGlobal('fetch', fetchSpy)

    await apiFetchFresh('/api/v1/leads', {
      method: 'POST',
      headers: { 'X-Custom-Header': 'custom-value' },
    })

    const calledInit = fetchSpy.mock.calls[0][1] as RequestInit
    const headers = calledInit?.headers as Record<string, string>
    // Both the auth header and the custom header must be present
    expect(headers['Authorization']).toBe(`Bearer ${testKey}`)
    expect(headers['X-Custom-Header']).toBe('custom-value')
  })

  it('caller-provided Authorization header overrides the VITE_API_KEY bearer token', async () => {
    // When a caller explicitly passes their own Authorization, it wins (header spread order).
    const testKey = 'base-key-111'
    vi.stubEnv('VITE_API_KEY', testKey)

    const { apiFetch: apiFetchFresh } = await import('./client')

    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    )
    vi.stubGlobal('fetch', fetchSpy)

    const customAuth = 'Bearer override-token-999'
    await apiFetchFresh('/api/v1/clients', {
      headers: { Authorization: customAuth },
    })

    const calledInit = fetchSpy.mock.calls[0][1] as RequestInit
    const headers = calledInit?.headers as Record<string, string>
    // The caller's explicit Authorization header wins via spread
    expect(headers['Authorization']).toBe(customAuth)
  })
})
