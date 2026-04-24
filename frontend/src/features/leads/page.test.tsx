/**
 * LeadsPage — Integration tests
 *
 * Spec: sdd/qora-basic-crm/spec — Requirement: Lead Table Renders Correctly,
 *       Loading and Empty States
 * Design: Container-presentational, mirrors DashboardPage pattern.
 *
 * TDD Layer: Integration (RTL + MSW)
 * TDD: RED phase — tests written before implementation
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider, Outlet } from 'react-router'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { LeadsPage } from './page'

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function createTestClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  })
}

function renderLeadsPage(clientId = 'demo-client') {
  const qc = createTestClient()
  const router = createMemoryRouter(
    [
      {
        path: '/app/:clientId',
        element: <Outlet />,
        children: [
          { path: 'leads', element: <LeadsPage /> },
          { path: 'leads/:leadId', element: <div data-testid="lead-detail-page">Lead Detail</div> },
        ],
      },
    ],
    { initialEntries: [`/app/${clientId}/leads`] }
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  return { qc, router }
}

// ──────────────────────────────────────────────────────────────────────────────
// Renders heading
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadsPage — renders heading', () => {
  it('renders the "Leads" heading', async () => {
    renderLeadsPage()
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Leads' })).toBeInTheDocument()
    )
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Successful data load — table shows leads
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadsPage — successful data rendering', () => {
  it('renders lead names from fixture', async () => {
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('John Doe')).toBeInTheDocument())
    expect(screen.getByText('Jane Smith')).toBeInTheDocument()
  })

  it('renders lead phone numbers', async () => {
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('+1-555-0100')).toBeInTheDocument())
  })

  it('renders status badges for leads', async () => {
    renderLeadsPage()
    await waitFor(() => {
      // "new" and "interested" statuses from fixture
      const badges = screen.getAllByRole('cell')
      expect(badges.length).toBeGreaterThan(0)
    })
  })

  it('renders call count for leads', async () => {
    renderLeadsPage()
    // lead-1 has call_count: 2
    await waitFor(() => expect(screen.getByText('2')).toBeInTheDocument())
  })

  it('renders "Next Action" column header', async () => {
    renderLeadsPage()
    await waitFor(() =>
      expect(screen.getByText('Next Action')).toBeInTheDocument()
    )
  })

  it('does NOT render "Interest" column header', async () => {
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('John Doe')).toBeInTheDocument())
    expect(screen.queryByText('Interest')).not.toBeInTheDocument()
  })

  it('renders next action badge for lead with no scheduled call and call_count > 0 (Sin agenda)', async () => {
    renderLeadsPage()
    // Both leads have call_count > 0 and next_scheduled_call_at: null → both show Sin agenda
    await waitFor(() => {
      const badges = screen.getAllByText('Sin agenda')
      expect(badges.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders next action badge for new lead (Pendiente)', async () => {
    // Override fixture: lead with call_count 0, next_scheduled_call_at null, status new
    const { http, HttpResponse } = await import('msw')
    server.use(
      http.get('/api/v1/leads', () =>
        HttpResponse.json([
          {
            id: 'lead-new',
            client_id: 'demo-client',
            name: 'Fresh Lead',
            phone: '+1-555-0300',
            car_make: null,
            car_model: null,
            car_year: null,
            current_insurance: null,
            status: 'new',
            notes: null,
            call_count: 0,
            last_called_at: null,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: null,
            summary_last_call: null,
            objections_heard: null,
            interest_level: null,
            extracted_facts: null,
            do_not_call: false,
            next_action: null,
            next_action_at: null,
            next_scheduled_call_at: null,
          },
        ])
      )
    )
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('Pendiente')).toBeInTheDocument())
  })

  it('renders next action badge for closed lead (Cerrado)', async () => {
    // TRIANGULATE: do_not_call=true → Cerrado / error
    const { http, HttpResponse } = await import('msw')
    server.use(
      http.get('/api/v1/leads', () =>
        HttpResponse.json([
          {
            id: 'lead-closed',
            client_id: 'demo-client',
            name: 'Closed Lead',
            phone: '+1-555-0400',
            car_make: null,
            car_model: null,
            car_year: null,
            current_insurance: null,
            status: 'not_interested',
            notes: null,
            call_count: 3,
            last_called_at: '2026-01-15T10:00:00Z',
            created_at: '2026-01-01T00:00:00Z',
            updated_at: null,
            summary_last_call: null,
            objections_heard: null,
            interest_level: null,
            extracted_facts: null,
            do_not_call: true,
            next_action: null,
            next_action_at: null,
            next_scheduled_call_at: '2099-12-31T10:00:00Z', // future, but closed takes priority
          },
        ])
      )
    )
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('Cerrado')).toBeInTheDocument())
  })

  it('renders next action badge for lead with future scheduled call (active badge)', async () => {
    // TRIANGULATE: next_scheduled_call_at in future → active badge with relative time
    const { http, HttpResponse } = await import('msw')
    const futureDate = new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString() // 2h from now
    server.use(
      http.get('/api/v1/leads', () =>
        HttpResponse.json([
          {
            id: 'lead-scheduled',
            client_id: 'demo-client',
            name: 'Scheduled Lead',
            phone: '+1-555-0500',
            car_make: null,
            car_model: null,
            car_year: null,
            current_insurance: null,
            status: 'interested',
            notes: null,
            call_count: 1,
            last_called_at: '2026-01-10T10:00:00Z',
            created_at: '2026-01-01T00:00:00Z',
            updated_at: null,
            summary_last_call: null,
            objections_heard: null,
            interest_level: 60,
            extracted_facts: null,
            do_not_call: false,
            next_action: null,
            next_action_at: null,
            next_scheduled_call_at: futureDate,
          },
        ])
      )
    )
    renderLeadsPage()
    // Active state shows relative time label — "En Xh" for 2h from now
    await waitFor(() => {
      const labels = screen.getAllByText(/^En \d+h$/)
      expect(labels.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders next action badge for overdue scheduled call (Atrasado)', async () => {
    // TRIANGULATE: next_scheduled_call_at in the past → Atrasado / warning
    const { http, HttpResponse } = await import('msw')
    const pastDate = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString() // 3h ago
    server.use(
      http.get('/api/v1/leads', () =>
        HttpResponse.json([
          {
            id: 'lead-overdue',
            client_id: 'demo-client',
            name: 'Overdue Lead',
            phone: '+1-555-0600',
            car_make: null,
            car_model: null,
            car_year: null,
            current_insurance: null,
            status: 'interested',
            notes: null,
            call_count: 1,
            last_called_at: '2026-01-10T10:00:00Z',
            created_at: '2026-01-01T00:00:00Z',
            updated_at: null,
            summary_last_call: null,
            objections_heard: null,
            interest_level: 40,
            extracted_facts: null,
            do_not_call: false,
            next_action: null,
            next_action_at: null,
            next_scheduled_call_at: pastDate,
          },
        ])
      )
    )
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('Atrasado')).toBeInTheDocument())
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Loading state
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadsPage — loading state', () => {
  it('shows loading skeleton while data is fetching', async () => {
    server.use(
      http.get('/api/v1/leads', async () => {
        await new Promise(r => setTimeout(r, 200))
        return HttpResponse.json([])
      })
    )

    renderLeadsPage()
    expect(screen.getByTestId('leads-loading')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Empty state
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadsPage — empty state', () => {
  it('shows "No leads found" when no leads returned', async () => {
    server.use(
      http.get('/api/v1/leads', () => HttpResponse.json([]))
    )

    renderLeadsPage()
    await waitFor(() =>
      expect(screen.getByTestId('leads-empty')).toBeInTheDocument()
    )
    expect(screen.getByText('No leads found')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Error state
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadsPage — error state', () => {
  it('shows error message when API returns 500', async () => {
    server.use(
      http.get('/api/v1/leads', () =>
        HttpResponse.json({ detail: 'Server error' }, { status: 500 })
      )
    )

    renderLeadsPage()
    await waitFor(() =>
      expect(screen.getByTestId('leads-error')).toBeInTheDocument(),
      { timeout: 5000 }
    )
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Row click navigation
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadsPage — row click navigation', () => {
  it('clicking a lead row navigates to lead detail page', async () => {
    const user = userEvent.setup()
    renderLeadsPage()

    await waitFor(() => expect(screen.getByText('John Doe')).toBeInTheDocument())

    // Click the first data row (rows[0] = header, rows[1] = first lead)
    const rows = screen.getAllByRole('row')
    await user.click(rows[1])

    // After click, the router should navigate to the lead detail page.
    // The test router defines leads/:leadId → <div data-testid="lead-detail-page">.
    // If navigation happened, the LeadsPage unmounts and the detail page renders.
    await waitFor(() =>
      expect(screen.getByTestId('lead-detail-page')).toBeInTheDocument()
    )
  })
})
