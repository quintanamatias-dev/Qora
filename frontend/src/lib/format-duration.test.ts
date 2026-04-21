/**
 * format-duration — Unit tests
 *
 * Spec source of truth: sdd/qora-dashboard-metrics/spec
 * formatDuration(seconds: number): string
 *
 * Rules:
 *   < 3600  → "M:SS"
 *   ≥ 3600  → "Xh Ym"
 *   0 or negative → "0:00"
 */

import { describe, it, expect } from 'vitest'
import { formatDuration } from './format-duration'

describe('formatDuration — sub-hour (M:SS)', () => {
  it('returns "0:00" for 0 seconds', () => {
    expect(formatDuration(0)).toBe('0:00')
  })

  it('returns "0:59" for 59 seconds', () => {
    expect(formatDuration(59)).toBe('0:59')
  })

  it('returns "1:00" for 60 seconds', () => {
    expect(formatDuration(60)).toBe('1:00')
  })

  it('returns "2:05" for 125 seconds', () => {
    expect(formatDuration(125)).toBe('2:05')
  })

  it('returns "59:59" for 3599 seconds', () => {
    expect(formatDuration(3599)).toBe('59:59')
  })
})

describe('formatDuration — hour+ (Xh Ym)', () => {
  it('returns "1h 0m" for 3600 seconds (hour boundary)', () => {
    expect(formatDuration(3600)).toBe('1h 0m')
  })

  it('returns "1h 1m" for 3661 seconds', () => {
    expect(formatDuration(3661)).toBe('1h 1m')
  })

  it('returns "1h 30m" for 5400 seconds', () => {
    expect(formatDuration(5400)).toBe('1h 30m')
  })
})

describe('formatDuration — edge cases', () => {
  it('returns "0:00" for negative values', () => {
    expect(formatDuration(-1)).toBe('0:00')
  })

  it('returns "0:00" for large negative values', () => {
    expect(formatDuration(-99999)).toBe('0:00')
  })
})
