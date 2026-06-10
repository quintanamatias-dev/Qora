/**
 * Analytics API — tests for fetcher functions (task 5.1 RED)
 *
 * Tests verify:
 * - Correct URL construction with period params
 * - agent_id propagation
 * - Custom period with start_date/end_date
 * - Response types are returned correctly
 */

import { describe, it, expect, afterEach, vi } from 'vitest'
import {
  fetchAnalyticsOverview,
  fetchAnalyticsServiceIssues,
  fetchAnalyticsInterests,
  fetchAnalyticsAgentStats,
} from './analytics'
import type {
  AnalyticsOverviewResponse,
  AnalyticsServiceIssuesResponse,
  AnalyticsInterestsResponse,
  AnalyticsAgentStatsResponse,
} from './types'

// ──────────────────────────────────────────────────────────────────────────────
// Fixtures
// ──────────────────────────────────────────────────────────────────────────────

const mockOverview: AnalyticsOverviewResponse = {
  total_calls: 24,
  outcome_distribution: { interested: 12, not_interested: 8, busy: 4 },
  avg_call_duration_seconds: 120.5,
  conversion_rate: 0.5,
  period: 'month',
  start_date: '2026-03-29',
  end_date: '2026-04-28',
  agent_id: null,
}

const mockServiceIssues: AnalyticsServiceIssuesResponse = {
  issues: [
    { issue: 'billing_error', count: 5, rank: 1 },
    { issue: 'coverage_gap', count: 3, rank: 2 },
  ],
  period: 'week',
  start_date: '2026-04-21',
  end_date: '2026-04-28',
  agent_id: null,
}

const mockInterests: AnalyticsInterestsResponse = {
  interests: [
    { interest: 'solar_panels', count: 10, trend: 'up', previous_count: 6 },
  ],
  period: 'week',
  start_date: '2026-04-21',
  end_date: '2026-04-28',
  agent_id: null,
}

const mockAgentStats: AnalyticsAgentStatsResponse = {
  agents: [
    {
      agent_id: 'agent-1',
      agent_name: 'Alice',
      total_calls: 15,
      outcome_distribution: { completed_positive: 8, completed_negative: 7 },
      conversion_rate: 0.53,
    },
  ],
  period: 'month',
  start_date: '2026-03-29',
  end_date: '2026-04-28',
}

function spyFetch(body: unknown, status = 200) {
  const spy = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  )
  vi.stubGlobal('fetch', spy)
  return spy
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ──────────────────────────────────────────────────────────────────────────────
// fetchAnalyticsOverview
// ──────────────────────────────────────────────────────────────────────────────
describe('fetchAnalyticsOverview', () => {
  it('calls correct URL with client_id and default period=month', async () => {
    const spy = spyFetch(mockOverview)

    const result = await fetchAnalyticsOverview('quintana-seguros', { period: 'month' })

    expect(result.total_calls).toBe(24)
    expect(result.period).toBe('month')
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('/api/v1/analytics/quintana-seguros/overview')
    expect(url).toContain('period=month')
  })

  it('includes agent_id in URL when provided', async () => {
    const spy = spyFetch(mockOverview)

    await fetchAnalyticsOverview('quintana-seguros', {
      period: 'week',
      agentId: 'agent-abc',
    })

    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('agent_id=agent-abc')
    expect(url).toContain('period=week')
  })

  it('includes start_date and end_date for custom period', async () => {
    const spy = spyFetch(mockOverview)

    await fetchAnalyticsOverview('quintana-seguros', {
      period: 'custom',
      startDate: '2026-01-01',
      endDate: '2026-01-31',
    })

    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('period=custom')
    expect(url).toContain('start_date=2026-01-01')
    expect(url).toContain('end_date=2026-01-31')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// fetchAnalyticsServiceIssues
// ──────────────────────────────────────────────────────────────────────────────
describe('fetchAnalyticsServiceIssues', () => {
  it('calls correct URL and returns ranked issues', async () => {
    const spy = spyFetch(mockServiceIssues)

    const result = await fetchAnalyticsServiceIssues('quintana-seguros', { period: 'week' })

    expect(result.issues).toHaveLength(2)
    expect(result.issues[0].issue).toBe('billing_error')
    expect(result.issues[0].rank).toBe(1)
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('/api/v1/analytics/quintana-seguros/service-issues')
    expect(url).toContain('period=week')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// fetchAnalyticsInterests
// ──────────────────────────────────────────────────────────────────────────────
describe('fetchAnalyticsInterests', () => {
  it('calls correct URL and returns interests with trend', async () => {
    const spy = spyFetch(mockInterests)

    const result = await fetchAnalyticsInterests('quintana-seguros', { period: 'week' })

    expect(result.interests).toHaveLength(1)
    expect(result.interests[0].interest).toBe('solar_panels')
    expect(result.interests[0].trend).toBe('up')
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('/api/v1/analytics/quintana-seguros/interests')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// fetchAnalyticsAgentStats
// ──────────────────────────────────────────────────────────────────────────────
describe('fetchAnalyticsAgentStats', () => {
  it('calls correct URL and returns agent stats', async () => {
    const spy = spyFetch(mockAgentStats)

    const result = await fetchAnalyticsAgentStats('quintana-seguros', { period: 'month' })

    expect(result.agents).toHaveLength(1)
    expect(result.agents[0].agent_id).toBe('agent-1')
    expect(result.agents[0].total_calls).toBe(15)
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain('/api/v1/analytics/quintana-seguros/agent-stats')
  })
})
