import { describe, it, expect } from 'vitest'
import { sanitizeReturnTo } from './return-to'

describe('sanitizeReturnTo', () => {
  it('returns the value unchanged when it is a safe app path', () => {
    expect(sanitizeReturnTo('/app/acme-motors/leads?q=juan')).toBe('/app/acme-motors/leads?q=juan')
  })

  it('defaults to / when null', () => {
    expect(sanitizeReturnTo(null)).toBe('/')
  })

  it('defaults to / when undefined', () => {
    expect(sanitizeReturnTo(undefined)).toBe('/')
  })

  it('defaults to / when empty string', () => {
    expect(sanitizeReturnTo('')).toBe('/')
  })

  it('defaults to / when it does not start with a slash', () => {
    expect(sanitizeReturnTo('evil.com/phish')).toBe('/')
  })

  it('defaults to / for a protocol-relative // URL', () => {
    expect(sanitizeReturnTo('//evil.com/phish')).toBe('/')
  })

  it('defaults to / for a backslash-prefixed /\\ URL', () => {
    expect(sanitizeReturnTo('/\\evil.com')).toBe('/')
  })

  it('defaults to / when it targets the API', () => {
    expect(sanitizeReturnTo('/api/v1/clients')).toBe('/')
  })
})
