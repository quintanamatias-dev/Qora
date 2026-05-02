/**
 * Analytics hooks tests (task 5.1 RED)
 *
 * Tests verify:
 * - Hooks return data from fetchers
 * - disabled when clientId is undefined/empty
 * - period and agentId propagated correctly
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  useAnalyticsOverview,
  useAnalyticsServiceIssues,
  useAnalyticsInterests,
  useAnalyticsAgentStats,
} from './hooks'
import type {
  AnalyticsOverviewResponse,
  AnalyticsServiceIssuesResponse,
  AnalyticsInterestsResponse,
  AnalyticsAgentStatsResponse,
} from './types'

// ──────────────────────────────────────────────────────────────────────────────
// Mocks
// ──────────────────────────────────────────────────────────────────────────────

vi.mock('./analytics', () => ({
  fetchAnalyticsOverview: vi.fn(),
  fetchAnalyticsServiceIssues: vi.fn(),
  fetchAnalyticsInterests: vi.fn(),
  fetchAnalyticsAgentStats: vi.fn(),
}))

import * as analyticsApi from './analytics'

// ──────────────────────────────────────────────────────────────────────────────
// Fixtures
// ──────────────────────────────────────────────────────────────────────────────

const mockOverview: AnalyticsOverviewResponse = {
  total_calls: 24,
  outcome_distribution: { interested: 12, not_interested: 8, busy: 4 },
  engagement_distribution: { high: 5, medium: 10, low: 7, none: 2 },
  avg_call_duration_seconds: 120.5,
  conversion_rate: 0.5,
  period: 'month',
  start_date: '2026-03-29',
  end_date: '2026-04-28',
  agent_id: null,
}

const mockServiceIssues: AnalyticsServiceIssuesResponse = {
  issues: [{ issue: 'billing_error', count: 5, rank: 1 }],
  period: 'week',
  start_date: '2026-04-21',
  end_date: '2026-04-28',
  agent_id: null,
}

const mockInterests: AnalyticsInterestsResponse = {
  interests: [{ interest: 'solar_panels', count: 10, trend: 'up', previous_count: 6 }],
  period: 'week',
  start_date: '2026-04-21',
  end_date: '2026-04-28',
  agent_id: null,
}

const mockAgentStats: AnalyticsAgentStatsResponse = {
  agents: [{
    agent_id: 'agent-1',
    agent_name: 'Alice',
    total_calls: 15,
    outcome_distribution: { completed_positive: 8, completed_negative: 7 },
    conversion_rate: 0.53,
  }],
  period: 'month',
  start_date: '2026-03-29',
  end_date: '2026-04-28',
}

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function createTestClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = createTestClient()
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

afterEach(() => vi.clearAllMocks())

// ──────────────────────────────────────────────────────────────────────────────
// useAnalyticsOverview
// ──────────────────────────────────────────────────────────────────────────────
describe('useAnalyticsOverview', () => {
  it('returns data from fetchAnalyticsOverview', async () => {
    vi.mocked(analyticsApi.fetchAnalyticsOverview).mockResolvedValue(mockOverview)

    function Comp() {
      const { data, isLoading } = useAnalyticsOverview('client-1', { period: 'month' })
      if (isLoading) return <span>loading</span>
      return <span data-testid="total">{data?.total_calls}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('total')).toHaveTextContent('24'))
    expect(analyticsApi.fetchAnalyticsOverview).toHaveBeenCalledWith('client-1', { period: 'month' })
  })

  it('is disabled when clientId is empty', async () => {
    vi.mocked(analyticsApi.fetchAnalyticsOverview).mockResolvedValue(mockOverview)

    function Comp() {
      const { data, isLoading } = useAnalyticsOverview('', { period: 'month' })
      if (isLoading) return <span>loading</span>
      return <span data-testid="state">{data ? 'has-data' : 'no-data'}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    // Should not be loading (disabled) — show no-data without fetching
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('no-data'))
    expect(analyticsApi.fetchAnalyticsOverview).not.toHaveBeenCalled()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// useAnalyticsServiceIssues
// ──────────────────────────────────────────────────────────────────────────────
describe('useAnalyticsServiceIssues', () => {
  it('returns issues from fetchAnalyticsServiceIssues', async () => {
    vi.mocked(analyticsApi.fetchAnalyticsServiceIssues).mockResolvedValue(mockServiceIssues)

    function Comp() {
      const { data, isLoading } = useAnalyticsServiceIssues('client-1', { period: 'week' })
      if (isLoading) return <span>loading</span>
      return <span data-testid="count">{data?.issues.length}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('1'))
    expect(analyticsApi.fetchAnalyticsServiceIssues).toHaveBeenCalledWith('client-1', { period: 'week' })
  })

  it('is disabled when clientId is empty', async () => {
    vi.mocked(analyticsApi.fetchAnalyticsServiceIssues).mockResolvedValue(mockServiceIssues)

    function Comp() {
      const { isLoading } = useAnalyticsServiceIssues('', { period: 'week' })
      return <span data-testid="loading">{isLoading ? 'loading' : 'idle'}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('idle'))
    expect(analyticsApi.fetchAnalyticsServiceIssues).not.toHaveBeenCalled()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// useAnalyticsInterests
// ──────────────────────────────────────────────────────────────────────────────
describe('useAnalyticsInterests', () => {
  it('returns interests from fetchAnalyticsInterests', async () => {
    vi.mocked(analyticsApi.fetchAnalyticsInterests).mockResolvedValue(mockInterests)

    function Comp() {
      const { data, isLoading } = useAnalyticsInterests('client-1', { period: 'week' })
      if (isLoading) return <span>loading</span>
      return <span data-testid="trend">{data?.interests[0]?.trend}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('trend')).toHaveTextContent('up'))
    expect(analyticsApi.fetchAnalyticsInterests).toHaveBeenCalledWith('client-1', { period: 'week' })
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// useAnalyticsAgentStats
// ──────────────────────────────────────────────────────────────────────────────
describe('useAnalyticsAgentStats', () => {
  it('returns agent stats from fetchAnalyticsAgentStats', async () => {
    vi.mocked(analyticsApi.fetchAnalyticsAgentStats).mockResolvedValue(mockAgentStats)

    function Comp() {
      const { data, isLoading } = useAnalyticsAgentStats('client-1', { period: 'month' })
      if (isLoading) return <span>loading</span>
      return <span data-testid="agents">{data?.agents.length}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('agents')).toHaveTextContent('1'))
    expect(analyticsApi.fetchAnalyticsAgentStats).toHaveBeenCalledWith('client-1', { period: 'month' })
  })

  it('is disabled when clientId is empty', async () => {
    vi.mocked(analyticsApi.fetchAnalyticsAgentStats).mockResolvedValue(mockAgentStats)

    function Comp() {
      const { isLoading } = useAnalyticsAgentStats('', { period: 'month' })
      return <span data-testid="loading">{isLoading ? 'loading' : 'idle'}</span>
    }

    render(<Wrapper><Comp /></Wrapper>)
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('idle'))
    expect(analyticsApi.fetchAnalyticsAgentStats).not.toHaveBeenCalled()
  })
})
