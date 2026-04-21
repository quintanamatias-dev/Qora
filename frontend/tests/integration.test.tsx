/**
 * CAP-6: MSW-based integration tests
 *
 * REQ-6.2: MSW handlers intercept API calls in tests
 * REQ-6.3: Component smoke tests (confirmed still work)
 * REQ-6.4: Route rendering test
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider, MemoryRouter, Routes, Route, Outlet } from 'react-router'
import { useMetrics, useLeads } from '../src/api/hooks'
import { DashboardPage } from '../src/features/dashboard/page'
import { LeadsPage } from '../src/features/leads/page'
import { Sidebar } from '../src/design/components'

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function createTestClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

// ──────────────────────────────────────────────────────────────────────────────
// REQ-6.4: Route rendering test
// ──────────────────────────────────────────────────────────────────────────────
describe('REQ-6.4 Route rendering', () => {
  it('navigating to /app/demo-client/dashboard renders DashboardPage placeholder', () => {
    const r = createMemoryRouter(
      [
        {
          path: '/app/:clientId',
          element: <Outlet />,
          children: [{ path: 'dashboard', element: <DashboardPage /> }],
        },
      ],
      { initialEntries: ['/app/demo-client/dashboard'] }
    )
    render(<RouterProvider router={r} />)

    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByText('demo-client')).toBeInTheDocument()
  })

  it('navigating to /app/test-client/dashboard renders DashboardPage with test-client', () => {
    const r = createMemoryRouter(
      [
        {
          path: '/app/:clientId',
          element: <Outlet />,
          children: [{ path: 'dashboard', element: <DashboardPage /> }],
        },
      ],
      { initialEntries: ['/app/test-client/dashboard'] }
    )
    render(<RouterProvider router={r} />)
    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByText('test-client')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// REQ-6.2: MSW intercepts API calls
// Hook integration test — useMetrics returns MSW-mocked data
// ──────────────────────────────────────────────────────────────────────────────
describe('REQ-6.2 MSW API interception', () => {
  it('useMetrics returns mocked data from MSW handler (total_calls: 150)', async () => {
    function MetricsComp() {
      const { data, isLoading, isError } = useMetrics('demo-client')
      if (isLoading) return <span>loading</span>
      if (isError) return <span>error</span>
      return (
        <div>
          <span data-testid="total-calls">{data?.total_calls}</span>
          <span data-testid="completed-calls">{data?.completed_calls}</span>
        </div>
      )
    }

    const qc = createTestClient()
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/app/demo-client/dashboard']}>
          <Routes>
            <Route path="/app/:clientId/*" element={<MetricsComp />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    )

    expect(screen.getByText('loading')).toBeInTheDocument()
    // MSW handler returns { total_calls: 150, completed_calls: 120 }
    await waitFor(() => expect(screen.getByTestId('total-calls')).toHaveTextContent('150'))
    expect(screen.getByTestId('completed-calls')).toHaveTextContent('120')
  })

  it('useLeads returns MSW-mocked lead list for /api/v1/leads (component-triggered fetch)', async () => {
    function LeadsComp() {
      const { data, isLoading, isError } = useLeads('demo-client')
      if (isLoading) return <span>loading</span>
      if (isError) return <span>error</span>
      return (
        <ul>
          {data?.map((lead) => (
            <li key={lead.id} data-testid="lead-item">{lead.name}</li>
          ))}
        </ul>
      )
    }

    const qc = createTestClient()
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/app/demo-client/leads']}>
          <Routes>
            <Route path="/app/:clientId/*" element={<LeadsComp />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    )

    expect(screen.getByText('loading')).toBeInTheDocument()
    // MSW handler for /api/v1/leads returns 2 leads: John Doe, Jane Smith
    await waitFor(() => expect(screen.getAllByTestId('lead-item')).toHaveLength(2))
    expect(screen.getByText('John Doe')).toBeInTheDocument()
    expect(screen.getByText('Jane Smith')).toBeInTheDocument()
  })

  it('useMetrics shows error state when MSW handler returns 500 (error-client)', async () => {
    function MetricsComp() {
      const { data, isLoading, isError } = useMetrics('error-client')
      if (isLoading) return <span>loading</span>
      if (isError) return <span data-testid="error-state">error</span>
      return <span data-testid="data">{data?.total_calls}</span>
    }

    const qc = createTestClient()
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/app/error-client/dashboard']}>
          <Routes>
            <Route path="/app/:clientId/*" element={<MetricsComp />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    )

    // MSW handler returns 500 for 'error-client' → ApiError → isError = true
    await waitFor(
      () => expect(screen.getByTestId('error-state')).toBeInTheDocument(),
      { timeout: 3000 }
    )
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// REQ-6.3: App shell smoke tests — sidebar navigation visible
// ──────────────────────────────────────────────────────────────────────────────
describe('REQ-6.3 App shell smoke tests', () => {
  it('Sidebar renders navigation with Dashboard, Leads, and Import links', () => {
    render(
      <MemoryRouter initialEntries={['/app/demo-client/dashboard']}>
        <Sidebar clientId="demo-client" />
      </MemoryRouter>
    )

    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(nav).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Leads' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Import' })).toBeInTheDocument()
  })

  it('LeadsPage renders heading without crashing', () => {
    render(
      <MemoryRouter initialEntries={['/app/demo-client/leads']}>
        <Routes>
          <Route path="/app/:clientId/*" element={<LeadsPage />} />
        </Routes>
      </MemoryRouter>
    )
    expect(screen.getByRole('heading', { name: 'Leads' })).toBeInTheDocument()
  })

  it('DashboardPage renders heading with client context', () => {
    const r = createMemoryRouter(
      [
        {
          path: '/app/:clientId',
          element: <Outlet />,
          children: [{ path: 'dashboard', element: <DashboardPage /> }],
        },
      ],
      { initialEntries: ['/app/demo-client/dashboard'] }
    )
    render(<RouterProvider router={r} />)
    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
  })
})
