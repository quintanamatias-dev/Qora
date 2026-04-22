/**
 * CAP-4: Router tests
 *
 * CRITICAL FIX: Tests now import and use the ACTUAL production routes from
 * src/router.tsx instead of a duplicated/mirrored routeConfig.
 *
 * Strategy: import `routes` from router.tsx and wrap with createMemoryRouter
 * in tests. This tests the real production route configuration, not a copy.
 * (Production router uses createBrowserRouter; tests use createMemoryRouter
 * with the same `routes` export — same config, different history strategy.)
 *
 * Tests for:
 * - Root `/` redirects to `/app/demo-client/dashboard`
 * - `/app/:clientId/dashboard` renders DashboardPage via AppLayout
 * - `/app/:clientId/leads` renders LeadsPage via AppLayout
 * - `/app/:clientId/leads/:leadId` renders LeadDetailPage via AppLayout
 * - Unknown path catch-all redirects to `/app/demo-client/dashboard`
 * - useClientId() returns correct clientId from URL params
 * - useClientId() throws outside :clientId route
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { routes } from './router'
import { useClientId } from './hooks/use-client-id'

// ──────────────────────────────────────────────────────────────────────────────
// Helper: render at a given path using the PRODUCTION route config
// DashboardPage now uses useMetrics (TanStack Query) so QueryClientProvider is required
// ──────────────────────────────────────────────────────────────────────────────
function renderAt(initialEntry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const r = createMemoryRouter(routes, { initialEntries: [initialEntry] })
  return render(<QueryClientProvider client={qc}><RouterProvider router={r} /></QueryClientProvider>)
}

// ──────────────────────────────────────────────────────────────────────────────
// REQ-4.1: Route structure — all routes from production router.tsx
// ──────────────────────────────────────────────────────────────────────────────
describe('REQ-4.1 Production route config — correct rendering', () => {
  it('root `/` redirects to /app/demo-client/dashboard and renders DashboardPage via AppLayout', () => {
    renderAt('/')
    // DashboardPage renders "Dashboard" as an h1
    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    // AppLayout renders clientId in multiple places (TopBar, Sidebar, page) — use getAllByText
    expect(screen.getAllByText('demo-client').length).toBeGreaterThanOrEqual(1)
  })

  it('/app/:clientId/dashboard renders DashboardPage with correct clientId via AppLayout', () => {
    renderAt('/app/acme-motors/dashboard')
    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    // AppLayout passes clientId to TopBar and Sidebar — text appears multiple times in the shell
    expect(screen.getAllByText('acme-motors').length).toBeGreaterThanOrEqual(1)
  })

  it('/app/:clientId/leads renders LeadsPage via AppLayout', () => {
    renderAt('/app/acme-motors/leads')
    expect(screen.getByRole('heading', { name: 'Leads' })).toBeInTheDocument()
    // clientId present in shell (TopBar + Sidebar + page content)
    expect(screen.getAllByText('acme-motors').length).toBeGreaterThanOrEqual(1)
  })

  it('/app/:clientId/leads/:leadId renders LeadDetailPage via AppLayout', () => {
    renderAt('/app/acme-motors/leads/lead-42')
    // LeadDetailPage now fetches lead data asynchronously.
    // On initial render (before data loads) it shows a loading skeleton.
    // The clientId is still present in the shell (Sidebar/TopBar).
    // We verify the route rendered the correct page by checking the loading state.
    expect(screen.getByTestId('lead-loading')).toBeInTheDocument()
    // clientId present in shell (TopBar + Sidebar)
    expect(screen.getAllByText('acme-motors').length).toBeGreaterThanOrEqual(1)
  })

  it('unknown path redirects to /app/demo-client/dashboard via catch-all', () => {
    renderAt('/totally-unknown')
    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    // clientId "demo-client" appears after redirect
    expect(screen.getAllByText('demo-client').length).toBeGreaterThanOrEqual(1)
  })

  it('production routes config has the correct number of top-level routes', () => {
    // Structural: routes must have 3 top-level entries (/, /app/:clientId, *)
    expect(routes).toHaveLength(3)
  })

  it('/app/:clientId children include dashboard, leads, leads/:leadId, and import', () => {
    const appRoute = routes.find((r) => r.path === '/app/:clientId')
    expect(appRoute).toBeDefined()
    const childPaths = appRoute!.children?.map((c) => c.path).filter(Boolean)
    expect(childPaths).toContain('dashboard')
    expect(childPaths).toContain('leads')
    expect(childPaths).toContain('leads/:leadId')
    expect(childPaths).toContain('import')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// REQ-4.1 clientId param propagation — useClientId hook
// ──────────────────────────────────────────────────────────────────────────────

function ClientIdDisplay() {
  const clientId = useClientId()
  return <span data-testid="client-id">{clientId}</span>
}

describe('useClientId hook', () => {
  it('returns correct clientId from URL params (acme-motors)', () => {
    render(
      <MemoryRouter initialEntries={['/app/acme-motors/dashboard']}>
        <Routes>
          <Route path="/app/:clientId/*" element={<ClientIdDisplay />} />
        </Routes>
      </MemoryRouter>
    )
    expect(screen.getByTestId('client-id')).toHaveTextContent('acme-motors')
  })

  it('returns correct clientId from URL params (demo-client)', () => {
    render(
      <MemoryRouter initialEntries={['/app/demo-client/dashboard']}>
        <Routes>
          <Route path="/app/:clientId/*" element={<ClientIdDisplay />} />
        </Routes>
      </MemoryRouter>
    )
    expect(screen.getByTestId('client-id')).toHaveTextContent('demo-client')
  })

  it('throws when used outside a :clientId route', () => {
    const originalError = console.error
    console.error = () => {}
    expect(() => {
      render(
        <MemoryRouter>
          <Routes>
            <Route path="/" element={<ClientIdDisplay />} />
          </Routes>
        </MemoryRouter>
      )
    }).toThrow('useClientId must be used inside a route with :clientId param')
    console.error = originalError
  })
})
