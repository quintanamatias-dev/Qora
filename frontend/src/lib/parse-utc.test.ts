/**
 * parse-utc — Unit tests
 *
 * parseUTC ensures ISO date strings from the backend (Python isoformat,
 * no Z suffix) are interpreted as UTC by the browser.
 */

import { describe, it, expect } from 'vitest'
import { parseUTC } from './parse-utc'

describe('parseUTC — no timezone indicator', () => {
  it('appends Z to a bare ISO string', () => {
    const d = parseUTC('2026-07-05T02:32:00')
    // Should be parsed as UTC — getUTCHours returns 2
    expect(d.getUTCHours()).toBe(2)
    expect(d.getUTCMinutes()).toBe(32)
  })

  it('handles microsecond precision from Python', () => {
    const d = parseUTC('2026-07-05T02:32:00.110680')
    expect(d.getUTCHours()).toBe(2)
    expect(d.getUTCFullYear()).toBe(2026)
  })

  it('returns a valid Date object', () => {
    const d = parseUTC('2026-01-15T10:30:00')
    expect(d).toBeInstanceOf(Date)
    expect(isNaN(d.getTime())).toBe(false)
  })
})

describe('parseUTC — already has timezone info', () => {
  it('passes through Z suffix unchanged', () => {
    const d = parseUTC('2026-07-05T02:32:00Z')
    expect(d.getUTCHours()).toBe(2)
  })

  it('passes through lowercase z suffix', () => {
    const d = parseUTC('2026-07-05T02:32:00z')
    expect(d.getUTCHours()).toBe(2)
  })

  it('passes through positive offset (+HH:MM)', () => {
    // +05:00 means local is 5h ahead of UTC → UTC hour = 10 - 5 = 5
    const d = parseUTC('2026-07-05T10:00:00+05:00')
    expect(d.getUTCHours()).toBe(5)
  })

  it('passes through negative offset (-HH:MM)', () => {
    // -03:00 means local is 3h behind UTC → UTC hour = 10 + 3 = 13
    const d = parseUTC('2026-07-05T10:00:00-03:00')
    expect(d.getUTCHours()).toBe(13)
  })
})

describe('parseUTC — edge cases', () => {
  it('date-only string gets Z appended', () => {
    // Date-only ISO strings: "2026-07-05" has a dash but no time offset
    const d = parseUTC('2026-07-05')
    expect(d).toBeInstanceOf(Date)
    expect(isNaN(d.getTime())).toBe(false)
  })

  it('does not double-append Z', () => {
    const d1 = parseUTC('2026-07-05T02:32:00Z')
    const d2 = parseUTC('2026-07-05T02:32:00Z')
    expect(d1.getTime()).toBe(d2.getTime())
  })
})
