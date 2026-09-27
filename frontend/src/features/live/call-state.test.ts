import { describe, it, expect } from 'vitest'
import { reconcileCanvasCalls, detectNewFacts, END_FADE_GRACE_MS } from './call-state'
import type { LiveCall, LiveRecentFact } from '@/api/live'

function call(overrides: Partial<LiveCall> = {}): LiveCall {
  return {
    session_id: 's1',
    lead_id: 'lead-1',
    lead_first_name: 'Lucia',
    agent_id: 'agent-1',
    agent_name: 'Juanma',
    telephony_status: 'connected',
    started_at: '2026-01-15T09:58:00Z',
    ...overrides,
  }
}

describe('reconcileCanvasCalls', () => {
  it('maps queued/dialing/ringing to dial and connected to talk', () => {
    const now = 1000
    const result = reconcileCanvasCalls(
      [],
      [
        call({ session_id: 'a', telephony_status: 'queued' }),
        call({ session_id: 'b', telephony_status: 'dialing' }),
        call({ session_id: 'c', telephony_status: 'ringing' }),
        call({ session_id: 'd', telephony_status: 'connected' }),
      ],
      now,
    )
    expect(result.find((c) => c.sessionId === 'a')?.state).toBe('dial')
    expect(result.find((c) => c.sessionId === 'b')?.state).toBe('dial')
    expect(result.find((c) => c.sessionId === 'c')?.state).toBe('dial')
    expect(result.find((c) => c.sessionId === 'd')?.state).toBe('talk')
  })

  it('preserves "since" when a call keeps the same canvas state across polls', () => {
    const first = reconcileCanvasCalls([], [call({ telephony_status: 'connected' })], 1000)
    const second = reconcileCanvasCalls(first, [call({ telephony_status: 'connected' })], 5000)
    expect(second[0].since).toBe(1000)
  })

  it('resets "since" when a call transitions dial -> talk', () => {
    const first = reconcileCanvasCalls([], [call({ telephony_status: 'dialing' })], 1000)
    const second = reconcileCanvasCalls(first, [call({ telephony_status: 'connected' })], 5000)
    expect(second[0].state).toBe('talk')
    expect(second[0].since).toBe(5000)
  })

  it('transitions a disappeared call to "end" instead of dropping it immediately', () => {
    const first = reconcileCanvasCalls([], [call({ session_id: 'gone' })], 1000)
    const second = reconcileCanvasCalls(first, [], 2000)
    expect(second).toHaveLength(1)
    expect(second[0].state).toBe('end')
    expect(second[0].since).toBe(2000)
  })

  it('drops an "end" call once the fade grace period has elapsed', () => {
    const withEnd = reconcileCanvasCalls(
      reconcileCanvasCalls([], [call({ session_id: 'gone' })], 1000),
      [],
      2000,
    )
    const pruned = reconcileCanvasCalls(withEnd, [], 2000 + END_FADE_GRACE_MS + 1)
    expect(pruned).toHaveLength(0)
  })

  it('keeps an "end" call within the fade grace period', () => {
    const withEnd = reconcileCanvasCalls(
      reconcileCanvasCalls([], [call({ session_id: 'gone' })], 1000),
      [],
      2000,
    )
    const stillThere = reconcileCanvasCalls(withEnd, [], 2000 + END_FADE_GRACE_MS - 1)
    expect(stillThere).toHaveLength(1)
    expect(stillThere[0].state).toBe('end')
  })
})

describe('detectNewFacts', () => {
  function fact(overrides: Partial<LiveRecentFact> = {}): LiveRecentFact {
    return { text: 'Prefiere WhatsApp', lead_first_name: 'Lucia', duration_seconds: 160, ...overrides }
  }

  it('reports all facts as new against an empty seen set', () => {
    const { newFacts, seen } = detectNewFacts(new Set(), [fact()])
    expect(newFacts).toHaveLength(1)
    expect(seen.size).toBe(1)
  })

  it('does not re-report a fact already in the seen set', () => {
    const { seen } = detectNewFacts(new Set(), [fact()])
    const { newFacts } = detectNewFacts(seen, [fact()])
    expect(newFacts).toHaveLength(0)
  })

  it('reports only the genuinely new fact when one of two was already seen', () => {
    const { seen } = detectNewFacts(new Set(), [fact()])
    const { newFacts } = detectNewFacts(seen, [fact(), fact({ text: 'Vive en Recoleta' })])
    expect(newFacts).toHaveLength(1)
    expect(newFacts[0].text).toBe('Vive en Recoleta')
  })
})
