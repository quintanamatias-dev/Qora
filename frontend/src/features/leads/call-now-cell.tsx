/**
 * CallNowCell — Stateful table cell managing the per-row outbound call lifecycle.
 *
 * Spec: call-now-feedback — Requirement: Polling Lifecycle After Trigger
 *   Replaces the blind 60s timer with real-time polling via useCallPolling.
 *   After POST /call returns call_session_id, polls GET /calls/{id}/status every 3s.
 *
 * Spec: call-now-feedback — Requirement: Real State Badges
 *   Badge text and color map to real telephony_status from the polling endpoint.
 *   No timer-based "Calling…" badge — the badge reflects actual state.
 *
 * Spec: call-now-feedback — Requirement: Honest Timeout
 *   After 180s with no terminal state, shows "Timed out — check call history".
 *
 * Spec: call-now-feedback — Requirement: Graceful 409 Display
 *   409 shows active_session_id when available. No polling started on 409.
 */

import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import type { Lead, CallTriggerResponse } from '@/api/types'
import { Badge } from '@/design/components/badge'
import { Button } from '@/design/components/button'
import { triggerCall } from '@/api/leads'
import { ApiError } from '@/api/client'
import { useCallPolling } from './use-call-polling'
import type { TelephonyStatus } from '@/api/types'

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
// Badge configuration — maps telephony_status to user-visible label and color
//
// Spec: call-now-feedback — Requirement: Real State Badges
// Badge map: dialing→"Dialing…" (gray) | ringing→"Ringing…" (blue) |
//   connected→"Connected" (green) | voicemail→"Voicemail" (amber) |
//   completed→"Completed" (green-muted) | no_answer→"No Answer" (gray) |
//   failed/recurrent_error→"Call Failed" (red)
// ──────────────────────────────────────────────────────────────────────────────

interface BadgeConfig {
  label: string
  variant: 'active' | 'success' | 'warning' | 'error' | 'muted' | 'neutral'
}

const TELEPHONY_BADGE_MAP: Record<TelephonyStatus, BadgeConfig> = {
  queued:          { label: 'Queued',      variant: 'neutral' },
  dialing:         { label: 'Dialing…',    variant: 'neutral' },
  ringing:         { label: 'Ringing…',    variant: 'active' },
  connected:       { label: 'Connected',   variant: 'success' },
  voicemail:       { label: 'Voicemail',   variant: 'warning' },
  completed:       { label: 'Completed',   variant: 'muted' },
  no_answer:       { label: 'No Answer',   variant: 'neutral' },
  failed:          { label: 'Call Failed', variant: 'error' },
  recurrent_error: { label: 'Call Failed', variant: 'error' },
  stale_in_call:   { label: 'Call Failed', variant: 'error' },
}

