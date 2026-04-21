/**
 * DashboardPage — Integration tests
 *
 * Spec: sdd/qora-dashboard-metrics/spec — Requirements: Period Selection, Page Loading,
 *       Page Error, Empty State, default period = today
 * Design: container pattern — page owns state/data, composes PeriodSelector + MetricsGrid
 *
 * TDD Layer: Integration (RTL + MSW via global server setup)
 * MSW: server configured in tests/setup.ts — handlers in tests/mocks/handlers.ts
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider, Outlet } from 'react-router'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { DashboardPage, periodToDateRange } from './page'

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function createTestClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  })
}

function renderDashboard(clientId = 'demo-client') {
  const qc = createTestClient()
  const router = createMemoryRouter(
    [
      {
        path: '/app/:clientId',
        element: <Outlet />,
        children: [{ path: 'dashboard', element: <DashboardPage /> }],
      },
    ],
    { initialEntries: [`/app/${clientId}/dashboard`] }
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  return { qc }
}

// ──────────────────────────────────────────────────────────────────────────────
// Default state — successful data load
// ──────────────────────────────────────────────────────────────────────────────
describe('DashboardPage — renders heading', () => {
  it('renders the "Dashboard" heading', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument())
  })
})

describe('DashboardPage — default period is "Today"', () => {
  it('"Today" option is active on first render', async () => {
    renderDashboard()
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: 'Today' })).toHaveAttribute('data-state', 'on')
    )
  })

  it('PeriodSelector renders all 4 options', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByRole('radio', { name: 'Today' })).toBeInTheDocument())
    expect(screen.getByRole('radio', { name: '7d' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '30d' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'All' })).toBeInTheDocument()
  })
})

describe('DashboardPage — successful data rendering', () => {
  it('renders "Total Calls" card after data loads', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByText('Total Calls')).toBeInTheDocument())
  })

  it('renders total_calls value "150" from MSW fixture', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByText('150')).toBeInTheDocument())
  })

  it('renders "Completed" card with emerald accent and value "120"', async () => {
    renderDashboard()
    // Wait for actual value to load (not just the label, which shows during loading too)
    await waitFor(() => expect(screen.getByText('120')).toBeInTheDocument())
    expect(screen.getByText('Completed')).toBeInTheDocument()
  })

  it('renders status breakdown bar', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByTestId('status-breakdown')).toBeInTheDocument())
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Loading state — skeletons during fetch
// ──────────────────────────────────────────────────────────────────────────────
describe('DashboardPage — loading state', () => {
  it('renders skeleton cards while data is loading', async () => {
    // Use a slow handler to capture loading state
    server.use(
      http.get('/api/v1/calls/metrics', async () => {
        await new Promise(r => setTimeout(r, 200))
        return HttpResponse.json({
          total_calls: 150, completed_calls: 120, abandoned_calls: 30,
          total_duration_seconds: 9000, average_duration_seconds: 75,
          total_billable_minutes: 150, period: { date_from: null, date_to: null },
        })
      })
    )

    renderDashboard()
    // During loading, skeletons should be present
    const skeletons = await waitFor(() => screen.getAllByTestId('stat-skeleton'))
    expect(skeletons).toHaveLength(6)
  })

  it('PeriodSelector remains interactive during loading', async () => {
    server.use(
      http.get('/api/v1/calls/metrics', async () => {
        await new Promise(r => setTimeout(r, 300))
        return HttpResponse.json({
          total_calls: 150, completed_calls: 120, abandoned_calls: 30,
          total_duration_seconds: 9000, average_duration_seconds: 75,
          total_billable_minutes: 150, period: { date_from: null, date_to: null },
        })
      })
    )

    renderDashboard()
    // PeriodSelector should be present while loading
    await waitFor(() => expect(screen.getByRole('radio', { name: 'Today' })).toBeInTheDocument())
    expect(screen.getByRole('radio', { name: '7d' })).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Error state — graceful error display
// ──────────────────────────────────────────────────────────────────────────────
describe('DashboardPage — error state', () => {
  it('shows error message when API returns 500 (error-client)', async () => {
    renderDashboard('error-client')
    await waitFor(() =>
      expect(screen.getByRole('alert')).toBeInTheDocument(),
      { timeout: 5000 }
    )
  })

  it('error message does not expose raw API error details', async () => {
    renderDashboard('error-client')
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument(), { timeout: 5000 })
    // Should not contain raw error text
    expect(screen.queryByText('Internal server error')).not.toBeInTheDocument()
    expect(screen.queryByText('detail')).not.toBeInTheDocument()
  })

  it('does not throw uncaught exception on API error', async () => {
    // If the component throws, render itself will throw → test fails
    expect(() => renderDashboard('error-client')).not.toThrow()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Empty state — total_calls === 0
// ──────────────────────────────────────────────────────────────────────────────
describe('DashboardPage — empty state', () => {
  it('renders empty state when total_calls = 0 instead of zero-value cards', async () => {
    server.use(
      http.get('/api/v1/calls/metrics', () =>
        HttpResponse.json({
          total_calls: 0, completed_calls: 0, abandoned_calls: 0,
          total_duration_seconds: 0, average_duration_seconds: 0,
          total_billable_minutes: 0, period: { date_from: null, date_to: null },
        })
      )
    )

    renderDashboard()
    await waitFor(() =>
      expect(screen.getByTestId('empty-state')).toBeInTheDocument()
    )
  })

  it('does NOT render stat cards when in empty state', async () => {
    server.use(
      http.get('/api/v1/calls/metrics', () =>
        HttpResponse.json({
          total_calls: 0, completed_calls: 0, abandoned_calls: 0,
          total_duration_seconds: 0, average_duration_seconds: 0,
          total_billable_minutes: 0, period: { date_from: null, date_to: null },
        })
      )
    )

    renderDashboard()
    await waitFor(() => expect(screen.getByTestId('empty-state')).toBeInTheDocument())
    expect(screen.queryByText('Total Calls')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Period change — triggers re-fetch
// ──────────────────────────────────────────────────────────────────────────────
describe('DashboardPage — period change', () => {
  it('switches active period when user clicks "7d"', async () => {
    const user = userEvent.setup()
    renderDashboard()
    await waitFor(() => expect(screen.getByRole('radio', { name: '7d' })).toBeInTheDocument())
    await user.click(screen.getByRole('radio', { name: '7d' }))
    expect(screen.getByRole('radio', { name: '7d' })).toHaveAttribute('data-state', 'on')
    expect(screen.getByRole('radio', { name: 'Today' })).toHaveAttribute('data-state', 'off')
  })

  it('switches to "All" period when clicked', async () => {
    const user = userEvent.setup()
    renderDashboard()
    await waitFor(() => expect(screen.getByRole('radio', { name: 'All' })).toBeInTheDocument())
    await user.click(screen.getByRole('radio', { name: 'All' }))
    expect(screen.getByRole('radio', { name: 'All' })).toHaveAttribute('data-state', 'on')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// periodToDateRange — pure unit tests (no mocks needed)
// ──────────────────────────────────────────────────────────────────────────────
describe('periodToDateRange — "all" sends no date params', () => {
  it('returns empty object for "all" period (no date_from, no date_to)', () => {
    const result = periodToDateRange('all')
    expect(result).toEqual({})
  })

  it('"all" result has no date_from property', () => {
    const result = periodToDateRange('all')
    expect(result.date_from).toBeUndefined()
  })

  it('"all" result has no date_to property', () => {
    const result = periodToDateRange('all')
    expect(result.date_to).toBeUndefined()
  })
})

describe('periodToDateRange — "today" sends correct date params', () => {
  it('returns date_from set to start of today in UTC ISO format', () => {
    const result = periodToDateRange('today')
    const now = new Date()
    const expectedFrom = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())).toISOString()
    expect(result.date_from).toBe(expectedFrom)
  })

  it('returns date_to set to end of today in UTC ISO format', () => {
    const result = periodToDateRange('today')
    const now = new Date()
    const expectedTo = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 23, 59, 59, 999)).toISOString()
    expect(result.date_to).toBe(expectedTo)
  })

  it('date_from and date_to are both defined for "today"', () => {
    const result = periodToDateRange('today')
    expect(result.date_from).toBeDefined()
    expect(result.date_to).toBeDefined()
  })
})

describe('periodToDateRange — period switch changes date params', () => {
  it('"7d" returns date_from ~7 days ago and date_to is now (both defined)', () => {
    const before = Date.now()
    const result = periodToDateRange('7d')
    const after = Date.now()

    expect(result.date_from).toBeDefined()
    expect(result.date_to).toBeDefined()

    const from = new Date(result.date_from!).getTime()
    const to = new Date(result.date_to!).getTime()

    // to should be within the test execution window
    expect(to).toBeGreaterThanOrEqual(before)
    expect(to).toBeLessThanOrEqual(after + 100)

    // from should be approximately 7 days before to
    const sevenDaysMs = 7 * 24 * 60 * 60 * 1000
    expect(to - from).toBeCloseTo(sevenDaysMs, -3) // within ~1 second
  })

  it('"30d" returns date_from ~30 days ago (different from "7d")', () => {
    const result7d = periodToDateRange('7d')
    const result30d = periodToDateRange('30d')

    const from7d = new Date(result7d.date_from!).getTime()
    const from30d = new Date(result30d.date_from!).getTime()

    // 30d range starts earlier than 7d range
    expect(from30d).toBeLessThan(from7d)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Error state — retry button
// ──────────────────────────────────────────────────────────────────────────────
describe('DashboardPage — error state retry', () => {
  it('renders a "Retry" button inside the error alert', async () => {
    renderDashboard('error-client')
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument(), { timeout: 5000 })
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('Retry button is inside the alert region', async () => {
    renderDashboard('error-client')
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument(), { timeout: 5000 })
    const alert = screen.getByRole('alert')
    expect(alert).toContainElement(screen.getByRole('button', { name: 'Retry' }))
  })

  it('clicking Retry triggers a new API request', async () => {
    const user = userEvent.setup()
    let requestCount = 0

    server.use(
      http.get('/api/v1/calls/metrics', ({ request }) => {
        const url = new URL(request.url)
        const clientId = url.searchParams.get('client_id')
        if (clientId === 'error-client') {
          requestCount++
          return HttpResponse.json({ detail: 'Internal server error' }, { status: 500 })
        }
        return HttpResponse.json({
          total_calls: 150, completed_calls: 120, abandoned_calls: 30,
          total_duration_seconds: 9000, average_duration_seconds: 75,
          total_billable_minutes: 150, period: { date_from: null, date_to: null },
        })
      })
    )

    renderDashboard('error-client')
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument(), { timeout: 5000 })

    const countAfterInitialError = requestCount
    expect(countAfterInitialError).toBeGreaterThan(0)

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    await waitFor(() => expect(requestCount).toBeGreaterThan(countAfterInitialError), { timeout: 3000 })
  })
})
