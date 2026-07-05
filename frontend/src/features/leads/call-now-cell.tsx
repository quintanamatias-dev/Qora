/**
 * CallNowCell — Stateful table cell managing the per-row outbound call lifecycle.
 *
 * Spec: phase-c2-outbound-call-trigger — Requirement: Frontend Call Trigger UX
 *
 * Responsibilities:
 *   - Renders the "Call Now" button in its idle state
 *   - Opens a confirmation dialog (ConfirmCallDialog) before dispatching
 *   - Shows an optimistic "Calling…" badge after a successful dispatch
 *   - Shows a dismissible error row for 403/409/422/429 or provider failures
 *   - Starts a 60-second safety timeout in the 'calling' phase to prevent
 *     the UI from freezing when the provider fails silently
 */

import { useState, useEffect, useRef } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import type { Lead, CallTriggerResponse } from '@/api/types'
import { Badge } from '@/design/components/badge'
import { Button } from '@/design/components/button'
import { triggerCall } from '@/api/leads'
import { ApiError } from '@/api/client'

// ──────────────────────────────────────────────────────────────────────────────
// Per-row call state
// ──────────────────────────────────────────────────────────────────────────────

type CallRowState =
  | { phase: 'idle' }
  | { phase: 'confirming' }
  | { phase: 'loading' }
  | { phase: 'calling'; callSessionId: string }
  | { phase: 'error'; message: string }

// ──────────────────────────────────────────────────────────────────────────────
// Error message mapping (spec-compliant user-readable messages)
// ──────────────────────────────────────────────────────────────────────────────

function resolveErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    // Prefer the server's detail message when it's a string
    if (err.body && typeof err.body === 'object' && 'detail' in err.body) {
      const detail = (err.body as { detail: unknown }).detail
      if (typeof detail === 'string' && detail.length > 0) {
        // Prefix with status context for operator clarity
        return `(${err.status}) ${detail}`
      }
    }
    switch (err.status) {
      case 403:
        return '(403) Outbound calls are not enabled. Set ENABLE_OUTBOUND_CALLS=true to activate.'
      case 409:
        return '(409) A call is already active or in progress for this lead.'
      case 422:
        return '(422) Lead phone number is not valid E.164. Update the phone and retry.'
      case 429:
        return '(429) Too soon after last attempt. Wait a few seconds and retry.'
      default:
        return `Error ${err.status}: ${err.message}`
    }
  }
  if (err instanceof Error) return err.message
  return 'An unexpected error occurred.'
}

/**
 * Build a user-readable message for a 200 response that reports a non-dialing
 * status (failed / recurrent_error). The backend HTTP call succeeded but the
 * dial did not — so we surface the backend `error` when present, with a
 * status-specific fallback. This prevents the row from getting stuck on
 * "Calling…" when the call was never actually placed.
 */
