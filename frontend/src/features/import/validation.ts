/**
 * Row validation for the CSV import flow.
 *
 * isLikelyValidArgentinePhone is a client-side PREVIEW heuristic, not the
 * source of truth. The backend (app/phones/normalization.py normalize_phone,
 * region="AR") does the authoritative validation via libphonenumber when the
 * lead is actually created; rows that pass this heuristic can still be
 * rejected by the API (surfaced as per-row import failures).
 */

import { SKIP_FIELD_KEY } from './mapping'

export function isLikelyValidArgentinePhone(raw: string): boolean {
  if (typeof raw !== 'string') return false
  const trimmed = raw.trim()
  if (!trimmed) return false
  if (!/^[\d+()\- ]+$/.test(trimmed)) return false

  const compact = trimmed.replace(/[()\- ]/g, '')
  if (compact === '' || compact === '+') return false

  if (compact.startsWith('+')) {
    if (!compact.startsWith('+54')) return false
    const digits = compact.slice(1)
    if (compact.startsWith('+549')) return digits.length === 13
    return digits.length === 12
  }

  const digits = compact
  return digits.length >= 10 && digits.length <= 11
}

export type RowInvalidReason = 'missing_name' | 'missing_phone' | 'invalid_phone'

export interface RowValidation {
  valid: boolean
  reason?: RowInvalidReason
}

export function validateLeadCandidate(name: string, phone: string): RowValidation {
  if (!name || !name.trim()) return { valid: false, reason: 'missing_name' }
  if (!phone || !phone.trim()) return { valid: false, reason: 'missing_phone' }
  if (!isLikelyValidArgentinePhone(phone)) return { valid: false, reason: 'invalid_phone' }
  return { valid: true }
}

export interface ImportRow {
  index: number
  name: string
  phone: string
  notes: string | null
  custom_fields: Record<string, string>
  valid: boolean
  reason?: RowInvalidReason
}

/**
 * Builds one ImportRow per CSV data row from the header→field mapping.
 * Unmapped/"No importar" columns and empty cells are ignored. Multiple
 * columns mapped to "notes" are concatenated with a space.
 */
export function buildImportRows(
  headers: string[],
  rows: string[][],
  mapping: Record<string, string>
): ImportRow[] {
  return rows.map((row, index) => {
    let name = ''
    let phone = ''
    let notes = ''
    const custom_fields: Record<string, string> = {}

    headers.forEach((header, colIndex) => {
      const target = mapping[header]
      const value = (row[colIndex] ?? '').trim()
      if (!target || target === SKIP_FIELD_KEY || !value) return

      if (target === 'name') name = value
      else if (target === 'phone') phone = value
      else if (target === 'notes') notes = notes ? `${notes} ${value}` : value
      else custom_fields[target] = value
    })

    const validation = validateLeadCandidate(name, phone)
    return {
      index,
      name,
      phone,
      notes: notes || null,
      custom_fields,
      valid: validation.valid,
      reason: validation.valid ? undefined : validation.reason,
    }
  })
}
