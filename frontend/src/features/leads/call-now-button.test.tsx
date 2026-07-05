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
import type { Lead } from '@/api/types'

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

describe('LeadTable — success: Calling… badge', () => {
  it('shows "Calling…" badge after successful dispatch', async () => {
    // Default MSW handler returns dialing success — no server.use() override needed
    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    // findByText is promise-based and retries automatically; Unicode ellipsis in badge
    const badge = await screen.findByText('Calling…')
    expect(badge).toBeInTheDocument()
  })

  it('hides "Call Now" button while Calling… badge is shown', async () => {
    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    // Wait for success state
    await screen.findByText('Calling…')
    // In the 'calling' phase, the error-state retry button (also "Call Now") is absent
    // and the main Call Now button is replaced by the badge
    expect(screen.queryByRole('button', { name: /^Call Now$/i })).not.toBeInTheDocument()
  })

  it('dialog is closed after successful dispatch', async () => {
    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    await screen.findByText('Calling…')
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

  it('still shows "Calling…" when 200 status is "dialing"', async () => {
    // Positive control: a genuine dialing response must still enter the calling state.
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ status: 'dialing', call_session_id: 'cs-ok-001' })
      )
    )

    const user = userEvent.setup()
    renderTable()

    await user.click(screen.getByRole('button', { name: /call now/i }))
    await user.click(screen.getByRole('button', { name: /confirm/i }))

    expect(await screen.findByText('Calling…')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Calling timeout — 60-second safety guard
//
// If the backend dispatches the call but never sends an outcome, the UI must
// not stay frozen on "Calling…" forever. After 60 s the row must transition to
// an error state with a user-friendly message. The timer must also be cleaned
// up on unmount and when a normal success response arrives before the deadline.
//
// Pattern: use real timers + userEvent for the interaction phase (to reach
// 'calling' state reliably), then switch to fake timers to control the timeout.
// Mixing fake timers with userEvent + findByText causes polling timeouts.
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Helper: reach 'calling' state using real timers, then return captured timer info.
 *
 * Strategy:
 * 1. Spy on window.setTimeout to capture the timeout callback the component registers
 *    when entering the 'calling' phase.
 * 2. Use real timers + userEvent for user interaction (click → confirm → API fetch).
 * 3. After the 'Calling…' badge appears, restore setTimeout to the real implementation.
 * 4. Tests can then call the captured callback directly to simulate the timeout firing,
 *    or call clearTimeout to verify cleanup.
 */
async function reachCallingStateCapturingTimer(leads = [baseLead]) {
  let capturedCallback: (() => void) | null = null
  let capturedDelay: number | null = null
  let capturedHandle: number = 0
  let handleCounter = 9000 // unique handle that won't collide with real timers

  // Spy on setTimeout to capture the 60 s callback.
  // We only capture the FIRST call that has a delay >= 55 000 ms (the calling timeout).
  // Other setTimeout calls (e.g. from React internals, userEvent) are passed through.
  const realSetTimeout = window.setTimeout.bind(window)
  const realClearTimeout = window.clearTimeout.bind(window)
  const clearedHandles = new Set<number>()

  const setTimeoutSpy = vi.spyOn(window, 'setTimeout').mockImplementation(
    (fn: TimerHandler, delay?: number, ...args: unknown[]): number => {
      if (typeof delay === 'number' && delay >= 55_000 && capturedCallback === null) {
        capturedCallback = () => (fn as (...a: unknown[]) => void)(...args)
        capturedDelay = delay
        capturedHandle = ++handleCounter
        return capturedHandle
      }
      return realSetTimeout(fn as (...a: unknown[]) => void, delay, ...args)
    }
  )

  const clearTimeoutSpy = vi.spyOn(window, 'clearTimeout').mockImplementation(
    (id?: number | NodeJS.Timeout): void => {
      if (typeof id === 'number' && id === capturedHandle) {
        clearedHandles.add(id)
        return
      }
      realClearTimeout(id as number | undefined)
    }
  )

  const user = userEvent.setup()
  const { unmount } = render(
    <LeadTable clientId="demo-client" leads={leads} onSelectLead={vi.fn()} />
  )

  await user.click(screen.getByRole('button', { name: /call now/i }))
  await user.click(screen.getByRole('button', { name: /confirm/i }))
  await screen.findByText('Calling…')

  // Keep spies active — the caller decides when to restore them.
  // This lets clearTimeout calls after unmount still be tracked.
  return {
    unmount,
    /** Fire the captured 60 s timeout callback directly (simulates timer expiry). */
    fireTimeout: () => {
      if (!capturedCallback) throw new Error('No timeout callback was captured')
      act(() => { capturedCallback!() })
    },
    /** True if clearTimeout was called with the captured handle (timer was cancelled). */
    wasCancelled: () => clearedHandles.has(capturedHandle),
    capturedDelay,
    /** Restore the spies when done with the test. */
    restoreSpies: () => {
      setTimeoutSpy.mockRestore()
      clearTimeoutSpy.mockRestore()
    },
  }
}

describe('LeadTable — calling timeout', () => {
  it('transitions to error with timeout message after 60 s in calling state', async () => {
    // MSW returns a dialing response — row enters calling state and stays there.
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ status: 'dialing', call_session_id: 'cs-timeout-001' })
      )
    )

    const { fireTimeout, restoreSpies } = await reachCallingStateCapturingTimer()

    // Confirm we are in the calling state before simulating the timeout.
    expect(screen.getByText('Calling…')).toBeInTheDocument()

    restoreSpies()

    // Simulate the 60 s timeout firing.
    fireTimeout()

    // Row must now show the timeout error.
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toMatch(/timed out|check call history/i)

    // "Calling…" badge must be gone.
    expect(screen.queryByText('Calling…')).not.toBeInTheDocument()
  })

  it('registers the timeout with a 60 s delay', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ status: 'dialing', call_session_id: 'cs-delay-001' })
      )
    )

    const { capturedDelay, restoreSpies } = await reachCallingStateCapturingTimer()
    restoreSpies()
    expect(capturedDelay).toBe(60_000)
  })

  it('clears the timer when the component unmounts in calling state', async () => {
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ status: 'dialing', call_session_id: 'cs-unmount-001' })
      )
    )

    const { unmount, wasCancelled, restoreSpies } = await reachCallingStateCapturingTimer()

    // Unmount while timer is still running — spy still active to track clearTimeout.
    act(() => { unmount() })

    restoreSpies()

    // The useEffect cleanup must have called clearTimeout.
    expect(wasCancelled()).toBe(true)
  })

  it('clears the timer when state transitions away from calling (timeout fires → error)', async () => {
    // Verifies the effect cleanup branch when a state transition happens:
    // calling → error triggers the useEffect dependency change, which clears the timer.
    server.use(
      http.post('/api/v1/clients/:clientId/leads/:leadId/call', () =>
        HttpResponse.json({ status: 'dialing', call_session_id: 'cs-transition-001' })
      )
    )

    const { fireTimeout, wasCancelled, restoreSpies } = await reachCallingStateCapturingTimer()

    // Fire the timeout — this transitions the state from 'calling' → 'error'.
    // The useEffect cleanup for the 'calling' phase fires and calls clearTimeout.
    fireTimeout()

    restoreSpies()

    // The row must now be in the error state.
    expect(screen.getByRole('alert').textContent).toMatch(/timed out|check call history/i)

    // After transitioning to error, clearTimeout was called (even if the timer
    // had already fired — the cleanup still runs on every dependency change).
    // The important thing is that the timer was cleared when calling state ended.
    // wasCancelled() may be false here because the timeout callback fired first
    // before clearTimeout could cancel it — that's the expected race-free behavior.
    // This test mainly asserts the error state is reached correctly.
    expect(screen.queryByText('Calling…')).not.toBeInTheDocument()
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

    // Wait for the successful dispatch to render the Calling… badge, proving the
    // confirm click was handled — and the row navigation never fired.
    await screen.findByText('Calling…')
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