function resolveTriggerFailureMessage(result: CallTriggerResponse): string {
  if (result.error && result.error.length > 0) {
    return result.error
  }
  switch (result.status) {
    case 'recurrent_error':
      return 'The call could not be placed after a retry. Please try again shortly.'
    case 'failed':
    default:
      return 'The call could not be placed. Please try again.'
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────────────────────

/**
 * How long (ms) to wait in the 'calling' phase before declaring a timeout.
 * The ElevenLabs backend read-timeout is 45 s; 60 s gives a comfortable margin
 * so the UI never stays stuck when the provider fails silently.
 */
const CALLING_TIMEOUT_MS = 60_000

const CALLING_TIMEOUT_MESSAGE =
  'Call timed out — the call may still be connecting. Check call history.'

// ──────────────────────────────────────────────────────────────────────────────
// ConfirmCallDialog — Radix Dialog wrapping the confirmation step
// ──────────────────────────────────────────────────────────────────────────────

interface ConfirmCallDialogProps {
  open: boolean
  leadName: string
  isLoading: boolean
  onConfirm: () => void
  onCancel: () => void
}

function ConfirmCallDialog({
  open,
  leadName,
  isLoading,
  onConfirm,
  onCancel,
}: ConfirmCallDialogProps) {
  // The dialog is rendered inside CallNowCell, which lives inside the clickable
  // <tr>. Radix portals the content to document.body, but React synthetic events
  // bubble through the REACT tree — not the DOM tree — so clicks on the overlay,
  // Confirm, or Cancel would still reach the row's onClick and navigate to the
  // lead profile. Stop propagation at the portal boundary to isolate the dialog.
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { if (!o) onCancel() }}>
      <Dialog.Portal>
        {/* Overlay */}
        <Dialog.Overlay
          className="fixed inset-0 bg-ink/20 backdrop-blur-[2px] z-40"
          onClick={stop}
        />
        {/* Content */}
        <Dialog.Content
          onClick={stop}
          className={[
            'fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50',
            'bg-paper rounded-xl shadow-xl border border-line',
            'w-[min(440px,90vw)] p-6',
            'focus:outline-none',
          ].join(' ')}
        >
          {/* Header */}
          <Dialog.Title className="font-display text-lg font-semibold text-ink mb-1">
            Confirm real call
          </Dialog.Title>

          {/* Body — Dialog.Description provides proper aria-describedby wiring for Radix */}
          <Dialog.Description asChild>
            <div className="text-sm text-ink-2 space-y-3 mb-6">
              <p>
                You are about to place a <strong className="text-ink">real call</strong> to{' '}
                <span className="font-medium text-teal">{leadName}</span>.
              </p>
              <p className="flex items-start gap-2 bg-warning/8 border border-warning/20 rounded-lg px-3 py-2">
                <span aria-hidden>⚠️</span>
                <span>
                  This will connect via ElevenLabs + Telnyx and incur telephony costs
                  (~$0.21/min). The call begins immediately after you confirm.
                </span>
              </p>
            </div>
          </Dialog.Description>

          {/* Actions */}
          <div className="flex gap-3 justify-end">
            <Button
              variant="secondary"
              size="sm"
              onClick={(e) => { e.stopPropagation(); onCancel() }}
              disabled={isLoading}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={(e) => { e.stopPropagation(); onConfirm() }}
              disabled={isLoading}
              className="min-w-[90px]"
            >
              {isLoading ? (
                <span className="flex items-center gap-1.5">
                  <span
                    className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"
                    aria-hidden
                  />
                  Calling…
                </span>
              ) : (
                'Confirm'
              )}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// CallNowCell
// ──────────────────────────────────────────────────────────────────────────────

export interface CallNowCellProps {
  clientId: string
  lead: Lead
}

export function CallNowCell({ clientId, lead }: CallNowCellProps) {
  const [state, setState] = useState<CallRowState>({ phase: 'idle' })
  // Holds the active timeout handle so it can be cancelled on state change or unmount.
  const callingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Start a 60-second safety timeout whenever we enter the 'calling' phase.
  // If the backend never sends an outcome (silent provider failure), the timer
  // fires and transitions the row to an error state instead of staying frozen.
  useEffect(() => {
    if (state.phase === 'calling') {
      callingTimerRef.current = setTimeout(() => {
        setState({ phase: 'error', message: CALLING_TIMEOUT_MESSAGE })
      }, CALLING_TIMEOUT_MS)
    } else {
      // Any transition away from 'calling' (success, error, cancel) cancels the timer.
      if (callingTimerRef.current !== null) {
        clearTimeout(callingTimerRef.current)
        callingTimerRef.current = null
      }
    }

    return () => {
      // Cleanup on unmount or before re-running the effect.
      if (callingTimerRef.current !== null) {
        clearTimeout(callingTimerRef.current)
        callingTimerRef.current = null
      }
    }
  }, [state.phase])

  function handleButtonClick(e: React.MouseEvent) {
    // Stop row-level onClick from navigating to lead detail
    e.stopPropagation()
    setState({ phase: 'confirming' })
  }

  function handleCancel() {
    setState({ phase: 'idle' })
  }

  async function handleConfirm() {
    setState({ phase: 'loading' })
    try {
      const result = await triggerCall(clientId, lead.id)
      // A 200 response does NOT mean the call was placed. The backend returns
      // 200 with status 'failed' | 'recurrent_error' for provider errors and
      // ambiguous timeouts. Only 'dialing' is a real in-progress call — anything
      // else must show an error row, never a permanent "Calling…" badge.
      if (result.status === 'dialing' && result.call_session_id) {
        setState({ phase: 'calling', callSessionId: result.call_session_id })
      } else {
        setState({ phase: 'error', message: resolveTriggerFailureMessage(result) })
      }
    } catch (err) {
      setState({ phase: 'error', message: resolveErrorMessage(err) })
    }
  }

  if (state.phase === 'calling') {
    return (
      <Badge status="active" className="whitespace-nowrap">
        Calling…
      </Badge>
    )
  }

  if (state.phase === 'error') {
    return (
      <div className="flex flex-col gap-1 max-w-[200px]">
        <span
          role="alert"
          className="text-xs text-coral leading-tight"
          title={state.message}
        >
          {state.message}
        </span>
        <button
          onClick={(e) => { e.stopPropagation(); setState({ phase: 'idle' }) }}
          className="text-xs text-ink-3 underline text-left hover:text-ink transition-colors"
          aria-label="Call Now"
        >
          Call Now
        </button>
      </div>
    )
  }

  return (
    <>
      <Button
        variant="primary"
        size="sm"
        onClick={handleButtonClick}
        disabled={state.phase === 'loading'}
        className="whitespace-nowrap"
      >
        Call Now
      </Button>

      <ConfirmCallDialog
        open={state.phase === 'confirming' || state.phase === 'loading'}
        leadName={lead.name}
        isLoading={state.phase === 'loading'}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </>
  )
}
