/**
 * bucketCallSessions — pure unit tests (no rendering, no mocks)
 */

import { describe, it, expect } from 'vitest'
import { bucketCallSessions } from './chart-buckets'
import type { CallSession } from '@/api/types'

function session(overrides: Partial<CallSession>): CallSession {
  return {
    id: 's1',
    client_id: 'demo-client',
    lead_id: 'lead-1',
    status: 'completed',
    started_at: null,
    ended_at: null,
    duration_seconds: null,
    summary: null,
    outcome: null,
    closed_reason: null,
    billable_minutes: null,
    total_user_turns: null,
    total_agent_turns: null,
    extracted_facts: null,
    ...overrides,
  }
}

const NOW = new Date('2026-06-15T18:00:00.000Z')
const UTC = 'UTC'

describe('bucketCallSessions — "today"', () => {
  it('returns 24 hourly buckets with unit "hora"', () => {
    const result = bucketCallSessions([], 'today', NOW, UTC)
    expect(result.series).toHaveLength(24)
    expect(result.unit).toBe('hora')
  })

  it('places a completed call in the correct UTC hour bucket', () => {
    const sessions = [session({ started_at: '2026-06-15T09:30:00.000Z', status: 'completed' })]
    const result = bucketCallSessions(sessions, 'today', NOW, UTC)
    expect(result.series[9]).toEqual({ t: 1, c: 1, a: 0 })
  })

  it('excludes sessions from a different day', () => {
    const sessions = [session({ started_at: '2026-06-14T09:30:00.000Z', status: 'completed' })]
    const result = bucketCallSessions(sessions, 'today', NOW, UTC)
    expect(result.series.every((b) => b.t === 0)).toBe(true)
  })

  it('excludes sessions with no started_at', () => {
    const sessions = [session({ started_at: null, status: 'completed' })]
    const result = bucketCallSessions(sessions, 'today', NOW, UTC)
    expect(result.series.every((b) => b.t === 0)).toBe(true)
  })

  it('shifts the hour bucket into the client timezone (Buenos Aires, UTC-3)', () => {
    // 09:30 UTC is 06:30 in Buenos Aires — same wall-clock day, hour 6
    const sessions = [session({ started_at: '2026-06-15T09:30:00.000Z', status: 'completed' })]
    const result = bucketCallSessions(sessions, 'today', NOW, 'America/Argentina/Buenos_Aires')
    expect(result.series[6]).toEqual({ t: 1, c: 1, a: 0 })
  })

  it('excludes a call that is "today" in UTC but still "yesterday" in Buenos Aires', () => {
    // 2026-06-15T02:00:00Z is 2026-06-14T23:00 in Buenos Aires — a different wall-clock day
    const sessions = [session({ started_at: '2026-06-15T02:00:00.000Z', status: 'completed' })]
    const result = bucketCallSessions(sessions, 'today', NOW, 'America/Argentina/Buenos_Aires')
    expect(result.series.every((b) => b.t === 0)).toBe(true)
  })
})

describe('bucketCallSessions — "7d"', () => {
  it('returns 7 daily buckets with unit "día"', () => {
    const result = bucketCallSessions([], '7d', NOW, UTC)
    expect(result.series).toHaveLength(7)
    expect(result.axis).toHaveLength(7)
    expect(result.unit).toBe('día')
  })

  it('buckets an abandoned call into the correct day, oldest-first order', () => {
    // NOW is 2026-06-15; 6 days back is 2026-06-09 (bucket index 0, oldest)
    const sessions = [session({ started_at: '2026-06-09T05:00:00.000Z', status: 'abandoned' })]
    const result = bucketCallSessions(sessions, '7d', NOW, UTC)
    expect(result.series[0]).toEqual({ t: 1, c: 0, a: 1 })
    expect(result.series[6]).toEqual({ t: 0, c: 0, a: 0 })
  })

  it('counts calls with a non-completed/abandoned status toward total only', () => {
    const sessions = [session({ started_at: NOW.toISOString(), status: 'in_progress' })]
    const result = bucketCallSessions(sessions, '7d', NOW, UTC)
    expect(result.series[6]).toEqual({ t: 1, c: 0, a: 0 })
  })

  it('buckets by calendar day in a DST-transitioning zone (Europe/Madrid)', () => {
    // 2026-10-25T23:30Z is 2026-10-26T00:30 in Madrid (post fall-back, UTC+1) — the last bucket day
    const sessions = [session({ started_at: '2026-10-25T23:30:00.000Z', status: 'completed' })]
    const now = new Date('2026-10-26T12:00:00.000Z')
    const result = bucketCallSessions(sessions, '7d', now, 'Europe/Madrid')
    expect(result.series[6]).toEqual({ t: 1, c: 1, a: 0 })
  })
})

describe('bucketCallSessions — "30d"', () => {
  it('returns 30 daily buckets with unit "día"', () => {
    const result = bucketCallSessions([], '30d', NOW, UTC)
    expect(result.series).toHaveLength(30)
    expect(result.unit).toBe('día')
  })

  it('samples axis labels every 7 days', () => {
    const result = bucketCallSessions([], '30d', NOW, UTC)
    expect(result.axis).toHaveLength(5)
  })
})

describe('bucketCallSessions — "all"', () => {
  it('returns empty series and axis when there are no sessions with started_at', () => {
    const result = bucketCallSessions([session({ started_at: null })], 'all', NOW, UTC)
    expect(result.series).toEqual([])
    expect(result.axis).toEqual([])
    expect(result.unit).toBe('semana')
  })

  it('buckets sessions by week from the earliest session to now', () => {
    const sessions = [
      session({ started_at: '2026-05-01T00:00:00.000Z', status: 'completed' }),
      session({ started_at: NOW.toISOString(), status: 'abandoned' }),
    ]
    const result = bucketCallSessions(sessions, 'all', NOW, UTC)
    expect(result.series[0].c).toBe(1)
    expect(result.series[result.series.length - 1].a).toBe(1)
  })

  it('caps axis at 5 sampled labels for long ranges', () => {
    const sessions = [
      session({ started_at: '2025-01-01T00:00:00.000Z', status: 'completed' }),
      session({ started_at: NOW.toISOString(), status: 'completed' }),
    ]
    const result = bucketCallSessions(sessions, 'all', NOW, UTC)
    expect(result.axis.length).toBeLessThanOrEqual(5)
  })
})

describe('bucketCallSessions — default timezone', () => {
  it('defaults to Buenos Aires when no timezone is passed', () => {
    // 09:30 UTC is 06:30 in Buenos Aires — bucket 6, not bucket 9
    const sessions = [session({ started_at: '2026-06-15T09:30:00.000Z', status: 'completed' })]
    const result = bucketCallSessions(sessions, 'today', NOW)
    expect(result.series[6]).toEqual({ t: 1, c: 1, a: 0 })
  })
})
