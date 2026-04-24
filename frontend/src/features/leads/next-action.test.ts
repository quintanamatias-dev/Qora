/**
 * next-action.test.ts — Unit tests for deriveNextAction() and formatRelativeTime()
 *
 * Spec: sdd/qora-crm-next-action/spec — Requirement: Derive Next Action State
 *       + Relative Time Formatting
 * Design: Pure function tests — zero mocks needed (pure functions).
 *
 * TDD Layer: Unit (pure functions, no DOM/RTL needed)
 * TDD: RED phase tasks 2.1 + 2.2 — tests written before implementation
 */

import { describe, it, expect } from 'vitest'
import type { Lead } from '@/api/types'
import { deriveNextAction, formatRelativeTime } from './next-action'

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

/** Build a minimal Lead fixture with required fields, merging overrides. */
function makeLead(overrides: Partial<Lead> = {}): Lead {
  return {
    id: 'lead-test',
    client_id: 'demo-client',
    name: 'Test Lead',
    phone: '+1-555-0000',
    car_make: null,
    car_model: null,
    car_year: null,
    current_insurance: null,
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
    next_action: null,
    next_action_at: null,
    next_scheduled_call_at: null,
    ...overrides,
  }
}

/** ISO string N minutes from now */
function minutesFromNow(n: number): string {
  return new Date(Date.now() + n * 60 * 1000).toISOString()
}

/** ISO string N hours from now */
function hoursFromNow(n: number): string {
  return new Date(Date.now() + n * 60 * 60 * 1000).toISOString()
}

// ──────────────────────────────────────────────────────────────────────────────
// Task 2.1 — deriveNextAction() priority chain
// ──────────────────────────────────────────────────────────────────────────────

describe('deriveNextAction — Priority 1: Closed', () => {
  it('do_not_call=true returns Cerrado/error', () => {
    const lead = makeLead({ do_not_call: true })
    const result = deriveNextAction(lead)
    expect(result.label).toBe('Cerrado')
    expect(result.badge).toBe('error')
  })

  it('status=not_interested returns Cerrado/error', () => {
    const lead = makeLead({ status: 'not_interested', do_not_call: false })
    const result = deriveNextAction(lead)
    expect(result.label).toBe('Cerrado')
    expect(result.badge).toBe('error')
  })

  it('do_not_call=true beats a future scheduled call (closed wins)', () => {
    const lead = makeLead({
      do_not_call: true,
      next_scheduled_call_at: minutesFromNow(30),
    })
    const result = deriveNextAction(lead)
    expect(result.label).toBe('Cerrado')
    expect(result.badge).toBe('error')
  })
})

describe('deriveNextAction — Priority 2: Scheduled future', () => {
  it('future next_scheduled_call_at returns active badge', () => {
    const lead = makeLead({
      next_scheduled_call_at: minutesFromNow(30),
    })
    const result = deriveNextAction(lead)
    expect(result.badge).toBe('active')
    // label is a relative time string — non-empty
    expect(result.label.length).toBeGreaterThan(0)
    // Must NOT be a closed/overdue/sin-agenda/pendiente label
    expect(result.label).not.toBe('Cerrado')
    expect(result.label).not.toBe('Atrasado')
    expect(result.label).not.toBe('Sin agenda')
    expect(result.label).not.toBe('Pendiente')
  })

  it('lead with call_count>0 and future schedule shows active (not sin agenda)', () => {
    const lead = makeLead({
      call_count: 3,
      next_scheduled_call_at: hoursFromNow(2),
    })
    const result = deriveNextAction(lead)
    expect(result.badge).toBe('active')
  })
})

describe('deriveNextAction — Priority 3: Overdue (past scheduled)', () => {
  it('past next_scheduled_call_at returns Atrasado/warning', () => {
    const lead = makeLead({
      next_scheduled_call_at: minutesFromNow(-30),
    })
    const result = deriveNextAction(lead)
    expect(result.label).toBe('Atrasado')
    expect(result.badge).toBe('warning')
  })
})

