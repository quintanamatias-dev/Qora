/**
 * CAP-5: Clients API — typed endpoint functions
 *
 * REQ-5.2: src/api/clients.ts must export typed functions matching backend API surface.
 * TypeScript interfaces in src/api/types.ts must include Client.
 *
 * RED: Written before clients.ts exists — tests reference code that does not exist yet.
 */

import { describe, it, expect, vi, afterEach } from 'vitest'

// Mock the base fetch client so no real HTTP calls are made
vi.mock('./client', () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number
    constructor(message: string, status: number) {
      super(message)
      this.status = status
    }
  },
}))

import * as clientModule from './client'
import { fetchClient } from './clients'
import type { Client } from './types'

const mockApiFetch = vi.mocked(clientModule.apiFetch)

const mockClient: Client = {
  client_id: 'demo-client',
  broker_name: 'Demo Broker',
  agent_name: 'Demo Agent',
  voice_id: 'voice-1',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}

afterEach(() => {
  vi.clearAllMocks()
})

// ──────────────────────────────────────────────────────────────────────────────
// fetchClient
// ──────────────────────────────────────────────────────────────────────────────

describe('fetchClient', () => {
  it('calls the correct URL for the given clientId', async () => {
    mockApiFetch.mockResolvedValue(mockClient)

    await fetchClient('demo-client')

    expect(mockApiFetch).toHaveBeenCalledWith(
      '/api/v1/clients/demo-client'
    )
  })

  it('returns a typed Client object', async () => {
    mockApiFetch.mockResolvedValue(mockClient)

    const result = await fetchClient('demo-client')

    expect(result.client_id).toBe('demo-client')
    expect(result.broker_name).toBe('Demo Broker')
    expect(result.is_active).toBe(true)
  })

  it('uses URL-encoded clientId in the path', async () => {
    const encodedClient: Client = { ...mockClient, client_id: 'acme motors' }
    mockApiFetch.mockResolvedValue(encodedClient)

    await fetchClient('acme motors')

    expect(mockApiFetch).toHaveBeenCalledWith(
      '/api/v1/clients/acme%20motors'
    )
  })
})
