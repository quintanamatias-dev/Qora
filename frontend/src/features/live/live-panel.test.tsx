import { describe, it, expect, vi, afterEach } from 'vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/api/live', () => ({
  fetchActiveCalls: vi.fn(),
}))
vi.mock('@/api/hooks', () => ({
  useAgents: vi.fn(),
  useClient: vi.fn(),
}))

import * as liveApi from '@/api/live'
import * as apiHooks from '@/api/hooks'
import { LivePanel } from './live-panel'
import type { LiveCallsResponse } from '@/api/live'
import type { Agent, Client } from '@/api/types'

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

function renderWithProviders(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('LivePanel', () => {
  it('renders "N llamadas en curso" headline from mocked live-call data', async () => {
    vi.mocked(liveApi.fetchActiveCalls).mockResolvedValue(mockResponse)
    vi.mocked(apiHooks.useAgents).mockReturnValue({ data: [makeAgent()], isLoading: false } as ReturnType<
      typeof apiHooks.useAgents
    >)
    vi.mocked(apiHooks.useClient).mockReturnValue({
      data: { client_id: 'demo-client', name: 'Quintana Seguros', scheduler_timezone: 'America/Argentina/Buenos_Aires' } as Client,
      isLoading: false,
    } as ReturnType<typeof apiHooks.useClient>)

    renderWithProviders(<LivePanel clientId="demo-client" />)

    expect(await screen.findByText(/llamada(s)? en curso/)).toBeInTheDocument()
  })

  it('renders without crashing when jsdom has no canvas 2d context', async () => {
    // jsdom's HTMLCanvasElement.getContext always returns null unless a
    // canvas polyfill is installed — assert the component tolerates that.
    vi.mocked(liveApi.fetchActiveCalls).mockResolvedValue({ ...mockResponse, calls: [] })
    vi.mocked(apiHooks.useAgents).mockReturnValue({ data: [], isLoading: false } as unknown as ReturnType<
      typeof apiHooks.useAgents
    >)
    vi.mocked(apiHooks.useClient).mockReturnValue({ data: undefined, isLoading: true } as ReturnType<
      typeof apiHooks.useClient
    >)

    expect(() => renderWithProviders(<LivePanel clientId="demo-client" embedded />)).not.toThrow()
  })

  it('hides the Memoria counter when there is no memory data', async () => {
    vi.mocked(liveApi.fetchActiveCalls).mockResolvedValue({
      ...mockResponse,
      calls: [],
      recent_facts: [],
      memory_total: 0,
    })
    vi.mocked(apiHooks.useAgents).mockReturnValue({ data: [], isLoading: false } as unknown as ReturnType<
      typeof apiHooks.useAgents
    >)
    vi.mocked(apiHooks.useClient).mockReturnValue({ data: undefined, isLoading: false } as ReturnType<
      typeof apiHooks.useClient
    >)

    renderWithProviders(<LivePanel clientId="demo-client" />)

    await screen.findByText(/llamadas en curso/)
    expect(screen.queryByText('Memoria')).not.toBeInTheDocument()
  })
})
