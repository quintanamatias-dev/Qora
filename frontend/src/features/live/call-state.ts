/**
 * Pure state-mapping logic for the "en vivo" live canvas.
 *
 * Kept free of React/canvas concerns so it can be unit-tested in isolation:
 * turns raw API call rows into canvas-ready call states (dial/talk/end) and
 * detects newly-arrived facts for the memory-particle animation.
 */

import type { LiveCall, LiveRecentFact } from '@/api/live'

export type CanvasCallState = 'dial' | 'talk' | 'end'

export interface CanvasCall {
  sessionId: string
  agentId: string | null
  leadFirstName: string | null
  telephonyStatus: LiveCall['telephony_status']
  state: CanvasCallState
  /** Timestamp (ms) this call entered its current state — drives animation. */
  since: number
}

/** telephony_status values shown as an active "talking" line on the canvas. */
const TALK_STATUSES: ReadonlyArray<LiveCall['telephony_status']> = ['connected']

/** How long an "end" call is kept around (for the fade-out) before it can be pruned. */
export const END_FADE_GRACE_MS = 1500

function statusToCanvasState(status: LiveCall['telephony_status']): 'dial' | 'talk' {
  return TALK_STATUSES.includes(status) ? 'talk' : 'dial'
}

/**
 * Reconcile the previous canvas call list against the latest API poll.
 *
 * - New sessions enter as 'dial' or 'talk' (since = now).
 * - Sessions still present keep their identity; 'since' only resets when
 *   their canvas state actually changes (e.g. dial → talk).
 * - Sessions no longer present transition to 'end' (since = now) so the
 *   caller can render a fade-out instead of an abrupt disappearance.
 * - Sessions already 'end' are dropped once END_FADE_GRACE_MS has elapsed.
 */
export function reconcileCanvasCalls(
  previous: CanvasCall[],
  apiCalls: LiveCall[],
  now: number,
): CanvasCall[] {
  const alive = previous.filter((c) => c.state !== 'end' || now - c.since < END_FADE_GRACE_MS)
  const previousById = new Map(alive.map((c) => [c.sessionId, c]))
  const seenIds = new Set<string>()
  const next: CanvasCall[] = []

  for (const api of apiCalls) {
    seenIds.add(api.session_id)
    const state = statusToCanvasState(api.telephony_status)
    const prevCall = previousById.get(api.session_id)
    if (prevCall && prevCall.state === state) {
      next.push({ ...prevCall, telephonyStatus: api.telephony_status })
    } else {
      next.push({
        sessionId: api.session_id,
        agentId: api.agent_id,
        leadFirstName: api.lead_first_name,
        telephonyStatus: api.telephony_status,
        state,
        since: now,
      })
    }
  }

  for (const c of alive) {
    if (seenIds.has(c.sessionId)) continue
    next.push(c.state === 'end' ? c : { ...c, state: 'end', since: now })
  }

  return next
}

/** Stable identity for a recent fact — no server-side id/timestamp is exposed. */
function factSignature(fact: LiveRecentFact): string {
  return `${fact.text}|${fact.lead_first_name ?? ''}|${fact.duration_seconds ?? ''}`
}

/**
 * Detect which recent facts are new since the last poll (by signature).
 * Returns the new facts (feed order preserved) and the updated seen-set.
 */
export function detectNewFacts(
  seen: ReadonlySet<string>,
  recentFacts: LiveRecentFact[],
): { newFacts: LiveRecentFact[]; seen: Set<string> } {
  const nextSeen = new Set(seen)
  const newFacts: LiveRecentFact[] = []
  for (const fact of recentFacts) {
    const sig = factSignature(fact)
    if (!nextSeen.has(sig)) {
      newFacts.push(fact)
      nextSeen.add(sig)
    }
  }
  return { newFacts, seen: nextSeen }
}
