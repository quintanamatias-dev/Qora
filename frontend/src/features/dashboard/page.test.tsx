/**
 * DashboardPage — "Resumen" — Integration tests
 *
 * Design: qora-presentacion/project/dashboard/screens-overview.jsx (Overview)
 * TDD Layer: Integration (RTL + MSW via global server setup)
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
        children: [
          { path: 'dashboard', element: <DashboardPage /> },
          { path: 'leads', element: <div>Leads List</div> },
          { path: 'leads/:leadId', element: <div>Lead Detail</div> },
          { path: 'import', element: <div>Import</div> },
        ],
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
  it('renders the "Resumen" heading', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Resumen' })).toBeInTheDocument())
  })
})

describe('DashboardPage — default period is "Todo"', () => {
  it('"Todo" option is active on first render', async () => {
    renderDashboard()
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: 'Todo' })).toHaveAttribute('aria-checked', 'true')
    )
  })

  it('renders all 4 period options in Spanish', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByRole('radio', { name: 'Todo' })).toBeInTheDocument())
    expect(screen.getByRole('radio', { name: 'Hoy' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '7 días' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '30 días' })).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Successful data rendering
// ──────────────────────────────────────────────────────────────────────────────
describe('DashboardPage — successful data rendering', () => {
  it('renders "Llamadas" KPI with total_calls value "150" from MSW fixture', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByText('Llamadas')).toBeInTheDocument())
    expect(screen.getByText('150')).toBeInTheDocument()
  })

  it('renders "Completadas" KPI with value "120"', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByText('120')).toBeInTheDocument())
    expect(screen.getAllByText('Completadas').length).toBeGreaterThan(0)
  })

  it('renders the "Volumen de llamadas" chart card', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByText('Volumen de llamadas')).toBeInTheDocument())
  })

  it('renders the "Actividad reciente" card with recent calls from MSW fixture', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByText('Actividad reciente')).toBeInTheDocument())
    const rows = await screen.findAllByText('John Doe')
    expect(rows.length).toBeGreaterThan(0)
  })

  it('renders the "Agentes" right-rail card', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByText('Agentes')).toBeInTheDocument())
  })

  it('renders the "Consumo" right-rail card', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByText('Consumo')).toBeInTheDocument())
  })

  it('renders the "Integraciones" right-rail card', async () => {
    renderDashboard()
    await waitFor(() => expect(screen.getByText('Integraciones')).toBeInTheDocument())
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Loading state — skeletons during fetch
// ──────────────────────────────────────────────────────────────────────────────
describe('DashboardPage — loading state', () => {
  it('renders KPI skeletons while metrics are loading', async () => {
    server.use(
      http.get('/api/v1/calls/metrics', async () => {
        await new Promise((r) => setTimeout(r, 200))
        return HttpResponse.json({
          total_calls: 150, completed_calls: 120, abandoned_calls: 30,
          total_duration_seconds: 9000, average_duration_seconds: 75,
          total_billable_minutes: 150, period: { date_from: null, date_to: null },
        })
      })
    )

    renderDashboard()
    const skeletons = await waitFor(() => screen.getAllByTestId('kpi-skeleton'))
    expect(skeletons).toHaveLength(4)
  })

  it('period Seg remains interactive during loading', async () => {
    server.use(
      http.get('/api/v1/calls/metrics', async () => {
        await new Promise((r) => setTimeout(r, 300))
        return HttpResponse.json({
          total_calls: 150, completed_calls: 120, abandoned_calls: 30,
          total_duration_seconds: 9000, average_duration_seconds: 75,
          total_billable_minutes: 150, period: { date_from: null, date_to: null },
        })
      })
    )

    renderDashboard()
    await waitFor(() => expect(screen.getByRole('radio', { name: 'Hoy' })).toBeInTheDocument())
    expect(screen.getByRole('radio', { name: '7 días' })).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Error state
// ──────────────────────────────────────────────────────────────────────────────
describe('DashboardPage — error state', () => {
  it('shows error alert when the metrics API returns 500 (error-client)', async () => {
    renderDashboard('error-client')
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument(), { timeout: 5000 })
  })

  it('error message does not expose raw API error details', async () => {
    renderDashboard('error-client')
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument(), { timeout: 5000 })
    expect(screen.queryByText('Internal server error')).not.toBeInTheDocument()
    expect(screen.queryByText('detail')).not.toBeInTheDocument()
  })

  it('does not throw an uncaught exception on API error', async () => {
    expect(() => renderDashboard('error-client')).not.toThrow()
  })

  it('renders a "Reintentar" button inside the error alert', async () => {
    renderDashboard('error-client')
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument(), { timeout: 5000 })
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeInTheDocument()
  })

  it('clicking Reintentar triggers a new API request', async () => {
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

    await user.click(screen.getByRole('button', { name: 'Reintentar' }))

    await waitFor(() => expect(requestCount).toBeGreaterThan(countAfterInitialError), { timeout: 3000 })
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Empty state — total_calls === 0
// ──────────────────────────────────────────────────────────────────────────────
describe('DashboardPage — empty state', () => {
  it('renders empty state when total_calls = 0 instead of KPI cards', async () => {
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
    expect(screen.queryByText('Llamadas')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Period change — triggers re-fetch
// ──────────────────────────────────────────────────────────────────────────────
describe('DashboardPage — period change', () => {
  it('switches active period when user clicks "7 días"', async () => {
    const user = userEvent.setup()
    renderDashboard()
    await waitFor(() => expect(screen.getByRole('radio', { name: '7 días' })).toBeInTheDocument())
    await user.click(screen.getByRole('radio', { name: '7 días' }))
    expect(screen.getByRole('radio', { name: '7 días' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: 'Hoy' })).toHaveAttribute('aria-checked', 'false')
  })

  it('switches to "Todo" period when clicked', async () => {
    const user = userEvent.setup()
    renderDashboard()
    await waitFor(() => expect(screen.getByRole('radio', { name: 'Hoy' })).toBeInTheDocument())
    await user.click(screen.getByRole('radio', { name: 'Hoy' }))
    await user.click(screen.getByRole('radio', { name: 'Todo' }))
    expect(screen.getByRole('radio', { name: 'Todo' })).toHaveAttribute('aria-checked', 'true')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Recent activity — navigation
// ──────────────────────────────────────────────────────────────────────────────
describe('DashboardPage — recent activity navigation', () => {
  it('clicking a recent call row navigates to the lead detail route', async () => {
    const user = userEvent.setup()
    renderDashboard()
    const rows = await screen.findAllByText('John Doe')
    await user.click(rows[0])
    await waitFor(() => expect(screen.getByText('Lead Detail')).toBeInTheDocument())
  })

  it('clicking "Ver leads" navigates to the leads list route', async () => {
    const user = userEvent.setup()
    renderDashboard()
    await waitFor(() => expect(screen.getByText('Actividad reciente')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Ver leads/ }))
    await waitFor(() => expect(screen.getByText('Leads List')).toBeInTheDocument())
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
  const NOW = new Date('2026-06-15T18:00:00.000Z')

  it('returns date_from set to start of today in the given timezone', () => {
    const result = periodToDateRange('today', 'America/Argentina/Buenos_Aires', NOW)
    expect(result.date_from).toBe('2026-06-15T03:00:00.000Z')
  })

  it('returns date_to set to end of today in the given timezone', () => {
    const result = periodToDateRange('today', 'America/Argentina/Buenos_Aires', NOW)
    expect(result.date_to).toBe('2026-06-16T02:59:59.999Z')
  })

  it('date_from and date_to are both defined for "today"', () => {
    const result = periodToDateRange('today', 'America/Argentina/Buenos_Aires', NOW)
    expect(result.date_from).toBeDefined()
    expect(result.date_to).toBeDefined()
  })

  it('shifts the range when the timezone changes (Europe/Madrid)', () => {
    const result = periodToDateRange('today', 'Europe/Madrid', NOW)
    expect(result.date_from).toBe('2026-06-14T22:00:00.000Z')
  })

  it('defaults to Buenos Aires when no timezone is passed', () => {
    const result = periodToDateRange('today', undefined, NOW)
    expect(result.date_from).toBe('2026-06-15T03:00:00.000Z')
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

    expect(to).toBeGreaterThanOrEqual(before)
    expect(to).toBeLessThanOrEqual(after + 100)

    const sevenDaysMs = 7 * 24 * 60 * 60 * 1000
    expect(to - from).toBeCloseTo(sevenDaysMs, -3)
  })

  it('"30d" returns date_from ~30 days ago (different from "7d")', () => {
    const result7d = periodToDateRange('7d')
    const result30d = periodToDateRange('30d')

    const from7d = new Date(result7d.date_from!).getTime()
    const from30d = new Date(result30d.date_from!).getTime()

    expect(from30d).toBeLessThan(from7d)
  })
})
