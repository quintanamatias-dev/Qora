/**
 * LeadDetailPage — Integration tests (Spanish redesign — screens-lead.jsx `Lead`)
 *
 * Covers: header, KPI strip, tabs (Memoria/Cotización/Registro/CRM/Próxima
 * llamada), zona mismatch warning, profile facts, dimension rollups states,
 * call history rail + CallDrawer, context preview lazy-load, loading/error.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider, Outlet } from 'react-router'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { LeadDetailPage } from './detail-page'

function createTestClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } } })
}

function renderDetailPage(clientId = 'demo-client', leadId = 'lead-1') {
  const qc = createTestClient()
  const router = createMemoryRouter(
    [
      {
        path: '/app/:clientId',
        element: <Outlet />,
        children: [
          { path: 'leads', element: <div>Leads List</div> },
          { path: 'leads/:leadId', element: <LeadDetailPage /> },
          { path: 'calls/:sessionId', element: <div>Call Detail Page</div> },
        ],
      },
    ],
    { initialEntries: [`/app/${clientId}/leads/${leadId}`] }
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  return { qc }
}

async function switchTab(name: string) {
  const matcher = new RegExp(`^${name}`)
  await screen.findByRole('button', { name: matcher })
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: matcher }))
  return user
}

// ──────────────────────────────────────────────────────────────────────────────
// Header
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — header', () => {
  it('renders lead name in page heading', async () => {
    renderDetailPage()
    await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: /John Doe/i })).toBeInTheDocument())
  })

  it('renders lead phone in header', async () => {
    renderDetailPage()
    await waitFor(() => expect(screen.getAllByText('+1-555-0100').length).toBeGreaterThanOrEqual(1))
  })

  it('renders "Se puede llamar" when do_not_call is false', async () => {
    renderDetailPage()
    await waitFor(() => expect(screen.getByText('Se puede llamar')).toBeInTheDocument())
  })

  it('renders "Copiar link" and "Llamar ahora" actions', async () => {
    renderDetailPage()
    await waitFor(() => expect(screen.getByRole('button', { name: /copiar link/i })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /llamar ahora/i })).toBeInTheDocument()
  })

  it('copies the current URL to the clipboard on "Copiar link"', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, writable: true, configurable: true })

    renderDetailPage()
    await screen.findByRole('button', { name: /copiar link/i })
    await user.click(screen.getByRole('button', { name: /copiar link/i }))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(window.location.href))
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// KPI strip
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — KPI strip', () => {
  it('shows interest level', async () => {
    renderDetailPage()
    await waitFor(() => expect(screen.getByText('75%')).toBeInTheDocument())
  })

  it('shows the real quote-ready fields ratio (1/3 for lead-1)', async () => {
    renderDetailPage()
    await waitFor(() => expect(screen.getByText('1')).toBeInTheDocument())
    expect(screen.getByText('/ 3')).toBeInTheDocument()
  })

  it('shows call count', async () => {
    renderDetailPage()
    await waitFor(() => expect(screen.getAllByText('2').length).toBeGreaterThanOrEqual(1))
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Tabs — Cotización (Quote readiness fields, real data, read-only)
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — Cotización tab', () => {
  it('shows quote-ready fields and CRM-provided fields separately', async () => {
    renderDetailPage()
    await switchTab('Cotización')
    await waitFor(() => expect(screen.getByText('Car Make')).toBeInTheDocument())
    expect(screen.getByText('Car Model')).toBeInTheDocument()
    expect(screen.getByText('Current Insurance')).toBeInTheDocument()
    expect(screen.getByText('Del CRM · solo contexto, el agente no lo pregunta')).toBeInTheDocument()
  })

  it('marks quote-ready fields with "Obligatorio" and CRM-provided with "Del CRM"', async () => {
    renderDetailPage()
    await switchTab('Cotización')
    await waitFor(() => expect(screen.getAllByText('Obligatorio').length).toBeGreaterThanOrEqual(1))
    expect(screen.getByText('Del CRM')).toBeInTheDocument()
  })

  it('shows filled values and "Sin completar" for missing ones', async () => {
    renderDetailPage()
    await switchTab('Cotización')
    await waitFor(() => expect(screen.getByText('Toyota')).toBeInTheDocument())
    expect(screen.getByText('State Farm')).toBeInTheDocument()
    expect(screen.getAllByText('Sin completar').length).toBeGreaterThanOrEqual(2)
  })

  it('does not render a "Guardar" (save) affordance — read-only, no write endpoint', async () => {
    renderDetailPage()
    await switchTab('Cotización')
    await waitFor(() => expect(screen.getByText('Car Make')).toBeInTheDocument())
    expect(screen.queryByText(/guardar/i)).not.toBeInTheDocument()
  })

  it('forwards data-testid to the section root', async () => {
    renderDetailPage()
    await switchTab('Cotización')
    await waitFor(() => expect(document.querySelector('[data-testid="quote-readiness-section"]')).toBeInTheDocument())
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Tabs — Registro
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — Registro tab', () => {
  it('renders base stored fields', async () => {
    renderDetailPage()
    await switchTab('Registro')
    await waitFor(() => expect(screen.getByText('Teléfono')).toBeInTheDocument())
    expect(screen.getByText('john@example.com')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Tabs — CRM
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — CRM tab', () => {
  it('shows external IDs when present', async () => {
    renderDetailPage()
    await switchTab('CRM')
    await waitFor(() => expect(screen.getByText('recABC123')).toBeInTheDocument())
    expect(screen.getByText('1001')).toBeInTheDocument()
  })

  it('shows an honest empty state for a client with no integration', async () => {
    renderDetailPage('no-zona-client', 'lead-3')
    await switchTab('CRM')
    await waitFor(() => expect(screen.getByText('No hay integración CRM configurada para este cliente.')).toBeInTheDocument())
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Tabs — Memoria (profile facts, zona mismatch, rollups)
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — Memoria tab', () => {
  it('shows profile fact items', async () => {
    renderDetailPage()
    await waitFor(() => expect(screen.getAllByTestId('profile-fact-item').length).toBeGreaterThanOrEqual(1))
  })

  it('shows the zona mismatch warning for lead-1', async () => {
    renderDetailPage()
    await waitFor(() => expect(document.querySelector('[data-testid="zona-mismatch-warning"]')).toBeInTheDocument())
  })

  it('does not show the mismatch warning when the client has no zona field configured (lead-3)', async () => {
    renderDetailPage('no-zona-client', 'lead-3')
    await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: /No Zona Client/i })).toBeInTheDocument())
    expect(document.querySelector('[data-testid="zona-mismatch-warning"]')).not.toBeInTheDocument()
  })

  it('surfaces a rollups error instead of empty rankings when /dimension-rollups fails', async () => {
    server.use(http.get('/api/v1/leads/:leadId/dimension-rollups', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })))
    renderDetailPage()
    await waitFor(() => expect(screen.getByTestId('rollups-error')).toBeInTheDocument(), { timeout: 5000 })
  })

  it('shows empty-state rankings when rollups load successfully but are empty (lead-2)', async () => {
    renderDetailPage('demo-client', 'lead-2')
    await waitFor(() => expect(screen.getByText('No detected interests across calls yet.')).toBeInTheDocument())
    expect(screen.getByText('No service issues recorded across calls yet.')).toBeInTheDocument()
    expect(screen.queryByTestId('rollups-error')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Tabs — Próxima llamada (context preview, lazy load)
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — Próxima llamada tab', () => {
  it('does not fetch the preview until the load button is clicked', async () => {
    renderDetailPage()
    await switchTab('Próxima llamada')
    expect(screen.getByRole('button', { name: /cargar vista previa/i })).toBeInTheDocument()
    expect(screen.queryByText('Lead Profile')).not.toBeInTheDocument()
  })

  it('loads and renders literal context blocks after clicking the trigger', async () => {
    renderDetailPage()
    const user = await switchTab('Próxima llamada')
    await user.click(screen.getByRole('button', { name: /cargar vista previa/i }))

    await waitFor(() => expect(screen.getByText(/present, not shown/i)).toBeInTheDocument())
    expect(screen.getByText('Lead Profile')).toBeInTheDocument()
    expect(screen.getByText(/Auto: Toyota Camry 2022/)).toBeInTheDocument()
    expect(screen.getByText('Call #3')).toBeInTheDocument()
  })

  it('shows an error message when the preview request fails', async () => {
    server.use(http.get('/api/v1/leads/:leadId/context-preview', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })))
    renderDetailPage()
    const user = await switchTab('Próxima llamada')
    await user.click(screen.getByRole('button', { name: /cargar vista previa/i }))
    await waitFor(() => expect(screen.getByText(/Failed to load context preview/i)).toBeInTheDocument(), { timeout: 5000 })
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Call history rail + CallDrawer
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — call history rail', () => {
  it('renders call session items from fixture', async () => {
    renderDetailPage()
    await waitFor(() => expect(screen.getAllByTestId('call-history-item')).toHaveLength(2))
  })

  it('clicking a call item opens the real CallDrawer with a transcript', async () => {
    const user = userEvent.setup()
    renderDetailPage()

    await waitFor(() => expect(screen.getAllByTestId('call-history-item')).toHaveLength(2))
    await user.click(screen.getAllByTestId('call-history-item')[0])

    const drawer = await screen.findByRole('dialog')
    expect(within(drawer).getByText(/transcripción/i)).toBeInTheDocument()
  })

  it('clicking "Ver detalle →" navigates to the call detail route instead of opening the drawer', async () => {
    const user = userEvent.setup()
    renderDetailPage()

    await waitFor(() => expect(screen.getAllByTestId('call-detail-link')).toHaveLength(2))
    await user.click(screen.getAllByTestId('call-detail-link')[0])

    await waitFor(() => expect(screen.getByText('Call Detail Page')).toBeInTheDocument())
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows an honest error when sessions fetch fails', async () => {
    server.use(http.get('/api/v1/calls', () => HttpResponse.json({ detail: 'Internal server error' }, { status: 500 })))
    renderDetailPage()
    await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: /John Doe/i })).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText(/Unable to load call history/i)).toBeInTheDocument(), { timeout: 5000 })
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Loading / error states
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadDetailPage — loading state', () => {
  it('shows a page-level loading state while the lead is loading', async () => {
    server.use(
      http.get('/api/v1/leads/:leadId', async () => {
        await new Promise((r) => setTimeout(r, 200))
        return HttpResponse.json({
          id: 'lead-1', client_id: 'demo-client', name: 'John Doe', phone: '+1-555-0100',
          status: 'new', call_count: 0, last_called_at: null, notes: null, created_at: null,
          updated_at: null, summary_last_call: null, objections_heard: null, interest_level: null,
          extracted_facts: null, do_not_call: false, next_action: null, next_action_at: null,
          next_scheduled_call_at: null,
        })
      })
    )
    renderDetailPage()
    expect(screen.getByTestId('lead-loading')).toBeInTheDocument()
  })
})

describe('LeadDetailPage — error state', () => {
  it('shows an error state when lead fetch fails', async () => {
    server.use(http.get('/api/v1/leads/:leadId', () => HttpResponse.json({ detail: 'Not found' }, { status: 404 })))
    renderDetailPage()
    await waitFor(() => expect(screen.getByTestId('lead-error')).toBeInTheDocument(), { timeout: 5000 })
  })
})