function TelephonyBadge({ status }: { status: TelephonyStatus }) {
  const config = TELEPHONY_BADGE_MAP[status] ?? { label: status, variant: 'neutral' as const }
  return (
    <Badge status={config.variant} className="whitespace-nowrap">
      {config.label}
    </Badge>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Error message mapping (spec-compliant user-readable messages)
// ──────────────────────────────────────────────────────────────────────────────

function resolveErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    // Spec: call-now-feedback — Requirement: Graceful 409 Display
    // 409 must display actionable message with active_session_id if available.
    if (err.status === 409) {
      const body = err.body as Record<string, unknown> | undefined
      const activeSessionId =
        body && typeof body === 'object' && 'active_session_id' in body
          ? (body as { active_session_id?: string }).active_session_id
          : undefined
      if (activeSessionId) {
        return `(409) A call is already active for this lead (session: ${activeSessionId}).`
      }
      return '(409) A call is already active or in progress for this lead.'
    }

    // Prefer the server's detail message when it's a string
    if (err.body && typeof err.body === 'object' && 'detail' in err.body) {
      const detail = (err.body as { detail: unknown }).detail
      if (typeof detail === 'string' && detail.length > 0) {
        return `(${err.status}) ${detail}`
      }
    }

    switch (err.status) {
      case 403:
        return '(403) Outbound calls are not enabled. Set ENABLE_OUTBOUND_CALLS=true to activate.'
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
 * status-specific fallback.
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

const TIMEOUT_MESSAGE = 'Timed out — check call history.'

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
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { if (!o) onCancel() }}>
      <Dialog.Portal>
        <Dialog.Overlay
          className="fixed inset-0 bg-ink/20 backdrop-blur-[2px] z-40"
          onClick={stop}
        />
        <Dialog.Content
          onClick={stop}
          className={[
            'fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50',
            'bg-paper rounded-xl shadow-xl border border-line',
            'w-[min(440px,90vw)] p-6',
            'focus:outline-none',
          ].join(' ')}
        >
          <Dialog.Title className="font-display text-lg font-semibold text-ink mb-1">
            Confirm real call
          </Dialog.Title>

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

  // Resolve the active session ID for polling (null when not in 'calling' phase).
  const activeSessionId = state.phase === 'calling' ? state.callSessionId : null

  // useCallPolling starts/stops automatically based on activeSessionId.
  // Returns null when inactive (no polling).
  const pollingState = useCallPolling(activeSessionId)

  // Derive displayed content from polling state (overrides local 'calling' phase).
  // Polling is authoritative when active; local state governs all other phases.

  function handleButtonClick(e: React.MouseEvent) {
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
      if (result.status === 'dialing' && result.call_session_id) {
        // Spec: polling starts within 3s of POST response.
        // useCallPolling activates when callSessionId is set.
        setState({ phase: 'calling', callSessionId: result.call_session_id })
      } else {
        setState({ phase: 'error', message: resolveTriggerFailureMessage(result) })
      }
    } catch (err) {
      setState({ phase: 'error', message: resolveErrorMessage(err) })
    }
  }

  // ── Render: polling phase — real state badges from the polling endpoint ──

  if (state.phase === 'calling' && pollingState !== null) {
    // Spec: Honest Timeout — show message after 180s with no terminal state.
    if (pollingState.status === 'timedOut') {
      return (
        <div className="flex flex-col gap-1 max-w-[200px]">
          <span role="alert" className="text-xs text-ink-2 leading-tight">
            {TIMEOUT_MESSAGE}
          </span>
          <button
            onClick={(e) => { e.stopPropagation(); setState({ phase: 'idle' }) }}
            className="text-xs text-ink-3 underline text-left hover:text-ink transition-colors"
          >
            Dismiss
          </button>
        </div>
      )
    }

    // Spec: Real State Badges — badge reflects telephony_status from polling.
    if (pollingState.status === 'polling') {
      return <TelephonyBadge status={pollingState.telephonyStatus} />
    }

    // Terminal state — call ended.
    if (pollingState.status === 'terminal') {
      const isFailure = ['failed', 'recurrent_error', 'stale_in_call', 'no_answer'].includes(
        pollingState.telephonyStatus
      )
      return (
        <div className="flex flex-col gap-1 max-w-[200px]">
          <TelephonyBadge status={pollingState.telephonyStatus} />
          {isFailure && (
            <button
              onClick={(e) => { e.stopPropagation(); setState({ phase: 'idle' }) }}
              className="text-xs text-ink-3 underline text-left hover:text-ink transition-colors"
            >
              Retry
            </button>
          )}
        </div>
      )
    }

    // Polling error — surface to operator.
    if (pollingState.status === 'error') {
      return (
        <div className="flex flex-col gap-1 max-w-[200px]">
          <span role="alert" className="text-xs text-coral leading-tight">
            {pollingState.message}
          </span>
          <button
            onClick={(e) => { e.stopPropagation(); setState({ phase: 'idle' }) }}
            className="text-xs text-ink-3 underline text-left hover:text-ink transition-colors"
          >
            Dismiss
          </button>
        </div>
      )
    }
  }

  // ── Render: 'calling' phase but polling hasn't returned yet (first tick) ──
  if (state.phase === 'calling') {
    return (
      <Badge status="active" className="whitespace-nowrap">
        Dialing…
      </Badge>
    )
  }

  // ── Render: error phase ──
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

  // ── Render: idle / confirming / loading phase ──
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
