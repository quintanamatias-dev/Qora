/**
 * CallNowButton tests — C2 outbound call trigger UI
 *
 * Spec: phase-c2-outbound-call-trigger / REQ: Frontend Call Trigger UX
 * Design: lead-table.tsx — "Call Now" green button after next_action column;
 *         confirmation dialog before dispatch; "Calling…" badge after success;
 *         error messages for 403/409/422/429.
 *
 * TDD RED phase: written before the implementation.
 * All API calls are mocked — no live calls possible.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'

// The component under test — imported after RED confirms the file exists but
// exports are missing. Test will fail at import level or at runtime.
import { LeadTable } from './lead-table'
import { CallNowCell } from './call-now-cell'
import type { Lead } from '@/api/types'

// Mock useCallPolling so these tests don't depend on the polling network behavior.
// The hook is tested separately in use-call-polling.test.ts.
// Here we return null (inactive) to isolate CallNowCell's own behavior.
vi.mock('./use-call-polling', () => ({
  useCallPolling: vi.fn(() => null),
}))

// ──────────────────────────────────────────────────────────────────────────────
// Fixtures
// ──────────────────────────────────────────────────────────────────────────────

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

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function renderTable(leads: Lead[] = [baseLead]) {
  const onSelectLead = vi.fn()
  return render(
    <LeadTable
      clientId="demo-client"
      leads={leads}
      onSelectLead={onSelectLead}
    />
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

// ──────────────────────────────────────────────────────────────────────────────
// Button placement
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadTable — Call Now button placement', () => {
  it('renders a "Call Now" column header', () => {
    renderTable()
    expect(screen.getByRole('columnheader', { name: /call now/i })).toBeInTheDocument()
  })

  it('renders a "Call Now" button for each lead row', () => {
    renderTable([baseLead, { ...baseLead, id: 'lead-2', name: 'Jane Smith' }])
    const buttons = screen.getAllByRole('button', { name: /call now/i })
    expect(buttons).toHaveLength(2)
  })

  it('button is positioned after the Next Action column', () => {
    renderTable()
    // Get all column headers in order
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent?.toLowerCase())
    const nextActionIdx = headers.findIndex((h) => h?.includes('next action'))
    const callNowIdx = headers.findIndex((h) => h?.includes('call now'))
    expect(callNowIdx).toBeGreaterThan(nextActionIdx)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Confirmation dialog
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadTable — confirmation dialog', () => {
  it('shows confirmation dialog when "Call Now" is clicked', async () => {
    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))

    // Dialog must warn about real cost — check dialog role and cost copy
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    // The dialog title contains "real call" (getAllByText handles multiple matches)
    expect(screen.getAllByText(/real call/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/\$0\.21/)).toBeInTheDocument()
  })

  it('does NOT dispatch the call when dialog appears (before confirmation)', async () => {
    const user = userEvent.setup()
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)

    renderTable()
    await user.click(screen.getByRole('button', { name: /call now/i }))

    // Dialog is showing but POST has not been fired
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('closes dialog on cancel without making a call', async () => {
    const user = userEvent.setup()
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)

    renderTable()
    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /cancel/i }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Success — Calling… badge
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadTable — success: calling badge', () => {
  it('shows initial "Dialing…" badge after successful dispatch (before first poll)', async () => {
    // Spec: call-now-feedback — Requirement: Real State Badges
    // Before the first polling response, the component shows "Dialing…" as the
    // initial optimistic badge. The badge text is driven by polling once it starts.
    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    // findByText retries automatically — resolves when the badge renders
    const badge = await screen.findByText('Dialing…')
    expect(badge).toBeInTheDocument()
  })

  it('hides "Call Now" button while calling badge is shown', async () => {
    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    // Wait for success state — "Dialing…" badge replaces the button
    await screen.findByText('Dialing…')
    // In the 'calling' phase, the main Call Now button is replaced by the badge
    expect(screen.queryByRole('button', { name: /^Call Now$/i })).not.toBeInTheDocument()
  })

  it('dialog is closed after successful dispatch', async () => {
    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await screen.findByText('Dialing…')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Error states
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadTable — error states', () => {
  it('shows 403 error message when feature flag is off', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json(
          { detail: 'Outbound calls are not enabled for this instance.' },
          { status: 403 }
        )
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      // Must show a user-readable error — no "Calling…" badge
      const errorText = screen.getByRole('alert')
      expect(errorText).toBeInTheDocument()
      expect(errorText.textContent).toMatch(/not enabled|disabled|403/i)
    })

    // No "Calling…" badge when there is an error
    expect(screen.queryByText(/calling/i)).not.toBeInTheDocument()
  })

  it('shows 409 error when a concurrent call is active', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json(
          { detail: 'A call is already active for this lead.' },
          { status: 409 }
        )
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      const errorText = screen.getByRole('alert')
      expect(errorText.textContent).toMatch(/active|in progress|already|409/i)
    })
  })

  it('shows 422 error when phone number is invalid E.164', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json(
          { detail: 'Lead phone number is not valid E.164.' },
          { status: 422 }
        )
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      const errorText = screen.getByRole('alert')
      expect(errorText.textContent).toMatch(/phone|invalid|E\.164|422/i)
    })
  })

  it('shows 429 error when cooldown is active', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json(
          { detail: 'Call attempt too soon after last attempt.' },
          { status: 429 }
        )
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      const errorText = screen.getByRole('alert')
      expect(errorText.textContent).toMatch(/too soon|cooldown|wait|429/i)
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

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    // After the error resolves, "Call Now" must reappear (not frozen)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /call now/i })).toBeInTheDocument()
    })
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Non-dialing 200 responses — must NOT get stuck on "Calling…"
//
// Regression: the backend returns HTTP 200 with status 'failed' | 'recurrent_error'
// for provider errors and ambiguous timeouts. The UI previously entered the
// 'calling' phase on any 2xx, leaving the row stuck on "Calling…" forever even
// though no call was placed. It must render an error instead.
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadTable — non-dialing 200 responses', () => {
  it('shows an error (not "Calling…") when 200 status is "failed"', async () => {
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

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      const errorText = screen.getByRole('alert')
      expect(errorText.textContent).toMatch(/could not|timeout|provider|failed/i)
    })

    // Must NOT show the Calling… badge — no real call is in progress
    expect(screen.queryByText('Calling…')).not.toBeInTheDocument()
    // The retry affordance (Call Now) must reappear
    expect(screen.getByRole('button', { name: /call now/i })).toBeInTheDocument()
  })

  it('shows an error (not "Calling…") when 200 status is "recurrent_error"', async () => {
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

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    expect(screen.queryByText('Calling…')).not.toBeInTheDocument()
  })

  it('shows "Dialing…" badge (not an error) when 200 status is "dialing"', async () => {
    // Positive control: a genuine dialing response must enter the calling state.
    // Spec: call-now-feedback — initial badge shows "Dialing…" before first poll.
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ status: 'dialing', call_session_id: 'cs-ok-001' })
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    // "Dialing…" is the initial optimistic badge before polling returns
    expect(await screen.findByText('Dialing…')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Calling state — polling-driven timeout
//
// Spec: call-now-feedback — Requirement: Honest Timeout
//   The 60s blind timer is REPLACED by useCallPolling with a 180s honest timeout.
//   Timeout behavior is tested in use-call-polling.test.ts at the hook level.
//   Here we verify the component renders the timedOut message from the hook.
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadTable — calling timeout (polling-driven, 180s)', () => {
  it('the 60s blind timer is removed — component no longer uses setTimeout for calling timeout', () => {
    // Spec: call-now-feedback — Requirement: Honest Timeout
    // The previous 60s blind timer (CALLING_TIMEOUT_MS = 60_000) is gone.
    // Timeout is now handled by useCallPolling at 180s.
    // Regression guard: if this test breaks, someone re-introduced the blind timer.
    const cellSource = `${CallNowCell.toString()}`
    expect(cellSource).not.toMatch(/60.000|60_000|CALLING_TIMEOUT/i)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Row click isolation
// ──────────────────────────────────────────────────────────────────────────────

describe('LeadTable — row click isolation', () => {
  it('does not navigate to lead detail when "Call Now" button is clicked', async () => {
    const user = userEvent.setup()
    const onSelectLead = vi.fn()
    render(<LeadTable clientId="demo-client" leads={[baseLead]} onSelectLead={onSelectLead} />)

    await user.click(screen.getByRole('button', { name: /call now/i }))

    // row onClick must not fire — only the dialog should open
    expect(onSelectLead).not.toHaveBeenCalled()
  })

  it('does not navigate to lead detail when the dialog is confirmed', async () => {
    // Regression: the ConfirmCallDialog is portaled to document.body, but React
    // synthetic events bubble through the React tree back to the row's onClick.
    // Confirming must NOT trigger onSelectLead / lead navigation.
    const user = userEvent.setup()
    const onSelectLead = vi.fn()
    render(<LeadTable clientId="demo-client" leads={[baseLead]} onSelectLead={onSelectLead} />)

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    // Wait for the successful dispatch to render the "Dialing…" badge, proving the
    // confirm click was handled — and the row navigation never fired.
    // Spec: call-now-feedback — initial badge is "Dialing…" before first poll.
    await screen.findByText('Dialing…')
    expect(onSelectLead).not.toHaveBeenCalled()
  })

  it('does not navigate to lead detail when the dialog is cancelled', async () => {
    const user = userEvent.setup()
    const onSelectLead = vi.fn()
    render(<LeadTable clientId="demo-client" leads={[baseLead]} onSelectLead={onSelectLead} />)

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /cancel/i }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(onSelectLead).not.toHaveBeenCalled()
  })
})
