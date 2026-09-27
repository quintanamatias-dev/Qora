import { describe, it, expect } from 'vitest'
import { isLikelyValidArgentinePhone, validateLeadCandidate, buildImportRows } from './validation'

describe('isLikelyValidArgentinePhone', () => {
  it('accepts E.164 Argentine mobile numbers', () => {
    expect(isLikelyValidArgentinePhone('+5491122223333')).toBe(true)
  })

  it('accepts E.164 Argentine fixed-line numbers', () => {
    expect(isLikelyValidArgentinePhone('+541122223333')).toBe(true)
  })

  it('accepts plausible domestic-format numbers', () => {
    expect(isLikelyValidArgentinePhone('01122223333')).toBe(false)
    expect(isLikelyValidArgentinePhone('1122223333')).toBe(false)
  })

  it('rejects numbers with a non-Argentine country code', () => {
    expect(isLikelyValidArgentinePhone('+5215512345678')).toBe(false)
  })

  it('rejects empty, non-numeric, or too-short values', () => {
    expect(isLikelyValidArgentinePhone('')).toBe(false)
    expect(isLikelyValidArgentinePhone('abc')).toBe(false)
    expect(isLikelyValidArgentinePhone('123')).toBe(false)
  })

  // B-001: mirror backend/tests/unit/phones/test_normalization.py so the
  // preview heuristic never accepts what normalize_phone rejects, and never
  // rejects what it accepts.
  it('accepts domestic formats normalize_phone accepts', () => {
    expect(isLikelyValidArgentinePhone('011 15 5555-0101')).toBe(true)
    expect(isLikelyValidArgentinePhone('0341 15 555-0101')).toBe(true)
    expect(isLikelyValidArgentinePhone('02966 15 550101')).toBe(true)
    expect(isLikelyValidArgentinePhone('341155550101')).toBe(true)
    expect(isLikelyValidArgentinePhone('296615550101')).toBe(true)
  })

  it('rejects domestic formats normalize_phone rejects as ambiguous_or_incomplete', () => {
    expect(isLikelyValidArgentinePhone('011 5555-0101')).toBe(false)
    expect(isLikelyValidArgentinePhone('1155550101')).toBe(false)
    expect(isLikelyValidArgentinePhone('5555-0101')).toBe(false)
    expect(isLikelyValidArgentinePhone('15 5555-0101')).toBe(false)
    expect(isLikelyValidArgentinePhone('011 5515-0101')).toBe(false)
    expect(isLikelyValidArgentinePhone('0054 9 11 5555 0101')).toBe(false)
    expect(isLikelyValidArgentinePhone('5491155550101')).toBe(false)
  })
})

describe('validateLeadCandidate', () => {
  it('flags missing name', () => {
    expect(validateLeadCandidate('', '+5491122223333')).toEqual({ valid: false, reason: 'missing_name' })
  })

  it('flags missing phone', () => {
    expect(validateLeadCandidate('Lucia', '')).toEqual({ valid: false, reason: 'missing_phone' })
  })

  it('flags an invalid phone', () => {
    expect(validateLeadCandidate('Lucia', 'not-a-phone')).toEqual({ valid: false, reason: 'invalid_phone' })
  })

  it('accepts a valid candidate', () => {
    expect(validateLeadCandidate('Lucia', '+5491122223333')).toEqual({ valid: true })
  })
})

describe('buildImportRows', () => {
  const headers = ['Nombre', 'Celular', 'Marca', 'Comentarios']
  const mapping = { Nombre: 'name', Celular: 'phone', Marca: 'car_make', Comentarios: 'notes' }

  it('builds a valid row with custom fields from mapped columns', () => {
    const rows = buildImportRows(headers, [['Lucia', '+5491122223333', 'Peugeot', 'Vino de Meta']], mapping)
    expect(rows).toEqual([
      {
        index: 0,
        name: 'Lucia',
        phone: '+5491122223333',
        notes: 'Vino de Meta',
        custom_fields: { car_make: 'Peugeot' },
        valid: true,
        reason: undefined,
      },
    ])
  })

  it('marks a row invalid when phone is missing', () => {
    const rows = buildImportRows(headers, [['Lucia', '', 'Peugeot', '']], mapping)
    expect(rows[0].valid).toBe(false)
    expect(rows[0].reason).toBe('missing_phone')
  })

  it('ignores columns mapped to "skip"', () => {
    const rows = buildImportRows(
      headers,
      [['Lucia', '+5491122223333', 'Peugeot', '']],
      { ...mapping, Marca: 'skip' }
    )
    expect(rows[0].custom_fields).toEqual({})
  })

  it('concatenates multiple columns mapped to notes', () => {
    const multiHeaders = ['Nombre', 'Celular', 'Nota A', 'Nota B']
    const multiMapping = { Nombre: 'name', Celular: 'phone', 'Nota A': 'notes', 'Nota B': 'notes' }
    const rows = buildImportRows(
      multiHeaders,
      [['Lucia', '+5491122223333', 'primera', 'segunda']],
      multiMapping
    )
    expect(rows[0].notes).toBe('primera segunda')
  })
})
