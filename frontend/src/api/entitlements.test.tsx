/**
 * Entitlements API + hooks (multi-tenant-readiness WU3)
 *
 * Spec: openspec/changes/multi-tenant-readiness/specs/plan-entitlements/spec.md
 */

import { describe, it, expect, afterEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../tests/mocks/server'
import { ApiError } from './client'
import { fetchEntitlements, updateEntitlements, fetchPlanCatalog } from './entitlements'
import { useEntitlements, useFeature } from './hooks'
import { makeEntitlements } from '../../tests/mocks/entitlements'

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

afterEach(() => vi.unstubAllGlobals())

describe('entitlements API', () => {
  it('GETs /api/v1/clients/:id/entitlements', async () => {
    const result = await fetchEntitlements('acme-motors')
    expect(result.client_id).toBe('acme-motors')
    expect(result.features.analytics).toBe(true)
  })

  it('PUTs plan and overrides', async () => {
    let body: unknown
    server.use(
      http.put('/api/v1/clients/:clientId/entitlements', async ({ request, params }) => {
        body = await request.json()
        return HttpResponse.json(makeEntitlements({ client_id: String(params.clientId), plan: 'starter' }))
      }),
    )
    const result = await updateEntitlements('acme-motors', { plan: 'starter', overrides: { limits: { max_agents: 2 } } })
    expect(body).toEqual({ plan: 'starter', overrides: { limits: { max_agents: 2 } } })
    expect(result.plan).toBe('starter')
  })

  it('GETs the plan catalog', async () => {
    const catalog = await fetchPlanCatalog()
    expect(catalog.plans.map((p) => p.name)).toContain('pilot')
  })
})

describe('ApiError.reason', () => {
  it('exposes the backend reason code from the canonical envelope', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: 429, message: 'Plan limit reached', reason: 'plan_limit_reached', request_id: '' } }),
          { status: 429 },
        ),
      ),
    )
    const { apiFetch } = await import('./client')
    const err = await apiFetch('/x').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).reason).toBe('plan_limit_reached')
    expect((err as ApiError).message).toBe('Plan limit reached')
  })

  it('is undefined when the envelope has no reason', () => {
    expect(new ApiError(404, { error: { code: 404, message: 'nope' } }).reason).toBeUndefined()
  })
})

describe('useFeature', () => {
  it('is true while loading so the UI does not flicker features away', () => {
    const { result } = renderHook(() => useFeature('acme-motors', 'analytics'), { wrapper })
    expect(result.current).toBe(true)
  })

  it('reflects a disabled feature once entitlements load', async () => {
    server.use(
      http.get('/api/v1/clients/:clientId/entitlements', () =>
        HttpResponse.json(makeEntitlements({ features: { analytics: false } })),
      ),
    )
    const { result } = renderHook(() => useFeature('acme-motors', 'analytics'), { wrapper })
    await waitFor(() => expect(result.current).toBe(false))
  })

  it('useEntitlements exposes usage', async () => {
    const { result } = renderHook(() => useEntitlements('acme-motors'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data?.usage.monthly_minutes).toBeTypeOf('number')
  })
})
