/**
 * Analytics route tests (task 6.1 RED)
 *
 * Tests verify:
 * - /app/:clientId/analytics route exists in production router
 * - Route renders AnalyticsDashboardPage
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { routes } from '../../router'

const overviewFixture = {
  total_calls: 5,
  outcome_distribution: {},
  engagement_distribution: {},
  avg_call_duration_seconds: null,
  conversion_rate: null,
  period: 'month',
  start_date: '2026-03-29',
  end_date: '2026-04-28',
  agent_id: null,
}

beforeEach(() => {
  server.use(
    http.get('/api/v1/analytics/:clientId/overview', () =>
      HttpResponse.json(overviewFixture)
    ),
    http.get('/api/v1/analytics/:clientId/service-issues', () =>
      HttpResponse.json({ issues: [], period: 'month', start_date: '2026-03-29', end_date: '2026-04-28', agent_id: null })
    ),
    http.get('/api/v1/analytics/:clientId/interests', () =>
      HttpResponse.json({ interests: [], period: 'month', start_date: '2026-03-29', end_date: '2026-04-28', agent_id: null })
    ),
    http.get('/api/v1/analytics/:clientId/agent-stats', () =>
      HttpResponse.json({ agents: [], period: 'month', start_date: '2026-03-29', end_date: '2026-04-28' })
    ),
  )
})

function renderAt(initialEntry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const r = createMemoryRouter(routes, { initialEntries: [initialEntry] })
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={r} />
    </QueryClientProvider>
  )
}

describe('Analytics route', () => {
  it('/app/:clientId/analytics route exists in production router', () => {
    const appRoute = routes.find((r) => r.path === '/app/:clientId')
    const childPaths = appRoute?.children?.map((c) => c.path).filter(Boolean)
    expect(childPaths).toContain('analytics')
  })

  it('/app/demo-client/analytics renders AnalyticsDashboardPage with heading', async () => {
    renderAt('/app/demo-client/analytics')
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /analytics/i })).toBeInTheDocument(),
      { timeout: 5000 }
    )
  })
})
