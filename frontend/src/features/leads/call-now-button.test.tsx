/**
 * CallNowCell tests — real outbound call trigger UI (Spanish copy)
 *
 * Spec: phase-c2-outbound-call-trigger / REQ: Frontend Call Trigger UX
 * Design: lead-table.tsx — "Llamar" button in the table; "Llamar ahora" in
 *         the lead detail header (same component, different label).
 *         Confirmation dialog before dispatch; real telephony badges after
 *         success; error messages for 403/409/422/429; do_not_call guard.
 *
 * All API calls are mocked — no live calls possible.
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'

import { LeadTable } from './lead-table'
import { CallNowCell } from './call-now-cell'
import type { Lead } from '@/api/types'

vi.mock('./use-call-polling', () => ({
  useCallPolling: vi.fn(() => null),
}))

const baseLead: Lead = {
  id: 'lead-1',
  client_id: 'demo-client',
  name: 'John Doe',
  phone: '+5491112345678',
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
  next_action: 'Send quote',
  next_action_at: null,
  next_scheduled_call_at: null,
  custom_fields: {},
}

function renderTable(leads: Lead[] = [baseLead]) {
  const onSelectLead = vi.fn()
  return render(<LeadTable clientId="demo-client" leads={leads} onSelectLead={onSelectLead} />)
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('LeadTable — Call Now button placement', () => {
  it('renders a "Llamar" column header', () => {
    renderTable()
    expect(screen.getByRole('columnheader', { name: /llamar/i })).toBeInTheDocument()
  })

  it('renders a "Llamar" button for each lead row', () => {
    renderTable([baseLead, { ...baseLead, id: 'lead-2', name: 'Jane Smith' }])
    const buttons = screen.getAllByRole('button', { name: /^llamar$/i })
    expect(buttons).toHaveLength(2)
  })
})

describe('LeadTable — confirmation dialog', () => {
  it('shows confirmation dialog when "Llamar" is clicked', async () => {
    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getAllByText(/llamada real/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/\$0\.21/)).toBeInTheDocument()
  })

  it('does NOT dispatch the call when dialog appears (before confirmation)', async () => {
    const user = userEvent.setup()
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)

    renderTable()
    await user.click(screen.getByRole('button', { name: /^llamar$/i }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('closes dialog on cancel without making a call', async () => {
    const user = userEvent.setup()
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)

    renderTable()
    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /cancelar/i }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

describe('LeadTable — success: dialing badge', () => {
  it('shows initial "Marcando…" badge after successful dispatch (before first poll)', async () => {
    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /confirmar/i }))

    const badge = await screen.findByText('Marcando…')
    expect(badge).toBeInTheDocument()
  })

  it('hides "Llamar" button while calling badge is shown', async () => {
    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /confirmar/i }))

    await screen.findByText('Marcando…')
    expect(screen.queryByRole('button', { name: /^Llamar$/i })).not.toBeInTheDocument()
  })

  it('dialog is closed after successful dispatch', async () => {
    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /confirmar/i }))

    await screen.findByText('Marcando…')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('LeadTable — error states', () => {
  it('shows 403 error message when feature flag is off', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ detail: 'Outbound calls are not enabled for this instance.' }, { status: 403 })
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /confirmar/i }))

    await waitFor(() => {
      const errorText = screen.getByRole('alert')
      expect(errorText).toBeInTheDocument()
      expect(errorText.textContent).toMatch(/no están habilitadas|403/i)
    })

    expect(screen.queryByText(/marcando/i)).not.toBeInTheDocument()
  })

  it('shows 409 error when a concurrent call is active', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ detail: 'A call is already active for this lead.' }, { status: 409 })
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /confirmar/i }))

    await waitFor(() => {
      const errorText = screen.getByRole('alert')
      expect(errorText.textContent).toMatch(/activa|409/i)
    })
  })

  it('shows 422 error when phone number is invalid E.164', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ detail: 'Lead phone number is not valid E.164.' }, { status: 422 })
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /confirmar/i }))

    await waitFor(() => {
      const errorText = screen.getByRole('alert')
      expect(errorText.textContent).toMatch(/teléfono|E\.164|422/i)
    })
  })

  it('shows 429 error when cooldown is active', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ detail: 'Call attempt too soon after last attempt.' }, { status: 429 })
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /confirmar/i }))

    await waitFor(() => {
      const errorText = screen.getByRole('alert')
      expect(errorText.textContent).toMatch(/pronto|espera|429/i)
    })
  })

  it('button is re-enabled after an error (not stuck in loading)', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ detail: 'Server error' }, { status: 500 })
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /confirmar/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^llamar$/i })).toBeInTheDocument()
    })
  })
})

describe('LeadTable — non-dialing 200 responses', () => {
  it('shows an error (not the dialing badge) when 200 status is "failed"', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({
          status: 'failed',
          call_session_id: 'cs-failed-001',
          error: 'ambiguous_timeout (provider may have placed a call; not retried)',
        })
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /confirmar/i }))

    await waitFor(() => {
      const errorText = screen.getByRole('alert')
      expect(errorText.textContent).toMatch(/no se pudo|timeout|provider/i)
    })

    expect(screen.queryByText('Marcando…')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^llamar$/i })).toBeInTheDocument()
  })

  it('shows an error (not the dialing badge) when 200 status is "recurrent_error"', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({
          status: 'recurrent_error',
          call_session_id: 'cs-recurrent-001',
          error: 'attempt_1: 503; attempt_2: 503',
        })
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /confirmar/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.queryByText('Marcando…')).not.toBeInTheDocument()
  })

  it('shows the dialing badge (not an error) when 200 status is "dialing"', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ status: 'dialing', call_session_id: 'cs-ok-001' })
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /confirmar/i }))

    expect(await screen.findByText('Marcando…')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('LeadTable — calling timeout (polling-driven, 180s)', () => {
  it('the 60s blind timer is removed — component no longer uses setTimeout for calling timeout', () => {
    const cellSource = `${CallNowCell.toString()}`
    expect(cellSource).not.toMatch(/60.000|60_000|CALLING_TIMEOUT/i)
  })
})

describe('LeadTable — do_not_call guard', () => {
  it('renders "No llamar" instead of the trigger button when do_not_call is true', () => {
    renderTable([{ ...baseLead, do_not_call: true }])
    expect(screen.getByText('No llamar')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^llamar$/i })).not.toBeInTheDocument()
  })
})

describe('LeadTable — row click isolation', () => {
  it('does not navigate to lead detail when "Llamar" button is clicked', async () => {
    const user = userEvent.setup()
    const onSelectLead = vi.fn()
    render(<LeadTable clientId="demo-client" leads={[baseLead]} onSelectLead={onSelectLead} />)

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))

    expect(onSelectLead).not.toHaveBeenCalled()
  })

  it('does not navigate to lead detail when the dialog is confirmed', async () => {
    const user = userEvent.setup()
    const onSelectLead = vi.fn()
    render(<LeadTable clientId="demo-client" leads={[baseLead]} onSelectLead={onSelectLead} />)

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /confirmar/i }))

    await screen.findByText('Marcando…')
    expect(onSelectLead).not.toHaveBeenCalled()
  })

  it('does not navigate to lead detail when the dialog is cancelled', async () => {
    const user = userEvent.setup()
    const onSelectLead = vi.fn()
    render(<LeadTable clientId="demo-client" leads={[baseLead]} onSelectLead={onSelectLead} />)

    await user.click(screen.getByRole('button', { name: /^llamar$/i }))
    await user.click(screen.getByRole('button', { name: /cancelar/i }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(onSelectLead).not.toHaveBeenCalled()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Plan gating (multi-tenant-readiness)
// ──────────────────────────────────────────────────────────────────────────────

describe('CallNowCell — plan gating', () => {
  it('renders a disabled button with the reason when the plan excludes outbound calls', () => {
    render(
      <CallNowCell
        clientId="demo-client"
        lead={baseLead}
        disabledReason="Tu plan no incluye llamadas salientes"
      />,
    )
    const button = screen.getByRole('button', { name: 'Llamar' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', 'Tu plan no incluye llamadas salientes')
  })

  it('LeadTable forwards the disabled reason to every row', () => {
    render(
      <LeadTable
        clientId="demo-client"
        leads={[baseLead]}
        onSelectLead={vi.fn()}
        callDisabledReason="Tu plan no incluye llamadas salientes"
      />,
    )
    expect(screen.getByRole('button', { name: 'Llamar' })).toBeDisabled()
  })

  it.each([
    ['plan_limit_reached', 429, 'Plan limit reached: max_monthly_minutes (200/200).', 'Alcanzaste el límite de tu plan'],
    ['feature_not_in_plan', 403, "The client's plan does not include 'outbound_calls'.", 'Tu plan no incluye llamadas salientes'],
  ])('explains a %s error from the backend', async (reason, status, message, expected) => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ error: { code: status, message, reason, request_id: '' } }, { status }),
      ),
    )
    const user = userEvent.setup()
    render(<CallNowCell clientId="demo-client" lead={baseLead} />)

    await user.click(screen.getByRole('button', { name: 'Llamar' }))
    await user.click(screen.getByRole('button', { name: /confirmar|llamar ahora/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(expected)
  })
})
