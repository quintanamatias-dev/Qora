/**
 * useCallPolling — React hook for polling call telephony status.
 *
 * Spec: call-now-feedback — Requirement: Polling Lifecycle After Trigger
 *   - Start polling after POST /call returns call_session_id
 *   - Poll GET /calls/{id}/status every 3 seconds
 *   - Stop when is_terminal=true or when the component unmounts
 *   - Stop after 180 seconds (honest timeout)
 *   - Gracefully handle 429 rate limit responses (skip, don't crash)
 *
 * Spec: call-now-feedback — Requirement: Real State Badges
 *   Returns telephony_status as a string for the calling component to render.
 *
 * Spec: call-now-feedback — Requirement: Honest Timeout
 *   After 180s with no terminal state, sets timedOut=true and stops polling.
 */

import { useEffect, useRef, useState } from 'react'
import type { TelephonyStatus } from '@/api/types'
import { getCallStatus } from '@/api/leads'
import { ApiError } from '@/api/client'

// Polling interval in milliseconds — every 3 seconds.
// Spec: call-now-feedback — Requirement: Polling Lifecycle After Trigger.
const POLL_INTERVAL_MS = 3_000

// Maximum polling duration before declaring a timeout.
// Spec: call-now-feedback — Requirement: Honest Timeout (180s).
const MAX_POLL_DURATION_MS = 180_000

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

export type PollingState =
  | { status: 'polling'; telephonyStatus: TelephonyStatus }
  | { status: 'terminal'; telephonyStatus: TelephonyStatus; outcomeReason: string | null }
  | { status: 'timedOut' }
  | { status: 'error'; message: string }

// ──────────────────────────────────────────────────────────────────────────────
// Hook
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Poll GET /api/v1/calls/{sessionId}/status every 3 seconds.
 *
 * Usage:
 *   const pollingState = useCallPolling(callSessionId)
 *   // pollingState.status: 'polling' | 'terminal' | 'timedOut' | 'error'
 *
 * Returns null when sessionId is null (no active session — polling inactive).
 *
 * @param sessionId - The call_session_id returned from POST /call. Pass null to disable.
 */
export function useCallPolling(sessionId: string | null): PollingState | null {
  const [pollingState, setPollingState] = useState<PollingState | null>(null)

  // Mutable refs for interval and timeout handles — never trigger re-renders.
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isMountedRef = useRef(true)

  const stopPolling = () => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
  }

  useEffect(() => {
    isMountedRef.current = true

    if (!sessionId) {
      setPollingState(null)
      return
    }

    // Start polling immediately (first tick runs without waiting 3s).
    const poll = async () => {
      try {
        const result = await getCallStatus(sessionId)

        if (!isMountedRef.current) return

        if (result.is_terminal) {
          stopPolling()
          setPollingState({
            status: 'terminal',
            telephonyStatus: result.telephony_status,
            outcomeReason: result.outcome_reason,
          })
        } else {
          setPollingState({
            status: 'polling',
            telephonyStatus: result.telephony_status,
          })
        }
      } catch (err) {
        if (!isMountedRef.current) return

        // 429 rate limit — skip this tick, don't crash the polling loop.
        if (err instanceof ApiError && err.status === 429) {
          return
        }

        // Any other error: surface it and stop polling.
        stopPolling()
        const message = err instanceof Error ? err.message : 'Unknown polling error'
        setPollingState({ status: 'error', message })
      }
    }

    // Run immediately, then set up the interval.
    void poll()
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS)

    // Set the honest timeout — stops polling after 180s regardless of state.
    timeoutRef.current = setTimeout(() => {
      if (!isMountedRef.current) return
      stopPolling()
      setPollingState({ status: 'timedOut' })
    }, MAX_POLL_DURATION_MS)

    return () => {
      isMountedRef.current = false
      stopPolling()
    }
  }, [sessionId])

  return pollingState
}
