/**
 * Timezone helpers — wall-clock math against an IANA zone using only `Intl`.
 *
 * No date library dependency. Every function that returns an "instant" (a
 * moment in time) returns a plain `Date`, whose `.getTime()`/`.toISOString()`
 * are always UTC — `Date` itself has no concept of a zone. Zone-awareness
 * only exists in how we *compute* those instants (reading/writing wall-clock
 * parts through `Intl.DateTimeFormat` with a `timeZone`).
 *
 * DST-safety: `zonedTimeToUtc` resolves the UTC instant for a given wall-clock
 * date by computing the zone offset twice (before and after an initial
 * guess) so a DST transition landing exactly on the requested time is still
 * resolved correctly.
 */

export const DEFAULT_TIMEZONE = 'America/Argentina/Buenos_Aires'

export interface ZonedDateParts {
  year: number
  month: number // 1-12
  day: number
  hour: number // 0-23
  minute: number
  second: number
}

export interface ZonedCalendarDate {
  year: number
  month: number // 1-12
  day: number
}

const formatterCache = new Map<string, Intl.DateTimeFormat>()

function getFormatter(timeZone: string, options: Intl.DateTimeFormatOptions, locale = 'es-AR'): Intl.DateTimeFormat {
  const key = `${locale}|${timeZone}|${JSON.stringify(options)}`
  let formatter = formatterCache.get(key)
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(locale, { ...options, timeZone })
    formatterCache.set(key, formatter)
  }
  return formatter
}

function isValidTimeZone(timeZone: string): boolean {
  try {
    new Intl.DateTimeFormat(undefined, { timeZone })
    return true
  } catch {
    return false
  }
}

/**
 * Resolves the timezone to use: the client's configured zone if valid,
 * falling back to the browser's zone, falling back to `DEFAULT_TIMEZONE`.
 */
export function resolveTimezone(clientTimezone?: string | null): string {
  if (clientTimezone && isValidTimeZone(clientTimezone)) return clientTimezone
  const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  if (isValidTimeZone(browserTimezone)) return browserTimezone
  return DEFAULT_TIMEZONE
}

/** Reads the wall-clock year/month/day/hour/minute/second of `instant` in `timeZone`. */
export function getZonedDateParts(instant: Date, timeZone: string): ZonedDateParts {
  const formatter = getFormatter(timeZone, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  })
  const map: Record<string, string> = {}
  for (const part of formatter.formatToParts(instant)) {
    if (part.type !== 'literal') map[part.type] = part.value
  }
  return {
    year: Number(map.year),
    month: Number(map.month),
    day: Number(map.day),
    hour: Number(map.hour),
    minute: Number(map.minute),
    second: Number(map.second),
  }
}

/** `YYYY-MM-DD` wall-clock day key for `instant` in `timeZone`. Stable for grouping/comparison. */
export function zonedDayKey(instant: Date, timeZone: string): string {
  const p = getZonedDateParts(instant, timeZone)
  return `${p.year}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')}`
}

function timeZoneOffsetMs(instant: Date, timeZone: string): number {
  const p = getZonedDateParts(instant, timeZone)
  const asUTC = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second)
  return asUTC - instant.getTime()
}

/**
 * Resolves the UTC instant for a given wall-clock date/time in `timeZone`.
 * Missing time fields default to `0` (start of day).
 */
export function zonedTimeToUtc(
  parts: ZonedCalendarDate & Partial<Pick<ZonedDateParts, 'hour' | 'minute' | 'second'>>,
  timeZone: string,
): Date {
  const { year, month, day, hour = 0, minute = 0, second = 0 } = parts
  const guess = Date.UTC(year, month - 1, day, hour, minute, second)
  const offset1 = timeZoneOffsetMs(new Date(guess), timeZone)
  const candidate = guess - offset1
  const offset2 = timeZoneOffsetMs(new Date(candidate), timeZone)
  return new Date(offset2 === offset1 ? candidate : guess - offset2)
}

/** Shifts a calendar date by `days` (may be negative). Pure calendar math, zone-independent. */
export function shiftZonedDay(date: ZonedCalendarDate, days: number): ZonedCalendarDate {
  const d = new Date(Date.UTC(date.year, date.month - 1, date.day + days))
  return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() }
}

/** UTC instant of `00:00:00` on `instant`'s wall-clock day in `timeZone`. */
export function startOfDayInZone(instant: Date, timeZone: string): Date {
  const p = getZonedDateParts(instant, timeZone)
  return zonedTimeToUtc({ year: p.year, month: p.month, day: p.day }, timeZone)
}

/** UTC instant of the last millisecond of `instant`'s wall-clock day in `timeZone`. */
export function endOfDayInZone(instant: Date, timeZone: string): Date {
  const p = getZonedDateParts(instant, timeZone)
  const nextDay = shiftZonedDay({ year: p.year, month: p.month, day: p.day }, 1)
  const nextDayStart = zonedTimeToUtc(nextDay, timeZone)
  return new Date(nextDayStart.getTime() - 1)
}

/** UTC instant of the Monday `00:00:00` of `instant`'s wall-clock week in `timeZone`. */
export function startOfWeekInZone(instant: Date, timeZone: string): Date {
  const p = getZonedDateParts(instant, timeZone)
  const weekday = new Date(Date.UTC(p.year, p.month - 1, p.day)).getUTCDay() // 0 = Sunday
  const mondayOffset = (weekday + 6) % 7
  return zonedTimeToUtc(shiftZonedDay(p, -mondayOffset), timeZone)
}

/** Calendar-day distance between two `YYYY-MM-DD` dates (zone-independent, no DST math). */
export function calendarDaysBetween(from: ZonedCalendarDate, to: ZonedCalendarDate): number {
  const MS_DAY = 24 * 60 * 60 * 1000
  const fromUTC = Date.UTC(from.year, from.month - 1, from.day)
  const toUTC = Date.UTC(to.year, to.month - 1, to.day)
  return Math.round((toUTC - fromUTC) / MS_DAY)
}

/** Memoized `Intl.DateTimeFormat` factory pinned to `timeZone` (default locale `es-AR`). */
export function createZonedFormatter(timeZone: string, options: Intl.DateTimeFormatOptions, locale = 'es-AR'): Intl.DateTimeFormat {
  return getFormatter(timeZone, options, locale)
}
