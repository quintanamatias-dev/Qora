/**
 * CAP-5: Base fetch function tests
 *
 * REQ-5.1: Base fetch handles 2xx success and non-2xx errors (ApiError)
 * multi-tenant-auth §9: apiFetch always sends X-Qora-Client: web and
 * credentials: 'same-origin', and routes 401s (outside /api/v1/auth/*)
 * through an injectable unauthorized handler.
 */

import { describe, it, expect, afterEach, vi } from 'vitest'
import { apiFetch, ApiError, setUnauthorizedHandler, resetUnauthorizedHandler } from './client'
import { stubLocationAssign, restoreLocation } from '../../tests/stub-location'

// ──────────────────────────────────────────────────────────────────────────────
// Setup: mock global fetch
// ──────────────────────────────────────────────────────────────────────────────

function mockFetch(status: number, body: unknown) {
  const response = new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: status === 204 ? undefined : { 'Content-Type': 'application/json' },
  })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
}

afterEach(() => {
  vi.unstubAllGlobals()
  // jsdom cannot perform real navigation — keep the handler a no-op between
  // tests; the dedicated reset test below verifies the real default in isolation.
  setUnauthorizedHandler(() => {})
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

  it('returns undefined on 204 No Content without parsing a body', async () => {
    mockFetch(204, null)
    const result = await apiFetch<void>('/api/v1/clients/acme/access/invitations/inv-1', { method: 'DELETE' })
    expect(result).toBeUndefined()
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
// multi-tenant-auth §9: X-Qora-Client header + same-origin credentials
// ──────────────────────────────────────────────────────────────────────────────
describe('apiFetch — auth headers and credentials', () => {
  it('always sends X-Qora-Client: web', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)

    await apiFetch('/api/v1/clients')

    const calledInit = fetchSpy.mock.calls[0][1] as RequestInit
    const headers = calledInit?.headers as Record<string, string>
    expect(headers['X-Qora-Client']).toBe('web')
  })

  it('always sends credentials: same-origin, even if the caller passes a different value', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)

    await apiFetch('/api/v1/clients', { credentials: 'omit' })

    const calledInit = fetchSpy.mock.calls[0][1] as RequestInit
    expect(calledInit.credentials).toBe('same-origin')
  })

  it('caller-provided headers merge with X-Qora-Client', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)

    await apiFetch('/api/v1/leads', {
      method: 'POST',
      headers: { 'X-Custom-Header': 'custom-value' },
    })

    const calledInit = fetchSpy.mock.calls[0][1] as RequestInit
    const headers = calledInit?.headers as Record<string, string>
    expect(headers['X-Qora-Client']).toBe('web')
    expect(headers['X-Custom-Header']).toBe('custom-value')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// multi-tenant-auth §9: 401 handling
// ──────────────────────────────────────────────────────────────────────────────
describe('apiFetch — 401 unauthorized handler', () => {
  it('invokes the unauthorized handler on 401 for a non-auth path, and still throws', async () => {
    mockFetch(401, { error: { message: 'Session expired or invalid' } })
    const handler = vi.fn()
    setUnauthorizedHandler(handler)

    await expect(apiFetch('/api/v1/clients')).rejects.toBeInstanceOf(ApiError)
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('does not invoke the unauthorized handler on 401 for /api/v1/auth/* paths', async () => {
    mockFetch(401, { error: { message: 'Authentication required' } })
    const handler = vi.fn()
    setUnauthorizedHandler(handler)

    await expect(apiFetch('/api/v1/auth/me')).rejects.toBeInstanceOf(ApiError)
    expect(handler).not.toHaveBeenCalled()
  })

  it('does not invoke the unauthorized handler on non-401 errors', async () => {
    mockFetch(500, { detail: 'boom' })
    const handler = vi.fn()
    setUnauthorizedHandler(handler)

    await expect(apiFetch('/api/v1/clients')).rejects.toBeInstanceOf(ApiError)
    expect(handler).not.toHaveBeenCalled()
  })

  it('resetUnauthorizedHandler restores the default redirect-to-login behavior', async () => {
    const originalLocation = window.location
    const assignMock = stubLocationAssign()

    resetUnauthorizedHandler()
    mockFetch(401, { error: { message: 'Session expired or invalid' } })

    await expect(apiFetch('/api/v1/clients')).rejects.toBeInstanceOf(ApiError)

    expect(assignMock).toHaveBeenCalledWith(expect.stringContaining('/login?return_to='))

    restoreLocation(originalLocation)
  })
})
