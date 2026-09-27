/**
 * bucketCallSessions — pure client-side bucket derivation for the
 * "Volumen de llamadas" chart.
 *
 * The metrics endpoint has no time series, so buckets are derived from the
 * full call session list (GET /api/v1/calls?client_id=...), which the backend
 * returns unpaginated and ordered by started_at descending. Sessions without
 * started_at (never actually rang) are excluded from bucketing.
 *
 * All bucketing (which day/hour/week a call falls into) and axis labels are
 * computed in the client's configured timezone, not UTC.
 */

import type { CallSession } from '@/api/types'
import {
  DEFAULT_TIMEZONE,
  createZonedFormatter,
  getZonedDateParts,
  zonedDayKey,
  zonedTimeToUtc,
  shiftZonedDay,
  startOfWeekInZone,
  calendarDaysBetween,
  type ZonedCalendarDate,
} from '@/lib/timezone'

export type Period = 'today' | '7d' | '30d' | 'all'

export interface ChartBucket {
  t: number
  c: number
  a: number
}

export interface ChartSeries {
  series: ChartBucket[]
  axis: string[]
  unit: string
}

function emptyBucket(): ChartBucket {
  return { t: 0, c: 0, a: 0 }
}

function addToBucket(bucket: ChartBucket, session: CallSession): void {
  bucket.t += 1
  if (session.status === 'completed') bucket.c += 1
  if (session.status === 'abandoned') bucket.a += 1
}

/** Midday instant for a calendar date — safely inside the day for axis-label formatting, DST-proof. */
function middayInstant(date: ZonedCalendarDate, tz: string): Date {
  return zonedTimeToUtc({ ...date, hour: 12 }, tz)
}

function bucketToday(started: CallSession[], now: Date, tz: string): ChartSeries {
  const todayKey = zonedDayKey(now, tz)
  const buckets: ChartBucket[] = Array.from({ length: 24 }, emptyBucket)
  for (const s of started) {
    const instant = new Date(s.started_at as string)
    const parts = getZonedDateParts(instant, tz)
    const dayKey = `${parts.year}-${String(parts.month).padStart(2, '0')}-${String(parts.day).padStart(2, '0')}`
    if (dayKey !== todayKey) continue
    addToBucket(buckets[parts.hour], s)
  }
  return { series: buckets, axis: ['00', '04', '08', '12', '16', '20'], unit: 'hora' }
}

function bucketDays(started: CallSession[], now: Date, days: number, tz: string): ChartSeries {
  const todayParts = getZonedDateParts(now, tz)
  const today: ZonedCalendarDate = { year: todayParts.year, month: todayParts.month, day: todayParts.day }
  const rangeStart = shiftZonedDay(today, -(days - 1))
  const buckets: ChartBucket[] = Array.from({ length: days }, emptyBucket)

  for (const s of started) {
    const instant = new Date(s.started_at as string)
    const parts = getZonedDateParts(instant, tz)
    const sessionDay: ZonedCalendarDate = { year: parts.year, month: parts.month, day: parts.day }
    const dayIndex = calendarDaysBetween(rangeStart, sessionDay)
    if (dayIndex < 0 || dayIndex >= days) continue
    addToBucket(buckets[dayIndex], s)
  }

  const axis: string[] = []
  if (days === 7) {
    const weekdayFmt = createZonedFormatter(tz, { weekday: 'short' })
    for (let i = 0; i < days; i++) {
      axis.push(weekdayFmt.format(middayInstant(shiftZonedDay(rangeStart, i), tz)))
    }
  } else {
    const dayMonthFmt = createZonedFormatter(tz, { day: 'numeric', month: 'short' })
    for (let i = 0; i < days; i += 7) {
      axis.push(dayMonthFmt.format(middayInstant(shiftZonedDay(rangeStart, i), tz)))
    }
  }
  return { series: buckets, axis, unit: 'día' }
}

function bucketAll(started: CallSession[], now: Date, tz: string): ChartSeries {
  if (started.length === 0) {
    return { series: [], axis: [], unit: 'semana' }
  }

  const earliest = Math.min(...started.map((s) => new Date(s.started_at as string).getTime()))
  const firstWeekStart = startOfWeekInZone(new Date(earliest), tz)
  const lastWeekStart = startOfWeekInZone(now, tz)
  const firstWeekDay = getZonedDateParts(firstWeekStart, tz)
  const lastWeekDay = getZonedDateParts(lastWeekStart, tz)
  const weekCount = Math.round(
    calendarDaysBetween(
      { year: firstWeekDay.year, month: firstWeekDay.month, day: firstWeekDay.day },
      { year: lastWeekDay.year, month: lastWeekDay.month, day: lastWeekDay.day },
    ) / 7,
  ) + 1
  const buckets: ChartBucket[] = Array.from({ length: weekCount }, emptyBucket)
  const rangeStart: ZonedCalendarDate = { year: firstWeekDay.year, month: firstWeekDay.month, day: firstWeekDay.day }

  for (const s of started) {
    const instant = new Date(s.started_at as string)
    const weekStart = startOfWeekInZone(instant, tz)
    const weekDay = getZonedDateParts(weekStart, tz)
    const weekIndex = Math.round(
      calendarDaysBetween(rangeStart, { year: weekDay.year, month: weekDay.month, day: weekDay.day }) / 7,
    )
    if (weekIndex < 0 || weekIndex >= weekCount) continue
    addToBucket(buckets[weekIndex], s)
  }

  const monthFmt = createZonedFormatter(tz, { month: 'short' })
  const sampleCount = Math.min(5, weekCount)
  const axis: string[] = []
  for (let i = 0; i < sampleCount; i++) {
    const idx = sampleCount === 1 ? 0 : Math.round((i * (weekCount - 1)) / (sampleCount - 1))
    axis.push(monthFmt.format(middayInstant(shiftZonedDay(rangeStart, idx * 7), tz)))
  }
  return { series: buckets, axis, unit: 'semana' }
}

export function bucketCallSessions(
  sessions: CallSession[],
  period: Period,
  now: Date = new Date(),
  tz: string = DEFAULT_TIMEZONE,
): ChartSeries {
  const started = sessions.filter((s) => Boolean(s.started_at))

  if (period === 'today') return bucketToday(started, now, tz)
  if (period === '7d') return bucketDays(started, now, 7, tz)
  if (period === '30d') return bucketDays(started, now, 30, tz)
  return bucketAll(started, now, tz)
}