describe('deriveNextAction — Priority 4: Sin agenda', () => {
  it('call_count>0 with no scheduled call returns Sin agenda/warning', () => {
    const lead = makeLead({
      call_count: 2,
      next_scheduled_call_at: null,
    })
    const result = deriveNextAction(lead)
    expect(result.label).toBe('Sin agenda')
    expect(result.badge).toBe('warning')
  })
})

describe('deriveNextAction — Priority 5: Pendiente (default)', () => {
  it('new lead never contacted returns Pendiente/neutral', () => {
    const lead = makeLead({
      status: 'new',
      call_count: 0,
      next_scheduled_call_at: null,
    })
    const result = deriveNextAction(lead)
    expect(result.label).toBe('Pendiente')
    expect(result.badge).toBe('neutral')
  })

  it('lead with zero calls and no schedule shows Pendiente regardless of status', () => {
    const lead = makeLead({
      status: 'called',
      call_count: 0,
      next_scheduled_call_at: null,
    })
    const result = deriveNextAction(lead)
    expect(result.label).toBe('Pendiente')
    expect(result.badge).toBe('neutral')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Task 2.2 — formatRelativeTime() time band cases
// ──────────────────────────────────────────────────────────────────────────────

describe('formatRelativeTime — < 60 minutes', () => {
  it('30 minutes from now returns "En 30m"', () => {
    const now = new Date('2026-04-23T10:00:00Z')
    const dt = new Date('2026-04-23T10:30:00Z').toISOString()
    const result = formatRelativeTime(dt, now)
    expect(result).toBe('En 30m')
  })

  it('1 minute from now returns "En 1m"', () => {
    const now = new Date('2026-04-23T10:00:00Z')
    const dt = new Date('2026-04-23T10:01:00Z').toISOString()
    const result = formatRelativeTime(dt, now)
    expect(result).toBe('En 1m')
  })

  it('59 minutes from now returns "En 59m"', () => {
    const now = new Date('2026-04-23T10:00:00Z')
    const dt = new Date('2026-04-23T10:59:00Z').toISOString()
    const result = formatRelativeTime(dt, now)
    expect(result).toBe('En 59m')
  })
})

describe('formatRelativeTime — same day, hours away', () => {
  it('2 hours from now returns "En 2h"', () => {
    const now = new Date('2026-04-23T10:00:00Z')
    const dt = new Date('2026-04-23T12:00:00Z').toISOString()
    const result = formatRelativeTime(dt, now)
    expect(result).toBe('En 2h')
  })

  it('exactly 1 hour from now returns "En 1h"', () => {
    const now = new Date('2026-04-23T10:00:00Z')
    const dt = new Date('2026-04-23T11:00:00Z').toISOString()
    const result = formatRelativeTime(dt, now)
    expect(result).toBe('En 1h')
  })
})

describe('formatRelativeTime — tomorrow', () => {
  it('next calendar day starts with "Mañana"', () => {
    const now = new Date('2026-04-23T10:00:00Z')
    const dt = new Date('2026-04-24T09:00:00Z').toISOString()
    const result = formatRelativeTime(dt, now)
    expect(result).toMatch(/^Mañana/)
  })

  it('next calendar day includes HH:MM time', () => {
    const now = new Date('2026-04-23T10:00:00Z')
    const dt = new Date('2026-04-24T15:30:00Z').toISOString()
    const result = formatRelativeTime(dt, now)
    // Must start with "Mañana" and contain time digits
    expect(result).toMatch(/^Mañana \d{2}:\d{2}/)
  })
})

describe('formatRelativeTime — multi-day', () => {
  it('3 days from now returns "En 3 días"', () => {
    const now = new Date('2026-04-23T10:00:00Z')
    const dt = new Date('2026-04-26T10:00:00Z').toISOString()
    const result = formatRelativeTime(dt, now)
    expect(result).toBe('En 3 días')
  })

  it('2 days from now returns "En 2 días"', () => {
    const now = new Date('2026-04-23T10:00:00Z')
    const dt = new Date('2026-04-25T10:00:00Z').toISOString()
    const result = formatRelativeTime(dt, now)
    expect(result).toBe('En 2 días')
  })
})
