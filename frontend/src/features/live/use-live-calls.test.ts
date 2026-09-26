import { describe, it, expect, vi, afterEach } from 'vitest'
import React from 'react'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/api/live', () => ({
  fetchActiveCalls: vi.fn(),
}))
vi.mock('@/api/hooks', () => ({
  useAgents: vi.fn(),
}))

import * as liveApi from '@/api/live'
import * as apiHooks from '@/api/hooks'
import { useLiveCalls } from './use-live-calls'
import type { LiveCallsResponse } from '@/api/live'
import type { Agent } from '@/api/types'

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: qc }, children)
  }
}

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    agent_id: 'agent-1',
    client_id: 'demo-client',
    slug: 'juanma',
    name: 'Juanma',
    voice_id: 'voice-1',
    model: 'gpt-4o',
    system_prompt: null,
    tools_enabled: [],
    is_active: true,
    is_default: true,
    created_at: '2026-01-01T00:00:00Z',
    has_prompt: true,
    has_elevenlabs_agent_id: true,
    is_conversation_ready: true,
    tts_speed: 1,
    tts_stability: 0.5,
    ...overrides,
  } as Agent
}

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

afterEach(() => {
  vi.clearAllMocks()
})

describe('useLiveCalls', () => {
  it('maps API calls to canvas call states and exposes agents/today/memory', async () => {
    vi.mocked(liveApi.fetchActiveCalls).mockResolvedValue(mockResponse)
    vi.mocked(apiHooks.useAgents).mockReturnValue({ data: [makeAgent()], isLoading: false } as ReturnType<
      typeof apiHooks.useAgents
    >)

    const { result } = renderHook(() => useLiveCalls('demo-client'), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.calls).toHaveLength(1))

    expect(result.current.calls[0].state).toBe('talk')
    expect(result.current.calls[0].agentId).toBe('agent-1')
    expect(result.current.agents).toEqual([{ id: 'agent-1', name: 'Juanma', isLive: true }])
    expect(result.current.today).toEqual({ calls_total: 5, completed: 3 })
    expect(result.current.memoryTotal).toBe(42)
    expect(result.current.recentFacts).toHaveLength(1)
  })

  it('marks an agent as not live when inactive or not conversation-ready', async () => {
    vi.mocked(liveApi.fetchActiveCalls).mockResolvedValue({ ...mockResponse, calls: [] })
    vi.mocked(apiHooks.useAgents).mockReturnValue({
      data: [makeAgent({ is_active: false })],
      isLoading: false,
    } as ReturnType<typeof apiHooks.useAgents>)

    const { result } = renderHook(() => useLiveCalls('demo-client'), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.today).not.toBeNull())
    expect(result.current.agents).toEqual([{ id: 'agent-1', name: 'Juanma', isLive: false }])
  })

  it('does not flag the first poll\'s facts as new', async () => {
    vi.mocked(liveApi.fetchActiveCalls).mockResolvedValue(mockResponse)
    vi.mocked(apiHooks.useAgents).mockReturnValue({ data: [], isLoading: false } as unknown as ReturnType<
      typeof apiHooks.useAgents
    >)

    const { result } = renderHook(() => useLiveCalls('demo-client'), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.today).not.toBeNull())
    expect(result.current.newFacts).toHaveLength(0)
  })
})
