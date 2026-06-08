/**
 * Integrations API tests — T16/T17
 *
 * Verifies:
 * - fetchIntegrations calls correct URL
 * - updateIntegration calls correct URL with PUT
 * - testIntegrationConnection calls correct URL with POST
 * - Types are correct shape
 */

import { describe, it, expect } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { fetchIntegrations, updateIntegration, testIntegrationConnection } from './integrations'
import { useIntegrations, useUpdateIntegration, useTestIntegration } from './hooks'
import type { IntegrationConfig } from './types'

// ──────────────────────────────────────────────────────────────────────────────
// API functions — MSW-intercepted
// ──────────────────────────────────────────────────────────────────────────────

describe('fetchIntegrations', () => {
  it('returns an array for a configured client', async () => {
    const result = await fetchIntegrations('quintana-seguros')
    expect(Array.isArray(result)).toBe(true)
    expect(result.length).toBeGreaterThan(0)
  })

  it('returns empty array for a client with no integrations', async () => {
    const result = await fetchIntegrations('demo-client')
    expect(Array.isArray(result)).toBe(true)
    expect(result.length).toBe(0)
  })

  it('returned integration has all required fields', async () => {
    const result = await fetchIntegrations('quintana-seguros')
    const item = result[0] as IntegrationConfig
    expect(item).toHaveProperty('provider')
    expect(item).toHaveProperty('base_id')
    expect(item).toHaveProperty('table_id')
    expect(item).toHaveProperty('api_key_env')
    expect(item).toHaveProperty('match_field')
    expect(item).toHaveProperty('field_count')
    expect(item).toHaveProperty('connected')
  })

  it('api_key_env field is a string (env var name, not a secret)', async () => {
    const result = await fetchIntegrations('quintana-seguros')
    const item = result[0]
    expect(typeof item.api_key_env).toBe('string')
    // The fixture sets api_key_env to 'QUINTANA_AIRTABLE_API_KEY'
    expect(item.api_key_env).toBe('QUINTANA_AIRTABLE_API_KEY')
  })
})

describe('updateIntegration', () => {
  it('calls PUT and returns updated config', async () => {
    const result = await updateIntegration('quintana-seguros', 'airtable', {
      base_id: 'appNEW',
    })
    expect(result).toHaveProperty('provider', 'airtable')
    expect(result).toHaveProperty('base_id', 'appNEW')
  })
})

describe('testIntegrationConnection', () => {
  it('returns success and record_count for quintana-seguros/airtable', async () => {
    const result = await testIntegrationConnection('quintana-seguros', 'airtable')
    expect(result.success).toBe(true)
    expect(typeof result.message).toBe('string')
    expect(result.record_count).toBe(42)
  })

  it('returns failure for unconfigured client/provider', async () => {
    const result = await testIntegrationConnection('demo-client', 'airtable')
    expect(result.success).toBe(false)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Hooks — via renderHook
// ──────────────────────────────────────────────────────────────────────────────

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: qc }, children)
  }
}

describe('useIntegrations hook', () => {
  it('returns array of integrations for configured client', async () => {
    const { result } = renderHook(
      () => useIntegrations('quintana-seguros'),
      { wrapper: createWrapper() },
    )
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })
    expect(result.current.data).toBeDefined()
    expect(Array.isArray(result.current.data)).toBe(true)
    expect(result.current.data?.length).toBeGreaterThan(0)
  })

  it('returns empty array for client with no integrations', async () => {
    const { result } = renderHook(
      () => useIntegrations('demo-client'),
      { wrapper: createWrapper() },
    )
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })
    expect(result.current.data).toEqual([])
  })

  it('is disabled when clientId is empty', () => {
    const { result } = renderHook(
      () => useIntegrations(''),
      { wrapper: createWrapper() },
    )
    // Disabled queries stay in loading without fetching
    expect(result.current.isLoading).toBe(false)
    expect(result.current.fetchStatus).toBe('idle')
  })
})

describe('useUpdateIntegration hook', () => {
  it('is a mutation hook with mutate function', () => {
    const { result } = renderHook(
      () => useUpdateIntegration('quintana-seguros'),
      { wrapper: createWrapper() },
    )
    expect(typeof result.current.mutate).toBe('function')
  })
})

describe('useTestIntegration hook', () => {
  it('is a mutation hook with mutate function', () => {
    const { result } = renderHook(
      () => useTestIntegration('quintana-seguros'),
      { wrapper: createWrapper() },
    )
    expect(typeof result.current.mutate).toBe('function')
  })
})
