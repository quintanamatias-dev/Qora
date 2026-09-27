import { describe, it, expect } from 'vitest'
import {
  DEFAULT_TIMEZONE,
  resolveTimezone,
  getZonedDateParts,
  zonedDayKey,
  zonedTimeToUtc,
  shiftZonedDay,
  startOfDayInZone,
  endOfDayInZone,
  startOfWeekInZone,
  calendarDaysBetween,
} from './timezone'

describe('resolveTimezone', () => {
  it('returns the client timezone when valid', () => {
    expect(resolveTimezone('America/New_York')).toBe('America/New_York')
  })

  it('falls back to the browser timezone when the client timezone is invalid', () => {
    const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone
    expect(resolveTimezone('Not/A_Zone')).toBe(browserTz)
  })

  it('falls back to DEFAULT_TIMEZONE when no client timezone is provided', () => {
    const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone
    expect(resolveTimezone(undefined)).toBe(browserTz || DEFAULT_TIMEZONE)
  })

  it('falls back to DEFAULT_TIMEZONE when client timezone is null', () => {
    const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone
    expect(resolveTimezone(null)).toBe(browserTz || DEFAULT_TIMEZONE)
  })
})

describe('getZonedDateParts', () => {
  it('reads Buenos Aires wall-clock time (UTC-3, no DST)', () => {
    const instant = new Date('2026-06-15T09:30:00.000Z')
    const parts = getZonedDateParts(instant, 'America/Argentina/Buenos_Aires')
    expect(parts).toEqual({ year: 2026, month: 6, day: 15, hour: 6, minute: 30, second: 0 })
  })

  it('reads New York wall-clock time during DST (UTC-4 in July)', () => {
    const instant = new Date('2026-07-15T12:00:00.000Z')
    const parts = getZonedDateParts(instant, 'America/New_York')
    expect(parts.hour).toBe(8)
  })

  it('reads New York wall-clock time outside DST (UTC-5 in January)', () => {
    const instant = new Date('2026-01-15T12:00:00.000Z')
    const parts = getZonedDateParts(instant, 'America/New_York')
    expect(parts.hour).toBe(7)
  })
})

describe('zonedDayKey', () => {
  it('rolls over to the previous calendar day west of UTC late at night', () => {
    // 2026-06-16T02:00:00Z is still 2026-06-15 23:00 in Buenos Aires (UTC-3)
    const instant = new Date('2026-06-16T02:00:00.000Z')
    expect(zonedDayKey(instant, 'America/Argentina/Buenos_Aires')).toBe('2026-06-15')
  })
})

describe('zonedTimeToUtc', () => {
  it('resolves the UTC instant for a wall-clock date in Buenos Aires', () => {
    const instant = zonedTimeToUtc({ year: 2026, month: 6, day: 15 }, 'America/Argentina/Buenos_Aires')
    expect(instant.toISOString()).toBe('2026-06-15T03:00:00.000Z')
  })

  it('resolves correctly across the US DST spring-forward boundary', () => {
    // 2026-03-08 is the US spring-forward date; midnight is still EST (UTC-5)
    const instant = zonedTimeToUtc({ year: 2026, month: 3, day: 8 }, 'America/New_York')
    expect(instant.toISOString()).toBe('2026-03-08T05:00:00.000Z')
  })

  it('resolves correctly across the Europe/Madrid DST fall-back boundary', () => {
    const instant = zonedTimeToUtc({ year: 2026, month: 10, day: 25 }, 'Europe/Madrid')
    expect(instant.toISOString()).toBe('2026-10-24T22:00:00.000Z')
  })
})

describe('shiftZonedDay', () => {
  it('advances across a month boundary', () => {
    expect(shiftZonedDay({ year: 2026, month: 1, day: 31 }, 1)).toEqual({ year: 2026, month: 2, day: 1 })
  })

  it('goes back across a year boundary', () => {
    expect(shiftZonedDay({ year: 2026, month: 1, day: 1 }, -1)).toEqual({ year: 2025, month: 12, day: 31 })
  })
})

describe('startOfDayInZone / endOfDayInZone', () => {
  it('computes start-of-day for Buenos Aires (fixed UTC-3)', () => {
    const instant = new Date('2026-06-15T18:00:00.000Z')
    const start = startOfDayInZone(instant, 'America/Argentina/Buenos_Aires')
    expect(start.toISOString()).toBe('2026-06-15T03:00:00.000Z')
  })

  it('computes end-of-day one millisecond before the next start-of-day', () => {
    const instant = new Date('2026-06-15T18:00:00.000Z')
    const tz = 'America/Argentina/Buenos_Aires'
    const end = endOfDayInZone(instant, tz)
    expect(end.toISOString()).toBe('2026-06-16T02:59:59.999Z')
  })

  it('spans the correct wall-clock day across a DST spring-forward (New York, 23 hours)', () => {
    const instant = new Date('2026-03-08T12:00:00.000Z')
    const start = startOfDayInZone(instant, 'America/New_York')
    const end = endOfDayInZone(instant, 'America/New_York')
    expect(end.getTime() - start.getTime()).toBe(23 * 60 * 60 * 1000 - 1)
  })

  it('spans the correct wall-clock day across a DST fall-back (New York, 25 hours)', () => {
    const instant = new Date('2026-11-01T12:00:00.000Z')
    const start = startOfDayInZone(instant, 'America/New_York')
    const end = endOfDayInZone(instant, 'America/New_York')
    expect(end.getTime() - start.getTime()).toBe(25 * 60 * 60 * 1000 - 1)
  })
})

describe('startOfWeekInZone', () => {
  it('resolves the Monday start of the week in Buenos Aires', () => {
    // 2026-06-15 is a Monday
    const instant = new Date('2026-06-17T18:00:00.000Z') // Wednesday
    const monday = startOfWeekInZone(instant, 'America/Argentina/Buenos_Aires')
    expect(zonedDayKey(monday, 'America/Argentina/Buenos_Aires')).toBe('2026-06-15')
  })
})

describe('calendarDaysBetween', () => {
  it('counts whole days between two calendar dates', () => {
    expect(calendarDaysBetween({ year: 2026, month: 6, day: 9 }, { year: 2026, month: 6, day: 15 })).toBe(6)
  })

  it('returns a negative count when `to` is before `from`', () => {
    expect(calendarDaysBetween({ year: 2026, month: 6, day: 15 }, { year: 2026, month: 6, day: 9 })).toBe(-6)
  })
})
