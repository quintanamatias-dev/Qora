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

  it('renders interest level when present', async () => {
    renderLeadsPage()
    // lead-1 has interest_level: 75
    await waitFor(() => expect(screen.getByText('75%')).toBeInTheDocument())
  })

  it('renders "—" for null interest level', async () => {
    renderLeadsPage()
    // lead-2 has interest_level: null
    await waitFor(() => {
      const dashes = screen.getAllByText('—')
      expect(dashes.length).toBeGreaterThan(0)
    })
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
