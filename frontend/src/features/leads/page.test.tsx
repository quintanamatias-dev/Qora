/**
 * LeadsPage — Integration tests (Spanish redesign — screens-leads.jsx `Leads`)
 *
 * Spec: sdd/qora-basic-crm/spec — Requirement: Lead Table Renders Correctly,
 *       Loading and Empty States
 */

import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider, Outlet } from 'react-router'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { LeadsPage } from './page'

function createTestClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  })
}

function renderLeadsPage(clientId = 'demo-client', initialEntry?: string) {
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
    { initialEntries: [initialEntry ?? `/app/${clientId}/leads`] }
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  return { qc, router }
}

describe('LeadsPage — renders heading', () => {
  it('renders the "Leads" heading', async () => {
    renderLeadsPage()
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Leads' })).toBeInTheDocument())
  })
})

describe('LeadsPage — successful data rendering', () => {
  it('renders lead names and phones from fixture', async () => {
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('John Doe')).toBeInTheDocument())
    expect(screen.getByText('Jane Smith')).toBeInTheDocument()
    expect(screen.getByText('+1-555-0100')).toBeInTheDocument()
  })

  it('renders call counts for leads', async () => {
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('2')).toBeInTheDocument())
  })

  it('renders the Spanish column headers', async () => {
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('John Doe')).toBeInTheDocument())
    expect(screen.getByRole('columnheader', { name: 'Lead' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Estado' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Llamadas' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Última llamada' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Datos para cotizar' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Próxima acción' })).toBeInTheDocument()
  })

  it('renders the real quote_fields n/N ratio (not a hardcoded /5)', async () => {
    // lead-1 fixture has 3 in_quote_ready_fields (car_model, car_make, zona), 1 filled
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('1/3')).toBeInTheDocument())
  })

  it('renders next action label for lead with no scheduled call and call_count > 0 (Sin agenda)', async () => {
    renderLeadsPage()
    await waitFor(() => {
      const labels = screen.getAllByText('Sin agenda')
      expect(labels.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders next action label for new lead (Pendiente)', async () => {
    server.use(
      http.get('/api/v1/leads', () =>
        HttpResponse.json([
          {
            id: 'lead-new',
            client_id: 'demo-client',
            name: 'Fresh Lead',
            phone: '+1-555-0300',
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

  it('renders next action label for closed lead (Cerrado)', async () => {
    server.use(
      http.get('/api/v1/leads', () =>
        HttpResponse.json([
          {
            id: 'lead-closed',
            client_id: 'demo-client',
            name: 'Closed Lead',
            phone: '+1-555-0400',
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
            next_scheduled_call_at: '2099-12-31T10:00:00Z',
          },
        ])
      )
    )
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('Cerrado')).toBeInTheDocument())
    // do_not_call must also disable the real call trigger — "No llamar" tag shown instead of a button
    expect(screen.getByText('No llamar')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Llamar$/i })).not.toBeInTheDocument()
  })

  it('renders next action label for overdue scheduled call (Atrasado)', async () => {
    const pastDate = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString()
    server.use(
      http.get('/api/v1/leads', () =>
        HttpResponse.json([
          {
            id: 'lead-overdue',
            client_id: 'demo-client',
            name: 'Overdue Lead',
            phone: '+1-555-0600',
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

describe('LeadsPage — search (accent-insensitive) and ?q= from URL', () => {
  it('reads the initial ?q= param from the URL (TopBar search hands off here)', async () => {
    renderLeadsPage('demo-client', '/app/demo-client/leads?q=jane')
    await waitFor(() => expect(screen.getByText('Jane Smith')).toBeInTheDocument())
    expect(screen.queryByText('John Doe')).not.toBeInTheDocument()
  })

  it('filters by name accent-insensitively', async () => {
    const user = userEvent.setup()
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('John Doe')).toBeInTheDocument())
    await user.type(screen.getByPlaceholderText('Buscar por nombre o teléfono'), 'jóhn')
    await waitFor(() => expect(screen.queryByText('Jane Smith')).not.toBeInTheDocument())
    expect(screen.getByText('John Doe')).toBeInTheDocument()
  })
})

describe('LeadsPage — status filter (Seg) with real counts', () => {
  it('shows Todos / Nuevos / Seguimiento counts', async () => {
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText(/Todos ·/)).toBeInTheDocument())
    expect(screen.getByText(/Nuevos ·/)).toBeInTheDocument()
    expect(screen.getByText(/Seguimiento ·/)).toBeInTheDocument()
  })

  it('filtering by Nuevos hides non-new leads', async () => {
    const user = userEvent.setup()
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('John Doe')).toBeInTheDocument())
    await user.click(screen.getByText(/^Nuevos ·/))
    await waitFor(() => expect(screen.queryByText('Jane Smith')).not.toBeInTheDocument())
    expect(screen.getByText('John Doe')).toBeInTheDocument()
  })
})

describe('LeadsPage — loading state', () => {
  it('shows loading state while data is fetching', async () => {
    server.use(
      http.get('/api/v1/leads', async () => {
        await new Promise((r) => setTimeout(r, 200))
        return HttpResponse.json([])
      })
    )

    renderLeadsPage()
    expect(screen.getByTestId('leads-loading')).toBeInTheDocument()
  })
})

describe('LeadsPage — empty state', () => {
  it('shows an empty message when no leads returned', async () => {
    server.use(http.get('/api/v1/leads', () => HttpResponse.json([])))

    renderLeadsPage()
    await waitFor(() => expect(screen.getByTestId('leads-empty')).toBeInTheDocument())
  })
})

describe('LeadsPage — error state', () => {
  it('shows an error message when API returns 500', async () => {
    server.use(http.get('/api/v1/leads', () => HttpResponse.json({ detail: 'Server error' }, { status: 500 })))

    renderLeadsPage()
    await waitFor(() => expect(screen.getByTestId('leads-error')).toBeInTheDocument(), { timeout: 5000 })
  })
})

describe('LeadsPage — row click navigation', () => {
  it('clicking a lead row navigates to lead detail page', async () => {
    const user = userEvent.setup()
    renderLeadsPage()

    await waitFor(() => expect(screen.getByText('John Doe')).toBeInTheDocument())

    const rows = screen.getAllByRole('row')
    await user.click(rows[1])

    await waitFor(() => expect(screen.getByTestId('lead-detail-page')).toBeInTheDocument())
  })

  it('clicking "Llamar" does not navigate to lead detail', async () => {
    const user = userEvent.setup()
    renderLeadsPage()
    await waitFor(() => expect(screen.getByText('John Doe')).toBeInTheDocument())

    const callButtons = screen.getAllByRole('button', { name: /^Llamar$/i })
    await user.click(callButtons[0])

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.queryByTestId('lead-detail-page')).not.toBeInTheDocument()
  })
})
