/**
 * AnalyticsDashboardPage — tests (task 6.1 RED)
 *
 * Spec: analytics-dashboard-ui
 * Tests:
 * - Page renders without crash
 * - Shows "Analytics" heading
 * - Renders PeriodSelector
 * - Renders section headings for each analytics section
 * - Shows loading state during fetch
 * - Shows error state on 500
 * - Period change updates query params
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider, Outlet } from 'react-router'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { AnalyticsDashboardPage } from './page'

// ──────────────────────────────────────────────────────────────────────────────
// MSW Analytics Handlers
// ──────────────────────────────────────────────────────────────────────────────

const overviewFixture = {
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

const serviceIssuesFixture = {
  issues: [
    { issue: 'billing_error', count: 5, rank: 1 },
    { issue: 'coverage_gap', count: 3, rank: 2 },
  ],
  period: 'month',
  start_date: '2026-03-29',
  end_date: '2026-04-28',
  agent_id: null,
}

const interestsFixture = {
  interests: [
    { interest: 'solar_panels', count: 10, trend: 'up', previous_count: 6 },
    { interest: 'auto_insurance', count: 7, trend: 'stable', previous_count: 7 },
  ],
  period: 'month',
  start_date: '2026-03-29',
  end_date: '2026-04-28',
  agent_id: null,
}

const agentStatsFixture = {
  agents: [
    {
      agent_id: 'agent-1',
      agent_name: 'Alice',
      total_calls: 15,
      outcome_distribution: { interested: 8, not_interested: 7 },
      avg_engagement_quality: 'high',
      conversion_rate: 0.53,
    },
  ],
  period: 'month',
  start_date: '2026-03-29',
  end_date: '2026-04-28',
}

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function createTestClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  })
}

function renderAnalyticsPage(clientId = 'demo-client') {
  const qc = createTestClient()
  const router = createMemoryRouter(
    [
      {
        path: '/app/:clientId',
        element: <Outlet />,
        children: [
          { path: 'analytics', element: <AnalyticsDashboardPage /> },
        ],
      },
    ],
    { initialEntries: [`/app/${clientId}/analytics`] }
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  return { qc }
}

// Register analytics MSW handlers before tests
beforeEach(() => {
  server.use(
    http.get('/api/v1/analytics/:clientId/overview', () =>
      HttpResponse.json(overviewFixture)
    ),
    http.get('/api/v1/analytics/:clientId/service-issues', () =>
      HttpResponse.json(serviceIssuesFixture)
    ),
    http.get('/api/v1/analytics/:clientId/interests', () =>
      HttpResponse.json(interestsFixture)
    ),
    http.get('/api/v1/analytics/:clientId/agent-stats', () =>
      HttpResponse.json(agentStatsFixture)
    ),
  )
})

// ──────────────────────────────────────────────────────────────────────────────
// Basic rendering
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalyticsDashboardPage — renders heading', () => {
  it('renders the "Analytics" heading', async () => {
    renderAnalyticsPage()
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /analytics/i })).toBeInTheDocument()
    )
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Period Selector
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalyticsDashboardPage — PeriodSelector', () => {
  it('renders a period selector with period options', async () => {
    renderAnalyticsPage()
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /analytics/i })).toBeInTheDocument()
    )
    // PeriodSelector has buttons for day/week/month/custom
    const monthButton = screen.getByRole('button', { name: /month/i })
    expect(monthButton).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Data rendering — sections visible
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalyticsDashboardPage — section headings', () => {
  it('renders MetricsOverview section with total calls', async () => {
    renderAnalyticsPage()
    await waitFor(() =>
      expect(screen.getByText('24')).toBeInTheDocument()
    )
  })

  it('renders ServiceIssuesList with ranked issues', async () => {
    renderAnalyticsPage()
    await waitFor(() =>
      expect(screen.getByText('billing_error')).toBeInTheDocument()
    )
    expect(screen.getByText('coverage_gap')).toBeInTheDocument()
  })

  it('renders InterestsList with trend indicators', async () => {
    renderAnalyticsPage()
    await waitFor(() =>
      expect(screen.getByText('solar_panels')).toBeInTheDocument()
    )
    // Trend indicator for "up"
    expect(screen.getByText(/↑/)).toBeInTheDocument()
  })

  it('renders AgentStatsTable with agent name', async () => {
    renderAnalyticsPage()
    await waitFor(() =>
      expect(screen.getByText('Alice')).toBeInTheDocument()
    )
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Loading state
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalyticsDashboardPage — loading state', () => {
  it('shows loading state while data is fetching', () => {
    // Delay all analytics responses
    server.use(
      http.get('/api/v1/analytics/:clientId/overview', async () => {
        await new Promise(r => setTimeout(r, 200))
        return HttpResponse.json(overviewFixture)
      }),
    )
    renderAnalyticsPage()
    // Should show some loading indicator immediately
    expect(screen.getByTestId('analytics-loading')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Error state
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalyticsDashboardPage — error state', () => {
  it('shows error message when overview API returns 500', async () => {
    server.use(
      http.get('/api/v1/analytics/:clientId/overview', () =>
        HttpResponse.json({ detail: 'Server error' }, { status: 500 })
      ),
    )
    renderAnalyticsPage()
    await waitFor(
      () => expect(screen.getByTestId('analytics-error')).toBeInTheDocument(),
      { timeout: 5000 }
    )
  })

  it('shows error when service-issues API fails (CRITICAL 8)', async () => {
    server.use(
      http.get('/api/v1/analytics/:clientId/service-issues', () =>
        HttpResponse.json({ detail: 'Server error' }, { status: 500 })
      ),
    )
    renderAnalyticsPage()
    await waitFor(
      () => expect(screen.getByTestId('analytics-error')).toBeInTheDocument(),
      { timeout: 5000 }
    )
  })

  it('shows error when interests API fails (CRITICAL 8)', async () => {
    server.use(
      http.get('/api/v1/analytics/:clientId/interests', () =>
        HttpResponse.json({ detail: 'Server error' }, { status: 500 })
      ),
    )
    renderAnalyticsPage()
    await waitFor(
      () => expect(screen.getByTestId('analytics-error')).toBeInTheDocument(),
      { timeout: 5000 }
    )
  })

  it('shows error when agent-stats API fails (CRITICAL 8)', async () => {
    server.use(
      http.get('/api/v1/analytics/:clientId/agent-stats', () =>
        HttpResponse.json({ detail: 'Server error' }, { status: 500 })
      ),
    )
    renderAnalyticsPage()
    await waitFor(
      () => expect(screen.getByTestId('analytics-error')).toBeInTheDocument(),
      { timeout: 5000 }
    )
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// CRITICAL 7: AgentFilter
// ──────────────────────────────────────────────────────────────────────────────

describe('AnalyticsDashboardPage — AgentFilter (CRITICAL 7)', () => {
  it('renders an AgentFilter select element', async () => {
    renderAnalyticsPage()
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /analytics/i })).toBeInTheDocument()
    )
    // AgentFilter renders a <select> or combobox for agent selection
    const agentSelect = screen.getByTestId('agent-filter')
    expect(agentSelect).toBeInTheDocument()
  })

  it('AgentFilter default value is "all" (no filter)', async () => {
    renderAnalyticsPage()
    await waitFor(() =>
      expect(screen.getByTestId('agent-filter')).toBeInTheDocument()
    )
    const select = screen.getByTestId('agent-filter') as HTMLSelectElement
    expect(select.value).toBe('all')
  })
})
